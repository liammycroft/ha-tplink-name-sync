"""Config flow for TP-Link Name Sync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_AUTO_SYNC,
    CONF_DRY_RUN,
    CONF_INCLUDE_PARENTS,
    DEFAULT_AUTO_SYNC,
    DEFAULT_DRY_RUN,
    DEFAULT_INCLUDE_PARENTS,
    DOMAIN,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_DRY_RUN, default=defaults.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)
            ): bool,
            vol.Required(
                CONF_AUTO_SYNC, default=defaults.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC)
            ): bool,
            vol.Required(
                CONF_INCLUDE_PARENTS,
                default=defaults.get(CONF_INCLUDE_PARENTS, DEFAULT_INCLUDE_PARENTS),
            ): bool,
        }
    )


class TPLinkNameSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title="TP-Link Name Sync", data={}, options=user_input
            )
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return TPLinkNameSyncOptionsFlow()


class TPLinkNameSyncOptionsFlow(OptionsFlow):
    """Options flow (self.config_entry is provided by the base class)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self.config_entry.options))
        )
