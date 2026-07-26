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
import abc
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class TTSVoice(BaseModel):
  name: str
  description: str
  primary_language: str
  id: str | None = None
  gender: str | None = None
  sample_rate: int | None = None


@dataclass(frozen=True)
class TTSSynthesisRequest:
  url: str
  method: Literal["GET", "POST"]
  body: str | None = None
  headers: dict[str, str] | None = None


class BaseTTSClient(abc.ABC):
  """Abstract base class for speech synthesis provider clients."""

  @abc.abstractmethod
  async def get_voices(self) -> list[TTSVoice]:
    """Fetch available voices from the backend."""

  @abc.abstractmethod
  def synthesize_request(self, text: str, voice: str, language: str | None = None) -> TTSSynthesisRequest:
    """Build a synthesis request for the given text and voice."""


def voices_for_language(voices: list[TTSVoice], language: str) -> list[TTSVoice]:
  language_names = {"en": "english", "fr": "french"}
  expected = language_names.get(language, language).lower()
  language_prefix = f"{language.lower()}-"
  multilingual_tokens = ("auto", "multilingual", "all", "*")

  return [
    voice
    for voice in voices
    if voice.primary_language.strip().lower() in multilingual_tokens
    or voice.primary_language.strip().lower().startswith((expected, language.lower(), language_prefix))
    or voice.name.strip().lower().startswith(language_prefix)
  ]
