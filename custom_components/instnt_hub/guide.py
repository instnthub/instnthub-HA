"""TV guide from an XMLTV source.

By default the free Dutch file from open-epg.com: about 240 channels, some
2.5 days ahead, titles and times only. The URL is configurable, since free
sources come and go.

Fetched every six hours and parsed in the executor (a few MB of XML). Only
the chosen channels are kept, from three hours back to 36 hours ahead.

Which channel is on can't always be told: an Apple TV usually reports just a
title for streaming apps. Use `media_channel` when the player reports it,
otherwise the channel currently airing a programme with that title.
"""

from __future__ import annotations

import gzip
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

DEFAULT_GUIDE_URL = "https://www.open-epg.com/files/netherlands1.xml"
# Without a choice: the main Dutch channels, as named in that source.
DEFAULT_CHANNELS = [
    "NPO 1.nl", "NPO 2.nl", "NPO 3.nl", "RTL4.nl", "RTL5.nl", "SBS6.nl", "RTL7.nl",
    "Veronica / Disney Jr..nl", "NET5.nl", "RTL8.nl", "SBS9.nl", "RTL Z.nl", "Ziggo Sport.nl",
]
REFRESH = timedelta(hours=6)
KEEP_BEFORE = timedelta(hours=3)
KEEP_AFTER = timedelta(hours=36)


@dataclass
class Programme:
    start: datetime
    stop: datetime
    title: str
    description: str | None = None
    icon: str | None = None


@dataclass
class Channel:
    id: str
    name: str
    icon: str | None = None
    programmes: list[Programme] = field(default_factory=list)


def _time(value: str | None) -> datetime | None:
    """XMLTV: "20261025210000 +0000"."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z")
    except ValueError:
        try:
            return datetime.strptime(value.strip()[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _name(channel_id: str, display: str | None) -> str:
    # This source appends ".nl" to every name.
    return re.sub(r"\.nl$", "", display or channel_id).strip()


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse(raw: bytes, wanted: set[str], now: datetime) -> tuple[list[str], dict[str, Channel]]:
    """All channel IDs (for the options), and the chosen channels with programmes."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    all_ids: list[str] = []
    channels: dict[str, Channel] = {}
    for element in root.iter("channel"):
        channel_id = element.get("id") or ""
        all_ids.append(channel_id)
        if channel_id in wanted:
            icon = element.find("icon")
            channels[channel_id] = Channel(channel_id, _name(channel_id, element.findtext("display-name")),
                                           icon.get("src") if icon is not None else None)
    lower, upper = now - KEEP_BEFORE, now + KEEP_AFTER
    for element in root.iter("programme"):
        channel = channels.get(element.get("channel") or "")
        if channel is None:
            continue
        start, stop = _time(element.get("start")), _time(element.get("stop"))
        if start is None or stop is None or stop < lower or start > upper:
            continue
        icon = element.find("icon")
        channel.programmes.append(Programme(start, stop, element.findtext("title") or "",
                                            element.findtext("desc"), icon.get("src") if icon is not None else None))
    for channel in channels.values():
        channel.programmes.sort(key=lambda p: p.start)
    return all_ids, channels


class TvGuide:
    """The guide of one source, refreshed in the background."""

    def __init__(self, hass: HomeAssistant, url: str, channels: list[str] | None) -> None:
        self.hass = hass
        self.url = url or DEFAULT_GUIDE_URL
        self.wanted = list(channels or DEFAULT_CHANNELS)
        self.all_ids: list[str] = []
        self.channels: dict[str, Channel] = {}
        self.updated: datetime | None = None
        self._unsub = None

    async def async_start(self) -> None:
        self.hass.async_create_background_task(self.async_refresh(), "instnt_hub tv guide")
        self._unsub = async_track_time_interval(self.hass, self._interval, REFRESH)

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _interval(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(self.url, timeout=60) as response:
                response.raise_for_status()
                raw = await response.read()
            now = datetime.now(timezone.utc)
            all_ids, channels = await self.hass.async_add_executor_job(parse, raw, set(self.wanted), now)
        except Exception as err:  # noqa: BLE001 - keep the old guide while the source is down
            _LOGGER.warning("Could not fetch the TV guide (%s): %s", self.url, err)
            return
        self.all_ids = all_ids
        # In the order of the options, not of the file.
        self.channels = {cid: channels[cid] for cid in self.wanted if cid in channels}
        self.updated = datetime.now(timezone.utc)

    @property
    def available(self) -> bool:
        return bool(self.channels)

    def choices(self) -> list[dict[str, str]]:
        """All channels of the source, for the options."""
        return [{"value": cid, "label": _name(cid, None)} for cid in self.all_ids]

    def lineup(self, count: int = 4) -> list[dict[str, Any]]:
        """Now and next per channel."""
        now = datetime.now(timezone.utc)
        result = []
        for channel in self.channels.values():
            upcoming = [p for p in channel.programmes if p.stop > now][:count]
            result.append({
                "id": channel.id,
                "name": channel.name,
                "icon": channel.icon,
                "programmes": [
                    {"title": p.title, "start": p.start.isoformat(), "stop": p.stop.isoformat(),
                     "description": p.description, "icon": p.icon}
                    for p in upcoming
                ],
            })
        return result

    def watching(self, state: State | None) -> str | None:
        """The channel currently on the TV, if it can be told."""
        if state is None or state.state not in ("playing", "paused", "on"):
            return None
        now = datetime.now(timezone.utc)
        if wanted := state.attributes.get("media_channel"):
            for channel in self.channels.values():
                if _normalize(channel.name) == _normalize(str(wanted)):
                    return channel.id
        title = _normalize(str(state.attributes.get("media_title") or ""))
        if not title:
            return None
        for channel in self.channels.values():
            for programme in channel.programmes:
                if programme.start <= now < programme.stop and _normalize(programme.title) == title:
                    return channel.id
        return None
