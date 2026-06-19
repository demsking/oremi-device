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
from .utils.logger import LOG_LEVEL_STR
from .utils.logger import logger


async def start() -> None:
  args = parse_arguments()
  loop = asyncio.get_running_loop()

  # Log initial configuration
  logger.info(f"Starting {APP_NAME}/{APP_VERSION}")
  logger.info(f"Log level: {LOG_LEVEL_STR}")
  logger.info(f"Configuration Node ID: {args.node_id}")
  logger.info(f"Configuration Ohunerin Host: {args.ohunerin_host}")
  logger.info(f"Configuration Ohunerin Port: {args.ohunerin_port}")
  logger.info(f"Configuration Andika Host: {args.andika_host}")
  logger.info(f"Configuration Andika Port: {args.andika_port}")
  logger.info(f"Configuration Secure Connection: {'Enabled' if args.cert_file else 'Disabled'}")

  if args.cert_file:
    logger.info(f"Configuration Certificate File: {args.cert_file}")

  config_path = args.config
  logger.info(f"Device Configuration Path: {config_path or 'None'}")

  context = DeviceContext(
    node_id=args.node_id,
    language=args.language,
    delay=args.delay,
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
  needs_audio = any(isinstance(c, AudioStreamComponent) for c, _ in active_components)

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
  else:
    logger.info("No AudioStreamComponent active — skipping audio initialisation.")

  active_stream_container: dict = {"stream": audio_stream}

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

  @mqtt_client.client.connect_callback()
  def mqtt_on_connect(client, userdata, flags, reason_code, properties) -> None:
    logger.info(f"Connected to MQTT broker with result code {reason_code}")

    if needs_audio:
      # Subscribe to the instance-scoped microphone-select command topic.
      # Using node_id in the topic prevents cross-instance interference when
      # multiple oremi-device instances share the same base MQTT topic.
      client.subscribe(mqtt_client.get_microphone_command_topic())

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
          input_devices=Audio.get_compatible_input_devices(current_device=curr_name),
          current_device=curr_name,
          entities=ha_entities,
          enabled=device_state["enabled"],
          current_language=language_state["language"],
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

  # Queue to receive audio device-change requests (used only when needs_audio)
  device_change_queue: asyncio.Queue = asyncio.Queue()
  # Queue to receive HA enable/disable switch commands
  device_enable_queue: asyncio.Queue = asyncio.Queue()
  # Queue to receive HA language-select commands
  language_change_queue: asyncio.Queue = asyncio.Queue()
  device_state: dict = {"enabled": True}
  language_state: dict = {"language": args.language}

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

    elif topic == mqtt_client.get_language_command_topic():
      try:
        new_language = message.payload.decode("utf-8").strip().lower()
        logger.info(f"Received language set command: {new_language}")
        loop.call_soon_threadsafe(language_change_queue.put_nowait, new_language)
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

      # Signal components that a new stream is ready
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
          current_language=language_state["language"],
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
    "language_change_queue": language_change_queue,
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
            current_language=language_state["language"],
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

      language_change_task = loop.create_task(language_change_queue.get())
      tasks.append(language_change_task)

      done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

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

            if curr_stream is not None:
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
      elif language_change_task is not None and language_change_task in done:
        new_language = language_change_task.result()
        language_state["language"] = new_language
        args.language = new_language
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
              input_devices=Audio.get_compatible_input_devices(current_device=curr_name),
              current_device=curr_name,
              entities=ha_entities,
              enabled=device_state["enabled"],
              current_language=new_language,
            )
          except Exception as error:
            logger.error(f"Failed to republish discovery after language change: {error}")

        # Restart audio components to reconnect to ohunerin with the new language
        if needs_audio:
          curr_stream = active_stream_container["stream"]

          for component, _ in started_components:
            if isinstance(component, AudioStreamComponent):
              await component.on_device_changed(None)
              if curr_stream is not None:
                await component.on_device_changed(curr_stream)
      else:
        # Cancel the pending queue-wait tasks (if any) before handling task completion
        if device_change_task is not None:
          device_change_task.cancel()

        if device_enable_task is not None:
          device_enable_task.cancel()

        if language_change_task is not None:
          language_change_task.cancel()

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
    if monitor_task is not None:
      monitor_task.cancel()

    # Ensure all components are stopped
    for component, _ in started_components:
      await component.stop()
