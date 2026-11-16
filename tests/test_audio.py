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
import asyncio
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
    ]

    devs = Audio.get_compatible_input_devices()
    assert devs == ["Mic 1", "Mic 2"]

    devs_with_current = Audio.get_compatible_input_devices(current_device="Mic 2")
    assert "Mic 1" in devs_with_current
    assert "Mic 2" in devs_with_current


def test_is_physical_microphone() -> None:
  assert Audio.is_physical_microphone("eMeet Luna") is True


def test_audio_logs_device_info_on_selection(caplog) -> None:
  import logging

  with patch("miniaudio.Devices") as mock_devices, caplog.at_level(logging.INFO):
    mock_devices.return_value.get_captures.return_value = [
      {
        "name": "Test Microphone",
        "id": 1,
        "formats": [{"format": "16-bit Signed Integer", "samplerate": 48000, "channels": 2}],
      }
    ]
    audio = Audio(samplerate=16000, dtype="int16", blocksize=4000)

    assert audio.info == {
      "samplerate": 16000,
      "dtype": "int16",
      "channels": 1,
      "blocksize": 4000,
      "native_samplerate": 48000,
      "native_channels": 2,
      "native_format": "16-bit Signed Integer",
    }

    assert "Selected audio input device: Test Microphone" in caplog.text


def test_audio_resamples_when_native_samplerate_differs() -> None:
  with (
    patch("miniaudio.Devices") as mock_devices,
    patch("miniaudio.CaptureDevice") as mock_capture_cls,
  ):
    mock_devices.return_value.get_captures.return_value = [
      {
        "name": "BY-BMW700 Analog",
        "id": 1,
        "formats": [{"format": "16-bit Signed Integer", "samplerate": 48000, "channels": 2}],
      }
    ]

    audio = Audio(samplerate=16000)
    audio.start_stream()

    # CaptureDevice initialized with target sample rate (16000) for miniaudio native stateful resampling
    mock_capture_cls.assert_called_once()
    _, kwargs = mock_capture_cls.call_args
    assert kwargs["sample_rate"] == 16000


def test_audio_prefers_physical_microphone_over_monitor() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {"name": "Monitor of eMeet Luna Mono device", "id": 1},
      {"name": "eMeet Luna Mono", "id": 2},
    ]

    audio = Audio(device_name="eMeet Luna Mono")
    assert "eMeet Luna" in audio.device_name


def test_match_device_name() -> None:
  from device.core.audio import match_device_name

  # Exact match
  assert match_device_name("eMeet Luna Mono", "eMeet Luna Mono") is True
  # Substring matches
  assert match_device_name("eMeet Luna", "eMeet Luna Mono") is True
  assert match_device_name("eMeet Luna Mono", "eMeet Luna") is True
  # Mismatched/different devices
  assert match_device_name("eMeet Luna: USB Audio (hw:2,0)", "Built-in Audio Analog Stereo") is False
  assert match_device_name("Built-in Audio Analog Stereo", "Built-in Audio Analog Stereo") is True


def test_find_device_by_name_exact_matching() -> None:
  from device.core.audio import find_device_by_name

  devs = [
    {"name": "USB Audio and HID, USB Audio", "id": 1},
    {"name": "BY-BMW700, USB Audio", "id": 2},
    {"name": "Built-in Audio Analog Stereo", "id": 3},
  ]

  selected = find_device_by_name("BY-BMW700, USB Audio", devs)
  assert selected is not None
  assert selected["name"] == "BY-BMW700, USB Audio"

  selected_hid = find_device_by_name("USB Audio and HID, USB Audio", devs)
  assert selected_hid is not None
  assert selected_hid["name"] == "USB Audio and HID, USB Audio"


def test_find_device_by_name_ignores_unusable_devices_when_physical_filtered() -> None:
  from device.core.audio import find_device_by_name

  devices = [
    {
      "name": "Discard all samples (playback) or generate zero samples (capture)",
      "id": 0,
      "formats": [{"samplerate": 48000, "channels": 0}],
    },
    {
      "name": "eMeet Luna Mono",
      "id": 2,
      "formats": [{"samplerate": 16000, "channels": 1}],
    },
  ]

  assert find_device_by_name("Discard all samples (playback)", devices, filter_physical=True) is None
  selected = find_device_by_name("eMeet Luna Mono", devices, filter_physical=True)
  assert selected is not None
  assert selected["name"] == "eMeet Luna Mono"


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


def test_find_compatible_device_ignores_discard_and_zero_channel_devices() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {
        "name": "Discard all samples (playback) or generate zero samples (capture)",
        "id": 0,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
      {
        "name": "Default Audio Device",
        "id": 1,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
      {
        "name": "eMeet Luna Mono",
        "id": 2,
        "formats": [{"samplerate": 16000, "channels": 1}],
      },
    ]

    compatible = Audio.find_compatible_device()

  assert compatible is not None
  assert compatible["name"] == "eMeet Luna Mono"


def test_find_compatible_device_returns_none_when_only_unusable_devices_exist() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {
        "name": "Discard all samples (playback) or generate zero samples (capture)",
        "id": 0,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
      {
        "name": "Default Audio Device",
        "id": 1,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
    ]

    assert Audio.find_compatible_device() is None


def test_get_compatible_input_devices_excludes_discard_and_zero_channel_devices() -> None:
  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.return_value = [
      {
        "name": "Discard all samples (playback) or generate zero samples (capture)",
        "id": 0,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
      {
        "name": "Default Audio Device",
        "id": 1,
        "formats": [{"samplerate": 48000, "channels": 0}],
      },
      {
        "name": "eMeet Luna Mono",
        "id": 2,
        "formats": [{"samplerate": 16000, "channels": 1}],
      },
    ]

    assert Audio.get_compatible_input_devices() == ["eMeet Luna Mono"]


@pytest.mark.asyncio
async def test_monitor_devices_keeps_selected_microphone_when_device_list_changes(monkeypatch) -> None:
  from device.core.settings import Settings
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    microphone_device="eMeet Luna Mono",
  )
  service = AudioService(settings)
  service.audio_stream = MagicMock()
  queue: asyncio.Queue[str] = asyncio.Queue()
  device_lists = [
    [{"name": "eMeet Luna Mono", "id": 1}],
    [{"name": "eMeet Luna Mono", "id": 1}, {"name": "Camera Mono", "id": 2}],
    [{"name": "eMeet Luna Mono", "id": 1}],
    [{"name": "Camera Mono", "id": 2}, {"name": "eMeet Luna Mono", "id": 1}],
  ]
  index = 0

  def get_captures():
    nonlocal index
    result = device_lists[min(index, len(device_lists) - 1)]
    index += 1
    return result

  original_sleep = asyncio.sleep

  async def fast_sleep(_: float) -> None:
    await original_sleep(0.01)

  monkeypatch.setattr("device.services.audio_service.asyncio.sleep", fast_sleep)

  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.side_effect = get_captures
    task = asyncio.create_task(service.monitor_devices(queue))
    await original_sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
      await task

  assert queue.empty()


@pytest.mark.asyncio
async def test_monitor_devices_ignores_transient_device_query_failures(monkeypatch) -> None:
  from device.core.settings import Settings
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    microphone_device="eMeet Luna Mono",
  )
  service = AudioService(settings)
  queue: asyncio.Queue[str] = asyncio.Queue()
  calls = 0

  def get_captures():
    nonlocal calls
    calls += 1

    if calls == 2:
      raise OSError("can't get device info")

    return [{"name": "eMeet Luna Mono", "id": 1}]

  original_sleep = asyncio.sleep

  async def fast_sleep(_: float) -> None:
    await original_sleep(0.01)

  monkeypatch.setattr("device.services.audio_service.asyncio.sleep", fast_sleep)

  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.side_effect = get_captures
    task = asyncio.create_task(service.monitor_devices(queue))
    await original_sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
      await task

  assert queue.empty()


def test_select_speaker_updates_state_and_verifies() -> None:
  from device.core.settings import Settings
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    speaker_device="Built-in Audio",
  )
  service = AudioService(settings)
  service.speaker = MagicMock()
  service.speaker.device_name = "Built-in Audio"
  service.speaker.select_device.return_value = "eMeet Luna Mono"
  service.speaker_state = {"device": "Built-in Audio", "muted": False, "volume": 1.0}

  assert service.select_speaker("eMeet Luna Mono") is True
  service.speaker.select_device.assert_called_with("eMeet Luna Mono")
  service.speaker.verify_device.assert_called_once()
  assert service.speaker_state["device"] == "eMeet Luna Mono"


def test_select_speaker_reverts_when_device_cannot_be_opened() -> None:
  from device.core.settings import Settings
  from device.core.speaker import SpeakerDeviceError
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    speaker_device="Built-in Audio",
  )
  service = AudioService(settings)
  service.speaker = MagicMock()
  service.speaker.device_name = "Built-in Audio"
  service.speaker.select_device.side_effect = ["Broken Speaker", "Built-in Audio"]
  service.speaker.verify_device.side_effect = SpeakerDeviceError("failed to init device")
  service.speaker_state = {"device": "Built-in Audio", "muted": False, "volume": 1.0}

  assert service.select_speaker("Broken Speaker") is False
  assert service.speaker.select_device.call_args_list[0].args == ("Broken Speaker",)
  assert service.speaker.select_device.call_args_list[1].args == ("Built-in Audio",)
  assert service.speaker_state["device"] == "Built-in Audio"


@pytest.mark.asyncio
async def test_monitor_devices_reopens_selected_microphone_after_reappearing(monkeypatch) -> None:
  from device.core.settings import Settings
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    microphone_device="eMeet Luna Mono",
  )
  service = AudioService(settings)
  service.audio_stream = MagicMock()
  queue: asyncio.Queue[str] = asyncio.Queue()
  device_lists = [
    [{"name": "eMeet Luna Mono", "id": 1}],
    [{"name": "Camera Mono", "id": 2}],
    [{"name": "eMeet Luna Mono", "id": 1}],
  ]
  index = 0

  def get_captures():
    nonlocal index
    result = device_lists[min(index, len(device_lists) - 1)]
    index += 1
    return result

  original_sleep = asyncio.sleep

  async def fast_sleep(_: float) -> None:
    await original_sleep(0.01)

  monkeypatch.setattr("device.services.audio_service.asyncio.sleep", fast_sleep)

  with patch("miniaudio.Devices") as mock_devices:
    mock_devices.return_value.get_captures.side_effect = get_captures
    task = asyncio.create_task(service.monitor_devices(queue))
    await original_sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
      await task

  assert queue.get_nowait() == "eMeet Luna Mono"


def test_speaker_initialization_falls_back_to_default_device() -> None:
  from device.core.settings import Settings
  from device.core.speaker import SpeakerDeviceError
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    mqtt_broker="localhost",
    microphone_enabled=False,
    speaker_enabled=True,
    speaker_device="Broken Speaker",
  )
  service = AudioService(settings)
  broken_speaker = MagicMock()
  broken_speaker.verify_device.side_effect = SpeakerDeviceError("failed to init device")
  default_speaker = MagicMock()
  default_speaker.device_name = "Built-in Audio"
  default_speaker.info = {"device": "Built-in Audio"}

  with patch("device.services.audio_service.Speaker", side_effect=[broken_speaker, default_speaker]):
    service.initialize_hardware()

  assert service.speaker is default_speaker
  assert service.speaker_enabled is True
  assert service.speaker_state["device"] == "Built-in Audio"
  assert settings.speaker_device == "Built-in Audio"


def test_speaker_initialization_disables_speaker_when_default_fails() -> None:
  from device.core.settings import Settings
  from device.core.speaker import SpeakerDeviceError
  from device.services.audio_service import AudioService

  settings = Settings(
    _env_file=None,
    node_id="test-node",
    mqtt_broker="localhost",
    microphone_enabled=False,
    speaker_enabled=True,
    speaker_device="Broken Speaker",
  )
  service = AudioService(settings)
  configured_speaker = MagicMock()
  configured_speaker.verify_device.side_effect = SpeakerDeviceError("failed to init device")
  default_speaker = MagicMock()
  default_speaker.verify_device.side_effect = SpeakerDeviceError("default failed too")

  with patch("device.services.audio_service.Speaker", side_effect=[configured_speaker, default_speaker]):
    service.initialize_hardware()

  assert service.speaker is None
  assert service.speaker_enabled is False
