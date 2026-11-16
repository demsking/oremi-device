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
from unittest.mock import MagicMock
from unittest.mock import patch

from device.core.mqtt import MqttDevice
from device.core.package import APP_VERSION


def test_mqtt_client_initialization() -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="test/topic",
    node_id="listener-1",
    username="user",
    password="pwd",
    discovery_prefix="homeassistant",
  )
  assert client.broker == "localhost"
  assert client.port == 1883
  assert client.topic == "test/topic"
  assert client.node_id == "listener-1"
  assert client.username == "user"
  assert client.password == "pwd"
  assert client.discovery_prefix == "homeassistant"


@patch("paho.mqtt.client.Client")
def test_topic_publishers_normalize_topics(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device/",
    node_id="living-room",
  )

  client.publish_event("/event", "event", qos=1, retain=True)
  client.publish_node("/microphone/mute/state", "ON", retain=True)

  assert client.topic == "oremi/device"
  assert mock_mqtt_class.return_value.publish.call_args_list == [
    (("oremi/device/nodes/living-room/event", "event"), {"qos": 1, "retain": True, "properties": None}),
    (("oremi/device/nodes/living-room/microphone/mute/state", "ON"), {"qos": 0, "retain": True, "properties": None}),
  ]


@patch("paho.mqtt.client.Client")
def test_publish_discovery_configs_no_entities(mock_mqtt_class) -> None:
  """Without component entities only the select + state topics are published."""
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/ohunerin/custom",
    node_id="oremi-ohunerin-custom",
    discovery_prefix="homeassistant",
  )

  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.publish = MagicMock()

  devices = ["Mic 1", "Mic 2"]
  current = "Mic 1"
  speakers = ["Built-in Audio", "USB Speaker"]
  client.publish_discovery_configs(
    input_devices=devices,
    current_device=current,
    output_devices=speakers,
    current_output="USB Speaker",
    speaker_muted=True,
    speaker_volume=0.42,
  )

  # 3 core entities + 7 device-level configs, their states, player integration
  # discovery, service controls/statuses, and device status.
  assert mock_client_instance.publish.call_count == 26

  calls = mock_client_instance.publish.call_args_list

  # First 3 calls: core entities (transcription, wakeword, sound)
  assert calls[0][0][0] == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/transcription/config"
  assert calls[1][0][0] == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/wakeword/config"
  assert calls[2][0][0] == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/sound/config"

  # Fourth call: language select config
  call_lang = calls[3]
  topic_lang, payload_lang = call_lang[0]
  assert topic_lang == "homeassistant/select/oremi-device-oremi-ohunerin-custom/language/config"
  assert call_lang[1].get("retain") is True
  data_lang = json.loads(payload_lang)
  assert data_lang["name"] == "Language"
  assert data_lang["unique_id"] == "oremi-device-oremi-ohunerin-custom_language"
  assert data_lang["options"] == ["fr", "en"]
  assert data_lang["icon"] == "mdi:translate"

  # Fifth call: language state
  call_lang_state = calls[4]
  topic_lang_state, payload_lang_state = call_lang_state[0]
  assert topic_lang_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/language/state"
  assert payload_lang_state == "fr"  # default

  # Sixth and seventh calls: microphone mute config and state
  call_mute = calls[5]
  topic_mute, payload_mute = call_mute[0]
  assert topic_mute == "homeassistant/switch/oremi-device-oremi-ohunerin-custom/microphone_muted/config"
  data_mute = json.loads(payload_mute)
  assert data_mute["name"] == "Microphone muted"
  assert data_mute["command_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/set"
  assert data_mute["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/state"

  topic_mute_state, payload_mute_state = calls[6][0]
  assert topic_mute_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/state"
  assert payload_mute_state == "OFF"

  # Eighth call: mic select config
  call_mic = calls[7]
  topic_mic, payload_mic = call_mic[0]
  kwargs_mic = call_mic[1]
  assert topic_mic == "homeassistant/select/oremi-device-oremi-ohunerin-custom/microphone_device/config"
  assert kwargs_mic.get("retain") is True

  data_mic = json.loads(payload_mic)
  assert data_mic["name"] == "Microphone Device"
  assert data_mic["unique_id"] == "oremi-device-oremi-ohunerin-custom_microphone_device"
  assert data_mic["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/state"
  assert data_mic["command_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/set"
  assert data_mic["options"] == devices
  assert data_mic["device"]["identifiers"] == ["oremi-device-oremi-ohunerin-custom"]

  # Ninth call: microphone state
  call_mic_state = calls[8]
  topic_mic_state, payload_mic_state = call_mic_state[0]
  kwargs_mic_state = call_mic_state[1]
  assert topic_mic_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/state"
  assert payload_mic_state == current
  assert kwargs_mic_state.get("retain") is True

  # Speaker output select config and state
  topic_speaker, payload_speaker = calls[9][0]
  assert topic_speaker == "homeassistant/select/oremi-device-oremi-ohunerin-custom/speaker_device/config"
  data_speaker = json.loads(payload_speaker)
  assert data_speaker["command_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/set"
  assert data_speaker["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/state"
  assert data_speaker["options"] == speakers
  assert calls[10][0] == (
    "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/state",
    "USB Speaker",
  )

  # Speaker mute config and state
  topic_speaker_mute, payload_speaker_mute = calls[11][0]
  assert topic_speaker_mute == "homeassistant/switch/oremi-device-oremi-ohunerin-custom/speaker_muted/config"
  data_speaker_mute = json.loads(payload_speaker_mute)
  assert data_speaker_mute["command_topic"].endswith("/speaker/mute/set")
  assert calls[12][0][1] == "ON"

  # Speaker volume config and percentage state
  topic_volume, payload_volume = calls[13][0]
  assert topic_volume == "homeassistant/number/oremi-device-oremi-ohunerin-custom/speaker_volume/config"
  data_volume = json.loads(payload_volume)
  assert data_volume["min"] == 0
  assert data_volume["max"] == 100
  assert data_volume["command_topic"].endswith("/speaker/volume/set")
  assert calls[14][0][1] == "42"

  assert calls[15][0] == (
    "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/player/state",
    "idle",
  )
  topic_player, payload_player = calls[16][0]
  assert topic_player == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/player/discovery"
  assert json.loads(payload_player) == {
    "node_id": "oremi-ohunerin-custom",
    "topic": "oremi/ohunerin/custom",
  }


@patch("paho.mqtt.client.Client")
def test_publish_discovery_configs_adds_device_context_controls(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="kitchen",
    discovery_prefix="homeassistant",
  )
  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.publish = MagicMock()
  device_context = {
    "language": "en",
    "location": "12 Rue de Rivoli, Paris",
    "timezone": "America/New_York",
    "temperature_unit": "fahrenheit",
    "preferred_currency": "USD",
    "measurement_system": "imperial",
    "distance_unit": "mile",
    "time_format": "12h",
    "date_format": "MM/DD/YYYY",
    "first_day_of_week": "sunday",
  }

  client.publish_discovery_configs(
    input_devices=[],
    current_device="",
    device_context=device_context,
    microphone_enabled=False,
    speaker_enabled=False,
    current_language="en",
  )

  published = {call.args[0]: call.args[1] for call in mock_client_instance.publish.call_args_list}
  language_config = json.loads(published["homeassistant/select/oremi-device-kitchen/language/config"])
  location_config = json.loads(published["homeassistant/text/oremi-device-kitchen/location/config"])
  timezone_config = json.loads(published["homeassistant/text/oremi-device-kitchen/timezone/config"])
  temperature_config = json.loads(published["homeassistant/select/oremi-device-kitchen/temperature_unit/config"])
  context_payload = json.loads(published["oremi/device/nodes/kitchen/context/state"])

  assert language_config["name"] == "Language"
  assert language_config["options"] == ["fr", "en"]
  assert language_config["state_topic"] == "oremi/device/nodes/kitchen/context/language/state"
  assert language_config["command_topic"] == "oremi/device/nodes/kitchen/context/language/set"
  assert location_config["name"] == "Location"
  assert location_config["state_topic"] == "oremi/device/nodes/kitchen/context/location/state"
  assert location_config["command_topic"] == "oremi/device/nodes/kitchen/context/location/set"
  assert timezone_config["name"] == "Timezone"
  assert timezone_config["state_topic"] == "oremi/device/nodes/kitchen/context/timezone/state"
  assert timezone_config["command_topic"] == "oremi/device/nodes/kitchen/context/timezone/set"
  assert temperature_config["options"] == ["celsius", "fahrenheit"]
  assert temperature_config["state_topic"] == "oremi/device/nodes/kitchen/context/temperature_unit/state"
  assert published["oremi/device/nodes/kitchen/context/language/state"] == "en"
  assert published["oremi/device/nodes/kitchen/context/location/state"] == "12 Rue de Rivoli, Paris"
  assert published["oremi/device/nodes/kitchen/context/preferred_currency/state"] == "USD"
  assert published["oremi/device/nodes/kitchen/context/temperature_unit/state"] == "fahrenheit"
  assert context_payload == device_context


@patch("paho.mqtt.client.Client")
def test_disabled_audio_discovery(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="test-node",
    discovery_prefix="homeassistant",
  )
  mock_client = mock_mqtt_class.return_value

  client.publish_discovery_configs(
    input_devices=[],
    current_device="",
    microphone_enabled=False,
    speaker_enabled=False,
  )

  audio_config_payloads = {
    call.args[0]: call.args[1]
    for call in mock_client.publish.call_args_list
    if call.args[0].endswith(
      (
        "/microphone_muted/config",
        "/microphone_device/config",
        "/speaker_device/config",
        "/speaker_muted/config",
        "/speaker_volume/config",
      )
    )
  }

  assert len(audio_config_payloads) == 5
  assert all(payload == "" for payload in audio_config_payloads.values())
  microphone_sensor_configs = {
    call.args[0]: call.args[1]
    for call in mock_client.publish.call_args_list
    if call.args[0].endswith(("/transcription/config", "/wakeword/config", "/sound/config"))
  }
  assert len(microphone_sensor_configs) == 3
  assert all(payload == "" for payload in microphone_sensor_configs.values())
  service_config_payloads = {
    call.args[0]: call.args[1]
    for call in mock_client.publish.call_args_list
    if call.args[0].endswith(
      (
        "/ambient_sound/config",
        "/voice_assistant/config",
        "/wake-word_status/config",
        "/voice-assistant_status/config",
        "/voice-responses_status/config",
      )
    )
  }
  assert len(service_config_payloads) == 5
  assert all(payload == "" for payload in service_config_payloads.values())
  mock_client.publish.assert_any_call(
    "oremi/device/nodes/test-node/player/discovery",
    "",
    retain=True,
  )


@patch("paho.mqtt.client.Client")
def test_discovery_preserves_active_player_state(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="test-node",
    discovery_prefix="homeassistant",
  )
  client.set_player_state("playing")
  mock_mqtt_class.return_value.publish.reset_mock()

  client.publish_discovery_configs(input_devices=[], current_device="")

  mock_mqtt_class.return_value.publish.assert_any_call(
    "oremi/device/nodes/test-node/player/state",
    "playing",
    retain=True,
  )


@patch("paho.mqtt.client.Client")
def test_voice_discovery_uses_filtered_options(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="test-node",
    discovery_prefix="homeassistant",
  )

  client.publish_discovery_configs(
    input_devices=[],
    current_device="",
    voices=["ff_siwis", "ff_gilles"],
    current_voice="ff_siwis",
  )

  calls = mock_mqtt_class.return_value.publish.call_args_list
  voice_call = next(call for call in calls if call.args[0].endswith("/voice/config"))
  payload = json.loads(voice_call.args[1])
  assert payload["options"] == ["ff_siwis", "ff_gilles"]
  assert payload["command_topic"].endswith("/voice/set")
  assert payload["state_topic"].endswith("/voice/state")
  mock_mqtt_class.return_value.publish.assert_any_call(
    "oremi/device/nodes/test-node/voice/state",
    "ff_siwis",
    retain=True,
  )


@patch("paho.mqtt.client.Client")
def test_publish_discovery_configs_with_entities(mock_mqtt_class) -> None:
  """Component-provided entities are published before the device-level select."""
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/ohunerin/custom",
    node_id="oremi-ohunerin-custom",
    discovery_prefix="homeassistant",
  )

  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.publish = MagicMock()

  node_id = client.get_node_id()
  device = client.get_device_descriptor()

  wakeword_payload = {
    "name": "Wakeword",
    "unique_id": f"{node_id}_wakeword",
    "state_topic": "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event",
    "availability_topic": "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/available",
    "device_class": "enum",
    "options": ["detected", "💤"],
    "icon": "mdi:waveform",
    "device": device,
  }
  sound_payload = {
    "name": "Sound Detector",
    "unique_id": f"{node_id}_sound",
    "state_topic": "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event",
    "availability_topic": "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/available",
    "icon": "mdi:waveform",
    "device": device,
  }

  entities = [
    ("sensor", "wakeword", wakeword_payload),
    ("sensor", "sound", sound_payload),
  ]

  devices = ["Mic 1", "Mic 2"]
  current = "Mic 1"
  client.publish_discovery_configs(input_devices=devices, current_device=current, entities=entities)

  # 3 core entities + 2 custom entities + device-level configs (without
  # continue_conversation), states, player discovery, service controls/statuses,
  # and device status.
  assert mock_client_instance.publish.call_count == 28

  calls = mock_client_instance.publish.call_args_list

  # First 3 calls: core entities (transcription, wakeword, sound)
  assert calls[0][0][0] == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/transcription/config"

  # Custom entities passed in entities list:
  topic_1, payload_1 = calls[3][0]
  assert topic_1 == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/wakeword/config"
  data_1 = json.loads(payload_1)
  assert data_1["name"] == "Wakeword"
  assert data_1["unique_id"] == "oremi-device-oremi-ohunerin-custom_wakeword"
  assert data_1["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event"
  assert data_1["availability_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/available"
  assert data_1["device"]["identifiers"] == ["oremi-device-oremi-ohunerin-custom"]
  assert data_1["device"]["sw_version"] == APP_VERSION

  topic_2, payload_2 = calls[4][0]
  assert topic_2 == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/sound/config"
  data_2 = json.loads(payload_2)
  assert data_2["name"] == "Sound Detector"
  assert data_2["unique_id"] == "oremi-device-oremi-ohunerin-custom_sound"
  assert data_2["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event"
  assert data_2["device"]["identifiers"] == ["oremi-device-oremi-ohunerin-custom"]
  assert data_2["device"]["sw_version"] == APP_VERSION


@patch("paho.mqtt.client.Client")
def test_muted_discovery_state(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="test/topic",
    node_id="listener-1",
    discovery_prefix="homeassistant",
  )
  mock_client_instance = mock_mqtt_class.return_value

  client.publish_discovery_configs(
    input_devices=["Mic 1"],
    current_device="Mic 1",
    microphone_muted=True,
  )

  mute_state_call = mock_client_instance.publish.call_args_list[6]
  assert mute_state_call[0] == ("test/topic/nodes/listener-1/microphone/mute/state", "ON")
  assert mute_state_call[1]["retain"] is True


@patch("paho.mqtt.client.Client")
def test_publish_discovery_disabled(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/ohunerin",
    node_id="oremi-ohunerin",
    discovery_prefix=None,
  )

  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.publish = MagicMock()

  client.publish_discovery_configs(input_devices=["Mic 1"], current_device="Mic 1")
  mock_client_instance.publish.assert_not_called()


@patch("paho.mqtt.client.Client")
def test_connect_disconnect(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="test/topic",
    node_id="listener-1",
    username="user",
    password="pwd",
  )

  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.connect = MagicMock()
  mock_client_instance.loop_start = MagicMock()
  mock_client_instance.disconnect = MagicMock()
  mock_client_instance.loop_stop = MagicMock()
  mock_client_instance.username_pw_set = MagicMock()

  client.connect()
  mock_client_instance.username_pw_set.assert_called_once_with(username="user", password="pwd")
  mock_client_instance.connect.assert_called_once_with("localhost", 1883, keepalive=0)
  mock_client_instance.loop_start.assert_called_once()

  client.disconnect()
  mock_client_instance.disconnect.assert_called_once()
  mock_client_instance.loop_stop.assert_called_once()


@patch("paho.mqtt.client.Client")
def test_conversation_state_topic_is_retained(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="kitchen",
  )

  client.set_conversation_state("processing")

  mock_mqtt_class.return_value.publish.assert_called_once_with(
    "oremi/device/nodes/kitchen/conversation/state",
    "processing",
    retain=True,
  )


@patch("paho.mqtt.client.Client")
def test_service_control_and_status_discovery(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="kitchen",
    discovery_prefix="homeassistant",
  )
  mock_client_instance = mock_mqtt_class.return_value

  client.publish_discovery_configs(
    input_devices=[],
    current_device="",
    sound_detection_enabled=False,
    andika_enabled=True,
  )

  published = {call.args[0]: call.args[1] for call in mock_client_instance.publish.call_args_list}

  ambient_switch = json.loads(published["homeassistant/switch/oremi-device-kitchen/ambient_sound/config"])
  assistant_switch = json.loads(published["homeassistant/switch/oremi-device-kitchen/voice_assistant/config"])
  wakeword_status = json.loads(published["homeassistant/sensor/oremi-device-kitchen/wake-word_status/config"])
  tts_status = json.loads(published["homeassistant/sensor/oremi-device-kitchen/voice-responses_status/config"])
  device_status = json.loads(published["homeassistant/sensor/oremi-device-kitchen/device_status/config"])

  assert ambient_switch["name"] == "Ambient sound detection"
  assert ambient_switch["command_topic"] == "oremi/device/nodes/kitchen/services/ambient-sound/enabled/set"
  assert ambient_switch["state_topic"] == "oremi/device/nodes/kitchen/services/ambient-sound/enabled/state"
  assert ambient_switch["payload_on"] == "ON"
  assert ambient_switch["payload_off"] == "OFF"
  assert assistant_switch["name"] == "Voice assistant"
  assert assistant_switch["command_topic"].endswith("/services/voice-assistant/enabled/set")
  assert published["oremi/device/nodes/kitchen/services/ambient-sound/enabled/state"] == "OFF"
  assert published["oremi/device/nodes/kitchen/services/voice-assistant/enabled/state"] == "ON"

  assert wakeword_status["state_topic"] == "oremi/device/nodes/kitchen/services/wake-word/status"
  assert wakeword_status["json_attributes_topic"] == wakeword_status["state_topic"]
  assert wakeword_status["value_template"] == "{{ value_json.state }}"
  assert wakeword_status["entity_category"] == "diagnostic"
  assert tts_status["state_topic"] == "oremi/device/nodes/kitchen/services/voice-responses/status"
  assert device_status["state_topic"] == "oremi/device/nodes/kitchen/device/status"
  assert device_status["unique_id"] == "oremi-device-kitchen_device_status"


@patch("paho.mqtt.client.Client")
def test_publish_service_status_and_enabled_state(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="kitchen",
  )
  mock_client_instance = mock_mqtt_class.return_value

  client.publish_service_enabled_state("ambient-sound", False)
  client.publish_service_status("ohunerin", "error", enabled=False, detail="connection refused")
  client.publish_device_status("running", started_at="2026-11-16T08:00:00+00:00")

  calls = mock_client_instance.publish.call_args_list
  assert calls[0].args == ("oremi/device/nodes/kitchen/services/ambient-sound/enabled/state", "OFF")
  assert calls[0].kwargs["retain"] is True
  assert calls[1].args[0] == "oremi/device/nodes/kitchen/services/wake-word/status"
  assert json.loads(calls[1].args[1]) == {
    "state": "error",
    "enabled": False,
    "detail": "connection refused",
  }
  assert json.loads(calls[2].args[1]) == {
    "state": "running",
    "node_id": "kitchen",
    "version": APP_VERSION,
    "started_at": "2026-11-16T08:00:00+00:00",
  }


@patch("paho.mqtt.client.Client")
def test_disabled_services_hide_data_sensors(mock_mqtt_class) -> None:
  client = MqttDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="kitchen",
    discovery_prefix="homeassistant",
  )
  mock_client_instance = mock_mqtt_class.return_value

  client.publish_discovery_configs(
    input_devices=[],
    current_device="",
    microphone_enabled=True,
    sound_detection_enabled=False,
    andika_enabled=False,
  )

  published = {call.args[0]: call.args[1] for call in mock_client_instance.publish.call_args_list}

  assert published["homeassistant/sensor/oremi-device-kitchen/transcription/config"] == ""
  assert published["homeassistant/sensor/oremi-device-kitchen/sound/config"] == ""
  assert published["homeassistant/sensor/oremi-device-kitchen/wakeword/config"] != ""

  assert published["oremi/device/nodes/kitchen/services/ambient-sound/enabled/state"] == "OFF"
  assert published["oremi/device/nodes/kitchen/services/voice-assistant/enabled/state"] == "OFF"
  assert "homeassistant/switch/oremi-device-kitchen/ambient_sound/config" in published
  assert "homeassistant/sensor/oremi-device-kitchen/wake-word_status/config" in published
