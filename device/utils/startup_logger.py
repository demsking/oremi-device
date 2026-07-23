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
import logging
from typing import Any

from device.core.package import APP_NAME
from device.core.package import APP_VERSION
from device.core.settings import Settings
from device.utils.context import build_device_context

logger = logging.getLogger(__name__)


def format_setting_value(value: object) -> str:
  if value is None or value == "":
    return "unset"
  if isinstance(value, bool):
    return "enabled" if value else "disabled"
  return str(value)


def format_settings_group(values: dict[str, Any]) -> str:
  return ", ".join(f"{key}={format_setting_value(value)}" for key, value in values.items())


def log_startup_settings(settings: Settings) -> None:
  context = build_device_context(settings)
  transcription_settings: dict[str, Any] = {"backend": settings.transcription_backend}

  if settings.transcription_backend == "andika":
    transcription_settings.update(
      {
        "host": settings.andika_host,
        "port": settings.andika_port,
        "model": settings.andika_model,
        "samplerate": settings.andika_samplerate,
      }
    )
  else:
    transcription_settings["url"] = settings.whisper_url

  speech_settings: dict[str, Any] = {"backend": settings.tts_backend, "voice": settings.tts_voice}
  if settings.tts_backend == "edge-tts":
    speech_settings.update(
      {
        "url": settings.edge_tts_url,
        "locale": settings.edge_tts_locale,
        "model": settings.edge_tts_model,
        "format": settings.edge_tts_response_format,
        "speed": settings.edge_tts_speed,
      }
    )
  else:
    speech_settings["url"] = settings.izwi_url

  logger.info(f"{APP_NAME} v{APP_VERSION}")
  logger.info(f"Application setting path: {settings.path}")

  # Log groupings
  groups: dict[str, dict[str, Any]] = {
    "runtime": {
      "log_level": logging.getLevelName(logger.getEffectiveLevel()),
      "node_id": settings.node_id,
      "data": settings.data_path,
    },
    "context": context,
    "audio": {
      "microphone": settings.microphone_enabled,
      "microphone_device": settings.microphone_device,
      "speaker": settings.speaker_enabled,
      "speaker_device": settings.speaker_device,
      "speaker_volume": settings.speaker_volume,
    },
    "transcription": transcription_settings,
    "speech": speech_settings,
    "mqtt": {"broker": settings.mqtt_broker, "port": settings.mqtt_port, "topic": settings.mqtt_topic},
  }

  for name, data in groups.items():
    logger.info(f"Settings {name}: %s", format_settings_group(data))
