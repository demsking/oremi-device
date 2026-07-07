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

from oremi_device.components import COMPONENTS
from oremi_device.components.akorin import AkorinClient
from oremi_device.components.akorin import AkorinComponent
from oremi_device.components.akorin import is_cancellation_request
from oremi_device.core.models import AkorinConfig
from oremi_device.core.models import ProcessingResponse
from oremi_device.core.models import SpeakCommand
from oremi_device.core.settings import DeviceSettings


def _make_settings(**kwargs) -> DeviceSettings:
  defaults = {
    "node_id": "test-node",
    "language": "fr",
    "ohunerin_host": "localhost",
    "andika_host": "andika",
    "mqtt_broker": "mqtt",
    "akorin_url": "http://akorin:5020",
  }
  defaults.update(kwargs)
  return DeviceSettings(_env_file=None, **defaults)


def test_akorin_component_registered() -> None:
  config_model, component_model = COMPONENTS["akorin"]

  assert config_model is AkorinConfig
  assert component_model is AkorinComponent


@pytest.mark.parametrize("message", ["stop", "annule", "annuler ca", "arrête", "ne fais rien"])
def test_akorin_detects_cancellation_requests(message: str) -> None:
  assert is_cancellation_request(message) is True


@pytest.mark.asyncio
async def test_akorin_client_posts_agent_request() -> None:
  response = MagicMock()
  response.json.return_value = {"message": "Bonjour"}
  context = AsyncMock()
  http_client = context.__aenter__.return_value
  http_client.post.return_value = response

  with patch("oremi_device.components.akorin.httpx.AsyncClient", return_value=context) as client_class:
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
      "language": "fr",
      "context": {"timezone": "Europe/Paris"},
      "tags": ["device_id:test-node"],
    },
  )
  response.raise_for_status.assert_called_once()
  assert result.resolved_commands() == [SpeakCommand(type="speak", text="Bonjour")]


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

  with patch("oremi_device.components.akorin.AkorinClient.process", AsyncMock(return_value=response)) as process:
    await component.start(AkorinConfig(wait_cue_delay=10), MagicMock(), shared_resources)
    await transcription_queue.put("bonjour")
    result = await asyncio.wait_for(processing_queue.get(), timeout=1)

  assert result is response
  process.assert_awaited_once()
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

  with patch("oremi_device.components.akorin.AkorinClient.process", AsyncMock(side_effect=process)):
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
async def test_akorin_timeout_returns_discreet_error_message() -> None:
  component = AkorinComponent(_make_settings(language="fr"))
  cues = []

  async def play_sound_cue(cue: str) -> None:
    cues.append(cue)

  component._play_sound_cue = play_sound_cue

  with patch(
    "oremi_device.components.akorin.AkorinClient.process",
    AsyncMock(side_effect=httpx.ReadTimeout("slow")),
  ):
    result = await component._process_message(
      AkorinClient("http://akorin:5020"),
      AkorinConfig(wait_cue_delay=10, timeout=0.01),
      "bonjour",
      {"language": "fr"},
      lambda: {},
    )

  assert result is not None
  assert result.commands[0].type == "announce"
  assert "reponse" in result.commands[0].text
  assert cues == ["cancel"]
