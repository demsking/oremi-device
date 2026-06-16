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


class DeviceContext(BaseModel):
  node_id: str
  """The unique identifier of the Oremi Device node."""

  language: str
  """The language code (e.g., 'en', 'fr') used for processing the audio input."""

  delay: int
  """The cooldown period (in seconds) after a sound event is detected during which subsequent events are ignored to prevent rapid retriggering."""

  ohunerin_host: str
  """The hostname or IP address of the Ohunerin service."""

  ohunerin_port: int
  """The port number on which the Ohunerin service is listening."""

  cert_file: str | None
  """The path to the SSL certificate file for secure WebSocket connections. If None, an insecure connection will be used."""


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


class Discriminant(BaseModel):
  """
  A word/phoneme combo used as a discriminant to prevent false activation
  of a wakeword (e.g. if the wakeword is 'alexa', a discriminant might be 'alex').
  """

  word: str = Field(..., description="The discriminant word that could be confused with the wakeword.")
  phones: list[str] = Field(..., description="The phonetic pronunciation mapping for the discriminant word.")


SupportedLanguage = Literal[
  "en",  # English
  "fr",  # French
]


class Wakeword(BaseModel):
  """
  A wakeword configuration for the listener.
  """

  language: SupportedLanguage | None = Field(
    default=None,
    description="The language code for this specific wakeword. Overrides the device-level language.",
  )
  word: str = Field(..., description="The target wakeword to detect (e.g., 'ok google').")
  phones: list[str] = Field(..., description="The phonetic pronunciation mapping for the target wakeword.")
  discriminants: list[Discriminant] = Field(
    default_factory=list, description="A list of similar-sounding words to be ignored or treated as false positives."
  )


class OhunerinConfig(BaseModel):
  """
  The configuration schema for the Oremi Device.
  """

  threshold: float = Field(
    default=0.85, description="The minimum confidence score required to trigger a sound event detection. Defaults to 0.85."
  )


class ComponentsConfig(BaseModel):
  """
  Container for all component-level configurations.

  Each field corresponds to a named integration component (e.g. ``ohunerin``).
  """

  ohunerin: OhunerinConfig | None = Field(
    default=None, description="Configuration settings for the Ohunerin integration component."
  )


class DeviceConfig(BaseModel):
  """
  The root configuration schema for the Oremi Device.
  """

  language: SupportedLanguage = Field(
    default="fr",
    description="The default language code for the device. Used as a fallback when not overridden at the component or wakeword level.",
  )

  components: ComponentsConfig = Field(
    default_factory=ComponentsConfig,
    description="Component-specific configuration blocks, keyed by component name.",
  )
