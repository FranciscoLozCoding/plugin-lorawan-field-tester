## About The Plugin

The Field Tester Server is a plugin that processes and forwards coverage data from the [RAK10701](https://store.rakwireless.com/products/field-tester-for-lorawan-rak10701) Field Tester or compatible LoRaWAN devices. It connects directly to your LoRa Network Server (e.g. Chirpstack) via MQTT, parses incoming uplink messages, calculates key metrics such as distance, and generates the appropriate downlink message to send back to the device through MQTT. It also optionally publishes results to the Beehive.

## Using the code

Before the plugin can work...
1) Register your Field Tester device in your LoRa Network Server (e.g. Chirpstack)
2) Get the Field Tester device to join the network.
2) Finally, make sure the `device-devui` is passed as an argument — this is required to identify which device to listen for in MQTT topics. Based on the selected `parser_type`, the correct MQTT topic is automatically constructed.

## Arguments

**--device-devui**: **Required.** The DevEUI of the Field Tester device. This must match a registered device in your LoRa Network Server (e.g. Chirpstack). Used to construct the correct MQTT subscription topic.

**--publish**: Enable publish mode where processed measurements are broadcast to Beehive. Using this flag will make the measurements viewable in SAGE portal.

**--logging_level**: Set the logging level (`10=DEBUG`, `20=INFO`, `30=WARN`, `40=ERROR`, `50=CRITICAL`). Defaults to `DEBUG`.

**--parser_type**: Specify the LoRa Network Server parser to use. Options are `TheThingsStack_v3` or `ChirpStack_v3+`. Defaults to `ChirpStack_v3+`.

**--mqtt-server-ip**: MQTT server IP address.

**--mqtt-server-port**: MQTT server port.

**--mqtt-subscribe-topic**: MQTT topic to subscribe to. The default is auto-generated based on the `parser_type` and `device-devui`, but advanced users can change it using this argument.
