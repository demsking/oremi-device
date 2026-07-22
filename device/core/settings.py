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
import logging
import os
from datetime import datetime
from functools import cached_property
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal
from typing import TypedDict
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from device.core.geocode import get_location_geocode
from device.core.models import AndikaModel
from device.core.package import APP_NAME
from device.core.package import APP_VERSION
from device.core.timezone import infer_timezone_from_coordinates


DEFAULT_TIMEZONE = "UTC"
logger = logging.getLogger(__name__)

LanguageSetting = Literal["fr", "en"]
TemperatureUnitSetting = Literal["celsius", "fahrenheit"]
MeasurementSystemSetting = Literal["metric", "imperial"]
DistanceUnitSetting = Literal["kilometer", "mile"]
TimeFormatSetting = Literal["12h", "24h"]
DateFormatSetting = Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"]
FirstDayOfWeekSetting = Literal["monday", "sunday", "saturday"]
TranscriptionBackendSetting = Literal["andika", "whisper.cpp"]
TTSBackendSetting = Literal["izwi", "edge-tts"]
EdgeTTSResponseFormatSetting = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]
LogLevelSetting = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class SettingsError(Exception):
  """User-facing configuration validation failure."""

  def __init__(self, issues: list[str]) -> None:
    super().__init__("Invalid application configuration")
    self.issues = issues


def format_settings_errors(error: ValidationError) -> list[str]:
  """Convert Pydantic details into concise environment-variable errors."""
  issues = []

  for detail in error.errors(include_url=False, include_input=False):
    location = detail.get("loc", ())
    field = str(location[0]) if location else "configuration"
    setting = f"OREMI_DEVICE_{field.upper()}"
    error_type = detail.get("type")
    context = detail.get("ctx", {})

    if not location and error_type == "value_error":
      issues.append(str(context.get("error", "Invalid transcription backend configuration")))
      continue

    if error_type == "missing":
      message = "is required"
    elif field == "language" and error_type == "literal_error":
      message = "must be one of: fr, en"
    elif field == "preferred_currency" and error_type == "string_pattern_mismatch":
      message = "must be a three-letter ISO 4217 currency code"
    elif field == "andika_model" and error_type == "literal_error":
      message = "contains an unsupported model identifier"
    elif field == "izwi_url" and error_type in ("url_parsing", "url_scheme"):
      message = "must be a valid HTTP or HTTPS URL"
    elif field == "edge_tts_url" and error_type in ("url_parsing", "url_scheme"):
      message = "must be a valid HTTP or HTTPS URL"
    elif field in ("tts_backend", "edge_tts_response_format") and error_type == "literal_error":
      message = "has an unsupported value"
    elif error_type == "greater_than":
      message = f"must be greater than {context['gt']}"
    elif error_type == "greater_than_equal":
      message = f"must be at least {context['ge']}"
    elif error_type == "less_than":
      message = f"must be less than {context['lt']}"
    elif error_type == "less_than_equal":
      message = f"must be at most {context['le']}"
    elif error_type in ("int_parsing", "int_type"):
      message = "must be an integer"
    elif error_type in ("float_parsing", "float_type"):
      message = "must be a number"
    elif error_type in ("bool_parsing", "bool_type"):
      message = "must be true or false"
    else:
      message = "has an invalid value"

    issues.append(f"{setting} {message}")

  return issues


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_prefix="OREMI_DEVICE_", env_file=".env", extra="ignore")

  server_host: str = "127.0.0.1"
  server_port: int = Field(default=5048, gt=0, le=65535)

  language: LanguageSetting = "fr"
  location: str = ""
  timezone: str = DEFAULT_TIMEZONE
  temperature_unit: TemperatureUnitSetting = "celsius"
  preferred_currency: str = Field(default="XAF", pattern=r"^[A-Z]{3}$")
  measurement_system: MeasurementSystemSetting = "metric"
  distance_unit: DistanceUnitSetting = "kilometer"
  time_format: TimeFormatSetting = "24h"
  date_format: DateFormatSetting = "DD/MM/YYYY"
  first_day_of_week: FirstDayOfWeekSetting = "monday"
  microphone_device_index: int | None = None
  microphone_device: str | None = None
  microphone_enabled: bool = True
  microphone_muted: bool = False
  speaker_enabled: bool = True
  speaker_device: str | None = None
  speaker_muted: bool = False
  speaker_volume: float = Field(default=1.0, ge=0, le=1)
  delay: int = Field(default=3, gt=0)
  conversation_timeout: float = Field(default=15.0, gt=0)

  akorin_url: HttpUrl | None = None

  ohunerin_host: str
  ohunerin_port: int = Field(default=5023, gt=0, le=65535)
  ohunerin_threshold: float = Field(default=0.25, gt=0)

  transcription_backend: TranscriptionBackendSetting = "andika"
  andika_host: str | None = None
  andika_port: int = Field(default=5315, gt=0, le=65535)
  andika_model: AndikaModel = "vosk-model-small-fr-0.22"
  andika_samplerate: int = Field(default=16000, gt=0)
  whisper_url: HttpUrl | None = None
  whisper_silence_threshold: int = Field(default=500, ge=0)
  whisper_silence_duration: float = Field(default=1.0, gt=0)

  tts_backend: TTSBackendSetting = "izwi"
  izwi_url: HttpUrl | None = None
  edge_tts_url: HttpUrl | None = None
  edge_tts_api_key: str = "your_api_key_here"
  edge_tts_locale: str | None = None
  edge_tts_model: str = "tts-1"
  edge_tts_response_format: EdgeTTSResponseFormatSetting = "mp3"
  edge_tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)
  tts_voice: str | None = None

  cert_file: str | None = None
  node_id: str
  data_path: Path = Field(default=None)  # type: ignore

  mqtt_broker: str
  mqtt_port: int = Field(default=1883, gt=0, le=65535)
  mqtt_username: str | None = None
  mqtt_password: str | None = None
  mqtt_topic: str = "oremi/device"
  mqtt_discovery: bool = True
  mqtt_discovery_prefix: str = "homeassistant"

  log_level: LogLevelSetting = Field(default="INFO")
  log_file: str | None = Field(default=None)

  @property
  def context(self) -> dict[str, Any]:
    context = {
      "language": self.language,
      "location": self.location,
      "timezone": self.timezone,
      "temperature_unit": self.temperature_unit,
      "preferred_currency": self.preferred_currency,
      "measurement_system": self.measurement_system,
      "distance_unit": self.distance_unit,
      "time_format": self.time_format,
      "date_format": self.date_format,
      "first_day_of_week": self.first_day_of_week,
    }

    location = get_location_geocode(self.location)

    if location:
      context["latitude"] = location.latitude
      context["longitude"] = location.longitude
      context["address"] = location.address
      inferred_timezone = infer_timezone_from_coordinates(latitude=location.latitude, longitude=location.longitude)

      if self.timezone == DEFAULT_TIMEZONE and inferred_timezone:
        context["timezone"] = inferred_timezone

    context["device_datetime"] = datetime.now(ZoneInfo(context["timezone"])).isoformat()

    return context

  @cached_property
  def user_agent(self) -> str:
    return f"{APP_NAME}/{APP_VERSION}/{self.node_id}"

  @cached_property
  def path(self) -> Path:
    return self.data_path / f"{self.node_id}.json"

  @field_validator("data_path", mode="before")
  @classmethod
  def validate_data_path(cls, value) -> Path:
    if value is not None:
      return value

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME

  @field_validator("preferred_currency", mode="before")
  @classmethod
  def normalize_preferred_currency(cls, value: str) -> str:
    return value.upper() if isinstance(value, str) else value

  @field_validator("timezone")
  @classmethod
  def validate_timezone(cls, value: str) -> str:
    try:
      ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
      raise ValueError("must be a valid IANA timezone") from error

    return value

  @model_validator(mode="after")
  def validate_backends(self) -> "Settings":
    if self.transcription_backend == "andika" and not self.andika_host:
      raise ValueError("OREMI_DEVICE_ANDIKA_HOST is required when using the Andika transcription backend")

    if self.transcription_backend == "whisper.cpp" and not self.whisper_url:
      raise ValueError("OREMI_DEVICE_WHISPER_URL is required when using the whisper.cpp transcription backend")

    if self.tts_backend == "edge-tts" and not self.edge_tts_url:
      raise ValueError("OREMI_DEVICE_EDGE_TTS_URL is required when using the Edge-TTS speech synthesis backend")

    return self


class SettingsUpdates(TypedDict, total=False):
  """Typed dictionary representing runtime settings update payloads."""

  language: LanguageSetting
  location: str | None
  timezone: str | None
  temperature_unit: TemperatureUnitSetting
  preferred_currency: str
  measurement_system: MeasurementSystemSetting
  distance_unit: DistanceUnitSetting
  time_format: TimeFormatSetting
  date_format: DateFormatSetting
  first_day_of_week: FirstDayOfWeekSetting
  microphone_device: str | None
  microphone_muted: bool
  speaker_device: str | None
  speaker_muted: bool
  speaker_volume: float
  tts_voice: str | None


class RuntimeSettingsCache(BaseModel):
  """Runtime settings changed through MQTT/Home Assistant controls."""

  language: LanguageSetting | None = None
  location: str | None = None
  timezone: str | None = None
  temperature_unit: TemperatureUnitSetting | None = None
  preferred_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
  measurement_system: MeasurementSystemSetting | None = None
  distance_unit: DistanceUnitSetting | None = None
  time_format: TimeFormatSetting | None = None
  date_format: DateFormatSetting | None = None
  first_day_of_week: FirstDayOfWeekSetting | None = None
  microphone_device: str | None = None
  microphone_muted: bool | None = None
  speaker_device: str | None = None
  speaker_muted: bool | None = None
  speaker_volume: float | None = Field(default=None, ge=0, le=1)
  tts_voice: str | None = None

  @field_validator("preferred_currency", mode="before")
  @classmethod
  def normalize_preferred_currency(cls, value: str | None) -> str | None:
    return value.upper() if isinstance(value, str) else value

  @field_validator("timezone")
  @classmethod
  def validate_timezone(cls, value: str | None) -> str | None:
    if value is None:
      return None

    try:
      ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
      raise ValueError("must be a valid IANA timezone") from error

    return value


def read_runtime_settings_cache(settings: Settings) -> RuntimeSettingsCache:
  if not settings.path.exists():
    return RuntimeSettingsCache()

  try:
    content = json.loads(settings.path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    logger.warning(f"Ignoring unreadable runtime settings cache {settings.path}: {error}")

    return RuntimeSettingsCache()

  try:
    return RuntimeSettingsCache.model_validate(content)
  except ValidationError as error:
    logger.warning(f"Ignoring invalid runtime settings cache {settings.path}: {error}")

    return RuntimeSettingsCache()


def apply_runtime_settings_cache(settings: Settings, cache: RuntimeSettingsCache) -> Settings:
  for field, value in cache.model_dump(exclude_none=True).items():
    setattr(settings, field, value)

  if cache.microphone_device is not None:
    settings.microphone_device_index = None

  return settings


def update_runtime_settings_cache(settings: Settings, **updates: Any) -> None:
  cache = read_runtime_settings_cache(settings)
  values = cache.model_dump()
  values.update(updates)

  try:
    updated_cache = RuntimeSettingsCache.model_validate(values)
  except ValidationError as error:
    logger.warning(f"Not caching invalid runtime settings update: {error}")
    return

  try:
    settings.path.parent.mkdir(parents=True, exist_ok=True)
    settings.path.write_text(
      json.dumps(updated_cache.model_dump(exclude_none=True), sort_keys=True, indent=2) + "\n",
      encoding="utf-8",
    )
  except OSError as error:
    logger.warning(f"Failed to write runtime settings cache {settings.path}: {error}")


@lru_cache
def get_settings() -> Settings:
  settings = Settings()  # type: ignore

  return apply_runtime_settings_cache(settings, read_runtime_settings_cache(settings))
