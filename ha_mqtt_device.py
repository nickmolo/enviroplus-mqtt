import json
import logging
import os
import yaml

import paho.mqtt.client as mqtt


DISCOVERY_PREFIX = "homeassistant"


logger = logging.getLogger(__name__)
if "DEBUG" in os.environ:
    logger.setLevel(logging.DEBUG)


class Device(dict):
    def __init__(self, identifiers, name, sw_version, model, manufacturer):
        super().__init__()

        self.name = name

        self["identifiers"] = identifiers
        self["name"] = name
        self["sw_version"] = sw_version
        self["model"] = model
        self["manufacturer"] = manufacturer

    @staticmethod
    def from_config(config_yaml_path):
        with open(config_yaml_path) as file:
            device_config = yaml.safe_load(file)
            device = Device(**device_config)
            return device


class Component:
    def __init__(self, name):
        self.component = name


class Sensor(Component):
    def __init__(
        self,
        client: mqtt.Client,
        friendly_name,
        parent_device,
        unit_of_measurement,
        state_topic,
        device_class=None,
        value_template=None,
        icon=None,
    ):
        super().__init__("sensor")

        self.client = client
        self.friendly_name = friendly_name
        self.parent_device = parent_device
        self.unit_of_measurement = unit_of_measurement
        self.device_class = device_class
        self.state_topic = state_topic
        self.icon = icon
        self.name = f"{self.parent_device['name']} {self.friendly_name}"
        self.unique_id = f"{self.parent_device['identifiers'][0]}_{self.device_class}"
        self.value_template = value_template
        self.object_id = self.friendly_name.replace(" ", "_").lower()

        self._send_config()

    def _send_config(self):
        _config = {
            "device": self.parent_device,
            "name": self.name,
            "state_class": "measurement",
            "state_topic": self.state_topic,
            "unique_id": self.unique_id,
            "unit_of_measurement": self.unit_of_measurement,
        }

        if self.device_class:
            _config["device_class"] = self.device_class

        if self.icon:
            _config["icon"] = self.icon

        if self.value_template:
            _config["value_template"] = f"{{{{ value_json.{self.value_template} }}}}"

        self.client.publish(
            f"{DISCOVERY_PREFIX}/{self.component}/{self.parent_device['identifiers'][0]}/{self.object_id}/config",
            json.dumps(_config),
            retain=True,
        ).wait_for_publish()


class Tracker:
    def __init__(self, client: mqtt.Client, name):
        self.client = client
        self.name = name
        self.unique_id = self.name.replace(" ", "_").lower()
        self.topic = f"{DISCOVERY_PREFIX}/device_tracker/{self.unique_id}"
        self._send_config()

    def _send_config(self):
        _config = {
            "~": self.topic,
            "name": self.name,
            "unique_id": self.unique_id,
            "stat_t": "~/state",
            "json_attr_t": "~/attributes",
            "payload_home": "home",
            "payload_not_home": "not_home",
        }
        self.client.publish(f"{self.topic}/config", json.dumps(_config))

    def send(self, latitude, longitude, gps_accuracy):
        _payload = {
            "latitude": latitude,
            "longitude": longitude,
            "gps_accuracy": gps_accuracy,
        }
        self.client.publish(f"{self.topic}/attributes", json.dumps(_payload))


class Binary:
    def __init__(self, client: mqtt.Client, name, icon):
        self.client = client
        self.name = name
        self.unique_id = self.name.replace(" ", "_").lower()
        self.topic = f"{DISCOVERY_PREFIX}/binary_sensor/{self.unique_id}"
        self.icon = icon
        self._send_config()

    def _send_config(self):
        _config = {
            "~": self.topic,
            "name": self.name,
            "unique_id": self.unique_id,
            "stat_t": "~/state",
            "icon": self.icon,
        }
        self.client.publish(f"{self.topic}/config", json.dumps(_config))

    def send(self, value):
        self.client.publish(f"{self.topic}/state", str(value))
