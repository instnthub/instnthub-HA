"""Collects the settings of a speaker: bass, treble, loudness, crossfade,
battery. These are separate entities whose IDs differ per speaker, so they
are found through the device registry and translation keys. Built for Sonos;
other brands simply return less.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# Sonos translation key → key in the response.
KEYS = {
    "bass": "bass",
    "treble": "treble",
    "balance": "balance",
    "loudness": "loudness",
    "cross_fade": "crossfade",
    "microphone": "microphone",
}


def speaker_entities(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if not entry or not entry.device_id:
        return {}
    result: dict[str, Any] = {}
    for other in er.async_entries_for_device(registry, entry.device_id):
        if other.entity_id == entity_id:
            continue
        key = KEYS.get(other.translation_key or "")
        state = hass.states.get(other.entity_id)
        device_class = (state.attributes.get("device_class") if state else None) or other.original_device_class
        if not key and other.domain == "sensor" and device_class == "battery":
            key = "battery"
        if not key and other.domain == "binary_sensor" and device_class == "battery_charging":
            key = "charging"
        if key:
            result[key] = other.entity_id
    return result
