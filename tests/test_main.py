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
