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
import ssl
import urllib.parse
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import connect

from device.components.transcribers.andika_ws import AndikaTranscriber
from device.components.transcribers.base import SupportedModel
from device.components.transcribers.whisper_cpp import WhisperCppListener
from device.core.audio import Audio
from device.core.components import ActiveStreamContainer
from device.core.components import AudioStreamComponent
from device.core.components import DeviceState
from device.core.components import SharedResources
from device.core.cues import ConversationEvent
from device.core.listener import AudioListener
from device.core.models import AndikaConfig
from device.core.settings import Settings

logger = logging.getLogger(__name__)

PARTIAL_TRANSCRIPTION_TOPIC = "transcription/partial"
FINAL_TRANSCRIPTION_TOPIC = "transcription/result"

# Backward compatibility aliases
AndikaSupportedModel = SupportedModel


class Speech2Text(AudioStreamComponent[AndikaConfig]):
  """Speech-to-text component (WebSocket / HTTP + audio stream)."""

  def __init__(self, settings: Settings) -> None:
    super().__init__(settings)

    self._task: asyncio.Task | None = None
    self._websocket: Any = None
    self.audio_listener: AudioListener | WhisperCppListener | None = None
    self._listening_task: asyncio.Task | None = None
    self._handle_task_done: Callable[[asyncio.Task], None] | None = None
    self._wakeword_event: asyncio.Event | None = None
    self._transcription_complete_event = asyncio.Event()
    self._transcription_result_received = False
    self._transcription_active = False
    self._conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]] | None = None
    self._final_transcription_handler: Callable[[str], Awaitable[None]] | None = None
    self._publisher: Any = None
    self._active_stream_container: ActiveStreamContainer | dict[str, Any] = {}
    self._device_state: DeviceState | dict[str, Any] = {}

  @property
  def name(self) -> str:
    return "andika"

  @property
  def task(self) -> asyncio.Task | None:
    return self._task

  @property
  def listening_task(self) -> asyncio.Task | None:
    return None

  def _get_supported_models(self) -> list[SupportedModel]:
    if self.settings.transcription_backend == "andika":
      return AndikaTranscriber.get_supported_models(self.settings)
    elif self.settings.transcription_backend == "whisper.cpp":
      return WhisperCppListener.get_supported_models(self.settings)
    return []

  def build_connection_uri(self, config: AndikaConfig | None = None) -> str:
    config = config or AndikaConfig()
    query_string = urllib.parse.urlencode(
      {
        "model": config.model,
        "samplerate": config.samplerate,
        "show-words": False,
        "max-alternatives": 0,
        "language": self.settings.language,
      }
    )

    if self.settings.andika_cert_file:
      return f"wss://{self.settings.andika_host}:{self.settings.andika_port}/ws?{query_string}"

    return f"ws://{self.settings.andika_host}:{self.settings.andika_port}/ws?{query_string}"

  async def start(
    self,
    config: AndikaConfig | None,
    shared_resources: SharedResources,
  ) -> None:
    publisher = shared_resources.get("mqtt_publisher")
    resources = shared_resources

    if config is None:
      logger.warning("Andika component started without configuration; using defaults.")
      config = AndikaConfig()

    if self.settings.transcription_backend == "whisper.cpp":
      logger.info(f"whisper.cpp Server URL: {self.settings.whisper_url}")
      logger.info(f"whisper.cpp Language: {self.settings.language}")
    else:
      logger.info(f"Andika Server Host: {self.settings.andika_host}")
      logger.info(f"Andika Server Port: {self.settings.andika_port}")
      logger.info(f"Andika Model: {config.model}")
      logger.info(f"Andika Samplerate: {config.samplerate}")

    supported_models = (
      await asyncio.to_thread(self._get_supported_models)
      if self.settings.transcription_backend == "andika"
      else []
    )

    if supported_models:
      supported_model_ids = ", ".join(model.id for model in supported_models)
      logger.info(f"Andika Supported Models: {supported_model_ids}")

    loop = asyncio.get_running_loop()
    self._handle_task_done = resources.get("handle_task_done")
    self._task = loop.create_task(self._run(config, publisher, resources), name="Andika Task")

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
    if self.settings.transcription_backend == "whisper.cpp":
      if new_stream:
        if self.audio_listener and isinstance(self.audio_listener, WhisperCppListener):
          self.audio_listener.audio_stream = new_stream
        else:
          self.audio_listener = WhisperCppListener(
            self.settings,
            self._publisher,
            new_stream,
            self._transcription_complete_event,
            self._conversation_event_handler,
            self._final_transcription_handler,
          )
      elif self.audio_listener and isinstance(self.audio_listener, WhisperCppListener):
        self.audio_listener.audio_stream = new_stream
    elif new_stream and self.audio_listener and isinstance(self.audio_listener, AudioListener):
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

    is_muted = self._device_state.get("microphone_muted", False) if self._device_state else False
    if self._transcription_active and new_stream is not None and not is_muted:
      self._start_listening()

  def _start_listening(self) -> None:
    stream = self._active_stream_container.get("stream") if self._active_stream_container else None

    if self.settings.transcription_backend == "whisper.cpp":
      if not self.audio_listener and stream:
        self.audio_listener = WhisperCppListener(
          self.settings,
          self._publisher,
          stream,
          self._transcription_complete_event,
          self._conversation_event_handler,
          self._final_transcription_handler,
        )
      elif isinstance(self.audio_listener, WhisperCppListener) and stream:
        self.audio_listener.audio_stream = stream
    elif stream:
      if not self.audio_listener and self._websocket:
        self.audio_listener = AudioListener(stream, self._websocket, stop_message=None)
      elif isinstance(self.audio_listener, AudioListener):
        self.audio_listener.audio_stream = stream
        if self._websocket:
          self.audio_listener.websocket = self._websocket
        self.audio_listener.stop_message = None

    if self._listening_task and self._listening_task.done():
      self._listening_task = None

    if not self.audio_listener or self._listening_task is not None:
      return

    loop = asyncio.get_running_loop()
    self._listening_task = loop.create_task(self.audio_listener.listening(), name="Andika Listening Task")

    if self._handle_task_done:
      self._listening_task.add_done_callback(self._handle_task_done)

  async def on_mute_changed(self, muted: bool) -> None:
    if muted:
      await self._stop_listening()

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
    self._transcription_result_received = True
    await self._stop_listening()

    if self._conversation_event_handler:
      await self._conversation_event_handler(event)

  async def _wait_for_transcription_turn(self) -> None:
    event_task = asyncio.create_task(self._transcription_complete_event.wait(), name="Andika Transcription Complete Task")
    wait_tasks = [event_task]

    if self._listening_task is not None and not self._listening_task.done():
      wait_tasks.append(self._listening_task)

    try:
      done, _ = await asyncio.wait(wait_tasks, timeout=self.settings.conversation_timeout, return_when=asyncio.FIRST_COMPLETED)

      if event_task in done:
        return

      if self._listening_task is not None and self._listening_task in done:
        if self._transcription_result_received:
          await event_task
          return

        try:
          self._listening_task.result()
        except asyncio.CancelledError:
          pass
        except Exception as error:
          logger.warning(f"Andika listening failed before a transcription result was received: {error}")
        else:
          logger.warning("Andika listening stopped before a transcription result was received")

        if self._conversation_event_handler:
          await self._conversation_event_handler("cancelled")

        return

      logger.info(f"Andika conversation timed out after {self.settings.conversation_timeout:g}s")

      if self._conversation_event_handler:
        await self._conversation_event_handler("cancelled")
    finally:
      if not event_task.done():
        event_task.cancel()

      await asyncio.gather(event_task, return_exceptions=True)

  async def _wait_for_activation(self) -> None:
    if self._wakeword_event is None:
      return

    await self._wakeword_event.wait()
    self._wakeword_event.clear()

  async def _activate_on_wakeword(
    self,
    active_stream_container: ActiveStreamContainer | dict[str, Any],
    device_state: DeviceState | dict[str, Any] | None = None,
    andika_uri: str | None = None,
    ssl_context: ssl.SSLContext | None = None,
    publisher: Any = None,
  ) -> None:
    if self._wakeword_event is None:
      return

    if device_state is None:
      device_state = {"microphone_muted": False}

    loop = asyncio.get_running_loop()

    while True:
      await self._wait_for_activation()
      await self._stop_listening()
      self._transcription_complete_event.clear()
      self._transcription_result_received = False
      self._transcription_active = True

      if self._conversation_event_handler:
        await self._conversation_event_handler("listening")

      stream = active_stream_container.get("stream")
      is_muted = device_state.get("microphone_muted", False)

      if self.audio_listener is not None:
        try:
          if stream is not None and not is_muted:
            self._start_listening()

          await self._wait_for_transcription_turn()
        finally:
          try:
            await self._stop_listening()
          finally:
            self._transcription_active = False
      elif andika_uri and stream is not None and not is_muted:
        transcribing_task: asyncio.Task | None = None
        try:
          async with connect(andika_uri, ssl=ssl_context, user_agent_header=self.settings.user_agent) as websocket:
            self._websocket = websocket

            transcriber = AndikaTranscriber(
              self.settings,
              publisher or self._publisher,
              websocket,
              self._transcription_complete_event,
              self._handle_transcription_event,
              self._final_transcription_handler,
            )
            transcribing_task = loop.create_task(transcriber.transcribing(), name="Andika Transcription Task")
            if self._handle_task_done:
              transcribing_task.add_done_callback(self._handle_task_done)

            self.audio_listener = AudioListener(
              stream,
              websocket,
              stop_message=json.dumps({"eof": 1}),
            )

            self._start_listening()
            await self._wait_for_transcription_turn()
        except asyncio.CancelledError:
          raise
        except Exception as error:
          logger.error(f"Andika connection error during transcription turn: {error}")
          if self._conversation_event_handler:
            await self._conversation_event_handler("cancelled")
        finally:
          if transcribing_task and not transcribing_task.done():
            transcribing_task.cancel()

            try:
              await transcribing_task
            except Exception:
              pass

          await self._stop_listening()
          self._websocket = None
          self.audio_listener = None
          self._transcription_active = False
      else:
        self._transcription_active = False

  async def _run(
    self,
    config: AndikaConfig,
    publisher: Any,
    shared_resources: SharedResources,
  ) -> None:
    self._publisher = publisher
    self._active_stream_container = shared_resources.get("active_stream_container", {})
    self._device_state = shared_resources.get("device_state", {})

    if self.settings.transcription_backend == "whisper.cpp":
      await self._run_whisper(publisher, shared_resources)
      return

    active_stream_container = shared_resources.get("active_stream_container", {})
    device_state = shared_resources.get("device_state", {})
    self._wakeword_event = shared_resources.get("wakeword_event")
    self._conversation_event_handler = shared_resources.get("conversation_event_handler")
    self._final_transcription_handler = shared_resources.get("final_transcription_handler")
    andika_uri = self.build_connection_uri(config)

    logger.info(f"Andika Connection URI: {andika_uri}")

    if self.settings.andika_cert_file:
      ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
      ssl_context.load_verify_locations(self.settings.andika_cert_file)
    else:
      ssl_context = None

    await self._activate_on_wakeword(
      active_stream_container,
      device_state,
      andika_uri=andika_uri,
      ssl_context=ssl_context,
      publisher=publisher,
    )

  async def _run_whisper(self, publisher: Any, shared_resources: SharedResources) -> None:
    self._publisher = publisher
    self._active_stream_container = shared_resources.get("active_stream_container", {})
    self._device_state = shared_resources.get("device_state", {})
    active_stream_container = shared_resources.get("active_stream_container", {})
    self._wakeword_event = shared_resources.get("wakeword_event")
    self._conversation_event_handler = shared_resources.get("conversation_event_handler")
    self._final_transcription_handler = shared_resources.get("final_transcription_handler")
    self._handle_task_done = shared_resources.get("handle_task_done")
    audio_stream = active_stream_container.get("stream")

    if audio_stream is None:
      logger.warning("whisper.cpp transcription started without an active microphone")
    else:
      self.audio_listener = WhisperCppListener(
        self.settings,
        publisher,
        audio_stream,
        self._transcription_complete_event,
        self._conversation_event_handler,
        self._final_transcription_handler,
      )

    await self._activate_on_wakeword(active_stream_container, shared_resources.get("device_state"))


# Backward compatibility alias
AndikaComponent = Speech2Text

__all__ = [
  "AndikaComponent",
  "AndikaSupportedModel",
  "AndikaTranscriber",
  "Speech2Text",
  "SupportedModel",
  "WhisperCppListener",
]
