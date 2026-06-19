# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import json
from typing import Literal

import paho.mqtt.client as mqtt
import paho.mqtt.properties as mqtt_properties

from ..utils.logger import logger
from ..utils.string import sluggify
from .models import DetectedSoundType
from .package import APP_VERSION

# Type alias re-exported for callers that build entity lists.
# Each element: (ha_domain, entity_slug, payload_dict)
# e.g. ("sensor", "wakeword", {"name": "Wakeword", ...})
HAEntity = tuple[str, str, dict]


class MQTTClient:  # pylint: disable=too-many-public-methods
  # pylint: disable=too-many-arguments
  def __init__(
    self,
    broker: str,
    port: int,
    *,
    topic: str,
    node_id: str,
    username: str | None = None,
    password: str | None = None,
    discovery_prefix: str | None = None,
  ):
    self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"oremi-device-{node_id}")
    self.broker = broker
    self.port = port
    self.topic = topic
    self.node_id = node_id
    self.username = username
    self.password = password
    self.discovery_prefix = discovery_prefix

  # ── Helpers for building HA entity payloads outside this class ──────────────

  def get_node_id(self) -> str:
    """Return the slugified node identifier used in HA discovery topics."""
    return sluggify(f"oremi-device-{self.node_id}")

  def get_device_descriptor(self) -> dict:
    """
    Return the HA device descriptor dict shared across all entities.

    See https://www.home-assistant.io/integrations/mqtt/
    """
    node_id = self.get_node_id()

    return {
      "identifiers": [node_id],
      "name": f"Oremi Device ({self.node_id})",
      "manufacturer": "Sébastien Demanou",
      "model": "Oremi Device",
      "sw_version": APP_VERSION,
      "configuration_url": "https://gitlab.com/demsking/oremi-device",
    }

  def get_microphone_command_topic(self) -> str:
    """Return the instance-scoped MQTT topic for microphone select commands.

    Using the node_id ensures that when multiple instances share the same
    base topic, each instance only reacts to commands addressed to it.
    """
    return f"{self.topic}/device/{self.node_id}/microphone/set"

  def get_mute_command_topic(self) -> str:
    """Return the instance-scoped topic for microphone mute commands."""
    return f"{self.topic}/device/{self.node_id}/microphone/mute/set"

  def get_mute_state_topic(self) -> str:
    """Return the instance-scoped topic for microphone mute state."""
    return f"{self.topic}/device/{self.node_id}/microphone/mute/state"

  def get_speaker_command_topic(self) -> str:
    """Return the instance-scoped topic for speaker selection commands."""
    return f"{self.topic}/device/{self.node_id}/speaker/set"

  def get_speaker_state_topic(self) -> str:
    """Return the instance-scoped topic for the selected speaker."""
    return f"{self.topic}/device/{self.node_id}/speaker/state"

  def get_speaker_mute_cmd_topic(self) -> str:
    """Return the instance-scoped topic for speaker mute commands."""
    return f"{self.topic}/device/{self.node_id}/speaker/mute/set"

  def get_speaker_mute_state_topic(self) -> str:
    """Return the instance-scoped topic for speaker mute state."""
    return f"{self.topic}/device/{self.node_id}/speaker/mute/state"

  def get_speaker_volume_cmd_topic(self) -> str:
    """Return the instance-scoped topic for speaker volume commands."""
    return f"{self.topic}/device/{self.node_id}/speaker/volume/set"

  def get_speaker_volume_state_topic(self) -> str:
    """Return the instance-scoped topic for speaker volume state."""
    return f"{self.topic}/device/{self.node_id}/speaker/volume/state"

  def get_language_command_topic(self) -> str:
    """Return the instance-scoped MQTT topic for language-select commands."""
    return f"{self.topic}/device/{self.node_id}/language/set"

  def get_language_state_topic(self) -> str:
    """Return the instance-scoped MQTT topic for the current language state."""
    return f"{self.topic}/device/{self.node_id}/language/state"

  def get_switch_command_topic(self) -> str:
    """Return the instance-scoped MQTT topic for the enable/disable switch."""
    return f"{self.topic}/device/{self.node_id}/switch/set"

  def get_switch_state_topic(self) -> str:
    """Return the instance-scoped MQTT topic for the switch state."""
    return f"{self.topic}/device/{self.node_id}/switch/state"

  def connect(self) -> None:
    if self.username:
      self.client.username_pw_set(username=self.username, password=self.password)

    self.client.connect(self.broker, self.port, keepalive=0)
    self.client.loop_start()

  def publish(
    self,
    topic: DetectedSoundType | str,
    message: str,
    *,
    qos: int = 0,
    props: mqtt_properties.Properties | None = None,
    retain: bool = False,
  ) -> None:
    logger.debug(f"Publishing #{self.topic}/{topic}: {message} with retain {retain}")
    self.client.publish(f"{self.topic}/{topic}", message, qos=qos, retain=retain, properties=props)

  def publish_discovery_configs(
    self,
    input_devices: list[str],
    current_device: str,
    entities: list["HAEntity"] | None = None,
    enabled: bool = True,
    microphone_muted: bool = False,
    output_devices: list[str] | None = None,
    current_output: str = "",
    speaker_muted: bool = False,
    speaker_volume: float = 1.0,
    current_language: str = "fr",
    supported_languages: list[str] | None = None,
  ) -> None:
    """Publish Home Assistant MQTT discovery configs.

    Publishes device-level entities (microphone select, language select,
    enable/disable switch) and any additional entities supplied by components
    via their ``ha_entities()`` hook.

    Args:
      input_devices: Available input device names for the HA select entity.
      current_device: Currently active input device name.
      entities: Optional list of ``(ha_domain, entity_slug, payload)`` tuples
        collected from active components. Each payload should already contain
        the ``"device"`` key.
      enabled: Whether the device is currently enabled (switch initial state).
      microphone_muted: Whether microphone audio capture is currently muted.
      output_devices: Available speaker output names for the HA select entity.
      current_output: Currently selected speaker output name.
      speaker_muted: Whether speaker playback is currently muted.
      speaker_volume: Current speaker gain, between 0.0 and 1.0.
      current_language: The currently active language code (e.g. ``'fr'``).
      supported_languages: List of language codes to present in the HA select.
        Defaults to ``['fr', 'en']`` when not provided.
    """
    if not self.discovery_prefix:
      return

    node_id = self.get_node_id()
    device = self.get_device_descriptor()

    # ── Component-provided entities ──────────────────────────────────────────
    for ha_domain, entity_slug, payload in entities or []:
      discovery_topic = f"{self.discovery_prefix}/{ha_domain}/{node_id}/{entity_slug}/config"

      logger.debug(f"Publishing HA entity discovery: {discovery_topic}")
      self.client.publish(discovery_topic, json.dumps(payload), retain=True)

    # ── Device-level: language select ────────────────────────────────────────
    # See https://www.home-assistant.io/integrations/select.mqtt/
    languages = supported_languages or ["fr", "en"]
    language_payload = {
      "name": "Language",
      "unique_id": f"{node_id}_language",
      "state_topic": self.get_language_state_topic(),
      "command_topic": self.get_language_command_topic(),
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "options": languages,
      "icon": "mdi:translate",
      "device": device,
    }

    language_topic = f"{self.discovery_prefix}/select/{node_id}/language/config"
    self.client.publish(language_topic, json.dumps(language_payload), retain=True)

    # Publish the current language state
    self.client.publish(self.get_language_state_topic(), current_language, retain=True)

    # ── Device-level: enable/disable switch ──────────────────────────────────
    # See https://www.home-assistant.io/integrations/switch.mqtt/
    switch_payload = {
      "name": "Enabled",
      "unique_id": f"{node_id}_enabled",
      "state_topic": self.get_switch_state_topic(),
      "command_topic": self.get_switch_command_topic(),
      "payload_on": "ON",
      "payload_off": "OFF",
      "state_on": "ON",
      "state_off": "OFF",
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:ear-hearing",
      "device": device,
    }

    switch_topic = f"{self.discovery_prefix}/switch/{node_id}/enabled/config"
    self.client.publish(switch_topic, json.dumps(switch_payload), retain=True)

    # Publish initial switch state
    self.client.publish(self.get_switch_state_topic(), "ON" if enabled else "OFF", retain=True)

    # ── Device-level: microphone mute switch ─────────────────────────────────
    mute_payload = {
      "name": "Microphone muted",
      "unique_id": f"{node_id}_microphone_muted",
      "state_topic": self.get_mute_state_topic(),
      "command_topic": self.get_mute_command_topic(),
      "payload_on": "ON",
      "payload_off": "OFF",
      "state_on": "ON",
      "state_off": "OFF",
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:microphone-off",
      "device": device,
    }

    mute_topic = f"{self.discovery_prefix}/switch/{node_id}/microphone_muted/config"
    self.client.publish(mute_topic, json.dumps(mute_payload), retain=True)
    self.set_mute_state(microphone_muted)

    # ── Device-level: microphone select ─────────────────────────────────────
    # See https://www.home-assistant.io/integrations/select.mqtt/
    select_payload = {
      "name": "Microphone Device",
      "unique_id": f"{node_id}_microphone_device",
      "state_topic": f"{self.topic}/microphone/state",
      "command_topic": self.get_microphone_command_topic(),
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "options": input_devices,
      "icon": "mdi:microphone",
      "device": device,
    }

    select_topic = f"{self.discovery_prefix}/select/{node_id}/microphone_device/config"

    logger.info(f"Publishing MQTT Discovery configurations to {self.discovery_prefix}...")
    self.client.publish(select_topic, json.dumps(select_payload), retain=True)

    # Publish currently active device state
    self.publish("microphone/state", current_device, retain=True)

    # ── Device-level: speaker output select ──────────────────────────────────
    speaker_payload = {
      "name": "Speaker Device",
      "unique_id": f"{node_id}_speaker_device",
      "state_topic": self.get_speaker_state_topic(),
      "command_topic": self.get_speaker_command_topic(),
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "options": output_devices or [],
      "icon": "mdi:speaker",
      "device": device,
    }
    speaker_topic = f"{self.discovery_prefix}/select/{node_id}/speaker_device/config"
    self.client.publish(speaker_topic, json.dumps(speaker_payload), retain=True)
    self.set_speaker_state(current_output)

    # ── Device-level: speaker mute switch ────────────────────────────────────
    speaker_mute_payload = {
      "name": "Speaker muted",
      "unique_id": f"{node_id}_speaker_muted",
      "state_topic": self.get_speaker_mute_state_topic(),
      "command_topic": self.get_speaker_mute_cmd_topic(),
      "payload_on": "ON",
      "payload_off": "OFF",
      "state_on": "ON",
      "state_off": "OFF",
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:volume-off",
      "device": device,
    }
    speaker_mute_topic = f"{self.discovery_prefix}/switch/{node_id}/speaker_muted/config"
    self.client.publish(speaker_mute_topic, json.dumps(speaker_mute_payload), retain=True)
    self.set_speaker_mute_state(speaker_muted)

    # ── Device-level: speaker volume number ──────────────────────────────────
    speaker_volume_payload = {
      "name": "Speaker volume",
      "unique_id": f"{node_id}_speaker_volume",
      "state_topic": self.get_speaker_volume_state_topic(),
      "command_topic": self.get_speaker_volume_cmd_topic(),
      "availability_topic": f"{self.topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "min": 0,
      "max": 100,
      "step": 1,
      "mode": "slider",
      "unit_of_measurement": "%",
      "icon": "mdi:volume-high",
      "device": device,
    }
    speaker_volume_topic = f"{self.discovery_prefix}/number/{node_id}/speaker_volume/config"
    self.client.publish(speaker_volume_topic, json.dumps(speaker_volume_payload), retain=True)
    self.set_speaker_volume_state(speaker_volume)

  def publish_language_state(self, language: str) -> None:
    """Publish the current language state to the instance-scoped topic."""
    logger.debug(f"Publishing language state: {language}")
    self.client.publish(self.get_language_state_topic(), language, retain=True)

  def set_availability(self, available: bool) -> None:
    message: Literal["online", "offline"] = "online" if available else "offline"
    self.publish("available", message, retain=True)

  def set_switch_state(self, enabled: bool) -> None:
    """Publish the enable/disable switch state to the instance-scoped topic."""
    state = "ON" if enabled else "OFF"
    logger.debug(f"Publishing switch state: {state}")
    self.client.publish(self.get_switch_state_topic(), state, retain=True)

  def set_mute_state(self, muted: bool) -> None:
    """Publish the microphone mute state to the instance-scoped topic."""
    state = "ON" if muted else "OFF"
    logger.debug(f"Publishing microphone mute state: {state}")
    self.client.publish(self.get_mute_state_topic(), state, retain=True)

  def set_speaker_state(self, device_name: str) -> None:
    """Publish the selected speaker output."""
    self.client.publish(self.get_speaker_state_topic(), device_name, retain=True)

  def set_speaker_mute_state(self, muted: bool) -> None:
    """Publish the speaker mute state."""
    state = "ON" if muted else "OFF"
    self.client.publish(self.get_speaker_mute_state_topic(), state, retain=True)

  def set_speaker_volume_state(self, volume: float) -> None:
    """Publish speaker volume as a Home Assistant percentage."""
    self.client.publish(self.get_speaker_volume_state_topic(), str(round(volume * 100)), retain=True)

  def disconnect(self) -> None:
    self.client.disconnect()
    self.client.loop_stop()
