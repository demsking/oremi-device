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
import pytest
from pydantic import ValidationError

from oremi_device.core.settings import DeviceSettings


REQUIRED_SETTINGS = {
  "node_id": "test-node",
  "ohunerin_host": "localhost",
  "andika_host": "localhost",
  "mqtt_broker": "localhost",
}


def test_settings_defaults() -> None:
  settings = DeviceSettings(_env_file=None, **REQUIRED_SETTINGS)

  assert settings.microphone_enabled is True
  assert settings.speaker_enabled is True
  assert settings.microphone_device is None
  assert settings.microphone_device_index is None
  assert settings.ohunerin_threshold == 0.65
  assert settings.andika_model == "vosk-model-small-fr-0.22"
  assert settings.andika_samplerate == 16000
  assert settings.partial_transcription_topic == "transcription/partial"
  assert settings.final_transcription_topic == "transcription/text"


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("OREMI_DEVICE_NODE_ID", "kitchen")
  monkeypatch.setenv("OREMI_DEVICE_OHUNERIN_HOST", "ohunerin")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_HOST", "andika")
  monkeypatch.setenv("OREMI_DEVICE_MQTT_BROKER", "mqtt")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_ENABLED", "false")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE", "USB Microphone")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE_INDEX", "2")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_SAMPLERATE", "48000")
  monkeypatch.setenv("OREMI_DEVICE_PARTIAL_TRANSCRIPTION_TOPIC", "speech/in-progress")
  monkeypatch.setenv("OREMI_DEVICE_FINAL_TRANSCRIPTION_TOPIC", "speech/final")

  settings = DeviceSettings(_env_file=None)

  assert settings.node_id == "kitchen"
  assert settings.microphone_enabled is False
  assert settings.microphone_device == "USB Microphone"
  assert settings.microphone_device_index == 2
  assert settings.andika_samplerate == 48000
  assert settings.partial_transcription_topic == "speech/in-progress"
  assert settings.final_transcription_topic == "speech/final"


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("conversation_timeout", 0),
    ("language", "de"),
    ("ohunerin_threshold", 0),
    ("andika_model", "unsupported"),
    ("andika_samplerate", 0),
  ],
)
def test_invalid_settings_are_rejected(field: str, value: object) -> None:
  with pytest.raises(ValidationError):
    DeviceSettings(_env_file=None, **REQUIRED_SETTINGS, **{field: value})
