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

from oremi_device.core.args import parse_arguments


BASE_ARGS = [
  "oremi-device",
  "start",
  "--node-id",
  "test-node",
  "--ohunerin-host",
  "localhost",
  "--andika-host",
  "localhost",
  "--mqtt-broker",
  "localhost",
]


def test_audio_devices_default() -> None:
  with patch("sys.argv", BASE_ARGS):
    args = parse_arguments()

  assert args.microphone_enabled is True
  assert args.speaker_enabled is True


def test_audio_devices_disabled() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--no-microphone", "--no-speaker"]):
    args = parse_arguments()

  assert args.microphone_enabled is False
  assert args.speaker_enabled is False
