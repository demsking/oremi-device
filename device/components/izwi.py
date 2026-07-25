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

import httpx

from device.core.tts import BaseTTSClient
from device.core.tts import TTSSynthesisRequest
from device.core.tts import TTSVoice


class IzwiClient(BaseTTSClient):
  MAX_GET_URL_LENGTH = 2000

  def __init__(self, url: str) -> None:
    self.base_url = url.rstrip("/")

  async def get_voices(self) -> list[TTSVoice]:
    async with httpx.AsyncClient() as client:
      response = await client.get(f"{self.base_url}/api/voices")
      response.raise_for_status()
      return [TTSVoice.model_validate(voice) for voice in response.json()]

  def synthesize_request(self, text: str, voice: str) -> TTSSynthesisRequest:
    query = urllib.parse.urlencode({"voice": voice, "input": text})
    endpoint = f"{self.base_url}/api/synthesize/stream"
    url = f"{endpoint}?{query}"

    if len(url) <= self.MAX_GET_URL_LENGTH:
      return TTSSynthesisRequest(url=url, method="GET")

    body = json.dumps({"voice": voice, "input": text})
    return TTSSynthesisRequest(url=endpoint, method="POST", body=body)
