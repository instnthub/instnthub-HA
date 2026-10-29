"""The instnt hub integration.

Configured once in Home Assistant; every device running the app reads the
setup through WebSocket commands, so the app only ever talks to Home
Assistant.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .hub import Hub
from .lyrics import cache as lyrics_cache
from .queue import ArtView, queue_with_art
from .speaker import speaker_entities
from . import trophies

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type InstntHubConfigEntry = ConfigEntry[Hub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    websocket_api.async_register_command(hass, ws_contract)
    websocket_api.async_register_command(hass, ws_lyrics)
    websocket_api.async_register_command(hass, ws_queue)
    websocket_api.async_register_command(hass, ws_speaker)
    websocket_api.async_register_command(hass, ws_trophy_titles)
    websocket_api.async_register_command(hass, ws_trophy_game)
    websocket_api.async_register_command(hass, ws_tv_guide)
    hass.http.register_view(ArtView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: InstntHubConfigEntry) -> bool:
    hub = Hub(hass, entry)
    entry.runtime_data = hub
    await hub.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Rebuild on new options so the listeners follow the chosen entities.
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InstntHubConfigEntry) -> bool:
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _reload(hass: HomeAssistant, entry: InstntHubConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/contract"})
@callback
def ws_contract(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The contract for the app, or None when the integration is not set up."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], None)
        return
    connection.send_result(msg["id"], entries[0].runtime_data.contract())


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/lyrics",
    vol.Required("artist"): str,
    vol.Required("title"): str,
    vol.Optional("album"): vol.Any(str, None),
    vol.Optional("duration"): vol.Any(vol.Coerce(float), None),
})
@websocket_api.async_response
async def ws_lyrics(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Lyrics for a track: timed `lines`, or `plain` text only.

    Works without a config entry.
    """
    result = await lyrics_cache(hass).lookup(msg["artist"], msg["title"], msg.get("album"), msg.get("duration"))
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/queue", vol.Required("entity_id"): str})
@websocket_api.async_response
async def ws_queue(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The queue of a player with cover art per track, or None."""
    connection.send_result(msg["id"], await queue_with_art(hass, msg["entity_id"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/speaker", vol.Required("entity_id"): str})
@callback
def ws_speaker(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Related speaker entities: {"bass": "number.…", "battery": "sensor.…", …}."""
    connection.send_result(msg["id"], speaker_entities(hass, msg["entity_id"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/trophy_titles"})
@websocket_api.async_response
async def ws_trophy_titles(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Recently played games with progress.

    Works without a config entry, but needs the PlayStation Network integration.
    """
    try:
        connection.send_result(msg["id"], {"titles": await trophies.async_titles(hass)})
    except trophies.NoPlayStationNetwork:
        connection.send_error(msg["id"], "no_psn", "PlayStation Network is not set up in Home Assistant")
    except Exception as err:  # noqa: BLE001 - PSNAWP raises many error types; the app retries later
        connection.send_error(msg["id"], "psn_error", str(err))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/trophy_game",
    vol.Required("id"): str,
    vol.Required("service"): str,
})
@websocket_api.async_response
async def ws_trophy_game(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """All trophies of one game, with what has been earned."""
    try:
        connection.send_result(msg["id"], {"trophies": await trophies.async_game(hass, msg["id"], msg["service"])})
    except trophies.NoPlayStationNetwork:
        connection.send_error(msg["id"], "no_psn", "PlayStation Network is not set up in Home Assistant")
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "psn_error", str(err))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/tv_guide", vol.Optional("count", default=4): vol.All(int, vol.Range(min=1, max=24))})
@callback
def ws_tv_guide(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Now and next per chosen channel, and the channel the TV is on."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    hub = entries[0].runtime_data if entries else None
    if hub is None or hub.guide is None:
        connection.send_error(msg["id"], "no_guide", "The TV guide is turned off in the integration options")
        return
    tv = hub.opt("tv")
    connection.send_result(msg["id"], {
        "channels": hub.guide.lineup(msg["count"]),
        "watching": hub.guide.watching(hass.states.get(tv)) if tv else None,
        "updated": hub.guide.updated.isoformat() if hub.guide.updated else None,
    })
