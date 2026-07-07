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
from datetime import datetime

from websockets.asyncio.client import ClientConnection as WebSocket
from websockets.exceptions import ConnectionClosedError

from ..utils.string import sluggify
from .audio import Audio
from .models import DetectedSound
from .models import DetectedSoundType
from .mqtt import MQTTClient


logger = logging.getLogger(__name__)

DETECTION_EVENT_TOPIC = "event"


class SoundDetector:
  def __init__(
    self,
    mqtt_client: MQTTClient,
    websocket: WebSocket,
    audio_stream: Audio | None,
    *,
    delay: int,
    threshold: float,
    wakeword_event: asyncio.Event | None = None,
  ):
    self.mqtt_client = mqtt_client
    self.websocket = websocket
    self.audio_stream: Audio | None = audio_stream
    self.delay = delay
    self.threshold = threshold
    self.wakeword_event = wakeword_event
    self.published_sound_sentinel: dict[str, tuple[DetectedSoundType, asyncio.Task]] = {}

  async def clear_sound_after_delay(self, data: DetectedSound) -> None:
    try:
      await asyncio.sleep(self.delay)
    except asyncio.CancelledError:
      return

    if data["sound"] in self.published_sound_sentinel:
      _, task = self.published_sound_sentinel[data["sound"]]

      if task is asyncio.current_task():
        del self.published_sound_sentinel[data["sound"]]

        other_active = any(t == data["type"] for t, _ in self.published_sound_sentinel.values())

        if not other_active:
          self.send_clearing_message(data["type"])

  def send_clearing_message(self, sound_type: DetectedSoundType) -> None:
    data: DetectedSound = {
      "type": sound_type,
      "sound": "...",
      "score": 1.0,
      "date": datetime.now().isoformat(),
    }
    message = json.dumps(data)
    self.mqtt_client.publish_event(DETECTION_EVENT_TOPIC, message, retain=True)

  async def detecting(self) -> None:
    try:
      async for message in self.websocket:
        data: DetectedSound = json.loads(message)

        if data["score"] >= self.threshold:
          await self.process_detected_sound(data)
    except asyncio.CancelledError:
      logger.info("Recording cancelled")
      raise
    except ConnectionClosedError as error:
      logger.error(f"Ohunerin connection closed: {error}")
    finally:
      self.terminate()

  async def process_detected_sound(self, data: DetectedSound) -> None:
    data["sound"] = sluggify(data["sound"])
    current_sound = data["sound"]
    payload = json.dumps(data)

    if data["type"] == "wakeword":
      self.mqtt_client.publish_event(DETECTION_EVENT_TOPIC, payload)
      self.schedule_clearing_task(data)

      if self.wakeword_event:
        self.wakeword_event.set()
    elif current_sound not in self.published_sound_sentinel:
      self.mqtt_client.publish_event(DETECTION_EVENT_TOPIC, payload)
      self.schedule_clearing_task(data)

  def schedule_clearing_task(self, data: DetectedSound) -> None:
    if data["sound"] in self.published_sound_sentinel:
      _, existing_task = self.published_sound_sentinel[data["sound"]]
      existing_task.cancel()

    task = asyncio.create_task(self.clear_sound_after_delay(data))
    self.published_sound_sentinel[data["sound"]] = (data["type"], task)

  def terminate(self) -> None:
    for _, task in self.published_sound_sentinel.values():
      task.cancel()

    self.published_sound_sentinel.clear()
