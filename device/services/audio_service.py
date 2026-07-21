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
import asyncio
import logging

import miniaudio

from device.core.audio import Audio
from device.core.audio import AudioDeviceError
from device.core.components import AudioStreamComponent
from device.core.components import DeviceState
from device.core.settings import Settings
from device.core.speaker import Speaker
from device.core.speaker import SpeakerDeviceError

logger = logging.getLogger(__name__)


class AudioService:
  def __init__(self, settings: Settings):
    self.settings = settings
    self.needs_audio = settings.microphone_enabled
    self.speaker_enabled = settings.speaker_enabled
    self.audio_stream: Audio | None = None
    self.speaker: Speaker | None = None
    self.device_state: DeviceState = {"microphone_muted": settings.microphone_muted}
    self.speaker_state = {"device": "", "muted": settings.speaker_muted, "volume": settings.speaker_volume}

  def initialize_hardware(self) -> None:
    if self.needs_audio:
      try:
        self.audio_stream = Audio(
          device_index=self.settings.microphone_device_index,
          device_name=self.settings.microphone_device,
        )

        logger.info(f"Active Microphone Device: {self.audio_stream.device_name}")
      except AudioDeviceError as error:
        logger.error(str(error))
        raise

    if self.speaker_enabled:
      try:
        self.speaker = Speaker(
          self.settings.speaker_device, volume=self.settings.speaker_volume, muted=self.settings.speaker_muted
        )
        self.speaker.verify_device()
        self.speaker_state["device"] = self.speaker.device_name

        logger.info(f"Active Speaker Device: {self.speaker.device_name}")
      except SpeakerDeviceError as error:
        logger.warning(f"Speaker initialization failed, running without speaker support: {error}")
        self.speaker = None
        self.speaker_enabled = False

  async def change_audio_device(self, target_device, components) -> bool:
    if self.audio_stream:
      try:
        await asyncio.to_thread(self.audio_stream.close)
      except Exception as err:
        logger.warning(f"Failed to close old stream: {err}")

    try:
      loop = asyncio.get_running_loop()

      def _create_audio():
        if target_device is not None and target_device != "__auto_select__":
          return (
            Audio(device_index=target_device, loop=loop)
            if isinstance(target_device, int)
            else Audio(device_name=str(target_device), loop=loop)
          )
        else:
          comp = Audio.find_compatible_device()

          if not comp:
            raise AudioDeviceError("No compatible device")

          return Audio(device_index=comp["index"], loop=loop)

      self.audio_stream = await asyncio.to_thread(_create_audio)

      for component in components:
        if isinstance(component, AudioStreamComponent):
          await component.on_device_changed(self.audio_stream)

      return True
    except Exception as err:
      logger.error(f"Device switch failed: {err}")
      self.audio_stream = None

      for component in components:
        if isinstance(component, AudioStreamComponent):
          await component.on_device_changed(None)

      return False

  async def monitor_devices(self, queue: asyncio.Queue) -> None:
    if not self.needs_audio:
      return

    def get_input_signatures():
      try:
        current_devs = miniaudio.Devices().get_captures()
        return {d["name"] for d in current_devs}
      except Exception as e:
        logger.warning(f"Failed to query audio devices: {e}")
        return set()

    last_signatures = await asyncio.to_thread(get_input_signatures)

    while True:
      await asyncio.sleep(3.0)

      current_signatures = await asyncio.to_thread(get_input_signatures)

      if current_signatures != last_signatures:
        logger.info("Audio device change detected.")
        last_signatures = current_signatures

        await queue.put("__auto_select__")
