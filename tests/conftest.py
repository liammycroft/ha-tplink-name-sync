"""Test fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of this custom integration."""


@pytest.fixture(autouse=True)
def skip_dependencies() -> Generator[None]:
    """Don't load the real tplink integration (and its ffmpeg/stream deps)."""
    with patch(
        "homeassistant.setup.async_process_deps_reqs", return_value=None
    ) as mock, patch(
        "homeassistant.config_entries.async_process_deps_reqs", return_value=None
    ):
        yield mock
