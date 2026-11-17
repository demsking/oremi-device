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
import abc
import logging

from pydantic import BaseModel

from device.core.settings import Settings

logger = logging.getLogger(__name__)


class SupportedModel(BaseModel):
  id: str  # pylint: disable=invalid-name
  name: str
  language: str
  backend: str | None = None


class BaseTranscriber(abc.ABC):
  """Abstract Base Class for all speech-to-text transcribers."""

  def __init__(self, settings: Settings) -> None:
    self.settings = settings

  @property
  @abc.abstractmethod
  def name(self) -> str:
    """Unique identifier for the transcriber implementation."""

  @classmethod
  def get_supported_models(cls, settings: Settings) -> list[SupportedModel]:
    """Return a list of models supported by this transcriber."""
    return []

  @abc.abstractmethod
  async def transcribing(self) -> None:
    """Execute the transcription process or processing loop."""
