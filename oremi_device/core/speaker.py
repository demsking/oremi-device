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
import array
import subprocess  # nosec B404
import threading

import sounddevice as sd

from ..utils.logger import logger


class SpeakerDeviceError(Exception):
  """Raised when a speaker output device cannot be selected."""


class SpeakerPlaybackError(Exception):
  """Raised when media cannot be decoded or played."""


class Speaker:
  """Shared output-device and playback-control state."""

  def __init__(self, device_name: str | None = None, *, volume: float = 1.0, muted: bool = False) -> None:
    self._device_name = ""
    self._volume = 1.0
    self._muted = muted
    self._playback_lock = threading.Lock()
    self._playback_process: subprocess.Popen | None = None
    self._stop_playback = threading.Event()
    self.set_volume(volume)

    if device_name:
      self.select_device(device_name)
    else:
      try:
        default_device = sd.query_devices(kind="output")
      except Exception as error:
        raise SpeakerDeviceError(f"Failed to query the default speaker: {error}") from error

      if not default_device or default_device.get("max_output_channels", 0) <= 0:
        raise SpeakerDeviceError("No compatible speaker output device found")

      self._device_name = default_device["name"]

  @property
  def device_name(self) -> str:
    return self._device_name

  @property
  def volume(self) -> float:
    return self._volume

  @property
  def muted(self) -> bool:
    return self._muted

  @property
  def gain(self) -> float:
    """Return the gain future playback streams should apply."""
    return 0.0 if self._muted else self._volume

  def select_device(self, device_name: str) -> str:
    """Select a compatible output device and return its canonical name."""
    requested = device_name.strip().lower()

    if not requested:
      raise SpeakerDeviceError("Speaker output device name cannot be empty")

    matched_name = next(
      (name for name in self.get_compatible_output_devices() if requested in name.lower()),
      None,
    )

    if matched_name is None:
      raise SpeakerDeviceError(f"Speaker output device not found: {device_name}")

    try:
      sd.check_output_settings(device=matched_name)
    except Exception as error:
      raise SpeakerDeviceError(f"Speaker output device is not compatible: {matched_name}") from error

    self._device_name = matched_name
    return matched_name

  def set_muted(self, muted: bool) -> None:
    self._muted = muted

  def set_volume(self, volume: float) -> None:
    if not 0.0 <= volume <= 1.0:
      raise ValueError("Speaker volume must be between 0.0 and 1.0")

    self._volume = volume

  def play_url(self, media_url: str) -> None:
    """Decode and play an HTTP media URL, blocking until playback finishes."""
    if not media_url.startswith(("http://", "https://")):
      raise SpeakerPlaybackError("Speaker media URL must use HTTP or HTTPS")

    self.stop()
    self._stop_playback.clear()
    command = [
      "ffmpeg",
      "-nostdin",
      "-loglevel",
      "error",
      "-i",
      media_url,
      "-f",
      "f32le",
      "-acodec",
      "pcm_f32le",
      "-ac",
      "2",
      "-ar",
      "48000",
      "pipe:1",
    ]

    try:
      # media_url is restricted to HTTP(S) above and remains one argv value.
      process = subprocess.Popen(  # nosec B603  # pylint: disable=consider-using-with
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
      )
    except (FileNotFoundError, OSError) as error:
      raise SpeakerPlaybackError(f"Failed to start ffmpeg: {error}") from error

    with self._playback_lock:
      self._playback_process = process

    try:
      with sd.RawOutputStream(samplerate=48000, channels=2, dtype="float32", device=self._device_name) as stream:
        remainder = b""

        while not self._stop_playback.is_set():
          chunk = remainder + (process.stdout.read(16384) if process.stdout else b"")

          if not chunk:
            break

          complete_length = len(chunk) - (len(chunk) % 4)
          remainder = chunk[complete_length:]

          if complete_length == 0:
            continue

          samples = array.array("f")
          samples.frombytes(chunk[:complete_length])
          gain = self.gain

          if gain != 1.0:
            for index, sample in enumerate(samples):
              samples[index] = sample * gain

          stream.write(samples.tobytes())

      return_code = process.wait()

      if return_code and not self._stop_playback.is_set():
        raise SpeakerPlaybackError(f"ffmpeg exited with status {return_code}")
    except SpeakerPlaybackError:
      raise
    except Exception as error:
      raise SpeakerPlaybackError(f"Failed to play media: {error}") from error
    finally:
      if process.poll() is None:
        process.terminate()
        process.wait()

      with self._playback_lock:
        if self._playback_process is process:
          self._playback_process = None

  def stop(self) -> None:
    """Stop current media playback, if any."""
    self._stop_playback.set()

    with self._playback_lock:
      process = self._playback_process

    if process is not None and process.poll() is None:
      process.terminate()

  @staticmethod
  def get_compatible_output_devices() -> list[str]:
    try:
      devices = sd.query_devices()
    except Exception:
      return []

    compatible_devices = []
    seen = set()

    for device in devices:
      name = device["name"]

      if device.get("max_output_channels", 0) <= 0 or name in seen:
        continue

      try:
        sd.check_output_settings(device=name)
      except Exception as error:
        logger.debug(f"Ignoring incompatible speaker output '{name}': {error}")
        continue

      seen.add(name)
      compatible_devices.append(name)

    return compatible_devices
