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
# pylint: disable=invalid-name
import json
import logging
from typing import Literal

import paho.mqtt.client as mqtt
import paho.mqtt.properties as mqtt_properties
from paho.mqtt.enums import CallbackAPIVersion

from device.core.cues import ConversationState
from device.core.models import DetectedSoundType
from device.core.package import APP_VERSION

logger = logging.getLogger(__name__)

# Type alias re-exported for callers that build entity lists.
# Each element: (ha_domain, entity_slug, payload_dict)
# e.g. ("sensor", "wakeword", {"name": "Wakeword", ...})
HAEntity = tuple[str, str, dict]

DEVICE_CONTEXT_OPTIONS: dict[str, list[str]] = {
  "language": ["fr", "en"],
  "temperature_unit": ["celsius", "fahrenheit"],
  "measurement_system": ["metric", "imperial"],
  "distance_unit": ["kilometer", "mile"],
  "time_format": ["12h", "24h"],
  "date_format": ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"],
  "first_day_of_week": ["monday", "sunday", "saturday"],
}

DEVICE_CONTEXT_TEXT_FIELDS = ("location", "timezone", "preferred_currency")

SERVICES = ("ohunerin", "andika", "akorin", "tts")

SERVICE_SLUGS = {
  "ohunerin": "wake-word",
  "andika": "voice-assistant",
  "akorin": "command-processing",
  "tts": "voice-responses",
}

SERVICE_LABELS = {
  "ohunerin": "Wake word",
  "andika": "Voice assistant",
  "akorin": "Command processing",
  "tts": "Voice responses",
}

SERVICE_ICONS = {
  "ohunerin": "mdi:waveform",
  "andika": "mdi:account-voice",
  "akorin": "mdi:brain",
  "tts": "mdi:volume-high",
}

SERVICE_SWITCHES = (
  ("ambient-sound", "Ambient sound detection", "mdi:ear-hearing"),
  ("voice-assistant", "Voice assistant", "mdi:account-voice"),
)

DEVICE_CONTEXT_LABELS = {
  "language": "Language",
  "location": "Location",
  "timezone": "Timezone",
  "temperature_unit": "Temperature unit",
  "preferred_currency": "Preferred currency",
  "measurement_system": "Measurement system",
  "distance_unit": "Distance unit",
  "time_format": "Time format",
  "date_format": "Date format",
  "first_day_of_week": "First day of week",
}

DEVICE_CONTEXT_ICONS = {
  "language": "mdi:translate",
  "location": "mdi:map-marker",
  "timezone": "mdi:map-clock",
  "temperature_unit": "mdi:thermometer",
  "preferred_currency": "mdi:cash",
  "measurement_system": "mdi:ruler-square",
  "distance_unit": "mdi:map-marker-distance",
  "time_format": "mdi:clock-outline",
  "date_format": "mdi:calendar-month",
  "first_day_of_week": "mdi:calendar-week",
}


class HomeAssistantDevice:
  """Central MQTT manager responsible for Home Assistant device status, discovery, and component events."""

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
  ) -> None:
    self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"oremi-device-{node_id}")
    self.broker = broker
    self.port = port
    self.topic = topic.rstrip("/")
    self.node_id = node_id
    self.username = username
    self.password = password
    self.discovery_prefix = discovery_prefix
    self.player_state: Literal["idle", "playing", "paused"] = "idle"

  # ── Helpers for building HA entity payloads outside this class ──────────────

  def get_node_id(self) -> str:
    return f"oremi-device-{self.node_id}"

  def get_device_descriptor(self) -> dict:
    """Return the HA device descriptor dict shared across all entities.

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

  def parse_node_topic(self, topic: str) -> str:
    node_topic = f"{self.topic}/nodes/{self.node_id}"
    suffix = topic.strip("/")
    return f"{node_topic}/{suffix}" if suffix else node_topic

  def parse_event_topic(self, topic: str) -> str:
    return self.parse_node_topic(topic)

  def publish_event(
    self,
    topic: DetectedSoundType | str,
    message: str,
    *,
    qos: int = 0,
    props: mqtt_properties.Properties | None = None,
    retain: bool = False,
  ) -> None:
    event_topic = self.parse_event_topic(topic)
    logger.debug(f"Publishing #{event_topic}: {message} with retain {retain}")
    self.client.publish(event_topic, message, qos=qos, retain=retain, properties=props)

  def publish_node(
    self,
    topic: str,
    message: str,
    *,
    qos: int = 0,
    props: mqtt_properties.Properties | None = None,
    retain: bool = False,
  ) -> None:
    node_topic = self.parse_node_topic(topic)
    logger.debug(f"Publishing #{node_topic}: {message} with retain {retain}")
    self.client.publish(node_topic, message, qos=qos, retain=retain, properties=props)

  def get_microphone_command_topic(self) -> str:
    """Return the instance-scoped MQTT topic for microphone select commands."""
    return self.parse_node_topic("microphone/set")

  def get_mute_command_topic(self) -> str:
    """Return the instance-scoped topic for microphone mute commands."""
    return self.parse_node_topic("microphone/mute/set")

  def get_mute_state_topic(self) -> str:
    """Return the instance-scoped topic for microphone mute state."""
    return self.parse_node_topic("microphone/mute/state")

  def get_speaker_command_topic(self) -> str:
    """Return the instance-scoped topic for speaker selection commands."""
    return self.parse_node_topic("speaker/set")

  def get_speaker_state_topic(self) -> str:
    """Return the instance-scoped topic for the selected speaker."""
    return self.parse_node_topic("speaker/state")

  def get_speaker_mute_cmd_topic(self) -> str:
    """Return the instance-scoped topic for speaker mute commands."""
    return self.parse_node_topic("speaker/mute/set")

  def get_speaker_mute_state_topic(self) -> str:
    """Return the instance-scoped topic for speaker mute state."""
    return self.parse_node_topic("speaker/mute/state")

  def get_speaker_volume_cmd_topic(self) -> str:
    """Return the instance-scoped topic for speaker volume commands."""
    return self.parse_node_topic("speaker/volume/set")

  def get_speaker_volume_state_topic(self) -> str:
    """Return the instance-scoped topic for speaker volume state."""
    return self.parse_node_topic("speaker/volume/state")

  def get_player_play_command_topic(self) -> str:
    return self.parse_node_topic("player/play/set")

  def get_player_stop_command_topic(self) -> str:
    return self.parse_node_topic("player/stop/set")

  def get_player_state_topic(self) -> str:
    return self.parse_node_topic("player/state")

  def get_player_discovery_topic(self) -> str:
    return self.parse_node_topic("player/discovery")

  def get_language_command_topic(self) -> str:
    """Return the instance-scoped MQTT topic for language-select commands."""
    return self.parse_node_topic("language/set")

  def get_language_state_topic(self) -> str:
    """Return the instance-scoped MQTT topic for the current language state."""
    return self.parse_node_topic("language/state")

  def get_device_context_state_topic(self) -> str:
    return self.parse_node_topic("context/state")

  def get_device_context_command_topic(self, field: str) -> str:
    return self.parse_node_topic(f"context/{field}/set")

  def get_device_context_field_state_topic(self, field: str) -> str:
    return self.parse_node_topic(f"context/{field}/state")

  def get_processing_result_topic(self) -> str:
    return self.parse_node_topic("processing/result")

  def get_conversation_state_topic(self) -> str:
    return self.parse_node_topic("conversation/state")

  def get_voice_command_topic(self) -> str:
    return self.parse_node_topic("voice/set")

  def get_voice_state_topic(self) -> str:
    return self.parse_node_topic("voice/state")

  def get_service_enabled_command_topic(self, service: str) -> str:
    return self.parse_node_topic(f"services/{service}/enabled/set")

  def get_service_enabled_state_topic(self, service: str) -> str:
    return self.parse_node_topic(f"services/{service}/enabled/state")

  def get_service_status_topic(self, service: str) -> str:
    slug = SERVICE_SLUGS.get(service, service)
    return self.parse_node_topic(f"services/{slug}/status")

  def get_device_status_topic(self) -> str:
    return self.parse_node_topic("device/status")

  def connect(self) -> None:
    if self.username:
      self.client.username_pw_set(username=self.username, password=self.password)

    self.client.connect(self.broker, self.port, keepalive=0)
    self.client.loop_start()

  def _publish_discovery_config(self, topic: str, payload: dict, *, enabled: bool) -> None:
    self.client.publish(topic, json.dumps(payload) if enabled else "", retain=True)

  def publish_discovery_configs(
    self,
    input_devices: list[str],
    current_device: str,
    entities: list["HAEntity"] | None = None,
    microphone_muted: bool = False,
    output_devices: list[str] | None = None,
    current_output: str = "",
    speaker_muted: bool = False,
    speaker_volume: float = 1.0,
    current_language: str = "fr",
    supported_languages: list[str] | None = None,
    device_context: dict[str, str] | None = None,
    microphone_enabled: bool = True,
    speaker_enabled: bool = True,
    voices: list[str] | None = None,
    current_voice: str = "",
    ohunerin_sounds: list[str] | None = None,
    sound_detection_enabled: bool = True,
    andika_enabled: bool = True,
  ) -> None:
    """Publish Home Assistant MQTT discovery configs."""
    if not self.discovery_prefix:
      return

    node_id = self.get_node_id()
    device = self.get_device_descriptor()

    # ── Core Home Assistant Entities Managed ONLY by HomeAssistantDevice ─────
    transcription_payload = {
      "name": "Voice transcription",
      "unique_id": f"{node_id}_transcription",
      "state_topic": self.parse_node_topic("transcription/result"),
      "value_template": "{{ value_json.text }}",
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:subtitles",
      "device": device,
    }
    transcription_topic = f"{self.discovery_prefix}/sensor/{node_id}/transcription/config"
    self._publish_discovery_config(
      transcription_topic,
      transcription_payload,
      enabled=microphone_enabled and andika_enabled,
    )

    event_topic = self.parse_node_topic("events/detection")
    wakeword_payload = {
      "name": "Wake word",
      "unique_id": f"{node_id}_wakeword",
      "state_topic": event_topic,
      "value_template": ("{% if value_json.type == 'wakeword' and value_json.sound != '...' %}detected{% else %}💤{% endif %}"),
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "device_class": "enum",
      "options": ["detected", "💤"],
      "json_attributes_topic": event_topic,
      "json_attributes_template": (
        "{% if value_json.type == 'wakeword' and value_json.sound != '...' %}{{ value_json | tojson }}{% else %}{}{% endif %}"
      ),
      "icon": "mdi:waveform",
      "device": device,
    }
    wakeword_topic = f"{self.discovery_prefix}/sensor/{node_id}/wakeword/config"
    self._publish_discovery_config(
      wakeword_topic,
      wakeword_payload,
      enabled=microphone_enabled,
    )

    sound_payload: dict = {
      "name": "Ambient sound",
      "unique_id": f"{node_id}_sound",
      "state_topic": event_topic,
      "value_template": (
        "{% if value_json.type == 'sound' and value_json.sound != '...' %}{{ value_json.sound }}{% else %}💤{% endif %}"
      ),
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "json_attributes_topic": event_topic,
      "json_attributes_template": (
        "{% if value_json.type == 'sound' and value_json.sound != '...' %}{{ value_json | tojson }}{% else %}{}{% endif %}"
      ),
      "icon": "mdi:waveform",
      "device": device,
    }

    if ohunerin_sounds:
      sound_payload["device_class"] = "enum"
      sound_payload["options"] = ohunerin_sounds + ["💤"]
      mapper_items = []

      for sound in ohunerin_sounds:
        escaped_sound = sound.replace("'", "\\'")

        mapper_items.append(f"'{escaped_sound}': '{escaped_sound}'")

      mapper_str = ", ".join(mapper_items)
      sound_payload["value_template"] = (
        f"{{% if value_json.type != 'sound' or value_json.sound == '...' %}}💤"
        f"{{% else %}}{{% set mapper = {{{mapper_str}}} %}}"
        f"{{{{ mapper.get(value_json.sound, value_json.sound) }}}}"
        f"{{% endif %}}"
      )

    sound_topic = f"{self.discovery_prefix}/sensor/{node_id}/sound/config"
    self._publish_discovery_config(
      sound_topic,
      sound_payload,
      enabled=microphone_enabled and sound_detection_enabled,
    )

    # ── Additional custom entities (if provided) ──────────────────────────────
    for ha_domain, entity_slug, payload in entities or []:
      discovery_topic = f"{self.discovery_prefix}/{ha_domain}/{node_id}/{entity_slug}/config"

      logger.debug(f"Publishing HA entity discovery: {discovery_topic}")
      self.client.publish(discovery_topic, json.dumps(payload), retain=True)

    if device_context is None:
      languages = supported_languages or ["fr", "en"]
      language_payload = {
        "name": "Language",
        "unique_id": f"{node_id}_language",
        "state_topic": self.get_language_state_topic(),
        "command_topic": self.get_language_command_topic(),
        "availability_topic": self.parse_node_topic("available"),
        "payload_available": "online",
        "payload_not_available": "offline",
        "options": languages,
        "icon": "mdi:translate",
        "device": device,
      }
      language_topic = f"{self.discovery_prefix}/select/{node_id}/language/config"
      self.client.publish(language_topic, json.dumps(language_payload), retain=True)

    self.client.publish(self.get_language_state_topic(), current_language, retain=True)

    if device_context is not None:
      for field in DEVICE_CONTEXT_TEXT_FIELDS:
        payload = {
          "name": DEVICE_CONTEXT_LABELS[field],
          "unique_id": f"{node_id}_{field}",
          "state_topic": self.get_device_context_field_state_topic(field),
          "command_topic": self.get_device_context_command_topic(field),
          "availability_topic": self.parse_node_topic("available"),
          "payload_available": "online",
          "payload_not_available": "offline",
          "icon": DEVICE_CONTEXT_ICONS[field],
          "device": device,
        }
        topic = f"{self.discovery_prefix}/text/{node_id}/{field}/config"
        self.client.publish(topic, json.dumps(payload), retain=True)
        self.publish_device_context_value(field, device_context[field])

      for field, options in DEVICE_CONTEXT_OPTIONS.items():
        payload = {
          "name": DEVICE_CONTEXT_LABELS[field],
          "unique_id": f"{node_id}_{field}",
          "state_topic": self.get_device_context_field_state_topic(field),
          "command_topic": self.get_device_context_command_topic(field),
          "availability_topic": self.parse_node_topic("available"),
          "payload_available": "online",
          "payload_not_available": "offline",
          "options": options,
          "icon": DEVICE_CONTEXT_ICONS[field],
          "device": device,
        }
        topic = f"{self.discovery_prefix}/select/{node_id}/{field}/config"
        self.client.publish(topic, json.dumps(payload), retain=True)
        self.publish_device_context_value(field, device_context[field])

      self.publish_device_context(device_context)

    if voices is not None:
      voice_payload = {
        "name": "Voice",
        "unique_id": f"{node_id}_voice",
        "state_topic": self.get_voice_state_topic(),
        "command_topic": self.get_voice_command_topic(),
        "availability_topic": self.parse_node_topic("available"),
        "payload_available": "online",
        "payload_not_available": "offline",
        "options": voices,
        "icon": "mdi:account-voice",
        "device": device,
      }
      voice_topic = f"{self.discovery_prefix}/select/{node_id}/voice/config"
      self.client.publish(voice_topic, json.dumps(voice_payload) if voices else "", retain=True)

      if voices:
        self.publish_voice_state(current_voice)

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
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:microphone-off",
      "device": device,
    }

    mute_topic = f"{self.discovery_prefix}/switch/{node_id}/microphone_muted/config"
    self.client.publish(mute_topic, json.dumps(mute_payload) if microphone_enabled else "", retain=True)

    if microphone_enabled:
      self.set_mute_state(microphone_muted)

    # ── Device-level: microphone select ─────────────────────────────────────
    select_payload = {
      "name": "Microphone Device",
      "unique_id": f"{node_id}_microphone_device",
      "state_topic": self.parse_node_topic("microphone/state"),
      "command_topic": self.get_microphone_command_topic(),
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "options": input_devices,
      "icon": "mdi:microphone",
      "device": device,
    }

    select_topic = f"{self.discovery_prefix}/select/{node_id}/microphone_device/config"

    logger.info(f"Publishing MQTT Discovery configurations to {self.discovery_prefix}...")
    self.client.publish(select_topic, json.dumps(select_payload) if microphone_enabled else "", retain=True)

    if microphone_enabled:
      self.publish_node("microphone/state", current_device, retain=True)

    # ── Device-level: speaker output select ──────────────────────────────────
    speaker_payload = {
      "name": "Speaker Device",
      "unique_id": f"{node_id}_speaker_device",
      "state_topic": self.get_speaker_state_topic(),
      "command_topic": self.get_speaker_command_topic(),
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "options": output_devices or [],
      "icon": "mdi:speaker",
      "device": device,
    }

    speaker_topic = f"{self.discovery_prefix}/select/{node_id}/speaker_device/config"
    self.client.publish(speaker_topic, json.dumps(speaker_payload) if speaker_enabled else "", retain=True)

    if speaker_enabled:
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
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:volume-off",
      "device": device,
    }
    speaker_mute_topic = f"{self.discovery_prefix}/switch/{node_id}/speaker_muted/config"
    self.client.publish(speaker_mute_topic, json.dumps(speaker_mute_payload) if speaker_enabled else "", retain=True)

    if speaker_enabled:
      self.set_speaker_mute_state(speaker_muted)

    # ── Device-level: speaker volume number ──────────────────────────────────
    speaker_volume_payload = {
      "name": "Speaker volume",
      "unique_id": f"{node_id}_speaker_volume",
      "state_topic": self.get_speaker_volume_state_topic(),
      "command_topic": self.get_speaker_volume_cmd_topic(),
      "availability_topic": self.parse_node_topic("available"),
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
    self.client.publish(speaker_volume_topic, json.dumps(speaker_volume_payload) if speaker_enabled else "", retain=True)

    if speaker_enabled:
      self.set_speaker_volume_state(speaker_volume)
      self.set_player_state(self.player_state)
      self.client.publish(
        self.get_player_discovery_topic(),
        json.dumps({"node_id": self.node_id, "topic": self.topic}),
        retain=True,
      )
    else:
      self.client.publish(self.get_player_discovery_topic(), "", retain=True)

    self._publish_service_discovery(
      node_id=node_id,
      device=device,
      microphone_enabled=microphone_enabled,
      speaker_enabled=speaker_enabled,
      sound_detection_enabled=sound_detection_enabled,
      andika_enabled=andika_enabled,
    )

  def _publish_service_discovery(
    self,
    *,
    node_id: str,
    device: dict,
    microphone_enabled: bool,
    speaker_enabled: bool,
    sound_detection_enabled: bool,
    andika_enabled: bool,
  ) -> None:
    """Publish service enable switches and diagnostic status sensors."""
    if microphone_enabled:
      for service, label, icon in SERVICE_SWITCHES:
        enabled = sound_detection_enabled if service == "ambient-sound" else andika_enabled
        payload = {
          "name": label,
          "unique_id": f"{node_id}_{service.replace('-', '_')}",
          "state_topic": self.get_service_enabled_state_topic(service),
          "command_topic": self.get_service_enabled_command_topic(service),
          "payload_on": "ON",
          "payload_off": "OFF",
          "state_on": "ON",
          "state_off": "OFF",
          "availability_topic": self.parse_node_topic("available"),
          "payload_available": "online",
          "payload_not_available": "offline",
          "icon": icon,
          "device": device,
        }
        topic = f"{self.discovery_prefix}/switch/{node_id}/{service.replace('-', '_')}/config"
        self.client.publish(topic, json.dumps(payload), retain=True)
        self.publish_service_enabled_state(service, enabled)
    else:
      for service in ("ambient-sound", "voice-assistant"):
        self.client.publish(
          f"{self.discovery_prefix}/switch/{node_id}/{service.replace('-', '_')}/config",
          "",
          retain=True,
        )

      for service in ("ohunerin", "andika"):
        slug = SERVICE_SLUGS[service]
        self.client.publish(f"{self.discovery_prefix}/sensor/{node_id}/{slug}_status/config", "", retain=True)

    if not speaker_enabled:
      self.client.publish(
        f"{self.discovery_prefix}/sensor/{node_id}/{SERVICE_SLUGS['tts']}_status/config",
        "",
        retain=True,
      )

    visible_services = [
      service
      for service in SERVICES
      if (service not in ("ohunerin", "andika") or microphone_enabled)
      and (service != "tts" or speaker_enabled)
    ]

    for service in visible_services:
      slug = SERVICE_SLUGS[service]
      payload = {
        "name": f"{SERVICE_LABELS[service]} status",
        "unique_id": f"{node_id}_{slug}_status",
        "state_topic": self.get_service_status_topic(service),
        "value_template": "{{ value_json.state }}",
        "json_attributes_topic": self.get_service_status_topic(service),
        "availability_topic": self.parse_node_topic("available"),
        "payload_available": "online",
        "payload_not_available": "offline",
        "entity_category": "diagnostic",
        "icon": SERVICE_ICONS[service],
        "device": device,
      }
      topic = f"{self.discovery_prefix}/sensor/{node_id}/{slug}_status/config"
      self.client.publish(topic, json.dumps(payload), retain=True)

    device_payload = {
      "name": "Device status",
      "unique_id": f"{node_id}_device_status",
      "state_topic": self.get_device_status_topic(),
      "value_template": "{{ value_json.state }}",
      "json_attributes_topic": self.get_device_status_topic(),
      "availability_topic": self.parse_node_topic("available"),
      "payload_available": "online",
      "payload_not_available": "offline",
      "entity_category": "diagnostic",
      "icon": "mdi:server-network",
      "device": device,
    }
    topic = f"{self.discovery_prefix}/sensor/{node_id}/device_status/config"
    self.client.publish(topic, json.dumps(device_payload), retain=True)

  def publish_language_state(self, language: str) -> None:
    """Publish the current language state to the instance-scoped topic."""
    logger.debug(f"Publishing language state: {language}")
    self.client.publish(self.get_language_state_topic(), language, retain=True)

  def publish_device_context(self, context: dict[str, str]) -> None:
    self.client.publish(self.get_device_context_state_topic(), json.dumps(context, sort_keys=True), retain=True)

  def publish_device_context_value(self, field: str, value: str) -> None:
    self.client.publish(self.get_device_context_field_state_topic(field), value, retain=True)

  def publish_voice_state(self, voice: str) -> None:
    self.client.publish(self.get_voice_state_topic(), voice, retain=True)

  def publish_service_enabled_state(self, service: str, enabled: bool) -> None:
    """Publish the desired enabled state of a service switch."""
    self.client.publish(self.get_service_enabled_state_topic(service), "ON" if enabled else "OFF", retain=True)

  def publish_service_status(
    self,
    service: str,
    status: str,
    *,
    enabled: bool,
    detail: str | None = None,
  ) -> None:
    """Publish a service status payload for the diagnostic sensor."""
    payload: dict[str, object] = {"state": status, "enabled": enabled}

    if detail:
      payload["detail"] = detail

    self.client.publish(self.get_service_status_topic(service), json.dumps(payload), retain=True)

  def publish_device_status(self, state: str, *, started_at: str | None = None) -> None:
    """Publish the device lifecycle state and its diagnostic attributes."""
    payload: dict[str, object] = {
      "state": state,
      "node_id": self.node_id,
      "version": APP_VERSION,
    }

    if started_at:
      payload["started_at"] = started_at

    self.client.publish(self.get_device_status_topic(), json.dumps(payload), retain=True)

  def set_conversation_state(self, state: ConversationState) -> None:
    self.client.publish(self.get_conversation_state_topic(), state, retain=True)

  def set_availability(self, available: bool) -> None:
    message: Literal["online", "offline"] = "online" if available else "offline"
    self.publish_node("available", message, retain=True)

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

  def set_player_state(self, state: Literal["idle", "playing", "paused"]) -> None:
    """Publish the Home Assistant player state."""
    self.player_state = state
    self.client.publish(self.get_player_state_topic(), state, retain=True)

  def disconnect(self) -> None:
    self.client.disconnect()
    self.client.loop_stop()


# Backward compatibility alias
MqttDevice = HomeAssistantDevice
