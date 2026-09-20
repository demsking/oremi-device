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
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import PromptMessage
from mcp.types import TextContent
from pydantic import Field


def register_mcp_prompts(mcp: MCPServer) -> None:
  """Register MCP prompts for assisting users with device configurations and audio settings."""

  @mcp.prompt(
    name="configure_device",
    title="Configure Device",
    description="Assist the user in configuring the device settings.",
  )
  def configure_device(
    language: Annotated[str | None, Field(description="The language to set on the device (e.g., 'fr', 'en').")] = None,
    location: Annotated[str | None, Field(description="The physical location of the device.")] = None,
    timezone: Annotated[str | None, Field(description="The IANA timezone to set on the device.")] = None,
  ) -> list[PromptMessage]:
    steps = []

    if language:
      steps.append(f"- Set language to '{language}'")

    if location:
      steps.append(f"- Set location to '{location}'")

    if timezone:
      steps.append(f"- Set timezone to '{timezone}'")

    steps_str = "\n".join(steps) if steps else "- Update relevant settings based on the user's instructions"

    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to configure the device settings.\n\n"
            "Please assist them by performing the following actions:\n"
            f"{steps_str}\n\n"
            "1. Call the `update_device_settings` tool with the requested updates.\n"
            "2. Confirm to the user that the settings have been successfully updated."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="adjust_audio",
    title="Adjust Audio",
    description="Assist the user in adjusting the device audio volume or mute status.",
  )
  def adjust_audio(
    volume: Annotated[int | None, Field(description="The speaker volume level to set (0 to 100).")] = None,
    mute_speaker: Annotated[bool | None, Field(description="Whether to mute the speaker.")] = None,
    mute_microphone: Annotated[bool | None, Field(description="Whether to mute the microphone.")] = None,
  ) -> list[PromptMessage]:
    steps = []

    if volume is not None:
      steps.append(f"- Set speaker volume to {volume}% (as a float between 0.0 and 1.0, e.g., {volume / 100:.2f})")

    if mute_speaker is not None:
      action = "mute" if mute_speaker else "unmute"
      steps.append(f"- {action.capitalize()} the speaker")

    if mute_microphone is not None:
      action = "mute" if mute_microphone else "unmute"
      steps.append(f"- {action.capitalize()} the microphone")

    steps_str = "\n".join(steps) if steps else "- Adjust volume or mute status based on the user's instructions"

    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to adjust the audio settings on the device.\n\n"
            "Please follow these steps:\n"
            f"{steps_str}\n\n"
            "1. Call the `update_device_settings` tool with the correct arguments.\n"
            "2. Confirm to the user that the audio settings have been updated successfully."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="play_media",
    title="Play Media",
    description="Assist the user in playing media on the device.",
  )
  def play_media(
    url: Annotated[str | None, Field(description="The URL of the media file to play.")] = None,
    title: Annotated[str | None, Field(description="The title of the media.")] = None,
    artist: Annotated[str | None, Field(description="The artist name.")] = None,
  ) -> list[PromptMessage]:
    steps = []

    if url:
      steps.append(f"- Play media from URL '{url}'")

    if title:
      steps.append(f"- Media title: '{title}'")

    if artist:
      steps.append(f"- Artist: '{artist}'")

    steps_str = "\n".join(steps) if steps else "- Play the requested media"

    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            f"The user wants to play media.\n\nInstructions:\n{steps_str}\n\n"
            "1. Call the `play` or `play_url` tool as appropriate.\n"
            "2. Confirm to the user that the media is playing."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="pause_playback",
    title="Pause Playback",
    description="Assist the user in pausing media playback.",
  )
  def pause_playback() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to pause playback.\n\n"
            "1. Call the `pause` tool.\n"
            "2. Confirm to the user that playback has been paused."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="resume_playback",
    title="Resume Playback",
    description="Assist the user in resuming media playback.",
  )
  def resume_playback() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to resume playback.\n\n"
            "1. Call the `resume` tool.\n"
            "2. Confirm to the user that playback has been resumed."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="stop_playback",
    title="Stop Playback",
    description="Assist the user in stopping media playback.",
  )
  def stop_playback() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to stop playback.\n\n"
            "1. Call the `stop` tool.\n"
            "2. Confirm to the user that playback has been stopped."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="next_track",
    title="Next Track",
    description="Assist the user in skipping to the next track in the queue.",
  )
  def next_track() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to play the next track.\n\n"
            "1. Call the `next` tool.\n"
            "2. Confirm to the user that the next track is playing."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="previous_track",
    title="Previous Track",
    description="Assist the user in going back to the previous track.",
  )
  def previous_track() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to play the previous track.\n\n"
            "1. Call the `previous` tool.\n"
            "2. Confirm to the user that the previous track is playing."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="restart_track",
    title="Restart Track",
    description="Assist the user in restarting the current track.",
  )
  def restart_track() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to restart the current track.\n\n"
            "1. Call the `seek` tool with position 0.\n"
            "2. Confirm to the user that the track has been restarted."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="set_volume",
    title="Set Volume",
    description="Assist the user in setting the speaker volume level.",
  )
  def set_volume_prompt(
    volume: Annotated[int, Field(description="The target volume level (0 to 100).")],
  ) -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            f"The user wants to set the volume to {volume}%.\n\n"
            f"1. Call the `set_volume` tool with the argument {volume / 100:.2f}.\n"
            "2. Confirm to the user that the volume has been updated."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="increase_volume",
    title="Increase Volume",
    description="Assist the user in increasing the volume.",
  )
  def increase_volume() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to increase the volume.\n\n"
            "1. First, call `get_volume` to check the current level.\n"
            "2. Then, calculate a new volume (e.g., current + 0.10) and call `set_volume`.\n"
            "3. Confirm to the user that the volume has been increased."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="decrease_volume",
    title="Decrease Volume",
    description="Assist the user in decreasing the volume.",
  )
  def decrease_volume() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to decrease the volume.\n\n"
            "1. First, call `get_volume` to check the current level.\n"
            "2. Then, calculate a new volume (e.g., current - 0.10) and call `set_volume`.\n"
            "3. Confirm to the user that the volume has been decreased."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="mute_speaker",
    title="Mute Speaker",
    description="Assist the user in muting the speaker.",
  )
  def mute_speaker() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to mute the speaker.\n\n1. Call the `mute` tool.\n2. Confirm to the user that the speaker is muted."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="unmute_speaker",
    title="Unmute Speaker",
    description="Assist the user in unmuting the speaker.",
  )
  def unmute_speaker() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to unmute the speaker.\n\n"
            "1. Call the `unmute` tool.\n"
            "2. Confirm to the user that the speaker is unmuted."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="speaker_status",
    title="Speaker Status",
    description="Assist the user in checking the speaker status and volume details.",
  )
  def speaker_status() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to check the speaker status.\n\n"
            "1. Call `get_volume` and check the active speaker device.\n"
            "2. Summarize the volume level, mute status, and device name for the user."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="what's_playing",
    title="What's Playing",
    description="Assist the user in checking what is currently playing on the device.",
  )
  def whats_playing() -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to know what is currently playing.\n\n"
            "1. Call `get_now_playing` to retrieve the current playback information.\n"
            "2. Present the details (title, artist, state) to the user."
          ),
        ),
      )
    ]

  @mcp.prompt(
    name="sleep_timer",
    title="Sleep Timer",
    description="Assist the user in setting a sleep timer to stop playback after a duration.",
  )
  def sleep_timer(
    duration_minutes: Annotated[int, Field(description="The duration in minutes before stopping playback.")] = 15,
  ) -> list[PromptMessage]:
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            f"The user wants to set a sleep timer for {duration_minutes} minutes.\n\n"
            f"1. Schedule a sleep timer using the `sleep_timer` tool for {duration_minutes} minutes.\n"
            f"2. Confirm to the user that a sleep timer has been set for {duration_minutes} minutes."
          ),
        ),
      )
    ]
