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
from unittest.mock import patch, MagicMock
import pytest
import sounddevice as sd
from oremi_device.core.audio import Audio, AudioDeviceError
from oremi_device import start
from oremi_device.core.detector import SoundDetector


def test_audio_no_compatible_device() -> None:
  # Mock sd.query_devices to return some devices but none with max_input_channels > 0
  with patch('sounddevice.query_devices') as mock_query:
    mock_query.return_value = [
      {'name': 'Output Device', 'max_input_channels': 0, 'default_samplerate': 44100}
    ]
    with pytest.raises(AudioDeviceError) as exc_info:
      Audio()
    assert "No compatible audio input device found" in str(exc_info.value)


def test_audio_query_devices_fails() -> None:
  # Mock sd.query_devices to raise an exception
  with patch('sounddevice.query_devices', side_effect=Exception("PortAudio error")):
    with pytest.raises(AudioDeviceError) as exc_info:
      Audio()
    assert "No compatible audio input device found" in str(exc_info.value)


def test_audio_initialize_fails() -> None:
  # Mock sd.query_devices to return a compatible device
  # but mock RawInputStream to raise PortAudioError
  with patch('sounddevice.query_devices') as mock_query, \
       patch('sounddevice.check_input_settings'), \
       patch('sounddevice.RawInputStream', side_effect=sd.PortAudioError("Init failed")):
    mock_query.return_value = [
      {'name': 'Mic', 'max_input_channels': 1, 'default_samplerate': 16000, 'index': 0}
    ]
    with pytest.raises(AudioDeviceError) as exc_info:
      Audio()
    assert "Failed to initialize audio device" in str(exc_info.value)


@pytest.mark.asyncio
async def test_main_audio_device_error() -> None:
  # Mock settings loading to return a fully-populated model so that
  # start() can configure MQTT before reaching Audio().
  from oremi_device.core.settings import DeviceSettings

  fake_settings = DeviceSettings(
    _env_file=None,
    node_id="test-node",
    language="fr",
    delay=3,
    conversation_timeout=15,
    ohunerin_host="localhost",
    ohunerin_port=5023,
    andika_host="localhost",
    andika_port=5315,
    cert_file=None,
    ohunerin_threshold=0.65,
    andika_model="vosk-model-small-fr-0.22",
    andika_samplerate=16000,
    microphone_device_index=None,
    microphone_device=None,
    mqtt_broker="localhost",
    mqtt_port=1883,
    mqtt_topic="oremi/test",
    mqtt_username=None,
    mqtt_password=None,
    mqtt_discovery_prefix="homeassistant",
    mqtt_discovery=False,
    microphone_enabled=True,
    speaker_enabled=True,
  )

  with patch('oremi_device.load_settings', return_value=fake_settings), \
       patch('oremi_device.Audio', side_effect=AudioDeviceError("No device")), \
       patch('sys.exit', side_effect=SystemExit(1)) as mock_exit, \
       patch('oremi_device.MQTTClient') as mock_mqtt_cls:
    mock_mqtt_cls.return_value.connect = MagicMock()
    mock_mqtt_cls.return_value.set_availability = MagicMock()
    mock_mqtt_cls.return_value.client.connect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt_cls.return_value.client.disconnect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt_cls.return_value.client.message_callback = MagicMock(return_value=lambda f: f)

    with pytest.raises(SystemExit) as exc_info:
      await start()

    assert exc_info.value.code == 1
    mock_exit.assert_called_once_with(1)


def test_get_compatible_input_devices() -> None:
  with patch('sounddevice.query_devices') as mock_query, \
       patch('sounddevice.check_input_settings') as mock_check:
    mock_query.return_value = [
      {'name': 'Mic 1', 'max_input_channels': 1, 'default_samplerate': 16000},
      {'name': 'Output Only', 'max_input_channels': 0, 'default_samplerate': 44100},
      {'name': 'Mic 2', 'max_input_channels': 2, 'default_samplerate': 16000},
      {'name': 'sysdefault', 'max_input_channels': 1, 'default_samplerate': 16000},
    ]
    # Simulate checks succeeding
    mock_check.side_effect = [None, None, None]

    # sysdefault is a virtual device, so it should not be returned when physical ones exist
    devs = Audio.get_compatible_input_devices()
    assert devs == ['Mic 1', 'Mic 2']

    # Test with current_device parameter
    mock_check.side_effect = [None, None, None, None]
    devs_with_current = Audio.get_compatible_input_devices(current_device='Mic 2')
    assert 'Mic 1' in devs_with_current
    assert 'Mic 2' in devs_with_current


def test_is_physical_microphone() -> None:
  assert Audio.is_physical_microphone("eMeet Luna") is True
  assert Audio.is_physical_microphone("sysdefault") is False
  assert Audio.is_physical_microphone("spdif") is False
  assert Audio.is_physical_microphone("default") is False
  assert Audio.is_physical_microphone("Default Microphone") is True


def test_sound_detector_terminate_with_no_stream() -> None:
  mock_mqtt = MagicMock()
  mock_ws = MagicMock()
  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=3, threshold=0.8)
  # Should not raise AttributeError when audio_stream is None
  detector.terminate()
  mock_mqtt.set_availability.assert_not_called()
  mock_mqtt.disconnect.assert_not_called()
