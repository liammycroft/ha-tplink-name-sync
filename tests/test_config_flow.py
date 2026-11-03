"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tplink_name_sync.const import DOMAIN


async def test_user_flow_defaults_and_single_instance(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "dry_run": True,
        "auto_sync": True,
        "include_parents": False,
    }
    await hass.async_block_till_done()

    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert again["type"] is FlowResultType.ABORT


async def test_options_flow(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={"dry_run": True})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"dry_run": False, "auto_sync": False, "include_parents": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "dry_run": False,
        "auto_sync": False,
        "include_parents": True,
    }
