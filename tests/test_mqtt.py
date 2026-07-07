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

from device.core.mqtt import MQTTClient
from device.core.package import APP_VERSION


def test_mqtt_client_initialization() -> None:
  client = MQTTClient(
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
  client = MQTTClient(
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
  client = MQTTClient(
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

  # Six device-level configs, their states, and player integration discovery.
  assert mock_client_instance.publish.call_count == 14

  calls = mock_client_instance.publish.call_args_list

  # First call: language select config
  call_lang = calls[0]
  topic_lang, payload_lang = call_lang[0]
  assert topic_lang == "homeassistant/select/oremi-device-oremi-ohunerin-custom/language/config"
  assert call_lang[1].get("retain") is True
  data_lang = json.loads(payload_lang)
  assert data_lang["name"] == "Language"
  assert data_lang["unique_id"] == "oremi-device-oremi-ohunerin-custom_language"
  assert data_lang["options"] == ["fr", "en"]
  assert data_lang["icon"] == "mdi:translate"

  # Second call: language state
  call_lang_state = calls[1]
  topic_lang_state, payload_lang_state = call_lang_state[0]
  assert topic_lang_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/language/state"
  assert payload_lang_state == "fr"  # default

  # Third and fourth calls: microphone mute config and state
  call_mute = calls[2]
  topic_mute, payload_mute = call_mute[0]
  assert topic_mute == "homeassistant/switch/oremi-device-oremi-ohunerin-custom/microphone_muted/config"
  data_mute = json.loads(payload_mute)
  assert data_mute["name"] == "Microphone muted"
  assert data_mute["command_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/set"
  assert data_mute["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/state"

  topic_mute_state, payload_mute_state = calls[3][0]
  assert topic_mute_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/state"
  assert payload_mute_state == "OFF"

  # Fifth call: mic select config
  call_mic = calls[4]
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

  # Sixth call: microphone state
  call_mic_state = calls[5]
  topic_mic_state, payload_mic_state = call_mic_state[0]
  kwargs_mic_state = call_mic_state[1]
  assert topic_mic_state == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/state"
  assert payload_mic_state == current
  assert kwargs_mic_state.get("retain") is True

  # Speaker output select config and state
  topic_speaker, payload_speaker = calls[6][0]
  assert topic_speaker == "homeassistant/select/oremi-device-oremi-ohunerin-custom/speaker_device/config"
  data_speaker = json.loads(payload_speaker)
  assert data_speaker["command_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/set"
  assert data_speaker["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/state"
  assert data_speaker["options"] == speakers
  assert calls[7][0] == (
    "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/speaker/state",
    "USB Speaker",
  )

  # Speaker mute config and state
  topic_speaker_mute, payload_speaker_mute = calls[8][0]
  assert topic_speaker_mute == "homeassistant/switch/oremi-device-oremi-ohunerin-custom/speaker_muted/config"
  data_speaker_mute = json.loads(payload_speaker_mute)
  assert data_speaker_mute["command_topic"].endswith("/speaker/mute/set")
  assert calls[9][0][1] == "ON"

  # Speaker volume config and percentage state
  topic_volume, payload_volume = calls[10][0]
  assert topic_volume == "homeassistant/number/oremi-device-oremi-ohunerin-custom/speaker_volume/config"
  data_volume = json.loads(payload_volume)
  assert data_volume["min"] == 0
  assert data_volume["max"] == 100
  assert data_volume["command_topic"].endswith("/speaker/volume/set")
  assert calls[11][0][1] == "42"

  assert calls[12][0] == (
    "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/player/state",
    "idle",
  )
  topic_player, payload_player = calls[13][0]
  assert topic_player == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/player/discovery"
  assert json.loads(payload_player) == {
    "node_id": "oremi-ohunerin-custom",
    "topic": "oremi/ohunerin/custom",
  }


@patch("paho.mqtt.client.Client")
def test_publish_discovery_configs_adds_device_context_controls(mock_mqtt_class) -> None:
  client = MQTTClient(
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
  client = MQTTClient(
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
  mock_client.publish.assert_any_call(
    "oremi/device/nodes/test-node/player/discovery",
    "",
    retain=True,
  )


@patch("paho.mqtt.client.Client")
def test_discovery_preserves_active_player_state(mock_mqtt_class) -> None:
  client = MQTTClient(
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
  client = MQTTClient(
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
  client = MQTTClient(
    broker="localhost",
    port=1883,
    topic="oremi/ohunerin/custom",
    node_id="oremi-ohunerin-custom",
    discovery_prefix="homeassistant",
  )

  mock_client_instance = mock_mqtt_class.return_value
  mock_client_instance.publish = MagicMock()

  node_id = client.get_node_id()  # noqa: SLF001
  device = client.get_device_descriptor()  # noqa: SLF001

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

  # 2 component entities + device-level configs, states, and player discovery.
  assert mock_client_instance.publish.call_count == 16

  calls = mock_client_instance.publish.call_args_list

  # First call: wakeword entity
  topic_1, payload_1 = calls[0][0]
  assert topic_1 == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/wakeword/config"
  data_1 = json.loads(payload_1)
  assert data_1["name"] == "Wakeword"
  assert data_1["unique_id"] == "oremi-device-oremi-ohunerin-custom_wakeword"
  assert data_1["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event"
  assert data_1["availability_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/available"
  assert data_1["device"]["identifiers"] == ["oremi-device-oremi-ohunerin-custom"]
  assert data_1["device"]["sw_version"] == APP_VERSION

  # Second call: sound entity
  topic_2, payload_2 = calls[1][0]
  assert topic_2 == "homeassistant/sensor/oremi-device-oremi-ohunerin-custom/sound/config"
  data_2 = json.loads(payload_2)
  assert data_2["name"] == "Sound Detector"
  assert data_2["unique_id"] == "oremi-device-oremi-ohunerin-custom_sound"
  assert data_2["state_topic"] == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/event"
  assert data_2["device"]["identifiers"] == ["oremi-device-oremi-ohunerin-custom"]
  assert data_2["device"]["sw_version"] == APP_VERSION

  # Third call: language select config
  topic_3, payload_3 = calls[2][0]
  assert topic_3 == "homeassistant/select/oremi-device-oremi-ohunerin-custom/language/config"
  data_3 = json.loads(payload_3)
  assert data_3["name"] == "Language"
  assert data_3["options"] == ["fr", "en"]

  # Fourth call: language state
  topic_4, payload_4 = calls[3][0]
  assert topic_4 == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/language/state"
  assert payload_4 == "fr"  # default

  # Fifth and sixth calls: microphone mute config and state
  topic_5, payload_5 = calls[4][0]
  assert topic_5 == "homeassistant/switch/oremi-device-oremi-ohunerin-custom/microphone_muted/config"
  assert json.loads(payload_5)["unique_id"] == "oremi-device-oremi-ohunerin-custom_microphone_muted"

  topic_6, payload_6 = calls[5][0]
  assert topic_6 == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/mute/state"
  assert payload_6 == "OFF"

  # Seventh call: mic select config
  topic_7, _ = calls[6][0]
  assert topic_7 == "homeassistant/select/oremi-device-oremi-ohunerin-custom/microphone_device/config"

  # Eighth call: microphone state
  topic_8, payload_8 = calls[7][0]
  assert topic_8 == "oremi/ohunerin/custom/nodes/oremi-ohunerin-custom/microphone/state"
  assert payload_8 == current


@patch("paho.mqtt.client.Client")
def test_muted_discovery_state(mock_mqtt_class) -> None:
  client = MQTTClient(
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

  mute_state_call = mock_client_instance.publish.call_args_list[3]
  assert mute_state_call[0] == ("test/topic/nodes/listener-1/microphone/mute/state", "ON")
  assert mute_state_call[1]["retain"] is True


@patch("paho.mqtt.client.Client")
def test_publish_discovery_disabled(mock_mqtt_class) -> None:
  client = MQTTClient(
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
  client = MQTTClient(
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
  client = MQTTClient(
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
