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
from typing import Annotated
from typing import Any
from typing import Literal
from typing import TypedDict

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator


DetectedSoundType = Literal["sound", "wakeword"]


class DetectedSound(TypedDict):
  """
  Represents a detected sound event payload.

  Attributes:
    type: The category of the detected event, either 'sound' or 'wakeword'.
    sound: The name or identifier of the specific sound or wakeword.
    score: The confidence score of the detection (float value).
    date: The timestamp when the detection occurred in ISO 8601 format.
  """

  type: DetectedSoundType
  sound: str
  score: float
  date: str


OhunerinConfigFeature = Literal["wakeword-detection", "sound-detection"]


class OhunerinConfig(BaseModel):
  """
  The configuration schema for the Ohunerin component.
  """

  features: list[OhunerinConfigFeature] = Field(
    default_factory=lambda: ["wakeword-detection", "sound-detection"],
    description=("The list of detection features to enable."),
  )

  threshold: float = Field(
    default=0.65, description="The minimum confidence score required for a detection to be considered valid. "
  )

  @field_validator("features")
  @classmethod
  def deduplicate_features(cls, value: list[OhunerinConfigFeature]) -> list[OhunerinConfigFeature]:
    return list(dict.fromkeys(value))


AndikaModel = Literal[
  "vosk-model-small-en-us-0.15",
  "vosk-model-small-en-in-0.4",
  "vosk-model-small-cn-0.22",
  "vosk-model-small-ru-0.22",
  "vosk-model-small-fr-0.22",
  "vosk-model-small-de-0.15",
  "vosk-model-small-es-0.42",
  "vosk-model-small-pt-0.3",
  "vosk-model-small-tr-0.3",
  "vosk-model-small-vn-0.4",
  "vosk-model-small-it-0.22",
  "vosk-model-small-nl-0.22",
  "vosk-model-small-ca-0.4",
  "vosk-model-small-ar-tn-0.1-linto",
  "vosk-model-small-fa-0.42",
  "vosk-model-small-uk-v3-small",
  "vosk-model-small-kz-0.42",
  "vosk-model-small-sv-rhasspy-0.15",
  "vosk-model-small-ja-0.22",
  "vosk-model-small-eo-0.42",
  "vosk-model-small-hi-0.22",
  "vosk-model-small-cs-0.4-rhasspy",
  "vosk-model-small-pl-0.22",
  "vosk-model-small-uz-0.22",
  "vosk-model-small-ko-0.22",
  "vosk-model-small-gu-0.42",
  "vosk-model-small-tg-0.22",
  "vosk-model-small-te-0.42",
  "vosk-model-small-ky-0.42",
  "vosk-model-small-ka-0.42",
]


class AndikaConfig(BaseModel):
  """
  The configuration schema for the Andika speech-recognition component.
  """

  model: AndikaModel = Field(default="vosk-model-small-fr-0.22", description="The Andika speech-to-text model identifier.")
  samplerate: int = Field(default=16000, description="The audio sample rate in Hz.")


class AkorinConfig(BaseModel):
  """
  The configuration schema for the Akorin orchestration component.
  """

  wait_cue_delay: float = Field(default=2.0, ge=0)
  wait_cue_interval: float = Field(default=4.0, gt=0)
  timeout: float = Field(default=30.0, gt=0)
  conversation_history_limit: int = Field(default=12, gt=0)


class Command(BaseModel):
  model_config = ConfigDict(extra="forbid")


class SpeakCommand(Command):
  type: Literal["speak"]
  text: str = Field(min_length=1)
  voice: str | None = None


class AnnounceCommand(Command):
  type: Literal["announce"]
  text: str = Field(min_length=1)
  voice: str | None = None


class PlayCommand(Command):
  type: Literal["play"]
  url: str = Field(pattern=r"^https?://")


class PlayerCommand(Command):
  type: Literal["stop", "pause", "resume"]


class AlarmCommand(Command):
  type: Literal["alarm"]
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")  # pylint: disable=invalid-name
  at: AwareDatetime  # pylint: disable=invalid-name
  message: str = Field(default="Alarm", min_length=1)
  url: str | None = Field(default=None, pattern=r"^https?://")
  voice: str | None = None


class ReminderCommand(Command):
  type: Literal["reminder"]
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")  # pylint: disable=invalid-name
  at: AwareDatetime  # pylint: disable=invalid-name
  message: str = Field(min_length=1)
  voice: str | None = None


class CancelScheduledCommand(Command):
  type: Literal["cancel_scheduled"]
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")  # pylint: disable=invalid-name


class SetVolumeCommand(Command):
  type: Literal["set_volume"]
  volume: int = Field(ge=0, le=100)


class MuteCommand(Command):
  type: Literal["mute"]
  muted: bool


class SetVoiceCommand(Command):
  type: Literal["set_voice"]
  voice: str = Field(min_length=1)


ProcessingCommand = Annotated[
  SpeakCommand
  | AnnounceCommand
  | PlayCommand
  | PlayerCommand
  | AlarmCommand
  | ReminderCommand
  | CancelScheduledCommand
  | SetVolumeCommand
  | MuteCommand
  | SetVoiceCommand,
  Field(discriminator="type"),
]


class ConversationMessage(BaseModel):
  """Single message in a conversation passed to Akorin."""

  role: Literal["user", "assistant"]
  content: str = Field(min_length=1)


class ProcessingResponse(BaseModel):
  """Validated command envelope published by an Oremi NLP service."""

  ok: bool = True  # pylint: disable=invalid-name
  service: str = ""
  message: str | None = None
  data: Any = Field(default_factory=dict)
  confidence: float = 0.0
  commands: list[ProcessingCommand] = Field(default_factory=list)

  def resolved_commands(self) -> list[ProcessingCommand]:
    """Use a response message as the conversational speech fallback."""
    if self.commands or not self.message or not self.message.strip():
      return self.commands

    return [SpeakCommand(type="speak", text=self.message)]
