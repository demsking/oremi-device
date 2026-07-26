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
import json
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from device.components.edge_tts import OpenAIEdgeTTSClient
from device.components.izwi import IzwiClient
from device.core.models import ProcessingResponse
from device.core.models import SpeakCommand
from device.core.tts import TTSVoice
from device.core.tts import voices_for_language


def test_processing_message_defaults_to_speech() -> None:
  response = ProcessingResponse.model_validate({"message": "Il est 13h30"})

  assert response.resolved_commands() == [SpeakCommand(type="speak", text="Il est 13h30")]


def test_explicit_commands_override_message_fallback() -> None:
  response = ProcessingResponse.model_validate(
    {
      "message": "Now playing",
      "commands": [
        {"type": "announce", "text": "Now playing"},
        {"type": "play", "url": "https://media.local/song.mp3"},
        {"type": "pause"},
        {"type": "resume"},
        {"type": "stop"},
        {"type": "set_volume", "volume": 35},
        {"type": "mute", "muted": True},
        {"type": "set_voice", "voice": "af_heart"},
        {"type": "cancel_scheduled", "id": "morning"},
      ],
    }
  )

  assert [command.type for command in response.resolved_commands()] == [
    "announce",
    "play",
    "pause",
    "resume",
    "stop",
    "set_volume",
    "mute",
    "set_voice",
    "cancel_scheduled",
  ]


def test_processing_rejects_unknown_or_unsafe_commands() -> None:
  with pytest.raises(ValidationError):
    ProcessingResponse.model_validate({"commands": [{"type": "shell", "command": "shutdown"}]})

  with pytest.raises(ValidationError):
    ProcessingResponse.model_validate({"commands": [{"type": "play", "url": "file:///private/audio.wav"}]})

  with pytest.raises(ValidationError):
    ProcessingResponse.model_validate({"commands": [{"type": "stop", "unexpected": True}]})


def test_alarm_and_reminder_require_aware_timestamps() -> None:
  response = ProcessingResponse.model_validate(
    {
      "commands": [
        {
          "type": "alarm",
          "id": "morning",
          "at": "2026-06-23T07:00:00+02:00",
          "message": "Wake up",
          "url": "https://media.local/alarm.mp3",
        },
        {
          "type": "reminder",
          "id": "medicine",
          "at": "2026-06-23T18:30:00Z",
          "message": "Take your medicine",
        },
      ]
    }
  )

  assert [command.type for command in response.commands] == ["alarm", "reminder"]

  with pytest.raises(ValidationError):
    ProcessingResponse.model_validate(
      {
        "commands": [
          {
            "type": "reminder",
            "id": "medicine",
            "at": "2026-06-23T18:30:00",
            "message": "Take your medicine",
          }
        ]
      }
    )


@pytest.mark.parametrize("volume", [-1, 101])
def test_set_volume_rejects_out_of_range_values(volume: int) -> None:
  with pytest.raises(ValidationError):
    ProcessingResponse.model_validate({"commands": [{"type": "set_volume", "volume": volume}]})


@pytest.mark.asyncio
async def test_izwi_get_voices_parses_supertonic_voices() -> None:
  client = IzwiClient("http://izwi:5031")
  mock_response = MagicMock(spec=httpx.Response)
  mock_response.raise_for_status.return_value = None
  mock_response.json.return_value = {
    "voices": [
      {
        "id": "F1",
        "name": "Sophia",
        "gender": "Female",
        "description": "Expressive female voice",
        "sample_rate": 44100,
      }
    ],
    "total": 1,
  }

  with patch("httpx.AsyncClient.get", return_value=mock_response):
    voices = await client.get_voices()

  assert len(voices) == 1
  assert voices[0].id == "F1"
  assert voices[0].name == "F1"
  assert voices[0].primary_language == "multilingual"
  assert voices[0].gender == "Female"
  assert voices[0].sample_rate == 44100


def test_izwi_synthesis_uses_streaming_post() -> None:
  client = IzwiClient("http://izwi:5031/")
  request = client.synthesize_request("quelle heure est-il ?", "F1", language="fr")

  assert request.method == "POST"
  assert request.url == "http://izwi:5031/api/tts/stream"
  assert request.headers == {"Content-Type": "application/json"}
  assert request.body is not None
  body = json.loads(request.body)
  assert body == {
    "text": "quelle heure est-il ?",
    "audio_format": "wav",
    "voice": "F1",
    "language": "fr",
  }


def test_voices_are_filtered_by_device_language() -> None:
  voices = [
    TTSVoice(name="af_heart", description="Warm", primary_language="English"),
    TTSVoice(name="ff_siwis", description="French", primary_language="French (France)"),
    TTSVoice(name="fr-FR-DeniseNeural", description="French", primary_language="fr-FR"),
    TTSVoice(name="F1", description="Supertonic", primary_language="multilingual"),
  ]

  assert [voice.name for voice in voices_for_language(voices, "fr")] == ["ff_siwis", "fr-FR-DeniseNeural", "F1"]
  assert [voice.name for voice in voices_for_language(voices, "en")] == ["af_heart", "F1"]


def test_edge_tts_synthesis_uses_openai_speech_endpoint() -> None:
  client = OpenAIEdgeTTSClient("http://edge-tts:5050/", api_key="secret", locale="fr-FR")
  request = client.synthesize_request("bonjour", "fr-FR-DeniseNeural")

  assert request.method == "POST"
  assert request.url == "http://edge-tts:5050/v1/audio/speech"
  assert request.headers == {"Authorization": "Bearer secret"}
  assert request.body is not None
  assert '"model": "tts-1"' in request.body
  assert '"input": "bonjour"' in request.body
  assert '"voice": "fr-FR-DeniseNeural"' in request.body
  assert '"response_format": "mp3"' in request.body


def test_edge_tts_voice_parser_accepts_edge_voice_metadata() -> None:
  client = OpenAIEdgeTTSClient("http://edge-tts:5050", api_key="secret")

  voice = client._parse_voice(
    {
      "ShortName": "fr-FR-DeniseNeural",
      "FriendlyName": "Microsoft Denise Online (Natural) - French (France)",
      "Locale": "fr-FR",
    }
  )

  assert voice == TTSVoice(
    name="fr-FR-DeniseNeural",
    description="Microsoft Denise Online (Natural) - French (France)",
    primary_language="fr-FR",
  )
