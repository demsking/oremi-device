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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from device.core.app import DeviceApplication
from device.core.mcp import McpDevice
from device.core.settings import Settings
from device.mcp.prompts import register_mcp_prompts
from device.mcp.resources import register_mcp_resources
from device.mcp.tools import register_mcp_tools

REQUIRED_SETTINGS = {
  "node_id": "test-node",
  "ohunerin_host": "localhost",
  "andika_host": "localhost",
  "mqtt_broker": "localhost",
}


@pytest.fixture
def temp_settings(tmp_path) -> Settings:
  # Using tmp_path as data directory so settings cache writes there
  return Settings(_env_file=None, data_path=tmp_path, **REQUIRED_SETTINGS)


@pytest.fixture
async def device_app(temp_settings) -> DeviceApplication:
  with patch("device.core.app.get_settings", return_value=temp_settings):
    app = DeviceApplication()
    app.audio = MagicMock()
    app.audio.change_audio_device = AsyncMock()
    app.audio.speaker = MagicMock()
    app.audio.speaker.device_name = "Built-in Speaker"
    app.audio.speaker.volume = 1.0
    app.audio.speaker.muted = False
    app.audio.speaker.set_volume = MagicMock(side_effect=lambda v: setattr(app.audio.speaker, "volume", v))
    app.audio.speaker.set_muted = MagicMock(side_effect=lambda m: setattr(app.audio.speaker, "muted", m))
    app.ha_device = MagicMock()
    app.tts = MagicMock()
    app.components = {}
    app._publish_discovery = MagicMock()
    return app


@pytest.fixture
async def mcp_device(device_app) -> McpDevice:
  return McpDevice(device_app)


@pytest.fixture
async def mcp_server(mcp_device) -> FastMCP:
  server = FastMCP(
    name="Oremi Device Test Server",
    instructions=(
      "Retrieve and manage local device settings, audio devices, and speech synthesis voices. "
      "Use get_device_status or read device:///status to check current state. "
      "Call update_device_settings to update device configuration such as volume and language."
    ),
  )

  register_mcp_tools(server, mcp_device)
  register_mcp_resources(server, mcp_device)
  register_mcp_prompts(server)

  return server


async def test_get_device_status_tool(mcp_server) -> None:
  # Call the get_device_status tool
  result = await mcp_server.call_tool("get_device_status", {})

  # result is a tuple of (text_content, structured_response)
  # Let's inspect structured_response
  _, structured = result

  assert structured["node_id"] == "test-node"
  assert structured["language"] == "fr"
  assert structured["microphone_muted"] is False
  assert structured["speaker_volume"] == 1.0


@patch("miniaudio.Devices")
async def test_list_audio_devices_tool(mock_devices, mcp_server) -> None:
  mock_devices.return_value.get_captures.return_value = [{"name": "Built-in Microphone", "id": 0}]
  mock_devices.return_value.get_playbacks.return_value = [{"name": "Built-in Speaker", "id": 1}]

  _, input_res = await mcp_server.call_tool("list_input_devices", {})
  _, output_res = await mcp_server.call_tool("list_output_devices", {})

  assert "Built-in Microphone" in input_res["devices"]
  assert "Built-in Speaker" in output_res["devices"]


async def test_list_voices_no_backend(mcp_server) -> None:
  # No TTS backend configured or running in temp_settings by default, so should return empty list
  _, structured = await mcp_server.call_tool("list_voices", {})
  assert structured == {"result": []}


@patch("httpx.AsyncClient.get")
async def test_list_voices_edge_tts(mock_get, mcp_server, temp_settings) -> None:
  temp_settings.tts_backend = "edge-tts"
  temp_settings.edge_tts_url = "http://localhost:5050"

  mock_response = MagicMock()
  mock_response.json.return_value = {
    "voices": [
      {"ShortName": "fr-FR-DeniseNeural", "FriendlyName": "Denise", "Locale": "fr-FR"},
      {"ShortName": "en-US-GuyNeural", "FriendlyName": "Guy", "Locale": "en-US"},
    ]
  }
  mock_get.return_value = mock_response

  _, structured = await mcp_server.call_tool("list_voices", {"language": "fr"})

  assert structured == {
    "result": [
      {
        "name": "fr-FR-DeniseNeural",
        "description": "Denise",
        "primary_language": "fr-FR",
        "id": None,
        "gender": None,
        "sample_rate": None,
      }
    ]
  }


async def test_update_device_settings_tool(mcp_server, temp_settings, tmp_path) -> None:
  # Call tool to update settings
  _, structured = await mcp_server.call_tool(
    "update_device_settings",
    {
      "language": "en",
      "location": "Paris",
      "speaker_volume": 0.5,
    },
  )

  assert structured["language"] == "en"
  assert structured["location"] == "Paris"
  assert structured["speaker_volume"] == 0.5

  # Check if setting is updated in memory
  assert temp_settings.language == "en"
  assert temp_settings.location == "Paris"
  assert temp_settings.speaker_volume == 0.5

  # Check if cache file is written
  cache_file = tmp_path / "test-node.json"
  assert cache_file.exists()
  cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
  assert cache_data["language"] == "en"
  assert cache_data["location"] == "Paris"
  assert cache_data["speaker_volume"] == 0.5


async def test_update_device_settings_invalid_volume(mcp_server) -> None:
  with pytest.raises(ToolError, match=r"volume must be a float between 0\.0 and 1\.0"):
    await mcp_server.call_tool("update_device_settings", {"speaker_volume": 1.5})


async def test_update_device_settings_no_updates(mcp_server) -> None:
  with pytest.raises(ToolError, match="No settings were provided to update"):
    await mcp_server.call_tool("update_device_settings", {})


async def test_mcp_resources(mcp_server) -> None:
  # Test list_resources
  resources = await mcp_server.list_resources()
  resource_uris = [str(r.uri) for r in resources]
  assert "device:///status" in resource_uris
  assert "device:///settings" in resource_uris

  # Test read_resource status
  status_content = await mcp_server.read_resource("device:///status")
  assert status_content is not None
  assert "test-node" in status_content[0].content

  # Test read_resource settings
  settings_content = await mcp_server.read_resource("device:///settings")
  assert settings_content is not None
  assert "fr" in settings_content[0].content


async def test_mcp_prompts(mcp_server) -> None:
  # Test list_prompts
  prompts = await mcp_server.list_prompts()
  prompt_names = [p.name for p in prompts]
  assert "configure_device" in prompt_names
  assert "adjust_audio" in prompt_names

  # Test configure_device prompt
  result_conf = await mcp_server.get_prompt("configure_device", {"language": "en", "location": "New York"})
  assert len(result_conf.messages) == 1
  assert "Set language to 'en'" in result_conf.messages[0].content.text
  assert "Set location to 'New York'" in result_conf.messages[0].content.text

  # Test adjust_audio prompt
  result_audio = await mcp_server.get_prompt("adjust_audio", {"volume": 80, "mute_speaker": True})
  assert len(result_audio.messages) == 1
  assert "Set speaker volume to 80%" in result_audio.messages[0].content.text
  assert "Mute the speaker" in result_audio.messages[0].content.text


def test_mcp_server_initialization_settings(temp_settings) -> None:
  server = FastMCP(
    name="Oremi Device",
    instructions="Test instructions",
    host=temp_settings.server_host,
    port=temp_settings.server_port,
    streamable_http_path="/mcp",
  )
  assert server.name == "Oremi Device"
  assert server.settings.host == "127.0.0.1"
  assert server.settings.port == 5048
  assert server.settings.streamable_http_path == "/mcp"
  assert server._mcp_server.instructions == "Test instructions"


@patch("miniaudio.Devices")
async def test_new_media_and_device_tools(mock_devices, mcp_server, temp_settings, device_app) -> None:
  mock_devices.return_value.get_captures.return_value = [{"name": "Built-in Microphone", "id": 0}]
  mock_devices.return_value.get_playbacks.return_value = [{"name": "Built-in Speaker", "id": 1}]

  # Test list_output_devices
  _, output_devices = await mcp_server.call_tool("list_output_devices", {})
  assert "Built-in Speaker" in output_devices["devices"]

  # Test list_input_devices
  _, input_devices = await mcp_server.call_tool("list_input_devices", {})
  assert "Built-in Microphone" in input_devices["devices"]

  # Test set_active_input_device
  _, res = await mcp_server.call_tool("set_active_input_device", {"device_name": "Built-in Microphone"})
  assert res["active_input_device"] == "Built-in Microphone"

  # Test set_active_output_device
  _, res = await mcp_server.call_tool("set_active_output_device", {"device_name": "Built-in Speaker"})
  assert res["active_output_device"] == "Built-in Speaker"

  # Test enqueue
  _, res = await mcp_server.call_tool(
    "enqueue", {"url": "http://example.com/stream.mp3", "title": "Song 1", "artist": "Artist 1"}
  )
  assert res["status"] == "success"
  assert res["enqueued_index"] == 0
  assert res["item"]["title"] == "Song 1"

  # Test get_queue
  _, queue = await mcp_server.call_tool("get_queue", {})
  assert len(queue["items"]) == 1
  assert queue["items"][0]["title"] == "Song 1"

  # Test get_now_playing
  _, now_playing = await mcp_server.call_tool("get_now_playing", {})
  assert now_playing["title"] is None  # not playing yet

  # Test play
  _, res = await mcp_server.call_tool("play", {})
  assert res["status"] == "success"

  # Test pause
  _, res = await mcp_server.call_tool("pause", {})
  assert res["status"] == "success"
  assert res["now_playing"]["is_paused"] is True

  # Test resume
  _, res = await mcp_server.call_tool("resume", {})
  assert res["status"] == "success"

  # Test seek
  _, res = await mcp_server.call_tool("seek", {"position": 30.0})
  assert res["position"] == 30.0

  # Test get_volume and set_volume
  _, res = await mcp_server.call_tool("set_volume", {"volume": 0.8})
  assert res["volume"] == 0.8
  _, vol = await mcp_server.call_tool("get_volume", {})
  assert vol["volume"] == 0.8

  # Test mute / unmute
  _, res = await mcp_server.call_tool("mute", {})
  assert res["muted"] is True
  _, res = await mcp_server.call_tool("unmute", {})
  assert res["muted"] is False

  # Test play_url
  _, res = await mcp_server.call_tool("play_url", {"url": "http://example.com/track2.mp3", "title": "Song 2"})
  assert res["status"] == "success"
  assert res["now_playing"]["title"] == "Song 2"
  await asyncio.sleep(0.1)
  device_app.audio.speaker.play_url.assert_called_with("http://example.com/track2.mp3")

  # Test remove_from_queue
  _, res = await mcp_server.call_tool("remove_from_queue", {"index": 0})
  assert res["status"] == "success"
  assert res["removed_item"]["title"] == "Song 2"

  # Test clear_queue
  _, res = await mcp_server.call_tool("clear_queue", {})
  assert res["status"] == "success"
  assert res["queue"] == []

  # Test get_device_capabilities
  _, caps = await mcp_server.call_tool("get_device_capabilities", {})
  assert caps["can_play_audio"] is True

  # Test sleep_timer
  _, res = await mcp_server.call_tool("sleep_timer", {"duration_minutes": 10})
  assert res["sleep_timer_minutes"] == 10


@patch("miniaudio.Devices")
async def test_new_mcp_resources(mock_devices, mcp_server) -> None:
  mock_devices.return_value.get_playbacks.return_value = [{"name": "Built-in Speaker", "id": 1}]

  # test device:///speakers
  res = await mcp_server.read_resource("device:///speakers")
  assert res is not None
  assert "Built-in Speaker" in res[0].content

  # test device:///playing
  res = await mcp_server.read_resource("device:///playing")
  assert res is not None
  assert "is_playing" in res[0].content

  # test device:///queue
  res = await mcp_server.read_resource("device:///queue")
  assert res is not None

  # test device:///volume
  res = await mcp_server.read_resource("device:///volume")
  assert res is not None
  assert "volume" in res[0].content

  # test device:///capabilities
  res = await mcp_server.read_resource("device:///capabilities")
  assert res is not None
  assert "can_play_audio" in res[0].content

  # test device:///settings
  res = await mcp_server.read_resource("device:///settings")
  assert res is not None
  assert "language" in res[0].content


async def test_new_mcp_prompts(mcp_server) -> None:
  prompts = await mcp_server.list_prompts()
  prompt_names = [p.name for p in prompts]

  # Check all required prompt names are registered
  required_names = [
    "play_media",
    "pause_playback",
    "resume_playback",
    "stop_playback",
    "next_track",
    "previous_track",
    "restart_track",
    "set_volume",
    "increase_volume",
    "decrease_volume",
    "mute_speaker",
    "unmute_speaker",
    "speaker_status",
    "what's_playing",
    "sleep_timer",
  ]
  for name in required_names:
    assert name in prompt_names

  # Test a few prompts specifically
  res = await mcp_server.get_prompt("play_media", {"url": "http://test.mp3"})
  assert "http://test.mp3" in res.messages[0].content.text

  res = await mcp_server.get_prompt("set_volume", {"volume": 75})
  assert "75%" in res.messages[0].content.text

  res = await mcp_server.get_prompt("sleep_timer", {"duration_minutes": 20})
  assert "20 minutes" in res.messages[0].content.text


async def test_mcp_mutation_tools_apply_on_device_application(mcp_device) -> None:
  app = mcp_device.app
  app.audio = MagicMock()
  app.audio.speaker = MagicMock()
  app.ha_device = MagicMock()
  app.tts = MagicMock()
  app.components = {}
  app._publish_discovery = MagicMock()

  server = FastMCP(name="App Mutation Test Server")
  register_mcp_tools(server, mcp_device)

  # Test volume mutation via MCP tool
  await server.call_tool("set_volume", {"volume": 0.75})
  assert app.settings.speaker_volume == 0.75
  app.audio.speaker.set_volume.assert_called_with(0.75)
  app.ha_device.set_speaker_volume_state.assert_called_with(0.75)
  assert app._publish_discovery.call_count >= 1

  # Test mute mutation via MCP tool
  await server.call_tool("mute", {})
  assert app.settings.speaker_muted is True
  app.audio.speaker.set_muted.assert_called_with(True)
  app.ha_device.set_speaker_mute_state.assert_called_with(True)

  # Test unmute mutation via MCP tool
  await server.call_tool("unmute", {})
  assert app.settings.speaker_muted is False
  app.audio.speaker.set_muted.assert_called_with(False)
  app.ha_device.set_speaker_mute_state.assert_called_with(False)

  # Test output device mutation via MCP tool
  await server.call_tool("set_active_output_device", {"device_name": "USB Audio Speaker"})
  assert app.settings.speaker_device == "USB Audio Speaker"
  app.audio.speaker.select_device.assert_called_with("USB Audio Speaker")
  app.ha_device.set_speaker_state.assert_called_with("USB Audio Speaker")

  # Test update_device_settings mutation via MCP tool
  await server.call_tool("update_device_settings", {"language": "en", "location": "Douala", "speaker_volume": 0.4})
  assert app.settings.language == "en"
  assert app.settings.location == "Douala"
  assert app.settings.speaker_volume == 0.4
  app.ha_device.publish_language_state.assert_called_with("en")
  app.audio.speaker.set_volume.assert_called_with(0.4)
