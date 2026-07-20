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
import re
from typing import ClassVar

import miniaudio


logger = logging.getLogger(__name__)


class AudioDeviceError(Exception):
  """Exception raised when an audio device cannot be found or initialized."""


def match_device_name(requested: str, candidate: str) -> bool:
  """Check if the requested device name matches the candidate device name."""
  req_lower = requested.lower()
  cand_lower = candidate.lower()

  # 1. Exact or direct substring match
  if req_lower == cand_lower:
    return True
  if req_lower in cand_lower or cand_lower in req_lower:
    return True

  # 2. Token-based matching
  # Replace non-alphanumeric characters with spaces
  req_clean = re.sub(r"[^a-z0-9\s]", " ", req_lower)
  cand_clean = re.sub(r"[^a-z0-9\s]", " ", cand_lower)

  req_words = set(req_clean.split())
  cand_words = set(cand_clean.split())

  # Filter out generic terms, numbers, and short tokens
  generic = {
    "audio",
    "usb",
    "mono",
    "stereo",
    "analog",
    "digital",
    "fallback",
    "hw",
    "hda",
    "built-in",
    "pch",
    "intel",
    "nvidia",
    "card",
    "device",
    "sink",
    "source",
    "input",
    "output",
  }
  req_specific = {w for w in req_words if w not in generic and not w.isdigit() and len(w) > 2}
  cand_specific = {w for w in cand_words if w not in generic and not w.isdigit() and len(w) > 2}

  # If we have specific words to compare
  if req_specific and cand_specific:
    if req_specific.issubset(cand_specific) or cand_specific.issubset(req_specific):
      return True
    if req_specific & cand_specific:
      return True

  return False


class Audio:
  """Audio class for handling audio input devices using miniaudio."""

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
    "monitor",
  ]

  def __init__(
    self,
    *,
    dtype: str = "int16",
    samplerate: int = 16000,
    blocksize: int = 4000,
    device_index: int | None = None,
    device_name: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
  ) -> None:
    if loop is None:
      try:
        loop = asyncio.get_running_loop()
      except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    self.loop = loop
    self.audio_queue = asyncio.Queue[bytes]()
    self._subscribers: set[asyncio.Queue[bytes]] = set()
    self._active_users = 0
    self.samplerate = samplerate
    self.blocksize = blocksize
    self.dtype = dtype
    self._capture_device: miniaudio.CaptureDevice | None = None
    self._is_active = False

    try:
      devices = miniaudio.Devices().get_captures()
    except Exception as error:
      raise AudioDeviceError(f"Failed to query audio devices: {error}") from error

    selected_dev = None

    if device_index is not None:
      if 0 <= device_index < len(devices):
        selected_dev = devices[device_index]
      else:
        raise AudioDeviceError(f"Invalid device index: {device_index}")
    elif device_name is not None:
      try:
        idx = int(device_name)

        if 0 <= idx < len(devices):
          selected_dev = devices[idx]
      except ValueError:
        for dev in devices:
          if Audio.is_physical_microphone(dev["name"]) and match_device_name(device_name, dev["name"]):
            selected_dev = dev
            break

        if selected_dev is None:
          for dev in devices:
            if match_device_name(device_name, dev["name"]):
              selected_dev = dev
              break

        if selected_dev is None:
          for dev in devices:
            if device_name.lower() in dev["name"].lower():
              selected_dev = dev
              break
    else:
      comp = Audio.find_compatible_device()

      if comp is not None:
        idx = comp["index"]

        if 0 <= idx < len(devices):
          selected_dev = devices[idx]

    if selected_dev is None:
      raise AudioDeviceError("No compatible audio input device found")

    self._device_name = selected_dev["name"]
    self._device_id = selected_dev.get("id")

    format_map = {
      "int16": miniaudio.SampleFormat.SIGNED16,
      "float32": miniaudio.SampleFormat.FLOAT32,
      "int32": miniaudio.SampleFormat.SIGNED32,
    }
    self.sample_format = format_map.get(dtype, miniaudio.SampleFormat.SIGNED16)

  def _capture_generator(self):
    data = yield
    while True:
      if data:
        self.loop.call_soon_threadsafe(self._publish_audio_data, bytes(data))
      data = yield

  def start_stream(self) -> None:
    if self._capture_device is None:
      try:
        gen = self._capture_generator()
        next(gen)
        self._capture_device = miniaudio.CaptureDevice(
          input_format=self.sample_format,
          nchannels=1,
          sample_rate=self.samplerate,
          device_id=self._device_id,
        )
        self._capture_device.start(gen)
        self._is_active = True
      except Exception as error:
        self._capture_device = None
        self._is_active = False
        raise AudioDeviceError(f"Failed to initialize audio device: {error}") from error

  async def __aenter__(self):
    self._active_users += 1

    if not self._is_active:
      self.start_stream()

    return self

  async def __aexit__(self, exc_type, exc, tb):
    self._active_users = max(0, self._active_users - 1)

    if self._active_users == 0 and self._is_active:
      self.stop()

  def __str__(self) -> str:
    return f"{self.device_name} with samplerate {self.samplerate}, blocksize {self.blocksize}, channels 1"

  @property
  def device_name(self) -> str:
    return self._device_name

  @property
  def info(self):
    return {
      "samplerate": self.samplerate,
      "dtype": self.dtype,
      "channels": 1,
      "blocksize": self.blocksize,
      "device": self._device_name,
    }

  def is_active(self) -> bool:
    return self._is_active

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
      devices = miniaudio.Devices().get_captures()
    except Exception:
      return None

    # First pass: try to find a physical, compatible device
    for idx, device in enumerate(devices):
      name = device["name"]
      if Audio.is_physical_microphone(name):
        return {"index": idx, "name": name, "id": device.get("id")}

    # Second pass fallback: if no physical compatible device, check any input device
    for idx, device in enumerate(devices):
      return {"index": idx, "name": device["name"], "id": device.get("id")}

    return None

  def restart_stream(self) -> None:
    active_users = self._active_users
    self.stop()
    self._active_users = active_users

    if active_users > 0:
      try:
        self.start_stream()
      except Exception as error:
        logger.error(f"Failed to restart audio capture device: {error}")

  def _publish_audio_data(self, data: bytes) -> None:
    if self._subscribers:
      for queue in tuple(self._subscribers):
        try:
          queue.put_nowait(data)
        except asyncio.QueueFull:
          try:
            queue.get_nowait()
            queue.put_nowait(data)
          except Exception:
            pass
    else:
      try:
        self.audio_queue.put_nowait(data)
      except asyncio.QueueFull:
        try:
          self.audio_queue.get_nowait()
          self.audio_queue.put_nowait(data)
        except Exception:
          pass

  def subscribe(self) -> asyncio.Queue[bytes]:
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    self._subscribers.add(queue)
    return queue

  def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
    self._subscribers.discard(queue)

  async def data(self, queue: asyncio.Queue[bytes] | None = None):
    return await (queue or self.audio_queue).get()

  def stop(self) -> None:
    self._active_users = 0
    self._is_active = False

    if self._capture_device is not None:
      try:
        self._capture_device.stop()
        self._capture_device.close()
      except Exception:
        pass
      self._capture_device = None

  def close(self) -> None:
    self.stop()

  @staticmethod
  def get_compatible_input_devices(current_device: str | None = None) -> list[str]:
    try:
      devices = miniaudio.Devices().get_captures()
    except Exception:
      return []

    seen = set()
    matched_devices = []

    # First pass: check for physical devices (or active device)
    for device in devices:
      name = device["name"]

      if not Audio.is_physical_microphone(name) and not (current_device and name == current_device):
        continue

      if name not in seen:
        seen.add(name)
        matched_devices.append(name)

    # If no compatible physical devices found, fall back to virtual devices
    if not matched_devices:
      for device in devices:
        name = device["name"]

        if name not in seen:
          seen.add(name)
          matched_devices.append(name)

    return matched_devices
