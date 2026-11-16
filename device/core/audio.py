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
import struct
import time
from typing import Any
from typing import ClassVar

import miniaudio


logger = logging.getLogger(__name__)


class AudioDeviceError(Exception):
  """Exception raised when an audio device cannot be found or initialized."""


_UNUSABLE_CAPTURE_PATTERNS = ("discard", "zero samples", "generate zero", "dummy")


def is_usable_capture_device(device: dict) -> bool:
  """Return whether a miniaudio capture device can provide real audio samples."""
  name = str(device.get("name", "")).lower()

  if any(pattern in name for pattern in _UNUSABLE_CAPTURE_PATTERNS):
    return False

  formats = device.get("formats") or []

  if formats and all((fmt.get("channels") or 0) <= 0 for fmt in formats):
    return False

  return True


_GENERIC_TERMS_TO_IGNORE: set[str] = {
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


def match_device_name(requested: str, candidate: str) -> bool:
  """Check if the requested device name matches the candidate device name."""
  req_lower = requested.lower().strip()
  cand_lower = candidate.lower().strip()

  # 1. Exact match
  if req_lower == cand_lower:
    return True

  # 2. Direct substring match
  if req_lower in cand_lower or cand_lower in req_lower:
    return True

  # 3. Token-based matching
  req_clean = re.sub(r"[^a-z0-9\s]", " ", req_lower)
  cand_clean = re.sub(r"[^a-z0-9\s]", " ", cand_lower)

  req_words = set(req_clean.split())
  cand_words = set(cand_clean.split())

  req_specific = {w for w in req_words if w not in _GENERIC_TERMS_TO_IGNORE and not w.isdigit() and len(w) > 2}
  cand_specific = {w for w in cand_words if w not in _GENERIC_TERMS_TO_IGNORE and not w.isdigit() and len(w) > 2}

  t1 = req_specific if req_specific and cand_specific else req_words
  t2 = cand_specific if req_specific and cand_specific else cand_words

  if t1 and t2:
    if t1.issubset(t2) or t2.issubset(t1):
      return True

    common = t1 & t2
    if len(common) >= 2 or (len(common) / min(len(t1), len(t2)) >= 0.5):
      return True

  return False


def find_device_by_name(requested_name: str, devices: list[dict], *, filter_physical: bool = False) -> dict | None:
  """Find the best matching device from a list of miniaudio device dicts."""
  req = requested_name.strip()
  if not req:
    return None

  req_lower = req.lower()

  if filter_physical:
    devices = [d for d in devices if is_usable_capture_device(d)]

  # Pass 1: Exact match (case-insensitive)
  for dev in devices:
    if dev["name"].strip().lower() == req_lower:
      return dev

  search_lists = []
  if filter_physical:
    physical_devs = [d for d in devices if Audio.is_physical_microphone(d["name"])]
    if physical_devs:
      search_lists.append(physical_devs)

  search_lists.append(devices)

  # Pass 2: Substring match (pick match with smallest length difference)
  for dev_list in search_lists:
    matches = [d for d in dev_list if req_lower in d["name"].lower() or d["name"].lower() in req_lower]
    if matches:
      return min(matches, key=lambda d: abs(len(d["name"].strip()) - len(req)))

  # Pass 3: Token similarity score
  best_dev = None
  best_score = 0.0
  req_clean = re.sub(r"[^a-z0-9\s]", " ", req_lower)
  req_tokens = set(req_clean.split())
  req_specific = {w for w in req_tokens if w not in _GENERIC_TERMS_TO_IGNORE and not w.isdigit() and len(w) > 2}

  for dev_list in search_lists:
    for dev in dev_list:
      cand_clean = re.sub(r"[^a-z0-9\s]", " ", dev["name"].lower())
      cand_tokens = set(cand_clean.split())
      cand_specific = {w for w in cand_tokens if w not in _GENERIC_TERMS_TO_IGNORE and not w.isdigit() and len(w) > 2}

      t1 = req_specific if req_specific and cand_specific else req_tokens
      t2 = cand_specific if req_specific and cand_specific else cand_tokens

      if t1 and t2:
        intersection = t1 & t2
        union = t1 | t2
        score = len(intersection) / len(union) if union else 0.0
        if score > best_score:
          best_score = score
          best_dev = dev

  return best_dev if best_score > 0 else None


class Audio:
  """Audio class for handling audio input devices using miniaudio."""

  FORMAT_MAP: ClassVar[dict[str, miniaudio.SampleFormat]] = {
    "int16": miniaudio.SampleFormat.SIGNED16,
    "float32": miniaudio.SampleFormat.FLOAT32,
    "int32": miniaudio.SampleFormat.SIGNED32,
  }

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
        selected_dev = find_device_by_name(device_name, devices, filter_physical=True)
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

    self._native_formats = selected_dev.get("formats", [])
    self._native_samplerate = None
    self._native_channels = None
    self._native_format = None

    if self._native_formats and isinstance(self._native_formats, list) and len(self._native_formats) > 0:
      first_fmt = self._native_formats[0]
      self._native_samplerate = first_fmt.get("samplerate")
      self._native_channels = first_fmt.get("channels")
      self._native_format = first_fmt.get("format")

    self.sample_format = Audio.FORMAT_MAP.get(dtype, miniaudio.SampleFormat.SIGNED16)

    self._bytes_captured = 0
    self._chunks_captured = 0
    self._peak_since_log = 0
    self._last_stats_log_time = 0.0

    logger.info(f"Selected audio input device: {self._device_name} {self.info}")

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

        logger.info(
          "Starting audio stream for '%s' (requested_rate: %d Hz, format: %s, channels: 1, native_rate: %s)",
          self._device_name,
          self.samplerate,
          self.dtype,
          self._native_samplerate or "unknown",
        )

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
  def info(self) -> dict[str, Any]:
    info_dict: dict[str, Any] = {
      "samplerate": self.samplerate,
      "dtype": self.dtype,
      "channels": 1,
      "blocksize": self.blocksize,
    }

    if self._native_samplerate is not None:
      info_dict["native_samplerate"] = self._native_samplerate

    if self._native_channels is not None:
      info_dict["native_channels"] = self._native_channels

    if self._native_format is not None:
      info_dict["native_format"] = self._native_format

    return info_dict

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

    # First pass: try to find a physical, usable capture device.
    for idx, device in enumerate(devices):
      name = device["name"]

      if Audio.is_physical_microphone(name) and is_usable_capture_device(device):
        return {"index": idx, "name": name, "id": device.get("id")}

    # Second pass fallback: accept virtual devices only when they can provide
    # real samples. This prevents selecting ALSA's "Discard all samples" null
    # capture or a default device that reports zero input channels.
    for idx, device in enumerate(devices):
      if is_usable_capture_device(device):
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
    self._bytes_captured += len(data)
    self._chunks_captured += 1
    now = time.time()

    if self._last_stats_log_time == 0.0:
      self._last_stats_log_time = now

    sample = data[:400]
    sample = sample[: len(sample) - (len(sample) % 2)]

    if sample:
      chunk_peak = max(abs(value) for (value,) in struct.iter_unpack("<h", sample))
      self._peak_since_log = max(self._peak_since_log, chunk_peak)

    elapsed = now - self._last_stats_log_time
    if elapsed >= 5.0:
      bytes_per_sec = self._bytes_captured / elapsed
      samples_per_sec = bytes_per_sec / 2.0

      logger.debug(
        "Audio stream '%s' diagnostics (last %.1fs): %.1f B/s (~%.0f Hz mono PCM), %d chunks, peak=%d",
        self._device_name,
        elapsed,
        bytes_per_sec,
        samples_per_sec,
        self._chunks_captured,
        self._peak_since_log,
      )

      self._bytes_captured = 0
      self._chunks_captured = 0
      self._peak_since_log = 0
      self._last_stats_log_time = now

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

    # First pass: check for physical, usable devices (or the active device)
    for device in devices:
      name = device["name"]

      if not is_usable_capture_device(device):
        continue

      if not Audio.is_physical_microphone(name) and not (current_device and name == current_device):
        continue

      if name not in seen:
        seen.add(name)
        matched_devices.append(name)

    # If no compatible physical devices found, fall back to usable virtual devices
    if not matched_devices:
      for device in devices:
        name = device["name"]

        if is_usable_capture_device(device) and name not in seen:
          seen.add(name)
          matched_devices.append(name)

    return matched_devices
