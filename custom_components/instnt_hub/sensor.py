"""Console power as a sensor, for use in Home Assistant itself. The app uses
the WebSocket contract instead."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import InstntHubConfigEntry
from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: InstntHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ConsoleSensor(entry)])


class ConsoleSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "console"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["on", "off", "unknown"]
    _attr_should_poll = False

    def __init__(self, entry: InstntHubConfigEntry) -> None:
        self._hub = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_console"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": "instnt hub"}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        return self._hub.contract()["console"]["power"] or "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._hub.contract()
        return {"title": c["console"]["title"], "power_source": c["console"]["power_source"], "missing": c["console"]["missing"]}
