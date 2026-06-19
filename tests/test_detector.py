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
# pylint: disable=invalid-name
import asyncio
import json
from unittest.mock import MagicMock
import pytest

from oremi_device.core.detector import SoundDetector
from oremi_device.core.models import DetectedSound


class MockWebSocket:
  def __init__(self, messages: list[str]) -> None:
    self.messages = messages

  def __aiter__(self) -> "MockWebSocket":
    return self

  async def __anext__(self) -> str:
    if not self.messages:
      raise StopAsyncIteration
    return self.messages.pop(0)


@pytest.mark.asyncio
async def test_detector_threshold_filtering() -> None:
  mock_mqtt = MagicMock()

  # Message 1: below threshold
  # Message 2: above threshold
  messages = [
    json.dumps(
      {
        "type": "sound",
        "sound": "cough",
        "score": 0.5,
        "date": "2026-06-15T09:00:00",
      }
    ),
    json.dumps(
      {
        "type": "sound",
        "sound": "cough",
        "score": 0.6677674,
        "date": "2026-06-13T07:35:04.123456",
      }
    ),
  ]
  mock_ws = MockWebSocket(messages)

  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=1, threshold=0.65)  # type: ignore

  # Run detecting (it terminates when messages are exhausted)
  await detector.detecting()

  # Only the second message should have been processed and published
  assert mock_mqtt.publish.call_count == 1
  args = mock_mqtt.publish.call_args[0]
  assert args[0] == "sound"
  data = json.loads(args[1])
  assert data["score"] == 0.6677674


@pytest.mark.asyncio
async def test_detector_cooldown_normal_sound() -> None:
  mock_mqtt = MagicMock()
  mock_ws = MagicMock()

  # Set delay to 1 second
  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=1, threshold=0.8)

  sound1: DetectedSound = {
    "type": "sound",
    "sound": "cough",
    "score": 0.9,
    "date": "2026-06-15T09:00:00",
  }

  # First occurrence should publish and schedule clearing task
  await detector.process_detected_sound(sound1)
  assert "cough" in detector.published_sound_sentinel
  assert mock_mqtt.publish.call_count == 1

  # Second occurrence immediately after should be ignored (cooldown active)
  mock_mqtt.publish.reset_mock()
  await detector.process_detected_sound(sound1)
  assert mock_mqtt.publish.call_count == 0

  # Wait for cooldown to expire
  await asyncio.sleep(1.1)

  # Cooldown is done, should be cleared from sentinel and clearing message sent
  assert "cough" not in detector.published_sound_sentinel

  # Verify that the clearing message was sent
  clearing_sent = False
  for call in mock_mqtt.publish.call_args_list:
    args = call[0]
    topic = args[0]
    payload = args[1]
    retain = call.kwargs.get("retain", False)
    data = json.loads(payload)
    if topic == "sound" and data["sound"] == "..." and retain is True:
      clearing_sent = True
  assert clearing_sent is True


@pytest.mark.asyncio
async def test_detector_wakeword_no_cooldown() -> None:
  mock_mqtt = MagicMock()
  mock_ws = MagicMock()
  wakeword_event = asyncio.Event()

  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=1, threshold=0.8, wakeword_event=wakeword_event)

  wakeword: DetectedSound = {
    "type": "wakeword",
    "sound": "hey assistant",
    "score": 0.9,
    "date": "2026-06-15T09:00:00",
  }

  # First occurrence
  await detector.process_detected_sound(wakeword)
  assert "hey-assistant" in detector.published_sound_sentinel
  assert mock_mqtt.publish.call_count == 1
  assert wakeword_event.is_set()

  # Second occurrence should publish immediately (no cooldown for wakeword)
  mock_mqtt.publish.reset_mock()
  await detector.process_detected_sound(wakeword)
  assert mock_mqtt.publish.call_count == 1


@pytest.mark.asyncio
async def test_detector_multiple_active_sounds_clearing() -> None:
  mock_mqtt = MagicMock()
  mock_ws = MagicMock()

  # Set delay to 1 second
  detector = SoundDetector(mock_mqtt, mock_ws, None, delay=1, threshold=0.8)

  sound1: DetectedSound = {
    "type": "sound",
    "sound": "cough",
    "score": 0.9,
    "date": "2026-06-15T09:00:00",
  }

  sound2: DetectedSound = {
    "type": "sound",
    "sound": "snoring",
    "score": 0.9,
    "date": "2026-06-15T09:00:00",
  }

  # Publish sound1
  await detector.process_detected_sound(sound1)
  # Publish sound2 after 0.5s
  await asyncio.sleep(0.5)
  await detector.process_detected_sound(sound2)

  # At t = 0.5s, both are in sentinel
  assert "cough" in detector.published_sound_sentinel
  assert "snoring" in detector.published_sound_sentinel

  # Reset mock to watch for clearing messages
  mock_mqtt.publish.reset_mock()

  # Wait 0.6s (total t = 1.1s). sound1's cooldown should expire.
  await asyncio.sleep(0.6)
  assert "cough" not in detector.published_sound_sentinel
  assert "snoring" in detector.published_sound_sentinel

  # Clearing message should NOT have been sent because snoring is still active
  # Verify that no clearing message of type "sound" with "..." was published
  for call in mock_mqtt.publish.call_args_list:
    args = call[0]
    topic = args[0]
    payload = args[1]
    data = json.loads(payload)
    if topic == "sound":
      assert data["sound"] != "..."

  # Wait another 0.5s (total t = 1.6s). sound2's cooldown should expire.
  await asyncio.sleep(0.5)
  assert "snoring" not in detector.published_sound_sentinel

  # Now, the clearing message should have been sent since no other sounds are active
  clearing_sent = False
  for call in mock_mqtt.publish.call_args_list:
    args = call[0]
    topic = args[0]
    payload = args[1]
    retain = call.kwargs.get("retain", False)
    data = json.loads(payload)
    if topic == "sound" and data["sound"] == "..." and retain is True:
      clearing_sent = True
  assert clearing_sent is True
