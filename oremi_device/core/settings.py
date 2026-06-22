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
from typing import Literal

from pydantic import AnyHttpUrl
from pydantic import Field
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from .models import AndikaModel


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

    if error_type == "missing":
      message = "is required"
    elif field == "language" and error_type == "literal_error":
      message = "must be one of: fr, en"
    elif field == "andika_model" and error_type == "literal_error":
      message = "contains an unsupported model identifier"
    elif field == "izwi_url" and error_type in ("url_parsing", "url_scheme"):
      message = "must be a valid HTTP or HTTPS URL"
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


class DeviceSettings(BaseSettings):
  model_config = SettingsConfigDict(env_prefix="OREMI_DEVICE_", env_file=".env", extra="ignore")

  language: Literal["fr", "en"] = "fr"
  microphone_device_index: int | None = None
  microphone_device: str | None = None
  microphone_enabled: bool = True
  speaker_enabled: bool = True
  delay: int = Field(default=3, gt=0)
  conversation_timeout: float = Field(default=15.0, gt=0)

  ohunerin_host: str
  ohunerin_port: int = Field(default=5023, gt=0, le=65535)
  ohunerin_threshold: float = Field(default=0.25, gt=0)

  andika_host: str
  andika_port: int = Field(default=5315, gt=0, le=65535)
  andika_model: AndikaModel = "vosk-model-small-fr-0.22"
  andika_samplerate: int = Field(default=16000, gt=0)

  izwi_url: AnyHttpUrl | None = None

  cert_file: str | None = None
  node_id: str

  mqtt_broker: str
  mqtt_port: int = Field(default=1883, gt=0, le=65535)
  mqtt_username: str | None = None
  mqtt_password: str | None = None
  mqtt_topic: str = "oremi/device"
  mqtt_discovery: bool = True
  mqtt_discovery_prefix: str = "homeassistant"


def load_settings() -> DeviceSettings:  # type: ignore
  try:
    return DeviceSettings()  # type: ignore
  except ValidationError as error:
    raise SettingsError(format_settings_errors(error)) from None
