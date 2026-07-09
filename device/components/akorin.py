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
from pydantic_ai import Agent

from ..core.cues import SoundCue
from ..core.models import AkorinConfig
from ..core.models import AnnounceCommand
from ..core.models import ConversationMessage
from ..core.models import ProcessingResponse
from ..core.models import SpeakCommand
from ..core.mqtt import MQTTClient
from ..core.settings import Settings
from ..llm import AgentClient
from .base import HttpComponent

logger = logging.getLogger(__name__)

CONTINUE_CONVERSATION_ANALYSIS_PROMPT = """
Analyze whether the assistant message is asking the user for more information and needs a spoken follow-up.
Reply with exactly "yes" when the user must answer before the task can continue.
Reply with exactly "no" when the message is informational, a completed answer, an error, or does not need a user answer.

Assistant message:
{message}
""".strip()

FOLLOW_UP_REPHRASE_PROMPT = """
Rewrite the latest user answer as one complete standalone user request.
Use the previous user request and assistant clarification only to restore missing intent.
Return only the rewritten request. Do not answer the request and do not explain.

Previous conversation:
{history}

Latest user answer:
{message}
""".strip()

CONTINUE_CONVERSATION_TRUE_VALUES = {"yes", "oui", "true"}
CONTINUE_CONVERSATION_FALSE_VALUES = {"no", "non", "false"}
CONTINUE_CONVERSATION_PROMPT_MARKERS = (
  "comment puis je vous aider",
  "que puis je faire",
  "comment je peux vous aider",
  "comment puis je t aider",
  "que puis je faire pour vous",
  "pour quel",
  "quel jour",
  "quelle date",
  "quelle heure",
  "precisez",
  "preciser cela",
  "pouvez vous preciser",
  "peux tu preciser",
  "veuillez preciser",
  "merci de preciser",
  "j ai besoin",
  "il me faut",
  "how can i help",
  "how may i help",
  "what can i help",
  "what do you need",
  "please provide",
)

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


def parse_continue_conversation_decision(value: str | None) -> bool | None:
  text = normalize_command_text(value or "").strip(" .,!?:;\"'")

  if text in CONTINUE_CONVERSATION_TRUE_VALUES:
    return True

  if text in CONTINUE_CONVERSATION_FALSE_VALUES:
    return False

  first_word = text.split(maxsplit=1)[0] if text else ""

  if first_word in CONTINUE_CONVERSATION_TRUE_VALUES:
    return True

  if first_word in CONTINUE_CONVERSATION_FALSE_VALUES:
    return False

  return None


def looks_like_follow_up_prompt(value: str | None) -> bool:
  text = normalize_follow_up_text(value or "")
  return any(marker in text for marker in CONTINUE_CONVERSATION_PROMPT_MARKERS)


def is_cancellation_request(message: str) -> bool:
  text = normalize_command_text(message)
  return text in STOP_WORDS or any(text.startswith(f"{word} ") for word in STOP_WORDS)


def processing_response_message(response: ProcessingResponse) -> str:
  if response.message and response.message.strip():
    return response.message.strip()

  spoken_text = [
    command.text.strip()
    for command in response.resolved_commands()
    if isinstance(command, (SpeakCommand, AnnounceCommand)) and command.text.strip()
  ]
  return "\n".join(spoken_text)


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
  def __init__(self, base_url: str, *, ca_file: str | None = None) -> None:
    self.base_url = base_url.rstrip("/")
    self.verify: str | bool = ca_file if ca_file else True

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
    logger.debug(
      f"Sending processing request to {self.endpoint} "
      f"(message={message!r}, "
      f"language={language or 'auto'}, "
      f"device_context={context}, "
      f"tags={tags}"
    )

    async with httpx.AsyncClient(verify=self.verify, timeout=timeout) as client:
      response = await client.post(
        url=self.endpoint,
        json={
          "message": message,
          "language": language,
          "context": {"preferences": context},
          "tags": tags,
        },
      )

      response.raise_for_status()

      data = response.json()
      result = ProcessingResponse.model_validate(data)

      logger.debug(
        f"Processing completed (service={result.service}, confidence={result.confidence:.2f}, message={result.message!r}, data={result.data})"
      )

      return result


class InternalTextAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(
      self.model,
      output_type=str,
      model_settings=self.model_settings,
    )


class AkorinInternalLLM:
  def __init__(self, settings: Settings) -> None:
    self._client = httpx.AsyncClient()
    self._agent = InternalTextAgent(settings, self._client)

  async def close(self) -> None:
    await self._client.aclose()

  async def should_continue_conversation(
    self,
    message: str,
    *,
    language: str | None,
    history: list[ConversationMessage],
  ) -> bool:
    del language

    analysis = await self._agent.exec(CONTINUE_CONVERSATION_ANALYSIS_PROMPT.format(message=message.strip()))
    decision = normalize_command_text(analysis).strip(" .,!?:;\"'")
    parsed_decision = parse_continue_conversation_decision(analysis)
    fallback_decision = looks_like_follow_up_prompt(analysis) or looks_like_follow_up_prompt(message)
    should_continue = parsed_decision if parsed_decision is not None else fallback_decision
    decision_source = "explicit" if parsed_decision is not None else "prompt_fallback"
    logger.debug(
      f"Continue conversation analysis completed "
      f"(raw_decision={analysis!r}, decision={decision!r}, "
      f"decision_source={decision_source}, should_continue={should_continue}, history_items={len(history)})"
    )
    return should_continue

  async def rephrase_follow_up(
    self,
    message: str,
    *,
    language: str | None,
    history: list[ConversationMessage],
  ) -> str:
    del language

    rephrased = (
      await self._agent.exec(
        FOLLOW_UP_REPHRASE_PROMPT.format(history=format_conversation_history(history), message=message.strip())
      )
    ).strip()

    if not rephrased:
      logger.debug("Follow-up rephrase returned an empty message; using original transcription")
      return message

    logger.debug(
      f"Follow-up rephrase completed "
      f"(original_chars={len(message)}, rephrased_chars={len(rephrased)}, history_items={len(history)})"
    )
    return rephrased


def create_internal_llm(settings: Settings) -> AkorinInternalLLM | None:
  try:
    return AkorinInternalLLM(settings)
  except ValueError as error:
    logger.warning(f"Internal LLM unavailable: {error}")
    return None


class AkorinComponent(HttpComponent[AkorinConfig]):
  """Akorin orchestration component (HTTP request/response)."""

  def __init__(self, settings: Settings) -> None:
    super().__init__(settings)

    self._task: asyncio.Task | None = None
    self._request_task: asyncio.Task | None = None
    self._handle_task_done = None
    self._cancel_active_processing: Callable[[], Awaitable[None]] | None = None
    self._play_sound_cue: Callable[[SoundCue], Awaitable[None]] | None = None
    self._conversation_history: list[ConversationMessage] = []
    self._continue_conversation_pending = False
    self._internal_llm: AkorinInternalLLM | None = None

  def _clear_follow_up_state(self, reason: str) -> None:
    if self._conversation_history or self._continue_conversation_pending:
      logger.debug(
        f"Clearing follow-up state after {reason} "
        f"(history_items={len(self._conversation_history)}, pending_rephrase={self._continue_conversation_pending})"
      )

    self._conversation_history = []
    self._continue_conversation_pending = False

  @property
  def name(self) -> str:
    return "akorin"

  @property
  def task(self) -> asyncio.Task | None:
    return self._task

  async def start(
    self,
    config: AkorinConfig | None,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    if self.settings.akorin_url is None:
      logger.warning("Akorin component disabled because OREMI_DEVICE_AKORIN_URL is not configured")
      return

    if config is None:
      config = AkorinConfig()

    logger.info(f"Akorin Server URL: {self.settings.akorin_url}")

    self._handle_task_done = shared_resources["handle_task_done"]
    self._cancel_active_processing = shared_resources["cancel_active_processing"]
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

  async def _run(self, config: AkorinConfig, shared_resources: dict[str, Any]) -> None:
    transcription_queue: asyncio.Queue[str] = shared_resources["transcription_queue"]
    processing_queue: asyncio.Queue[ProcessingResponse] = shared_resources["processing_queue"]
    follow_up_reset_queue: asyncio.Queue[None] | None = shared_resources.get("follow_up_reset_queue")
    language_state: dict[str, str] = shared_resources["language_state"]
    device_context: Callable[[], dict[str, Any]] = shared_resources["device_context"]
    client = AkorinClient(str(self.settings.akorin_url), ca_file=self.settings.cert_file)
    internal_llm = self._internal_llm or create_internal_llm(self.settings)
    queue_task = asyncio.create_task(transcription_queue.get(), name="Akorin Transcription Queue Task")
    reset_task = (
      asyncio.create_task(follow_up_reset_queue.get(), name="Akorin Follow-up Reset Task")
      if follow_up_reset_queue is not None
      else None
    )
    processing_task: asyncio.Task | None = None

    try:
      while True:
        pending: list[asyncio.Task] = [queue_task]

        if reset_task is not None:
          pending.append(reset_task)

        if processing_task is not None:
          pending.append(processing_task)

        done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        if reset_task is not None and reset_task in done:
          self._clear_follow_up_state("listening cancellation")

          if follow_up_reset_queue:
            reset_task = asyncio.create_task(follow_up_reset_queue.get(), name="Akorin Follow-up Reset Task")

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
            self._clear_follow_up_state("cancellation request")
            continue

          processing_task = asyncio.create_task(
            self._process_message(client, internal_llm, config, message, language_state, device_context),
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

      if reset_task is not None:
        reset_task.cancel()
        tasks_to_cancel.append(reset_task)

      await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

      if processing_task is not None and not processing_task.done():
        processing_task.cancel()
        await asyncio.gather(processing_task, return_exceptions=True)

      if internal_llm is not None and internal_llm is not self._internal_llm:
        await internal_llm.close()

  async def _process_message(
    self,
    client: AkorinClient,
    internal_llm: AkorinInternalLLM | None,
    config: AkorinConfig,
    message: str,
    language_state: dict[str, str],
    device_context: Callable[[], dict[str, Any]],
  ) -> ProcessingResponse | None:
    wait_cue_task = asyncio.create_task(self._play_wait_cues(config), name="Akorin Wait Cue Task")
    context = device_context()
    tags = [f"device_id:{self.settings.node_id}"]
    history = self._conversation_history.copy()
    processing_message = message
    should_rephrase = self._continue_conversation_pending and bool(history)
    self._continue_conversation_pending = False

    if should_rephrase:
      if internal_llm is None:
        logger.warning("Follow-up rephrase skipped because the internal LLM is unavailable")
      else:
        try:
          logger.debug(
            f"Rephrasing follow-up transcription before processing (message_chars={len(message)}, history_items={len(history)})"
          )
          processing_message = await internal_llm.rephrase_follow_up(
            message,
            language=language_state["language"],
            history=history,
          )
        except Exception as error:
          logger.warning(f"Follow-up rephrase failed; using original transcription: {error}")
    elif history:
      logger.debug(f"Follow-up rephrase skipped because continue conversation is not pending (history_items={len(history)})")

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
      response = await self._request_task
      response_text = processing_response_message(response)
      next_history = append_conversation_exchange(history, config.conversation_history_limit, processing_message, response_text)

      if response_text and internal_llm is not None:
        logger.debug(
          f"Analyzing processing response for follow-up "
          f"(response_text_chars={len(response_text)}, "
          f"previous_history_items={len(history)}, "
          f"analysis_history_items={len(next_history)})"
        )

        try:
          response.continue_conversation = await internal_llm.should_continue_conversation(
            response_text,
            language=language_state["language"],
            history=next_history,
          )
        except Exception as error:
          logger.warning(f"Continue conversation analysis failed: {error}")
      elif response_text:
        logger.warning("Follow-up analysis skipped because the internal LLM is unavailable")
      else:
        logger.debug("Skipping follow-up analysis because the processing response has no spoken message")

      self._conversation_history = next_history if response.continue_conversation else []
      self._continue_conversation_pending = response.continue_conversation
      logger.debug(
        f"Follow-up state updated "
        f"(continue_conversation={response.continue_conversation}, "
        f"pending_rephrase={self._continue_conversation_pending}, "
        f"retained_history_items={len(self._conversation_history)}, "
        f"discarded_history_items={0 if response.continue_conversation else len(next_history)})"
      )
      return response
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
      await self._play_sound_cue("cancel")

    message = ERROR_MESSAGE.get(language, ERROR_MESSAGE["en"])
    return ProcessingResponse(commands=[AnnounceCommand(type="announce", text=message)])
