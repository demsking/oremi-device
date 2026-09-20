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

from typing import Any
from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations
from pydantic import BaseModel

if TYPE_CHECKING:
  from device.core.app import DeviceApplication

from device.core.playback import PlaybackState
from device.core.speaker import Speaker

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True)
MUTATION = ToolAnnotations(destructive_hint=False)


class DeviceStatus(BaseModel):
  """Strongly-typed model representing the current device status."""

  node_id: str
  language: str
  location: str
  timezone: str
  temperature_unit: str
  preferred_currency: str
  measurement_system: str
  distance_unit: str
  time_format: str
  date_format: str
  first_day_of_week: str
  microphone_device: str | None
  microphone_muted: bool
  microphone_enabled: bool
  speaker_device: str | None
  speaker_muted: bool
  speaker_enabled: bool
  speaker_volume: float
  tts_voice: str | None


class OutputDevicesResponse(BaseModel):
  """Response listing the output (speaker) devices."""

  devices: list[str]


class InputDevicesResponse(BaseModel):
  """Response listing the input (microphone) devices."""

  devices: list[str]


class SetActiveInputDeviceResponse(BaseModel):
  """Response for setting active input device."""

  status: str
  active_input_device: str | None


class SetActiveOutputDeviceResponse(BaseModel):
  """Response for setting active output device."""

  status: str
  active_output_device: str | None
  current_speaker: str | None


class QueueItem(BaseModel):
  """Represents a media item in the queue."""

  url: str
  title: str
  artist: str
  metadata: dict[str, Any] = {}


class PlaybackInfo(BaseModel):
  """Information about the current playback status."""

  title: str | None
  artist: str | None
  url: str | None
  metadata: dict[str, Any] = {}
  is_playing: bool
  is_paused: bool
  position: float


class PlaybackResponse(BaseModel):
  """Response for playback action."""

  status: str
  now_playing: PlaybackInfo


class SeekResponse(BaseModel):
  """Response for seek action."""

  status: str
  message: str
  position: float


class VolumeStatus(BaseModel):
  """Current volume and mute status."""

  volume: float
  muted: bool


class VolumeMutationResponse(BaseModel):
  """Response for mutating volume/mute settings."""

  status: str
  volume: float | None = None
  muted: bool | None = None


class QueueResponse(BaseModel):
  """Response containing all items in the queue."""

  items: list[QueueItem]


class EnqueueResponse(BaseModel):
  """Response for enqueuing a track."""

  status: str
  enqueued_index: int
  item: QueueItem


class RemoveFromQueueResponse(BaseModel):
  """Response for removing a track from the queue."""

  status: str
  removed_item: QueueItem


class ClearQueueResponse(BaseModel):
  """Response for clearing the queue."""

  status: str
  queue: list[QueueItem] = []


class DeviceCapabilities(BaseModel):
  """Hardware and software capabilities of the device."""

  can_play_audio: bool
  can_record_audio: bool
  has_volume_control: bool
  has_mute_control: bool
  has_tts: bool
  supported_languages: list[str]


class SleepTimerResponse(BaseModel):
  """Response for sleep timer registration."""

  status: str
  sleep_timer_minutes: int


class SpeakersResourceModel(BaseModel):
  """Resource model representing the speakers status."""

  active_speaker: str | None
  compatible_speakers: list[str]
  muted: bool
  volume: float


class McpDevice:
  def __init__(self, app: DeviceApplication) -> None:
    self.app = app
    self.settings = app.settings
    self._real_playback_state: Any = None

  @property
  def playback_state(self) -> PlaybackState:
    if hasattr(self.app, "audio") and self.app.audio and getattr(self.app.audio, "speaker", None):
      speaker = self.app.audio.speaker
      pb_state = getattr(speaker, "playback_state", None)

      if isinstance(pb_state, PlaybackState):
        return pb_state

      if not hasattr(speaker, "_real_playback_state") or not isinstance(self._real_playback_state, PlaybackState):
        self._real_playback_state = PlaybackState(speaker)

      return self._real_playback_state

    if not hasattr(self, "_fallback_playback_state"):
      self._fallback_playback_state = PlaybackState()
    return self._fallback_playback_state

  def get_device_status_model(self) -> DeviceStatus:
    return DeviceStatus(
      node_id=self.settings.node_id,
      language=self.settings.language,
      location=self.settings.location,
      timezone=self.settings.timezone,
      temperature_unit=self.settings.temperature_unit,
      preferred_currency=self.settings.preferred_currency,
      measurement_system=self.settings.measurement_system,
      distance_unit=self.settings.distance_unit,
      time_format=self.settings.time_format,
      date_format=self.settings.date_format,
      first_day_of_week=self.settings.first_day_of_week,
      microphone_device=self.settings.microphone_device,
      microphone_muted=self.settings.microphone_muted,
      microphone_enabled=self.settings.microphone_enabled,
      speaker_device=self.settings.speaker_device,
      speaker_muted=self.settings.speaker_muted,
      speaker_enabled=self.settings.speaker_enabled,
      speaker_volume=self.settings.speaker_volume,
      tts_voice=self.settings.tts_voice,
    )

  def get_playback_info(self) -> PlaybackInfo:
    info = self.playback_state.get_now_playing()

    return PlaybackInfo(
      title=info["title"],
      artist=info["artist"],
      url=info["url"],
      metadata=info["metadata"],
      is_playing=info["is_playing"],
      is_paused=info["is_paused"],
      position=info["position"],
    )

  def get_queue_model(self) -> QueueResponse:
    return QueueResponse(
      items=[
        QueueItem(url=item.url, title=item.title, artist=item.artist, metadata=item.metadata)
        for item in self.playback_state.queue
      ]
    )

  def get_volume_model(self) -> VolumeStatus:
    speaker = self.playback_state.speaker
    vol = getattr(speaker, "volume", None) if speaker else None
    muted = getattr(speaker, "muted", None) if speaker else None

    final_vol = float(vol) if isinstance(vol, (int, float)) else self.settings.speaker_volume
    final_muted = muted if isinstance(muted, bool) else self.settings.speaker_muted

    return VolumeStatus(volume=final_vol, muted=final_muted)

  def get_capabilities_model(self) -> DeviceCapabilities:
    return DeviceCapabilities(
      can_play_audio=self.settings.speaker_enabled,
      can_record_audio=self.settings.microphone_enabled,
      has_volume_control=True,
      has_mute_control=True,
      has_tts=self.settings.izwi_url is not None or self.settings.edge_tts_url is not None,
      supported_languages=["fr", "en"],
    )

  def get_speakers_model(self) -> SpeakersResourceModel:
    return SpeakersResourceModel(
      active_speaker=self.settings.speaker_device,
      compatible_speakers=Speaker.get_compatible_output_devices(),
      muted=self.settings.speaker_muted,
      volume=self.settings.speaker_volume,
    )

  def get_tts_client(self):
    if self.settings.tts_backend == "edge-tts" and self.settings.edge_tts_url:
      from device.components.edge_tts import OpenAIEdgeTTSClient  # pylint: disable=import-outside-toplevel

      edge_tts_locale = self.settings.edge_tts_locale or {"fr": "fr-FR", "en": "en-US"}.get(self.settings.language)

      return OpenAIEdgeTTSClient(
        str(self.settings.edge_tts_url),
        api_key=self.settings.edge_tts_api_key,
        locale=edge_tts_locale,
        model=self.settings.edge_tts_model,
        response_format=self.settings.edge_tts_response_format,
        speed=self.settings.edge_tts_speed,
      )
    elif self.settings.izwi_url:
      from device.components.izwi import IzwiClient  # pylint: disable=import-outside-toplevel

      return IzwiClient(str(self.settings.izwi_url))

    return None
