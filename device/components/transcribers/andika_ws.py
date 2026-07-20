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
import asyncio
import json
import logging
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from typing import Literal

import httpx
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from device.components.transcribers.base import BaseTranscriber
from device.components.transcribers.base import SupportedModel
from device.core.cues import ConversationEvent
from device.core.settings import Settings

logger = logging.getLogger(__name__)

PARTIAL_TRANSCRIPTION_TOPIC = "transcription/partial"
FINAL_TRANSCRIPTION_TOPIC = "transcription/result"


class AndikaTranscriber(BaseTranscriber):
  """WebSocket-based Vosk/Andika speech transcriber backend."""

  def __init__(
    self,
    settings: Settings,
    publisher: Any,
    websocket: Any,
    transcription_complete_event: asyncio.Event | None = None,
    conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]] | None = None,
    final_transcription_handler: Callable[[str], Awaitable[None]] | None = None,
  ) -> None:
    super().__init__(settings)
    self.publisher = publisher
    self.websocket = websocket
    self.transcription_complete_event = transcription_complete_event
    self.conversation_event_handler = conversation_event_handler
    self.final_transcription_handler = final_transcription_handler

  @property
  def name(self) -> str:
    return "andika"

  @classmethod
  def get_supported_models(cls, settings: Settings) -> list[SupportedModel]:
    if not settings.andika_host:
      return []

    endpoint = (
      f"https://{settings.andika_host}:{settings.andika_port}/api/models"
      if settings.cert_file
      else f"http://{settings.andika_host}:{settings.andika_port}/api/models"
    )

    try:
      response = httpx.get(endpoint)
      response.raise_for_status()
      return [SupportedModel.model_validate(item) for item in response.json()]
    except Exception as error:
      logger.warning(f"Failed to fetch Andika supported models: {error}")

    return []

  def parse_transcription(self, payload: dict) -> tuple[Literal["partial", "text"] | None, str]:
    if "partial" in payload:
      return "partial", payload["partial"]

    if "text" in payload:
      return "text", payload["text"]

    return None, ""

  def _publish(
    self,
    topic: str,
    message: str,
    *,
    qos: int = 1,
    retain: bool = False,
    props: Properties | None = None,
  ) -> None:
    if self.publisher is None:
      return

    publish_event = getattr(self.publisher, "publish_event", None)
    if callable(publish_event):
      publish_event(topic, message, qos=qos, retain=retain, props=props)
    elif callable(self.publisher):
      self.publisher(topic, message, qos=qos, retain=retain, props=props)

  async def transcribing(self) -> None:
    props = Properties(PacketTypes.PUBLISH)
    props.MessageExpiryInterval = self.settings.delay

    async for message in self.websocket:
      payload = json.loads(message)

      if isinstance(payload.get("text"), str):
        payload["text"] = payload["text"].strip()

      field, transcription = self.parse_transcription(payload)

      if field:
        mqtt_message = json.dumps(payload)

        if field == "partial":
          if transcription:
            self._publish(PARTIAL_TRANSCRIPTION_TOPIC, mqtt_message, qos=1, retain=False, props=props)
        else:
          if transcription:
            self._publish(FINAL_TRANSCRIPTION_TOPIC, mqtt_message, qos=1, retain=False, props=props)

            if self.final_transcription_handler:
              await self.final_transcription_handler(transcription)

          if self.conversation_event_handler:
            await self.conversation_event_handler("processing" if transcription else "cancelled")

          if self.transcription_complete_event:
            self.transcription_complete_event.set()
      else:
        logger.debug(f"Ignoring unknown Andika result payload: {payload}")
