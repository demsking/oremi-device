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
from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from device.core.geocode import get_location_geocode
from device.core.settings import apply_runtime_settings_cache
from device.core.settings import format_settings_errors
from device.core.settings import get_settings
from device.core.settings import read_runtime_settings_cache
from device.core.settings import RuntimeSettingsCache
from device.core.settings import Settings
from device.core.settings import update_runtime_settings_cache
from device.core.timezone import infer_timezone_from_coordinates


REQUIRED_SETTINGS = {
  "node_id": "test-node",
  "ohunerin_host": "localhost",
  "andika_host": "localhost",
  "mqtt_broker": "localhost",
}


@pytest.fixture(autouse=True)
def clean_oremi_environment(monkeypatch: pytest.MonkeyPatch) -> None:
  get_settings.cache_clear()

  for name in tuple(os.environ):
    if name.startswith("OREMI_DEVICE_"):
      monkeypatch.delenv(name)


def test_settings_defaults() -> None:
  settings = Settings(_env_file=None, **REQUIRED_SETTINGS)

  assert settings.microphone_enabled is True
  assert settings.location == ""
  assert settings.context["timezone"] == "UTC"
  assert settings.temperature_unit == "celsius"
  assert settings.preferred_currency == "XAF"
  assert settings.measurement_system == "metric"
  assert settings.distance_unit == "kilometer"
  assert settings.time_format == "24h"
  assert settings.date_format == "DD/MM/YYYY"
  assert settings.first_day_of_week == "monday"
  assert settings.speaker_enabled is True
  assert settings.microphone_device is None
  assert settings.microphone_device_index is None
  assert settings.microphone_muted is False
  assert settings.speaker_device is None
  assert settings.speaker_muted is False
  assert settings.speaker_volume == 1.0
  assert settings.akorin_url is None
  assert settings.ohunerin_threshold == 0.25
  assert settings.andika_model == "vosk-model-small-fr-0.22"
  assert settings.andika_samplerate == 16000
  assert settings.transcription_backend == "andika"
  assert settings.whisper_url is None
  assert settings.tts_backend == "izwi"
  assert settings.izwi_url is None
  assert settings.edge_tts_url is None


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(
    "device.core.settings.get_location_geocode",
    lambda location: SimpleNamespace(latitude=48.8566, longitude=2.3522, address=location),
  )
  monkeypatch.setattr(
    "device.core.settings.infer_timezone_from_coordinates",
    lambda *, latitude, longitude: "Europe/Paris",
  )
  monkeypatch.setenv("OREMI_DEVICE_NODE_ID", "kitchen")
  monkeypatch.setenv("OREMI_DEVICE_OHUNERIN_HOST", "ohunerin")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_HOST", "andika")
  monkeypatch.setenv("OREMI_DEVICE_MQTT_BROKER", "mqtt")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_ENABLED", "false")
  monkeypatch.setenv("OREMI_DEVICE_LOCATION", "12 Rue de Rivoli, Paris")
  monkeypatch.setenv("OREMI_DEVICE_TEMPERATURE_UNIT", "fahrenheit")
  monkeypatch.setenv("OREMI_DEVICE_PREFERRED_CURRENCY", "usd")
  monkeypatch.setenv("OREMI_DEVICE_MEASUREMENT_SYSTEM", "imperial")
  monkeypatch.setenv("OREMI_DEVICE_DISTANCE_UNIT", "mile")
  monkeypatch.setenv("OREMI_DEVICE_TIME_FORMAT", "12h")
  monkeypatch.setenv("OREMI_DEVICE_DATE_FORMAT", "MM/DD/YYYY")
  monkeypatch.setenv("OREMI_DEVICE_FIRST_DAY_OF_WEEK", "sunday")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE", "USB Microphone")
  monkeypatch.setenv("OREMI_DEVICE_MICROPHONE_DEVICE_INDEX", "2")
  monkeypatch.setenv("OREMI_DEVICE_ANDIKA_SAMPLERATE", "48000")
  monkeypatch.setenv("OREMI_DEVICE_TTS_BACKEND", "edge-tts")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_URL", "http://edge-tts:5050")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_API_KEY", "test-key")
  monkeypatch.setenv("OREMI_DEVICE_EDGE_TTS_LOCALE", "fr-FR")

  settings = Settings(_env_file=None)

  assert settings.node_id == "kitchen"
  assert settings.microphone_enabled is False
  assert settings.location == "12 Rue de Rivoli, Paris"
  assert settings.context["timezone"] == "Europe/Paris"
  assert settings.temperature_unit == "fahrenheit"
  assert settings.preferred_currency == "USD"
  assert settings.measurement_system == "imperial"
  assert settings.distance_unit == "mile"
  assert settings.time_format == "12h"
  assert settings.date_format == "MM/DD/YYYY"
  assert settings.first_day_of_week == "sunday"
  context = settings.context
  device_datetime = datetime.fromisoformat(context.pop("device_datetime"))

  assert device_datetime.tzinfo is not None
  assert context == {
    "language": "fr",
    "location": "12 Rue de Rivoli, Paris",
    "timezone": "Europe/Paris",
    "temperature_unit": "fahrenheit",
    "preferred_currency": "USD",
    "measurement_system": "imperial",
    "distance_unit": "mile",
    "time_format": "12h",
    "date_format": "MM/DD/YYYY",
    "first_day_of_week": "sunday",
    "latitude": 48.8566,
    "longitude": 2.3522,
    "address": "12 Rue de Rivoli, Paris",
  }
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
    ("timezone", "Invalid/Timezone"),
    ("temperature_unit", "kelvin"),
    ("preferred_currency", "EURO"),
    ("measurement_system", "customary"),
    ("distance_unit", "meter"),
    ("time_format", "24-hour"),
    ("date_format", "YYYY/MM/DD"),
    ("first_day_of_week", "friday"),
    ("akorin_url", "not-a-url"),
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
    Settings(_env_file=None, **REQUIRED_SETTINGS, **{field: value})


def test_whisper_backend_does_not_require_andika_host() -> None:
  settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    mqtt_broker="localhost",
    transcription_backend="whisper.cpp",
    whisper_url="http://whisper:8080",
  )

  assert settings.andika_host is None
  assert str(settings.whisper_url) == "http://whisper:8080/"


def test_get_location_geocode_normalizes_location(monkeypatch: pytest.MonkeyPatch) -> None:
  result = object()
  calls = []

  def geocode(location: str) -> object:
    calls.append(location)
    return result

  monkeypatch.setattr("device.core.geocode._geocoder", SimpleNamespace(geocode=geocode))

  assert get_location_geocode("  12 Rue de Rivoli, Paris  ") is result
  assert calls == ["12 Rue de Rivoli, Paris"]


def test_timezone_is_inferred_from_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
  calls = []

  def timezone_at(*, lat: float, lng: float) -> str:
    calls.append({"lat": lat, "lng": lng})
    return "Europe/Paris"

  monkeypatch.setattr("device.core.timezone._timezone_finder", SimpleNamespace(timezone_at=timezone_at))

  assert infer_timezone_from_coordinates(latitude=48.8566, longitude=2.3522) == "Europe/Paris"
  assert calls == [{"lat": 48.8566, "lng": 2.3522}]


@pytest.mark.parametrize("timezone", [None, "Invalid/Timezone"])
def test_invalid_timezone_coordinates_return_none(monkeypatch: pytest.MonkeyPatch, timezone: str | None) -> None:
  monkeypatch.setattr(
    "device.core.timezone._timezone_finder",
    SimpleNamespace(timezone_at=lambda *, lat, lng: timezone),
  )

  assert infer_timezone_from_coordinates(latitude=0.0, longitude=0.0) is None


def test_whisper_backend_requires_url() -> None:
  with pytest.raises(ValidationError, match="OREMI_DEVICE_WHISPER_URL is required"):
    Settings(
      _env_file=None,
      node_id="test-node",
      ohunerin_host="localhost",
      mqtt_broker="localhost",
      transcription_backend="whisper.cpp",
    )


def test_edge_tts_backend_requires_url() -> None:
  with pytest.raises(ValidationError, match="OREMI_DEVICE_EDGE_TTS_URL is required"):
    Settings(_env_file=None, **REQUIRED_SETTINGS, tts_backend="edge-tts")


def test_settings_errors_are_formatted_without_technical_details(monkeypatch: pytest.MonkeyPatch) -> None:
  with pytest.raises(ValidationError) as exc_info:
    Settings(_env_file=None, language="de", izwi_url="secret-invalid-url")

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
        "location": "12 Rue de Rivoli, Paris",
        "timezone": "Europe/Paris",
        "temperature_unit": "fahrenheit",
        "preferred_currency": "usd",
        "measurement_system": "imperial",
        "distance_unit": "mile",
        "time_format": "12h",
        "date_format": "MM/DD/YYYY",
        "first_day_of_week": "sunday",
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
  monkeypatch.setenv("OREMI_DEVICE_DATA_PATH", str(data_dir))

  settings = get_settings()

  assert settings.language == "en"
  assert settings.location == "12 Rue de Rivoli, Paris"
  assert settings.context["timezone"] == "Europe/Paris"
  assert settings.timezone == "Europe/Paris"
  assert settings.temperature_unit == "fahrenheit"
  assert settings.preferred_currency == "USD"
  assert settings.measurement_system == "imperial"
  assert settings.distance_unit == "mile"
  assert settings.time_format == "12h"
  assert settings.date_format == "MM/DD/YYYY"
  assert settings.first_day_of_week == "sunday"
  assert settings.microphone_device == "USB Microphone"
  assert settings.microphone_device_index is None
  assert settings.microphone_muted is True
  assert settings.speaker_device == "USB Speaker"
  assert settings.speaker_muted is True
  assert settings.speaker_volume == 0.35
  assert settings.tts_voice == "en-US-JennyNeural"


def test_runtime_settings_cache_update_preserves_existing_values(tmp_path) -> None:
  settings = Settings(_env_file=None, **REQUIRED_SETTINGS, data_path=tmp_path)
  cache_file = tmp_path / "test-node.json"

  update_runtime_settings_cache(
    settings,
    language="en",
    location="12 Rue de Rivoli, Paris",
    speaker_volume=0.4,
  )
  update_runtime_settings_cache(settings, speaker_muted=True)

  assert json.loads(cache_file.read_text(encoding="utf-8")) == {
    "language": "en",
    "location": "12 Rue de Rivoli, Paris",
    "speaker_muted": True,
    "speaker_volume": 0.4,
  }


def test_invalid_runtime_settings_cache_is_ignored(tmp_path) -> None:
  settings = Settings(_env_file=None, **REQUIRED_SETTINGS, data_path=tmp_path)
  cache_file = tmp_path / "test-node.json"
  cache_file.write_text('{"language":"de","speaker_volume":2}', encoding="utf-8")

  cache = read_runtime_settings_cache(settings)
  applied = apply_runtime_settings_cache(settings, cache)

  assert cache == RuntimeSettingsCache()
  assert applied.language == "fr"
  assert applied.speaker_volume == 1.0


def test_get_location_geocode_handles_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
  from geopy.exc import GeocoderUnavailable
  from device.core.geocode import is_geocode_unavailable, _unavailable_locations

  _unavailable_locations.clear()

  def geocode(location: str) -> None:
    raise GeocoderUnavailable("Service temporarily down")

  monkeypatch.setattr("device.core.geocode._geocoder", SimpleNamespace(geocode=geocode))

  assert get_location_geocode("Paris") is None
  assert is_geocode_unavailable("Paris") is True

  # Succeeded request clears unavailable status
  def geocode_ok(location: str) -> object:
    return SimpleNamespace(latitude=1.0, longitude=2.0, address=location)

  monkeypatch.setattr("device.core.geocode._geocoder", SimpleNamespace(geocode=geocode_ok))
  assert get_location_geocode("Paris") is not None
  assert is_geocode_unavailable("Paris") is False
