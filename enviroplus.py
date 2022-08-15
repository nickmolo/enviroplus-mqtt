#!/usr/bin/env python3
"""
Run mqtt broker on localhost: sudo apt-get install mosquitto mosquitto-clients

Example run: python3 mqtt-all.py --broker 192.168.1.164 --topic enviro --username xxx --password xxxx
"""

# import argparse
import configparser
import ssl
import time
from runpy import run_path

import ST7735
from bme280 import BME280
from enviroplus import gas
from pms5003 import PMS5003, ReadTimeoutError, SerialTimeoutError

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559

    ltr559 = LTR559()
except ImportError:
    import ltr559

import json
from subprocess import PIPE, Popen, check_output

import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from fonts.ttf import RobotoMedium as UserFont
# from PIL import Image, ImageDraw, ImageFont

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus


# mqtt callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("connected OK")
    else:
        print("Bad connection Returned code=", rc)


def on_publish(client, userdata, mid):
    print("mid: " + str(mid))


# Read values from BME280 and return as dict
def read_bme280(bme280):
    # Compensation factor for temperature
    comp_factor = 2.25
    values = {}
    cpu_temp = get_cpu_temperature()
    raw_temp = bme280.get_temperature()  # float
    comp_temp = raw_temp - ((cpu_temp - raw_temp) / comp_factor)
    values["temperature"] = int(comp_temp)
    values["pressure"] = round(
        int(bme280.get_pressure() * 100), -1
    )  # round to nearest 10
    values["humidity"] = int(bme280.get_humidity())
    data = gas.read_all()
    values["oxidised"] = int(data.oxidising / 1000)
    values["reduced"] = int(data.reducing / 1000)
    values["nh3"] = int(data.nh3 / 1000)
    values["lux"] = int(ltr559.get_lux())
    return values


# Read values PMS5003 and return as dict
def read_pms5003(pms5003):
    values = {}
    try:
        pm_values = pms5003.read()  # int
        values["pm1"] = pm_values.pm_ug_per_m3(1)
        values["pm25"] = pm_values.pm_ug_per_m3(2.5)
        values["pm10"] = pm_values.pm_ug_per_m3(10)
    except ReadTimeoutError:
        pms5003.reset()
        pm_values = pms5003.read()
        values["pm1"] = pm_values.pm_ug_per_m3(1)
        values["pm25"] = pm_values.pm_ug_per_m3(2.5)
        values["pm10"] = pm_values.pm_ug_per_m3(10)
    return values


# Get CPU temperature to use for compensation
def get_cpu_temperature():
    process = Popen(["vcgencmd", "measure_temp"], stdout=PIPE, universal_newlines=True)
    output, _error = process.communicate()
    return float(output[output.index("=") + 1 : output.rindex("'")])


# Get Raspberry Pi serial number to use as ID
def get_serial_number():
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if line[0:6] == "Serial":
                return line.split(":")[1].strip()


# Check for Wi-Fi connection
def check_wifi():
    if check_output(["hostname", "-I"]):
        return True
    else:
        return False


# Display Raspberry Pi serial and Wi-Fi status on LCD
def display_status(disp, mqtt_broker):
    # Width and height to calculate text position
    WIDTH = disp.width
    HEIGHT = disp.height
    # Text settings
    font_size = 12
    font = ImageFont.truetype(UserFont, font_size)

    wifi_status = "connected" if check_wifi() else "disconnected"
    text_colour = (255, 255, 255)
    back_colour = (0, 170, 170) if check_wifi() else (85, 15, 15)
    device_serial_number = get_serial_number()
    message = "{}\nWi-Fi: {}\nmqtt-broker: {}".format(
        device_serial_number, wifi_status, mqtt_broker
    )
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    size_x, size_y = draw.textsize(message, font)
    x = (WIDTH - size_x) / 2
    y = (HEIGHT / 2) - (size_y / 2)
    draw.rectangle((0, 0, 160, 80), back_colour)
    draw.text((x, y), message, font=font, fill=text_colour)
    disp.display(img)


def run_mqtt(config, device_serial_number):
    broker = config.get("mqtt", "broker_ip")
    port = int(config.get("mqtt", "broker_port"))
    topic = config.get("mqtt", "topic")
    interval = int(config.get("mqtt", "read_interval"))
    tls = config.getboolean("mqtt", "tls_mode")
    username = config.get("mqtt", "Username", fallback=None)
    password = config.get("mqtt", "password", fallback=None)

    HAS_PMS = config.getboolean("device", "has_pms")

    device_id = "raspi-" + device_serial_number
    mqtt_client = mqtt.Client(client_id=device_id)
    if username and password:
        mqtt_client.username_pw_set(username, password)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_publish = on_publish

    if tls is True:
        mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLSv1_2)

    if username is not None:
        mqtt_client.username_pw_set(username, password=password)

    mqtt_client.connect(broker, port=port)

    bus = SMBus(1)

    # Create BME280 instance
    bme280 = BME280(i2c_dev=bus)

    # Create LCD instance
    disp = ST7735.ST7735(
        port=0, cs=1, dc=9, backlight=12, rotation=270, spi_speed_hz=10000000
    )

    # Initialize display
    disp.begin()

    # Try to create PMS5003 instance
    if HAS_PMS:
        try:
            pms5003 = PMS5003()
            _ = pms5003.read()
            print("PMS5003 sensor is connected")
        except SerialTimeoutError:
            print("No PMS5003 sensor connected")

    # Display Raspberry Pi serial and Wi-Fi status
    print("RPi serial: {}".format(device_serial_number))
    print("Wi-Fi: {}\n".format("connected" if check_wifi() else "disconnected"))
    print("MQTT broker IP: {}".format(broker))

    # Main loop to read data, display, and send over mqtt
    mqtt_client.loop_start()
    while True:
        try:
            values = read_bme280(bme280)
            if HAS_PMS:
                pms_values = read_pms5003(pms5003)
                values.update(pms_values)
            values["serial"] = device_serial_number
            print(values)
            mqtt_client.publish(topic, json.dumps(values))
            display_status(disp, broker)
            time.sleep(interval)
        except Exception as e:
            print(e)


def main():

    config = configparser.ConfigParser()
    config.read("config.ini")

    # Raspberry Pi ID
    # device_serial_number = get_serial_number()
    device_serial_number = "1234567890"
    device_id = "raspi-" + device_serial_number

    print(
        f"""mqtt-all.py - Reads Enviro plus data and sends over mqtt.

    broker: {config.get("mqtt", "broker_ip")}
    client_id: {device_id}
    port: {config.get("mqtt", "broker_port")}
    topic: {config.get("mqtt", "topic")}
    tls: {config.get("mqtt", "tls_mode")}
    username: {config.get("mqtt", "Username", fallback=None)}
    password: {config.get("mqtt", "password", fallback=None)}

    name: {config.get("device", "name")}
    sw_version: {config.get("device", "sw_version")}
    model: {config.get("device", "model")}
    manufacturer: {config.get("device", "manufacturer")}
    has_pms: {config.getboolean("device", "has_pms")}


    Press Ctrl+C to exit!

    """
    )



    run_mqtt(config, device_serial_number)


if __name__ == "__main__":
    main()
