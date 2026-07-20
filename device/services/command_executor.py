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
from datetime import datetime
from datetime import timezone

from device.core.cues import get_sound_cue_path
from device.core.models import AlarmCommand
from device.core.models import AnnounceCommand
from device.core.models import CancelScheduledCommand
from device.core.models import MuteCommand
from device.core.models import PlayCommand
from device.core.models import PlayerCommand
from device.core.models import ProcessingCommand
from device.core.models import ProcessingResponse
from device.core.models import ReminderCommand
from device.core.models import SetVolumeCommand
from device.core.models import SpeakCommand
from device.core.mqtt import HomeAssistantDevice
from device.services.audio_service import AudioService
from device.services.tts_manager import TTSManager

logger = logging.getLogger(__name__)


class CommandExecutor:
  def __init__(
    self, audio_service: AudioService, tts_manager: TTSManager, ha_device: HomeAssistantDevice, loop: asyncio.AbstractEventLoop
  ):
    self.audio = audio_service
    self.tts = tts_manager
    self.ha_device = ha_device
    self.loop = loop

    # Task references for clean cancellation
    self.playback_task: asyncio.Task | None = None
    self.speech_task: asyncio.Task | None = None
    self.scheduled_tasks: dict[str, asyncio.Task] = {}

  async def execute_response(self, response: ProcessingResponse) -> None:
    response_started_playback = False

    for command in response.resolved_commands():
      if self.speech_task is not None:
        await self.speech_task
        self.speech_task = None

      if isinstance(command, (SpeakCommand, AnnounceCommand)):
        await self._handle_speech(command)

      elif isinstance(command, PlayCommand):
        await self._handle_playback(command, response_started_playback)
        response_started_playback = True

      elif isinstance(command, PlayerCommand):
        self._handle_player_control(command)

      elif isinstance(command, (AlarmCommand, ReminderCommand)):
        self._schedule_task(command)

      elif isinstance(command, CancelScheduledCommand):
        self._cancel_task(command)

      elif isinstance(command, SetVolumeCommand):
        self._set_volume(command)

      elif isinstance(command, MuteCommand):
        self._set_mute(command)

  # ── Command Handlers ───────────────────────────────────────────────────────

  async def _handle_speech(self, command: SpeakCommand | AnnounceCommand) -> None:
    if not self.tts.client:
      logger.error("Cannot synthesize speech: no speech synthesis voice available")
      return

    speaker = self.audio.speaker

    if speaker is None:
      logger.error("Cannot play synthesized speech: no speaker available")
      return

    voice = command.voice or self.tts.current_voice
    synthesis = self.tts.client.synthesize_request(command.text, voice)

    # Note: Depending on ducking requirements, you might want to wrap this
    # in a dedicated play_speech wrapper just like in the original app.py
    self.speech_task = self.loop.create_task(
      asyncio.to_thread(
        speaker.play_url, synthesis.url, method=synthesis.method, body=synthesis.body, headers=synthesis.headers
      ),
      name="Speech Synthesis Task",
    )

  async def _handle_playback(self, command: PlayCommand, response_started_playback: bool) -> None:
    speaker = self.audio.speaker

    if speaker is None:
      logger.error("Cannot start playback: no speaker available")
      return

    if not response_started_playback:
      logger.debug("Stopping current playback before starting %s", command.url)
      speaker.stop()

    if self.playback_task is not None:
      logger.debug("Waiting for previous playback task to complete")
      await self.playback_task

    logger.info("Starting playback: %s", command.url)
    self.ha_device.set_player_state("playing")

    async def play_and_reset() -> None:
      try:
        await asyncio.to_thread(speaker.play_url, command.url)
        logger.info("Playback completed: %s", command.url)
      except Exception:
        logger.exception("Playback failed: %s", command.url)
      finally:
        self.ha_device.set_player_state("idle")
        logger.debug("Player state set to idle")

    self.playback_task = self.loop.create_task(
      play_and_reset(),
      name="Speaker Playback Task",
    )

    logger.debug("Playback task created: %s", self.playback_task.get_name())

  def _handle_player_control(self, command: PlayerCommand) -> None:
    if self.audio.speaker is None:
      return

    if command.type == "stop":
      self.audio.speaker.stop()
      self.ha_device.set_player_state("idle")
    elif command.type == "pause":
      self.audio.speaker.pause()
      self.ha_device.set_player_state("paused")
    elif command.type == "resume":
      self.audio.speaker.resume()
      self.ha_device.set_player_state("playing")

  def _set_volume(self, command: SetVolumeCommand) -> None:
    volume = command.volume / 100
    self.audio.speaker_state["volume"] = volume

    if self.audio.speaker is not None:
      self.audio.speaker.set_volume(volume)
      self.loop.create_task(
        asyncio.to_thread(self.audio.speaker.play_file, get_sound_cue_path("volume")),
        name="Volume Sound Task",
      )

    self.ha_device.set_speaker_volume_state(volume)

  def _set_mute(self, command: MuteCommand) -> None:
    self.audio.speaker_state["muted"] = command.muted

    if self.audio.speaker is not None:
      self.audio.speaker.set_muted(command.muted)

      cue = "mute_on" if command.muted else "mute_off"

      self.loop.create_task(
        asyncio.to_thread(self.audio.speaker.play_file, get_sound_cue_path(cue)),
        name="Mute Sound Task",
      )

    self.ha_device.set_speaker_mute_state(command.muted)

  # ── Scheduling ─────────────────────────────────────────────────────────────

  def _schedule_task(self, command: AlarmCommand | ReminderCommand) -> None:
    self._cancel_task(CancelScheduledCommand(id=command.id, type="cancel_scheduled"))
    task = self.loop.create_task(self._run_scheduled(command), name=f"Scheduled {command.type}: {command.id}")
    self.scheduled_tasks[command.id] = task
    logger.info(f"Scheduled {command.type} '{command.id}' for {command.at.isoformat()}")

  async def _run_scheduled(self, command: AlarmCommand | ReminderCommand) -> None:
    try:
      delay = max((command.at - datetime.now(timezone.utc)).total_seconds(), 0.0)
      await asyncio.sleep(delay)

      # Re-inject as an AnnounceCommand
      commands: list[ProcessingCommand] = [AnnounceCommand(type="announce", text=command.message, voice=command.voice)]

      if isinstance(command, AlarmCommand) and command.url:
        commands.append(PlayCommand(type="play", url=command.url))

      await self.execute_response(ProcessingResponse(commands=commands))
    finally:
      if self.scheduled_tasks.get(command.id) is asyncio.current_task():
        self.scheduled_tasks.pop(command.id, None)

  def _cancel_task(self, command: CancelScheduledCommand) -> None:
    existing = self.scheduled_tasks.pop(command.id, None)
    if existing is not None:
      existing.cancel()
      logger.info(f"Cancelled scheduled command: {command.id}")

  # ── Lifecycle ──────────────────────────────────────────────────────────────

  async def cancel_active(self) -> None:
    """Stops all active execution tasks safely."""
    if self.audio.speaker is not None:
      self.audio.speaker.stop()

    if self.playback_task is not None:
      await self.playback_task
      self.playback_task = None

    if self.speech_task is not None:
      await asyncio.gather(self.speech_task, return_exceptions=True)
      self.speech_task = None
