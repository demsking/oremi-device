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
import urllib.parse
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from device.components.ohunerin import OhunerinComponent
from device.core.models import AndikaConfig
from device.core.models import OhunerinConfig
from device.core.settings import Settings
from device.core.stt import AndikaComponent


def _make_settings(**kwargs) -> Settings:
  """Create device settings with sensible test defaults."""
  defaults = {
    "node_id": "test-node",
    "language": "fr",
    "delay": 3,
    "conversation_timeout": 15,
    "ohunerin_host": "localhost",
    "ohunerin_port": 5023,
    "andika_host": "localhost",
    "andika_port": 5022,
    "andika_cert_file": None,
    "ohunerin_cert_file": None,
    "mqtt_broker": "mqtt",
  }
  defaults.update(kwargs)
  return Settings(_env_file=None, **defaults)


def test_component_reports_status_to_reporter() -> None:
  component = OhunerinComponent(_make_settings())
  calls: list[tuple[str, str, str | None]] = []
  component.bind_status_reporter(lambda name, status, detail: calls.append((name, status, detail)))

  component.report_status("online")
  component.report_status("error", "connection refused")

  assert component.status == "error"
  assert component.status_detail == "connection refused"
  assert calls == [("ohunerin", "online", None), ("ohunerin", "error", "connection refused")]


def test_build_connection_uri_default() -> None:
  settings = _make_settings(language="fr", ohunerin_host="localhost", ohunerin_port=5023)
  component = OhunerinComponent(settings)
  uri = component.build_connection_uri()
  assert uri.startswith("ws://localhost:5023/ws?")

  # Parse the query params to verify
  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["fr"]
  assert "timezone" not in params


def test_build_connection_uri_secure() -> None:
  settings = _make_settings(
    language="en",
    ohunerin_host="127.0.0.1",
    ohunerin_port=8000,
    ohunerin_cert_file="cert.pem",
  )
  component = OhunerinComponent(settings)
  uri = component.build_connection_uri()
  assert uri.startswith("wss://127.0.0.1:8000/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["en"]
  assert "timezone" not in params


def test_build_connection_uri_with_ohunerin_config() -> None:
  features_content = {}
  settings = _make_settings(language="fr", ohunerin_host="localhost", ohunerin_port=5023)
  component = OhunerinComponent(settings)
  config = OhunerinConfig.model_validate(features_content)
  uri = component.build_connection_uri(config)
  assert uri.startswith("ws://localhost:5023/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["fr"]
  assert "temperature-unit" not in params
  assert "wakewords" not in params
  assert "discriminants" not in params
  assert "allowlist" not in params


def test_ohunerin_config_with_threshold() -> None:
  # With explicit threshold
  features_content = {"threshold": 0.75}
  config = OhunerinConfig.model_validate(features_content)
  assert config.threshold == 0.75

  # Default threshold
  features_content_default = {}
  config_default = OhunerinConfig.model_validate(features_content_default)
  assert config_default.threshold == 0.65


def test_ohunerin_ha_entities_use_event_topics_and_node_availability() -> None:
  from device.core.mqtt import HomeAssistantDevice

  client = HomeAssistantDevice(
    broker="localhost",
    port=1883,
    topic="oremi/device",
    node_id="test-node",
    discovery_prefix="homeassistant",
  )
  mock_client_instance = MagicMock()
  client.client = mock_client_instance

  client.publish_discovery_configs(input_devices=[], current_device="")

  wakeword_calls = [
    call
    for call in mock_client_instance.publish.call_args_list
    if call[0][0].endswith("sensor/oremi-device-test-node/wakeword/config")
  ]
  sound_calls = [
    call
    for call in mock_client_instance.publish.call_args_list
    if call[0][0].endswith("sensor/oremi-device-test-node/sound/config")
  ]

  assert len(wakeword_calls) == 1
  assert len(sound_calls) == 1

  wakeword_payload = json.loads(wakeword_calls[0][0][1])
  sound_payload = json.loads(sound_calls[0][0][1])

  assert wakeword_payload["state_topic"] == "oremi/device/nodes/test-node/events/detection"
  assert sound_payload["state_topic"] == "oremi/device/nodes/test-node/events/detection"
  assert wakeword_payload["availability_topic"] == "oremi/device/nodes/test-node/available"
  assert sound_payload["availability_topic"] == "oremi/device/nodes/test-node/available"


def test_build_andika_connection_uri_default() -> None:
  settings = _make_settings(andika_host="andika", andika_port=5022)
  component = AndikaComponent(settings)
  uri = component.build_connection_uri()
  assert uri.startswith("ws://andika:5022/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["model"] == ["zhifeixie/Mega-ASR"]
  assert params["samplerate"] == ["16000"]
  assert params["language"] == ["fr"]
  assert "timezone" not in params


def test_build_andika_connection_uri_with_config() -> None:
  settings = _make_settings(andika_host="127.0.0.1", andika_port=8080, andika_cert_file="cert.pem")
  component = AndikaComponent(settings)
  config = AndikaConfig.model_validate(
    {
      "model": "vosk-model-small-en-us-0.15",
      "samplerate": 16000,
    }
  )
  uri = component.build_connection_uri(config)
  assert uri.startswith("wss://127.0.0.1:8080/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["model"] == ["vosk-model-small-en-us-0.15"]
  assert params["samplerate"] == ["16000"]
  assert params["show-words"] == ["False"]
  assert params["max-alternatives"] == ["0"]
  assert params["language"] == ["fr"]
  assert "temperature-unit" not in params


@pytest.mark.asyncio
async def test_ohunerin_reports_online_when_connected() -> None:
  entered = asyncio.Event()

  class BlockingWebSocket:
    def __aiter__(self):
      return self

    async def __anext__(self):
      await asyncio.Event().wait()
      raise StopAsyncIteration

  class Connection:
    async def __aenter__(self):
      entered.set()
      return BlockingWebSocket()

    async def __aexit__(self, exc_type, exc, traceback):
      return False

  component = OhunerinComponent(_make_settings())
  statuses: list[tuple[str, str, str | None]] = []
  component.bind_status_reporter(lambda name, status, detail: statuses.append((name, status, detail)))
  shared_resources = {
    "handle_task_done": None,
    "active_stream_container": {"stream": None},
    "wakeword_event": asyncio.Event(),
    "device_state": {"microphone_muted": True},
  }

  with patch("device.components.ohunerin.connect", return_value=Connection()):
    await component.start(OhunerinConfig(), shared_resources)
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert ("ohunerin", "online", None) in statuses
    await component.stop()


@pytest.mark.asyncio
async def test_andika_speaks_error_when_connection_fails() -> None:
  component = AndikaComponent(_make_settings())
  voice_error_handler = AsyncMock()
  shared_resources = {
    "handle_task_done": None,
    "active_stream_container": {"stream": MagicMock()},
    "wakeword_event": asyncio.Event(),
    "device_state": {"microphone_muted": False},
    "conversation_event_handler": AsyncMock(),
    "final_transcription_handler": None,
    "voice_error_handler": voice_error_handler,
  }
  shared_resources["wakeword_event"].set()

  with (
    patch.object(component, "_get_supported_models", return_value=[]),
    patch("device.core.stt.connect", side_effect=OSError("Andika is down")),
  ):
    await component.start(AndikaConfig(), shared_resources)
    await asyncio.sleep(0.05)
    await component.stop()

  voice_error_handler.assert_awaited()
  assert component.status == "error"


@pytest.mark.asyncio
async def test_andika_reports_idle_when_started() -> None:
  component = AndikaComponent(_make_settings())
  statuses: list[tuple[str, str, str | None]] = []
  component.bind_status_reporter(lambda name, status, detail: statuses.append((name, status, detail)))
  shared_resources = {
    "handle_task_done": None,
    "active_stream_container": {"stream": None},
    "wakeword_event": asyncio.Event(),
    "device_state": {"microphone_muted": False},
    "conversation_event_handler": None,
    "final_transcription_handler": None,
  }

  with patch.object(component, "_get_supported_models", return_value=[]):
    await component.start(AndikaConfig(), shared_resources)
    await asyncio.sleep(0.05)
    assert ("andika", "idle", None) in statuses
    await component.stop()


@pytest.mark.asyncio
async def test_ohunerin_stop_cancels_main_task_without_waiting_for_websocket_close() -> None:
  component = OhunerinComponent(_make_settings())
  component._websocket = MagicMock()
  component._task = asyncio.create_task(asyncio.Event().wait())

  await component.stop()

  assert component._task.cancelled()
  component._websocket.close.assert_not_called()


@pytest.mark.asyncio
async def test_ohunerin_stop_does_not_reconnect_after_detection_cancellation() -> None:
  entered = asyncio.Event()

  class BlockingWebSocket:
    def __aiter__(self):
      return self

    async def __anext__(self):
      await asyncio.Event().wait()
      raise StopAsyncIteration

  class Connection:
    enter_count = 0

    async def __aenter__(self):
      self.enter_count += 1
      entered.set()
      return BlockingWebSocket()

    async def __aexit__(self, exc_type, exc, traceback):
      return False

  connection = Connection()
  component = OhunerinComponent(_make_settings())
  shared_resources = {
    "handle_task_done": None,
    "active_stream_container": {"stream": None},
    "wakeword_event": asyncio.Event(),
    "device_state": {"microphone_muted": True},
  }

  with patch("device.components.ohunerin.connect", return_value=connection):
    await component.start(OhunerinConfig(), shared_resources)
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(component.stop(), timeout=1)

  assert component.task.done()
  assert connection.enter_count == 1
