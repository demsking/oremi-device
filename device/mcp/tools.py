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
from __future__ import annotations

import asyncio
from typing import Any
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from device.core.audio import Audio
from device.core.mcp import ClearQueueResponse
from device.core.mcp import DeviceCapabilities
from device.core.mcp import DeviceStatus
from device.core.mcp import EnqueueResponse
from device.core.mcp import InputDevicesResponse
from device.core.mcp import McpDevice
from device.core.mcp import OutputDevicesResponse
from device.core.mcp import PlaybackInfo
from device.core.mcp import PlaybackResponse
from device.core.mcp import QueueItem
from device.core.mcp import QueueResponse
from device.core.mcp import RemoveFromQueueResponse
from device.core.mcp import SeekResponse
from device.core.mcp import SetActiveInputDeviceResponse
from device.core.mcp import SetActiveOutputDeviceResponse
from device.core.mcp import SleepTimerResponse
from device.core.mcp import VolumeMutationResponse
from device.core.mcp import VolumeStatus
from device.core.settings import SettingsUpdates
from device.core.speaker import Speaker
from device.core.tts import TTSVoice
from device.core.tts import voices_for_language

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
MUTATION = ToolAnnotations(destructiveHint=False)


def register_mcp_tools(mcp: FastMCP, device: McpDevice) -> None:
  """Register MCP tools for managing and querying device settings and audio state."""
  app = device.app
  settings = app.settings

  @mcp.tool(
    name="get_device_status",
    title="Get Device Status",
    description="Get the current configuration, audio settings, and general status of the device.",
    annotations=READ_ONLY,
  )
  async def get_device_status() -> DeviceStatus:
    return device.get_device_status_model()

  @mcp.tool(
    name="list_voices",
    title="List Voices",
    description="List the available text-to-speech voices from the configured TTS backend.",
    annotations=READ_ONLY,
  )
  async def list_voices(language: str | None = None) -> list[TTSVoice]:
    client = device.get_tts_client()

    if not client:
      return []

    try:
      voices = await client.get_voices()
    except Exception as error:
      raise ToolError(f"Failed to fetch speech synthesis voices: {error}") from error

    if language:
      return voices_for_language(voices, language)
    return voices

  @mcp.tool(
    name="update_device_settings",
    title="Update Device Settings",
    description="Update one or more of the runtime settings/configuration values on the device.",
    annotations=MUTATION,
  )
  async def update_device_settings(
    language: Literal["fr", "en"] | None = None,
    location: str | None = None,
    timezone: str | None = None,
    temperature_unit: Literal["celsius", "fahrenheit"] | None = None,
    preferred_currency: str | None = None,
    measurement_system: Literal["metric", "imperial"] | None = None,
    distance_unit: Literal["kilometer", "mile"] | None = None,
    time_format: Literal["12h", "24h"] | None = None,
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] | None = None,
    first_day_of_week: Literal["monday", "sunday", "saturday"] | None = None,
    microphone_device: str | None = None,
    microphone_muted: bool | None = None,
    speaker_device: str | None = None,
    speaker_muted: bool | None = None,
    speaker_volume: float | None = None,
    tts_voice: str | None = None,
  ) -> DeviceStatus:
    updates: SettingsUpdates = {}

    for key, val in [
      ("language", language),
      ("location", location),
      ("timezone", timezone),
      ("temperature_unit", temperature_unit),
      ("preferred_currency", preferred_currency),
      ("measurement_system", measurement_system),
      ("distance_unit", distance_unit),
      ("time_format", time_format),
      ("date_format", date_format),
      ("first_day_of_week", first_day_of_week),
      ("microphone_device", microphone_device),
      ("microphone_muted", microphone_muted),
      ("speaker_device", speaker_device),
      ("speaker_muted", speaker_muted),
      ("speaker_volume", speaker_volume),
      ("tts_voice", tts_voice),
    ]:
      if val is not None:
        updates[key] = val

    if not updates:
      raise ToolError("No settings were provided to update")

    if speaker_volume is not None and not (0.0 <= speaker_volume <= 1.0):
      raise ToolError("Speaker volume must be a float between 0.0 and 1.0")

    try:
      await app.apply_settings_updates(updates)
    except Exception as error:
      raise ToolError(f"Failed to update device settings: {error}") from error

    return device.get_device_status_model()

  @mcp.tool(
    name="list_output_devices",
    title="List Output Devices",
    description="List all compatible output (speaker) audio devices.",
    annotations=READ_ONLY,
  )
  async def list_output_devices() -> OutputDevicesResponse:
    try:
      devices = Speaker.get_compatible_output_devices()
      return OutputDevicesResponse(devices=devices)
    except Exception as error:
      raise ToolError(f"Failed to query output devices: {error}") from error

  @mcp.tool(
    name="list_input_devices",
    title="List Input Devices",
    description="List all compatible input (microphone) audio devices.",
    annotations=READ_ONLY,
  )
  async def list_input_devices() -> InputDevicesResponse:
    try:
      devices = Audio.get_compatible_input_devices(current_device=settings.microphone_device)
      return InputDevicesResponse(devices=devices)
    except Exception as error:
      raise ToolError(f"Failed to query input devices: {error}") from error

  @mcp.tool(
    name="set_active_input_device",
    title="Set Active Input Device",
    description="Set the active input (microphone) device.",
    annotations=MUTATION,
  )
  async def set_active_input_device(device_name: str) -> SetActiveInputDeviceResponse:
    try:
      await app.apply_settings_updates({"microphone_device": device_name})
    except Exception as error:
      raise ToolError(f"Failed to set active input device: {error}") from error

    return SetActiveInputDeviceResponse(status="success", active_input_device=settings.microphone_device)

  @mcp.tool(
    name="set_active_output_device",
    title="Set Active Output Device",
    description="Set the active output (speaker) device.",
    annotations=MUTATION,
  )
  async def set_active_output_device(device_name: str) -> SetActiveOutputDeviceResponse:
    try:
      await app.apply_settings_updates({"speaker_device": device_name})
    except Exception as error:
      raise ToolError(f"Failed to set active output device: {error}") from error

    speaker_name = getattr(device.playback_state.speaker, "device_name", None) if device.playback_state.speaker else None
    current_speaker = speaker_name if isinstance(speaker_name, str) else settings.speaker_device

    return SetActiveOutputDeviceResponse(
      status="success",
      active_output_device=settings.speaker_device,
      current_speaker=current_speaker,
    )

  @mcp.tool(
    name="play",
    title="Play Playback",
    description="Start or resume playback of the media queue.",
    annotations=MUTATION,
  )
  async def play_tool() -> PlaybackResponse:
    loop = asyncio.get_running_loop()
    device.playback_state.resume_playback(loop)

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="pause",
    title="Pause Playback",
    description="Pause the currently playing media.",
    annotations=MUTATION,
  )
  async def pause_tool() -> PlaybackResponse:
    device.playback_state.pause_playback()

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="resume",
    title="Resume Playback",
    description="Resume paused media playback.",
    annotations=MUTATION,
  )
  async def resume_tool() -> PlaybackResponse:
    loop = asyncio.get_running_loop()
    device.playback_state.resume_playback(loop)

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="stop",
    title="Stop Playback",
    description="Stop media playback and reset position.",
    annotations=MUTATION,
  )
  async def stop_tool() -> PlaybackResponse:
    device.playback_state.stop_playback()

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="next",
    title="Next Track",
    description="Skip to the next track in the queue.",
    annotations=MUTATION,
  )
  async def next_tool() -> PlaybackResponse:
    device.playback_state.stop_playback()

    if device.playback_state.queue:
      device.playback_state.current_index = (device.playback_state.current_index + 1) % len(device.playback_state.queue)

    loop = asyncio.get_running_loop()
    device.playback_state.start_playback(loop)

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="previous",
    title="Previous Track",
    description="Skip to the previous track in the queue.",
    annotations=MUTATION,
  )
  async def previous_tool() -> PlaybackResponse:
    device.playback_state.stop_playback()

    if device.playback_state.queue:
      device.playback_state.current_index = (device.playback_state.current_index - 1) % len(device.playback_state.queue)

    loop = asyncio.get_running_loop()
    device.playback_state.start_playback(loop)

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="seek",
    title="Seek Position",
    description="Seek to a position in seconds in the current track.",
    annotations=MUTATION,
  )
  async def seek(position: float) -> SeekResponse:
    device.playback_state.simulated_position = position

    return SeekResponse(
      status="success",
      message="Simulated seek completed.",
      position=device.playback_state.simulated_position,
    )

  @mcp.tool(
    name="get_volume",
    title="Get Volume",
    description="Get the current volume level and mute status of the speaker.",
    annotations=READ_ONLY,
  )
  async def get_volume() -> VolumeStatus:
    return device.get_volume_model()

  @mcp.tool(
    name="set_volume",
    title="Set Volume",
    description="Set the volume level of the speaker (float between 0.0 and 1.0).",
    annotations=MUTATION,
  )
  async def set_volume(volume: float) -> VolumeMutationResponse:
    if not (0.0 <= volume <= 1.0):
      raise ToolError("Volume must be a float between 0.0 and 1.0")

    try:
      await app.apply_settings_updates({"speaker_volume": volume})
    except Exception as error:
      raise ToolError(f"Failed to set volume: {error}") from error

    return VolumeMutationResponse(status="success", volume=volume)

  @mcp.tool(
    name="mute",
    title="Mute Speaker",
    description="Mute the speaker.",
    annotations=MUTATION,
  )
  async def mute_tool() -> VolumeMutationResponse:
    try:
      await app.apply_settings_updates({"speaker_muted": True})
    except Exception as error:
      raise ToolError(f"Failed to mute: {error}") from error

    return VolumeMutationResponse(status="success", muted=True)

  @mcp.tool(
    name="unmute",
    title="Unmute Speaker",
    description="Unmute the speaker.",
    annotations=MUTATION,
  )
  async def unmute_tool() -> VolumeMutationResponse:
    try:
      await app.apply_settings_updates({"speaker_muted": False})
    except Exception as error:
      raise ToolError(f"Failed to unmute: {error}") from error

    return VolumeMutationResponse(status="success", muted=False)

  @mcp.tool(
    name="get_queue",
    title="Get Playback Queue",
    description="Get the list of all tracks in the playback queue.",
    annotations=READ_ONLY,
  )
  async def get_queue() -> QueueResponse:
    return device.get_queue_model()

  @mcp.tool(
    name="enqueue",
    title="Enqueue Track",
    description="Add a track to the playback queue.",
    annotations=MUTATION,
  )
  async def enqueue(
    url: str,
    title: str | None = None,
    artist: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> EnqueueResponse:
    index = device.playback_state.enqueue(url, title, artist, metadata)
    raw_item = device.playback_state.queue[index]
    item = QueueItem(url=raw_item.url, title=raw_item.title, artist=raw_item.artist, metadata=raw_item.metadata)

    return EnqueueResponse(status="success", enqueued_index=index, item=item)

  @mcp.tool(
    name="remove_from_queue",
    title="Remove from Queue",
    description="Remove a track from the playback queue by its index.",
    annotations=MUTATION,
  )
  async def remove_from_queue(index: int) -> RemoveFromQueueResponse:
    if index < 0 or index >= len(device.playback_state.queue):
      raise ToolError(f"Invalid queue index: {index}")

    item = device.playback_state.queue.pop(index)

    if index == device.playback_state.current_index:
      device.playback_state.stop_playback()
    elif index < device.playback_state.current_index:
      device.playback_state.current_index -= 1

    return RemoveFromQueueResponse(
      status="success",
      removed_item=QueueItem(url=item.url, title=item.title, artist=item.artist, metadata=item.metadata),
    )

  @mcp.tool(
    name="clear_queue",
    title="Clear Queue",
    description="Remove all tracks from the playback queue.",
    annotations=MUTATION,
  )
  async def clear_queue() -> ClearQueueResponse:
    device.playback_state.clear_queue()

    return ClearQueueResponse(status="success", queue=[])

  @mcp.tool(
    name="play_url",
    title="Play URL Directly",
    description="Enqueue a URL and play it immediately.",
    annotations=MUTATION,
  )
  async def play_url(
    url: str,
    title: str | None = None,
    artist: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> PlaybackResponse:
    device.playback_state.clear_queue()

    index = device.playback_state.enqueue(url, title, artist, metadata)
    device.playback_state.current_index = index
    loop = asyncio.get_running_loop()
    device.playback_state.start_playback(loop)

    return PlaybackResponse(status="success", now_playing=device.get_playback_info())

  @mcp.tool(
    name="get_now_playing",
    title="Get Now Playing",
    description="Get details of the currently playing track.",
    annotations=READ_ONLY,
  )
  async def get_now_playing() -> PlaybackInfo:
    return device.get_playback_info()

  @mcp.tool(
    name="get_device_capabilities",
    title="Get Device Capabilities",
    description="Get a list of hardware capabilities supported by the device.",
    annotations=READ_ONLY,
  )
  async def get_device_capabilities() -> DeviceCapabilities:
    return device.get_capabilities_model()

  @mcp.tool(
    name="sleep_timer",
    title="Set Sleep Timer",
    description="Set a sleep timer to stop playback after the specified duration in minutes.",
    annotations=MUTATION,
  )
  async def sleep_timer_tool(duration_minutes: int) -> SleepTimerResponse:
    if duration_minutes <= 0:
      raise ToolError("Duration must be a positive integer.")

    if device.playback_state.sleep_timer_task and not device.playback_state.sleep_timer_task.done():
      device.playback_state.sleep_timer_task.cancel()

    device.playback_state.sleep_timer_seconds = duration_minutes * 60

    async def timer_task(seconds: int):
      await asyncio.sleep(seconds)
      device.playback_state.stop_playback()
      device.playback_state.sleep_timer_seconds = None

    loop = asyncio.get_running_loop()
    device.playback_state.sleep_timer_task = loop.create_task(timer_task(device.playback_state.sleep_timer_seconds))

    return SleepTimerResponse(status="success", sleep_timer_minutes=duration_minutes)
