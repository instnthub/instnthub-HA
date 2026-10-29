"""Config flow for instnt hub."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
    DOMAIN,
    CONF_GUIDE,
    CONF_GUIDE_CHANNELS,
    CONF_GUIDE_URL,
)
from .hub import detect


class InstntHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Added once; every choice lives in the options."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            # Pre-fill what can be detected (PlayStation Network, ps5-mqtt).
            found = {k: v for k, v in detect(self.hass).items() if v}
            return self.async_create_entry(title="instnt hub", data={}, options=found)
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return InstntHubOptionsFlow()


def _entity(domains: list[str], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains, multiple=multiple))


def _position() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
    )


class InstntHubOptionsFlow(OptionsFlow):
    """Entities, automations and the TV guide on one screen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        o = self.config_entry.options

        def opt(key: str) -> dict[str, Any]:
            # suggested_value instead of default, so a field can be cleared.
            return {"suggested_value": o.get(key)} if o.get(key) not in (None, "") else {}

        schema = vol.Schema(
            {
                vol.Optional(CONF_CONSOLE_POWER, description=opt(CONF_CONSOLE_POWER)): _entity(["switch", "media_player", "binary_sensor"]),
                vol.Optional(CONF_CONSOLE_PLAYING, description=opt(CONF_CONSOLE_PLAYING)): _entity(["media_player"]),
                vol.Optional(CONF_CONSOLE_ART, description=opt(CONF_CONSOLE_ART)): _entity(["image"]),
                vol.Optional(CONF_COVERS, description=opt(CONF_COVERS)): _entity(["cover"], multiple=True),
                vol.Optional(CONF_DAY_POSITION, default=o.get(CONF_DAY_POSITION, DEFAULT_DAY_POSITION)): _position(),
                vol.Optional(CONF_NIGHT_POSITION, default=o.get(CONF_NIGHT_POSITION, DEFAULT_NIGHT_POSITION)): _position(),
                vol.Optional(CONF_SOUNDBAR_TOGGLE, description=opt(CONF_SOUNDBAR_TOGGLE)): _entity(["script", "button", "input_button", "switch"]),
                vol.Optional(CONF_TV, description=opt(CONF_TV)): _entity(["media_player"]),
                vol.Optional(CONF_KEEP_ON, description=opt(CONF_KEEP_ON)): _entity(["media_player"], multiple=True),
                vol.Optional(CONF_AUTO_COVERS, default=o.get(CONF_AUTO_COVERS, False)): selector.BooleanSelector(),
                vol.Optional(CONF_AUTO_SOUNDBAR, default=o.get(CONF_AUTO_SOUNDBAR, False)): selector.BooleanSelector(),
                vol.Optional(CONF_AUTO_TV, default=o.get(CONF_AUTO_TV, False)): selector.BooleanSelector(),
                vol.Optional(CONF_GUIDE, default=o.get(CONF_GUIDE, False)): selector.BooleanSelector(),
                vol.Optional(CONF_GUIDE_URL, description=opt(CONF_GUIDE_URL)): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
                vol.Optional(CONF_GUIDE_CHANNELS, description=opt(CONF_GUIDE_CHANNELS)): self._channel_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    def _channel_selector(self) -> selector.SelectSelector:
        """Channels from the source once the guide has been fetched; free text
        (channel IDs as in the source) before that."""
        hub = getattr(self.config_entry, "runtime_data", None)
        choices = hub.guide.choices() if hub and hub.guide else []
        return selector.SelectSelector(selector.SelectSelectorConfig(
            options=choices, multiple=True, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN))
