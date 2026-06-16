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
import argparse
import json
from unittest.mock import patch
import urllib.parse

from oremi_device.components.ohunerin import OhunerinComponent
from oremi_device.core.models import DeviceConfig, OhunerinConfig


def test_build_connection_uri_default() -> None:
  args = argparse.Namespace(
    device_config=None,
    language="fr",
    ohunerin_host="localhost",
    ohunerin_port=5023,
    cert_file=None,
  )
  component = OhunerinComponent()
  uri = component.build_connection_uri(args)
  assert uri.startswith("ws://localhost:5023/ws?")

  # Parse the query params to verify
  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["fr"]


def test_build_connection_uri_secure() -> None:
  args = argparse.Namespace(
    device_config=None,
    language="en",
    ohunerin_host="127.0.0.1",
    ohunerin_port=8000,
    cert_file="cert.pem",
  )
  component = OhunerinComponent()
  uri = component.build_connection_uri(args)
  assert uri.startswith("wss://127.0.0.1:8000/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["en"]


def test_build_connection_uri_with_ohunerin_config(tmp_path) -> None:
  features_content = {
    "wakeword-detection": {
      "language": "en",
      "wakewords": [
        {
          "word": "hey assistant",
          "phones": ["hh ey aa ss ih ss t ah n t"],
          "discriminants": [{"word": "assistant", "phones": ["aa ss ih ss t ah n t"]}],
        }
      ],
    },
    "sound-detection": {"allowlist": ["Cough", "Snoring"]},
  }
  ohunerin_config = tmp_path / "ohunerin.json"
  ohunerin_config.write_text(json.dumps(features_content))

  args = argparse.Namespace(
    device_config=str(ohunerin_config),
    language="fr",  # should be overridden by features file for wakeword-detection
    ohunerin_host="localhost",
    ohunerin_port=5023,
    cert_file=None,
  )
  component = OhunerinComponent()
  config = OhunerinConfig.model_validate(features_content)
  uri = component.build_connection_uri(args, config)
  assert uri.startswith("ws://localhost:5023/ws?")

  parsed = urllib.parse.urlparse(uri)
  params = urllib.parse.parse_qs(parsed.query)
  assert params["features"] == ["wakeword-detection,sound-detection"]
  assert params["language"] == ["en"]

  wakewords = json.loads(params["wakewords"][0])
  assert wakewords[0]["word"] == "hey assistant"

  discriminants = json.loads(params["discriminants"][0])
  assert discriminants[0]["word"] == "assistant"

  assert params["allowlist"] == ["Cough,Snoring"]


def test_log_ohunerin_config_details_valid() -> None:
  features_content = {
    "wakeword-detection": {
      "language": "en",
      "wakewords": [
        {
          "word": "hey assistant",
          "phones": ["hh ey aa ss ih ss t ah n t"],
          "discriminants": [{"word": "assistant", "phones": ["aa ss ih ss t ah n t"]}],
        }
      ],
    },
    "sound-detection": {"allowlist": ["Cough", "Snoring"]},
  }

  config = OhunerinConfig.model_validate(features_content)
  component = OhunerinComponent()

  with patch("oremi_device.utils.logger.logger.info") as mock_info:
    component.log_ohunerin_config_details(config, "fr")

  logged_messages = [call[0][0] for call in mock_info.call_args_list]

  assert "Ohunerin Config Content Details:" in logged_messages
  assert "  - Feature: wakeword-detection" in logged_messages
  assert "    Default Language: en" in logged_messages
  assert "    Wake words [en]: hey assistant" in logged_messages
  assert "    Discriminants: assistant" in logged_messages
  assert "  - Feature: sound-detection" in logged_messages
  assert "    Allowlist: Cough, Snoring" in logged_messages


def test_ohunerin_config_with_threshold() -> None:
  # With explicit threshold
  features_content = {"threshold": 0.75, "sound-detection": {"allowlist": ["Cough", "Snoring"]}}
  config = OhunerinConfig.model_validate(features_content)
  assert config.threshold == 0.75
  assert config.sound_detection is not None
  assert config.sound_detection.allowlist == ["Cough", "Snoring"]

  # Default threshold
  features_content_default = {"sound-detection": {"allowlist": ["Cough", "Snoring"]}}
  config_default = OhunerinConfig.model_validate(features_content_default)
  assert config_default.threshold == 0.85


def test_device_config_nested() -> None:
  """DeviceConfig expects ohunerin config nested under the 'components.ohunerin' key."""
  nested_data = {"language": "fr", "components": {"ohunerin": {"threshold": 0.75, "sound-detection": {"allowlist": ["Cough"]}}}}
  config = DeviceConfig.model_validate(nested_data)
  assert config.language == "fr"
  assert config.components.ohunerin is not None
  assert config.components.ohunerin.threshold == 0.75
  assert config.components.ohunerin.sound_detection is not None
  assert config.components.ohunerin.sound_detection.allowlist == ["Cough"]
