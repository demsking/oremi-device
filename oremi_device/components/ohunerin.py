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
import ssl
import urllib.parse
from typing import Any

import httpx
from pydantic import BaseModel
from websockets.asyncio.client import connect

from ..core.audio import Audio
from ..core.detector import SoundDetector
from ..core.listener import AudioListener
from ..core.models import DeviceContext
from ..core.models import OhunerinConfig
from ..core.mqtt import MQTTClient
from ..core.package import APP_NAME
from ..core.package import APP_VERSION
from ..utils.logger import logger
from ..utils.string import sluggify
from .base import AudioStreamComponent
from .base import HAEntity


class OhunerinServerInfo(BaseModel):
  name: str
  version: str
  threshold: float
  wakewords: dict[str, list[str]]
  sounds: list[str]


class OhunerinComponent(AudioStreamComponent):
  """Ohunerin speech-event detection component (WebSocket + audio stream)."""

  def __init__(self, context: DeviceContext) -> None:
    super().__init__(context)

    self._task: asyncio.Task | None = None
    self._websocket = None
    self.sound_detector = None
    self.audio_listener = None
    self._listening_task: asyncio.Task | None = None
    self._handle_task_done = None
    self.sounds: list[str] = []

  @property
  def name(self) -> str:
    return "ohunerin"

  def _get_server_info(self, host: str, port: int) -> OhunerinServerInfo | None:
    endpoint = f"https://{host}:{port}/info" if self.context.cert_file else f"http://{host}:{port}/info"

    try:
      response = httpx.get(endpoint)
      response.raise_for_status()

      return OhunerinServerInfo.model_validate_json(response.text)
    except httpx.HTTPStatusError as exc:
      logger.error(f"Error response {exc.response.status_code} while requesting {exc.request.url!r}.")

    return None

  def ha_entities(self, node_id: str, topic: str, device: dict) -> list[HAEntity]:
    """
    Register Wakeword and Sound Detector HA sensor entities.

    See https://www.home-assistant.io/integrations/sensor.mqtt/
    """
    server_info = self._get_server_info(self.context.ohunerin_host, self.context.ohunerin_port)

    wakeword_payload: dict = {
      "name": "Wakeword",
      "unique_id": f"{node_id}_wakeword",
      "state_topic": f"{topic}/wakeword",
      "value_template": "{% if value_json.sound == '...' %}💤{% else %}detected{% endif %}",
      "availability_topic": f"{topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "device_class": "enum",
      "options": ["detected", "💤"],
      "json_attributes_topic": f"{topic}/wakeword",
      "json_attributes_template": "{% if value_json.sound != '...' %}{{ value_json | tojson }}{% else %}{}{% endif %}",
      "icon": "mdi:waveform",
      "device": device,
    }

    sound_payload: dict = {
      "name": "Sound Detector",
      "unique_id": f"{node_id}_sound",
      "state_topic": f"{topic}/sound",
      "value_template": "{% if value_json.sound == '...' %}💤{% else %}{{ value_json.sound }}{% endif %}",
      "availability_topic": f"{topic}/available",
      "payload_available": "online",
      "payload_not_available": "offline",
      "json_attributes_topic": f"{topic}/sound",
      "json_attributes_template": "{% if value_json.sound != '...' %}{{ value_json | tojson }}{% else %}{}{% endif %}",
      "icon": "mdi:waveform",
      "device": device,
    }

    if server_info and server_info.sounds:
      sound_payload["device_class"] = "enum"
      sound_payload["options"] = server_info.sounds + ["💤"]
      mapper_items = []

      for sound in server_info.sounds:
        slug = sluggify(sound)
        escaped_slug = slug.replace("'", "\\'")
        escaped_sound = sound.replace("'", "\\'")
        mapper_items.append(f"'{escaped_slug}': '{escaped_sound}'")

      mapper_str = ", ".join(mapper_items)
      sound_payload["value_template"] = (
        f"{{% if value_json.sound == '...' %}}💤"
        f"{{% else %}}{{% set mapper = {{{mapper_str}}} %}}"
        f"{{{{ mapper.get(value_json.sound, value_json.sound) }}}}"
        f"{{% endif %}}"
      )

    return [
      ("sensor", "wakeword", wakeword_payload),
      ("sensor", "sound", sound_payload),
    ]

  @property
  def task(self) -> asyncio.Task | None:
    """The main WebSocket detection task."""
    return self._task

  @property
  def listening_task(self) -> asyncio.Task | None:
    """The microphone audio-feed task."""
    return self._listening_task

  def build_connection_uri(self, config: OhunerinConfig | None = None) -> str:
    query_string = urllib.parse.urlencode(
      {
        "features": "wakeword-detection,sound-detection",
        "language": self.context.language,
      }
    )

    if self.context.cert_file:
      return f"wss://{self.context.ohunerin_host}:{self.context.ohunerin_port}/ws?{query_string}"

    return f"ws://{self.context.ohunerin_host}:{self.context.ohunerin_port}/ws?{query_string}"

  async def start(
    self,
    config: OhunerinConfig | None,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    if config is None:
      logger.warning("Ohunerin component started without configuration; using defaults.")
      config = OhunerinConfig()

    logger.info(f"Ohunerin Server Host: {self.context.ohunerin_host}")
    logger.info(f"Ohunerin Server Port: {self.context.ohunerin_port}")
    logger.info(f"Ohunerin Threshold: {config.threshold}")

    loop = asyncio.get_running_loop()
    self._handle_task_done = shared_resources["handle_task_done"]
    self._task = loop.create_task(self._run(config, mqtt_client, shared_resources))

  async def stop(self) -> None:
    if self._websocket:
      try:
        await self._websocket.close()
      except Exception:
        pass

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

    # Start new listening task
    if new_stream is not None and self.audio_listener:
      loop = asyncio.get_running_loop()
      self._listening_task = loop.create_task(self.audio_listener.listening(), name="Listening Task")

      if self._handle_task_done:
        self._listening_task.add_done_callback(self._handle_task_done)

  async def _run(
    self,
    config: OhunerinConfig,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    loop = asyncio.get_running_loop()
    active_stream_container = shared_resources["active_stream_container"]

    ohunerin_uri = self.build_connection_uri(config)

    logger.info(f"Ohunerin Configuration Threshold: {config.threshold}")
    logger.info(f"Ohunerin Connection URI: {ohunerin_uri}")
    logger.info(f"Ohunerin Configuration Delay: {self.context.delay}s")

    if self.context.cert_file:
      ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
      ssl_context.load_verify_locations(self.context.cert_file)
    else:
      ssl_context = None

    retry_delay = 2.0

    while True:
      try:
        async with connect(
          ohunerin_uri, ssl=ssl_context, user_agent_header=f"{APP_NAME}/{APP_VERSION}/{self.context.node_id}"
        ) as websocket:
          self._websocket = websocket
          retry_delay = 2.0  # reset backoff on successful connection
          logger.info(f"Connected to Oremi Ohunerin server at {self.context.ohunerin_host}:{self.context.ohunerin_port}")

          self.sound_detector = SoundDetector(
            mqtt_client,
            websocket,
            active_stream_container["stream"],
            delay=self.context.delay,
            threshold=config.threshold,
            wakeword_event=shared_resources["wakeword_event"],
          )

          self.audio_listener = AudioListener(
            active_stream_container["stream"],
            websocket,
            mqtt_client,
          )

          detecting_task = loop.create_task(self.sound_detector.detecting(), name="Detection Task")

          if self._handle_task_done:
            detecting_task.add_done_callback(self._handle_task_done)

          if active_stream_container["stream"] is not None:
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
