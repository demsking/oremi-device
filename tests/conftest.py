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
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_geocode(monkeypatch) -> None:
  """Automatically mock geocoding network calls for all tests."""
  mock_result = MagicMock()
  mock_result.latitude = 4.0510564
  mock_result.longitude = 9.7678687
  mock_result.address = "Douala, Littoral, Cameroon"

  def geocode_mock(location: str):
    if not location or not location.strip():
      return None
    return mock_result

  monkeypatch.setattr("device.core.settings.get_location_geocode", geocode_mock)
