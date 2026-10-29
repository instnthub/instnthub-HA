"""Soundbar switch for devices with only a power toggle (infrared through
Harmony or Broadlink). Home Assistant can't know the real state, so this
switch keeps the assumed state, also across restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import InstntHubConfigEntry
from .const import CONF_SOUNDBAR_TOGGLE, DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: InstntHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.runtime_data.opt(CONF_SOUNDBAR_TOGGLE):
        async_add_entities([SoundbarSwitch(entry)])


class SoundbarSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "soundbar"
    _attr_should_poll = False

    def __init__(self, entry: InstntHubConfigEntry) -> None:
        self._hub = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_soundbar"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": "instnt hub"}

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._hub.soundbar_on = last.state == "on"
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._hub.soundbar_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_soundbar(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_soundbar(False)
