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
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

_timezone_finder = TimezoneFinder()


def infer_timezone_from_coordinates(*, latitude: float, longitude: float) -> str | None:
  timezone = _timezone_finder.timezone_at(lat=latitude, lng=longitude)

  if timezone:
    try:
      ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
      timezone = None

  return timezone
