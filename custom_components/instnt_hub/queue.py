"""The queue of a player, with cover art per track.

`sonos.get_queue` returns title, artist and album, but no art. For Spotify
tracks the track ID is in `media_content_id`, and Spotify's public oEmbed
endpoint returns a 300 px cover without a key. The image is served through
`/api/instnt_hub/art` with a signed path, so the app only talks to Home
Assistant. Each cover is fetched once and cached.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import re
from typing import Any
from urllib.parse import unquote

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_SPOTIFY = re.compile(r"spotify:track:([A-Za-z0-9]+)")
OEMBED = "https://open.spotify.com/oembed"


class ArtCache:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # Track ID → Spotify image URL (or None), and the images themselves.
        self._art: dict[str, str | None] = {}
        self._images: dict[str, tuple[bytes, str]] = {}

    async def art(self, content_id: str | None) -> str | None:
        """Signed path to the cover of this track, or None."""
        match = _SPOTIFY.search(unquote(content_id or ""))
        if not match:
            return None
        track = match.group(1)
        if track not in self._art:
            self._art[track] = await self._fetch(track)
        if not self._art[track]:
            return None
        return async_sign_path(self.hass, f"/api/{DOMAIN}/art/{track}", timedelta(days=1))

    async def image(self, track: str) -> tuple[bytes, str] | None:
        if track in self._images:
            return self._images[track]
        url = self._art.get(track) or await self._fetch(track)
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                result = (await resp.read(), resp.content_type or "image/jpeg")
        except Exception:  # noqa: BLE001
            return None
        # Keep memory small: a few hundred covers of ~30 kB.
        if len(self._images) > 400:
            self._images.clear()
        self._images[track] = result
        return result

    async def _fetch(self, track: str) -> str | None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(OEMBED, params={"url": f"https://open.spotify.com/track/{track}"},
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return (await resp.json()).get("thumbnail_url")
        except Exception as err:  # noqa: BLE001 - cover art is optional
            _LOGGER.debug("Spotify cover for %s failed: %s", track, err)
            return None


def _cache(hass: HomeAssistant) -> ArtCache:
    store = hass.data.setdefault(DOMAIN, {})
    if "art" not in store:
        store["art"] = ArtCache(hass)
    return store["art"]


async def queue_with_art(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]] | None:
    """The queue of a Sonos player, or None if it has none."""
    try:
        response = await hass.services.async_call(
            "sonos", "get_queue", {"entity_id": entity_id}, blocking=True, return_response=True
        )
    except Exception as err:  # noqa: BLE001 - not a Sonos player, or it is gone
        _LOGGER.debug("Could not get the queue of %s: %s", entity_id, err)
        return None
    items = (response or {}).get(entity_id) or []
    cache = _cache(hass)
    # A few at a time: dozens of tracks one by one take too long.
    sem = asyncio.Semaphore(4)

    async def one(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            art = await cache.art(item.get("media_content_id"))
        return {
            "title": item.get("media_title") or "",
            "artist": item.get("media_artist") or "",
            "album": item.get("media_album_name") or "",
            "art": art,
        }

    return list(await asyncio.gather(*(one(i) for i in items)))


class ArtView(HomeAssistantView):
    """Serves queue cover art."""

    url = f"/api/{DOMAIN}/art/{{track}}"
    name = f"api:{DOMAIN}:art"
    requires_auth = True

    async def get(self, request: web.Request, track: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        result = await _cache(hass).image(track)
        if not result:
            return web.Response(status=404)
        body, content_type = result
        return web.Response(body=body, content_type=content_type, headers={"Cache-Control": "max-age=86400"})
