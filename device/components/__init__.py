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
from pydantic import BaseModel

from device.components.akorin import AkorinComponent
from device.components.ohunerin import OhunerinComponent
from device.core.components import AudioStreamComponent
from device.core.components import Component
from device.core.components import HttpComponent
from device.core.models import AkorinConfig
from device.core.models import AndikaConfig
from device.core.models import OhunerinConfig
from device.core.stt import Speech2Text

COMPONENTS: dict[str, tuple[type[BaseModel], type[Component]]] = {
  "ohunerin": (OhunerinConfig, OhunerinComponent),
  "andika": (AndikaConfig, Speech2Text),
  "akorin": (AkorinConfig, AkorinComponent),
}

__all__ = [
  "COMPONENTS",
  "AudioStreamComponent",
  "Component",
  "HttpComponent",
]
