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
"""Base classes for Oremi Device components.

Components are the integration units of an Oremi Device node. Each component
wraps a single Oremi service (e.g. Ohunerin, Andika, Injini) and is started
and stopped by the device runner.

Two concrete base classes are provided so that a component author only needs
to inherit from the one that matches its transport model:

- ``AudioStreamComponent``:
    For services that receive a continuous audio feed and communicate via
    WebSocket (e.g. Ohunerin, Andika).  The device runner will open the
    shared microphone stream before starting these components and will call
    ``on_device_changed`` whenever the active audio device is swapped.

- ``HttpComponent``:
    For services that operate purely over HTTP and do not require a
    microphone stream (e.g. Injini).  The device runner will start these
    components alongside audio-stream components without opening any audio
    device on their behalf.
"""
import abc
import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from typing import Generic
from typing import TypedDict
from typing import TypeVar

from pydantic import BaseModel

from device.core.audio import Audio
from device.core.cues import ConversationEvent
from device.core.cues import SoundCue
from device.core.models import ProcessingResponse
from device.core.settings import Settings

# Type alias: (ha_domain, entity_slug, payload_dict)
# e.g. ("sensor", "wakeword", {"name": "Wakeword", ...})
HAEntity = tuple[str, str, dict]
ComponentConfigModel = TypeVar("ComponentConfigModel", bound=BaseModel)


class ActiveStreamContainer(TypedDict, total=False):
  stream: Audio | None


class DeviceState(TypedDict, total=False):
  """Strongly typed dictionary representing device-level runtime state."""

  microphone_muted: bool


class SharedResources(TypedDict):
  """Strongly typed dictionary representing shared device-level resources."""

  active_stream_container: ActiveStreamContainer
  wakeword_event: asyncio.Event
  device_state: DeviceState
  handle_task_done: Callable[[asyncio.Task], None]
  transcription_queue: asyncio.Queue[str]
  processing_queue: asyncio.Queue[ProcessingResponse]
  language_state: dict[str, str]
  device_context: Callable[[], dict[str, Any]]
  conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]]
  final_transcription_handler: Callable[[str], Awaitable[None]]
  sound_cue_handler: Callable[[SoundCue], Awaitable[None]]
  cancel_active_processing: Callable[[], Awaitable[None]]
  mqtt_publisher: Any


class Component(Generic[ComponentConfigModel], abc.ABC):
  """Abstract base class for all Oremi Device components.

  Concrete components should not inherit from this class directly; use
  ``AudioStreamComponent`` or ``HttpComponent`` instead.
  """

  # Subclasses override this to declare whether they need a microphone stream.
  needs_audio: bool = False

  def __init__(self, settings: Settings) -> None:
    self.settings = settings

  @property
  @abc.abstractmethod
  def name(self) -> str:
    """Unique snake_case identifier for the component (e.g. ``'ohunerin'``)."""

  @property
  def task(self) -> asyncio.Task | None:
    """The main asyncio task driving the component, or ``None`` if not started."""
    return None

  @abc.abstractmethod
  async def start(
    self,
    config: ComponentConfigModel | None,
    shared_resources: SharedResources,
  ) -> None:
    """Start the component.

    Args:
      config: The component-specific Pydantic config model (may be ``None``).
      shared_resources: Device-level resources container.
    """

  @abc.abstractmethod
  async def stop(self) -> None:
    """Gracefully cancel and await all running tasks."""


class AudioStreamComponent(Generic[ComponentConfigModel], Component[ComponentConfigModel]):
  """Base class for components that process a continuous microphone audio stream.

  Inheriting classes receive access to the shared audio stream and will be
  notified via ``on_device_changed`` whenever the active microphone is
  replaced (e.g. on plug/unplug events).

  The device runner will only initialise the shared audio stream when at
  least one ``AudioStreamComponent`` is active.
  """

  needs_audio: bool = True

  @property
  def listening_task(self) -> asyncio.Task | None:
    """Secondary asyncio task that feeds audio frames to the WebSocket, or ``None``."""
    return None

  @abc.abstractmethod
  async def on_device_changed(self, new_stream: Audio | None) -> None:
    """React to the active microphone being swapped."""

  async def on_mute_changed(self, muted: bool) -> None:
    """React to the microphone mute state changing."""


class HttpComponent(Generic[ComponentConfigModel], Component[ComponentConfigModel]):
  """Base class for components that communicate over HTTP only."""

  needs_audio: bool = False
