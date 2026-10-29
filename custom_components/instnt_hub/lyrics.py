"""Lyrics from LRCLIB (lrclib.net).

The app only talks to Home Assistant, so the integration fetches the lyrics.
LRCLIB is free and needs no key; it asks for a recognisable User-Agent and a
modest request rate: one request at a time, and every result is cached,
including misses.

Lookup order:
1. `/api/get` with artist, title, album and duration (exact, ±2 s);
2. `/api/search` with artist and title, picking the match with the closest
   duration. This catches compilations and reissues, where the album name
   differs between the player and LRCLIB.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BASE = "https://lrclib.net"
USER_AGENT = "instnt-hub (Home Assistant integration; https://github.com/instnthub/instnthub-HA)"
# A real miss is not retried for six hours. An outage or a 429 is not a
# miss, otherwise a track that does have lyrics stays empty.
MISS_TTL = 6 * 3600
TIMEOUT = 10

_LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s?(.*)$")
_NOISE = re.compile(r"\s*[\(\[](feat\.?|ft\.?|with|remaster(ed)?|radio edit|single version|live|\d{4} remaster)[^\)\]]*[\)\]]", re.I)


class _Failed(Exception):
    """LRCLIB did not answer (outage, timeout, 429)."""


def _norm(text: str) -> str:
    return _NOISE.sub("", text or "").strip().lower()


def parse_lrc(text: str) -> list[dict[str, Any]]:
    """`[01:23.45] line` → [{"t": 83.45, "text": "line"}]; untimed lines are dropped."""
    lines = []
    for raw in (text or "").splitlines():
        match = _LINE.match(raw.strip())
        if match:
            minutes, seconds, words = match.groups()
            lines.append({"t": round(int(minutes) * 60 + float(seconds), 2), "text": words})
    return lines


class LyricsCache:
    """Caches LRCLIB results per track; one request at a time."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._found: dict[str, dict[str, Any]] = {}
        self._missed: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def lookup(self, artist: str, title: str, album: str | None, duration: float | None) -> dict[str, Any]:
        key = f"{_norm(artist)}|{_norm(title)}"
        if key in self._found:
            return self._found[key]
        if time.time() - self._missed.get(key, 0) < MISS_TTL:
            return {"found": False}
        async with self._lock:
            try:
                result = await self._fetch(artist, title, album, duration)
            except _Failed:
                return {"found": False}
        if result.get("found"):
            self._found[key] = result
        else:
            self._missed[key] = time.time()
        return result

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(f"{BASE}{path}", params=params, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 429:
                    _LOGGER.debug("LRCLIB asked to slow down")
                    raise _Failed
                resp.raise_for_status()
                return await resp.json()
        except _Failed:
            raise
        except Exception as err:  # noqa: BLE001 - lyrics are optional, never an error
            _LOGGER.debug("LRCLIB %s failed: %s", path, err)
            raise _Failed from err

    async def _fetch(self, artist: str, title: str, album: str | None, duration: float | None) -> dict[str, Any]:
        entry = None
        if album and duration:
            entry = await self._get("/api/get", {
                "artist_name": artist, "track_name": title, "album_name": album, "duration": str(round(duration)),
            })
        if not entry:
            results = await self._get("/api/search", {"artist_name": artist, "track_name": _norm(title) or title})
            if results:
                # Prefer timed lyrics, then the closest duration.
                def score(e: dict[str, Any]) -> tuple[int, float]:
                    gap = abs((e.get("duration") or 0) - duration) if duration else 0
                    return (0 if e.get("syncedLyrics") else 1, gap)
                candidates = [e for e in results if _norm(e.get("trackName", "")) == _norm(title)] or results
                best = min(candidates, key=score)
                if not duration or abs((best.get("duration") or 0) - duration) <= 5:
                    entry = best
        if not entry:
            return {"found": False}
        if entry.get("instrumental"):
            return {"found": True, "instrumental": True, "lines": [], "plain": None}
        return {
            "found": True,
            "instrumental": False,
            "lines": parse_lrc(entry.get("syncedLyrics") or ""),
            "plain": entry.get("plainLyrics"),
            "source": "lrclib",
            "id": entry.get("id"),
        }


def cache(hass: HomeAssistant) -> LyricsCache:
    store = hass.data.setdefault(DOMAIN, {})
    if "lyrics" not in store:
        store["lyrics"] = LyricsCache(hass)
    return store["lyrics"]
