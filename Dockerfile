FROM python:3.12.6-alpine3.20

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY ./app .

ENTRYPOINT ["python3" , "server.py"]
