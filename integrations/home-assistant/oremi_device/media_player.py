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
from typing import Any

from homeassistant.components import media_source
from homeassistant.components import mqtt
from homeassistant.components.media_player import MediaPlayerDeviceClass
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import build_node_topic
from .const import CONF_NODE_ID
from .const import CONF_TOPIC
from .const import DOMAIN


async def async_setup_entry(
  hass: HomeAssistant,
  entry: ConfigEntry,
  async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
  """Set up the Oremi media player."""
  async_add_entities([OremiMediaPlayer(entry)])


class OremiMediaPlayer(MediaPlayerEntity):
  """Media player backed by an Oremi Device over MQTT."""

  _attr_device_class = MediaPlayerDeviceClass.SPEAKER
  _attr_should_poll = False
  _attr_supported_features = (
    MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
  )

  def __init__(self, entry: ConfigEntry) -> None:
    self._node_id = entry.data[CONF_NODE_ID]
    self._topic = build_node_topic(entry.data[CONF_TOPIC], self._node_id)
    self._attr_name = f"Oremi Player ({self._node_id})"
    self._attr_unique_id = f"oremi-device-{self._node_id}-player"
    self._attr_state = MediaPlayerState.IDLE
    self._attr_available = False
    self._attr_volume_level = 1.0
    self._attr_is_volume_muted = False
    self._attr_device_info = DeviceInfo(
      identifiers={(DOMAIN, self._node_id)},
      name=f"Oremi Device ({self._node_id})",
      manufacturer="Sébastien Demanou",
      model="Oremi Device",
    )

  async def async_added_to_hass(self) -> None:
    """Subscribe to retained device state."""
    await super().async_added_to_hass()
    subscriptions = (
      (f"{self._topic}/player/state", self._state_received),
      (f"{self._topic}/speaker/volume/state", self._volume_received),
      (f"{self._topic}/speaker/mute/state", self._mute_received),
      (f"{self._topic}/available", self._availability_received),
    )

    for topic, handler in subscriptions:
      self.async_on_remove(await mqtt.async_subscribe(self.hass, topic, handler))

  @callback
  def _state_received(self, message: mqtt.ReceiveMessage) -> None:
    states = {
      "idle": MediaPlayerState.IDLE,
      "paused": MediaPlayerState.PAUSED,
      "playing": MediaPlayerState.PLAYING,
    }
    self._attr_state = states.get(message.payload, MediaPlayerState.IDLE)
    self.async_write_ha_state()

  @callback
  def _volume_received(self, message: mqtt.ReceiveMessage) -> None:
    try:
      self._attr_volume_level = max(0.0, min(1.0, float(message.payload) / 100))
      self.async_write_ha_state()
    except ValueError:
      pass

  @callback
  def _mute_received(self, message: mqtt.ReceiveMessage) -> None:
    self._attr_is_volume_muted = message.payload.upper() == "ON"
    self.async_write_ha_state()

  @callback
  def _availability_received(self, message: mqtt.ReceiveMessage) -> None:
    self._attr_available = message.payload == "online"
    self.async_write_ha_state()

  async def async_browse_media(self, media_content_type: str | None = None, media_content_id: str | None = None) -> Any:
    return await media_source.async_browse_media(
      self.hass,
      media_content_id,
      content_filter=lambda item: item.media_content_type.startswith("audio/"),
    )

  async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
    if media_source.is_media_source_id(media_id):
      play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
      media_id = play_item.url

    media_id = async_process_play_media_url(self.hass, media_id)
    await mqtt.async_publish(self.hass, f"{self._topic}/player/play/set", media_id)

  async def async_media_stop(self) -> None:
    await mqtt.async_publish(self.hass, f"{self._topic}/player/stop/set", "STOP")

  async def async_set_volume_level(self, volume: float) -> None:
    await mqtt.async_publish(self.hass, f"{self._topic}/speaker/volume/set", str(round(volume * 100)))

  async def async_mute_volume(self, mute: bool) -> None:
    await mqtt.async_publish(self.hass, f"{self._topic}/speaker/mute/set", "ON" if mute else "OFF")
