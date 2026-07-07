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
import logging
import signal
import subprocess  # nosec B404
import threading
from pathlib import Path

import sounddevice as sd


logger = logging.getLogger(__name__)


class SpeakerDeviceError(Exception):
  """Raised when a speaker output device cannot be selected."""


class SpeakerPlaybackError(Exception):
  """Raised when media cannot be decoded or played."""


class Speaker:
  """Shared output-device and playback-control state."""

  def __init__(self, device_name: str | None = None, *, volume: float = 1.0, muted: bool = False) -> None:
    self._device_name = ""
    self._output_channels = 2
    self._volume = 1.0
    self._muted = muted
    self._playback_lock = threading.Lock()
    self._playback_process: subprocess.Popen | None = None
    self._playback_processes: dict[subprocess.Popen, threading.Event] = {}
    self._ducking_count = 0
    self._ducking_gain = 0.25
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
      self._output_channels = self._get_stream_channels(default_device)

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

  @property
  def output_channels(self) -> int:
    """Return the channel count used for output streams."""
    return self._output_channels

  def begin_ducking(self) -> None:
    """Reduce the gain of duckable streams until matching calls complete."""
    with self._playback_lock:
      self._ducking_count += 1

  def end_ducking(self) -> None:
    """Release one active ducking request without changing user volume."""
    with self._playback_lock:
      self._ducking_count = max(0, self._ducking_count - 1)

  def playback_gain(self, *, duckable: bool) -> float:
    """Return current gain for a main-media or foreground speech stream."""
    gain = self.gain

    with self._playback_lock:
      ducking = self._ducking_count > 0

    return gain * self._ducking_gain if duckable and ducking else gain

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

    try:
      device_info = sd.query_devices(matched_name, kind="output")
    except Exception as error:
      raise SpeakerDeviceError(f"Failed to query speaker output device: {matched_name}") from error

    self._device_name = matched_name
    self._output_channels = self._get_stream_channels(device_info)

    return matched_name

  def set_muted(self, muted: bool) -> None:
    self._muted = muted

  def set_volume(self, volume: float) -> None:
    if not 0.0 <= volume <= 1.0:
      raise ValueError("Speaker volume must be between 0.0 and 1.0")

    self._volume = volume

  def play_url(
    self,
    media_url: str,
    *,
    method: str = "GET",
    body: str | None = None,
    headers: dict[str, str] | None = None,
    interrupt: bool = True,
    duckable: bool = True,
  ) -> None:
    """Decode and play an HTTP media URL, blocking until playback finishes."""
    if not media_url.startswith(("http://", "https://")):
      raise SpeakerPlaybackError("Speaker media URL must use HTTP or HTTPS")

    self._play_source(
      media_url,
      method=method,
      body=body,
      headers=headers,
      interrupt=interrupt,
      duckable=duckable,
    )

  def play_file(self, media_path: Path, *, interrupt: bool = False, duckable: bool = False) -> None:
    """Decode a trusted packaged audio file."""
    resolved_path = media_path.resolve()

    if not resolved_path.is_file():
      raise SpeakerPlaybackError(f"Audio cue not found: {resolved_path.name}")

    self._play_source(str(resolved_path), interrupt=interrupt, duckable=duckable)

  def _play_source(
    self,
    media_source: str,
    *,
    method: str = "GET",
    body: str | None = None,
    headers: dict[str, str] | None = None,
    interrupt: bool,
    duckable: bool,
  ) -> None:

    if method not in ("GET", "POST"):
      raise SpeakerPlaybackError(f"Unsupported HTTP method: {method}")

    if method == "POST" and body is None:
      raise SpeakerPlaybackError("POST media playback requires a request body")

    if headers:
      for name, value in headers.items():
        if "\r" in name or "\n" in name or ":" in name:
          raise SpeakerPlaybackError("HTTP header names cannot contain separators")

        if "\r" in value or "\n" in value:
          raise SpeakerPlaybackError("HTTP header values cannot contain line breaks")

    if interrupt:
      self.stop()

    stop_event = threading.Event()
    command = [
      "ffmpeg",
      "-nostdin",
      "-loglevel",
      "error",
    ]

    if method == "POST":
      command.extend(
        [
          "-method",
          "POST",
          "-content_type",
          "application/json",
          "-post_data",
          (body or "").encode("utf-8").hex(),
        ]
      )

    if headers:
      header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
      command.extend(["-headers", header_lines])

    command.extend(
      [
        "-i",
        media_source,
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(self._output_channels),
        "-ar",
        "48000",
        "pipe:1",
      ]
    )

    try:
      # The source is validated by play_url() or play_file() and remains one argv value.
      process = subprocess.Popen(  # nosec B603  # pylint: disable=consider-using-with
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
      )
    except (FileNotFoundError, OSError) as error:
      raise SpeakerPlaybackError(f"Failed to start ffmpeg: {error}") from error

    with self._playback_lock:
      self._playback_processes[process] = stop_event

      if interrupt:
        self._playback_process = process

    try:
      with sd.RawOutputStream(
        samplerate=48000,
        channels=self._output_channels,
        dtype="float32",
        device=self._device_name,
      ) as stream:
        remainder = b""

        while not stop_event.is_set():
          chunk = remainder + (process.stdout.read(16384) if process.stdout else b"")

          if not chunk:
            break

          complete_length = len(chunk) - (len(chunk) % 4)
          remainder = chunk[complete_length:]

          if complete_length == 0:
            continue

          samples = array.array("f")
          samples.frombytes(chunk[:complete_length])
          gain = self.playback_gain(duckable=duckable)

          if gain != 1.0:
            for index, sample in enumerate(samples):
              samples[index] = sample * gain

          stream.write(samples.tobytes())

      return_code = process.wait()

      if return_code and not stop_event.is_set():
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
        self._playback_processes.pop(process, None)

        if self._playback_process is process:
          self._playback_process = None

  def stop(self) -> None:
    """Stop current media playback, if any."""
    with self._playback_lock:
      processes = list(self._playback_processes.items())
      current_process = self._playback_process
      known_processes = set(self._playback_processes)

    if current_process is not None and current_process not in known_processes:
      processes.append((current_process, threading.Event()))

    for process, stop_event in processes:
      stop_event.set()

      if process.poll() is None:
        process.terminate()

  def pause(self) -> None:
    """Pause the active decoder on platforms that support POSIX signals."""
    with self._playback_lock:
      process = self._playback_process

    if process is not None and process.poll() is None:
      process.send_signal(signal.SIGSTOP)

  def resume(self) -> None:
    """Resume a paused decoder."""
    with self._playback_lock:
      process = self._playback_process

    if process is not None and process.poll() is None:
      process.send_signal(signal.SIGCONT)

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

  @staticmethod
  def _get_stream_channels(device_info: dict) -> int:
    """Normalize output channel count to a stream-safe value."""
    max_channels = int(device_info.get("max_output_channels", 0))
    return 1 if max_channels <= 1 else 2
