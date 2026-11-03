# TP-Link Name Sync

Home Assistant custom integration that pushes the **names you set in Home
Assistant** (`name_by_user`) to the **alias stored on the TP-Link Kasa / Tapo
device** itself, over the local network.

It does not open its own connection: it re-uses the python-kasa `Device`
objects already held by the core **TP-Link Smart Home** (`tplink`) integration
(`entry.runtime_data.parent_coordinator.device`, children via
`device.children`). No extra requirements, no credentials, no cloud.

## Behaviour

* Only devices with a **non-empty** HA name that **differs** from the device's
  current alias are written. A name is never cleared.
* Parent devices (e.g. the power strip itself) are skipped unless
  *include parents* is on. Child sockets are synced by default.
* After each write the coordinator is refreshed and the alias is **read back**
  and verified. Authentication errors, timeouts and offline devices are
  reported as `failed` / `skipped`, never raised.
* Aliases longer than 32 characters are skipped (never truncated).
* **Dry run is on by default** – nothing is written until you turn it off.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| Dry run | on | Log / report what would change, write nothing |
| Auto sync | on | Sync a device ~3 s after you rename it in HA |
| Include parents | off | Also sync the parent device alias |

## Services

* `tplink_name_sync.set_alias` – `device_id`, `alias`, optional `dry_run`.
* `tplink_name_sync.sync_all` – optional `dry_run` override.

Both support `response_variable` and return:

```yaml
dry_run: true
summary: {written: 0, dry_run: 1, skipped: 7, failed: 0}
results:
  - device_id: abc123
    name: Bedroom Spare Socket
    old: Bedroom Thunderbolt Dock PC
    new: Bedroom Spare Socket
    status: dry_run   # written | dry_run | skipped | failed
    detail: "dry run: would write alias"
```

A summary is also logged and shown as a persistent notification. A
**Sync all names** button entity runs `sync_all` with the configured options.

## Installation

HACS: add this repository as a custom repository (type *Integration*), install,
restart Home Assistant, then *Settings → Devices & services → Add integration →
TP-Link Name Sync*.

Manual: copy `custom_components/tplink_name_sync` to `<config>/custom_components/`
and restart.

## Development

```
pip install pytest-homeassistant-custom-component
pytest
```

## License

MIT
