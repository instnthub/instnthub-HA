"""Trophies through Home Assistant's PlayStation Network integration.

That integration (`playstation_network`) already holds the npsso token and a
rate-limited PSN client (300 requests per 15 minutes). This module borrows
that client: no second token and no extra requirement, since PSNAWP ships
with it. Its own title list only refreshes once a day, so titles are fetched
here with a short cache to include the game being played right now.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

PSN_DOMAIN = "playstation_network"

# The app asks every two minutes; several devices share one result.
CACHE_SECONDS = 90
TITLES_LIMIT = 50


class NoPlayStationNetwork(Exception):
    """The PlayStation Network integration is missing or not loaded yet."""


def _user(hass: HomeAssistant) -> Any:
    """The PSNAWP user ("me") of the first loaded PlayStation Network entry."""
    for entry in hass.config_entries.async_entries(PSN_DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        network = getattr(getattr(runtime, "user_data", None), "psn", None)
        user = getattr(network, "user", None)
        if user is not None:
            return user
    raise NoPlayStationNetwork


def available(hass: HomeAssistant) -> bool:
    """Whether trophies are available here (for the contract)."""
    try:
        _user(hass)
    except NoPlayStationNetwork:
        return False
    return True


def _cache(hass: HomeAssistant) -> dict[str, tuple[float, Any]]:
    return hass.data.setdefault(f"{__name__}.cache", {})


async def _cached(hass: HomeAssistant, key: str, fetch) -> Any:
    store = _cache(hass)
    hit = store.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = await hass.async_add_executor_job(fetch)
    store[key] = (time.monotonic(), value)
    return value


async def async_titles(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Recently played games, newest first."""
    user = _user(hass)

    def fetch() -> list[dict[str, Any]]:
        return [
            {
                "id": title.np_communication_id,
                "service": title.np_service_name or "trophy2",
                "name": title.title_name or "",
                "icon": title.title_icon_url,
                "progress": title.progress or 0,
            }
            for title in user.trophy_titles(limit=TITLES_LIMIT)
            if title.np_communication_id
        ]

    return await _cached(hass, "titles", fetch)


async def async_game(hass: HomeAssistant, np_communication_id: str, service: str) -> list[dict[str, Any]]:
    """All trophies of one game, with what has been earned."""
    user = _user(hass)
    # Imported here: PSNAWP is only installed with the PlayStation Network integration.
    from psnawp_api.models.trophies.trophy_constants import PlatformType  # noqa: PLC0415

    platform = PlatformType.PS5 if service == "trophy2" else PlatformType.PS4

    def fetch() -> list[dict[str, Any]]:
        return [
            {
                "id": trophy.trophy_id,
                "name": trophy.trophy_name,
                "detail": trophy.trophy_detail or "",
                "type": trophy.trophy_type.value if trophy.trophy_type else "bronze",
                "icon": trophy.trophy_icon_url,
                "rate": trophy.trophy_earn_rate or 0,
                "earned": bool(trophy.earned),
            }
            for trophy in user.trophies(
                np_communication_id=np_communication_id,
                platform=platform,
                include_progress=True,
                trophy_group_id="all",
            )
            if trophy.trophy_id is not None
        ]

    return await _cached(hass, f"game:{np_communication_id}", fetch)
