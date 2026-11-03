"""TP-Link Name Sync: push Home Assistant device names to TP-Link aliases."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ALIAS,
    ATTR_DEVICE_ID,
    ATTR_DRY_RUN,
    DOMAIN,
    SERVICE_SET_ALIAS,
    SERVICE_SYNC_ALL,
)
from .sync import NameSyncManager, summarize

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NameSyncConfigEntry = ConfigEntry[NameSyncManager]

SET_ALIAS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ALIAS): cv.string,
        vol.Optional(ATTR_DRY_RUN): cv.boolean,
    }
)
SYNC_ALL_SCHEMA = vol.Schema({vol.Optional(ATTR_DRY_RUN): cv.boolean})


def _get_manager(hass: HomeAssistant) -> NameSyncManager:
    """Return the manager of the (single) loaded config entry."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return entries[0].runtime_data


def _response(results: list, dry_run: bool) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "summary": summarize(results),
        "results": [r.as_dict() for r in results],
    }


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""

    async def _set_alias(call: ServiceCall) -> ServiceResponse:
        manager = _get_manager(hass)
        device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
        if device is None or not manager._is_tplink_device(device):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_tplink_device",
                translation_placeholders={"device_id": call.data[ATTR_DEVICE_ID]},
            )
        alias = call.data[ATTR_ALIAS].strip()
        if not alias:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="empty_alias"
            )
        dry_run = call.data.get(ATTR_DRY_RUN, manager.dry_run)
        result = await manager.async_set_alias(device, alias, dry_run=dry_run)
        manager.report([result], dry_run=dry_run, title_suffix="set_alias")
        return _response([result], dry_run)

    async def _sync_all(call: ServiceCall) -> ServiceResponse:
        manager = _get_manager(hass)
        dry_run = call.data.get(ATTR_DRY_RUN, manager.dry_run)
        results = await manager.async_sync_all(dry_run=dry_run)
        manager.report(results, dry_run=dry_run, title_suffix="sync_all")
        return _response(results, dry_run)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ALIAS,
        _set_alias,
        schema=SET_ALIAS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_ALL,
        _sync_all,
        schema=SYNC_ALL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NameSyncConfigEntry) -> bool:
    """Set up from a config entry."""
    manager = NameSyncManager(hass, entry)
    entry.runtime_data = manager
    manager.async_start()
    entry.async_on_unload(manager.async_stop)
    # Options are read live by the manager; no reload needed on change.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NameSyncConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
