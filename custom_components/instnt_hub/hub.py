"""The contract and the built-in automations.

`Hub.contract()` always returns the same shape, however a home is set up:
per part (console, room, TV) which entities are used and what is still
missing. The app relies on that shape only.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_GUIDE,
    CONF_GUIDE_CHANNELS,
    CONF_GUIDE_URL,
    CONF_AUTO_COVERS,
    CONF_AUTO_SOUNDBAR,
    CONF_AUTO_TV,
    CONF_CONSOLE_ART,
    CONF_CONSOLE_PLAYING,
    CONF_CONSOLE_POWER,
    CONF_COVERS,
    CONF_DAY_POSITION,
    CONF_KEEP_ON,
    CONF_NIGHT_POSITION,
    CONF_SOUNDBAR_TOGGLE,
    CONF_TV,
    DEFAULT_DAY_POSITION,
    DEFAULT_NIGHT_POSITION,
    OFF_STATES,
    ON_STATES,
    SIGNAL_UPDATE,
)
from . import trophies
from .guide import TvGuide

_LOGGER = logging.getLogger(__name__)


def power_state(state: State | None) -> str | None:
    """"on", "off", or None for an in-between state."""
    if state is None:
        return None
    if state.state in ON_STATES:
        return "on"
    if state.state in OFF_STATES:
        return "off"
    return None


def detect(hass: HomeAssistant) -> dict[str, Any]:
    """Suggested options.

    Entity IDs follow the user's language, so match on what an entity is
    where possible: a switch with ps5 and power in its ID (ps5-mqtt), a media
    player with playstation in its ID (PlayStation Network).
    """
    states = hass.states.async_all()

    def first(pred) -> str | None:
        return next((s.entity_id for s in states if pred(s)), None)

    power = first(lambda s: s.domain == "switch" and "ps5" in s.entity_id and "power" in s.entity_id) or first(
        lambda s: s.domain == "media_player" and "playstation" in s.entity_id
    )
    return {
        CONF_CONSOLE_POWER: power,
        CONF_CONSOLE_PLAYING: first(lambda s: s.domain == "media_player" and "playstation" in s.entity_id),
        CONF_CONSOLE_ART: first(lambda s: s.domain == "image" and s.entity_id.endswith("now_playing")),
    }


class Hub:
    """One per config entry: holds the options and follows the console."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsub: list = []
        self._last_power: str | None = None
        # Cover positions from before the console turned on, to restore later.
        self._covers_before: dict[str, int] = {}
        # Assumed soundbar state; kept by the switch entity.
        self.soundbar_on: bool = False
        # Once at startup: scanning all states on every change adds up in a
        # large home.
        self._detected: dict[str, Any] = detect(hass)
        # Only when enabled in the options.
        self.guide: TvGuide | None = None

    # Options

    @property
    def options(self) -> dict[str, Any]:
        return {**self._detected, **{k: v for k, v in self.entry.options.items() if v not in (None, "", [])}}

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    # Lifecycle

    async def async_start(self) -> None:
        if self.opt(CONF_GUIDE, False):
            self.guide = TvGuide(self.hass, self.opt(CONF_GUIDE_URL) or "", self.opt(CONF_GUIDE_CHANNELS, []))
            await self.guide.async_start()
        power = self.opt(CONF_CONSOLE_POWER)
        if power:
            self._last_power = power_state(self.hass.states.get(power))
            self._unsub.append(async_track_state_change_event(self.hass, [power], self._on_power))
        watched = [e for e in [self.opt(CONF_CONSOLE_PLAYING), self.opt(CONF_CONSOLE_ART), self.opt(CONF_TV)] if e]
        watched += self.opt(CONF_COVERS, []) + self.opt(CONF_KEEP_ON, [])
        if watched:
            self._unsub.append(async_track_state_change_event(self.hass, watched, self._on_any))

    async def async_stop(self) -> None:
        if self.guide:
            self.guide.async_stop()
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    @callback
    def _on_any(self, event: Event[EventStateChangedData]) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    # Automations

    async def _on_power(self, event: Event[EventStateChangedData]) -> None:
        new = power_state(event.data["new_state"])
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        # Real transitions only. The first known state after a restart is not
        # a power-on.
        if new is None or new == self._last_power:
            return
        previous, self._last_power = self._last_power, new
        if previous is None:
            return
        if new == "on":
            await self._console_on()
        else:
            await self._console_off()

    async def _console_on(self) -> None:
        if self.opt(CONF_AUTO_COVERS, False):
            covers = self.opt(CONF_COVERS, [])
            self._covers_before = {
                c: s.attributes.get("current_position")
                for c in covers
                if (s := self.hass.states.get(c)) and s.attributes.get("current_position") is not None
            }
            day = self.hass.states.is_state("sun.sun", "above_horizon")
            position = self.opt(CONF_DAY_POSITION, DEFAULT_DAY_POSITION) if day else self.opt(
                CONF_NIGHT_POSITION, DEFAULT_NIGHT_POSITION
            )
            if covers:
                await self.hass.services.async_call(
                    "cover", "set_cover_position", {ATTR_ENTITY_ID: covers, "position": int(position)}, blocking=False
                )
        if self.opt(CONF_AUTO_SOUNDBAR, False):
            await self.async_set_soundbar(True)

    async def _console_off(self) -> None:
        if self.opt(CONF_AUTO_COVERS, False) and self._covers_before:
            # Leave them alone if someone opened them further in the meantime.
            limit = max(self.opt(CONF_DAY_POSITION, DEFAULT_DAY_POSITION), self.opt(CONF_NIGHT_POSITION, DEFAULT_NIGHT_POSITION)) + 5
            now = [
                s.attributes.get("current_position", 0)
                for c in self._covers_before
                if (s := self.hass.states.get(c))
            ]
            if all(p <= limit for p in now):
                for cover, position in self._covers_before.items():
                    await self.hass.services.async_call(
                        "cover", "set_cover_position", {ATTR_ENTITY_ID: cover, "position": position}, blocking=False
                    )
            self._covers_before = {}
        if self.opt(CONF_AUTO_SOUNDBAR, False):
            await self.async_set_soundbar(False)
        if self.opt(CONF_AUTO_TV, False):
            await self._tv_off()

    async def _tv_off(self) -> None:
        tv = self.opt(CONF_TV)
        if not tv or (state := self.hass.states.get(tv)) is None or state.state in OFF_STATES | {"unavailable", "unknown"}:
            return
        # Stays on while, for example, the Apple TV is still playing. That
        # should be the Apple TV itself, not a HomePod in the same room.
        for player in self.opt(CONF_KEEP_ON, []):
            if (s := self.hass.states.get(player)) and s.state in ON_STATES:
                return
        await self.hass.services.async_call("media_player", "turn_off", {ATTR_ENTITY_ID: tv}, blocking=False)

    async def async_set_soundbar(self, on: bool) -> None:
        """Only press when the assumed state is wrong: the button toggles."""
        if on == self.soundbar_on:
            return
        toggle = self.opt(CONF_SOUNDBAR_TOGGLE)
        if not toggle:
            return
        domain = toggle.split(".")[0]
        service = {"script": "turn_on", "button": "press", "input_button": "press"}.get(domain, "toggle")
        await self.hass.services.async_call(domain, service, {ATTR_ENTITY_ID: toggle}, blocking=False)
        self.soundbar_on = on
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    # Contract

    def contract(self) -> dict[str, Any]:
        """The fixed shape for the app. Only changes with a new version."""
        power_id = self.opt(CONF_CONSOLE_POWER)
        power = self.hass.states.get(power_id) if power_id else None
        playing_id = self.opt(CONF_CONSOLE_PLAYING)
        playing = self.hass.states.get(playing_id) if playing_id else None

        console_missing = []
        if not power_id:
            console_missing.append("power")
        if not playing_id:
            console_missing.append("playstation_network")

        covers = self.opt(CONF_COVERS, [])
        return {
            "version": 1,
            "console": {
                "power_entity": power_id,
                "power_source": "local" if power_id and power_id.startswith("switch.") else "cloud" if power_id else None,
                "power": power_state(power),
                "since": power.last_changed.isoformat() if power else None,
                "playing_entity": playing_id,
                "title": playing.attributes.get("media_title") if playing else None,
                "art_entity": self.opt(CONF_CONSOLE_ART),
                # Trophies via `instnt_hub/trophy_titles`.
                "trophies": trophies.available(self.hass),
                "missing": console_missing,
            },
            "room": {
                "covers": covers,
                "day_position": self.opt(CONF_DAY_POSITION, DEFAULT_DAY_POSITION),
                "night_position": self.opt(CONF_NIGHT_POSITION, DEFAULT_NIGHT_POSITION),
                "soundbar": bool(self.opt(CONF_SOUNDBAR_TOGGLE)),
                # The switch of this integration; on/off goes through it so the
                # assumed state stays right.
                "soundbar_entity": er.async_get(self.hass).async_get_entity_id(
                    "switch", "instnt_hub", f"{self.entry.entry_id}_soundbar"
                ),
                "soundbar_on": self.soundbar_on,
                "missing": [] if covers else ["covers"],
            },
            "tv": {
                "tv_entity": self.opt(CONF_TV),
                "keep_on": self.opt(CONF_KEEP_ON, []),
                # TV guide via `instnt_hub/tv_guide`.
                "guide": bool(self.guide and self.guide.available),
                "watching": self.guide.watching(self.hass.states.get(self.opt(CONF_TV))) if self.guide and self.opt(CONF_TV) else None,
            },
            "automations": {
                "covers": bool(self.opt(CONF_AUTO_COVERS, False)),
                "soundbar": bool(self.opt(CONF_AUTO_SOUNDBAR, False)),
                "tv": bool(self.opt(CONF_AUTO_TV, False)),
            },
        }
