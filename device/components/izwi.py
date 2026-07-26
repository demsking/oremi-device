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


class IzwiClient(BaseTTSClient):
  def __init__(self, url: str) -> None:
    self.base_url = url.rstrip("/")

  async def get_voices(self) -> list[TTSVoice]:
    async with httpx.AsyncClient() as client:
      response = await client.get(f"{self.base_url}/api/tts/voices")
      response.raise_for_status()
      payload = response.json()

    return [
      TTSVoice(
        id=item["id"],
        name=item["id"],
        description=f"{item['name']} ({item['gender']}): {item['description']}",
        primary_language="multilingual",
        gender=item["gender"],
        sample_rate=item["sample_rate"],
      )
      for item in payload["voices"]
    ]

  def synthesize_request(self, text: str, voice: str, language: str | None = None) -> TTSSynthesisRequest:
    endpoint = f"{self.base_url}/api/tts/stream"
    payload: dict[str, object] = {
      "text": text,
      "voice": voice,
      "audio_format": "wav",
    }

    if language:
      payload["language"] = language

    body = json.dumps(payload)
    headers = {"Content-Type": "application/json"}

    return TTSSynthesisRequest(url=endpoint, method="POST", body=body, headers=headers)
