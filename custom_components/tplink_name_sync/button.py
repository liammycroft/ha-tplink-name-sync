"""Button entity: sync all names now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NameSyncConfigEntry
from .const import DOMAIN
from .sync import NameSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NameSyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([SyncAllButton(entry)])


class SyncAllButton(ButtonEntity):
    """Runs a full sync using the configured options (incl. dry run)."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_all"

    def __init__(self, entry: NameSyncConfigEntry) -> None:
        """Initialise the button."""
        self._manager: NameSyncManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_sync_all"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TP-Link Name Sync",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        dry_run = self._manager.dry_run
        results = await self._manager.async_sync_all(dry_run=dry_run)
        self._manager.report(results, dry_run=dry_run, title_suffix="sync all")
