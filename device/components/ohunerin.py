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
import ssl
import urllib.parse
from typing import Any

import httpx
from pydantic import BaseModel
from websockets.asyncio.client import connect

from device.core.audio import Audio
from device.core.components import ActiveStreamContainer
from device.core.components import AudioStreamComponent
from device.core.components import DeviceState
from device.core.components import SharedResources
from device.core.detector import SoundDetector
from device.core.listener import AudioListener
from device.core.models import OhunerinConfig
from device.core.settings import Settings

logger = logging.getLogger(__name__)


class OhunerinServerInfo(BaseModel):
  name: str
  version: str
  threshold: float
  wakewords: dict[str, list[str]]
  sounds: dict[str, list[str]]


class OhunerinComponent(AudioStreamComponent[OhunerinConfig]):
  """Ohunerin speech-event detection component (WebSocket + audio stream)."""

  def __init__(self, settings: Settings) -> None:
    super().__init__(settings)

    self._task: asyncio.Task | None = None
    self._websocket: Any = None
    self.sound_detector: SoundDetector | None = None
    self.audio_listener: AudioListener | None = None
    self._listening_task: asyncio.Task | None = None
    self._handle_task_done: Any = None
    self.sounds: list[str] = []
    self._active_stream_container: ActiveStreamContainer = {}
    self._device_state: DeviceState = {}

  @property
  def name(self) -> str:
    return "ohunerin"

  def get_supported_sounds(self) -> list[str]:
    path = "/api/sounds"

    if self.settings.ohunerin_cert_file:
      endpoint = f"https://{self.settings.ohunerin_host}:{self.settings.ohunerin_port}{path}"
    else:
      endpoint = f"http://{self.settings.ohunerin_host}:{self.settings.ohunerin_port}{path}"

    try:
      response = httpx.get(endpoint)
      response.raise_for_status()

      return response.json()
    except httpx.HTTPStatusError as exc:
      logger.error(f"Error response {exc.response.status_code} while requesting {exc.request.url!r}.")

    return []

  @property
  def task(self) -> asyncio.Task | None:
    """The main WebSocket detection task."""
    return self._task

  @property
  def listening_task(self) -> asyncio.Task | None:
    """The microphone audio-feed task."""
    return self._listening_task

  def build_connection_uri(self, config: OhunerinConfig | None = None) -> str:
    config = config or OhunerinConfig()
    query_string = urllib.parse.urlencode(
      {
        "features": ",".join(config.features),
        "language": self.settings.language,
      }
    )

    if self.settings.ohunerin_cert_file:
      return f"wss://{self.settings.ohunerin_host}:{self.settings.ohunerin_port}/ws?{query_string}"

    return f"ws://{self.settings.ohunerin_host}:{self.settings.ohunerin_port}/ws?{query_string}"

  async def start(
    self,
    config: OhunerinConfig | None,
    shared_resources: SharedResources,
  ) -> None:
    publisher = shared_resources.get("mqtt_publisher")
    resources = shared_resources

    if config is None:
      logger.warning("Ohunerin component started without configuration; using defaults.")
      config = OhunerinConfig()

    logger.info(f"Ohunerin Server Host: {self.settings.ohunerin_host}")
    logger.info(f"Ohunerin Server Port: {self.settings.ohunerin_port}")
    logger.info(f"Ohunerin Threshold: {config.threshold}")

    loop = asyncio.get_running_loop()
    self._handle_task_done = resources.get("handle_task_done")
    self._active_stream_container = resources.get("active_stream_container", {})
    self._device_state = resources.get("device_state", {})
    self._task = loop.create_task(self._run(config, publisher, resources))

  async def stop(self) -> None:
    if self._task and not self._task.done():
      self._task.cancel()

      try:
        await self._task
      except asyncio.CancelledError:
        pass

  async def on_device_changed(self, new_stream: Audio | None) -> None:
    """Handle audio device change."""
    if new_stream:
      if self.audio_listener:
        self.audio_listener.audio_stream = new_stream

      if self.sound_detector:
        self.sound_detector.audio_stream = new_stream

    # Stop current listening task if running
    if self._listening_task and not self._listening_task.done():
      self._listening_task.cancel()

      try:
        await self._listening_task
      except (asyncio.CancelledError, Exception):
        pass

    # Start new listening task if stream exists and microphone is not muted
    is_muted = self._device_state.get("microphone_muted", False) if self._device_state else False

    if new_stream is not None and self.audio_listener and not is_muted:
      loop = asyncio.get_running_loop()

      self._listening_task = loop.create_task(self.audio_listener.listening(), name="Listening Task")

      if self._handle_task_done:
        self._listening_task.add_done_callback(self._handle_task_done)

  async def on_mute_changed(self, muted: bool) -> None:
    """Handle microphone mute state change."""
    if self._listening_task and not self._listening_task.done():
      self._listening_task.cancel()

      try:
        await self._listening_task
      except (asyncio.CancelledError, Exception):
        pass

    stream = self._active_stream_container.get("stream") if self._active_stream_container else None

    if not muted and stream is not None and self.audio_listener:
      loop = asyncio.get_running_loop()
      self._listening_task = loop.create_task(self.audio_listener.listening(), name="Listening Task")

      if self._handle_task_done:
        self._listening_task.add_done_callback(self._handle_task_done)

  async def _run(
    self,
    config: OhunerinConfig,
    publisher: Any,
    shared_resources: SharedResources,
  ) -> None:
    loop = asyncio.get_running_loop()
    active_stream_container = shared_resources.get("active_stream_container", {})
    self._active_stream_container = active_stream_container
    self._device_state = shared_resources.get("device_state", {})

    ohunerin_uri = self.build_connection_uri(config)

    logger.info(f"Ohunerin Configuration Threshold: {config.threshold}")
    logger.info(f"Ohunerin Connection URI: {ohunerin_uri}")
    logger.info(f"Ohunerin Configuration Delay: {self.settings.delay}s")

    if self.settings.ohunerin_cert_file:
      ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
      ssl_context.load_verify_locations(self.settings.ohunerin_cert_file)
    else:
      ssl_context = None

    retry_delay = 2.0

    while True:
      try:
        async with connect(ohunerin_uri, ssl=ssl_context, user_agent_header=self.settings.user_agent) as websocket:
          self._websocket = websocket
          retry_delay = 2.0  # reset backoff on successful connection
          logger.info(f"Connected to Oremi Ohunerin server at {self.settings.ohunerin_host}:{self.settings.ohunerin_port}")

          self.sound_detector = SoundDetector(
            publisher,
            websocket,
            active_stream_container.get("stream"),
            delay=self.settings.delay,
            threshold=config.threshold,
            wakeword_event=shared_resources.get("wakeword_event"),
          )

          self.audio_listener = AudioListener(
            active_stream_container.get("stream"),
            websocket,
          )

          detecting_task = loop.create_task(self.sound_detector.detecting(), name="Detection Task")

          if self._handle_task_done:
            detecting_task.add_done_callback(self._handle_task_done)

          device_state = shared_resources.get("device_state", {})

          if active_stream_container.get("stream") is not None and not device_state.get("microphone_muted", False):
            self._listening_task = loop.create_task(self.audio_listener.listening(), name="Listening Task")

            if self._handle_task_done:
              self._listening_task.add_done_callback(self._handle_task_done)

          # Wait until the detecting task completes or is cancelled
          await detecting_task
      except asyncio.CancelledError:
        logger.info("Ohunerin component cancelled")
        break
      except Exception as error:
        logger.error(f"Ohunerin component error: {error}")
      finally:
        # Stop the listening task before the next reconnect attempt (or on exit)
        if self._listening_task and not self._listening_task.done():
          self._listening_task.cancel()

          try:
            await self._listening_task
          except (asyncio.CancelledError, Exception):
            pass

        self._websocket = None

      # Wait before reconnecting (exponential backoff, capped at 60 s)
      logger.info(f"Reconnecting to Ohunerin server in {retry_delay:.0f}s...")

      try:
        await asyncio.sleep(retry_delay)
      except asyncio.CancelledError:
        logger.info("Ohunerin component cancelled during reconnect wait")
        break

      retry_delay = min(retry_delay * 2, 60.0)
