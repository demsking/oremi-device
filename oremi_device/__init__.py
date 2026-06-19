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
import json
import logging
import signal
import sys

import sounddevice as sd

from .components import COMPONENTS
from .components.base import AudioStreamComponent
from .core.args import parse_arguments
from .core.audio import Audio
from .core.audio import AudioDeviceError
from .core.models import DeviceConfig
from .core.models import DeviceContext
from .core.mqtt import MQTTClient
from .core.package import APP_NAME
from .core.package import APP_VERSION
from .core.speaker import Speaker
from .core.speaker import SpeakerDeviceError
from .core.speaker import SpeakerPlaybackError
from .utils.logger import logger


async def start() -> None:
  args = parse_arguments()

  loop = asyncio.get_running_loop()

  # Log initial configuration
  logger.info(f"Starting {APP_NAME}/{APP_VERSION}")
  logger.info(f"Log level: {logging.getLevelName(logger.getEffectiveLevel())}")
  logger.info(f"Configuration Node ID: {args.node_id}")
  logger.info(f"Configuration Ohunerin Host: {args.ohunerin_host}")
  logger.info(f"Configuration Ohunerin Port: {args.ohunerin_port}")
  logger.info(f"Configuration Andika Host: {args.andika_host}")
  logger.info(f"Configuration Andika Port: {args.andika_port}")
  logger.info(f"Configuration Secure Connection: {'Enabled' if args.cert_file else 'Disabled'}")
  microphone_enabled = args.microphone_enabled
  speaker_enabled = args.speaker_enabled
  logger.info(f"Configuration Microphone: {'Enabled' if microphone_enabled else 'Disabled'}")
  logger.info(f"Configuration Speaker: {'Enabled' if speaker_enabled else 'Disabled'}")

  if args.cert_file:
    logger.info(f"Configuration Certificate File: {args.cert_file}")

  config_path = args.config
  logger.info(f"Device Configuration Path: {config_path or 'None'}")

  context = DeviceContext(
    node_id=args.node_id,
    language=args.language,
    delay=args.delay,
    conversation_timeout=args.conversation_timeout,
    ohunerin_host=args.ohunerin_host,
    ohunerin_port=args.ohunerin_port,
    andika_host=args.andika_host,
    andika_port=args.andika_port,
    cert_file=args.cert_file,
  )

  device_config: DeviceConfig | None = None

  if config_path:
    try:
      with open(config_path, "r", encoding="utf-8") as file:
        device_config = DeviceConfig.model_validate(json.load(file))
    except Exception as error:
      logger.error(f"Failed to load configuration file '{config_path}': {error}")
      sys.exit(1)
  else:
    device_config = DeviceConfig()

  logger.info(f"Configuration Language: {context.language}")

  # ── Resolve active components ────────────────────────────────────────────────
  active_components: list[tuple] = []

  for comp_name, (load_config, create_component) in COMPONENTS.items():
    comp_config = getattr(device_config.components, comp_name, None)
    comp_config = load_config.model_validate(comp_config) if comp_config else load_config()  # type: ignore

    component = create_component(context)  # pylint: disable=abstract-class-instantiated

    active_components.append((component, comp_config))

  # ── Audio stream (only for AudioStreamComponents) ────────────────────────────
  # Check whether any active component actually needs the microphone so that
  # HTTP-only components (e.g. Injini) can run without any audio hardware.
  needs_audio = microphone_enabled and any(isinstance(c, AudioStreamComponent) for c, _ in active_components)

  audio_stream: Audio | None = None

  if needs_audio:
    try:
      audio_stream = Audio(device_index=args.device_index, device_name=args.device)
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
      speaker = Speaker()
      logger.info(f"Active Speaker Device: {speaker.device_name}")
    except SpeakerDeviceError as error:
      logger.warning(str(error))
  else:
    logger.info("Speaker disabled — skipping speaker initialisation.")

  # ── MQTT client ──────────────────────────────────────────────────────────────
  mqtt_client = MQTTClient(
    broker=args.mqtt_broker,
    port=args.mqtt_port,
    node_id=args.node_id,
    topic=args.mqtt_topic,
    username=args.mqtt_username,
    password=args.mqtt_password,
    discovery_prefix=args.mqtt_discovery_prefix if args.mqtt_discovery else None,
  )

  # MQTT callbacks run on the client thread, so command state must exist
  # before connecting and subscribing to retained command topics.
  device_change_queue: asyncio.Queue = asyncio.Queue()
  device_enable_queue: asyncio.Queue = asyncio.Queue()
  microphone_mute_queue: asyncio.Queue = asyncio.Queue()
  speaker_change_queue: asyncio.Queue = asyncio.Queue()
  speaker_mute_queue: asyncio.Queue = asyncio.Queue()
  speaker_volume_queue: asyncio.Queue = asyncio.Queue()
  player_play_queue: asyncio.Queue = asyncio.Queue()
  player_stop_queue: asyncio.Queue = asyncio.Queue()
  language_change_queue: asyncio.Queue = asyncio.Queue()
  wakeword_event = asyncio.Event()
  device_state: dict = {"enabled": True, "microphone_muted": False}
  speaker_state: dict = {
    "device": speaker.device_name if speaker else "",
    "muted": speaker.muted if speaker else False,
    "volume": speaker.volume if speaker else 1.0,
  }
  language_state: dict = {"language": args.language}
  playback_task: asyncio.Task | None = None

  async def play_media(media_url: str) -> None:
    if speaker is None:
      logger.error("Cannot play media because no compatible speaker is available")
      return

    mqtt_client.set_player_state("playing")

    try:
      await asyncio.to_thread(speaker.play_url, media_url)
    except SpeakerPlaybackError as error:
      logger.error(f"Media playback failed: {error}")
    finally:
      mqtt_client.set_player_state("idle")

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

    # Subscribe to the instance-scoped enable/disable switch command topic.
    client.subscribe(mqtt_client.get_switch_command_topic())

    # Subscribe to the language-select command topic.
    client.subscribe(mqtt_client.get_language_command_topic())

    if mqtt_client.discovery_prefix:
      try:
        curr_stream = active_stream_container["stream"]
        curr_name = curr_stream.device_name if curr_stream else ""
        node_id = mqtt_client.get_node_id()
        device = mqtt_client.get_device_descriptor()

        ha_entities = [
          entity for component, _ in active_components for entity in component.ha_entities(node_id, mqtt_client.topic, device)
        ]

        mqtt_client.publish_discovery_configs(
          input_devices=Audio.get_compatible_input_devices(current_device=curr_name) if needs_audio else [],
          current_device=curr_name,
          entities=ha_entities,
          enabled=device_state["enabled"],
          microphone_muted=device_state["microphone_muted"],
          output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
          current_output=speaker_state["device"],
          speaker_muted=speaker_state["muted"],
          speaker_volume=speaker_state["volume"],
          current_language=language_state["language"],
          microphone_enabled=microphone_enabled,
          speaker_enabled=speaker_enabled,
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

    elif topic == mqtt_client.get_switch_command_topic():
      try:
        payload = message.payload.decode("utf-8").strip().upper()
        logger.info(f"Received device switch command: {payload}")

        if payload in ("ON", "OFF"):
          loop.call_soon_threadsafe(device_enable_queue.put_nowait, payload == "ON")
      except Exception as error:
        logger.error(f"Error decoding or handling MQTT switch command: {error}")

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

  def handle_task_done(task: asyncio.Task) -> None:
    try:
      if task.exception() is not None:
        logger.error(task)
      elif task.cancelled():
        logger.info(f"{task.get_name()} cancelled")
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
      if device_state["enabled"] and not device_state["microphone_muted"]:
        for component, _ in started_components:
          if isinstance(component, AudioStreamComponent):
            await component.on_device_changed(new_stream)

      # Publish microphone state
      mqtt_client.publish("microphone/state", new_stream.device_name, retain=True)
      mqtt_client.set_availability(True)

      # Republish HA discovery options with updated device list
      if mqtt_client.discovery_prefix:
        node_id = mqtt_client.get_node_id()
        device = mqtt_client.get_device_descriptor()
        ha_entities = [
          entity for component, _ in started_components for entity in component.ha_entities(node_id, mqtt_client.topic, device)
        ]
        comp_devices = Audio.get_compatible_input_devices(current_device=new_stream.device_name)
        mqtt_client.publish_discovery_configs(
          input_devices=comp_devices,
          current_device=new_stream.device_name,
          entities=ha_entities,
          enabled=device_state["enabled"],
          microphone_muted=device_state["microphone_muted"],
          output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
          current_output=speaker_state["device"],
          speaker_muted=speaker_state["muted"],
          speaker_volume=speaker_state["volume"],
          current_language=language_state["language"],
          microphone_enabled=microphone_enabled,
          speaker_enabled=speaker_enabled,
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

      mqtt_client.publish("microphone/state", "None", retain=True)
      mqtt_client.set_availability(False)

      return False

  shared_resources = {
    "active_stream_container": active_stream_container,
    "device_change_queue": device_change_queue,
    "device_enable_queue": device_enable_queue,
    "microphone_mute_queue": microphone_mute_queue,
    "speaker": speaker,
    "speaker_state": speaker_state,
    "language_change_queue": language_change_queue,
    "wakeword_event": wakeword_event,
    "device_state": device_state,
    "language_state": language_state,
    "change_audio_device": change_audio_device,
    "handle_task_done": handle_task_done,
  }

  # ── Start all active components ──────────────────────────────────────────────
  for component, comp_config in active_components:
    logger.info(f"Starting component: {component.name}")
    await component.start(comp_config, mqtt_client, shared_resources)
    started_components.append((component, comp_config))

  async def shutdown() -> None:
    logger.info("Shutdown signal received. Stopping all components...")
    for component, _ in started_components:
      await component.stop()

  loop.add_signal_handler(signal.SIGINT, lambda: loop.create_task(shutdown()))
  loop.add_signal_handler(signal.SIGTERM, lambda: loop.create_task(shutdown()))

  # ── Main event loop ──────────────────────────────────────────────────────────
  preferred_device = args.device if args.device is not None else args.device_index

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
            for entity in component.ha_entities(node_id, mqtt_client.topic, device)
          ]
          mqtt_client.publish_discovery_configs(
            input_devices=compatible_devs,
            current_device=curr_name or "",
            entities=ha_entities,
            enabled=device_state["enabled"],
            microphone_muted=device_state["microphone_muted"],
            output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
            current_output=speaker_state["device"],
            speaker_muted=speaker_state["muted"],
            speaker_volume=speaker_state["volume"],
            current_language=language_state["language"],
            microphone_enabled=microphone_enabled,
            speaker_enabled=speaker_enabled,
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

      device_enable_task = loop.create_task(device_enable_queue.get())
      tasks.append(device_enable_task)

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
      tasks.append(language_change_task)

      done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

      # Queue reads are recreated on each iteration. Cancel the pending ones so
      # they cannot consume a later command behind the active iteration's task.
      command_tasks = [
        device_change_task,
        device_enable_task,
        microphone_mute_task,
        speaker_change_task,
        speaker_mute_task,
        speaker_volume_task,
        player_play_task,
        player_stop_task,
        language_change_task,
      ]

      for command_task in command_tasks:
        if command_task is not None and command_task not in done:
          command_task.cancel()

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

      elif device_enable_task is not None and device_enable_task in done:
        new_enabled = device_enable_task.result()
        device_state["enabled"] = new_enabled

        if new_enabled:
          logger.info("Device enabled from HA UI. Resuming listening...")
          mqtt_client.set_switch_state(True)

          # Resume the audio stream if it was up before being disabled
          if needs_audio:
            curr_stream = active_stream_container["stream"]

            if curr_stream is not None and not device_state["microphone_muted"]:
              for component, _ in started_components:
                if isinstance(component, AudioStreamComponent):
                  await component.on_device_changed(curr_stream)
            else:
              loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")

          mqtt_client.set_availability(True)
        else:
          logger.info("Device disabled from HA UI. Stopping listening and sleeping...")
          mqtt_client.set_switch_state(False)

          # Stop all audio stream components (stop listening but keep WS/MQTT alive)
          if needs_audio:
            for component, _ in started_components:
              if isinstance(component, AudioStreamComponent):
                await component.on_device_changed(None)

          mqtt_client.set_availability(False)
      elif microphone_mute_task is not None and microphone_mute_task in done:
        muted = microphone_mute_task.result()
        device_state["microphone_muted"] = muted
        mqtt_client.set_mute_state(muted)

        if muted:
          logger.info("Microphone muted. Stopping audio capture...")

          for component, _ in started_components:
            if isinstance(component, AudioStreamComponent):
              await component.on_device_changed(None)
        elif device_state["enabled"]:
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
          mqtt_client.set_speaker_state(speaker.device_name)
          logger.info(f"Speaker switched to: {speaker.device_name}")
        except SpeakerDeviceError as error:
          logger.error(error)
          mqtt_client.set_speaker_state(speaker_state["device"])
      elif speaker_mute_task is not None and speaker_mute_task in done:
        muted = speaker_mute_task.result()
        speaker_state["muted"] = muted

        if speaker:
          speaker.set_muted(muted)

        mqtt_client.set_speaker_mute_state(muted)
        logger.info(f"Speaker {'muted' if muted else 'unmuted'}")
      elif speaker_volume_task is not None and speaker_volume_task in done:
        volume = speaker_volume_task.result()
        speaker_state["volume"] = volume

        if speaker:
          speaker.set_volume(volume)

        mqtt_client.set_speaker_volume_state(volume)
        logger.info(f"Speaker volume set to {volume:.0%}")
      elif player_play_task is not None and player_play_task in done:
        media_url = player_play_task.result()

        if speaker is not None:
          speaker.stop()

        if playback_task is not None:
          await playback_task

        playback_task = loop.create_task(play_media(media_url), name="Speaker Playback Task")
      elif player_stop_task is not None and player_stop_task in done:
        if speaker is not None:
          speaker.stop()

        if playback_task is not None:
          await playback_task
          playback_task = None
      elif language_change_task is not None and language_change_task in done:
        new_language = language_change_task.result()
        language_state["language"] = new_language
        context.language = new_language
        logger.info(f"Language switched to: {new_language}")

        # Publish the new language state for HA
        mqtt_client.publish_language_state(new_language)

        # Republish HA discovery so the select shows the new current value
        if mqtt_client.discovery_prefix:
          try:
            curr_stream = active_stream_container["stream"]
            curr_name = curr_stream.device_name if curr_stream else ""
            node_id = mqtt_client.get_node_id()
            device = mqtt_client.get_device_descriptor()
            ha_entities = [
              entity for component, _ in started_components for entity in component.ha_entities(node_id, mqtt_client.topic, device)
            ]
            mqtt_client.publish_discovery_configs(
              input_devices=Audio.get_compatible_input_devices(current_device=curr_name) if needs_audio else [],
              current_device=curr_name,
              entities=ha_entities,
              enabled=device_state["enabled"],
              microphone_muted=device_state["microphone_muted"],
              output_devices=Speaker.get_compatible_output_devices() if speaker_enabled else [],
              current_output=speaker_state["device"],
              speaker_muted=speaker_state["muted"],
              speaker_volume=speaker_state["volume"],
              current_language=new_language,
              microphone_enabled=microphone_enabled,
              speaker_enabled=speaker_enabled,
            )
          except Exception as error:
            logger.error(f"Failed to republish discovery after language change: {error}")

        # Ohunerin reads the language when opening its WebSocket, so reconnect it.
        for component, comp_config in started_components:
          if component.name == "ohunerin":
            await component.stop()
            await component.start(comp_config, mqtt_client, shared_resources)
      else:
        is_listening_done = any(t in listening_tasks for t in done)
        is_main_done = any(t in component_tasks for t in done)

        if is_listening_done and not is_main_done:
          # Audio feed task ended (e.g. mic disconnected) but WebSocket is still up
          logger.warning("Listening task finished unexpectedly (possibly microphone disconnected).")
          loop.call_soon_threadsafe(device_change_queue.put_nowait, "__auto_select__")
        else:
          # A main component task finished — time to exit
          break
  finally:
    if speaker is not None:
      speaker.stop()

    if playback_task is not None:
      await playback_task

    if monitor_task is not None:
      monitor_task.cancel()

    # Ensure all components are stopped
    for component, _ in started_components:
      await component.stop()

    current_stream = active_stream_container["stream"]

    if current_stream is not None:
      current_stream.stop()

    mqtt_client.set_availability(False)
    mqtt_client.disconnect()
