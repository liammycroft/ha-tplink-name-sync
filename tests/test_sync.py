"""Tests for TP-Link Name Sync (uses fake python-kasa devices)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from kasa import AuthenticationError
from kasa import TimeoutError as KasaTimeoutError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tplink_name_sync.const import (
    CONF_AUTO_SYNC,
    CONF_DRY_RUN,
    CONF_INCLUDE_PARENTS,
    DEBOUNCE_SECONDS,
    DOMAIN,
)

PARENT_ID = "8022AAAA"


class FakeDevice:
    """Minimal stand-in for a kasa Device."""

    def __init__(self, device_id, alias, children=()):
        self.device_id = device_id
        self.alias = alias
        self.children = list(children)
        self.host = "192.0.2.1"
        self.set_alias_calls: list[str] = []
        self.fail_with: Exception | None = None
        self.ignore_write = False

    async def set_alias(self, alias):
        if self.fail_with:
            raise self.fail_with
        self.set_alias_calls.append(alias)
        if not self.ignore_write:
            self.alias = alias
        return {}


@pytest.fixture
def strip(hass: HomeAssistant):
    """A fake loaded tplink entry with a parent and two children."""
    kids = [
        FakeDevice(f"{PARENT_ID}00", "Old Zero"),
        FakeDevice(f"{PARENT_ID}01", "Old One"),
    ]
    parent = FakeDevice(PARENT_ID, "Strip", kids)
    coordinator = SimpleNamespace(
        device=parent, last_update_success=True, async_refresh=AsyncMock()
    )
    entry = MockConfigEntry(domain="tplink", unique_id="aa:bb")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(parent_coordinator=coordinator)
    reg = dr.async_get(hass)
    devs = {
        d.device_id: reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("tplink", d.device_id)}
        )
        for d in [parent, *kids]
    }
    return SimpleNamespace(
        parent=parent, kids=kids, coordinator=coordinator, devs=devs, entry=entry
    )


async def _setup(hass, **options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DRY_RUN: False,
            CONF_AUTO_SYNC: True,
            CONF_INCLUDE_PARENTS: False,
            **options,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sync_all_writes_only_named_children(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}01"].id, name_by_user="New One")
    reg.async_update_device(strip.devs[PARENT_ID].id, name_by_user="Renamed Strip")
    await _setup(hass, auto_sync=False)

    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert resp["summary"] == {"written": 1, "dry_run": 0, "skipped": 2, "failed": 0}
    assert strip.kids[1].alias == "New One"
    assert strip.kids[1].set_alias_calls == ["New One"]
    assert strip.kids[0].set_alias_calls == []  # no name_by_user -> never cleared
    assert strip.parent.set_alias_calls == []  # parent skipped
    strip.coordinator.async_refresh.assert_awaited()
    written = next(r for r in resp["results"] if r["status"] == "written")
    assert (written["old"], written["new"]) == ("Old One", "New One")


async def test_include_parents(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[PARENT_ID].id, name_by_user="Renamed Strip")
    await _setup(hass, auto_sync=False, include_parents=True)
    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert strip.parent.alias == "Renamed Strip"
    assert resp["summary"]["written"] == 1


async def test_dry_run_default_and_override(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}00"].id, name_by_user="Zero")
    await _setup(hass, dry_run=True, auto_sync=False)

    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert resp["dry_run"] is True
    assert resp["summary"]["dry_run"] == 1
    assert strip.kids[0].set_alias_calls == []

    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {"dry_run": False}, blocking=True, return_response=True
    )
    assert resp["summary"]["written"] == 1
    assert strip.kids[0].alias == "Zero"


async def test_in_sync_is_skipped(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}00"].id, name_by_user="Old Zero")
    await _setup(hass, auto_sync=False)
    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert resp["summary"]["written"] == 0
    assert strip.kids[0].set_alias_calls == []


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (AuthenticationError("bad"), "authentication"),
        (KasaTimeoutError("slow"), "timed out"),
    ],
)
async def test_errors_reported_not_raised(hass, strip, exc, text) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}00"].id, name_by_user="Zero")
    await _setup(hass, auto_sync=False)
    strip.kids[0].fail_with = exc
    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert resp["summary"]["failed"] == 1
    failed = next(r for r in resp["results"] if r["status"] == "failed")
    assert text in failed["detail"]


async def test_readback_mismatch_fails(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}00"].id, name_by_user="Zero")
    await _setup(hass, auto_sync=False)
    strip.kids[0].ignore_write = True
    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert resp["summary"]["failed"] == 1
    assert "read-back mismatch" in resp["results"][0]["detail"] or any(
        "read-back mismatch" in r["detail"] for r in resp["results"]
    )


async def test_offline_skipped(hass, strip) -> None:
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}00"].id, name_by_user="Zero")
    await _setup(hass, auto_sync=False)
    strip.coordinator.last_update_success = False
    resp = await hass.services.async_call(
        DOMAIN, "sync_all", {}, blocking=True, return_response=True
    )
    assert strip.kids[0].set_alias_calls == []
    assert any("offline" in r["detail"] for r in resp["results"])


async def test_set_alias_service(hass, strip) -> None:
    await _setup(hass, auto_sync=False)
    resp = await hass.services.async_call(
        DOMAIN,
        "set_alias",
        {"device_id": strip.devs[f"{PARENT_ID}01"].id, "alias": " Spare "},
        blocking=True,
        return_response=True,
    )
    assert resp["results"][0]["status"] == "written"
    assert strip.kids[1].alias == "Spare"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_alias",
            {"device_id": "does-not-exist", "alias": "x"},
            blocking=True,
            return_response=True,
        )


async def test_auto_sync_debounced(hass, strip) -> None:
    await _setup(hass)
    reg = dr.async_get(hass)
    dev_id = strip.devs[f"{PARENT_ID}01"].id
    reg.async_update_device(dev_id, name_by_user="N")
    reg.async_update_device(dev_id, name_by_user="New One")
    await hass.async_block_till_done()
    assert strip.kids[1].set_alias_calls == []  # still debouncing

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=DEBOUNCE_SECONDS + 1)
    )
    await hass.async_block_till_done()
    assert strip.kids[1].set_alias_calls == ["New One"]  # one write, final name


async def test_auto_sync_disabled_and_other_changes_ignored(hass, strip) -> None:
    await _setup(hass, auto_sync=False)
    reg = dr.async_get(hass)
    reg.async_update_device(strip.devs[f"{PARENT_ID}01"].id, name_by_user="New One")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert strip.kids[1].set_alias_calls == []


async def test_non_tplink_device_ignored(hass, strip) -> None:
    await _setup(hass)
    other = MockConfigEntry(domain="hue")
    other.add_to_hass(hass)
    reg = dr.async_get(hass)
    dev = reg.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("hue", "1")}
    )
    reg.async_update_device(dev.id, name_by_user="Lamp")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert all(not k.set_alias_calls for k in strip.kids)


async def test_button_entity_exists(hass, strip) -> None:
    await _setup(hass, auto_sync=False)
    states = hass.states.async_all("button")
    assert len(states) == 1
    assert states[0].entity_id == "button.tp_link_name_sync_sync_all_names"
