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
from unittest.mock import ANY
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from oremi_device.components import COMPONENTS
from oremi_device.components.andika import AndikaComponent
from oremi_device.components.andika import AndikaTranscriber
from oremi_device.core.models import AndikaConfig
from oremi_device.core.models import DeviceContext


class AsyncMessages:
  def __init__(self, messages: list[str]) -> None:
    self.messages = messages

  async def __aiter__(self):
    for message in self.messages:
      yield message


class DelayedAsyncMessages:
  def __init__(self, messages: list[tuple[float, str]]) -> None:
    self.messages = messages

  async def __aiter__(self):
    for delay, message in self.messages:
      await asyncio.sleep(delay)
      yield message


def _make_context(**kwargs) -> DeviceContext:
  defaults = {
    "node_id": "test-node",
    "language": "fr",
    "delay": 3,
    "ohunerin_host": "localhost",
    "ohunerin_port": 5023,
    "andika_host": "andika",
    "andika_port": 5315,
    "cert_file": None,
  }
  defaults.update(kwargs)
  return DeviceContext(**defaults)


def test_andika_component_registered() -> None:
  config_model, component_model = COMPONENTS["andika"]

  assert config_model is AndikaConfig
  assert component_model is AndikaComponent


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_partial_results() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"partial": "bon", "confidence": 0.9})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_called_once_with(
    "transcription/partial",
    "bon",
    qos=1,
    retain=False,
    props=ANY,
  )
  assert mqtt_client.publish.call_args.kwargs["props"].MessageExpiryInterval == 3


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_final_results() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"text": "bonjour oremi", "confidence": 0.9})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_called_once_with(
    "transcription/text",
    "bonjour oremi",
    qos=1,
    retain=False,
    props=ANY,
  )


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_result_payloads() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": "bonjour oremi", "confidence": 0.9})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_nested_partial_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": {"partial": "bon", "confidence": 0.9}})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_nested_text_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": {"text": "bonjour oremi", "confidence": 0.9}})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_each_partial_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([
    json.dumps({"partial": "bon"}),
    json.dumps({"partial": "bon"}),
    json.dumps({"partial": "bonjour"}),
  ])
  transcriber = AndikaTranscriber(_make_context(delay=1), mqtt_client, websocket)

  await transcriber.transcribing()

  assert mqtt_client.publish.call_count == 3
  assert [call.args[1] for call in mqtt_client.publish.call_args_list] == ["bon", "bon", "bonjour"]


@pytest.mark.asyncio
async def test_andika_transcriber_uses_context_delay_as_message_expiry() -> None:
  mqtt_client = MagicMock()
  websocket = DelayedAsyncMessages([
    (0, json.dumps({"partial": "bon"})),
    (0.02, json.dumps({"partial": "bon"})),
  ])
  transcriber = AndikaTranscriber(_make_context(delay=5), mqtt_client, websocket)

  await transcriber.transcribing()

  assert mqtt_client.publish.call_count == 2
  assert all(call.kwargs["props"].MessageExpiryInterval == 5 for call in mqtt_client.publish.call_args_list)


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_unknown_payloads() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"event": "ready"})])
  transcriber = AndikaTranscriber(_make_context(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish.assert_not_called()


def test_andika_get_supported_models() -> None:
  component = AndikaComponent(_make_context())
  response = MagicMock()
  response.json.return_value = [
    {"id": "vosk-model-small-fr-0.22", "name": "French (Small)", "language": "fr"},
    {"id": "vosk-model-small-en-us-0.15", "name": "English US (Small)", "language": "en"},
  ]

  with patch("oremi_device.components.andika.httpx.get", return_value=response) as mock_get:
    models = component._get_supported_models()  # noqa: SLF001

  mock_get.assert_called_once_with("http://andika:5315/api/models")
  response.raise_for_status.assert_called_once()
  assert [model.id for model in models] == ["vosk-model-small-fr-0.22", "vosk-model-small-en-us-0.15"]
  assert models[0].language == "fr"


def test_andika_get_supported_models_secure_endpoint() -> None:
  component = AndikaComponent(_make_context(andika_host="127.0.0.1", andika_port=9443, cert_file="cert.pem"))
  response = MagicMock()
  response.json.return_value = []

  with patch("oremi_device.components.andika.httpx.get", return_value=response) as mock_get:
    assert component._get_supported_models() == []  # noqa: SLF001

  mock_get.assert_called_once_with("https://127.0.0.1:9443/api/models")


def test_andika_get_supported_models_returns_empty_on_error() -> None:
  component = AndikaComponent(_make_context())

  with patch("oremi_device.components.andika.httpx.get", side_effect=RuntimeError("offline")):
    assert component._get_supported_models() == []  # noqa: SLF001
