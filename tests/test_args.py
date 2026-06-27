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
import os

import pytest
from pydantic import ValidationError

from oremi_device.core.settings import apply_runtime_settings_cache
from oremi_device.core.settings import DeviceSettings
from oremi_device.core.settings import format_settings_errors
from oremi_device.core.settings import load_settings
from oremi_device.core.settings import read_runtime_settings_cache
from oremi_device.core.settings import RuntimeSettingsCache
from oremi_device.core.settings import update_runtime_settings_cache


REQUIRED_SETTINGS = {
  "node_id": "test-node",
  "ohunerin_host": "localhost",
  "andika_host": "localhost",
  "mqtt_broker": "localhost",
}


@pytest.fixture(autouse=True)
def clean_oremi_environment(monkeypatch: pytest.MonkeyPatch) -> None:
  for name in tuple(os.environ):
    if name.startswith("OREMI_DEVICE_"):
      monkeypatch.delenv(name)


def test_settings_defaults() -> None:
  settings = DeviceSettings(_env_file=None, **REQUIRED_SETTINGS)

  assert settings.microphone_enabled is True
  assert settings.speaker_enabled is True
  assert settings.microphone_device is None
  assert settings.microphone_device_index is None
  assert settings.microphone_muted is False
  assert settings.speaker_device is None
  assert settings.speaker_muted is False
  assert settings.speaker_volume == 1.0
  assert settings.ohunerin_threshold == 0.25
  assert settings.andika_model == "vosk-model-small-fr-0.22"
  assert settings.andika_samplerate == 16000
  assert settings.transcription_backend == "andika"
  assert settings.whisper_url is None
  assert settings.tts_backend == "izwi"
  assert settings.izwi_url is None
  assert settings.edge_tts_url is None


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("OREMI_DEVICE_NODE_ID", "kitchen")
  monkeypatch.setenv("OREMI_DEVICE_OHUNERIN_HOST", "ohunerin")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_HOST", "andika")
  monkeypatch.setenv("OREMI_DEVICE_MQTT_BROKER", "mqtt")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_ENABLED", "false")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE", "USB Microphone")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE_INDEX", "2")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_SAMPLERATE", "48000")
  monkeypatch.setenv("OREMI_DEVICE_TTS_BACKEND", "edge-tts")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_URL", "http://edge-tts:5050")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_API_KEY", "test-key")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_LOCALE", "fr-FR")

  settings = DeviceSettings(_env_file=None)

  assert settings.node_id == "kitchen"
  assert settings.microphone_enabled is False
  assert settings.microphone_device == "USB Microphone"
  assert settings.microphone_device_index == 2
  assert settings.andika_samplerate == 48000
  assert settings.tts_backend == "edge-tts"
  assert str(settings.edge_tts_url) == "http://edge-tts:5050/"
  assert settings.edge_tts_api_key == "test-key"
  assert settings.edge_tts_locale == "fr-FR"


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("conversation_timeout", 0),
    ("language", "de"),
    ("ohunerin_threshold", 0),
    ("andika_model", "unsupported"),
    ("andika_samplerate", 0),
    ("speaker_volume", 1.1),
    ("izwi_url", "not-a-url"),
    ("edge_tts_url", "not-a-url"),
    ("edge_tts_speed", 0.0),
    ("edge_tts_response_format", "ogg"),
  ],
)
def test_invalid_settings_are_rejected(field: str, value: object) -> None:
  with pytest.raises(ValidationError):
    DeviceSettings(_env_file=None, **REQUIRED_SETTINGS, **{field: value})


def test_whisper_backend_does_not_require_andika_host() -> None:
  settings = DeviceSettings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    mqtt_broker="localhost",
    transcription_backend="whisper.cpp",
    whisper_url="http://whisper:8080",
  )

  assert settings.andika_host is None
  assert str(settings.whisper_url) == "http://whisper:8080/"


def test_whisper_backend_requires_url() -> None:
  with pytest.raises(ValidationError, match="OREMI_DEVICE_WHISPER_URL is required"):
    DeviceSettings(
      _env_file=None,
      node_id="test-node",
      ohunerin_host="localhost",
      mqtt_broker="localhost",
      transcription_backend="whisper.cpp",
    )


def test_edge_tts_backend_requires_url() -> None:
  with pytest.raises(ValidationError, match="OREMI_DEVICE_EDGE_TTS_URL is required"):
    DeviceSettings(_env_file=None, **REQUIRED_SETTINGS, tts_backend="edge-tts")


def test_settings_errors_are_formatted_without_technical_details(monkeypatch: pytest.MonkeyPatch) -> None:
  with pytest.raises(ValidationError) as exc_info:
    DeviceSettings(_env_file=None, language="de", izwi_url="secret-invalid-url")

  issues = format_settings_errors(exc_info.value)

  assert issues == [
    "OREMI_DEVICE_LANGUAGE must be one of: fr, en",
    "OREMI_DEVICE_OHUNERIN_HOST is required",
    "OREMI_DEVICE_IZWI_URL must be a valid HTTP or HTTPS URL",
    "OREMI_DEVICE_NODE_ID is required",
    "OREMI_DEVICE_MQTT_BROKER is required",
  ]
  output = "\n".join(issues)
  assert "secret-invalid-url" not in output
  assert "pydantic" not in output.lower()
  assert "input_value" not in output


def test_runtime_settings_cache_overrides_mutable_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
  data_dir = tmp_path / "data"
  data_dir.mkdir()
  cache_file = data_dir / "kitchen.json"
  cache_file.write_text(
    json.dumps(
      {
        "language": "en",
        "microphone_device": "USB Microphone",
        "microphone_muted": True,
        "speaker_device": "USB Speaker",
        "speaker_muted": True,
        "speaker_volume": 0.35,
        "tts_voice": "en-US-JennyNeural",
      }
    ),
    encoding="utf-8",
  )

  monkeypatch.setenv("OREMI_DEVICE_NODE_ID", "kitchen")
  monkeypatch.setenv("OREMI_DEVICE_OHUNERIN_HOST", "ohunerin")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_HOST", "andika")
  monkeypatch.setenv("OREMI_DEVICE_MQTT_BROKER", "mqtt")
  monkeypatch.setenv("OREMI_DEVICE_LANGUAGE", "fr")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE_INDEX", "2")
  monkeypatch.setenv("OREMI_DEVICE_DATA", str(data_dir))

  settings = load_settings()

  assert settings.language == "en"
  assert settings.microphone_device == "USB Microphone"
  assert settings.microphone_device_index is None
  assert settings.microphone_muted is True
  assert settings.speaker_device == "USB Speaker"
  assert settings.speaker_muted is True
  assert settings.speaker_volume == 0.35
  assert settings.tts_voice == "en-US-JennyNeural"


def test_runtime_settings_cache_update_preserves_existing_values(tmp_path) -> None:
  settings = DeviceSettings(_env_file=None, **REQUIRED_SETTINGS, data=tmp_path)
  cache_file = tmp_path / "test-node.json"

  update_runtime_settings_cache(settings, language="en", speaker_volume=0.4)
  update_runtime_settings_cache(settings, speaker_muted=True)

  assert json.loads(cache_file.read_text(encoding="utf-8")) == {
    "language": "en",
    "speaker_muted": True,
    "speaker_volume": 0.4,
  }


def test_invalid_runtime_settings_cache_is_ignored(tmp_path) -> None:
  settings = DeviceSettings(_env_file=None, **REQUIRED_SETTINGS, data=tmp_path)
  cache_file = tmp_path / "test-node.json"
  cache_file.write_text('{"language":"de","speaker_volume":2}', encoding="utf-8")

  cache = read_runtime_settings_cache(settings)
  applied = apply_runtime_settings_cache(settings, cache)

  assert cache == RuntimeSettingsCache()
  assert applied.language == "fr"
  assert applied.speaker_volume == 1.0
