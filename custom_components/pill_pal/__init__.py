"""The Pill Pal integration.

One config entry per lamp. Each owns a signed client, a coordinator holding the lamp's
reported state, and the event stream. Home Assistant creates no reminders: it controls
the ambient light, drives the indicators (notify, status, gauge), acknowledges or
snoozes a reminder by id, and hears touches (development plan, 28 September 2026).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID as ATTR_DEVICE_ID
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import PillPalAuthError, PillPalClient, PillPalCommandError, PillPalError
from .const import (
    CONF_DEVICE_ID,
    CONF_GENERATION,
    CONF_GRANT_ID,
    CONF_GRANT_KEY,
    DEFAULT_PORT,
    DOMAIN,
    NOTIFY_PATTERNS,
    PLATFORMS,
    PRIORITIES,
    STATUS_PATTERNS,
)
from .coordinator import PillPalCoordinator, PillPalStream

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class PillPalData:
    client: PillPalClient
    coordinator: PillPalCoordinator
    stream: PillPalStream


type PillPalConfigEntry = ConfigEntry[PillPalData]


async def async_setup_entry(hass: HomeAssistant, entry: PillPalConfigEntry) -> bool:
    client = PillPalClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_GRANT_ID],
        bytes.fromhex(entry.data[CONF_GRANT_KEY]),
        entry.data[CONF_GENERATION],
    )
    coordinator = PillPalCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()
    stream = PillPalStream(hass, coordinator, entry)
    entry.runtime_data = PillPalData(client=client, coordinator=coordinator, stream=stream)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    stream.start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PillPalConfigEntry) -> bool:
    await entry.runtime_data.stream.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: PillPalConfigEntry) -> None:
    """Zeroconf found the lamp at a new address, or reauthentication stored a new grant."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---- Actions ---------------------------------------------------------------------------

def _hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in rgb)


RGB = vol.All(vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(list))
STATUS_ID = vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_.-]{1,23}$"))

SCHEMAS: dict[str, vol.Schema] = {
    "notify": vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Required("pattern"): vol.In(NOTIFY_PATTERNS),
            vol.Optional("color", default=[255, 255, 255]): RGB,
            vol.Optional("duration", default=5): vol.All(vol.Coerce(int), vol.Range(1, 60)),
        }
    ),
    "set_status": vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Required("status_id"): STATUS_ID,
            vol.Required("color"): RGB,
            vol.Optional("pattern", default="solid"): vol.In(STATUS_PATTERNS),
            vol.Optional("brightness", default=255): vol.All(vol.Coerce(int), vol.Range(1, 255)),
            vol.Optional("label"): vol.All(cv.string, vol.Length(max=47)),
            vol.Optional("priority", default="normal"): vol.In(PRIORITIES),
            vol.Optional("clears_at"): cv.datetime,
        }
    ),
    "clear_status": vol.Schema(
        {vol.Required(ATTR_DEVICE_ID): cv.string, vol.Required("status_id"): STATUS_ID}
    ),
    "set_gauge": vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Required("value"): vol.All(vol.Coerce(float), vol.Range(0, 1)),
            vol.Required("color"): RGB,
            vol.Optional("color_end"): RGB,
            vol.Optional("stale_after", default=900): vol.All(
                vol.Coerce(int), vol.Range(60, 86400)
            ),
        }
    ),
    "clear_gauge": vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string}),
    "acknowledge": vol.Schema(
        {vol.Required(ATTR_DEVICE_ID): cv.string, vol.Required("occurrence_id"): cv.positive_int}
    ),
    "snooze": vol.Schema(
        {vol.Required(ATTR_DEVICE_ID): cv.string, vol.Required("occurrence_id"): cv.positive_int}
    ),
}


def _payload(service: str, data: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """The contract's operation and payload for one action (indicators.md)."""
    if service == "notify":
        payload: dict[str, Any] = {"pattern": data["pattern"], "durationSeconds": data["duration"]}
        if data["pattern"] != "rainbow":
            payload["colour"] = _hex(data["color"])
        return "notify", payload
    if service == "set_status":
        payload = {
            "id": data["status_id"],
            "colour": _hex(data["color"]),
            "pattern": data["pattern"],
            "brightness": data["brightness"],
            "priority": data["priority"],
        }
        if data.get("label"):
            payload["label"] = data["label"]
        if data.get("clears_at") is not None:
            payload["clearsAt"] = int(data["clears_at"].timestamp() * 1000)
        return "set_status", payload
    if service == "clear_status":
        return "clear_status", {"id": data["status_id"]}
    if service == "set_gauge":
        payload = {
            "value": data["value"],
            "colour": _hex(data["color"]),
            "staleSeconds": data["stale_after"],
        }
        if data.get("color_end") is not None:
            payload["colourEnd"] = _hex(data["color_end"])
        return "set_gauge", payload
    if service == "clear_gauge":
        return "clear_gauge", None
    return service, {"occurrenceId": data["occurrence_id"]}


def _entry_for_device(hass: HomeAssistant, device_id: str) -> PillPalConfigEntry:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="unknown_device"
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def handle(call: ServiceCall) -> None:
        entry = _entry_for_device(hass, call.data[ATTR_DEVICE_ID])
        operation, payload = _payload(call.service, dict(call.data))
        try:
            await entry.runtime_data.client.command(operation, payload)
        except PillPalCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refused",
                translation_placeholders={"outcome": err.outcome},
            ) from err
        except PillPalAuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_authorised"
            ) from err
        except PillPalError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unreachable"
            ) from err
        await entry.runtime_data.coordinator.async_request_refresh()

    for service, schema in SCHEMAS.items():
        hass.services.async_register(DOMAIN, service, handle, schema=schema,
                                     supports_response=SupportsResponse.NONE)
    return True
