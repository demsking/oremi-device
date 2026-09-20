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
import threading
from zoneinfo import ZoneInfo

import pytest

from device.core.timezone import _get_timezone_finder
from device.core.timezone import infer_timezone_from_coordinates


@pytest.mark.parametrize(
  ("latitude", "longitude", "expected"),
  [
    (48.8566, 2.3522, "Europe/Paris"),
    (4.0511, 9.7679, "Africa/Douala"),
    (40.7128, -74.0060, "America/New_York"),
    (35.6762, 139.6503, "Asia/Tokyo"),
  ],
)
def test_infer_timezone_resolves_known_locations(latitude: float, longitude: float, expected: str) -> None:
  assert infer_timezone_from_coordinates(latitude=latitude, longitude=longitude) == expected


def test_latitude_and_longitude_are_not_swapped() -> None:
  assert infer_timezone_from_coordinates(latitude=48.8566, longitude=2.3522) == "Europe/Paris"
  assert infer_timezone_from_coordinates(latitude=2.3522, longitude=48.8566) != "Europe/Paris"


def test_ocean_coordinates_return_a_valid_iana_timezone() -> None:
  # timezonefinder 9.0.0 ships ocean timezones, so a mid-ocean point resolves
  # to a valid IANA zone (for example Etc/GMT+3) rather than None.
  timezone = infer_timezone_from_coordinates(latitude=30.0, longitude=-40.0)

  assert timezone is not None
  ZoneInfo(timezone)


@pytest.mark.parametrize(
  ("latitude", "longitude"),
  [
    (91.0, 0.0),
    (-91.0, 0.0),
    (0.0, 181.0),
    (0.0, -181.0),
    (float("nan"), 0.0),
    (0.0, float("inf")),
  ],
)
def test_invalid_coordinates_raise_value_error(latitude: float, longitude: float) -> None:
  with pytest.raises(ValueError):
    infer_timezone_from_coordinates(latitude=latitude, longitude=longitude)


def test_non_numeric_coordinates_raise_type_error() -> None:
  with pytest.raises(TypeError):
    infer_timezone_from_coordinates(latitude=None, longitude=0.0)


def test_timezone_finder_is_created_per_thread() -> None:
  main_finder = _get_timezone_finder()
  assert _get_timezone_finder() is main_finder

  thread_finders = []

  def resolve() -> None:
    thread_finders.append(_get_timezone_finder())

  thread = threading.Thread(target=resolve)
  thread.start()
  thread.join()

  assert thread_finders
  assert thread_finders[0] is not main_finder
