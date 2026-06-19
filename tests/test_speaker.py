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
from unittest.mock import patch

import pytest

from oremi_device.core.speaker import Speaker
from oremi_device.core.speaker import SpeakerDeviceError


@patch("sounddevice.query_devices")
def test_default_output(mock_query_devices) -> None:
  mock_query_devices.return_value = {"name": "Built-in Audio", "max_output_channels": 2}

  speaker = Speaker(volume=0.5)

  assert speaker.device_name == "Built-in Audio"
  assert speaker.volume == 0.5
  assert speaker.gain == 0.5


def test_muted_gain() -> None:
  with patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2}):
    speaker = Speaker(volume=0.75)

  speaker.set_muted(True)
  assert speaker.muted is True
  assert speaker.gain == 0.0


def test_invalid_volume() -> None:
  with patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2}):
    speaker = Speaker()

  with pytest.raises(ValueError):
    speaker.set_volume(1.1)


@patch("sounddevice.check_output_settings")
@patch("sounddevice.query_devices")
def test_select_output(mock_query_devices, mock_check_output) -> None:
  mock_query_devices.side_effect = [
    {"name": "Built-in Audio", "max_output_channels": 2},
    [
      {"name": "Microphone", "max_output_channels": 0},
      {"name": "USB Speaker", "max_output_channels": 2},
    ],
  ]
  speaker = Speaker()

  assert speaker.select_device("usb") == "USB Speaker"
  assert speaker.device_name == "USB Speaker"
  mock_check_output.assert_called_with(device="USB Speaker")


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 0})
def test_output_required(mock_query_devices) -> None:
  with pytest.raises(SpeakerDeviceError):
    Speaker()


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
def test_empty_output_rejected(mock_query_devices) -> None:
  speaker = Speaker()

  with pytest.raises(SpeakerDeviceError):
    speaker.select_device("  ")
