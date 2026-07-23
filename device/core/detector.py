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
from collections.abc import Callable
from typing import Any

from websockets.exceptions import ConnectionClosedError

from device.core.audio import Audio
from device.core.models import DetectedSound
from device.core.models import DetectedSoundType

logger = logging.getLogger(__name__)

DETECTION_EVENT_TOPIC = "event"


class SoundDetector:
  """Processes classification events and wakeword signals from an Ohunerin audio detector."""

  def __init__(
    self,
    websocket_or_publisher: Any,
    websocket: Any = None,
    audio_stream: Audio | None = None,
    *,
    delay: int = 3,
    threshold: float = 0.65,
    wakeword_event: asyncio.Event | None = None,
    on_detection: Callable[[str, str, bool], None] | Any | None = None,
  ) -> None:
    if websocket is None and (hasattr(websocket_or_publisher, "__aiter__") or hasattr(websocket_or_publisher, "recv")):
      self.websocket = websocket_or_publisher
      self._publisher: Any = on_detection
    else:
      self.websocket = websocket
      self._publisher = websocket_or_publisher or on_detection

    self.audio_stream: Audio | None = audio_stream
    self.delay: int = delay
    self.threshold: float = threshold
    self.wakeword_event: asyncio.Event | None = wakeword_event
    self.published_sound_sentinel: dict[str, tuple[DetectedSoundType, asyncio.Task]] = {}

  def _publish_event(self, topic: str, payload: str, retain: bool = False) -> None:
    if self._publisher is None:
      return

    publish_event = getattr(self._publisher, "publish_event", None)

    if callable(publish_event):
      publish_event(topic, payload, retain=retain)
    elif callable(self._publisher):
      try:
        self._publisher(topic, payload, retain=retain)
      except TypeError:
        self._publisher(topic, payload)

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
          self.send_clearing_message(data)

  def send_clearing_message(self, data: DetectedSound) -> None:
    data["sound"] = "..."
    message = json.dumps(data)
    self._publish_event(DETECTION_EVENT_TOPIC, message, retain=True)

  async def detecting(self) -> None:
    if self.websocket is None:
      return

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
    current_sound = data["sound"]
    payload = json.dumps(data)

    if data["type"] == "wakeword":
      self._publish_event(DETECTION_EVENT_TOPIC, payload)
      self.schedule_clearing_task(data)

      if self.wakeword_event:
        self.wakeword_event.set()
    elif current_sound not in self.published_sound_sentinel:
      self._publish_event(DETECTION_EVENT_TOPIC, payload)
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
