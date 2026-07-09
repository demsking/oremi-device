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
import urllib.parse

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
  assert response.continue_conversation is False


def test_processing_response_accepts_continue_conversation_flag() -> None:
  response = ProcessingResponse.model_validate({"message": "Quel jour ?", "continue_conversation": True})

  assert response.continue_conversation is True
  assert response.requests_user_input() is True
  assert response.resolved_commands() == [SpeakCommand(type="speak", text="Quel jour ?")]


def test_processing_response_does_not_request_user_input_from_data() -> None:
  response = ProcessingResponse.model_validate(
    {
      "ok": False,
      "message": "Please share a location so I can check alerts for that area.",
      "data": {"error": {"type": "more_information_required"}, "required": ["location"]},
    }
  )

  assert response.requests_user_input() is False
  assert response.resolved_commands() == [
    SpeakCommand(type="speak", text="Please share a location so I can check alerts for that area.")
  ]


def test_processing_response_does_not_request_user_input_for_generic_errors() -> None:
  response = ProcessingResponse.model_validate({"ok": False, "message": "Please try again shortly.", "data": {}})

  assert response.requests_user_input() is False


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


def test_izwi_short_synthesis_uses_streaming_get() -> None:
  client = IzwiClient("http://izwi:5215/")
  request = client.synthesize_request("quelle heure est-il ?", "ff_siwis")
  url = urllib.parse.urlparse(request.url)

  assert request.method == "GET"
  assert request.body is None
  assert f"{url.scheme}://{url.netloc}{url.path}" == "http://izwi:5215/api/synthesize/stream"
  assert urllib.parse.parse_qs(url.query) == {"voice": ["ff_siwis"], "input": ["quelle heure est-il ?"]}


def test_izwi_long_synthesis_uses_streaming_post() -> None:
  client = IzwiClient("https://izwi.example")
  request = client.synthesize_request("long text " * 300, "af_heart")

  assert request.method == "POST"
  assert request.url == "https://izwi.example/api/synthesize/stream"
  assert request.body is not None
  assert '"voice": "af_heart"' in request.body
  assert '"input": "long text ' in request.body


def test_voices_are_filtered_by_device_language() -> None:
  voices = [
    TTSVoice(name="af_heart", description="Warm", primary_language="English"),
    TTSVoice(name="ff_siwis", description="French", primary_language="French (France)"),
    TTSVoice(name="fr-FR-DeniseNeural", description="French", primary_language="fr-FR"),
  ]

  assert [voice.name for voice in voices_for_language(voices, "fr")] == ["ff_siwis", "fr-FR-DeniseNeural"]
  assert [voice.name for voice in voices_for_language(voices, "en")] == ["af_heart"]


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
