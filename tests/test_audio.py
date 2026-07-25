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
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from device.core.audio import Audio
from device.core.audio import AudioDeviceError
from device.core.detector import SoundDetector


def test_audio_no_compatible_device() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = []
    with pytest.raises(AudioDeviceError) as exc_info:
      Audio()
    assert "No compatible audio input device found" in str(exc_info.value)


def test_audio_query_devices_fails() -> None:
  with patch("miniaudio.Devices", side_effect=Exception("miniaudio query error")):
    with pytest.raises(AudioDeviceError) as exc_info:
      Audio()
    assert "Failed to query audio devices" in str(exc_info.value)


def test_audio_initialize_fails() -> None:
  with (
    patch("miniaudio.Devices") as mock_devices,
    patch("miniaudio.CaptureDevice", side_effect=Exception("Init failed")),
  ):
    mock_devices.return_value.get_captures.return_value = [{"name": "Mic", "id": None}]
    audio = Audio()
    with pytest.raises(AudioDeviceError) as exc_info:
      audio.start_stream()
    assert "Failed to initialize audio device" in str(exc_info.value)


def test_audio_validates_named_input_device_before_opening_stream() -> None:
  with (
    patch("miniaudio.Devices") as mock_devices,
    patch("miniaudio.CaptureDevice") as mock_stream,
  ):
    mock_devices.return_value.get_captures.return_value = [{"name": "eMeet Luna: USB Audio", "id": 2}]

    audio = Audio(device_name="eMeet Luna")
    audio.start_stream()

    assert audio.device_name == "eMeet Luna: USB Audio"
    mock_stream.assert_called_once()


def test_get_compatible_input_devices() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {"name": "Mic 1", "id": 1},
      {"name": "Mic 2", "id": 2},
      {"name": "sysdefault", "id": 3},
    ]

    devs = Audio.get_compatible_input_devices()
    assert devs == ["Mic 1", "Mic 2"]

    devs_with_current = Audio.get_compatible_input_devices(current_device="Mic 2")
    assert "Mic 1" in devs_with_current
    assert "Mic 2" in devs_with_current


def test_is_physical_microphone() -> None:
  assert Audio.is_physical_microphone("eMeet Luna") is True
  assert Audio.is_physical_microphone("sysdefault") is False
  assert Audio.is_physical_microphone("spdif") is False
  assert Audio.is_physical_microphone("default") is False
  assert Audio.is_physical_microphone("Default Microphone") is True
  assert Audio.is_physical_microphone("Monitor of eMeet Luna Mono device") is False


def test_audio_prefers_physical_microphone_over_monitor() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {"name": "Monitor of eMeet Luna Mono device", "id": 1},
      {"name": "eMeet Luna Mono", "id": 2},
    ]

    audio = Audio(device_name="eMeet Luna Mono")
    assert audio.device_name == "eMeet Luna Mono"


def test_match_device_name() -> None:
  from device.core.audio import match_device_name

  # Exact match
  assert match_device_name("eMeet Luna Mono", "eMeet Luna Mono") is True
  # Substring matches
  assert match_device_name("eMeet Luna", "eMeet Luna Mono") is True
  assert match_device_name("eMeet Luna Mono", "eMeet Luna") is True
  # Token-based match with hardware details (ALSA hw suffixes) vs pipewire
  assert match_device_name("eMeet Luna: USB Audio (hw:2,0)", "eMeet Luna Mono") is True
  # Mismatched/different devices
  assert match_device_name("eMeet Luna: USB Audio (hw:2,0)", "Built-in Audio Analog Stereo") is False
  assert match_device_name("HDA Intel PCH: PHL 325E1 (hw:2,3)", "HDA Intel PCH: HDMI 1 (hw:2,7)") is False
  assert match_device_name("Built-in Audio Analog Stereo", "Built-in Audio Analog Stereo") is True


def test_sound_detector_terminate_with_no_stream() -> None:
  mock_mqtt = MagicMock()
  mock_ws = MagicMock()
  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=3, threshold=0.8)
  detector.terminate()
  mock_mqtt.set_availability.assert_not_called()
  mock_mqtt.disconnect.assert_not_called()


@pytest.mark.asyncio
async def test_audio_listener_handles_null_stream() -> None:
  from device.core.listener import AudioListener

  websocket = MagicMock()
  listener = AudioListener(None, websocket)

  await listener.listening()


@pytest.mark.asyncio
async def test_audio_service_change_device_notifies_components() -> None:
  from device.core.components import AudioStreamComponent
  from device.services.audio_service import AudioService

  class DummyComponent(AudioStreamComponent):
    def __init__(self) -> None:
      self.device_changed_called = False

    async def on_device_changed(self, new_stream) -> None:
      self.device_changed_called = True

    async def start(self, config, shared_resources) -> None:
      pass

    async def stop(self) -> None:
      pass

    @property
    def name(self) -> str:
      return "dummy"

  from device.core.settings import Settings

  settings = Settings(
    _env_file=None, node_id="test", ohunerin_host="localhost", andika_host="localhost", mqtt_broker="localhost"
  )
  service = AudioService(settings)
  component = DummyComponent()

  with patch("device.services.audio_service.Audio") as mock_audio_cls:
    mock_audio_cls.find_compatible_device.return_value = {"index": 0}
    res = await service.change_audio_device("Mic", components=[component])
    assert res is True
    assert component.device_changed_called is True
