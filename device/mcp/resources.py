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
from mcp.server.mcpserver import MCPServer

from device.core.mcp import DeviceCapabilities
from device.core.mcp import DeviceStatus
from device.core.mcp import McpDevice
from device.core.mcp import PlaybackInfo
from device.core.mcp import QueueResponse
from device.core.mcp import SpeakersResourceModel
from device.core.mcp import VolumeStatus


def register_mcp_resources(mcp: MCPServer, device: McpDevice) -> None:
  """Register MCP resources for accessing device state and configurations directly."""

  @mcp.resource(
    "device:///status",
    name="get_device_status_resource",
    title="Device Status",
    description="Retrieve the current status, audio settings, and general configuration of the device.",
    mime_type="application/json",
  )
  async def get_device_status_resource() -> DeviceStatus:
    return device.get_device_status_model()

  @mcp.resource(
    "device:///settings",
    name="get_settings_resource",
    title="Device Settings",
    description="Retrieve raw, non-sensitive configuration settings of the device.",
    mime_type="application/json",
  )
  async def get_settings_resource() -> DeviceStatus:
    return device.get_device_status_model()

  @mcp.resource(
    "device:///speakers",
    name="get_speakers_resource",
    title="Device Speakers",
    description="Retrieve a list of speakers, active speaker, and mute/volume status.",
    mime_type="application/json",
  )
  async def get_speakers_resource() -> SpeakersResourceModel:
    return device.get_speakers_model()

  @mcp.resource(
    "device:///playing",
    name="get_playing_resource",
    title="Currently Playing Media",
    description="Retrieve details of what is currently playing on the device.",
    mime_type="application/json",
  )
  async def get_playing_resource() -> PlaybackInfo:
    return device.get_playback_info()

  @mcp.resource(
    "device:///queue",
    name="get_queue_resource",
    title="Playback Queue",
    description="Retrieve the current list of enqueued tracks.",
    mime_type="application/json",
  )
  async def get_queue_resource() -> QueueResponse:
    return device.get_queue_model()

  @mcp.resource(
    "device:///volume",
    name="get_volume_resource",
    title="Speaker Volume Status",
    description="Retrieve the current volume level and mute state of the speaker.",
    mime_type="application/json",
  )
  async def get_volume_resource() -> VolumeStatus:
    return device.get_volume_model()

  @mcp.resource(
    "device:///capabilities",
    name="get_capabilities_resource",
    title="Device Capabilities",
    description="Retrieve the hardware capabilities supported by the device.",
    mime_type="application/json",
  )
  async def get_capabilities_resource() -> DeviceCapabilities:
    return device.get_capabilities_model()
