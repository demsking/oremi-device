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
import logging
import time

from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import ConnectionClosedOK

from device.core.audio import Audio
from device.core.audio import AudioDeviceError

logger = logging.getLogger(__name__)


class AudioListener:
  """Streams captured microphone frames to a target WebSocket connection."""

  def __init__(
    self,
    audio_stream: Audio | None,
    websocket: ClientConnection,
    stop_message: str | bytes | None = None,
  ) -> None:
    self.audio_stream: Audio | None = audio_stream
    self.websocket: ClientConnection = websocket
    self.stop_message: str | bytes | None = stop_message

  async def listening(self) -> None:
    if not self.audio_stream:
      logger.warning("AudioListener cannot listen without an audio stream")
      return

    logger.info(f"Listening from {self.audio_stream.device_name} device...")
    audio_queue = self.audio_stream.subscribe()

    consecutive_timeouts = 0
    sent_bytes = 0
    last_stats_time = time.monotonic()

    try:
      async with self.audio_stream:
        while True:
          if not self.audio_stream.is_active():
            await asyncio.sleep(0.1)
            continue

          try:
            data = await asyncio.wait_for(self.audio_stream.data(audio_queue), timeout=1.0)
            consecutive_timeouts = 0
            await asyncio.wait_for(self.websocket.send(data), timeout=2.0)
            sent_bytes += len(data)

            now = time.monotonic()
            if now - last_stats_time >= 5.0:
              logger.debug(
                "Sent %d bytes from '%s' to the voice service in the last %.1fs",
                sent_bytes,
                self.audio_stream.device_name,
                now - last_stats_time,
              )
              sent_bytes = 0
              last_stats_time = now
          except TimeoutError:
            consecutive_timeouts += 1
            if consecutive_timeouts >= 3:
              logger.warning("No audio data received or websocket send blocked for 3s, restarting capture stream...")
              if hasattr(self.audio_stream, "restart_stream"):
                self.audio_stream.restart_stream()
              consecutive_timeouts = 0
            continue
          except ConnectionClosedOK:
            logger.info("Connection closed")
            break
          except ConnectionClosedError as error:
            logger.error(error)
            break
          except (AudioDeviceError, Exception) as error:
            logger.error(f"Audio stream error: {error}")
            raise
    finally:
      self.audio_stream.unsubscribe(audio_queue)

      if self.stop_message:
        try:
          await asyncio.shield(self.websocket.send(self.stop_message))
        except Exception:
          pass

    logger.info("Audio stream closed")
