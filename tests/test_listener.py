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

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import ConnectionClosedOK

from device.core.audio import AudioDeviceError
from device.core.listener import AudioListener


class FakeAudioStream:
  """Minimal asynchronous stand-in for device.core.audio.Audio."""

  def __init__(
    self,
    *,
    continuous_data: bool = False,
    timeout_data: bool = False,
    data_error: Exception | None = None,
  ) -> None:
    self.device_name = "Fake Microphone"
    self.samplerate = 16000
    self.queue: asyncio.Queue[bytes] = asyncio.Queue()
    self.unsubscribed: asyncio.Queue[bytes] | None = None
    self.restarts = 0
    self.on_restart = None
    self._continuous_data = continuous_data
    self._timeout_data = timeout_data
    self._data_error = data_error

  def subscribe(self) -> asyncio.Queue[bytes]:
    return self.queue

  def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
    self.unsubscribed = queue

  def is_active(self) -> bool:
    return True

  def stop_timeouts(self) -> None:
    self._timeout_data = False
    self._continuous_data = True

  async def data(self, queue: asyncio.Queue[bytes]) -> bytes:
    if self._timeout_data:
      await asyncio.sleep(0)
      raise TimeoutError

    if self._data_error is not None:
      await asyncio.sleep(0)
      raise self._data_error

    if self._continuous_data:
      await asyncio.sleep(0)
      return b"pcm-frame"

    return await queue.get()

  def restart_stream(self) -> None:
    self.restarts += 1

    if self.on_restart is not None:
      self.on_restart()

  async def __aenter__(self) -> "FakeAudioStream":
    return self

  async def __aexit__(self, exc_type, exc, traceback) -> bool:
    return False


class FakeWebSocket:
  """Minimal async stand-in that records sent messages or raises a configured error."""

  def __init__(self, *, send_error: Exception | None = None) -> None:
    self.sent: list[bytes | str] = []
    self.send_error = send_error
    self.attempts = 0

  async def send(self, message: bytes | str) -> None:
    self.attempts += 1

    if self.send_error is not None:
      await asyncio.sleep(0)
      error = self.send_error

      # A closed connection stays closed; only the first closure is observed.
      if isinstance(error, (ConnectionClosedOK, ConnectionClosedError)):
        self.send_error = None

      raise error

    self.sent.append(message)


async def _wait_until(predicate, timeout: float = 1.0) -> None:
  async with asyncio.timeout(timeout):
    while not predicate():
      await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_audio_listener_forwards_frames_and_stop_message() -> None:
  stream = FakeAudioStream()
  websocket = FakeWebSocket()
  listener = AudioListener(stream, websocket, stop_message='{"eof": 1}')

  stream.queue.put_nowait(b"pcm-frame-1")
  stream.queue.put_nowait(b"pcm-frame-2")
  task = asyncio.create_task(listener.listening())
  await _wait_until(lambda: len(websocket.sent) >= 2)

  websocket.send_error = ConnectionClosedOK(None, None)
  stream.queue.put_nowait(b"pcm-frame-3")

  await asyncio.wait_for(task, timeout=1.0)

  assert websocket.sent == [b"pcm-frame-1", b"pcm-frame-2", '{"eof": 1}']
  assert stream.unsubscribed is stream.queue


@pytest.mark.asyncio
async def test_audio_listener_restarts_stream_after_receive_timeouts() -> None:
  stream = FakeAudioStream(timeout_data=True)
  websocket = FakeWebSocket()

  def on_restart() -> None:
    stream.stop_timeouts()
    websocket.send_error = ConnectionClosedOK(None, None)

  stream.on_restart = on_restart
  listener = AudioListener(stream, websocket)

  await asyncio.wait_for(listener.listening(), timeout=2.0)

  assert stream.restarts == 1
  assert stream.unsubscribed is stream.queue


@pytest.mark.asyncio
async def test_audio_listener_tolerates_send_timeouts() -> None:
  stream = FakeAudioStream(continuous_data=True)
  websocket = FakeWebSocket(send_error=TimeoutError())
  listener = AudioListener(stream, websocket)

  task = asyncio.create_task(listener.listening())
  await _wait_until(lambda: websocket.attempts >= 3)

  websocket.send_error = ConnectionClosedOK(None, None)
  await asyncio.wait_for(task, timeout=1.0)

  # The listener resets its timeout counter after each successful receive, so
  # send timeouts alone never reach the restart threshold.
  assert stream.restarts == 0
  assert websocket.attempts >= 3
  assert stream.unsubscribed is stream.queue


@pytest.mark.asyncio
async def test_audio_listener_handles_normal_connection_closure() -> None:
  stream = FakeAudioStream(continuous_data=True)
  websocket = FakeWebSocket(send_error=ConnectionClosedOK(None, None))
  listener = AudioListener(stream, websocket)

  await asyncio.wait_for(listener.listening(), timeout=1.0)

  assert stream.restarts == 0
  assert stream.unsubscribed is stream.queue


@pytest.mark.asyncio
async def test_audio_listener_handles_abnormal_connection_closure(caplog) -> None:
  stream = FakeAudioStream(continuous_data=True)
  websocket = FakeWebSocket(send_error=ConnectionClosedError(None, None))
  listener = AudioListener(stream, websocket)

  with caplog.at_level(logging.ERROR):
    await asyncio.wait_for(listener.listening(), timeout=1.0)

  assert stream.restarts == 0
  assert stream.unsubscribed is stream.queue
  assert caplog.records


@pytest.mark.asyncio
async def test_audio_listener_propagates_audio_device_errors() -> None:
  stream = FakeAudioStream(data_error=AudioDeviceError("capture failed"))
  websocket = FakeWebSocket()
  listener = AudioListener(stream, websocket)

  with pytest.raises(AudioDeviceError):
    await asyncio.wait_for(listener.listening(), timeout=1.0)

  assert stream.unsubscribed is stream.queue


@pytest.mark.asyncio
async def test_audio_listener_without_stream_returns_immediately() -> None:
  listener = AudioListener(None, FakeWebSocket())

  await asyncio.wait_for(listener.listening(), timeout=1.0)
