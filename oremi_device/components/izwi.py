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
import urllib.parse
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel


class IzwiVoice(BaseModel):
  name: str
  description: str
  primary_language: str


@dataclass(frozen=True)
class IzwiSynthesisRequest:
  url: str
  method: Literal["GET", "POST"]
  body: str | None = None


class IzwiClient:
  MAX_GET_URL_LENGTH = 2000

  def __init__(self, url: str, *, ca_file: str | None = None) -> None:
    self.base_url = url.rstrip("/")
    self.ca_file = ca_file

  async def get_voices(self) -> list[IzwiVoice]:
    async with httpx.AsyncClient(verify=self.ca_file or True) as client:
      response = await client.get(f"{self.base_url}/api/voices")
      response.raise_for_status()
      return [IzwiVoice.model_validate(voice) for voice in response.json()]

  def synthesize_request(self, text: str, voice: str) -> IzwiSynthesisRequest:
    query = urllib.parse.urlencode({"voice": voice, "input": text})
    endpoint = f"{self.base_url}/api/synthesize/stream"
    url = f"{endpoint}?{query}"

    if len(url) <= self.MAX_GET_URL_LENGTH:
      return IzwiSynthesisRequest(url=url, method="GET")

    body = json.dumps({"voice": voice, "input": text})
    return IzwiSynthesisRequest(url=endpoint, method="POST", body=body)


def voices_for_language(voices: list[IzwiVoice], language: str) -> list[IzwiVoice]:
  language_names = {"en": "english", "fr": "french"}
  expected = language_names.get(language, language).lower()
  return [voice for voice in voices if voice.primary_language.strip().lower().startswith(expected)]
