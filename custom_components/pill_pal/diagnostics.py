"""Diagnostics. The grant key is the one secret here, and it never leaves."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PillPalConfigEntry
from .const import CONF_GRANT_KEY

REDACT = {CONF_GRANT_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PillPalConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "stream_connected": runtime.stream.connected,
        "state": runtime.coordinator.data,
    }
