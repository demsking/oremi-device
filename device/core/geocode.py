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
import logging
from typing import Any

from geopy.exc import GeocoderUnavailable
from geopy.geocoders import Nominatim

from device.core.package import APP_NAME
from device.core.package import APP_VERSION

logger = logging.getLogger(__name__)

_geocoder = Nominatim(user_agent=f"{APP_NAME}/{APP_VERSION}")
_unavailable_locations: set[str] = set()


def get_location_geocode(location: str) -> Any:
  normalized = location.strip()
  if not normalized:
    return None

  try:
    result = _geocoder.geocode(normalized)
    _unavailable_locations.discard(normalized)
    return result
  except GeocoderUnavailable as error:
    logger.warning(f"Geocoder service is unavailable for '{normalized}': {error}")
    _unavailable_locations.add(normalized)
    return None


def is_geocode_unavailable(location: str) -> bool:
  return location.strip() in _unavailable_locations
