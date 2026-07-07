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
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from device.core.cues import get_sound_cue_path
from device.core.speaker import Speaker
from device.core.speaker import SpeakerDeviceError
from device.core.speaker import SpeakerPlaybackError


@pytest.mark.parametrize(
  "cue",
  ["announcement", "cancel", "listening", "ready", "shutdown", "thinking", "volume"],
)
def test_bundled_sound_cues_exist(cue: str) -> None:
  assert get_sound_cue_path(cue).is_file()


@patch("sounddevice.query_devices")
def test_default_output(mock_query_devices) -> None:
  mock_query_devices.return_value = {"name": "Built-in Audio", "max_output_channels": 2}

  speaker = Speaker(volume=0.5)

  assert speaker.device_name == "Built-in Audio"
  assert speaker.volume == 0.5
  assert speaker.gain == 0.5


def test_muted_gain() -> None:
  with patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2}):
    speaker = Speaker(volume=0.75)

  speaker.set_muted(True)
  assert speaker.muted is True
  assert speaker.gain == 0.0


def test_ducking_reduces_only_media_gain_and_preserves_volume() -> None:
  with patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2}):
    speaker = Speaker(volume=0.8)

  speaker.begin_ducking()
  speaker.begin_ducking()

  assert speaker.playback_gain(duckable=True) == pytest.approx(0.2)
  assert speaker.playback_gain(duckable=False) == pytest.approx(0.8)
  assert speaker.volume == 0.8

  speaker.end_ducking()
  assert speaker.playback_gain(duckable=True) == pytest.approx(0.2)

  speaker.end_ducking()
  assert speaker.playback_gain(duckable=True) == pytest.approx(0.8)
  assert speaker.volume == 0.8


def test_invalid_volume() -> None:
  with patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2}):
    speaker = Speaker()

  with pytest.raises(ValueError):
    speaker.set_volume(1.1)


@patch("sounddevice.check_output_settings")
@patch("sounddevice.query_devices")
def test_select_output(mock_query_devices, mock_check_output) -> None:
  mock_query_devices.side_effect = [
    {"name": "Built-in Audio", "max_output_channels": 2},
    [
      {"name": "Microphone", "max_output_channels": 0},
      {"name": "USB Speaker", "max_output_channels": 2},
    ],
    {"name": "USB Speaker", "max_output_channels": 2},
  ]
  speaker = Speaker()

  assert speaker.select_device("usb") == "USB Speaker"
  assert speaker.device_name == "USB Speaker"
  mock_check_output.assert_called_with(device="USB Speaker")


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 0})
def test_output_required(mock_query_devices) -> None:
  with pytest.raises(SpeakerDeviceError):
    Speaker()


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
def test_empty_output_rejected(mock_query_devices) -> None:
  speaker = Speaker()

  with pytest.raises(SpeakerDeviceError):
    speaker.select_device("  ")


@patch("sounddevice.query_devices", return_value={"name": "Built-in Audio", "max_output_channels": 2})
@patch("sounddevice.RawOutputStream")
def test_play_url_decodes_audio_to_selected_device(mock_output_stream, mock_query_devices) -> None:
  speaker = Speaker(volume=0.5)
  process = MagicMock()
  process.stdout.read.side_effect = [(b"\x00\x00\x80?" * 4), b""]
  process.wait.return_value = 0
  process.poll.return_value = 0
  stream = mock_output_stream.return_value.__enter__.return_value

  with patch("device.core.speaker.subprocess.Popen", return_value=process) as popen:
    speaker.play_url("https://home-assistant.local/api/tts.wav")

  assert popen.call_args.args[0][0] == "ffmpeg"
  mock_output_stream.assert_called_once_with(
    samplerate=48000,
    channels=2,
    dtype="float32",
    device="Built-in Audio",
  )
  assert stream.write.call_count == 1


@patch("sounddevice.query_devices", return_value={"name": "Container Speaker", "max_output_channels": 1})
@patch("sounddevice.RawOutputStream")
def test_play_url_uses_mono_stream_when_output_device_is_mono(mock_output_stream, mock_query_devices) -> None:
  speaker = Speaker(volume=0.5)
  process = MagicMock()
  process.stdout.read.side_effect = [(b"\x00\x00\x80?" * 4), b""]
  process.wait.return_value = 0
  process.poll.return_value = 0

  with patch("device.core.speaker.subprocess.Popen", return_value=process) as popen:
    speaker.play_url("https://home-assistant.local/api/tts.wav")

  command = popen.call_args.args[0]
  assert command[command.index("-ac") + 1] == "1"
  mock_output_stream.assert_called_once_with(
    samplerate=48000,
    channels=1,
    dtype="float32",
    device="Container Speaker",
  )


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
def test_play_url_rejects_non_http_media(mock_query_devices) -> None:
  speaker = Speaker()

  with pytest.raises(SpeakerPlaybackError, match="HTTP or HTTPS"):
    speaker.play_url("file:///tmp/private.wav")


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
@patch("sounddevice.RawOutputStream")
def test_play_file_accepts_packaged_audio(mock_output_stream, mock_query_devices, tmp_path) -> None:
  cue = tmp_path / "cue.ogg"
  cue.write_bytes(b"OggS")
  speaker = Speaker()
  process = MagicMock()
  process.stdout.read.return_value = b""
  process.wait.return_value = 0
  process.poll.return_value = 0

  with patch("device.core.speaker.subprocess.Popen", return_value=process) as popen:
    speaker.play_file(cue)

  command = popen.call_args.args[0]
  assert command[command.index("-i") + 1] == str(cue)


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
@patch("sounddevice.RawOutputStream")
def test_play_url_supports_post_stream(mock_output_stream, mock_query_devices) -> None:
  speaker = Speaker()
  process = MagicMock()
  process.stdout.read.return_value = b""
  process.wait.return_value = 0
  process.poll.return_value = 0

  with patch("device.core.speaker.subprocess.Popen", return_value=process) as popen:
    speaker.play_url(
      "https://izwi.local/api/synthesize/stream",
      method="POST",
      body='{"voice":"af_heart","input":"long text"}',
    )

  command = popen.call_args.args[0]
  assert command[command.index("-method") + 1] == "POST"
  assert command[command.index("-content_type") + 1] == "application/json"
  expected_body = '{"voice":"af_heart","input":"long text"}'.encode("utf-8").hex()
  assert command[command.index("-post_data") + 1] == expected_body


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
@patch("sounddevice.RawOutputStream")
def test_play_url_forwards_http_headers(mock_output_stream, mock_query_devices) -> None:
  speaker = Speaker()
  process = MagicMock()
  process.stdout.read.return_value = b""
  process.wait.return_value = 0
  process.poll.return_value = 0

  with patch("device.core.speaker.subprocess.Popen", return_value=process) as popen:
    speaker.play_url(
      "https://edge-tts.local/v1/audio/speech",
      method="POST",
      body='{"input":"hello"}',
      headers={"Authorization": "Bearer secret"},
    )

  command = popen.call_args.args[0]
  assert command[command.index("-headers") + 1] == "Authorization: Bearer secret\r\n"


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
@patch("sounddevice.RawOutputStream")
def test_non_interrupting_speech_does_not_stop_media(mock_output_stream, mock_query_devices) -> None:
  speaker = Speaker()
  process = MagicMock()
  process.stdout.read.return_value = b""
  process.wait.return_value = 0
  process.poll.return_value = 0

  with (
    patch.object(speaker, "stop") as stop,
    patch("device.core.speaker.subprocess.Popen", return_value=process),
  ):
    speaker.play_url(
      "https://izwi.local/api/synthesize/stream?input=hello",
      interrupt=False,
      duckable=False,
    )

  stop.assert_not_called()


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
def test_stop_terminates_active_decoder(mock_query_devices) -> None:
  speaker = Speaker()
  process = MagicMock()
  process.poll.return_value = None
  speaker._playback_process = process  # noqa: SLF001

  speaker.stop()

  process.terminate.assert_called_once_with()


@patch("sounddevice.query_devices", return_value={"name": "Speaker", "max_output_channels": 2})
def test_pause_and_resume_signal_active_decoder(mock_query_devices) -> None:
  speaker = Speaker()
  process = MagicMock()
  process.poll.return_value = None
  speaker._playback_process = process  # noqa: SLF001

  speaker.pause()
  speaker.resume()

  assert process.send_signal.call_count == 2
