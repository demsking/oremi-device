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
import signal
import sys
from datetime import datetime
from datetime import timezone
from typing import Literal

import sounddevice as sd
from pydantic import BaseModel
from pydantic import ValidationError

from ..components import COMPONENTS
from ..components.base import AudioStreamComponent
from ..components.base import Component
from ..components.edge_tts import OpenAIEdgeTTSClient
from ..components.izwi import IzwiClient
from ..utils.logger import logger
from .audio import Audio
from .audio import AudioDeviceError
from .cues import ConversationEvent
from .cues import ConversationState
from .cues import get_sound_cue_path
from .cues import SoundCue
from .models import AlarmCommand
from .models import AnnounceCommand
from .models import CancelScheduledCommand
from .models import MuteCommand
from .models import PlayCommand
from .models import PlayerCommand
from .models import ProcessingCommand
from .models import ProcessingResponse
from .models import ReminderCommand
from .models import SetVoiceCommand
from .models import SetVolumeCommand
from .models import SpeakCommand
from .mqtt import MQTTClient
from .package import APP_NAME
from .package import APP_VERSION
from .settings import load_settings
from .settings import update_runtime_settings_cache
from .speaker import Speaker
from .speaker import SpeakerDeviceError
from .speaker import SpeakerPlaybackError
from .tts import TTSVoice
from .tts import voices_for_language


def listening_task_failed(task: asyncio.Task) -> bool:
  """Return true only when an audio listener failed with an exception."""
  if task.cancelled():
    return False

  try:
    return task.exception() is not None
  except asyncio.InvalidStateError:
    return False


def classify_supervisor_done(
  done: set[asyncio.Task],
  listening_tasks: dict[asyncio.Task, object],
  component_tasks: dict[asyncio.Task, object],
) -> Literal["recover_audio", "exit", "continue"]:
  unexpected_listening_tasks = [task for task in done if task in listening_tasks and listening_task_failed(task)]

  if unexpected_listening_tasks and not any(task in component_tasks for task in done):
    return "recover_audio"

  if any(task in component_tasks for task in done):
    return "exit"

  return "continue"


async def start() -> None:
  settings = load_settings()

  loop = asyncio.get_running_loop()

  # Log initial configuration
  logger.info(f"Starting {APP_NAME}/{APP_VERSION}")
  logger.info(f"Log level: {logging.getLevelName(logger.getEffectiveLevel())}")
  logger.info(f"Configuration Node ID: {settings.node_id}")
  logger.info(f"Configuration Ohunerin Host: {settings.ohunerin_host}")
  logger.info(f"Configuration Ohunerin Port: {settings.ohunerin_port}")
  logger.info(f"Configuration Transcription Backend: {settings.transcription_backend}")

  if settings.transcription_backend == "andika":
    logger.info(f"Configuration Andika Host: {settings.andika_host}")
    logger.info(f"Configuration Andika Port: {settings.andika_port}")
  else:
    logger.info(f"Configuration whisper.cpp URL: {settings.whisper_url}")

  if settings.tts_backend == "edge-tts" and settings.edge_tts_url:
    logger.info(f"Configuration Edge-TTS URL: {settings.edge_tts_url}")
  elif settings.izwi_url:
    logger.info(f"Configuration Izwi URL: {settings.izwi_url}")

  logger.info(f"Configuration Secure Connection: {'Enabled' if settings.cert_file else 'Disabled'}")
  microphone_enabled = settings.microphone_enabled
  speaker_enabled = settings.speaker_enabled
  logger.info(f"Configuration Microphone: {'Enabled' if microphone_enabled else 'Disabled'}")
  logger.info(f"Configuration Speaker: {'Enabled' if speaker_enabled else 'Disabled'}")

  if settings.cert_file:
    logger.info(f"Configuration Certificate File: {settings.cert_file}")

  logger.info(f"Configuration Language: {settings.language}")

  # ── Resolve active components ────────────────────────────────────────────────
  active_components: list[tuple[Component, BaseModel]] = []
  component_config = {
    "ohunerin": {"threshold": settings.ohunerin_threshold},
    "andika": {"model": settings.andika_model, "samplerate": settings.andika_samplerate},
  }

  for comp_name, (load_config, create_component) in COMPONENTS.items():
    comp_config = (
      load_config.model_validate(component_config.get(comp_name)) if comp_name in component_config else load_config()
    )
    component = create_component(settings)  # pylint: disable=abstract-class-instantiated

    active_components.append((component, comp_config))

  # ── Audio stream (only for AudioStreamComponents) ────────────────────────────
  # Check whether any active component actually needs the microphone so that
  # HTTP-only components (e.g. Injini) can run without any audio hardware.
  needs_audio = microphone_enabled and any(isinstance(c, AudioStreamComponent) for c, _ in active_components)

  audio_stream: Audio | None = None

  if needs_audio:
    try:
      audio_stream = Audio(
        device_index=settings.microphone_device_index,
        device_name=settings.microphone_device,
      )
    except AudioDeviceError as error:
      logger.error(str(error))
      sys.exit(1)

    logger.info(f"Active Microphone Device: {audio_stream.device_name}")
    compatible_devices = Audio.get_compatible_input_devices(current_device=audio_stream.device_name)
    logger.info(f"Compatible Input Devices: {', '.join(compatible_devices) if compatible_devices else 'None'}")
  elif microphone_enabled:
    logger.info("No AudioStreamComponent active — skipping audio initialisation.")
  else:
    logger.info("Microphone disabled — skipping audio initialisation.")

  active_stream_container: dict = {"stream": audio_stream}

  speaker: Speaker | None = None

  if speaker_enabled:
    try:
      speaker = Speaker(settings.speaker_device, volume=settings.speaker_volume, muted=settings.speaker_muted)
      logger.info(f"Active Speaker Device: {speaker.device_name}")
    except SpeakerDeviceError as error:
      logger.warning(str(error))

      if settings.speaker_device:
        try:
          speaker = Speaker(volume=settings.speaker_volume, muted=settings.speaker_muted)
          logger.info(f"Active Speaker Device: {speaker.device_name}")
        except SpeakerDeviceError as fallback_error:
          logger.warning(str(fallback_error))
  else:
    logger.info("Speaker disabled — skipping speaker initialisation.")

  edge_tts_locale = settings.edge_tts_locale or {"fr": "fr-FR", "en": "en-US"}.get(settings.language)
  tts_client: IzwiClient | OpenAIEdgeTTSClient | None

  if settings.tts_backend == "edge-tts" and settings.edge_tts_url:
    tts_client = OpenAIEdgeTTSClient(
      str(settings.edge_tts_url),
      api_key=settings.edge_tts_api_key,
      ca_file=settings.cert_file,
      locale=edge_tts_locale,
      model=settings.edge_tts_model,
      response_format=settings.edge_tts_response_format,
      speed=settings.edge_tts_speed,
    )
  elif settings.izwi_url:
    tts_client = IzwiClient(str(settings.izwi_url), ca_file=settings.cert_file)
  else:
    tts_client = None

  tts_voices: list[TTSVoice] = []

  if tts_client and speaker_enabled:
    try:
      tts_voices = await tts_client.get_voices()
      logger.info(f"Speech synthesis voices: {', '.join(voice.name for voice in tts_voices) or 'None'}")
    except (ValidationError, OSError, ValueError) as error:
      logger.warning(f"Failed to fetch speech synthesis voices: {error}")
    except Exception as error:
      logger.warning(f"Failed to connect to speech synthesis backend: {error}")

  # ── MQTT client ──────────────────────────────────────────────────────────────
  mqtt_client = MQTTClient(
    broker=settings.mqtt_broker,
    port=settings.mqtt_port,
    node_id=settings.node_id,
    topic=settings.mqtt_topic,
    username=settings.mqtt_username,
    password=settings.mqtt_password,
    discovery_prefix=settings.mqtt_discovery_prefix if settings.mqtt_discovery else None,
  )

  # MQTT callbacks run on the client thread, so command state must exist
  # before connecting and subscribing to retained command topics.
  device_change_queue: asyncio.Queue = asyncio.Queue()
  microphone_mute_queue: asyncio.Queue = asyncio.Queue()
  speaker_change_queue: asyncio.Queue = asyncio.Queue()
  speaker_mute_queue: asyncio.Queue = asyncio.Queue()
  speaker_volume_queue: asyncio.Queue = asyncio.Queue()
  player_play_queue: asyncio.Queue = asyncio.Queue()
  player_stop_queue: asyncio.Queue = asyncio.Queue()
  language_change_queue: asyncio.Queue = asyncio.Queue()
  processing_queue: asyncio.Queue[ProcessingResponse] = asyncio.Queue()
  voice_change_queue: asyncio.Queue[str] = asyncio.Queue()
  wakeword_event = asyncio.Event()
  device_state: dict = {"microphone_muted": settings.microphone_muted}

  speaker_state: dict = {
    "device": speaker.device_name if speaker else "",
    "muted": speaker.muted if speaker else settings.speaker_muted,
    "volume": speaker.volume if speaker else settings.speaker_volume,
  }

  language_state: dict = {"language": settings.language}
  initial_voices = voices_for_language(tts_voices, settings.language)
  initial_voice_names = [voice.name for voice in initial_voices]

  voice_state: dict = {
    "voice": (
      settings.tts_voice if settings.tts_voice in initial_voice_names else initial_voices[0].name if initial_voices else ""
    )
  }

  conversation_state: dict[str, ConversationState] = {"state": "idle"}
  playback_task: asyncio.Task | None = None
  speech_task: asyncio.Task | None = None
  scheduled_tasks: dict[str, asyncio.Task] = {}

  def active_voice_names() -> list[str]:
    return [voice.name for voice in voices_for_language(tts_voices, language_state["language"])]

  async def play_media(
    media_url: str,
    *,
    method: str = "GET",
    body: str | None = None,
    headers: dict[str, str] | None = None,
  ) -> None:
    if speaker is None:
      logger.error("Cannot play media because no compatible speaker is available")
      return

    mqtt_client.set_player_state("playing")

    try:
      await asyncio.to_thread(speaker.play_url, media_url, method=method, body=body, headers=headers)
    except SpeakerPlaybackError as error:
      logger.error(f"Media playback failed: {error}")
    finally:
      mqtt_client.set_player_state("idle")

  async def play_speech(media_url: str, *, method: str, body: str | None, headers: dict[str, str] | None) -> None:
    if speaker is None:
      logger.error("Cannot play speech because no compatible speaker is available")
      conversation_state["state"] = "idle"
      mqtt_client.set_conversation_state("idle")
      return

    speaker.begin_ducking()
    conversation_state["state"] = "speaking"
    mqtt_client.set_conversation_state("speaking")
    playback = loop.create_task(
      asyncio.to_thread(
        speaker.play_url,
        media_url,
        method=method,
        body=body,
        headers=headers,
        interrupt=False,
        duckable=False,
      ),
      name="Speech Decoder Task",
    )

    try:
      await asyncio.shield(playback)
    except asyncio.CancelledError:
      speaker.stop()
      await asyncio.gather(playback, return_exceptions=True)
      raise
    except SpeakerPlaybackError as error:
      logger.error(f"Speech playback failed: {error}")
    finally:
      speaker.end_ducking()
      conversation_state["state"] = "idle"
      mqtt_client.set_conversation_state("idle")

  async def play_sound_cue(cue: SoundCue) -> None:
    if speaker is None:
      return

    speaker.begin_ducking()

    try:
      await asyncio.to_thread(
        speaker.play_file,
        get_sound_cue_path(cue),
        interrupt=False,
        duckable=False,
      )
    except SpeakerPlaybackError as error:
      logger.warning(f"Failed to play '{cue}' sound cue: {error}")
    finally:
      speaker.end_ducking()

  async def handle_conversation_event(event: ConversationEvent) -> None:
    if event == "listening":
      conversation_state["state"] = "listening"
      mqtt_client.set_conversation_state("listening")
      await play_sound_cue("listening")
    elif event == "processing":
      conversation_state["state"] = "processing"
      mqtt_client.set_conversation_state("processing")
      await play_sound_cue("thinking")
    else:
      conversation_state["state"] = "idle"
      mqtt_client.set_conversation_state("idle")
      await play_sound_cue("cancel")

  async def run_scheduled(command: AlarmCommand | ReminderCommand) -> None:
    commands: list[ProcessingCommand] = []

    try:
      delay = max((command.at - datetime.now(timezone.utc)).total_seconds(), 0.0)
      await asyncio.sleep(delay)

      if isinstance(command, ReminderCommand):
        commands = [AnnounceCommand(type="announce", text=command.message, voice=command.voice)]
      else:
        commands = [AnnounceCommand(type="announce", text=command.message, voice=command.voice)]

        if command.url:
          commands.append(PlayCommand(type="play", url=command.url))

      await processing_queue.put(ProcessingResponse(commands=commands))
    finally:
      if scheduled_tasks.get(command.id) is asyncio.current_task():
        scheduled_tasks.pop(command.id, None)

  def schedule(command: AlarmCommand | ReminderCommand) -> None:
    existing = scheduled_tasks.pop(command.id, None)

    if existing is not None:
      existing.cancel()

    task = loop.create_task(run_scheduled(command), name=f"Scheduled {command.type}: {command.id}")
    task.add_done_callback(handle_task_done)
    scheduled_tasks[command.id] = task
    logger.info(f"Scheduled {command.type} '{command.id}' for {command.at.isoformat()}")

  @mqtt_client.client.connect_callback()
  def mqtt_on_connect(client, userdata, flags, reason_code, properties) -> None:
    logger.info(f"Connected to MQTT broker with result code {reason_code}")

    if needs_audio:
      # Subscribe to the instance-scoped microphone-select command topic.
      # Using node_id in the topic prevents cross-instance interference when
      # multiple oremi-device instances share the same base MQTT topic.
      client.subscribe(mqtt_client.get_microphone_command_topic())
      client.subscribe(mqtt_client.get_mute_command_topic())

    if speaker_enabled:
      client.subscribe(mqtt_client.get_speaker_command_topic())
      client.subscribe(mqtt_client.get_speaker_mute_cmd_topic())
      client.subscribe(mqtt_client.get_speaker_volume_cmd_topic())
      client.subscribe(mqtt_client.get_player_play_command_topic())
      client.subscribe(mqtt_client.get_player_stop_command_topic())
      client.subscribe(mqtt_client.get_processing_result_topic())

      if tts_voices:
        client.subscribe(mqtt_client.get_voice_command_topic())

    mqtt_client.set_conversation_state(conversation_state["state"])

    # Subscribe to the language-select command topic.
    client.subscribe(mqtt_client.get_language_command_topic())

    if mqtt_client.discovery_prefix:
      try:
        curr_stream = active_stream_container["stream"]
        curr_name = curr_stream.device_name if curr_stream else ""
        node_id = mqtt_client.get_node_id()
        device = mqtt_client.get_device_descriptor()

        ha_entities = [
          entity
          for component, _ in active_components
          for entity in component.ha_entities(
            node_id,
            mqtt_client.parse_event_topic(""),
            mqtt_client.parse_node_topic("available"),
            device,
          )
        ]

        mqtt_client.publish_discovery_configs(
          input_devices=Audio.get_compatible_input_devices(current_device=curr_name) if needs_audio else [],
          current_device=curr_name,
          entities=ha_entities,
          microphone_muted=device_state["microphone_muted"],
          output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
          current_output=speaker_state["device"],
          speaker_muted=speaker_state["muted"],
          speaker_volume=speaker_state["volume"],
          current_language=language_state["language"],
          microphone_enabled=microphone_enabled,
          speaker_enabled=speaker_enabled,
          voices=active_voice_names() if tts_client else None,
          current_voice=voice_state["voice"],
        )
      except Exception as error:
        logger.error(f"Failed to publish MQTT discovery configs: {error}")

  @mqtt_client.client.disconnect_callback()
  def mqtt_on_disconnect(client, userdata, flags, reason_code, properties) -> None:
    curr_stream = active_stream_container["stream"]

    if curr_stream and curr_stream.is_active():
      logger.warning(f"Unexpected disconnection from MQTT broker with result code {reason_code}. Reconnecting...")
      mqtt_client.connect()
    else:
      logger.info(f"Disconnected from MQTT broker with result code {reason_code}")

  mqtt_client.connect()
  mqtt_client.set_availability(False)

  @mqtt_client.client.message_callback()
  def mqtt_on_message(client, userdata, message) -> None:
    topic = message.topic

    if needs_audio and topic == mqtt_client.get_microphone_command_topic():
      try:
        new_device = message.payload.decode("utf-8")
        logger.info(f"Received microphone set command: {new_device}")
        loop.call_soon_threadsafe(device_change_queue.put_nowait, new_device)
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT microphone command: {error}")

    elif needs_audio and topic == mqtt_client.get_mute_command_topic():
      try:
        payload = message.payload.decode("utf-8").strip().upper()
        logger.info(f"Received microphone mute command: {payload}")

        if payload in ("ON", "OFF"):
          muted = payload == "ON"
          device_state["microphone_muted"] = muted
          loop.call_soon_threadsafe(microphone_mute_queue.put_nowait, muted)
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT microphone mute command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_speaker_command_topic():
      try:
        new_speaker = message.payload.decode("utf-8").strip()
        logger.info(f"Received speaker set command: {new_speaker}")
        loop.call_soon_threadsafe(speaker_change_queue.put_nowait, new_speaker)
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT speaker command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_speaker_mute_cmd_topic():
      try:
        payload = message.payload.decode("utf-8").strip().upper()
        logger.info(f"Received speaker mute command: {payload}")

        if payload in ("ON", "OFF"):
          loop.call_soon_threadsafe(speaker_mute_queue.put_nowait, payload == "ON")
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT speaker mute command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_speaker_volume_cmd_topic():
      try:
        volume = float(message.payload.decode("utf-8").strip()) / 100
        logger.info(f"Received speaker volume command: {volume:.0%}")

        if 0.0 <= volume <= 1.0:
          loop.call_soon_threadsafe(speaker_volume_queue.put_nowait, volume)
      except (UnicodeDecodeError, ValueError) as error:
        logger.error(f"Error decoding or handling MQTT speaker volume command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_player_play_command_topic():
      try:
        media_url = message.payload.decode("utf-8").strip()

        if media_url:
          loop.call_soon_threadsafe(player_play_queue.put_nowait, media_url)
      except UnicodeDecodeError as error:
        logger.error(f"Error decoding media playback command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_player_stop_command_topic():
      loop.call_soon_threadsafe(player_stop_queue.put_nowait, True)

    elif topic == mqtt_client.get_language_command_topic():
      try:
        new_language = message.payload.decode("utf-8").strip().lower()
        logger.info(f"Received language set command: {new_language}")

        if new_language in ("fr", "en"):
          loop.call_soon_threadsafe(language_change_queue.put_nowait, new_language)
        else:
          logger.warning(f"Ignoring unsupported language command: {new_language}")
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT language command: {error}")

    elif speaker_enabled and topic == mqtt_client.get_processing_result_topic():
      try:
        response = ProcessingResponse.model_validate_json(message.payload)
        loop.call_soon_threadsafe(processing_queue.put_nowait, response)
      except ValidationError:
        logger.warning("Ignoring invalid NLP processing response")
        loop.call_soon_threadsafe(lambda: loop.create_task(handle_conversation_event("cancelled")))

    elif tts_voices and topic == mqtt_client.get_voice_command_topic():
      try:
        voice = message.payload.decode("utf-8").strip()

        if voice in active_voice_names():
          loop.call_soon_threadsafe(voice_change_queue.put_nowait, voice)
        else:
          logger.warning(f"Ignoring unavailable speech synthesis voice: {voice}")
      except UnicodeDecodeError as error:
        logger.warning(f"Ignoring invalid speech synthesis voice command: {error}")

  def handle_task_done(task: asyncio.Task) -> None:
    try:
      if task.cancelled():
        logger.info(f"{task.get_name()} cancelled")
      elif task.exception() is not None:
        logger.error(task)
      else:
        logger.info(f"{task.get_name()} done")
    except (asyncio.CancelledError, asyncio.InvalidStateError) as error:
      logger.error(error)

  # ── Audio device switching (only when needs_audio) ───────────────────────────
  started_components: list[tuple] = []

  async def change_audio_device(target_device, fallback_to_previous=True) -> bool:
    """Open a new audio stream and notify all AudioStreamComponents."""
    prev_stream = active_stream_container["stream"]
    prev_device = prev_stream.device_name if prev_stream else None

    # Tear down the current stream
    if prev_stream is not None:
      try:
        prev_stream.stop()
      except Exception:
        pass

    # Signal components that the stream is gone
    for component, _ in started_components:
      if isinstance(component, AudioStreamComponent):
        await component.on_device_changed(None)

    try:
      if target_device is not None:
        if isinstance(target_device, int):
          new_stream = Audio(device_index=target_device)
        else:
          new_stream = Audio(device_name=str(target_device))
      else:
        # Auto-select: find any compatible device
        compatible = Audio.find_compatible_device()
        if compatible:
          new_stream = Audio(device_index=compatible["index"])
        else:
          raise AudioDeviceError("No compatible device found")

      active_stream_container["stream"] = new_stream

      # Signal components only when microphone capture should be active.
      if not device_state["microphone_muted"]:
        for component, _ in started_components:
          if isinstance(component, AudioStreamComponent):
            await component.on_device_changed(new_stream)

      # Publish microphone state
      mqtt_client.publish_node("microphone/state", new_stream.device_name, retain=True)
      mqtt_client.set_availability(True)

      # Republish HA discovery options with updated device list
      if mqtt_client.discovery_prefix:
        node_id = mqtt_client.get_node_id()
        device = mqtt_client.get_device_descriptor()
        ha_entities = [
          entity
          for component, _ in started_components
          for entity in component.ha_entities(
            node_id,
            mqtt_client.parse_event_topic(""),
            mqtt_client.parse_node_topic("available"),
            device,
          )
        ]
        comp_devices = Audio.get_compatible_input_devices(current_device=new_stream.device_name)
        mqtt_client.publish_discovery_configs(
          input_devices=comp_devices,
          current_device=new_stream.device_name,
          entities=ha_entities,
          microphone_muted=device_state["microphone_muted"],
          output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
          current_output=speaker_state["device"],
          speaker_muted=speaker_state["muted"],
          speaker_volume=speaker_state["volume"],
          current_language=language_state["language"],
          microphone_enabled=microphone_enabled,
          speaker_enabled=speaker_enabled,
          voices=active_voice_names() if tts_client else None,
          current_voice=voice_state["voice"],
        )

      logger.info(f"Successfully switched to microphone: {new_stream.device_name}")

      return True
    except Exception as err:
      logger.error(f"Failed to switch to device {target_device}: {err}")

      if fallback_to_previous and prev_device is not None:
        logger.info(f"Attempting to revert to previous microphone: {prev_device}")
        success = await change_audio_device(prev_device, fallback_to_previous=False)

        if success:
          return True

      # No fallback available — mark stream as unavailable
      active_stream_container["stream"] = None

      for component, _ in started_components:
        if isinstance(component, AudioStreamComponent):
          await component.on_device_changed(None)

      mqtt_client.publish_node("microphone/state", "None", retain=True)
      mqtt_client.set_availability(False)

      return False

  shared_resources = {
    "active_stream_container": active_stream_container,
    "device_change_queue": device_change_queue,
    "microphone_mute_queue": microphone_mute_queue,
    "speaker": speaker,
    "speaker_state": speaker_state,
    "language_change_queue": language_change_queue,
    "wakeword_event": wakeword_event,
    "device_state": device_state,
    "language_state": language_state,
    "conversation_event_handler": handle_conversation_event,
    "change_audio_device": change_audio_device,
    "handle_task_done": handle_task_done,
  }

  # ── Start all active components ──────────────────────────────────────────────
  for component, comp_config in active_components:
    logger.info(f"Starting component: {component.name}")
    await component.start(comp_config, mqtt_client, shared_resources)
    started_components.append((component, comp_config))

  shutdown_event = asyncio.Event()

  def request_shutdown() -> None:
    if not shutdown_event.is_set():
      logger.info("Shutdown signal received. Stopping application...")
      shutdown_event.set()

  loop.add_signal_handler(signal.SIGINT, request_shutdown)
  loop.add_signal_handler(signal.SIGTERM, request_shutdown)

  # ── Main event loop ──────────────────────────────────────────────────────────
  preferred_device = settings.microphone_device if settings.microphone_device is not None else settings.microphone_device_index

  def is_device_available(device, current_devs, compatible_devs) -> bool:
    if isinstance(device, int):
      return device < len(current_devs) and current_devs[device]["max_input_channels"] > 0

    for name in compatible_devs:
      if device.lower() in name.lower():
        return True

    return False

  async def monitor_devices() -> None:
    """Poll the OS device list and enqueue auto-select events on changes."""
    nonlocal preferred_device
    last_signatures: set = set()

    try:
      last_signatures = {(d["name"], d.get("hostapi"), d.get("max_input_channels")) for d in sd.query_devices()}
    except Exception as error:
      logger.warning(f"Failed to initialize device monitoring signatures: {error}")

    while True:
      try:
        await asyncio.sleep(3.0)
      except asyncio.CancelledError:
        break

      try:
        current_devs = sd.query_devices()
        current_signatures = {(d["name"], d.get("hostapi"), d.get("max_input_channels")) for d in current_devs}
      except Exception as error:
        logger.warning(f"Failed to query audio devices: {error}")
        continue

      if current_signatures == last_signatures:
        continue

      logger.info("Audio device change detected (added or removed).")
      last_signatures = current_signatures

      curr_stream = active_stream_container["stream"]
      curr_name = curr_stream.device_name if curr_stream else None
      compatible_devs = Audio.get_compatible_input_devices(current_device=curr_name)

      if mqtt_client.discovery_prefix:
        try:
          node_id = mqtt_client.get_node_id()
          device = mqtt_client.get_device_descriptor()
          ha_entities = [
            entity
            for component, _ in started_components
            for entity in component.ha_entities(
              node_id,
              mqtt_client.parse_event_topic(""),
              mqtt_client.parse_node_topic("available"),
              device,
            )
          ]
          mqtt_client.publish_discovery_configs(
            input_devices=compatible_devs,
            current_device=curr_name or "",
            entities=ha_entities,
            microphone_muted=device_state["microphone_muted"],
            output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
            current_output=speaker_state["device"],
            speaker_muted=speaker_state["muted"],
            speaker_volume=speaker_state["volume"],
            current_language=language_state["language"],
            microphone_enabled=microphone_enabled,
            speaker_enabled=speaker_enabled,
            voices=active_voice_names() if tts_client else None,
            current_voice=voice_state["voice"],
          )
        except Exception as error:
          logger.error(f"Failed to publish MQTT discovery configs on device change: {error}")

      # Current stream disappeared
      if curr_stream is not None:
        if curr_name not in compatible_devs:
          logger.warning(f"Active microphone '{curr_name}' was disconnected (removed).")
          loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")
      else:
        if compatible_devs:
          logger.info("A compatible microphone is now available. Starting audio stream...")
          loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")

      # Preferred device reconnected while a different device is active
      if preferred_device is not None and curr_stream is not None:
        is_preferred_active = False

        if isinstance(preferred_device, int):
          if curr_stream.stream.device == preferred_device:
            is_preferred_active = True
        else:
          if curr_name and preferred_device.lower() in curr_name.lower():
            is_preferred_active = True

        if not is_preferred_active and is_device_available(preferred_device, current_devs, compatible_devs):
          logger.info(f"Preferred microphone '{preferred_device}' is now available. Switching back...")
          loop.call_soon_threadsafe(device_change_queue.put_nowait, preferred_device)

  # Start the background device monitor only when audio is needed
  monitor_task: asyncio.Task | None = None

  if needs_audio:
    monitor_task = loop.create_task(monitor_devices(), name="Monitor Devices Task")
    monitor_task.add_done_callback(handle_task_done)

  shutdown_task = loop.create_task(shutdown_event.wait(), name="Shutdown Task")

  mqtt_client.set_availability(True)
  await play_sound_cue("ready")

  try:
    while True:
      tasks = []
      component_tasks: dict = {}
      listening_tasks: dict = {}

      for component, _ in started_components:
        if component.task and not component.task.done():
          tasks.append(component.task)
          component_tasks[component.task] = component

        if isinstance(component, AudioStreamComponent):
          if component.listening_task and not component.listening_task.done():
            tasks.append(component.listening_task)
            listening_tasks[component.listening_task] = component

      # No component tasks are running — clean exit
      if not tasks:
        break

      if needs_audio:
        device_change_task = loop.create_task(device_change_queue.get())
        tasks.append(device_change_task)
      else:
        device_change_task = None

      microphone_mute_task = loop.create_task(microphone_mute_queue.get()) if needs_audio else None

      if microphone_mute_task is not None:
        tasks.append(microphone_mute_task)

      speaker_change_task = loop.create_task(speaker_change_queue.get()) if speaker_enabled else None
      speaker_mute_task = loop.create_task(speaker_mute_queue.get()) if speaker_enabled else None
      speaker_volume_task = loop.create_task(speaker_volume_queue.get()) if speaker_enabled else None
      player_play_task = loop.create_task(player_play_queue.get()) if speaker_enabled else None
      player_stop_task = loop.create_task(player_stop_queue.get()) if speaker_enabled else None

      if speaker_enabled:
        tasks.extend((speaker_change_task, speaker_mute_task, speaker_volume_task, player_play_task, player_stop_task))

      language_change_task = loop.create_task(language_change_queue.get())
      processing_task = loop.create_task(processing_queue.get()) if speaker_enabled else None
      voice_change_task = loop.create_task(voice_change_queue.get()) if tts_voices else None
      tasks.append(language_change_task)

      if processing_task is not None:
        tasks.append(processing_task)

      if voice_change_task is not None:
        tasks.append(voice_change_task)
      tasks.append(shutdown_task)

      done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

      # Queue reads are recreated on each iteration. Cancel the pending ones so
      # they cannot consume a later command behind the active iteration's task.
      command_tasks = [
        device_change_task,
        microphone_mute_task,
        speaker_change_task,
        speaker_mute_task,
        speaker_volume_task,
        player_play_task,
        player_stop_task,
        language_change_task,
        processing_task,
        voice_change_task,
      ]

      cancelled_command_tasks = []

      for command_task in command_tasks:
        if command_task is not None and command_task not in done:
          command_task.cancel()
          cancelled_command_tasks.append(command_task)

      if cancelled_command_tasks:
        await asyncio.gather(*cancelled_command_tasks, return_exceptions=True)

      if shutdown_task in done:
        break

      if device_change_task is not None and device_change_task in done:
        new_device = device_change_task.result()

        if new_device == "__auto_select__":
          success = False

          if preferred_device is not None:
            logger.info(f"Attempting to switch to preferred microphone: {preferred_device}")
            success = await change_audio_device(preferred_device)

          if not success:
            logger.info("Attempting to auto-select any compatible microphone...")
            success = await change_audio_device(None)

          if not success:
            logger.error("No compatible microphone could be started. Waiting for a device to be connected...")
        else:
          # Explicit switch requested (from MQTT or reconnection logic)
          preferred_device = new_device
          logger.info(f"Switching microphone to: {preferred_device}")
          success = await change_audio_device(preferred_device)

          if not success:
            logger.info("Explicit switch failed. Attempting to auto-select any compatible microphone...")
            await change_audio_device(None)
          else:
            curr_stream = active_stream_container["stream"]

            if curr_stream is not None:
              settings.microphone_device = curr_stream.device_name
              settings.microphone_device_index = None

              await asyncio.to_thread(
                update_runtime_settings_cache,
                settings,
                microphone_device=curr_stream.device_name,
              )
      elif microphone_mute_task is not None and microphone_mute_task in done:
        muted = microphone_mute_task.result()
        device_state["microphone_muted"] = muted
        settings.microphone_muted = muted

        await asyncio.to_thread(update_runtime_settings_cache, settings, microphone_muted=muted)
        mqtt_client.set_mute_state(muted)

        if muted:
          logger.info("Microphone muted. Stopping audio capture...")

          for component, _ in started_components:
            if isinstance(component, AudioStreamComponent):
              await component.on_device_changed(None)
        else:
          logger.info("Microphone unmuted. Resuming audio capture...")
          curr_stream = active_stream_container["stream"]

          if curr_stream is not None:
            for component, _ in started_components:
              if isinstance(component, AudioStreamComponent):
                await component.on_device_changed(curr_stream)
          else:
            loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")
      elif speaker_change_task is not None and speaker_change_task in done:
        requested_speaker = speaker_change_task.result()

        try:
          if speaker is None:
            speaker = Speaker(
              requested_speaker,
              volume=speaker_state["volume"],
              muted=speaker_state["muted"],
            )
            shared_resources["speaker"] = speaker
          else:
            speaker.select_device(requested_speaker)

          speaker_state["device"] = speaker.device_name
          settings.speaker_device = speaker.device_name
          await asyncio.to_thread(
            update_runtime_settings_cache,
            settings,
            speaker_device=speaker.device_name,
          )
          mqtt_client.set_speaker_state(speaker.device_name)
          logger.info(f"Speaker switched to: {speaker.device_name}")
        except SpeakerDeviceError as error:
          logger.error(error)
          mqtt_client.set_speaker_state(speaker_state["device"])
      elif speaker_mute_task is not None and speaker_mute_task in done:
        muted = speaker_mute_task.result()
        speaker_state["muted"] = muted
        settings.speaker_muted = muted
        await asyncio.to_thread(update_runtime_settings_cache, settings, speaker_muted=muted)

        if speaker:
          speaker.set_muted(muted)

        mqtt_client.set_speaker_mute_state(muted)
        logger.info(f"Speaker {'muted' if muted else 'unmuted'}")
      elif speaker_volume_task is not None and speaker_volume_task in done:
        volume = speaker_volume_task.result()
        speaker_state["volume"] = volume
        settings.speaker_volume = volume
        await asyncio.to_thread(update_runtime_settings_cache, settings, speaker_volume=volume)

        if speaker:
          speaker.set_volume(volume)

        mqtt_client.set_speaker_volume_state(volume)
        logger.info(f"Speaker volume set to {volume:.0%}")
        await play_sound_cue("volume")
      elif player_play_task is not None and player_play_task in done:
        media_url = player_play_task.result()

        if speaker is not None:
          speaker.stop()

        if playback_task is not None:
          await playback_task

        if speech_task is not None:
          await speech_task
          speech_task = None

        playback_task = loop.create_task(play_media(media_url), name="Speaker Playback Task")
      elif player_stop_task is not None and player_stop_task in done:
        if speaker is not None:
          speaker.stop()

        if playback_task is not None:
          await playback_task
          playback_task = None

        if speech_task is not None:
          await speech_task
          speech_task = None
      elif processing_task is not None and processing_task in done:
        response = processing_task.result()
        response_started_playback = False

        for command in response.resolved_commands():
          if speech_task is not None:
            await speech_task
            speech_task = None

          if isinstance(command, (SpeakCommand, AnnounceCommand)):
            if tts_client is None or not voice_state["voice"]:
              logger.error("Cannot synthesize speech because no speech synthesis voice is available")
              continue

            voice = command.voice or voice_state["voice"]

            if voice not in {item.name for item in tts_voices}:
              logger.warning(f"Ignoring unavailable speech synthesis voice: {voice}")
              continue

            if isinstance(command, AnnounceCommand):
              await play_sound_cue("announcement")

            synthesis = tts_client.synthesize_request(command.text, voice)
            speech_task = loop.create_task(
              play_speech(synthesis.url, method=synthesis.method, body=synthesis.body, headers=synthesis.headers),
              name="Speech Announcement Task" if isinstance(command, AnnounceCommand) else "Speech Synthesis Task",
            )
          elif isinstance(command, PlayCommand):
            if not response_started_playback and speaker is not None:
              speaker.stop()

            if playback_task is not None:
              await playback_task

            playback_task = loop.create_task(play_media(command.url), name="Speaker Playback Task")
            response_started_playback = True
          elif isinstance(command, PlayerCommand):
            if command.type == "stop" and speaker is not None:
              speaker.stop()
            elif command.type == "pause" and speaker is not None:
              speaker.pause()
              mqtt_client.set_player_state("paused")
            elif command.type == "resume" and speaker is not None:
              speaker.resume()
              mqtt_client.set_player_state("playing")
          elif isinstance(command, (AlarmCommand, ReminderCommand)):
            schedule(command)
          elif isinstance(command, CancelScheduledCommand):
            scheduled = scheduled_tasks.pop(command.id, None)

            if scheduled is not None:
              scheduled.cancel()
              logger.info(f"Cancelled scheduled command: {command.id}")
          elif isinstance(command, SetVolumeCommand):
            volume = command.volume / 100
            speaker_state["volume"] = volume

            if speaker is not None:
              speaker.set_volume(volume)

            mqtt_client.set_speaker_volume_state(volume)
            await play_sound_cue("volume")
          elif isinstance(command, MuteCommand):
            speaker_state["muted"] = command.muted

            if speaker is not None:
              speaker.set_muted(command.muted)

            mqtt_client.set_speaker_mute_state(command.muted)
          elif isinstance(command, SetVoiceCommand):
            if command.voice in active_voice_names():
              voice_state["voice"] = command.voice
              mqtt_client.publish_voice_state(command.voice)
            else:
              logger.warning(f"Ignoring unavailable speech synthesis voice: {command.voice}")

        if speech_task is None and conversation_state["state"] == "processing":
          conversation_state["state"] = "idle"
          mqtt_client.set_conversation_state("idle")
      elif voice_change_task is not None and voice_change_task in done:
        voice_state["voice"] = voice_change_task.result()
        settings.tts_voice = voice_state["voice"]
        await asyncio.to_thread(update_runtime_settings_cache, settings, tts_voice=voice_state["voice"])
        mqtt_client.publish_voice_state(voice_state["voice"])
        logger.info(f"Speech synthesis voice switched to: {voice_state['voice']}")
      elif language_change_task is not None and language_change_task in done:
        new_language = language_change_task.result()
        language_state["language"] = new_language
        settings.language = new_language
        logger.info(f"Language switched to: {new_language}")

        # Publish the new language state for HA
        mqtt_client.publish_language_state(new_language)
        available_voices = active_voice_names()

        if voice_state["voice"] not in available_voices:
          voice_state["voice"] = available_voices[0] if available_voices else ""

        if voice_state["voice"]:
          mqtt_client.publish_voice_state(voice_state["voice"])

        settings.tts_voice = voice_state["voice"] or None
        await asyncio.to_thread(
          update_runtime_settings_cache,
          settings,
          language=new_language,
          tts_voice=settings.tts_voice,
        )

        # Republish HA discovery so the select shows the new current value
        if mqtt_client.discovery_prefix:
          try:
            curr_stream = active_stream_container["stream"]
            curr_name = curr_stream.device_name if curr_stream else ""
            node_id = mqtt_client.get_node_id()
            device = mqtt_client.get_device_descriptor()
            ha_entities = [
              entity
              for component, _ in started_components
              for entity in component.ha_entities(
                node_id,
                mqtt_client.parse_event_topic(""),
                mqtt_client.parse_node_topic("available"),
                device,
              )
            ]
            mqtt_client.publish_discovery_configs(
              input_devices=Audio.get_compatible_input_devices(current_device=curr_name) if needs_audio else [],
              current_device=curr_name,
              entities=ha_entities,
              microphone_muted=device_state["microphone_muted"],
              output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
              current_output=speaker_state["device"],
              speaker_muted=speaker_state["muted"],
              speaker_volume=speaker_state["volume"],
              current_language=new_language,
              microphone_enabled=microphone_enabled,
              speaker_enabled=speaker_enabled,
              voices=available_voices if tts_client else None,
              current_voice=voice_state["voice"],
            )
          except Exception as error:
            logger.error(f"Failed to republish discovery after language change: {error}")

        # Ohunerin reads the language when opening its WebSocket, so reconnect it.
        for component, comp_config in started_components:
          if component.name == "ohunerin":
            await component.stop()
            await component.start(comp_config, mqtt_client, shared_resources)
      else:
        supervisor_action = classify_supervisor_done(done, listening_tasks, component_tasks)

        if supervisor_action == "recover_audio":
          # Audio feed task ended (e.g. mic disconnected) but WebSocket is still up
          logger.warning("Listening task finished unexpectedly (possibly microphone disconnected).")
          loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")
        elif supervisor_action == "exit":
          # A main component task finished — time to exit
          break
  finally:
    for signal_number in (signal.SIGINT, signal.SIGTERM):
      loop.remove_signal_handler(signal_number)

    if not shutdown_task.done():
      shutdown_task.cancel()

    if monitor_task is not None:
      monitor_task.cancel()

    for scheduled_task in scheduled_tasks.values():
      scheduled_task.cancel()

    if scheduled_tasks:
      await asyncio.gather(*scheduled_tasks.values(), return_exceptions=True)

    # Ensure all components are stopped
    for component, _ in started_components:
      await component.stop()

    current_stream = active_stream_container["stream"]

    if current_stream is not None:
      current_stream.stop()

    if speaker is not None:
      speaker.stop()

    if playback_task is not None:
      await playback_task

    if speech_task is not None:
      await speech_task

    mqtt_client.set_availability(False)
    await play_sound_cue("shutdown")
    mqtt_client.disconnect()
