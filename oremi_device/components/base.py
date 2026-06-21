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

Example - adding a new HTTP component:

    # oremi_device/components/injini.py
    from .base import HttpComponent

    class InjiniComponent(HttpComponent):
        @property
        def name(self) -> str:
            return "injini"

        async def start(self, config, mqtt_client, shared_resources):
            ...

        async def stop(self):
            ...
"""
import abc
import asyncio
from typing import Any

from pydantic import BaseModel

from ..core.audio import Audio
from ..core.mqtt import MQTTClient
from ..core.settings import DeviceSettings

# Type alias: (ha_domain, entity_slug, payload_dict)
# e.g. ("sensor", "wakeword", {"name": "Wakeword", ...})
HAEntity = tuple[str, str, dict]


class Component(abc.ABC):
  """Abstract base class for all Oremi Device components.

  Concrete components should not inherit from this class directly; use
  ``AudioStreamComponent`` or ``HttpComponent`` instead.
  """

  # Subclasses override this to declare whether they need a microphone stream.
  needs_audio: bool = False

  def __init__(self, settings: DeviceSettings) -> None:
    self.settings = settings

  @property
  @abc.abstractmethod
  def name(self) -> str:
    """Unique snake_case identifier for the component (e.g. ``'ohunerin'``)."""

  @property
  def task(self) -> asyncio.Task | None:
    """The main asyncio task driving the component, or ``None`` if not started."""
    return None

  def ha_entities(self, node_id: str, topic: str, device: dict) -> list["HAEntity"]:
    """Return Home Assistant MQTT discovery entity registrations.

    Each element is a ``(ha_domain, entity_slug, payload)`` triple where:

    - ``ha_domain``: HA platform string, e.g. ``"sensor"``, ``"binary_sensor"``.
    - ``entity_slug``: Short identifier used in the discovery topic,
      e.g. ``"wakeword"``.  Must be unique within the component.
    - ``payload``: The full HA MQTT discovery payload dict (without the
      ``"device"`` key — it is injected automatically by
      :meth:`MQTTClient.publish_discovery_configs`).

    The default implementation returns an empty list.  Subclasses that want
    to register HA entities should override this method.

    Args:
      node_id: The slugified device node identifier (already prefixed with
        ``"oremi-device-"`` by the MQTT client).
      topic: The base MQTT topic for this device (e.g.
        ``"oremi/device/living-room"``).
      device: The HA device descriptor dict shared across all entities for
        this device.  Pass it through as the ``"device"`` key of each
        returned payload.
    """
    return []

  @abc.abstractmethod
  async def start(
    self,
    config: BaseModel | None,
    mqtt_client: MQTTClient,
    shared_resources: dict[str, Any],
  ) -> None:
    """Start the component.

    Args:
      config: The component-specific Pydantic config model (may be ``None``).
      mqtt_client: The shared MQTT client for publishing/subscribing.
      shared_resources: A dict of device-level resources (audio stream
        container, device-change queue, helper callbacks, etc.).
    """

  @abc.abstractmethod
  async def stop(self) -> None:
    """Gracefully cancel and await all running tasks."""


class AudioStreamComponent(Component):
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
    """React to the active microphone being swapped.

    Called by the device runner both when the old stream is torn down
    (``new_stream=None``) and when the new stream is ready.

    Args:
      new_stream: The newly opened ``Audio`` stream, or ``None`` if no
        compatible device is currently available.
    """


class HttpComponent(Component):
  """Base class for components that communicate over HTTP only.

  These components do not receive any audio stream and are unaffected by
  microphone plug/unplug events.  The device runner will start them alongside
  audio-stream components without opening a microphone on their behalf.
  """

  needs_audio: bool = False
