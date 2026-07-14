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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from device.components import COMPONENTS
from device.components.akorin import AkorinClient
from device.components.akorin import AkorinComponent
from device.components.akorin import AkorinInternalLLM
from device.components.akorin import format_conversation_history
from device.components.akorin import is_cancellation_request
from device.components.akorin import looks_like_follow_up_prompt
from device.components.akorin import parse_continue_conversation_decision
from device.core.models import AkorinConfig
from device.core.models import ConversationMessage
from device.core.models import ProcessingResponse
from device.core.models import SpeakCommand
from device.core.settings import Settings


class FakeInternalLLM:
  def __init__(self, *, decisions: list[bool] | None = None, rephrased: list[str] | None = None) -> None:
    self.should_continue_conversation = AsyncMock(side_effect=decisions or [])
    self.rephrase_follow_up = AsyncMock(side_effect=rephrased or [])


def _make_settings(**kwargs) -> Settings:
  defaults = {
    "node_id": "test-node",
    "language": "fr",
    "ohunerin_host": "localhost",
    "andika_host": "andika",
    "mqtt_broker": "mqtt",
    "akorin_url": "http://akorin:5020",
  }
  defaults.update(kwargs)
  return Settings(_env_file=None, **defaults)


def test_akorin_component_registered() -> None:
  config_model, component_model = COMPONENTS["akorin"]

  assert config_model is AkorinConfig
  assert component_model is AkorinComponent


@pytest.mark.parametrize("message", ["stop", "annule", "annuler ca", "arrête", "ne fais rien"])
def test_akorin_detects_cancellation_requests(message: str) -> None:
  assert is_cancellation_request(message) is True


def test_akorin_parses_explicit_continue_conversation_decisions() -> None:
  assert parse_continue_conversation_decision("yes") is True
  assert parse_continue_conversation_decision("Oui.") is True
  assert parse_continue_conversation_decision("no") is False
  assert parse_continue_conversation_decision("Je peux vous aider aujourd'hui ?") is None


def test_akorin_detects_natural_follow_up_prompt() -> None:
  assert looks_like_follow_up_prompt("Comment puis-je vous aider aujourd'hui ?") is True
  assert looks_like_follow_up_prompt("Précisez un appareil et l'opération à appliquer.") is True
  assert (
    looks_like_follow_up_prompt(
      "Je comprends, mais je ne connais pas l'appareil ou l'opération que vous souhaitez appliquer. Pouvez-vous préciser cela ?"
    )
    is True
  )
  assert looks_like_follow_up_prompt("Il est 13h30.") is False


def test_akorin_formats_conversation_history_for_rephrase_prompt() -> None:
  history = [
    ConversationMessage(role="user", content="allume la lumière"),
    ConversationMessage(role="assistant", content="Précisez un appareil et l'opération à appliquer."),
  ]

  assert format_conversation_history(history) == (
    "user: allume la lumière\nassistant: Précisez un appareil et l'opération à appliquer."
  )


@pytest.mark.asyncio
async def test_akorin_client_posts_agent_request() -> None:
  response = MagicMock()
  response.json.return_value = {"message": "Bonjour"}
  context = AsyncMock()
  http_client = context.__aenter__.return_value
  http_client.post.return_value = response

  with patch("device.components.akorin.httpx.AsyncClient", return_value=context) as client_class:
    result = await AkorinClient("http://akorin:5020/").process(
      "bonjour",
      language="fr",
      context={"timezone": "Europe/Paris"},
      tags=["device_id:test-node"],
      timeout=20,
    )

  client_class.assert_called_once_with(verify=True, timeout=20)
  http_client.post.assert_awaited_once_with(
    url="http://akorin:5020/api/agent/",
      json={
        "message": "bonjour",
        "context": {
          "preferences": {"timezone": "Europe/Paris"},
          "language": "fr",
        },
        "tags": ["device_id:test-node"],
      },
  )
  response.raise_for_status.assert_called_once()
  assert result.resolved_commands() == [SpeakCommand(type="speak", text="Bonjour")]


@pytest.mark.asyncio
async def test_akorin_client_analyzes_continue_conversation_from_message() -> None:
  internal_llm = AkorinInternalLLM.__new__(AkorinInternalLLM)
  internal_llm._agent = MagicMock()
  internal_llm._agent.exec = AsyncMock(return_value="yes")
  history = [ConversationMessage(role="assistant", content="Pour quel jour ?")]

  result = await internal_llm.should_continue_conversation(
    "Pour quel jour ?",
    language="fr",
    history=history,
  )

  assert result is True
  internal_llm._agent.exec.assert_awaited_once()


@pytest.mark.asyncio
async def test_akorin_client_treats_natural_analysis_prompt_as_continue_conversation() -> None:
  internal_llm = AkorinInternalLLM.__new__(AkorinInternalLLM)
  internal_llm._agent = MagicMock()
  internal_llm._agent.exec = AsyncMock(
    return_value="Je vous remercie pour votre réponse affirmative ! Comment puis-je vous aider aujourd'hui ?"
  )
  history = [ConversationMessage(role="assistant", content="Comment puis-je vous aider aujourd'hui ?")]

  result = await internal_llm.should_continue_conversation(
    "Je vous remercie pour votre réponse affirmative ! Comment puis-je vous aider aujourd'hui ?",
    language="fr",
    history=history,
  )

  assert result is True


@pytest.mark.asyncio
async def test_akorin_client_treats_clarification_analysis_prompt_as_continue_conversation() -> None:
  internal_llm = AkorinInternalLLM.__new__(AkorinInternalLLM)
  internal_llm._agent = MagicMock()
  internal_llm._agent.exec = AsyncMock(
    return_value=(
      "Je comprends, mais je ne connais pas l'appareil ou l'opération que vous souhaitez appliquer. Pouvez-vous préciser cela ?"
    )
  )
  message = "Précisez un appareil et l'opération à appliquer."
  history = [ConversationMessage(role="assistant", content=message)]

  result = await internal_llm.should_continue_conversation(
    message,
    language="fr",
    history=history,
  )

  assert result is True


@pytest.mark.asyncio
async def test_akorin_client_rephrases_follow_up_as_standalone_request() -> None:
  internal_llm = AkorinInternalLLM.__new__(AkorinInternalLLM)
  internal_llm._agent = MagicMock()
  internal_llm._agent.exec = AsyncMock(return_value="allume la lumière de la chambre")
  history = [
    ConversationMessage(role="user", content="allume la lumière"),
    ConversationMessage(role="assistant", content="Précisez un appareil et l'opération à appliquer."),
  ]

  result = await internal_llm.rephrase_follow_up(
    "la lumière de la chambre",
    language="fr",
    history=history,
  )

  assert result == "allume la lumière de la chambre"
  internal_llm._agent.exec.assert_awaited_once()


@pytest.mark.asyncio
async def test_akorin_processes_transcription_into_processing_queue() -> None:
  component = AkorinComponent(_make_settings())
  transcription_queue: asyncio.Queue[str] = asyncio.Queue()
  processing_queue: asyncio.Queue[ProcessingResponse] = asyncio.Queue()

  shared_resources = {
    "transcription_queue": transcription_queue,
    "processing_queue": processing_queue,
    "language_state": {"language": "fr"},
    "device_context": lambda: {"timezone": "Europe/Paris"},
    "cancel_active_processing": AsyncMock(),
    "handle_task_done": lambda task: None,
  }

  response = ProcessingResponse(message="Salut")

  with patch("device.components.akorin.AkorinClient.process", AsyncMock(return_value=response)) as process:
    await component.start(AkorinConfig(wait_cue_delay=10), MagicMock(), shared_resources)
    await transcription_queue.put("bonjour")
    result = await asyncio.wait_for(processing_queue.get(), timeout=1)

  assert result is response
  process.assert_awaited_once()
  await component.stop()


@pytest.mark.asyncio
async def test_akorin_clears_follow_up_state_when_listening_is_cancelled() -> None:
  component = AkorinComponent(_make_settings())
  component._conversation_history = [
    ConversationMessage(role="user", content="allume la lumière"),
    ConversationMessage(role="assistant", content="Précisez un appareil et l'opération à appliquer."),
  ]
  component._continue_conversation_pending = True
  transcription_queue: asyncio.Queue[str] = asyncio.Queue()
  processing_queue: asyncio.Queue[ProcessingResponse] = asyncio.Queue()
  follow_up_reset_queue: asyncio.Queue[None] = asyncio.Queue()

  shared_resources = {
    "transcription_queue": transcription_queue,
    "processing_queue": processing_queue,
    "follow_up_reset_queue": follow_up_reset_queue,
    "language_state": {"language": "fr"},
    "device_context": lambda: {},
    "cancel_active_processing": AsyncMock(),
    "handle_task_done": lambda task: None,
  }

  await component.start(AkorinConfig(wait_cue_delay=10), MagicMock(), shared_resources)
  await follow_up_reset_queue.put(None)

  async def wait_until_cleared() -> None:
    while component._conversation_history or component._continue_conversation_pending:
      await asyncio.sleep(0)

  await asyncio.wait_for(wait_until_cleared(), timeout=1)

  assert component._conversation_history == []
  assert component._continue_conversation_pending is False
  await component.stop()


@pytest.mark.asyncio
async def test_akorin_cancels_previous_request_for_new_transcription() -> None:
  component = AkorinComponent(_make_settings())
  transcription_queue: asyncio.Queue[str] = asyncio.Queue()
  processing_queue: asyncio.Queue[ProcessingResponse] = asyncio.Queue()
  first_started = asyncio.Event()
  release_first = asyncio.Event()
  calls: list[str] = []

  shared_resources = {
    "transcription_queue": transcription_queue,
    "processing_queue": processing_queue,
    "language_state": {"language": "fr"},
    "device_context": lambda: {},
    "cancel_active_processing": AsyncMock(),
    "handle_task_done": lambda task: None,
  }

  async def process(message: str, **kwargs) -> ProcessingResponse:
    calls.append(message)

    if message == "premiere":
      first_started.set()
      await release_first.wait()
      return ProcessingResponse(message="ignored")

    return ProcessingResponse(message="seconde")

  with patch("device.components.akorin.AkorinClient.process", AsyncMock(side_effect=process)):
    await component.start(AkorinConfig(wait_cue_delay=10), MagicMock(), shared_resources)
    await transcription_queue.put("premiere")
    await asyncio.wait_for(first_started.wait(), timeout=1)
    await transcription_queue.put("seconde")
    result = await asyncio.wait_for(processing_queue.get(), timeout=1)

  assert result.message == "seconde"
  assert calls == ["premiere", "seconde"]
  assert processing_queue.empty()
  release_first.set()
  await component.stop()


@pytest.mark.asyncio
async def test_akorin_rephrases_follow_up_before_next_processing_request() -> None:
  component = AkorinComponent(_make_settings())
  client = AkorinClient("http://akorin:5020")
  internal_llm = FakeInternalLLM(decisions=[True, False], rephrased=["cree un rappel demain"])
  config = AkorinConfig(wait_cue_delay=10)
  process = AsyncMock(
    side_effect=[
      ProcessingResponse(message="Pour quel jour ?"),
      ProcessingResponse(message="Le rappel est cree."),
    ]
  )
  with patch.object(client, "process", process):
    first = await component._process_message(client, internal_llm, config, "cree un rappel", {"language": "fr"}, lambda: {})
    second = await component._process_message(client, internal_llm, config, "demain", {"language": "fr"}, lambda: {})

  assert first is not None
  assert first.continue_conversation is True
  assert second is not None
  assert second.continue_conversation is False
  assert process.await_args_list[0].args == ("cree un rappel",)
  assert "history" not in process.await_args_list[0].kwargs
  assert process.await_args_list[1].args == ("cree un rappel demain",)
  assert "history" not in process.await_args_list[1].kwargs
  internal_llm.rephrase_follow_up.assert_awaited_once_with(
    "demain",
    language="fr",
    history=[
      ConversationMessage(role="user", content="cree un rappel"),
      ConversationMessage(role="assistant", content="Pour quel jour ?"),
    ],
  )
  assert internal_llm.should_continue_conversation.await_args_list[0].kwargs["history"] == [
    ConversationMessage(role="user", content="cree un rappel"),
    ConversationMessage(role="assistant", content="Pour quel jour ?"),
  ]


@pytest.mark.asyncio
async def test_akorin_does_not_rephrase_without_pending_continue_conversation() -> None:
  component = AkorinComponent(_make_settings())
  component._conversation_history = [
    ConversationMessage(role="user", content="cree un rappel"),
    ConversationMessage(role="assistant", content="Pour quel jour ?"),
  ]
  component._continue_conversation_pending = False
  client = AkorinClient("http://akorin:5020")
  internal_llm = FakeInternalLLM(decisions=[False], rephrased=["cree un rappel demain"])
  process = AsyncMock(return_value=ProcessingResponse(message="Le rappel est cree."))

  with patch.object(client, "process", process):
    result = await component._process_message(
      client,
      internal_llm,
      AkorinConfig(wait_cue_delay=10),
      "demain",
      {"language": "fr"},
      lambda: {},
    )

  assert result is not None
  assert process.await_args.args == ("demain",)
  internal_llm.rephrase_follow_up.assert_not_awaited()


@pytest.mark.asyncio
async def test_akorin_falls_back_when_continue_conversation_analysis_raises_unexpected_error() -> None:
  component = AkorinComponent(_make_settings())
  client = AkorinClient("http://akorin:5020")

  class BrokenInternalLLM:
    async def should_continue_conversation(self, *args, **kwargs) -> bool:
      raise AssertionError("analysis failed")

  process = AsyncMock(return_value=ProcessingResponse(message="Pour quel jour ?"))

  with patch.object(client, "process", process):
    result = await component._process_message(
      client,
      BrokenInternalLLM(),
      AkorinConfig(wait_cue_delay=10),
      "cree un rappel",
      {"language": "fr"},
      lambda: {},
    )

  assert result is not None
  assert result.continue_conversation is False


@pytest.mark.asyncio
async def test_akorin_reuses_original_transcription_when_rephrase_raises_unexpected_error() -> None:
  component = AkorinComponent(_make_settings())
  component._conversation_history = [
    ConversationMessage(role="user", content="cree un rappel"),
    ConversationMessage(role="assistant", content="Pour quel jour ?"),
  ]
  component._continue_conversation_pending = True
  client = AkorinClient("http://akorin:5020")

  class BrokenInternalLLM:
    async def rephrase_follow_up(self, *args, **kwargs) -> str:
      raise AssertionError("rephrase failed")

    async def should_continue_conversation(self, *args, **kwargs) -> bool:
      return False

  process = AsyncMock(return_value=ProcessingResponse(message="Le rappel est cree."))

  with patch.object(client, "process", process):
    result = await component._process_message(
      client,
      BrokenInternalLLM(),
      AkorinConfig(wait_cue_delay=10),
      "demain",
      {"language": "fr"},
      lambda: {},
    )

  assert result is not None
  assert process.await_args.args == ("demain",)


@pytest.mark.asyncio
async def test_akorin_timeout_returns_discreet_error_message() -> None:
  component = AkorinComponent(_make_settings(language="fr"))
  cues = []

  async def play_sound_cue(cue: str) -> None:
    cues.append(cue)

  component._play_sound_cue = play_sound_cue

  with patch(
    "device.components.akorin.AkorinClient.process",
    AsyncMock(side_effect=httpx.ReadTimeout("slow")),
  ):
    result = await component._process_message(
      AkorinClient("http://akorin:5020"),
      None,
      AkorinConfig(wait_cue_delay=10, timeout=0.01),
      "bonjour",
      {"language": "fr"},
      lambda: {},
    )

  assert result is not None
  assert result.commands[0].type == "announce"
  assert "reponse" in result.commands[0].text
  assert cues == ["cancel"]
