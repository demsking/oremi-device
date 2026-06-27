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
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class TTSVoice(BaseModel):
  name: str
  description: str
  primary_language: str


@dataclass(frozen=True)
class TTSSynthesisRequest:
  url: str
  method: Literal["GET", "POST"]
  body: str | None = None
  headers: dict[str, str] | None = None


def voices_for_language(voices: list[TTSVoice], language: str) -> list[TTSVoice]:
  language_names = {"en": "english", "fr": "french"}
  expected = language_names.get(language, language).lower()
  language_prefix = f"{language.lower()}-"

  return [
    voice
    for voice in voices
    if voice.primary_language.strip().lower().startswith((expected, language.lower(), language_prefix))
    or voice.name.strip().lower().startswith(language_prefix)
  ]
