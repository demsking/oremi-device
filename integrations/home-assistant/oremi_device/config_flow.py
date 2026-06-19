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
import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_NODE_ID
from .const import CONF_TOPIC
from .const import DOMAIN


class OremiDeviceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
  """Configure an Oremi media player."""

  VERSION = 1

  async def async_step_mqtt(self, discovery_info: Any) -> FlowResult:
    """Handle an Oremi MQTT announcement."""
    try:
      payload = discovery_info.payload
      data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
      node_id = data[CONF_NODE_ID]
      topic = data[CONF_TOPIC]
    except (AttributeError, KeyError, TypeError, ValueError):
      return self.async_abort(reason="invalid_discovery")

    await self.async_set_unique_id(node_id)
    self._abort_if_unique_id_configured()
    return self.async_create_entry(title=f"Oremi Player ({node_id})", data={CONF_NODE_ID: node_id, CONF_TOPIC: topic})

  async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    """Handle manual setup for custom MQTT base topics."""
    if user_input is not None:
      node_id = user_input[CONF_NODE_ID].strip()
      topic = user_input[CONF_TOPIC].strip().rstrip("/")
      await self.async_set_unique_id(node_id)
      self._abort_if_unique_id_configured()
      return self.async_create_entry(title=f"Oremi Player ({node_id})", data={CONF_NODE_ID: node_id, CONF_TOPIC: topic})

    schema = vol.Schema({vol.Required(CONF_NODE_ID): str, vol.Required(CONF_TOPIC, default="oremi/device"): str})
    return self.async_show_form(step_id="user", data_schema=schema)
