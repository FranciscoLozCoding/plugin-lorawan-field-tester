import os
import sys
import time
import logging
import json
import base64
import binascii
import math
import argparse
from waggle.plugin import Plugin
from paho.mqtt.client import Client

class Config:
    def __init__(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--publish",
            action="store_true",
            default=False,
            help="enable publish mode where field test measurements will be broadcast to Beehive",
        )
        parser.add_argument(
            "--logging_level",
            default=os.getenv("LOGGING_LEVEL", logging.DEBUG),
            help="Set the logging level (10=DEBUG, 20=INFO, 30=WARN, 40=ERROR, 50=CRITICAL)"
        )
        parser.add_argument(
            "--parser_type",
            default=os.getenv("PARSER_TYPE", 'ChirpStack_v3+'),
            help="Set the parser type (TheThingsStack_v3, ChirpStack_v3+)"
        )
        parser.add_argument(
            "--mqtt-server-ip",
            default=os.getenv("MQTT_SERVER_HOST", "wes-rabbitmq"),
            help="MQTT server IP address",
        )
        parser.add_argument(
            "--mqtt-server-port",
            default=os.getenv("MQTT_SERVER_PORT", "1883"),
            type=int,
            help="MQTT server port",
        )
        parser.add_argument(
            "--mqtt-subscribe-topic",
            default=None,
            help="MQTT topic to subscribe to. It will be auto-generated based on parser_type and device-devui but advanced users can override it",
        )
        parser.add_argument(
            "--device-devui",
            help="Field Tester Device DevEUI (MUST be registered in Network server)",
        )

        # Parse command-line arguments
        self._args = parser.parse_args()

        #fail service if deveui is not passed
        if not self._args.device_devui:
            logging.error("[CONFIG] device-devui must be passed, see --help or plugin documentation")
            sys.exit(1)
        
        # add auto-generated subscribe topic
        if not self._args.mqtt_subscribe_topic:
            if self._args.parser_type == 'TheThingsStack_v3':
                self._args.mqtt_subscribe_topic = f"v3/+/devices/{self._args.device_devui}/up"
            elif self._args.parser_type == 'ChirpStack_v3+':
                # chirpstack topic template is here https://www.chirpstack.io/docs/chirpstack/configuration.html in [integration.mqtt] section
                # chirpstack template: application/{{application_id}}/device/{{dev_eui}}/event/{{event}}
                self._args.mqtt_subscribe_topic = f"application/+/device/{self._args.device_devui}/event/up"
            else:
                logging.error("[CONFIG] Unknown parser type %s" % self._args.parser_type)
                sys.exit(1)

    def get(self, name, default=None):
        # Convert config key to argument format
        arg_name = name.replace('.', '_').replace('-', '_')
        return getattr(self._args, arg_name, default)

class MQTTClient(Client):

    MQTTv31 = 3
    MQTTv311 = 4
    MQTTv5 = 5

    def __init__(self, broker="localhost", port=1883, username=None, password=None, userdata=None):

        def connect_callback_default(client, userdata, flags, rc):
            if rc == 0:
                logging.debug("[MQTT] Connected to MQTT Broker!")

        def subscribe_callback_default(client, userdata, mid, granted_qos):
            logging.debug("[MQTT] Subscribed")

        def disconnect_callback_default(client, userdata, rc):
            logging.debug("[MQTT] Disconnected from MQTT Broker!")

        Client.__init__(self, 
            client_id = "",
            clean_session = None,
            userdata = userdata,
            protocol = self.MQTTv311,
            transport = "tcp",
            reconnect_on_failure = True
        )

        self.on_connect = connect_callback_default
        self.on_disconnect = disconnect_callback_default
        self.on_subscribe = subscribe_callback_default
        if username and password:
            self.username_pw_set(username, password)
        self.connect(broker, port)

    def start(self):
        self.loop_start()

def publish(measurement: dict, timestamp = time.time(), metadata = {}):
    if measurement["value"] is not None: #avoid NULLs
        with Plugin() as plugin: #publish lorawan data
            try:
                plugin.publish(measurement["name"], measurement["value"], timestamp=timestamp, meta=metadata)
                # If the function succeeds, log a success message
                logging.info(f'[PUBLISH] {measurement["name"]} published')
            except Exception as e:
                # If an exception is raised, log an error message
                logging.error(f'[PUBLISH] measurement {measurement["name"]} did not publish encountered an error: {str(e)}')

EARTH_RADIUS = 6371000

def degreesToRadians(degrees):
    return degrees * (math.pi / 180)

def radiansToDegrees(radians):
    return radians * (180 / math.pi)

def angularDistance(location1, location2):
    location1_latitude_radians = degreesToRadians(location1.get('latitude'))
    location2_latitude_radians = degreesToRadians(location2.get('latitude'))
    return math.acos(
        math.sin(location1_latitude_radians) * math.sin(location2_latitude_radians) +
        math.cos(location1_latitude_radians) * math.cos(location2_latitude_radians) * 
            math.cos(degreesToRadians(abs(location1.get('longitude') - location2.get('longitude'))))
    )

def circleDistance(location1, location2):
    return EARTH_RADIUS * angularDistance(location1, location2);

def constrain(value, lower, upper):
    return min(upper, max(lower, value))

MAX_DISTANCE=1e6
MIN_DISTANCE=0
MAX_RSSI=200
MIN_RSSI=-200

def process(data, port, sequence_id, gateways, config):

    output = {}

    # Gather data
    output['hdop'] = data[8]/10
    output['sats'] = data[9]
    output['has_gps'] = (output['hdop'] <= 2) and (output['sats'] >= 5)
    
    # We only add GPS data and distances information if there is valid GPS data
    if output['has_gps']:
        lonSign = -1 if ((data[0]>>7) & 0x01) else 1
        latSign = -1 if ((data[0]>>6) & 0x01) else 1
        encLat = ((data[0] & 0x3f)<<17) + (data[1]<<9) + (data[2]<<1) + (data[3]>>7)
        encLon = ((data[3] & 0x7f)<<16) + (data[4]<<8) + data[5]
        output['latitude'] = latSign * (encLat * 108 + 53) / 10000000
        output['longitude'] = lonSign * (encLon * 215 + 107) / 10000000
        output['altitude'] = ((data[6]<<8) + data[7]) - 1000
        output['accuracy'] = (output['hdop'] * 5 + 5) / 10

    # Build gateway data
    output['num_gateways'] = len(gateways)
    output['min_distance'] = MAX_DISTANCE if output['has_gps'] else MIN_DISTANCE
    output['max_distance'] = MIN_DISTANCE
    output['min_rssi'] = MAX_RSSI
    output['max_rssi'] = MIN_RSSI
    for gateway in gateways:

        output['min_rssi'] = min(output['min_rssi'], gateway.get('rssi', MAX_RSSI))
        output['max_rssi'] = max(output['max_rssi'], gateway.get('rssi', MIN_RSSI))

        if output['has_gps']:
            loc = gateway.get('location', {})
            lat = loc.get('latitude')
            lon = loc.get('longitude')
            if lat is not None and lon is not None:
                distance = int(circleDistance(output, loc)) 
                output['min_distance'] = min(output['min_distance'], distance)
                output['max_distance'] = max(output['max_distance'], distance)

    # Publish data to beehive
    if config.get('publish'):
        publish({'name': 'gps.hdop', 'value': output.get('hdop', None)})
        publish({'name': 'gps.sats', 'value': output.get('sats', None)})
        publish({'name': 'gps.latitude', 'value': output.get('latitude', None)})
        publish({'name': 'gps.longitude', 'value': output.get('longitude', None)})
        publish({'name': 'gps.altitude', 'value': output.get('altitude', None)})
        publish({'name': 'gps.accuracy', 'value': output.get('accuracy', None)})
        publish({'name': 'gateway.min_distance', 'value': output.get('min_distance', None)})
        publish({'name': 'gateway.max_distance', 'value': output.get('max_distance', None)})
        publish({'name': 'gateway.min_rssi', 'value': output.get('min_rssi', None)})
        publish({'name': 'gateway.max_rssi', 'value': output.get('max_rssi', None)})
        publish({'name': 'gateway.num_gateways', 'value': output.get('num_gateways', None)})

    # Build response buffer
    if 1 == port:
        min_distance = constrain(int(round(output['min_distance'] / 250.0)), 1, 128) if output['has_gps'] else 0
        max_distance = constrain(int(round(output['max_distance'] / 250.0)), 1, 128) if output['has_gps'] else 0
        output['buffer'] = [
            sequence_id % 256,
            int(output['min_rssi'] + 200) % 256,
            int(output['max_rssi'] + 200) % 256,
            min_distance,
            max_distance,
            output['num_gateways'] % 256
        ]
    elif 11 == port:
        min_distance = constrain(int(round(output['min_distance'] / 10.0)), 1, 65535) if output['has_gps'] else 0
        max_distance = constrain(int(round(output['max_distance'] / 10.0)), 1, 65535) if output['has_gps'] else 0
        logging.debug("[TTS3] max_distance: %d" % max_distance)
        output['buffer'] = [
            sequence_id % 256,
            int(output['min_rssi'] + 200) % 256,
            int(output['max_rssi'] + 200) % 256,
            int(min_distance / 256) % 256, min_distance % 256,
            int(max_distance / 256) % 256, max_distance % 256,
            output['num_gateways'] % 256
        ]

    return output

def parser_tts3(config, topic, payload):

    # Parse payload
    try:
        payload = json.loads(payload)
    except:
        logging.error("[TTS3] Decoding message has failed")
        return [False, False]

    # Check structure
    if 'uplink_message' not in payload:
        return [False, False]

    # Get port
    port = payload['uplink_message']['f_port']
    if port != 1 and port != 11:
        return [False, False]

    # Get attributes
    sequence_id = payload['uplink_message']['f_cnt']
    gateways = payload['uplink_message']['rx_metadata']
    data = base64.b64decode((payload['uplink_message']['frm_payload']))
    logging.debug("[TTS3] Received: 0x%s" % binascii.hexlify(data).decode('utf-8'))
    
    # Process the data
    data = process(data, port, sequence_id, gateways, config)
    if not data:
        return [False, False]
    logging.debug("[TTS3] Processed: %s" % data)

    # Get topic
    topic = topic.replace('/up', '/down/replace')

    # Build downlink
    downlink = {
        'downlinks': [{
            'f_port': port + 1,
            'frm_payload': base64.b64encode(bytes(data['buffer'])).decode('utf-8'),
            'priority': 'HIGH'
        }]
    }

    # Return topic and payload
    return [topic, json.dumps(downlink)]

def parser_cs34(config, topic, payload):

    # Parse payload
    try:
        payload = json.loads(payload)
    except:
        logging.error("[CS34] Decoding message has failed")
        return [False, False]

    # Chirpstack version
    version = 4 if 'deviceInfo' in payload else 3
    logging.debug("[CS34] ChirpStack version %d payload" % version)

    # Get port
    port = payload.get('fPort', 0)
    if port != 1 and port != 11:
        return [False, False]

    # Get attributes
    sequence_id = payload['fCnt']
    gateways = payload['rxInfo']
    data = base64.b64decode((payload['data']))
    logging.debug("[CS34] Received: 0x%s" % binascii.hexlify(data).decode('utf-8'))
    
    # Process the data
    data = process(data, port, sequence_id, gateways, config)
    if not data:
        return [False, False]
    logging.debug("[CS34] Processed: %s" % data)

    # Get topic
    topic = topic.replace('/event/up', '/command/down')

    # Build downlink
    downlink = {    
        'confirmed': False,
        'fPort': port + 1,
        'data': base64.b64encode(bytes(data['buffer'])).decode('utf-8')
    }
    if version == 4:
        downlink['devEui'] = payload['deviceInfo']['devEui']

    # Return topic and payload
    return [topic, json.dumps(downlink)]

def main():

    # load configuration
    config = Config()

    # set logging level based on settings (10=DEBUG, 20=INFO, ...)
    level=config.get("logging.level")
    logging.basicConfig(format='[%(asctime)s] %(message)s', level=level)
    logging.debug("[MAIN] Setting logging level to %d" % level)

    # configure parser
    parser = False
    parser_type = config.get('parser.type')
    if parser_type == 'TheThingsStack_v3':
        parser = parser_tts3
        logging.debug("[MAIN] Using The Things Stack v3 parser")
    elif parser_type == 'ChirpStack_v3+':
        parser = parser_cs34
        logging.debug("[MAIN] Using ChirpStack v3+ parser")
    else:
        logging.debug("[MAIN] Unknown parser type %s" % parser_type)
        sys.exit(1)

    def mqtt_on_message(client, userdata, msg):
        payload = msg.payload.decode('utf-8')
        logging.debug("[MQTT] Received for %s" % msg.topic)
        (topic, payload) = parser(config, msg.topic, payload)
        if topic:
            logging.debug("[MQTT] Topic: %s" % topic)
            logging.debug("[MQTT] Payload: %s" % payload)
            mqtt_client.publish(topic, payload)


    mqtt_client = MQTTClient(
        config.get('mqtt.server.ip'), 
        int(config.get('mqtt.server.port'))
    )
    mqtt_client.on_message = mqtt_on_message
    mqtt_client.subscribe(config.get('mqtt.subscribe.topic'))
    mqtt_client.start()

    while (True):
        time.sleep(0.01) 

if (__name__ == '__main__'): 
    main()