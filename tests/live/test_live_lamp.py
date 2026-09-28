"""Against a real lamp. Skipped unless PILLPAL_HOST and PILLPAL_CONSOLE are set.

    PILLPAL_HOST=192.168.86.182 PILLPAL_CONSOLE=/dev/cu.usbmodem1101 \
        pytest tests/live -s

The lamp's serial console stands in for the app: it approves the request and taps the
pad. This is the path HA-01 runs by hand, end to end through Home Assistant.
"""
import asyncio
import os
import time

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.pill_pal.const import DOMAIN

HOST = os.environ.get("PILLPAL_HOST")
CONSOLE = os.environ.get("PILLPAL_CONSOLE")

pytestmark = pytest.mark.skipif(not (HOST and CONSOLE), reason="no lamp configured")


@pytest.fixture
def lamp_network(socket_enabled):
    """Home Assistant's harness allows only 127.0.0.1 in each test; this adds the lamp."""
    import pytest_socket

    pytest_socket.socket_allow_hosts(["127.0.0.1", HOST], allow_unix_socket=True)
    yield


def console(line: str, wait: float = 2.0) -> str:
    import serial

    with serial.Serial(CONSOLE, 115200, timeout=0.2) as port:
        time.sleep(0.3)
        port.read(65536)
        port.write(line.encode() + b"\r\n")
        deadline = time.time() + wait
        out = b""
        while time.time() < deadline:
            out += port.read(4096)
        return out.decode("utf-8", "replace")


async def test_connect_control_and_hear(lamp_network, hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8080}
    )
    assert result["type"] == FlowResultType.SHOW_PROGRESS
    code = result["description_placeholders"]["code"]

    approved = await hass.async_add_executor_job(console, "approve", 3.0)
    assert f"code {code}" in approved, approved

    for _ in range(20):
        await asyncio.sleep(0.5)
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        if result["type"] != FlowResultType.SHOW_PROGRESS:
            break
    assert result["type"] == FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    entry = result["result"]

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.data["device_id"])}
    )
    await hass.services.async_call(
        DOMAIN, "set_status",
        {"device_id": device.id, "status_id": "live_test", "color": [255, 136, 0],
         "label": "Live test"},
        blocking=True,
    )
    for _ in range(20):
        await asyncio.sleep(0.25)
        state = hass.states.get("sensor.pill_pal_statuses")
        if state and any(s["id"] == "live_test" for s in state.attributes.get("statuses", [])):
            break
    assert any(s["id"] == "live_test" for s in state.attributes["statuses"])

    started = time.monotonic()
    await hass.async_add_executor_job(console, "tap", 1.5)
    for _ in range(40):
        await asyncio.sleep(0.1)
        event = hass.states.get("event.pill_pal_touch")
        if event and event.attributes.get("event_type") == "tap":
            break
    assert event.attributes["event_type"] == "tap"
    assert event.attributes["status_id"] == "live_test"
    # An upper bound: the console helper itself blocks for 1.5 s after sending `tap`.
    print(f"\ntouch seen {time.monotonic() - started:.2f}s after the console command began")

    await hass.services.async_call(
        DOMAIN, "clear_status", {"device_id": device.id, "status_id": "live_test"}, blocking=True
    )
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    revoked = await hass.async_add_executor_job(console, f"revoke {entry.data['grant_id']}")
    assert "revoked" in revoked
