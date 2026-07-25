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
import unicodedata
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from device.core.components import HttpComponent
from device.core.components import SharedResources
from device.core.cues import SoundCue
from device.core.models import AkorinConfig
from device.core.models import AnnounceCommand
from device.core.models import ConversationMessage
from device.core.models import ProcessingResponse
from device.core.settings import Settings

logger = logging.getLogger(__name__)

ERROR_MESSAGE = {
  "fr": "Je n'arrive pas a obtenir une reponse pour le moment.",
  "en": "I cannot get a response right now.",
}

STOP_WORDS = {
  "annule",
  "annuler",
  "arrete",
  "arreter",
  "stop",
  "cancel",
  "abort",
  "ne fais rien",
}


def normalize_command_text(value: str) -> str:
  normalized = unicodedata.normalize("NFKD", value.strip().lower())
  return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_follow_up_text(value: str) -> str:
  return normalize_command_text(value).replace("-", " ")


def is_cancellation_request(message: str) -> bool:
  text = normalize_command_text(message)
  return text in STOP_WORDS or any(text.startswith(f"{word} ") for word in STOP_WORDS)


def append_conversation_exchange(
  history: list[ConversationMessage],
  limit: int,
  user_message: str,
  assistant_message: str,
) -> list[ConversationMessage]:
  next_history = [*history, ConversationMessage(role="user", content=user_message)]

  if assistant_message:
    next_history.append(ConversationMessage(role="assistant", content=assistant_message))

  return next_history[-limit:]


def format_conversation_history(history: list[ConversationMessage]) -> str:
  if not history:
    return "(empty)"

  return "\n".join(f"{item.role}: {item.content}" for item in history)


class AkorinClient:
  def __init__(self, base_url: str) -> None:
    self.base_url = base_url.rstrip("/")

  @property
  def endpoint(self) -> str:
    return f"{self.base_url}/api/agent/"

  async def process(
    self,
    message: str,
    *,
    language: str | None,
    context: dict[str, Any],
    tags: list[str],
    timeout: float,
  ) -> ProcessingResponse:
    logger.info(f"Processing request: {message!r}")
    logger.debug(
      f"Sending processing request to {self.endpoint} "
      f"(message={message!r}, "
      f"language={language or 'auto'}, "
      f"device_context={context}, "
      f"tags={tags})"
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
      response = await client.post(
        url=self.endpoint,
        json={
          "message": message,
          "context": {"preferences": context, "language": language},
          "tags": tags,
        },
      )

      response.raise_for_status()

      data = response.json()
      result = ProcessingResponse.model_validate(data)

      logger.info(f"Processing completed (service={result.service})")
      logger.debug(
        f"Processing completed (service={result.service}, confidence={result.confidence:.2f}, message={result.message!r}, data={result.data})"
      )

      return result


class AkorinComponent(HttpComponent[AkorinConfig]):
  """Akorin orchestration component (HTTP request/response)."""

  def __init__(self, settings: Settings) -> None:
    super().__init__(settings)

    self._task: asyncio.Task | None = None
    self._request_task: asyncio.Task | None = None
    self._handle_task_done: Callable[[asyncio.Task[Any]], None] | None = None
    self._cancel_active_processing: Callable[[], Awaitable[None]] | None = None
    self._play_sound_cue: Callable[[SoundCue], Awaitable[None]] | None = None

  @property
  def name(self) -> str:
    return "akorin"

  @property
  def task(self) -> asyncio.Task | None:
    return self._task

  async def start(
    self,
    config: AkorinConfig | None,
    shared_resources: SharedResources,
  ) -> None:
    if self.settings.akorin_url is None:
      logger.warning("Akorin component disabled because OREMI_DEVICE_AKORIN_URL is not configured")
      return

    if config is None:
      config = AkorinConfig()

    logger.info(f"Akorin Server URL: {self.settings.akorin_url}")

    self._handle_task_done = shared_resources.get("handle_task_done")
    self._cancel_active_processing = shared_resources.get("cancel_active_processing")
    self._play_sound_cue = shared_resources.get("sound_cue_handler")
    loop = asyncio.get_running_loop()
    self._task = loop.create_task(self._run(config, shared_resources), name="Akorin Task")

  async def stop(self) -> None:
    if self._request_task and not self._request_task.done():
      self._request_task.cancel()

      try:
        await self._request_task
      except asyncio.CancelledError:
        pass

    if self._task and not self._task.done():
      self._task.cancel()

      try:
        await self._task
      except asyncio.CancelledError:
        pass

  async def _run(self, config: AkorinConfig, shared_resources: SharedResources) -> None:
    transcription_queue = shared_resources["transcription_queue"]
    processing_queue = shared_resources["processing_queue"]
    language_state = shared_resources["language_state"]
    device_context = shared_resources["device_context"]

    client = AkorinClient(str(self.settings.akorin_url))
    queue_task = asyncio.create_task(transcription_queue.get(), name="Akorin Transcription Queue Task")
    processing_task: asyncio.Task | None = None

    try:
      while True:
        pending: list[asyncio.Task] = [queue_task]

        if processing_task is not None:
          pending.append(processing_task)

        done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        if queue_task in done:
          message = queue_task.result()
          queue_task = asyncio.create_task(transcription_queue.get(), name="Akorin Transcription Queue Task")

          if self._cancel_active_processing:
            await self._cancel_active_processing()

          if processing_task is not None and not processing_task.done():
            processing_task.cancel()
            await asyncio.gather(processing_task, return_exceptions=True)
            processing_task = None

          if is_cancellation_request(message):
            logger.info("Akorin request skipped because the transcription is a cancellation command")
            continue

          processing_task = asyncio.create_task(
            self._process_message(client, config, message, language_state, device_context),
            name="Akorin Processing Task",
          )

        if processing_task is not None and processing_task in done:
          response = await processing_task
          processing_task = None

          if response is not None:
            await processing_queue.put(response)
    finally:
      queue_task.cancel()
      tasks_to_cancel: list[asyncio.Task] = [queue_task]

      await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

      if processing_task is not None and not processing_task.done():
        processing_task.cancel()
        await asyncio.gather(processing_task, return_exceptions=True)

  async def _process_message(
    self,
    client: AkorinClient,
    config: AkorinConfig,
    message: str,
    language_state: dict[str, str],
    device_context: Callable[[], dict[str, Any]],
  ) -> ProcessingResponse | None:
    wait_cue_task = asyncio.create_task(self._play_wait_cues(config), name="Akorin Wait Cue Task")
    context = device_context()
    tags = [f"device_id:{self.settings.node_id}"]
    processing_message = message

    self._request_task = asyncio.create_task(
      client.process(
        processing_message,
        language=language_state["language"],
        context=context,
        tags=tags,
        timeout=config.timeout,
      ),
      name="Akorin Request Task",
    )

    if self._handle_task_done:
      wait_cue_task.add_done_callback(self._handle_task_done)

    try:
      return await self._request_task
    except asyncio.CancelledError as error:
      logger.warning("Akorin request was cancelled")
      raise error
    except (httpx.HTTPError, TimeoutError) as error:
      logger.warning(f"Akorin request failed: {error}")
      return await self._handle_processing_error(language_state["language"])
    except (ValidationError, ValueError) as error:
      logger.warning(f"Ignoring invalid Akorin response: {error}")
      return await self._handle_processing_error(language_state["language"])
    finally:
      wait_cue_task.cancel()
      await asyncio.gather(wait_cue_task, return_exceptions=True)
      self._request_task = None

    return None

  async def _play_wait_cues(self, config: AkorinConfig) -> None:
    await asyncio.sleep(config.wait_cue_delay)

    while True:
      if self._play_sound_cue:
        await self._play_sound_cue("thinking")

      await asyncio.sleep(config.wait_cue_interval)

  async def _handle_processing_error(self, language: str) -> ProcessingResponse:
    if self._play_sound_cue:
      await self._play_sound_cue("error")

    message = ERROR_MESSAGE.get(language, ERROR_MESSAGE["en"])
    return ProcessingResponse(commands=[AnnounceCommand(type="announce", text=message)])
