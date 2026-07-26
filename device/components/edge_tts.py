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

import httpx

from device.core.tts import BaseTTSClient
from device.core.tts import TTSSynthesisRequest
from device.core.tts import TTSVoice


class OpenAIEdgeTTSClient(BaseTTSClient):
  def __init__(
    self,
    url: str,
    *,
    api_key: str,
    locale: str | None = None,
    model: str = "tts-1",
    response_format: str = "mp3",
    speed: float = 1.0,
  ) -> None:
    self.base_url = url.rstrip("/")
    self.api_key = api_key
    self.locale = locale
    self.model = model
    self.response_format = response_format
    self.speed = speed

  @property
  def _headers(self) -> dict[str, str]:
    return {"Authorization": f"Bearer {self.api_key}"}

  async def get_voices(self) -> list[TTSVoice]:
    params = {"language": self.locale} if self.locale else None

    async with httpx.AsyncClient() as client:
      response = await client.get(f"{self.base_url}/v1/voices", params=params, headers=self._headers)
      response.raise_for_status()
      payload = response.json()

    if isinstance(payload, dict):
      raw_voices = payload.get("voices") or payload.get("data") or []
    else:
      raw_voices = payload

    return [voice for item in raw_voices if (voice := self._parse_voice(item)) is not None]

  def synthesize_request(self, text: str, voice: str, language: str | None = None) -> TTSSynthesisRequest:
    body = json.dumps(
      {
        "model": self.model,
        "input": text,
        "voice": voice,
        "response_format": self.response_format,
        "speed": self.speed,
      }
    )
    return TTSSynthesisRequest(
      url=f"{self.base_url}/v1/audio/speech",
      method="POST",
      body=body,
      headers=self._headers,
    )

  def _parse_voice(self, item: object) -> TTSVoice | None:
    if isinstance(item, str):
      return TTSVoice(name=item, description=item, primary_language=self.locale or item.partition("-")[0])

    if not isinstance(item, dict):
      return None

    name = item.get("ShortName") or item.get("short_name") or item.get("name") or item.get("voice")

    if not isinstance(name, str) or not name:
      return None

    description = (
      item.get("FriendlyName")
      or item.get("friendly_name")
      or item.get("DisplayName")
      or item.get("display_name")
      or item.get("description")
      or name
    )

    primary_language = (
      item.get("Locale")
      or item.get("locale")
      or item.get("language")
      or item.get("primary_language")
      or self.locale
      or name.partition("-")[0]
    )

    return TTSVoice(name=name, description=str(description), primary_language=str(primary_language))
