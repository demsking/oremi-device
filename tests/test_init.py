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
import urllib.parse
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from device.components.andika import AndikaComponent
from device.components.ohunerin import OhunerinComponent
from device.core.models import AndikaConfig, OhunerinConfig
from device.core.settings import Settings


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
    "andika_port": 5315,
    "cert_file": None,
    "mqtt_broker": "mqtt",
  }
  defaults.update(kwargs)
  return Settings(_env_file=None, **defaults)


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
    cert_file="cert.pem",
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
  component = OhunerinComponent(_make_settings())

  with patch.object(component, "_get_server_info", return_value=None):
    entities = component.ha_entities(
      "oremi-device-test-node",
      "oremi/device/nodes/test-node",
      "oremi/device/nodes/test-node/available",
      {"identifiers": ["oremi-device-test-node"]},
    )

  payloads = {entity_slug: payload for _, entity_slug, payload in entities}
  assert payloads["wakeword"]["state_topic"] == "oremi/device/nodes/test-node/event"
  assert payloads["sound"]["state_topic"] == "oremi/device/nodes/test-node/event"
  assert payloads["wakeword"]["json_attributes_topic"] == "oremi/device/nodes/test-node/event"
  assert payloads["sound"]["json_attributes_topic"] == "oremi/device/nodes/test-node/event"
  assert "value_json.type == 'wakeword'" in payloads["wakeword"]["value_template"]
  assert "value_json.type == 'sound'" in payloads["sound"]["value_template"]
  assert all(payload["availability_topic"] == "oremi/device/nodes/test-node/available" for payload in payloads.values())


def test_build_andika_connection_uri_default() -> None:
  settings = _make_settings(andika_host="andika", andika_port=5315)
  component = AndikaComponent(settings)
  uri = component.build_connection_uri()
  assert uri.startswith("ws://andika:5315/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["model"] == ["vosk-model-small-fr-0.22"]
  assert params["samplerate"] == ["16000"]
  assert params["language"] == ["fr"]
  assert "timezone" not in params


def test_build_andika_connection_uri_with_config() -> None:
  settings = _make_settings(andika_host="127.0.0.1", andika_port=8080, cert_file="cert.pem")
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


def test_andika_ha_entities() -> None:
  settings = _make_settings()
  component = AndikaComponent(settings)
  entities = component.ha_entities(
    "oremi-device-test-node",
    "oremi/device/nodes/test-node",
    "oremi/device/nodes/test-node/available",
    {"identifiers": ["oremi-device-test-node"]},
  )

  assert len(entities) == 1
  ha_domain, entity_slug, payload = entities[0]
  assert ha_domain == "sensor"
  assert entity_slug == "transcription"
  assert payload["name"] == "Transcription"
  assert payload["unique_id"] == "oremi-device-test-node_transcription"
  assert payload["state_topic"] == "oremi/device/nodes/test-node/transcription/result"
  assert payload["availability_topic"] == "oremi/device/nodes/test-node/available"
  assert payload["value_template"] == "{{ value_json.text }}"
  assert "json_attributes_topic" not in payload


@pytest.mark.asyncio
async def test_ohunerin_stop_cancels_main_task_without_waiting_for_websocket_close() -> None:
  component = OhunerinComponent(_make_settings())
  component._websocket = MagicMock()  # noqa: SLF001
  component._task = asyncio.create_task(asyncio.Event().wait())  # noqa: SLF001

  await component.stop()

  assert component._task.cancelled()  # noqa: SLF001
  component._websocket.close.assert_not_called()  # noqa: SLF001


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
    await component.start(OhunerinConfig(), MagicMock(), shared_resources)
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(component.stop(), timeout=1)

  assert component.task.done()
  assert connection.enter_count == 1
