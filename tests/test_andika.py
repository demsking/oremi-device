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
import wave
from array import array
from io import BytesIO
from unittest.mock import ANY
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from oremi_device.components import COMPONENTS
from oremi_device.components.andika import AndikaComponent
from oremi_device.components.andika import AndikaTranscriber
from oremi_device.components.andika import WhisperCppListener
from oremi_device.core.models import AndikaConfig
from oremi_device.core.settings import DeviceSettings


class AsyncMessages:
  def __init__(self, messages: list[str]) -> None:
    self.messages = messages

  async def __aiter__(self):
    for message in self.messages:
      yield message


class DelayedAsyncMessages:
  def __init__(self, messages: list[tuple[float, str]]) -> None:
    self.messages = messages

  async def __aiter__(self):
    for delay, message in self.messages:
      await asyncio.sleep(delay)
      yield message


def _make_settings(**kwargs) -> DeviceSettings:
  defaults = {
    "node_id": "test-node",
    "language": "fr",
    "delay": 3,
    "conversation_timeout": 15,
    "ohunerin_host": "localhost",
    "ohunerin_port": 5023,
    "andika_host": "andika",
    "andika_port": 5315,
    "cert_file": None,
    "mqtt_broker": "mqtt",
  }
  defaults.update(kwargs)
  return DeviceSettings(_env_file=None, **defaults)


def test_andika_component_registered() -> None:
  config_model, component_model = COMPONENTS["andika"]

  assert config_model is AndikaConfig
  assert component_model is AndikaComponent


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_partial_results() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"partial": "bon", "confidence": 0.9})])
  transcriber = AndikaTranscriber(_make_settings(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_called_once_with(
    "transcription/partial",
    json.dumps({"partial": "bon", "confidence": 0.9}),
    qos=1,
    retain=False,
    props=ANY,
  )
  assert mqtt_client.publish_event.call_args.kwargs["props"].MessageExpiryInterval == 3


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_final_results() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"text": "bonjour oremi", "confidence": 0.9})])
  transcription_complete_event = asyncio.Event()
  conversation_events = []

  async def handle_conversation_event(event: str) -> None:
    conversation_events.append(event)

  transcriber = AndikaTranscriber(
    _make_settings(),
    mqtt_client,
    websocket,
    transcription_complete_event,
    handle_conversation_event,
  )

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_called_once_with(
    "transcription/result",
    json.dumps({"text": "bonjour oremi", "confidence": 0.9}),
    qos=1,
    retain=False,
    props=ANY,
  )
  assert transcription_complete_event.is_set()
  assert conversation_events == ["processing"]


@pytest.mark.asyncio
async def test_andika_transcriber_trims_final_text() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"text": " bonjour oremi\n", "confidence": 0.9})])

  await AndikaTranscriber(_make_settings(), mqtt_client, websocket).transcribing()

  mqtt_client.publish_event.assert_called_once_with(
    "transcription/result",
    json.dumps({"text": "bonjour oremi", "confidence": 0.9}),
    qos=1,
    retain=False,
    props=ANY,
  )


@pytest.mark.asyncio
async def test_andika_transcriber_uses_fixed_topics() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"partial": "bon"}), json.dumps({"text": "bonjour"})])

  await AndikaTranscriber(_make_settings(), mqtt_client, websocket).transcribing()

  assert [call.args[0] for call in mqtt_client.publish_event.call_args_list] == [
    "transcription/partial",
    "transcription/result",
  ]
  assert [json.loads(call.args[1]) for call in mqtt_client.publish_event.call_args_list] == [
    {"partial": "bon"},
    {"text": "bonjour"},
  ]


def test_andika_discovery_uses_final_result_topic() -> None:
  component = AndikaComponent(_make_settings())

  _, _, payload = component.ha_entities(
    "test-node",
    "oremi/device/nodes/test-node",
    "oremi/device/nodes/test-node/available",
    {},
  )[0]

  assert payload["state_topic"] == "oremi/device/nodes/test-node/transcription/result"
  assert payload["availability_topic"] == "oremi/device/nodes/test-node/available"
  assert payload["value_template"] == "{{ value_json.text }}"


@pytest.mark.asyncio
async def test_andika_empty_final_result_completes_conversation() -> None:
  mqtt_client = MagicMock()
  transcription_complete_event = asyncio.Event()
  conversation_events = []

  async def handle_conversation_event(event: str) -> None:
    conversation_events.append(event)

  transcriber = AndikaTranscriber(
    _make_settings(),
    mqtt_client,
    AsyncMessages([json.dumps({"text": ""})]),
    transcription_complete_event,
    handle_conversation_event,
  )

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_not_called()
  assert transcription_complete_event.is_set()
  assert conversation_events == ["cancelled"]


@pytest.mark.asyncio
async def test_andika_listens_only_between_wakeword_and_final_transcription() -> None:
  component = AndikaComponent(_make_settings())
  component._wakeword_event = asyncio.Event()  # noqa: SLF001
  listening = asyncio.Event()
  cue_started = asyncio.Event()
  cue_finished = asyncio.Event()

  async def handle_conversation_event(event: str) -> None:
    if event == "listening":
      cue_started.set()
      await cue_finished.wait()

  component._conversation_event_handler = handle_conversation_event  # noqa: SLF001

  class AudioListenerStub:
    def __init__(self) -> None:
      self.call_count = 0

    async def listening(self) -> None:
      self.call_count += 1
      listening.set()
      await asyncio.Event().wait()

  audio_listener = AudioListenerStub()
  component.audio_listener = audio_listener
  activation_task = asyncio.create_task(component._activate_on_wakeword({"stream": MagicMock()}))  # noqa: SLF001

  await asyncio.sleep(0)
  assert audio_listener.call_count == 0

  component._wakeword_event.set()  # noqa: SLF001
  await asyncio.wait_for(cue_started.wait(), timeout=1)
  assert audio_listener.call_count == 0

  cue_finished.set()
  await asyncio.wait_for(listening.wait(), timeout=1)
  assert audio_listener.call_count == 1
  assert component._listening_task is not None  # noqa: SLF001
  assert not component._listening_task.done()  # noqa: SLF001

  component._transcription_complete_event.set()  # noqa: SLF001

  async def wait_until_stopped() -> None:
    while component._transcription_active:  # noqa: SLF001
      await asyncio.sleep(0)

  await asyncio.wait_for(wait_until_stopped(), timeout=1)
  assert component._listening_task.done()  # noqa: SLF001

  activation_task.cancel()

  with pytest.raises(asyncio.CancelledError):
    await activation_task


@pytest.mark.asyncio
async def test_andika_stops_listening_when_conversation_times_out() -> None:
  component = AndikaComponent(_make_settings(conversation_timeout=0.01))
  component._wakeword_event = asyncio.Event()  # noqa: SLF001
  conversation_events = []

  async def handle_conversation_event(event: str) -> None:
    conversation_events.append(event)

  component._conversation_event_handler = handle_conversation_event  # noqa: SLF001

  class AudioListenerStub:
    async def listening(self) -> None:
      await asyncio.Event().wait()

  component.audio_listener = AudioListenerStub()
  activation_task = asyncio.create_task(component._activate_on_wakeword({"stream": MagicMock()}))  # noqa: SLF001
  component._wakeword_event.set()  # noqa: SLF001

  async def wait_until_stopped() -> None:
    while component._transcription_active or component._listening_task is None:  # noqa: SLF001
      await asyncio.sleep(0)

  await asyncio.wait_for(wait_until_stopped(), timeout=1)
  assert component._listening_task.done()  # noqa: SLF001
  assert conversation_events == ["listening", "cancelled"]

  activation_task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await activation_task


@pytest.mark.asyncio
async def test_andika_stops_listening_before_processing_cue() -> None:
  component = AndikaComponent(_make_settings())
  component._listening_task = asyncio.create_task(asyncio.Event().wait())  # noqa: SLF001
  listener_stopped_during_handler = False

  async def handle_conversation_event(event: str) -> None:
    nonlocal listener_stopped_during_handler
    listener_stopped_during_handler = component._listening_task.done()  # noqa: SLF001

  component._conversation_event_handler = handle_conversation_event  # noqa: SLF001

  await component._handle_transcription_event("processing")  # noqa: SLF001

  assert listener_stopped_during_handler is True


@pytest.mark.asyncio
async def test_andika_stop_cancels_main_task_without_waiting_for_websocket_close() -> None:
  component = AndikaComponent(_make_settings())
  component._websocket = MagicMock()  # noqa: SLF001
  component._task = asyncio.create_task(asyncio.Event().wait())  # noqa: SLF001

  await component.stop()

  assert component._task.cancelled()  # noqa: SLF001
  component._websocket.close.assert_not_called()  # noqa: SLF001


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_result_payloads() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": "bonjour oremi", "confidence": 0.9})])
  transcriber = AndikaTranscriber(_make_settings(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_nested_partial_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": {"partial": "bon", "confidence": 0.9}})])
  transcriber = AndikaTranscriber(_make_settings(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_nested_text_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"result": {"text": "bonjour oremi", "confidence": 0.9}})])
  transcriber = AndikaTranscriber(_make_settings(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_not_called()


@pytest.mark.asyncio
async def test_andika_transcriber_publishes_each_partial_result() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages(
    [
      json.dumps({"partial": "bon"}),
      json.dumps({"partial": "bon"}),
      json.dumps({"partial": "bonjour"}),
    ]
  )
  transcriber = AndikaTranscriber(_make_settings(delay=1), mqtt_client, websocket)

  await transcriber.transcribing()

  assert mqtt_client.publish_event.call_count == 3
  assert [json.loads(call.args[1]) for call in mqtt_client.publish_event.call_args_list] == [
    {"partial": "bon"},
    {"partial": "bon"},
    {"partial": "bonjour"},
  ]


@pytest.mark.asyncio
async def test_andika_transcriber_uses_settings_delay_as_message_expiry() -> None:
  mqtt_client = MagicMock()
  websocket = DelayedAsyncMessages(
    [
      (0, json.dumps({"partial": "bon"})),
      (0.02, json.dumps({"partial": "bon"})),
    ]
  )
  transcriber = AndikaTranscriber(_make_settings(delay=5), mqtt_client, websocket)

  await transcriber.transcribing()

  assert mqtt_client.publish_event.call_count == 2
  assert all(call.kwargs["props"].MessageExpiryInterval == 5 for call in mqtt_client.publish_event.call_args_list)


@pytest.mark.asyncio
async def test_andika_transcriber_ignores_unknown_payloads() -> None:
  mqtt_client = MagicMock()
  websocket = AsyncMessages([json.dumps({"event": "ready"})])
  transcriber = AndikaTranscriber(_make_settings(), mqtt_client, websocket)

  await transcriber.transcribing()

  mqtt_client.publish_event.assert_not_called()


def test_andika_get_supported_models() -> None:
  component = AndikaComponent(_make_settings())
  response = MagicMock()
  response.json.return_value = [
    {"id": "vosk-model-small-fr-0.22", "name": "French (Small)", "language": "fr"},
    {"id": "vosk-model-small-en-us-0.15", "name": "English US (Small)", "language": "en"},
  ]

  with patch("oremi_device.components.andika.httpx.get", return_value=response) as mock_get:
    models = component._get_supported_models()  # noqa: SLF001

  mock_get.assert_called_once_with("http://andika:5315/api/models")
  response.raise_for_status.assert_called_once()
  assert [model.id for model in models] == ["vosk-model-small-fr-0.22", "vosk-model-small-en-us-0.15"]
  assert models[0].language == "fr"


def test_andika_get_supported_models_secure_endpoint() -> None:
  component = AndikaComponent(_make_settings(andika_host="127.0.0.1", andika_port=9443, cert_file="cert.pem"))
  response = MagicMock()
  response.json.return_value = []

  with patch("oremi_device.components.andika.httpx.get", return_value=response) as mock_get:
    assert component._get_supported_models() == []  # noqa: SLF001

  mock_get.assert_called_once_with("https://127.0.0.1:9443/api/models")


def test_andika_get_supported_models_returns_empty_on_error() -> None:
  component = AndikaComponent(_make_settings())

  with patch("oremi_device.components.andika.httpx.get", side_effect=RuntimeError("offline")):
    assert component._get_supported_models() == []  # noqa: SLF001


class WhisperAudioStub:
  def __init__(self, chunks: list[bytes]) -> None:
    self.chunks = asyncio.Queue()
    self.samplerate = 16000
    self.device_name = "Test microphone"
    self.subscribed_queue = None

    for chunk in chunks:
      self.chunks.put_nowait(chunk)

  async def __aenter__(self):
    return self

  async def __aexit__(self, exc_type, exc, traceback):
    return None

  def subscribe(self):
    self.subscribed_queue = self.chunks
    return self.chunks

  def unsubscribe(self, queue) -> None:
    assert queue is self.subscribed_queue

  def is_active(self) -> bool:
    return True

  async def data(self, queue):
    return await queue.get()


@pytest.mark.asyncio
async def test_whisper_listener_stops_after_post_speech_silence() -> None:
  speech = array("h", [1000] * 8000).tobytes()
  silence = array("h", [0] * 8000).tobytes()
  listener = WhisperCppListener(
    _make_settings(
      transcription_backend="whisper.cpp",
      whisper_url="http://whisper:8080",
      whisper_silence_duration=1,
    ),
    MagicMock(),
    WhisperAudioStub([speech, silence, silence]),
    asyncio.Event(),
  )

  captured = await listener._capture()  # noqa: SLF001

  assert captured == speech + silence + silence


@pytest.mark.asyncio
async def test_whisper_listener_posts_wav_and_publishes_result() -> None:
  settings = _make_settings(
    transcription_backend="whisper.cpp",
    whisper_url="http://whisper:8080",
  )
  mqtt_client = MagicMock()
  complete = asyncio.Event()
  events = []
  response = MagicMock()
  response.json.return_value = {"text": " bonjour oremi\n"}
  client = AsyncMock()
  client.post.return_value = response
  client_context = AsyncMock()
  client_context.__aenter__.return_value = client

  async def handle_event(event: str) -> None:
    events.append(event)

  listener = WhisperCppListener(
    settings,
    mqtt_client,
    WhisperAudioStub([]),
    complete,
    handle_event,
  )
  listener._capture = AsyncMock(return_value=array("h", [1000] * 160).tobytes())  # type: ignore[method-assign]

  with patch("oremi_device.components.andika.httpx.AsyncClient", return_value=client_context):
    await listener.listening()

  response.raise_for_status.assert_called_once()
  _, kwargs = client.post.call_args
  assert client.post.call_args.args == ("http://whisper:8080/inference",)
  assert kwargs["data"] == {"language": "fr", "response_format": "json"}
  wav_data = kwargs["files"]["file"][1]

  with wave.open(BytesIO(wav_data), "rb") as wav_file:
    assert wav_file.getnchannels() == 1
    assert wav_file.getsampwidth() == 2
    assert wav_file.getframerate() == 16000

  mqtt_client.publish_event.assert_called_once_with(
    "transcription/result",
    json.dumps({"text": "bonjour oremi"}),
    qos=1,
    retain=False,
    props=ANY,
  )
  assert events == ["processing"]
  assert complete.is_set()


@pytest.mark.asyncio
async def test_whisper_listener_cancels_conversation_on_request_error() -> None:
  mqtt_client = MagicMock()
  complete = asyncio.Event()
  events = []
  client = AsyncMock()
  client.post.side_effect = httpx.ConnectError("offline")
  client_context = AsyncMock()
  client_context.__aenter__.return_value = client

  async def handle_event(event: str) -> None:
    events.append(event)

  listener = WhisperCppListener(
    _make_settings(transcription_backend="whisper.cpp", whisper_url="http://whisper:8080"),
    mqtt_client,
    WhisperAudioStub([]),
    complete,
    handle_event,
  )
  listener._capture = AsyncMock(return_value=array("h", [1000] * 160).tobytes())  # type: ignore[method-assign]

  with patch("oremi_device.components.andika.httpx.AsyncClient", return_value=client_context):
    await listener.listening()

  assert events == ["processing", "cancelled"]
  assert complete.is_set()
  mqtt_client.publish_event.assert_not_called()
