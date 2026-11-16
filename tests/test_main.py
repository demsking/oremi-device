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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from device.core.app import parse_device_context_command_field
from device.core.app import validate_device_context_value


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


@pytest.mark.asyncio
async def test_ready_and_shutdown_sounds_played() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    language="fr",
    delay=3,
    conversation_timeout=15,
    ohunerin_host="localhost",
    ohunerin_port=5023,
    andika_host="localhost",
    andika_port=5022,
    andika_cert_file=None,
    ohunerin_cert_file=None,
    ohunerin_threshold=0.65,
    andika_model="zhifeixie/Mega-ASR",
    andika_samplerate=16000,
    microphone_device_index=None,
    microphone_device=None,
    mqtt_broker="localhost",
    mqtt_port=1883,
    mqtt_topic="oremi/test",
    mqtt_username=None,
    mqtt_password=None,
    mqtt_discovery_prefix="homeassistant",
    mqtt_discovery=False,
    microphone_enabled=True,
    speaker_enabled=True,
  )

  with (
    patch("device.core.app.get_settings", return_value=fake_settings),
    patch("device.core.app.AudioService") as mock_audio_service_cls,
    patch("device.core.app.HomeAssistantDevice") as mock_mqtt_cls,
    patch("device.core.app.MCPServer") as mock_mcp_cls,
    patch("device.core.app.TTSManager"),
    patch("device.core.app.CommandExecutor") as mock_executor_cls,
  ):
    mock_audio_service = mock_audio_service_cls.return_value
    mock_audio_service.needs_audio = True
    mock_audio_service.speaker_enabled = True
    mock_speaker = MagicMock()
    mock_audio_service.speaker = mock_speaker
    mock_audio_service.audio_stream = MagicMock()
    mock_audio_service.monitor_devices.return_value = asyncio.sleep(0)

    mock_mqtt = mock_mqtt_cls.return_value
    mock_mqtt.connect = MagicMock()
    mock_mqtt.set_availability = MagicMock()
    mock_mqtt.disconnect = MagicMock()
    mock_mqtt.client.connect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt.client.disconnect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt.client.message_callback = MagicMock(return_value=lambda f: f)

    mock_mcp = mock_mcp_cls.return_value
    mock_mcp.run_streamable_http_async.return_value = asyncio.sleep(0)

    mock_executor = mock_executor_cls.return_value
    mock_executor.cancel_active = AsyncMock()

    app = DeviceApplication()
    run_task = asyncio.create_task(app.run())

    await asyncio.sleep(0.1)
    app.shutdown_event.set()
    await run_task

    assert mock_speaker.play_file.call_count == 2
    calls = mock_speaker.play_file.call_args_list
    ready_path = calls[0][0][0]
    shutdown_path = calls[1][0][0]
    assert ready_path.name == "ready.ogg"
    assert shutdown_path.name == "shutdown.ogg"

    # MCP 2.x receives the HTTP transport settings through the runner, and the
    # resulting endpoint/options are unchanged from the MCP 1.x configuration.
    mock_mcp.run_streamable_http_async.assert_called_once_with(
      host=fake_settings.server_host,
      port=fake_settings.server_port,
      stateless_http=True,
      json_response=True,
      streamable_http_path="/mcp",
    )

    # The MCP task is cleaned up with the application background tasks.
    assert app.background_tasks
    assert all(task.done() for task in app.background_tasks)


@pytest.mark.asyncio
async def test_geocode_background_retry(monkeypatch: pytest.MonkeyPatch) -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings
  from geopy.exc import GeocoderUnavailable
  from device.core.geocode import _unavailable_locations

  _unavailable_locations.clear()

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    language="fr",
    delay=3,
    conversation_timeout=15,
    location="Paris, France",
    ohunerin_host="localhost",
    ohunerin_port=5023,
    andika_host="localhost",
    andika_port=5022,
    andika_cert_file=None,
    ohunerin_cert_file=None,
    ohunerin_threshold=0.65,
    andika_model="zhifeixie/Mega-ASR",
    andika_samplerate=16000,
    microphone_device_index=None,
    microphone_device=None,
    mqtt_broker="localhost",
    mqtt_port=1883,
    mqtt_topic="oremi/test",
    mqtt_username=None,
    mqtt_password=None,
    mqtt_discovery_prefix="homeassistant",
    mqtt_discovery=False,
    microphone_enabled=True,
    speaker_enabled=True,
  )

  # Initially, geocoder raises GeocoderUnavailable, then succeeds on retry
  geocode_calls = []

  def mock_geocode(location: str):
    geocode_calls.append(location)
    if len(geocode_calls) <= 2:
      raise GeocoderUnavailable("Down")
    return SimpleNamespace(latitude=48.8566, longitude=2.3522, address="Paris, France")

  from types import SimpleNamespace
  from device.core.geocode import get_location_geocode

  monkeypatch.setattr("device.core.settings.get_location_geocode", get_location_geocode)
  monkeypatch.setattr("device.core.geocode._geocoder", SimpleNamespace(geocode=mock_geocode))

  with (
    patch("device.core.app.get_settings", return_value=fake_settings),
    patch("device.core.app.AudioService") as mock_audio_service_cls,
    patch("device.core.app.HomeAssistantDevice") as mock_mqtt_cls,
    patch("device.core.app.MCPServer") as mock_mcp_cls,
    patch("device.core.app.TTSManager"),
    patch("device.core.app.CommandExecutor") as mock_executor_cls,
  ):
    mock_audio_service = mock_audio_service_cls.return_value
    mock_audio_service.needs_audio = True
    mock_audio_service.speaker_enabled = True
    mock_audio_service.speaker = MagicMock()
    mock_audio_service.audio_stream = MagicMock()
    mock_audio_service.monitor_devices.return_value = asyncio.sleep(0)

    mock_mqtt = mock_mqtt_cls.return_value
    mock_mqtt.connect = MagicMock()
    mock_mqtt.set_availability = MagicMock()
    mock_mqtt.disconnect = MagicMock()
    mock_mqtt.client.connect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt.client.disconnect_callback = MagicMock(return_value=lambda f: f)
    mock_mqtt.client.message_callback = MagicMock(return_value=lambda f: f)

    mock_mcp = mock_mcp_cls.return_value
    mock_mcp.run_streamable_http_async.return_value = asyncio.sleep(0)

    mock_executor = mock_executor_cls.return_value
    mock_executor.cancel_active = AsyncMock()

    app = DeviceApplication()
    # Check that geocoding wasn't successful initially (no lat/lng keys in context)
    assert "latitude" not in app.device_context

    # Speed up retry loop for testing
    app._geocode_retry_interval = 0.05

    run_task = asyncio.create_task(app.run())

    # Wait for the background retry task to run and succeed
    await asyncio.sleep(0.3)

    assert "latitude" in app.device_context
    assert app.device_context["latitude"] == 48.8566
    assert app.device_context["longitude"] == 2.3522

    # Verify context update was published
    assert mock_mqtt.publish_device_context.called

    app.shutdown_event.set()
    await run_task


@pytest.mark.asyncio
async def test_handle_event_calls_apply_settings_updates() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    language="fr",
    delay=3,
    conversation_timeout=15,
    ohunerin_host="localhost",
    ohunerin_port=5023,
    andika_host="localhost",
    andika_port=5022,
    andika_cert_file=None,
    ohunerin_cert_file=None,
    ohunerin_threshold=0.65,
    andika_model="zhifeixie/Mega-ASR",
    andika_samplerate=16000,
    microphone_device_index=None,
    microphone_device=None,
    mqtt_broker="localhost",
    mqtt_port=1883,
    mqtt_topic="oremi/test",
    mqtt_username=None,
    mqtt_password=None,
    mqtt_discovery_prefix="homeassistant",
    mqtt_discovery=False,
    microphone_enabled=True,
    speaker_enabled=True,
  )

  with (
    patch("device.core.app.get_settings", return_value=fake_settings),
    patch("device.core.app.AudioService"),
    patch("device.core.app.HomeAssistantDevice"),
    patch("device.core.app.MCPServer"),
    patch("device.core.app.TTSManager"),
    patch("device.core.app.CommandExecutor"),
  ):
    app = DeviceApplication()
    app.apply_settings_updates = AsyncMock()

    await app._handle_event("device_change", "mic_1")
    app.apply_settings_updates.assert_called_once_with({"microphone_device": "mic_1"})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("microphone_mute", True)
    app.apply_settings_updates.assert_called_once_with({"microphone_muted": True})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("speaker_change", "spk_1")
    app.apply_settings_updates.assert_called_once_with({"speaker_device": "spk_1"})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("speaker_mute", True)
    app.apply_settings_updates.assert_called_once_with({"speaker_muted": True})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("speaker_volume", 80)
    app.apply_settings_updates.assert_called_once_with({"speaker_volume": 80})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("language_change", "en")
    app.apply_settings_updates.assert_called_once_with({"language": "en"})
    app.apply_settings_updates.reset_mock()

    await app._handle_event("device_context_change", ("timezone", "Africa/Douala"))
    app.apply_settings_updates.assert_called_once_with({"timezone": "Africa/Douala"})


@pytest.mark.asyncio
async def test_publish_discovery_does_not_block_event_loop(tmp_path) -> None:
  import threading
  import time

  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    data_path=tmp_path,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.audio.speaker_enabled = True
  app.audio.audio_stream = None
  app.audio.speaker_state = {}
  app.tts = MagicMock()
  app.tts.get_active_voice_names.return_value = []
  app.tts.current_voice = ""
  app.ha_device = MagicMock()
  app.ha_device.discovery_prefix = "homeassistant"
  app.device_context = {}

  started = threading.Event()
  ohunerin = MagicMock()

  def blocking_sounds() -> list[str]:
    started.set()
    time.sleep(0.2)
    return ["wake"]

  def blocking_input(**kwargs) -> list[str]:
    time.sleep(0.1)
    return ["microphone"]

  def blocking_output() -> list[str]:
    time.sleep(0.1)
    return ["speaker"]

  ohunerin.get_supported_sounds.side_effect = blocking_sounds
  app.components = {"ohunerin": ohunerin}

  stop = asyncio.Event()
  ticks = 0

  async def heartbeat() -> None:
    nonlocal ticks
    while not stop.is_set():
      await asyncio.sleep(0.005)
      ticks += 1

  hb = asyncio.create_task(heartbeat())

  with (
    patch("device.core.audio.Audio.get_compatible_input_devices", side_effect=blocking_input),
    patch("device.core.speaker.Speaker.get_compatible_output_devices", side_effect=blocking_output),
  ):
    await app._publish_discovery()

  stop.set()
  await hb

  # The blocking HTTP lookup and device enumeration run in a worker thread, so
  # the event loop keeps ticking (~80 ticks in 400 ms) instead of stalling.
  assert started.is_set()
  assert ticks >= 5
  app.ha_device.publish_discovery_configs.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_service_enabled() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.apply_settings_updates = AsyncMock()

  await app._handle_event("service_enabled", ("sound-detection", False))
  app.apply_settings_updates.assert_awaited_once_with({"sound_detection_enabled": False})
  app.apply_settings_updates.reset_mock()

  await app._handle_event("service_enabled", ("voice-assistant", False))
  app.apply_settings_updates.assert_awaited_once_with({"andika_enabled": False})


@pytest.mark.asyncio
async def test_load_components_keeps_wakeword_but_skips_disabled_voice_assistant() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
    speaker_enabled=False,
    sound_detection_enabled=False,
    andika_enabled=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.tts = MagicMock()
  app.tts.client = None
  app._load_components()

  assert "ohunerin" in app.components
  assert app.component_configs["ohunerin"].features == ["wakeword-detection"]
  assert "andika" not in app.components
  assert app.service_states["ohunerin"].enabled is True
  assert app.service_states["ohunerin"].status == "starting"
  assert app.service_states["andika"].enabled is False
  assert app.service_states["andika"].status == "disabled"
  assert app.service_states["tts"].enabled is False


@pytest.mark.asyncio
async def test_load_components_keeps_audio_services_muted() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
    microphone_muted=True,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.tts = MagicMock()
  app.tts.client = None
  app._load_components()

  assert "ohunerin" not in app.components
  assert "andika" not in app.components
  assert app.service_states["ohunerin"].enabled is True
  assert app.service_states["ohunerin"].status == "muted"
  assert app.service_states["andika"].enabled is True
  assert app.service_states["andika"].status == "muted"


@pytest.mark.asyncio
async def test_set_component_enabled_starts_and_stops() -> None:
  from device.core.app import DeviceApplication
  from device.core.components import ServiceState
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.ha_device = MagicMock()
  app.shared_resources = {}
  app.service_states = {"andika": ServiceState(enabled=False, status="disabled")}
  app.components = {}
  app.component_configs = {}
  app._publish_discovery = AsyncMock()

  component = MagicMock()
  component.start = AsyncMock()
  component.stop = AsyncMock()
  config = MagicMock()
  load_config = MagicMock()
  load_config.model_validate.return_value = config
  registry = {"andika": (load_config, MagicMock(return_value=component))}

  with patch.dict("device.core.app.COMPONENTS", registry, clear=True):
    await app._set_component_enabled("andika", True)

  assert app.settings.andika_enabled is True
  assert app.service_states["andika"].enabled is True
  assert app.components["andika"] is component
  component.bind_status_reporter.assert_called_once_with(app._set_service_status)
  component.start.assert_awaited_once_with(config, app.shared_resources)
  app.ha_device.publish_service_enabled_state.assert_called_once_with("voice-assistant", True)
  app._publish_discovery.assert_awaited_once()

  await app._set_component_enabled("andika", False)

  assert app.settings.andika_enabled is False
  assert app.service_states["andika"].enabled is False
  assert "andika" not in app.components
  component.stop.assert_awaited_once()
  app.ha_device.publish_service_enabled_state.assert_called_with("voice-assistant", False)
  assert app._publish_discovery.await_count == 2


@pytest.mark.asyncio
async def test_handle_voice_error_speaks_error() -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    language="fr",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.play_sound_cue = AsyncMock()
  app.executor = MagicMock()
  app.executor.execute_response = AsyncMock()

  await app.handle_voice_error()

  app.play_sound_cue.assert_awaited_once_with("error")
  response = app.executor.execute_response.await_args.args[0]
  assert response.commands[0].type == "announce"
  assert "comprendre" in response.commands[0].text
  assert "réessayer" in response.commands[0].text


@pytest.mark.asyncio
async def test_sound_detection_toggle_restarts_wakeword_service() -> None:
  from device.core.app import DeviceApplication
  from device.core.components import ServiceState
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.ha_device = MagicMock()
  app.shared_resources = {}
  app.service_states = {"ohunerin": ServiceState(enabled=True, status="online")}
  old_component = MagicMock()
  old_component.stop = AsyncMock()
  new_component = MagicMock()
  new_component.start = AsyncMock()
  new_config = MagicMock()
  app.components = {"ohunerin": old_component}
  app.component_configs = {"ohunerin": MagicMock()}
  app._create_component_config = MagicMock(return_value=new_config)
  app._publish_discovery = AsyncMock()

  with patch.dict(
    "device.core.app.COMPONENTS",
    {"ohunerin": (MagicMock(), MagicMock(return_value=new_component))},
    clear=True,
  ):
    await app._set_sound_detection_enabled(False)

  assert app.settings.sound_detection_enabled is False
  old_component.stop.assert_awaited_once()
  new_component.start.assert_awaited_once_with(new_config, app.shared_resources)
  app.ha_device.publish_service_enabled_state.assert_called_once_with("ambient-sound", False)
  app._publish_discovery.assert_awaited_once()


@pytest.mark.asyncio
async def test_microphone_mute_stops_and_restarts_voice_services() -> None:
  from device.core.app import DeviceApplication
  from device.core.components import ServiceState
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.audio.speaker_enabled = True
  app.audio.device_state = {}
  app.ha_device = MagicMock()
  app.shared_resources = {}
  app.service_states = {
    "ohunerin": ServiceState(enabled=True, status="online"),
    "andika": ServiceState(enabled=True, status="idle"),
  }
  app.components = {"ohunerin": MagicMock(), "andika": MagicMock()}
  app.component_configs = {"ohunerin": MagicMock(), "andika": MagicMock()}

  for component in app.components.values():
    component.stop = AsyncMock()

  app._publish_discovery = AsyncMock()
  app._publish_service_statuses = MagicMock()

  await app._apply_microphone_muted(True)

  assert app.settings.microphone_muted is True
  assert app.audio.device_state["microphone_muted"] is True
  assert app.components == {}
  assert app.service_states["ohunerin"].status == "muted"
  assert app.service_states["andika"].status == "muted"
  app.ha_device.set_mute_state.assert_called_once_with(True)
  app._publish_service_statuses.assert_called_once()

  first_ohunerin = MagicMock()
  first_ohunerin.start = AsyncMock()
  first_andika = MagicMock()
  first_andika.start = AsyncMock()
  factories = {
    "ohunerin": (MagicMock(), MagicMock(return_value=first_ohunerin)),
    "andika": (MagicMock(), MagicMock(return_value=first_andika)),
  }

  with patch.dict("device.core.app.COMPONENTS", factories, clear=True):
    await app._apply_microphone_muted(False)

  assert app.settings.microphone_muted is False
  assert app.audio.device_state["microphone_muted"] is False
  assert set(app.components) == {"ohunerin", "andika"}
  assert app.service_states["ohunerin"].status == "starting"
  assert app.service_states["andika"].status == "starting"
  first_ohunerin.start.assert_awaited_once()
  first_andika.start.assert_awaited_once()
  app._publish_discovery.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_select_sentinel_is_not_persisted_as_microphone(tmp_path) -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import read_runtime_settings_cache
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
    microphone_device="eMeet Luna Mono",
    data_path=tmp_path,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.audio.audio_stream = None
  app.audio.change_audio_device = AsyncMock(return_value=True)
  app.ha_device = MagicMock()
  app.active_stream_container = {"stream": None}
  app.components = {}
  app._publish_discovery = AsyncMock()

  await app.apply_settings_updates({"microphone_device": "__auto_select__"})

  assert app.settings.microphone_device is None
  assert read_runtime_settings_cache(fake_settings).microphone_device is None


@pytest.mark.asyncio
async def test_language_change_updates_shared_language_state_while_muted(tmp_path) -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
    microphone_muted=True,
    data_path=tmp_path,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.ha_device = MagicMock()
  app.tts = MagicMock()
  app.components = {}
  app.shared_resources = {"language_state": {"language": "fr"}}
  app._publish_discovery = AsyncMock()

  await app.apply_settings_updates({"language": "en"})

  assert app.shared_resources["language_state"]["language"] == "en"


@pytest.mark.asyncio
async def test_service_toggle_is_persisted(tmp_path) -> None:
  from device.core.app import DeviceApplication
  from device.core.settings import read_runtime_settings_cache
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
    data_path=tmp_path,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app._set_sound_detection_enabled = AsyncMock()

  await app.apply_settings_updates({"sound_detection_enabled": False})

  app._set_sound_detection_enabled.assert_awaited_once_with(False)
  assert read_runtime_settings_cache(fake_settings).sound_detection_enabled is False


@pytest.mark.asyncio
async def test_publish_service_statuses() -> None:
  from datetime import datetime
  from datetime import timezone
  from device.core.app import DeviceApplication
  from device.core.components import ServiceState
  from device.core.settings import Settings

  fake_settings = Settings(
    _env_file=None,
    node_id="test-node",
    ohunerin_host="localhost",
    andika_host="localhost",
    mqtt_broker="localhost",
    mqtt_discovery=False,
  )

  with patch("device.core.app.get_settings", return_value=fake_settings):
    app = DeviceApplication()

  app.audio = MagicMock()
  app.audio.needs_audio = True
  app.audio.speaker_enabled = True
  app.ha_device = MagicMock()
  app.started_at = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
  app.service_states = {
    "ohunerin": ServiceState(enabled=True, status="online"),
    "andika": ServiceState(enabled=True, status="idle"),
    "akorin": ServiceState(enabled=True, status="idle"),
    "tts": ServiceState(enabled=True, status="online"),
  }

  app._publish_service_statuses()

  published = {call.args[0]: call.args[1:] for call in app.ha_device.publish_service_status.call_args_list}
  assert published["ohunerin"] == ("online",)
  assert app.ha_device.publish_service_status.call_count == 4
  app.ha_device.publish_device_status.assert_called_once_with(
    "running",
    started_at="2026-11-16T08:00:00+00:00",
  )
