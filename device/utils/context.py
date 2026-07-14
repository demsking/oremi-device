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

from pydantic import ValidationError

from ..core.mqtt import DEVICE_CONTEXT_OPTIONS
from ..core.mqtt import DEVICE_CONTEXT_TEXT_FIELDS
from ..core.settings import RuntimeSettingsCache
from ..core.settings import Settings

logger = logging.getLogger(__name__)


def build_device_context(settings: Settings) -> dict[str, str]:
  return settings.context.copy()


def validate_device_context_value(field: str, value: str) -> str | None:
  if field not in (*DEVICE_CONTEXT_TEXT_FIELDS, *DEVICE_CONTEXT_OPTIONS):
    logger.warning(f"Ignoring unsupported device context command: {field}")
    return None

  normalized = value.strip()

  if field == "preferred_currency":
    normalized = normalized.upper()

  try:
    RuntimeSettingsCache.model_validate({field: normalized})
  except ValidationError as error:
    logger.warning(f"Ignoring invalid device context command for {field}: {error}")
    return None

  return normalized


def parse_device_context_command_field(topic: str, context_prefix: str) -> str | None:
  prefix = f"{context_prefix.rstrip('/')}/"

  if not topic.startswith(prefix) or not topic.endswith("/set"):
    return None

  field = topic.removeprefix(prefix).removesuffix("/set")
  return field.strip("/") or None
