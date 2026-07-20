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
from __future__ import annotations

import asyncio
import logging
from typing import Any
from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from device.core.speaker import Speaker

logger = logging.getLogger(__name__)


class PlaybackQueueItem:
  def __init__(
    self,
    url: str,
    title: str | None = None,
    artist: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> None:
    self.url = url
    self.title = title or "Unknown Title"
    self.artist = artist or "Unknown Artist"
    self.metadata = metadata or {}

  def to_dict(self) -> dict[str, Any]:
    return {
      "url": self.url,
      "title": self.title,
      "artist": self.artist,
      "metadata": self.metadata,
    }


class PlaybackState:
  def __init__(self, speaker: Speaker | None = None) -> None:
    self.queue: list[PlaybackQueueItem] = []
    self.current_index: int = -1
    self.speaker = speaker
    self.playing_task: Optional[asyncio.Task] = None
    self.is_paused: bool = False
    self.simulated_position: float = 0.0
    self.sleep_timer_task: Optional[asyncio.Task] = None
    self.sleep_timer_seconds: Optional[int] = None

  def start_playback(self, loop: asyncio.AbstractEventLoop) -> None:
    self.stop_playback()

    if self.current_index < 0 and self.queue:
      self.current_index = 0

    if 0 <= self.current_index < len(self.queue):
      self.playing_task = loop.create_task(self._run_loop())

  def stop_playback(self) -> None:
    if self.playing_task and not self.playing_task.done():
      self.playing_task.cancel()

    self.playing_task = None

    if self.speaker:
      try:
        self.speaker.stop()
      except Exception as error:
        logger.warning(f"Error stopping speaker: {error}")

    self.is_paused = False
    self.simulated_position = 0.0

  async def _run_loop(self) -> None:
    loop = asyncio.get_running_loop()

    while 0 <= self.current_index < len(self.queue):
      item = self.queue[self.current_index]
      self.simulated_position = 0.0
      self.is_paused = False

      def play():
        if self.speaker:
          try:
            self.speaker.play_url(item.url)
          except Exception as error:
            logger.error(f"Speaker playback finished or interrupted: {error}")
        else:
          logger.error("Speaker playback is not configured")

      await loop.run_in_executor(None, play)

      # Check if we should advance (only if we didn't pause/stop manually)
      if not self.is_paused and 0 <= self.current_index < len(self.queue):
        self.current_index += 1
      else:
        break

  def pause_playback(self) -> None:
    if self.speaker:
      try:
        self.speaker.pause()
      except Exception as error:
        logger.warning(f"Error pausing speaker: {error}")

    self.is_paused = True

  def resume_playback(self, loop: asyncio.AbstractEventLoop) -> None:
    if self.is_paused:
      if self.speaker:
        try:
          self.speaker.resume()
        except Exception as error:
          logger.warning(f"Error resuming speaker: {error}")

      self.is_paused = False
    else:
      self.start_playback(loop)

  def enqueue(
    self,
    url: str,
    title: str | None = None,
    artist: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> int:
    item = PlaybackQueueItem(url, title, artist, metadata)
    self.queue.append(item)

    return len(self.queue) - 1

  def clear_queue(self) -> None:
    self.stop_playback()
    self.queue.clear()

    self.current_index = -1

  def get_now_playing(self) -> dict[str, Any]:
    if 0 <= self.current_index < len(self.queue):
      item = self.queue[self.current_index]

      return {
        "title": item.title,
        "artist": item.artist,
        "url": item.url,
        "metadata": item.metadata,
        "is_playing": self.playing_task is not None and not self.playing_task.done() and not self.is_paused,
        "is_paused": self.is_paused,
        "position": self.simulated_position,
      }
    return {
      "title": None,
      "artist": None,
      "url": None,
      "metadata": {},
      "is_playing": False,
      "is_paused": False,
      "position": 0.0,
    }
