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
# Andika and Ohunerin intentionally share WebSocket/audio lifecycle behavior.
# pylint: disable=duplicate-code
import asyncio
import json
import ssl
import urllib.parse
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from typing import Literal

import httpx
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from pydantic import BaseModel
from websockets.asyncio.client import connect

from ..core.audio import Audio
from ..core.cues import ConversationEvent
from ..core.listener import AudioListener
from ..core.models import AndikaConfig
from ..core.mqtt import MQTTClient
from ..core.package import APP_NAME
from ..core.package import APP_VERSION
from ..core.settings import DeviceSettings
from ..utils.logger import logger
from .base import AudioStreamComponent
from .base import HAEntity


PARTIAL_TRANSCRIPTION_TOPIC = "transcription/partial"
FINAL_TRANSCRIPTION_TOPIC = "transcription/result"


class AndikaSupportedModel(BaseModel):
  id: str  # pylint: disable=invalid-name
  name: str
  language: str


class AndikaTranscriber:
  def __init__(
    self,
    settings: DeviceSettings,
    mqtt_client: MQTTClient,
    websocket,
    transcription_complete_event: asyncio.Event | None = None,
    conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]] | None = None,
  ) -> None:
    self.settings = settings
    self.mqtt_client = mqtt_client
    self.websocket = websocket
    self.transcription_complete_event = transcription_complete_event
    self.conversation_event_handler = conversation_event_handler

  def parse_transcription(self, payload: dict) -> tuple[Literal["partial", "text"] | None, str]:
    if "partial" in payload:
      return "partial", payload["partial"]

    if "text" in payload:
      return "text", payload["text"]

    return None, ""

  async def transcribing(self) -> None:
    props = Properties(PacketTypes.PUBLISH)
    props.MessageExpiryInterval = self.settings.delay

    async for message in self.websocket:
      payload = json.loads(message)
      field, transcription = self.parse_transcription(payload)

      if field:
        mqtt_message = json.dumps(payload)

        if field == "partial":
          if transcription:
            self.mqtt_client.publish_event(
              PARTIAL_TRANSCRIPTION_TOPIC, mqtt_message, qos=1, retain=False, props=props
            )
        else:
          if transcription:
            self.mqtt_client.publish_event(
              FINAL_TRANSCRIPTION_TOPIC, mqtt_message, qos=1, retain=False, props=props
            )

          if self.conversation_event_handler:
            await self.conversation_event_handler("processing" if transcription else "cancelled")

          if self.transcription_complete_event:
            self.transcription_complete_event.set()
      else:
        logger.debug(f"Ignoring unknown Andika result payload: {payload}")


class AndikaComponent(AudioStreamComponent):
  """Andika speech-recognition component (WebSocket + audio stream)."""

  def __init__(self, settings: DeviceSettings) -> None:
    super().__init__(settings)

    self._task: asyncio.Task | None = None
    self._websocket = None
    self.audio_listener = None
    self._listening_task: asyncio.Task | None = None
    self._handle_task_done = None
    self._wakeword_event: asyncio.Event | None = None
    self._transcription_complete_event = asyncio.Event()
    self._transcription_active = False
    self._conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]] | None = None

  @property
  def name(self) -> str:
    return "andika"

  @property
  def task(self) -> asyncio.Task | None:
    return self._task

  @property
  def listening_task(self) -> asyncio.Task | None:
    # This task stops intentionally after each final transcription. Ohunerin's
    # continuous listener remains responsible for microphone health checks.
    return None

  def _get_supported_models(self) -> list[AndikaSupportedModel]:
    endpoint = (
      f"https://{self.settings.andika_host}:{self.settings.andika_port}/api/models"
      if self.settings.cert_file
      else f"http://{self.settings.andika_host}:{self.settings.andika_port}/api/models"
    )

    try:
      response = httpx.get(endpoint)
      response.raise_for_status()
      return [AndikaSupportedModel.model_validate(item) for item in response.json()]
    except Exception as error:
      logger.warning(f"Failed to fetch Andika supported models: {error}")

    return []

  def ha_entities(self, node_id: str, topic: str, availability_topic: str, device: dict) -> list[HAEntity]:
    payload: dict = {
      "name": "Transcription",
      "unique_id": f"{node_id}_transcription",
      "state_topic": f"{topic}/{FINAL_TRANSCRIPTION_TOPIC}",
      "value_template": "{{ value_json.text }}",
      "availability_topic": availability_topic,
      "payload_available": "online",
      "payload_not_available": "offline",
      "icon": "mdi:subtitles",
      "device": device,
    }

    return [("sensor", "transcription", payload)]

  def build_connection_uri(self, config: AndikaConfig | None = None) -> str:
    config = config or AndikaConfig()
    query_string = urllib.parse.urlencode(
      {
        "model": config.model,
        "samplerate": config.samplerate,
        "show-words": False,
        "max-alternatives": 0,
      }
    )

    if self.settings.cert_file:
      return f"wss://{self.settings.andika_host}:{self.settings.andika_port}/ws?{query_string}"

    return f"ws://{self.settings.andika_host}:{self.settings.andika_port}/ws?{query_string}"

  async def start(
    self,
    config: AndikaConfig | None,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    if config is None:
      logger.warning("Andika component started without configuration; using defaults.")
      config = AndikaConfig()

    logger.info(f"Andika Server Host: {self.settings.andika_host}")
    logger.info(f"Andika Server Port: {self.settings.andika_port}")
    logger.info(f"Andika Model: {config.model}")
    logger.info(f"Andika Samplerate: {config.samplerate}")

    supported_models = self._get_supported_models()

    if supported_models:
      supported_model_ids = ", ".join(model.id for model in supported_models)
      logger.info(f"Andika Supported Models: {supported_model_ids}")

    loop = asyncio.get_running_loop()
    self._handle_task_done = shared_resources["handle_task_done"]
    self._task = loop.create_task(self._run(config, mqtt_client, shared_resources), name="Andika Task")

  async def stop(self) -> None:
    if self._task and not self._task.done():
      self._task.cancel()

      try:
        await self._task
      except asyncio.CancelledError:
        pass

    if self._listening_task and not self._listening_task.done():
      self._listening_task.cancel()

      try:
        await self._listening_task
      except asyncio.CancelledError:
        pass

  async def on_device_changed(self, new_stream: Audio | None) -> None:
    if new_stream and self.audio_listener:
      self.audio_listener.audio_stream = new_stream

    if self._listening_task and not self._listening_task.done():
      self._listening_task.cancel()

      try:
        await self._listening_task
      except asyncio.CancelledError:
        current_task = asyncio.current_task()

        if current_task and current_task.cancelling():
          raise
      except Exception:
        pass

    if self._transcription_active and new_stream is not None:
      self._start_listening()

  def _start_listening(self) -> None:
    if not self.audio_listener or (self._listening_task and not self._listening_task.done()):
      return

    loop = asyncio.get_running_loop()
    self._listening_task = loop.create_task(self.audio_listener.listening(), name="Andika Listening Task")

    if self._handle_task_done:
      self._listening_task.add_done_callback(self._handle_task_done)

  async def _stop_listening(self) -> None:
    if self._listening_task and not self._listening_task.done():
      self._listening_task.cancel()

      try:
        await self._listening_task
      except asyncio.CancelledError:
        current_task = asyncio.current_task()

        if current_task and current_task.cancelling():
          raise
      except Exception:
        pass

  async def _handle_transcription_event(self, event: ConversationEvent) -> None:
    await self._stop_listening()

    if self._conversation_event_handler:
      await self._conversation_event_handler(event)

  async def _activate_on_wakeword(self, active_stream_container: dict, device_state: dict | None = None) -> None:
    if self._wakeword_event is None:
      return

    if device_state is None:
      device_state = {"microphone_muted": False}

    while True:
      await self._wakeword_event.wait()
      self._wakeword_event.clear()
      self._transcription_complete_event.clear()
      self._transcription_active = True

      if self._conversation_event_handler:
        await self._conversation_event_handler("listening")

      try:
        if (
          active_stream_container["stream"] is not None
          and not device_state["microphone_muted"]
        ):
          self._start_listening()

        try:
          await asyncio.wait_for(
            self._transcription_complete_event.wait(),
            timeout=self.settings.conversation_timeout,
          )
        except TimeoutError:
          logger.info(f"Andika conversation timed out after {self.settings.conversation_timeout:g}s")

          await self._stop_listening()

          if self._conversation_event_handler:
            await self._conversation_event_handler("cancelled")
      finally:
        try:
          await self._stop_listening()
        finally:
          self._transcription_active = False
          self._wakeword_event.clear()

  async def _run(
    self,
    config: AndikaConfig,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    loop = asyncio.get_running_loop()
    active_stream_container = shared_resources["active_stream_container"]
    self._wakeword_event = shared_resources["wakeword_event"]
    self._conversation_event_handler = shared_resources.get("conversation_event_handler")
    andika_uri = self.build_connection_uri(config)

    logger.info(f"Andika Connection URI: {andika_uri}")

    if self.settings.cert_file:
      ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
      ssl_context.load_verify_locations(self.settings.cert_file)
    else:
      ssl_context = None

    retry_delay = 2.0

    while True:
      activation_task: asyncio.Task | None = None

      try:
        async with connect(
          andika_uri, ssl=ssl_context, user_agent_header=f"{APP_NAME}/{APP_VERSION}/{self.settings.node_id}"
        ) as websocket:
          self._websocket = websocket
          retry_delay = 2.0
          logger.info(
            f"Connected to Oremi Andika server at {self.settings.andika_host}:{self.settings.andika_port}"
          )

          transcriber = AndikaTranscriber(
            self.settings,
            mqtt_client,
            websocket,
            self._transcription_complete_event,
            self._handle_transcription_event,
          )
          self.audio_listener = AudioListener(active_stream_container["stream"], websocket, mqtt_client)
          device_state = shared_resources["device_state"]
          transcribing_task = loop.create_task(transcriber.transcribing(), name="Andika Transcription Task")
          activation_task = loop.create_task(
            self._activate_on_wakeword(active_stream_container, device_state),
            name="Andika Wakeword Activation Task",
          )

          if self._handle_task_done:
            transcribing_task.add_done_callback(self._handle_task_done)

          await transcribing_task
      except asyncio.CancelledError:
        logger.info("Andika component cancelled")
        break
      except Exception as error:
        logger.error(f"Andika component error: {error}")
      finally:
        if activation_task and not activation_task.done():
          activation_task.cancel()

          try:
            await activation_task
          except asyncio.CancelledError:
            pass

        await self._stop_listening()

        self._websocket = None

      logger.info(f"Reconnecting to Andika server in {retry_delay:.0f}s...")

      try:
        await asyncio.sleep(retry_delay)
      except asyncio.CancelledError:
        logger.info("Andika component cancelled during reconnect wait")
        break

      retry_delay = min(retry_delay * 2, 60.0)
