"""Constants for TP-Link Name Sync."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tplink_name_sync"
TPLINK_DOMAIN: Final = "tplink"

CONF_DRY_RUN: Final = "dry_run"
CONF_AUTO_SYNC: Final = "auto_sync"
CONF_INCLUDE_PARENTS: Final = "include_parents"

DEFAULT_DRY_RUN: Final = True
DEFAULT_AUTO_SYNC: Final = True
DEFAULT_INCLUDE_PARENTS: Final = False

SERVICE_SET_ALIAS: Final = "set_alias"
SERVICE_SYNC_ALL: Final = "sync_all"

ATTR_DEVICE_ID: Final = "device_id"
ATTR_ALIAS: Final = "alias"
ATTR_DRY_RUN: Final = "dry_run"

# Seconds to wait after a rename before syncing, so that typing/rapid edits
# in the UI collapse into a single write.
DEBOUNCE_SECONDS: Final = 3.0
# Seconds to wait for the device to acknowledge a write.
WRITE_TIMEOUT: Final = 15.0
# Conservative upper bound for an alias (Kasa IOT devices allow 31 bytes,
# Tapo nicknames 32 characters). Longer names are skipped, never truncated.
MAX_ALIAS_LENGTH: Final = 32

NOTIFICATION_ID: Final = f"{DOMAIN}_summary"

# Result statuses
STATUS_WRITTEN: Final = "written"
STATUS_DRY_RUN: Final = "dry_run"
STATUS_SKIPPED: Final = "skipped"
STATUS_FAILED: Final = "failed"
