"""Core logic: push Home Assistant device names to TP-Link device aliases.

The core ``tplink`` integration keeps one connected python-kasa ``Device`` per
config entry in ``entry.runtime_data.parent_coordinator.device``; child devices
(e.g. the sockets of a power strip) are in ``device.children``. We re-use those
objects, so no extra connection, credentials or discovery is needed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from kasa import AuthenticationError, Device, KasaException

from .const import (
    CONF_AUTO_SYNC,
    CONF_DRY_RUN,
    CONF_INCLUDE_PARENTS,
    DEBOUNCE_SECONDS,
    DEFAULT_AUTO_SYNC,
    DEFAULT_DRY_RUN,
    DEFAULT_INCLUDE_PARENTS,
    MAX_ALIAS_LENGTH,
    NOTIFICATION_ID,
    STATUS_DRY_RUN,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_WRITTEN,
    TPLINK_DOMAIN,
    WRITE_TIMEOUT,
)

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncResult:
    """Outcome for one device."""

    device_id: str
    name: str
    old: str | None
    new: str | None
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass(slots=True)
class KasaTarget:
    """A python-kasa device resolved for a Home Assistant device entry."""

    device: Device
    coordinator: DataUpdateCoordinator
    is_parent: bool


def summarize(results: list[SyncResult]) -> dict[str, int]:
    """Count results per status."""
    counts = {STATUS_WRITTEN: 0, STATUS_DRY_RUN: 0, STATUS_SKIPPED: 0, STATUS_FAILED: 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _id_candidates(device_id: str) -> set[str]:
    """Return the identifier forms core tplink may have registered.

    Core tplink strips an ``<mac>_`` prefix for legacy (IOT) device ids.
    """
    candidates = {device_id.lower()}
    if "_" in device_id:
        candidates.add(device_id.split("_", 1)[1].lower())
    return candidates


@callback
def _registry_event_filter(data: dr.EventDeviceRegistryUpdatedData) -> bool:
    """Cheap pre-filter: only name_by_user updates."""
    return data["action"] == "update" and "name_by_user" in data["changes"]


class NameSyncManager:
    """Owns the registry listener, debouncing and the write logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the manager."""
        self.hass = hass
        self.entry = entry
        # Serialise all writes so we never hammer a strip with parallel requests.
        self._lock = asyncio.Lock()
        self._pending: dict[str, CALLBACK_TYPE] = {}
        self._unsub_registry: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ options
    @property
    def dry_run(self) -> bool:
        """Return the configured dry-run option."""
        return bool(self.entry.options.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))

    @property
    def auto_sync(self) -> bool:
        """Return whether renames are synced automatically."""
        return bool(self.entry.options.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC))

    @property
    def include_parents(self) -> bool:
        """Return whether parent devices are synced too."""
        return bool(
            self.entry.options.get(CONF_INCLUDE_PARENTS, DEFAULT_INCLUDE_PARENTS)
        )

    # ---------------------------------------------------------------- lifecycle
    @callback
    def async_start(self) -> None:
        """Start listening for device registry renames."""
        self._unsub_registry = self.hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            self._handle_registry_event,
            event_filter=_registry_event_filter,
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening and cancel any pending debounced syncs."""
        if self._unsub_registry:
            self._unsub_registry()
            self._unsub_registry = None
        for cancel in self._pending.values():
            cancel()
        self._pending.clear()

    # ------------------------------------------------------------ event handling
    @callback
    def _handle_registry_event(
        self, event: Event[dr.EventDeviceRegistryUpdatedData]
    ) -> None:
        """Debounce a rename of a tplink-backed device."""
        if not self.auto_sync:
            return
        device_id = event.data["device_id"]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None or not self._is_tplink_device(device):
            return

        if cancel := self._pending.pop(device_id, None):
            cancel()

        @callback
        def _fire(_now: Any) -> None:
            self._pending.pop(device_id, None)
            self.entry.async_create_task(
                self.hass,
                self._async_sync_after_rename(device_id),
                f"{TPLINK_DOMAIN} name sync {device_id}",
            )

        self._pending[device_id] = async_call_later(self.hass, DEBOUNCE_SECONDS, _fire)

    async def _async_sync_after_rename(self, device_id: str) -> None:
        """Sync one device after its debounce window elapsed."""
        if not self.auto_sync:
            return
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return
        results = [await self.async_sync_device(device, dry_run=self.dry_run)]
        # Don't spam a notification for pure no-ops.
        if any(r.status != STATUS_SKIPPED for r in results):
            self.report(results, dry_run=self.dry_run, title_suffix="rename")

    # ------------------------------------------------------------------ helpers
    def _tplink_entries(self) -> list[ConfigEntry]:
        return self.hass.config_entries.async_entries(TPLINK_DOMAIN)

    def _is_tplink_device(self, device: dr.DeviceEntry) -> bool:
        tplink_ids = {e.entry_id for e in self._tplink_entries()}
        return bool(tplink_ids.intersection(device.config_entries))

    def tplink_devices(self) -> list[dr.DeviceEntry]:
        """Return all registry devices belonging to a tplink config entry."""
        registry = dr.async_get(self.hass)
        seen: dict[str, dr.DeviceEntry] = {}
        for entry in self._tplink_entries():
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                seen[device.id] = device
        return list(seen.values())

    def resolve_target(self, device: dr.DeviceEntry) -> KasaTarget | None:
        """Find the live python-kasa Device for a registry device.

        Mirrors core tplink: parent is ``runtime_data.parent_coordinator.device``
        and children live in ``device.children`` keyed by ``device_id``, which is
        also the ``(tplink, <id>)`` identifier in the device registry.
        """
        wanted: set[str] = set()
        for domain, identifier in device.identifiers:
            if domain == TPLINK_DOMAIN:
                wanted |= _id_candidates(identifier)
        if not wanted:
            return None

        for config_entry_id in device.config_entries:
            entry = self.hass.config_entries.async_get_entry(config_entry_id)
            if (
                entry is None
                or entry.domain != TPLINK_DOMAIN
                or entry.state is not ConfigEntryState.LOADED
            ):
                continue
            data = getattr(entry, "runtime_data", None)
            coordinator = getattr(data, "parent_coordinator", None)
            parent: Device | None = getattr(coordinator, "device", None)
            if coordinator is None or parent is None:
                continue
            if _id_candidates(parent.device_id) & wanted:
                return KasaTarget(parent, coordinator, True)
            for child in parent.children:
                if _id_candidates(child.device_id) & wanted:
                    return KasaTarget(child, coordinator, False)
        return None

    @staticmethod
    def _display_name(device: dr.DeviceEntry) -> str:
        return device.name_by_user or device.name or device.id

    # ----------------------------------------------------------------- the sync
    async def async_sync_device(
        self,
        device: dr.DeviceEntry,
        *,
        dry_run: bool,
        alias: str | None = None,
        explicit: bool = False,
    ) -> SyncResult:
        """Sync one device.

        ``alias`` overrides the registry name (service ``set_alias``);
        ``explicit`` means the user asked for exactly this device, so the
        include_parents option is not applied.
        """
        name = self._display_name(device)
        desired = alias if alias is not None else device.name_by_user
        desired = desired.strip() if desired else None

        def result(
            status: str, detail: str, old: str | None = None, new: str | None = None
        ) -> SyncResult:
            res = SyncResult(device.id, name, old, new, status, detail)
            _LOGGER.log(
                logging.WARNING if status == STATUS_FAILED else logging.INFO,
                "%s: %r -> %r [%s] %s",
                name,
                old,
                new,
                status,
                detail,
            )
            return res

        if not desired:
            return result(STATUS_SKIPPED, "no custom name set (never cleared)")
        if len(desired) > MAX_ALIAS_LENGTH:
            return result(
                STATUS_SKIPPED,
                f"name longer than {MAX_ALIAS_LENGTH} characters",
                new=desired,
            )

        target = self.resolve_target(device)
        if target is None:
            return result(
                STATUS_SKIPPED,
                "TP-Link device not loaded/available",
                new=desired,
            )
        if target.is_parent and not explicit and not self.include_parents:
            return result(
                STATUS_SKIPPED,
                "parent device (enable include_parents to sync)",
                old=target.device.alias,
                new=desired,
            )

        kasa_device = target.device
        old = kasa_device.alias
        if old == desired:
            return result(STATUS_SKIPPED, "already in sync", old, desired)
        if not target.coordinator.last_update_success:
            return result(STATUS_SKIPPED, "device offline/unavailable", old, desired)
        if dry_run:
            return result(STATUS_DRY_RUN, "dry run: would write alias", old, desired)

        async with self._lock:
            try:
                async with asyncio.timeout(WRITE_TIMEOUT):
                    await kasa_device.set_alias(desired)
            except AuthenticationError as ex:
                return result(STATUS_FAILED, f"authentication error: {ex}", old, desired)
            except TimeoutError:
                return result(STATUS_FAILED, "timed out writing alias", old, desired)
            except KasaException as ex:
                return result(STATUS_FAILED, f"device error: {ex}", old, desired)

            # Refresh via the integration's own coordinator (the parent updates
            # children's info) and read the alias back to verify.
            current = await self._async_refresh_and_read(target)
            if current != desired:
                await asyncio.sleep(1.0)
                current = await self._async_refresh_and_read(target)

        if current == desired:
            return result(STATUS_WRITTEN, "alias written and verified", old, desired)
        return result(
            STATUS_FAILED,
            f"read-back mismatch: device reports {current!r}",
            old,
            desired,
        )

    @staticmethod
    async def _async_refresh_and_read(target: KasaTarget) -> str | None:
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                await target.coordinator.async_refresh()
        except TimeoutError:
            _LOGGER.debug("Timeout refreshing %s after write", target.device.host)
        return target.device.alias

    async def async_sync_all(self, *, dry_run: bool | None = None) -> list[SyncResult]:
        """Sync every tplink device that has a custom name."""
        effective = self.dry_run if dry_run is None else dry_run
        results: list[SyncResult] = []
        for device in self.tplink_devices():
            results.append(await self.async_sync_device(device, dry_run=effective))
        return results

    async def async_set_alias(
        self, device: dr.DeviceEntry, alias: str, *, dry_run: bool | None = None
    ) -> SyncResult:
        """Write an explicit alias to one device."""
        effective = self.dry_run if dry_run is None else dry_run
        return await self.async_sync_device(
            device, dry_run=effective, alias=alias, explicit=True
        )

    # ----------------------------------------------------------------- reporting
    @callback
    def report(
        self, results: list[SyncResult], *, dry_run: bool, title_suffix: str = ""
    ) -> None:
        """Log and raise a persistent notification with the summary."""
        counts = summarize(results)
        lines = []
        for res in results:
            if res.status == STATUS_SKIPPED and res.detail.startswith("no custom"):
                continue
            lines.append(
                f"- **{res.name}**: `{res.old}` → `{res.new}` — {res.status}"
                + (f" ({res.detail})" if res.status != STATUS_WRITTEN else "")
            )
        head = (
            f"{'DRY RUN — no changes written. ' if dry_run else ''}"
            f"written: {counts[STATUS_WRITTEN]}, would write: {counts[STATUS_DRY_RUN]}, "
            f"skipped: {counts[STATUS_SKIPPED]}, failed: {counts[STATUS_FAILED]}"
        )
        _LOGGER.info("TP-Link name sync summary: %s", head)
        persistent_notification.async_create(
            self.hass,
            head + "\n\n" + "\n".join(lines),
            title="TP-Link Name Sync" + (f" ({title_suffix})" if title_suffix else ""),
            notification_id=NOTIFICATION_ID,
        )
