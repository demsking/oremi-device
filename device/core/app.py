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
import inspect
import logging
import signal
from typing import Any
from typing import cast

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from device.components import COMPONENTS
from device.components.ohunerin import OhunerinComponent
from device.core.audio import AudioDeviceError
from device.core.components import ActiveStreamContainer
from device.core.components import AudioStreamComponent
from device.core.components import SharedResources
from device.core.cues import ConversationEvent
from device.core.cues import get_sound_cue_path
from device.core.cues import SoundCue
from device.core.mcp import McpDevice
from device.core.models import ProcessingResponse
from device.core.mqtt import DEVICE_CONTEXT_OPTIONS
from device.core.mqtt import DEVICE_CONTEXT_TEXT_FIELDS
from device.core.mqtt import HomeAssistantDevice
from device.core.package import APP_DOCUMENTATION_URL
from device.core.package import APP_NAME
from device.core.package import APP_VERSION
from device.core.settings import apply_runtime_settings_cache
from device.core.settings import get_settings
from device.core.settings import log_group
from device.core.settings import read_runtime_settings_cache
from device.core.settings import SettingsUpdates
from device.core.settings import update_runtime_settings_cache
from device.mcp.prompts import register_mcp_prompts
from device.mcp.resources import register_mcp_resources
from device.mcp.tools import register_mcp_tools
from device.services.audio_service import AudioService
from device.services.command_executor import CommandExecutor
from device.services.tts_manager import TTSManager
from device.utils.context import build_device_context
from device.utils.context import parse_device_context_command_field
from device.utils.context import validate_device_context_value
from device.utils.logger import configure_logging


logger = logging.getLogger(__name__)


class DeviceApplication:
  def __init__(self) -> None:
    self.settings = get_settings()
    self.shutdown_event = asyncio.Event()
    self.loop = asyncio.get_event_loop()

    # Centralized State
    self.device_context = build_device_context(self.settings)

    # Task Tracking
    self.background_tasks: list[asyncio.Task] = []

    self._geocode_retry_interval = 60.0

    self._setup_queues()

  def _setup_queues(self) -> None:
    """Initialize all event queues required by the application."""
    self.queues: dict[str, asyncio.Queue[Any]] = {
      "device_change": asyncio.Queue(),
      "microphone_mute": asyncio.Queue(),
      "speaker_change": asyncio.Queue(),
      "speaker_mute": asyncio.Queue(),
      "speaker_volume": asyncio.Queue(),
      "player_play": asyncio.Queue(),
      "player_stop": asyncio.Queue(),
      "language_change": asyncio.Queue(),
      "device_context_change": asyncio.Queue(),
      "processing": asyncio.Queue(),
      "voice_change": asyncio.Queue(),
      "transcription": asyncio.Queue(),
    }

  def _setup_signals(self) -> None:
    """Bind OS signals to the shutdown event."""
    for sig in (signal.SIGINT, signal.SIGTERM):
      self.loop.add_signal_handler(sig, self._request_shutdown)

  def _request_shutdown(self) -> None:
    if not self.shutdown_event.is_set():
      logger.info("Shutdown signal received. Stopping application...")
      self.shutdown_event.set()

  async def play_sound_cue(self, cue: SoundCue) -> None:
    if self.audio.speaker:
      try:
        await asyncio.to_thread(self.audio.speaker.play_file, get_sound_cue_path(cue))
      except Exception as error:
        logger.warning(f"Failed to play sound cue {cue}: {error}")

  def _handle_task_done(self, task: asyncio.Task) -> None:
    if task.cancelled():
      return

    try:
      task.result()
    except Exception as error:
      logger.exception(f"Unhandled error in task {task.get_name() or task}: {error}")

  def _publish_discovery(self) -> None:
    if self.ha_device.discovery_prefix:
      try:
        from device.core.audio import Audio
        from device.core.speaker import Speaker

        curr_stream_name = self.audio.audio_stream.device_name if self.audio.audio_stream else None
        input_devices = Audio.get_compatible_input_devices(current_device=curr_stream_name) if self.audio.needs_audio else []
        output_devices = Speaker.get_compatible_output_devices() if self.audio.speaker_enabled else []
        ohunerin_comp: OhunerinComponent = self.components.get("ohunerin")  # type: ignore
        ohunerin_sounds = ohunerin_comp.get_supported_sounds()

        self.ha_device.publish_discovery_configs(
          input_devices=input_devices,
          current_device=curr_stream_name or "",
          microphone_muted=self.settings.microphone_muted,
          output_devices=output_devices,
          current_output=str(self.audio.speaker_state.get("device", "") or ""),
          speaker_muted=bool(self.audio.speaker_state.get("muted", False)),
          speaker_volume=cast(float, self.audio.speaker_state.get("volume", 1.0)),
          current_language=self.settings.language,
          device_context=self.device_context,
          microphone_enabled=self.settings.microphone_enabled,
          speaker_enabled=self.settings.speaker_enabled,
          voices=self.tts.get_active_voice_names() if self.tts else None,
          current_voice=self.tts.current_voice or "",
          ohunerin_sounds=ohunerin_sounds,
        )
      except Exception as error:
        logger.error(f"Failed to publish discovery: {error}")

  def _setup_mqtt_callbacks(self) -> None:
    """Bind MQTT network events to internal asyncio queues."""

    @self.ha_device.client.connect_callback()
    def mqtt_on_connect(client, userdata, flags, reason_code, properties) -> None:
      logger.info(f"Connected to MQTT broker with result code {reason_code}")

      if self.audio.needs_audio:
        client.subscribe(self.ha_device.get_microphone_command_topic())
        client.subscribe(self.ha_device.get_mute_command_topic())

      if self.audio.speaker_enabled:
        client.subscribe(self.ha_device.get_speaker_command_topic())
        client.subscribe(self.ha_device.get_speaker_mute_cmd_topic())
        client.subscribe(self.ha_device.get_speaker_volume_cmd_topic())
        client.subscribe(self.ha_device.get_player_play_command_topic())
        client.subscribe(self.ha_device.get_player_stop_command_topic())
        client.subscribe(self.ha_device.get_processing_result_topic())

      client.subscribe(self.ha_device.get_language_command_topic())
      for field in (*DEVICE_CONTEXT_TEXT_FIELDS, *DEVICE_CONTEXT_OPTIONS):
        client.subscribe(self.ha_device.get_device_context_command_topic(field))

      self.ha_device.publish_device_context(self.device_context)

    @self.ha_device.client.disconnect_callback()
    def mqtt_on_disconnect(client, userdata, flags, reason_code, properties) -> None:
      if self.audio.audio_stream and self.audio.audio_stream.is_active():
        logger.warning(f"Unexpected MQTT disconnection (code {reason_code}). Reconnecting...")
        self.ha_device.connect()
      else:
        logger.info(f"Disconnected from MQTT broker (code {reason_code})")

    @self.ha_device.client.message_callback()
    def mqtt_on_message(client, userdata, message) -> None:
      topic = message.topic
      payload_str = ""

      try:
        payload_str = message.payload.decode("utf-8").strip()
      except UnicodeDecodeError:
        pass  # Handled per-topic below if raw bytes are expected

      if self.audio.needs_audio and topic == self.ha_device.get_microphone_command_topic():
        logger.info(f"Received microphone set command: {payload_str}")
        self.loop.call_soon_threadsafe(self.queues["device_change"].put_nowait, payload_str)

      elif self.audio.needs_audio and topic == self.ha_device.get_mute_command_topic():
        logger.info(f"Received microphone mute command: {payload_str.upper()}")
        if payload_str.upper() in ("ON", "OFF"):
          self.loop.call_soon_threadsafe(self.queues["microphone_mute"].put_nowait, payload_str.upper() == "ON")

      elif self.audio.speaker_enabled and topic == self.ha_device.get_speaker_command_topic():
        logger.info(f"Received speaker set command: {payload_str}")
        self.loop.call_soon_threadsafe(self.queues["speaker_change"].put_nowait, payload_str)

      elif self.audio.speaker_enabled and topic == self.ha_device.get_speaker_mute_cmd_topic():
        if payload_str.upper() in ("ON", "OFF"):
          self.loop.call_soon_threadsafe(self.queues["speaker_mute"].put_nowait, payload_str.upper() == "ON")

      elif self.audio.speaker_enabled and topic == self.ha_device.get_speaker_volume_cmd_topic():
        try:
          volume = float(payload_str) / 100
          if 0.0 <= volume <= 1.0:
            self.loop.call_soon_threadsafe(self.queues["speaker_volume"].put_nowait, volume)
        except ValueError:
          logger.error("Error handling MQTT speaker volume command")

      elif self.audio.speaker_enabled and topic == self.ha_device.get_player_play_command_topic():
        if payload_str:
          self.loop.call_soon_threadsafe(self.queues["player_play"].put_nowait, payload_str)

      elif self.audio.speaker_enabled and topic == self.ha_device.get_player_stop_command_topic():
        self.loop.call_soon_threadsafe(self.queues["player_stop"].put_nowait, True)

      elif topic == self.ha_device.get_language_command_topic():
        logger.info(f"Received language set command: {payload_str.lower()}")
        if payload_str.lower() in ("fr", "en"):
          self.loop.call_soon_threadsafe(self.queues["language_change"].put_nowait, payload_str.lower())
        else:
          logger.warning(f"Ignoring unsupported language command: {payload_str}")

      elif (field := parse_device_context_command_field(topic, self.ha_device.parse_node_topic("context"))) is not None:
        value = validate_device_context_value(field, payload_str)
        if value is not None:
          logger.info(f"Received device context command: {field}={value}")
          if field == "language":
            self.loop.call_soon_threadsafe(self.queues["language_change"].put_nowait, value)
          else:
            self.loop.call_soon_threadsafe(self.queues["device_context_change"].put_nowait, (field, value))

      elif self.audio.speaker_enabled and topic == self.ha_device.get_processing_result_topic():
        try:
          response = ProcessingResponse.model_validate_json(message.payload)
          self.loop.call_soon_threadsafe(self.queues["processing"].put_nowait, response)
        except ValidationError:
          logger.warning("Ignoring invalid NLP processing response")

  async def _event_loop_processor(self) -> None:
    """Unified queue processor handling all application events."""
    while not self.shutdown_event.is_set():
      # Create a task map to identify which queue triggered
      task_map = {asyncio.create_task(queue.get()): name for name, queue in self.queues.items()}

      # Add shutdown event to the waitable tasks
      shutdown_task = asyncio.create_task(self.shutdown_event.wait())
      task_map[shutdown_task] = "shutdown"

      done, pending = await asyncio.wait(task_map.keys(), return_when=asyncio.FIRST_COMPLETED)

      # Cleanup pending tasks to avoid memory leaks
      for task in pending:
        task.cancel()

      if shutdown_task in done:
        break

      # Process completed events
      for task in done:
        event_type = task_map[task]

        try:
          result = task.result()
          await self._handle_event(event_type, result)
        except Exception as e:
          logger.error(f"Error processing {event_type} event: {e}")

  async def _handle_event(self, event_type: str, data: Any) -> None:
    """Route mapped events to their respective service handlers."""
    if event_type == "device_change":
      await self.apply_settings_updates({"microphone_device": data})

    elif event_type == "microphone_mute":
      await self.apply_settings_updates({"microphone_muted": data})

    elif event_type == "speaker_change":
      await self.apply_settings_updates({"speaker_device": data})

    elif event_type == "speaker_mute":
      await self.apply_settings_updates({"speaker_muted": data})

    elif event_type == "speaker_volume":
      await self.apply_settings_updates({"speaker_volume": data})

    elif event_type == "player_play":
      await self.executor.cancel_active()

      speaker = self.audio.speaker

      if speaker:
        # Logic for media playback delegated to executor
        self.executor.playback_task = self.loop.create_task(asyncio.to_thread(speaker.play_url, data))

    elif event_type == "player_stop":
      await self.executor.cancel_active()

    elif event_type == "language_change":
      await self.apply_settings_updates({"language": data})

    elif event_type == "device_context_change":
      field, value = data
      await self.apply_settings_updates(cast(SettingsUpdates, {field: value}))

    elif event_type == "processing":
      await self.executor.execute_response(data)

  async def apply_settings_updates(self, updates: SettingsUpdates) -> None:
    """Apply updated runtime settings across running application subsystems."""
    if not updates:
      return

    if "microphone_device" in updates:
      device_name = updates["microphone_device"]

      if hasattr(self, "audio") and self.audio:
        components_list = list(self.components.values()) if hasattr(self, "components") and self.components else []
        await self.audio.change_audio_device(device_name, components_list)

        if self.audio.audio_stream:
          if hasattr(self, "active_stream_container"):
            self.active_stream_container["stream"] = self.audio.audio_stream

          if hasattr(self, "ha_device") and self.ha_device:
            self.ha_device.publish_node("microphone/state", self.audio.audio_stream.device_name, retain=True)
        else:
          if hasattr(self, "active_stream_container"):
            self.active_stream_container["stream"] = None

          if hasattr(self, "ha_device") and self.ha_device:
            self.ha_device.publish_node("microphone/state", "None", retain=True)

        self._publish_discovery()

    if "microphone_muted" in updates:
      muted = updates["microphone_muted"]
      self.settings.microphone_muted = muted

      if hasattr(self, "audio") and self.audio:
        self.audio.device_state["microphone_muted"] = muted

      if hasattr(self, "ha_device") and self.ha_device:
        self.ha_device.set_mute_state(muted)

      if hasattr(self, "components") and self.components:
        for component in self.components.values():
          if isinstance(component, AudioStreamComponent):
            await component.on_mute_changed(muted)

    if "speaker_device" in updates:
      device_name = updates["speaker_device"]
      self.settings.speaker_device = device_name

      if device_name is not None:
        if hasattr(self, "audio") and self.audio and self.audio.speaker:
          self.audio.speaker.select_device(device_name)

        if hasattr(self, "ha_device") and self.ha_device:
          self.ha_device.set_speaker_state(device_name)
          self._publish_discovery()

    if "speaker_muted" in updates:
      muted = updates["speaker_muted"]
      self.settings.speaker_muted = muted

      if hasattr(self, "audio") and self.audio and self.audio.speaker:
        self.audio.speaker.set_muted(muted)
        await self.play_sound_cue("mute_on" if muted else "mute_off")

      if hasattr(self, "ha_device") and self.ha_device:
        self.ha_device.set_speaker_mute_state(muted)
        self._publish_discovery()

    if "speaker_volume" in updates:
      volume = updates["speaker_volume"]
      self.settings.speaker_volume = volume

      if hasattr(self, "audio") and self.audio and self.audio.speaker:
        self.audio.speaker.set_volume(volume)
        await self.play_sound_cue("volume")

      if hasattr(self, "ha_device") and self.ha_device:
        self.ha_device.set_speaker_volume_state(volume)
        self._publish_discovery()

    if "language" in updates:
      language = updates["language"]
      self.settings.language = language

      if hasattr(self, "device_context"):
        self.device_context["language"] = language

      if hasattr(self, "ha_device") and self.ha_device:
        self.ha_device.publish_language_state(language)

        if hasattr(self, "device_context"):
          self.ha_device.publish_device_context(self.device_context)

      if hasattr(self, "tts") and self.tts:
        self.tts.update_voice_for_language(language)

        if self.tts.current_voice and hasattr(self, "ha_device") and self.ha_device:
          self.ha_device.publish_voice_state(self.tts.current_voice)

      self._publish_discovery()

      if hasattr(self, "components") and "ohunerin" in self.components:
        await self.components["ohunerin"].stop()

        if hasattr(self, "shared_resources") and "language_state" in self.shared_resources:
          self.shared_resources["language_state"]["language"] = language

        await self.components["ohunerin"].start(self.component_configs["ohunerin"], self.shared_resources)

    context_fields = {
      "location",
      "timezone",
      "temperature_unit",
      "preferred_currency",
      "measurement_system",
      "distance_unit",
      "time_format",
      "date_format",
      "first_day_of_week",
    }

    updates_dict: dict[str, Any] = cast(dict[str, Any], updates)
    updated_context_fields = context_fields.intersection(updates_dict.keys())

    if updated_context_fields:
      for field in updated_context_fields:
        setattr(self.settings, field, updates_dict[field])

      self.device_context = await asyncio.to_thread(build_device_context, self.settings)

      if hasattr(self, "ha_device") and self.ha_device:
        for field in updated_context_fields:
          self.ha_device.publish_device_context_value(field, updates_dict[field])

        self.ha_device.publish_device_context(self.device_context)

    if "tts_voice" in updates:
      tts_voice = updates["tts_voice"]

      if tts_voice is not None:
        if hasattr(self, "tts") and self.tts:
          self.tts.current_voice = tts_voice

        if hasattr(self, "ha_device") and self.ha_device:
          self.ha_device.publish_voice_state(tts_voice)

        self._publish_discovery()

    await asyncio.to_thread(update_runtime_settings_cache, self.settings, **updates)
    apply_runtime_settings_cache(self.settings, read_runtime_settings_cache(self.settings))

  async def _geocode_retry_loop(self) -> None:
    """Periodically retries geocoding if it previously failed due to service unavailability."""
    from device.core.geocode import is_geocode_unavailable

    while not self.shutdown_event.is_set():
      try:
        await asyncio.sleep(self._geocode_retry_interval)
      except asyncio.CancelledError:
        break

      if self.shutdown_event.is_set():
        break

      location = self.settings.location
      if location and is_geocode_unavailable(location):
        logger.info(f"Retrying geocoding for location: {location}")
        try:
          new_context = await asyncio.to_thread(build_device_context, self.settings)
          if "latitude" in new_context:
            logger.info(f"Geocoding succeeded for location: {location}")
            self.device_context = new_context
            self.ha_device.publish_device_context(self.device_context)
            self._publish_discovery()
        except Exception as error:
          logger.error(f"Error during geocode retry: {error}")

  async def run(self) -> None:
    configure_logging(self.settings.log_level, self.settings.log_file)

    logger.info(f"{APP_NAME} v{APP_VERSION}")
    log_group(self.settings, "Server", "server_host", "server_port")
    log_group(self.settings, "Logging", "log_level", "log_file")
    log_group(self.settings, "Runtime", "node_id", "setting_path", "delay", "conversation_timeout")

    log_group(
      self.settings,
      "Preferences",
      "language",
      "location",
      "timezone",
      "temperature_unit",
      "preferred_currency",
      "measurement_system",
      "distance_unit",
      "time_format",
      "date_format",
      "first_day_of_week",
    )

    log_group(
      self.settings, "Microphone", "microphone_enabled", "microphone_device", "microphone_device_index", "microphone_muted"
    )

    log_group(self.settings, "Speaker", "speaker_enabled", "speaker_device", "speaker_muted", "speaker_volume")

    log_group(
      self.settings,
      "Wake Word & Sounds Detection",
      "ohunerin_threshold",
      "ohunerin_host",
      "ohunerin_port",
      "ohunerin_cert_file",
    )

    transcription_fields = (
      ("andika_model", "andika_samplerate", "andika_host", "andika_port", "andika_cert_file")
      if self.settings.transcription_backend == "andika"
      else ("whisper_url", "whisper_silence_threshold", "whisper_silence_duration")
    )

    log_group(self.settings, "Transcription", "transcription_backend", *transcription_fields)

    speech_fields = (
      ("izwi_url",)
      if self.settings.tts_backend == "izwi"
      else (
        "edge_tts_url",
        "edge_tts_api_key",
        "edge_tts_locale",
        "edge_tts_model",
        "edge_tts_response_format",
        "edge_tts_speed",
      )
    )

    log_group(self.settings, "Speech", "tts_backend", "tts_voice", *speech_fields)
    log_group(self.settings, "Orchestrator", "akorin_url")

    log_group(
      self.settings,
      "Connectivity",
      "mqtt_broker",
      "mqtt_port",
      "mqtt_username",
      "mqtt_password",
      "mqtt_topic",
      "mqtt_discovery",
      "mqtt_discovery_prefix",
    )

    self._setup_signals()

    self.audio = AudioService(self.settings)

    try:
      self.audio.initialize_hardware()
    except AudioDeviceError as error:
      logger.error(str(error))

    self.ha_device = HomeAssistantDevice(
      broker=self.settings.mqtt_broker,
      port=self.settings.mqtt_port,
      node_id=self.settings.node_id,
      topic=self.settings.mqtt_topic,
      username=self.settings.mqtt_username,
      password=self.settings.mqtt_password,
      discovery_prefix=self.settings.mqtt_discovery_prefix if self.settings.mqtt_discovery else None,
    )

    # 2. Init MCP server
    self.mcp = MCPServer(
      name="Oremi Device",
      instructions=(
        "Retrieve and manage local device settings, audio devices, and speech synthesis voices. "
        "Use get_device_status or read device:///status to check current state. "
        "Call update_device_settings to update device configuration such as volume and language."
      ),
      website_url=APP_DOCUMENTATION_URL,
    )

    mcp_device = McpDevice(self)

    register_mcp_tools(self.mcp, mcp_device)
    register_mcp_resources(self.mcp, mcp_device)
    register_mcp_prompts(self.mcp)

    # Start MCP server in background. The HTTP transport settings are runner
    # arguments in MCP 2.x (they were FastMCP constructor arguments in MCP 1.x);
    # the resulting endpoint and behavior are unchanged.
    self.background_tasks.append(
      self.loop.create_task(
        self.mcp.run_streamable_http_async(
          host=self.settings.server_host,
          port=self.settings.server_port,
          stateless_http=True,
          json_response=True,
          streamable_http_path="/mcp",
        )
      )
    )

    # Assume a TTS stub exists or inject the client here based on your original imports
    self.tts = TTSManager(self.settings)
    self.executor = CommandExecutor(self.audio, self.tts, self.ha_device, self.loop)

    # Load and configure components
    self.components = {}
    self.component_configs = {}

    component_config_inputs = {
      "ohunerin": {"threshold": self.settings.ohunerin_threshold},
      "andika": {"model": self.settings.andika_model, "samplerate": self.settings.andika_samplerate},
    }

    for comp_name, (load_config, create_component) in COMPONENTS.items():
      comp_config = (
        load_config.model_validate(component_config_inputs.get(comp_name))
        if comp_name in component_config_inputs
        else load_config()
      )

      self.component_configs[comp_name] = comp_config
      self.components[comp_name] = create_component(self.settings)

    # Define shared resources for components
    self.active_stream_container: ActiveStreamContainer = {"stream": self.audio.audio_stream}
    wakeword_event = asyncio.Event()

    async def cancel_active_processing() -> None:
      await self.executor.cancel_active()

    async def handle_final_transcription(text: str) -> None:
      self.queues["transcription"].put_nowait(text)

    async def handle_conversation_event(event: ConversationEvent) -> None:
      if event == "listening":
        self.ha_device.set_conversation_state("listening")
        await self.play_sound_cue("wakeword")
      elif event == "processing":
        self.ha_device.set_conversation_state("processing")
        await self.play_sound_cue("thinking")
      else:
        # cancelled / error / idle
        self.ha_device.set_conversation_state("idle")
        await self.play_sound_cue("sleep")

    self.shared_resources: SharedResources = {
      "active_stream_container": self.active_stream_container,
      "wakeword_event": wakeword_event,
      "device_state": self.audio.device_state,
      "handle_task_done": self._handle_task_done,
      "transcription_queue": self.queues["transcription"],
      "processing_queue": self.queues["processing"],
      "language_state": {"language": self.settings.language},
      "device_context": lambda: self.device_context,
      "conversation_event_handler": handle_conversation_event,
      "final_transcription_handler": handle_final_transcription,
      "sound_cue_handler": self.play_sound_cue,
      "cancel_active_processing": cancel_active_processing,
      "mqtt_publisher": self.ha_device,
    }

    # Start all components
    for comp_name, component in self.components.items():
      logger.info(f"Starting component: {comp_name}")
      await component.start(self.component_configs[comp_name], self.shared_resources)

    # 2. Wire up MQTT and Connect
    self._setup_mqtt_callbacks()
    self.ha_device.connect()
    self.ha_device.set_availability(True)

    # Fetch voices first so we have them for discovery
    if self.tts:
      res = self.tts.fetch_voices()

      if inspect.isawaitable(res):
        await res

      if self.tts.current_voice:
        self.ha_device.publish_voice_state(self.tts.current_voice)

    self._publish_discovery()

    # 3. Start Background Workers
    if self.audio.needs_audio:
      self.background_tasks.append(self.loop.create_task(self.audio.monitor_devices(self.queues["device_change"])))

    self.background_tasks.append(self.loop.create_task(self._event_loop_processor()))
    self.background_tasks.append(self.loop.create_task(self._geocode_retry_loop()))

    logger.info("Application is running. Waiting for shutdown signal.")

    # Play ready sound
    if self.audio.speaker:
      active_speaker = self.audio.speaker

      async def play_ready() -> None:
        try:
          await asyncio.to_thread(active_speaker.play_file, get_sound_cue_path("ready"))
        except Exception as exception:
          logger.warning(f"Failed to play ready sound: {exception}")

      self.loop.create_task(play_ready(), name="Ready Sound Task")

    # 4. Wait for termination
    await self.shutdown_event.wait()

    # 5. Graceful Teardown
    logger.info("Shutting down gracefully...")
    self.ha_device.set_availability(False)

    await self.executor.cancel_active()

    # Stop all components
    for component in self.components.values():
      await component.stop()

    # Play shutdown sound
    if self.audio.speaker:
      try:
        await asyncio.to_thread(self.audio.speaker.play_file, get_sound_cue_path("shutdown"))
      except Exception as e:
        logger.warning(f"Failed to play shutdown sound: {e}")

    for task in self.background_tasks:
      task.cancel()

    if self.background_tasks:
      await asyncio.gather(*self.background_tasks, return_exceptions=True)

    if self.audio.audio_stream:
      await asyncio.to_thread(self.audio.audio_stream.close)

    if self.audio.speaker:
      self.audio.speaker.stop()

    self.ha_device.disconnect()
