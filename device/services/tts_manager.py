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

from pydantic import ValidationError

from device.components.edge_tts import OpenAIEdgeTTSClient
from device.components.izwi import IzwiClient
from device.core.settings import Settings
from device.core.tts import TTSVoice
from device.core.tts import voices_for_language

logger = logging.getLogger(__name__)


class TTSManager:
  """Manages the lifecycle, configuration, and state of the Speech Synthesis backend."""

  def __init__(self, settings: Settings):
    self.settings = settings
    self.client: IzwiClient | OpenAIEdgeTTSClient | None = None
    self.available_voices: list[TTSVoice] = []
    self.current_voice: str = ""

    self._initialize_client()

  def _initialize_client(self) -> None:
    """Instantiates the correct TTS backend client based on device settings."""
    if self.settings.tts_backend == "edge-tts" and self.settings.edge_tts_url:
      edge_tts_locale = self.settings.edge_tts_locale or {"fr": "fr-FR", "en": "en-US"}.get(self.settings.language)

      self.client = OpenAIEdgeTTSClient(
        str(self.settings.edge_tts_url),
        api_key=self.settings.edge_tts_api_key,
        ca_file=self.settings.cert_file,
        locale=edge_tts_locale,
        model=self.settings.edge_tts_model,
        response_format=self.settings.edge_tts_response_format,
        speed=self.settings.edge_tts_speed,
      )
    elif self.settings.izwi_url:
      self.client = IzwiClient(str(self.settings.izwi_url), ca_file=self.settings.cert_file)
    else:
      self.client = None
      logger.info("No TTS backend properly configured (URLs missing or disabled).")

  async def fetch_voices(self) -> None:
    """Fetches available voices from the backend asynchronously and sets the initial voice."""
    if not self.client or not self.settings.speaker_enabled:
      return

    try:
      self.available_voices = await self.client.get_voices()
      voice_names = [voice.name for voice in self.available_voices]
      logger.info(f"Speech synthesis voices: {', '.join(voice_names) or 'None'}")

      # Establish the initial voice based on fetched records and current language
      self.update_voice_for_language(self.settings.language)

    except (ValidationError, OSError, ValueError) as error:
      logger.warning(f"Failed to fetch speech synthesis voices: {error}")
    except Exception as error:
      logger.warning(f"Failed to connect to speech synthesis backend: {error}")

  def get_active_voice_names(self, language: str | None = None) -> list[str]:
    """Returns a list of voice names compatible with the target language."""
    target_lang = language or self.settings.language

    return [voice.name for voice in voices_for_language(self.available_voices, target_lang)]

  def update_voice_for_language(self, language: str) -> None:
    """Sets the optimal voice for a given language, falling back to defaults if the preferred voice is incompatible."""
    valid_voices = self.get_active_voice_names(language)

    if self.settings.tts_voice in valid_voices:
      self.current_voice = self.settings.tts_voice
    elif valid_voices:
      self.current_voice = valid_voices[0]
    else:
      self.current_voice = ""

  def set_voice(self, voice_name: str) -> bool:
    """Attempts to set a new active voice. Returns True if successful."""
    if voice_name in self.get_active_voice_names():
      self.current_voice = voice_name
      self.settings.tts_voice = voice_name

      return True

    logger.warning(f"Ignoring unavailable or incompatible speech synthesis voice: {voice_name}")

    return False
