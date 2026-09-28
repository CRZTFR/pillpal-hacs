"""Connecting: an address or discovery, then approval in the app."""
from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.pill_pal.const import (
    CONF_DEVICE_ID,
    CONF_GENERATION,
    CONF_GRANT_ID,
    CONF_GRANT_KEY,
    DOMAIN,
)
from custom_components.pill_pal.crypto import Approval

from .conftest import fixture

VECTOR = fixture("integration_approval.json")["cases"][0]
LAMP = Approval.from_private_bytes(bytes.fromhex(VECTOR["lampPrivateKey"]))
OURS = Approval.from_private_bytes(bytes.fromhex(VECTOR["integrationPrivateKey"]))


def opened() -> dict:
    return {
        "requestId": VECTOR["requestId"],
        "publicKey": LAMP.public_key.hex(),
        "expiresInSeconds": 600,
    }


async def run_to_finish(hass: HomeAssistant, flow_id: str, result):
    while result["type"] == FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


async def test_approved(hass: HomeAssistant) -> None:
    with (
        patch("custom_components.pill_pal.config_flow.Approval", return_value=OURS),
        patch("custom_components.pill_pal.api.hello", AsyncMock(return_value={"deviceId": VECTOR["deviceId"]})),
        patch("custom_components.pill_pal.api.open_request", AsyncMock(return_value=opened())),
        patch(
            "custom_components.pill_pal.api.poll_request",
            AsyncMock(side_effect=[{"state": "pending"},
                                   {"state": "approved", "grantId": 9, "ownershipGeneration": 3}]),
        ),
        patch("custom_components.pill_pal.config_flow.APPROVAL_POLL_SECONDS", 0),
        patch("custom_components.pill_pal.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.5", CONF_PORT: 8080}
        )
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        # The code Home Assistant shows is the one the lamp derives too.
        assert result["description_placeholders"]["code"] == VECTOR["code"]
        result = await run_to_finish(hass, result["flow_id"], result)
        assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == VECTOR["deviceId"]
    assert result["data"][CONF_GRANT_ID] == 9
    assert result["data"][CONF_GENERATION] == 3
    assert result["data"][CONF_GRANT_KEY] == VECTOR["grantKey"]


async def test_declined(hass: HomeAssistant) -> None:
    with (
        patch("custom_components.pill_pal.api.hello", AsyncMock(return_value={"deviceId": "PP-000002"})),
        patch("custom_components.pill_pal.api.open_request", AsyncMock(return_value=opened())),
        patch("custom_components.pill_pal.api.poll_request", AsyncMock(return_value={"state": "declined"})),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.6", CONF_PORT: 8080}
        )
        result = await run_to_finish(hass, result["flow_id"], result)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "declined"


async def test_unreachable_address(hass: HomeAssistant) -> None:
    from custom_components.pill_pal.api import PillPalError

    with patch("custom_components.pill_pal.api.hello", AsyncMock(side_effect=PillPalError("no"))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.7", CONF_PORT: 8080}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_discovery_asks_first(hass: HomeAssistant) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.8"),
        ip_addresses=[ip_address("192.0.2.8")],
        hostname="pillpal.local.",
        name="Pill Pal._pillpal._tcp.local.",
        port=8080,
        type="_pillpal._tcp.local.",
        properties={"device": "PP-000003", "api": "1"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"


async def test_discovery_of_a_newer_lamp(hass: HomeAssistant) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.9"),
        ip_addresses=[ip_address("192.0.2.9")],
        hostname="pillpal.local.",
        name="Pill Pal._pillpal._tcp.local.",
        port=8080,
        type="_pillpal._tcp.local.",
        properties={"device": "PP-000004", "api": "2"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "unsupported_api"
