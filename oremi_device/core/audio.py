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
from typing import ClassVar

import sounddevice as sd


class AudioDeviceError(Exception):
  """Exception raised when an audio device cannot be found or initialized."""


class Audio:
  """Audio class for handling audio input devices."""

  BLACKLISTED_KEYWORDS: ClassVar[list[str]] = [
    "default",
    "sysdefault",
    "spdif",
    "dmix",
    "dsnoop",
    "pulse",
    "jack",
    "pipewire",
    "null",
    "loopback",
    "iec958",
  ]

  def __init__(
    self,
    *,
    dtype: str = "int16",
    samplerate: int = 16000,
    blocksize: int = 8000,
    device_index: int | None = None,
    device_name: str | None = None,
  ) -> None:
    try:
      loop = asyncio.get_running_loop()
    except RuntimeError:
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
    self.audio_queue = asyncio.Queue[bytes]()
    self._subscribers: set[asyncio.Queue[bytes]] = set()
    self._active_users = 0
    self.samplerate = samplerate
    self.blocksize = blocksize

    device: int | str | None = None

    if device_index is not None:
      device = device_index
    elif device_name is not None:
      try:
        device = int(device_name)
      except ValueError:
        # Find device matching the name (case-insensitive substring)
        try:
          devices = sd.query_devices()
        except Exception as error:
          raise AudioDeviceError(f"Failed to query audio devices: {error}") from error

        matched_index = None

        for idx, dev in enumerate(devices):
          if dev["max_input_channels"] > 0 and device_name.lower() in dev["name"].lower():
            matched_index = idx
            break

        if matched_index is None:
          for idx, dev in enumerate(devices):
            if device_name.lower() in dev["name"].lower():
              matched_index = idx
              break

        if matched_index is not None:
          device = matched_index
        else:
          device = device_name
    else:
      compatible = Audio.find_compatible_device()

      if isinstance(compatible, dict):
        device = compatible["index"]
      else:
        raise AudioDeviceError("No compatible audio input device found")

    try:
      self.stream = sd.RawInputStream(
        dtype=dtype,
        samplerate=samplerate,
        blocksize=blocksize,
        device=device,
        channels=1,
        callback=lambda indata, frames, time, status: loop.call_soon_threadsafe(self._publish_audio_data, bytes(indata)),
      )
    except sd.PortAudioError as error:
      raise AudioDeviceError(f"Failed to initialize audio device: {error}") from error

  async def __aenter__(self):
    self._active_users += 1

    if not self.stream.active:
      self.stream.start()

    return self

  async def __aexit__(self, exc_type, exc, tb):
    self._active_users = max(0, self._active_users - 1)

    if self._active_users == 0 and self.stream.active:
      self.stream.stop()

  def __str__(self) -> str:
    return f"{self.device_name} with samplerate {self.samplerate}, blocksize {self.blocksize}, channels {self.stream.channels}"

  @property
  def device_name(self) -> str:
    device_info = sd.query_devices(self.stream.device, "input")
    return device_info["name"]  # type: ignore

  @property
  def info(self):
    return {
      "samplerate": self.samplerate,
      "dtype": self.stream.dtype,
      "channels": self.stream.channels,
      "blocksize": self.blocksize,
      "device": self.stream.device,
    }

  def is_active(self) -> bool:
    return self.stream.active

  @staticmethod
  def is_physical_microphone(name: str) -> bool:
    name_lower = name.lower()

    for keyword in Audio.BLACKLISTED_KEYWORDS:
      if keyword == name_lower or (keyword != "default" and keyword in name_lower):
        return False

    return True

  @staticmethod
  def find_compatible_device() -> dict | None:
    try:
      devices = sd.query_devices()
    except Exception:
      return None

    # First pass: try to find a physical, compatible device
    for device in devices:
      if device["max_input_channels"] > 0:  # type: ignore
        name = device["name"]
        if Audio.is_physical_microphone(name):
          try:
            sd.check_input_settings(device=name, samplerate=16000)  # type: ignore
            return device  # type: ignore
          except Exception:
            pass

    # Second pass fallback: if no physical compatible device, check any input device
    for device in devices:
      if device["max_input_channels"] > 0:  # type: ignore
        try:
          sd.check_input_settings(device=device["name"], samplerate=16000)  # type: ignore
          return device  # type: ignore
        except Exception:
          pass

    return None

  def _publish_audio_data(self, data: bytes) -> None:
    if self._subscribers:
      for queue in tuple(self._subscribers):
        queue.put_nowait(data)
    else:
      self.audio_queue.put_nowait(data)

  def subscribe(self) -> asyncio.Queue[bytes]:
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    self._subscribers.add(queue)
    return queue

  def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
    self._subscribers.discard(queue)

  async def data(self, queue: asyncio.Queue[bytes] | None = None):
    return await (queue or self.audio_queue).get()

  def stop(self) -> None:
    self._active_users = 0

    if self.stream.active:
      self.stream.stop()

  @staticmethod
  def get_compatible_input_devices(current_device: str | None = None) -> list[str]:
    try:
      devices = sd.query_devices()
    except Exception:
      return []

    seen = set()
    matched_devices = []

    # First pass: check for physical devices (or active device)
    for device in devices:
      if device.get("max_input_channels", 0) > 0:
        name = device["name"]

        if not Audio.is_physical_microphone(name) and not (current_device and name == current_device):
          continue

        if current_device and name == current_device:
          if name not in seen:
            seen.add(name)
            matched_devices.append(name)
          continue

        try:
          sd.check_input_settings(device=name, samplerate=16000)

          if name not in seen:
            seen.add(name)
            matched_devices.append(name)
        except Exception:
          pass

    # If no compatible physical devices found, we fall back to virtual devices to ensure compatibility
    if not matched_devices:
      for device in devices:
        if device.get("max_input_channels", 0) > 0:
          name = device["name"]

          if current_device and name == current_device:
            if name not in seen:
              seen.add(name)
              matched_devices.append(name)
            continue

          try:
            sd.check_input_settings(device=name, samplerate=16000)

            if name not in seen:
              seen.add(name)
              matched_devices.append(name)
          except Exception:
            pass

    return matched_devices
