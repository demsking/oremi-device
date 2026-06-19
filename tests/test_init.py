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
import urllib.parse

from oremi_device.components.andika import AndikaComponent
from oremi_device.components.ohunerin import OhunerinComponent
from oremi_device.core.models import AndikaConfig, DeviceConfig, DeviceContext, OhunerinConfig


def _make_context(**kwargs) -> DeviceContext:
  """Helper to create a DeviceContext with sensible defaults."""
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
  }
  defaults.update(kwargs)
  return DeviceContext(**defaults)


def test_build_connection_uri_default() -> None:
  context = _make_context(language="fr", ohunerin_host="localhost", ohunerin_port=5023)
  component = OhunerinComponent(context)
  uri = component.build_connection_uri()
  assert uri.startswith("ws://localhost:5023/ws?")

  # Parse the query params to verify
  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["fr"]


def test_build_connection_uri_secure() -> None:
  context = _make_context(
    language="en",
    ohunerin_host="127.0.0.1",
    ohunerin_port=8000,
    cert_file="cert.pem",
  )
  component = OhunerinComponent(context)
  uri = component.build_connection_uri()
  assert uri.startswith("wss://127.0.0.1:8000/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["en"]


def test_build_connection_uri_with_ohunerin_config() -> None:
  features_content = {}
  context = _make_context(language="fr", ohunerin_host="localhost", ohunerin_port=5023)
  component = OhunerinComponent(context)
  config = OhunerinConfig.model_validate(features_content)
  uri = component.build_connection_uri(config)
  assert uri.startswith("ws://localhost:5023/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["fr"]
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


def test_device_config_nested() -> None:
  """DeviceConfig expects component configs nested under the 'components' key."""
  nested_data = {
    "language": "fr",
    "components": {
      "ohunerin": {"threshold": 0.75},
      "andika": {"model": "vosk-model-small-en-us-0.15", "samplerate": 16000},
    },
  }
  config = DeviceConfig.model_validate(nested_data)
  assert config.language == "fr"
  assert config.components.ohunerin is not None
  assert config.components.ohunerin.threshold == 0.75
  assert config.components.andika is not None
  assert config.components.andika.model == "vosk-model-small-en-us-0.15"
  assert config.components.andika.samplerate == 16000


def test_build_andika_connection_uri_default() -> None:
  context = _make_context(andika_host="andika", andika_port=5315)
  component = AndikaComponent(context)
  uri = component.build_connection_uri()
  assert uri.startswith("ws://andika:5315/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["model"] == ["vosk-model-small-fr-0.22"]
  assert params["samplerate"] == ["16000"]


def test_build_andika_connection_uri_with_config() -> None:
  context = _make_context(andika_host="127.0.0.1", andika_port=8080, cert_file="cert.pem")
  component = AndikaComponent(context)
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


def test_andika_ha_entities() -> None:
  context = _make_context()
  component = AndikaComponent(context)
  entities = component.ha_entities(
    "oremi-device-test-node",
    "oremi/device/test-node",
    {"identifiers": ["oremi-device-test-node"]},
  )

  assert len(entities) == 1
  ha_domain, entity_slug, payload = entities[0]
  assert ha_domain == "sensor"
  assert entity_slug == "transcription"
  assert payload["name"] == "Transcription"
  assert payload["unique_id"] == "oremi-device-test-node_transcription"
  assert payload["state_topic"] == "oremi/device/test-node/transcription/text"
  assert "value_template" not in payload
  assert "json_attributes_topic" not in payload
