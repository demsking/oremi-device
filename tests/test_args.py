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

from oremi_device.core.args import parse_arguments


BASE_ARGS = [
  "oremi-device",
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


def test_debug_option_is_rejected() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--debug"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()


def test_conversation_timeout_must_be_positive() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--conversation-timeout", "0"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()


def test_language_must_be_supported() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--language", "de"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()


def test_component_options_default() -> None:
  with patch("sys.argv", BASE_ARGS):
    args = parse_arguments()

  assert args.ohunerin_threshold == 0.65
  assert args.andika_model == "vosk-model-small-fr-0.22"
  assert args.andika_samplerate == 16000


def test_component_options_can_be_overridden() -> None:
  with patch(
    "sys.argv",
    [
      *BASE_ARGS,
      "--ohunerin-threshold",
      "0.75",
      "--andika-model",
      "vosk-model-small-en-us-0.15",
      "--andika-samplerate",
      "48000",
    ],
  ):
    args = parse_arguments()

  assert args.ohunerin_threshold == 0.75
  assert args.andika_model == "vosk-model-small-en-us-0.15"
  assert args.andika_samplerate == 48000


def test_ohunerin_threshold_must_be_positive() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--ohunerin-threshold", "0"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()


def test_andika_model_must_be_supported() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--andika-model", "unsupported"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()


def test_andika_samplerate_must_be_positive() -> None:
  with patch("sys.argv", [*BASE_ARGS, "--andika-samplerate", "0"]):
    with pytest.raises(SystemExit, match="2"):
      parse_arguments()
