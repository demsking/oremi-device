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
from unittest.mock import patch

import pytest

from device.__main__ import main
from device.core.app import classify_supervisor_done
from device.core.app import listening_task_failed
from device.core.app import parse_device_context_command_field
from device.core.app import should_continue_conversation
from device.core.app import should_play_follow_up_end_cue
from device.core.app import validate_device_context_value
from device.core.models import ProcessingResponse
from device.core.settings import SettingsError


def test_main_prints_clean_configuration_errors(capsys) -> None:
  error = SettingsError(
    [
      "OREMI_DEVICE_OHUNERIN_HOST is required",
      "OREMI_DEVICE_MQTT_PORT must be at most 65535",
    ]
  )

  with patch("device.__main__.start", side_effect=error):
    result = main([])

  captured = capsys.readouterr()
  assert result == 2
  assert captured.out == ""
  assert captured.err == (
    "oremi-device: configuration error\n"
    "  - OREMI_DEVICE_OHUNERIN_HOST is required\n"
    "  - OREMI_DEVICE_MQTT_PORT must be at most 65535\n"
  )
  assert "Traceback" not in captured.err


def test_parse_device_context_command_field_without_leading_slash() -> None:
  assert (
    parse_device_context_command_field(
      "oremi/device/nodes/kitchen/context/location/set",
      "oremi/device/nodes/kitchen/context",
    )
    == "location"
  )


def test_parse_device_context_command_field_ignores_other_topics() -> None:
  assert (
    parse_device_context_command_field(
      "oremi/device/nodes/kitchen/context/location/state",
      "oremi/device/nodes/kitchen/context",
    )
    is None
  )


def test_validate_device_context_value_accepts_location() -> None:
  assert validate_device_context_value("location", "  Douala, Cameroon  ") == "Douala, Cameroon"


def test_validate_device_context_value_accepts_timezone() -> None:
  assert validate_device_context_value("timezone", "Europe/Paris") == "Europe/Paris"


def test_validate_device_context_value_rejects_invalid_timezone() -> None:
  assert validate_device_context_value("timezone", "Invalid/Timezone") is None


def test_should_continue_conversation_for_classified_follow_up() -> None:
  response = ProcessingResponse(
    message="Please share a location so I can check alerts for that area.",
    continue_conversation=True,
  )

  assert should_continue_conversation(response, enabled=True, needs_audio=True, microphone_muted=False) is True


def test_should_not_continue_conversation_from_processing_data() -> None:
  response = ProcessingResponse(
    message="Please share a location so I can check alerts for that area.",
    data={"error": {"type": "more_information_required"}},
  )

  assert should_continue_conversation(response, enabled=True, needs_audio=True, microphone_muted=False) is False


@pytest.mark.parametrize(
  ("enabled", "needs_audio", "microphone_muted"),
  [
    (False, True, False),
    (True, False, False),
    (True, True, True),
  ],
)
def test_should_not_continue_conversation_when_disabled_or_audio_unavailable(
  enabled: bool,
  needs_audio: bool,
  microphone_muted: bool,
) -> None:
  response = ProcessingResponse(message="Quel jour ?", continue_conversation=True)

  assert (
    should_continue_conversation(
      response,
      enabled=enabled,
      needs_audio=needs_audio,
      microphone_muted=microphone_muted,
    )
    is False
  )


@pytest.mark.parametrize(
  ("follow_up_active", "will_continue", "expected"),
  [
    (False, False, False),
    (False, True, False),
    (True, True, False),
    (True, False, True),
  ],
)
def test_should_play_follow_up_end_cue(follow_up_active: bool, will_continue: bool, expected: bool) -> None:
  assert should_play_follow_up_end_cue(follow_up_active=follow_up_active, will_continue=will_continue) is expected


@pytest.mark.asyncio
async def test_cancelled_listening_task_is_not_unexpected() -> None:
  task = asyncio.create_task(asyncio.sleep(60))
  task.cancel()

  try:
    await task
  except asyncio.CancelledError:
    pass

  assert listening_task_failed(task) is False


@pytest.mark.asyncio
async def test_failed_listening_task_is_unexpected() -> None:
  async def fail() -> None:
    raise RuntimeError("audio failed")

  task = asyncio.create_task(fail())

  with pytest.raises(RuntimeError):
    await task

  assert listening_task_failed(task) is True


@pytest.mark.asyncio
async def test_supervisor_continues_after_expected_listening_task_completion() -> None:
  task = asyncio.create_task(asyncio.sleep(60))
  task.cancel()

  try:
    await task
  except asyncio.CancelledError:
    pass

  assert classify_supervisor_done({task}, {task: object()}, {}) == "continue"


@pytest.mark.asyncio
async def test_supervisor_recovers_after_failed_listening_task() -> None:
  async def fail() -> None:
    raise RuntimeError("audio failed")

  task = asyncio.create_task(fail())

  with pytest.raises(RuntimeError):
    await task

  assert classify_supervisor_done({task}, {task: object()}, {}) == "recover_audio"


@pytest.mark.asyncio
async def test_supervisor_exits_after_main_component_task_finishes() -> None:
  task = asyncio.create_task(asyncio.sleep(0))
  await task

  assert classify_supervisor_done({task}, {}, {task: object()}) == "exit"
