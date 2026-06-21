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
from typing import Literal
from typing import TypedDict

from pydantic import BaseModel
from pydantic import Field


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


class OhunerinConfig(BaseModel):
  """
  The configuration schema for the Ohunerin component.
  """

  threshold: float = Field(
    default=0.65,
    description="The minimum confidence score required to trigger a sound event detection. Defaults to 0.65.",
  )


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
