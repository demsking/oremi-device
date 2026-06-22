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
from unittest.mock import patch

from oremi_device.__main__ import main
from oremi_device.core.settings import SettingsError


def test_main_prints_clean_configuration_errors(capsys) -> None:
  error = SettingsError(
    [
      "OREMI_DEVICE_OHUNERIN_HOST is required",
      "OREMI_DEVICE_MQTT_PORT must be at most 65535",
    ]
  )

  with patch("oremi_device.__main__.start", side_effect=error):
    result = main([])

  captured = capsys.readouterr()
  assert result == 2
  assert captured.out == ""
  assert captured.err == (
    "oremi-device: configuration error\n"
    "  - OREMI_DEVICE_OHUNERIN_HOST is required\n"
    "  - OREMI_DEVICE_MQTT_PORT must be at most 65535\n"
  )
  assert "Traceback" not in captured.err
