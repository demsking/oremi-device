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
from unittest.mock import AsyncMock
from unittest.mock import patch

import httpx
import pytest

from device.components import COMPONENTS
from device.components.akorin import AkorinClient
from device.components.akorin import AkorinComponent
from device.components.akorin import is_cancellation_request
from device.core.models import AkorinConfig
from device.core.models import ProcessingResponse
from device.core.models import SpeakCommand
from device.core.settings import Settings


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


@pytest.mark.asyncio
async def test_akorin_client_posts_agent_request() -> None:
  client = AkorinClient("http://akorin:5020")
  response = httpx.Response(
    status_code=200,
    json={
      "service": "speak",
      "confidence": 1.0,
      "message": "Bonjour",
      "commands": [{"type": "speak", "text": "Bonjour"}],
    },
    request=httpx.Request("POST", "http://akorin:5020/api/agent/"),
  )

  with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)) as mock_post:
    result = await client.process(
      "bonjour",
      language="fr",
      context={"preferences": {"timezone": "Europe/Paris"}},
      tags=["device_id:test-node"],
      timeout=5.0,
    )

  mock_post.assert_called_once_with(
    url="http://akorin:5020/api/agent/",
    json={
      "message": "bonjour",
      "context": {"preferences": {"preferences": {"timezone": "Europe/Paris"}}, "language": "fr"},
      "tags": ["device_id:test-node"],
    },
  )
  assert result.resolved_commands() == [SpeakCommand(type="speak", text="Bonjour")]


@pytest.mark.asyncio
async def test_akorin_client_logs_info_and_debug(caplog: pytest.LogCaptureFixture) -> None:
  client = AkorinClient("http://akorin:5020")
  response = httpx.Response(
    status_code=200,
    json={"service": "weather", "confidence": 0.95, "message": "Weather is fine"},
    request=httpx.Request("POST", "http://akorin:5020/api/agent/"),
  )

  with caplog.at_level(logging.DEBUG):
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
      await client.process(
        "quelle météo ?",
        language="fr",
        context={},
        tags=["device_id:test-node"],
        timeout=5.0,
      )

  assert "Processing request: 'quelle météo ?'" in caplog.text
  assert "Processing completed (service=weather)" in caplog.text
  assert "Sending processing request to http://akorin:5020/api/agent/" in caplog.text


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
    await component.start(AkorinConfig(wait_cue_delay=10), shared_resources)
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

  with patch("device.components.akorin.AkorinClient.process", AsyncMock(side_effect=process)):
    await component.start(AkorinConfig(wait_cue_delay=10), shared_resources)
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
    "device.components.akorin.AkorinClient.process",
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
  assert cues == ["error"]
