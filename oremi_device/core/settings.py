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

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from .models import AndikaModel


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
  ohunerin_threshold: float = Field(default=0.65, gt=0)

  andika_host: str
  andika_port: int = Field(default=5315, gt=0, le=65535)
  andika_model: AndikaModel = "vosk-model-small-fr-0.22"
  andika_samplerate: int = Field(default=16000, gt=0)

  cert_file: str | None = None
  node_id: str

  mqtt_broker: str
  mqtt_port: int = Field(default=1883, gt=0, le=65535)
  mqtt_username: str | None = None
  mqtt_password: str | None = None
  mqtt_topic: str = "oremi/device"
  mqtt_discovery: bool = True
  mqtt_discovery_prefix: str = "homeassistant"
  partial_transcription_topic: str = "transcription/partial"
  final_transcription_topic: str = "transcription/text"


def load_settings() -> DeviceSettings:
  return DeviceSettings()  # type: ignore
