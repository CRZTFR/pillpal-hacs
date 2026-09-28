"""Setting up an entry against a stand-in lamp."""
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.pill_pal.api import PillPalCommandError
from custom_components.pill_pal.const import (
    CONF_DEVICE_ID,
    CONF_GENERATION,
    CONF_GRANT_ID,
    CONF_GRANT_KEY,
    DOMAIN,
    SIGNAL_TOUCH,
)

DEVICE = "PP-1620E4"

# Trimmed from a real snapshot of PP-1620E4 on 28 September 2026.
SNAPSHOT = {
    "deviceId": DEVICE,
    "ownershipGeneration": 1,
    "order": {"bootId": 4, "stateRevision": 7},
    "timeValid": True,
    "ambient": {"on": True, "level": 128, "scene": 3, "colour": "#FFB478"},
    "indicators": {
        "notify": None,
        "statuses": [
            {"owner": 9, "id": "garage", "colour": "#ff8800", "pattern": "solid",
             "brightness": 255, "label": "Garage door open", "priority": "high",
             "setAt": 1790598357000, "clearsAt": None, "dimmed": False, "shown": True},
            {"owner": 1, "id": "app", "colour": "#00ff00", "pattern": "solid",
             "brightness": 255, "label": None, "priority": "normal",
             "setAt": 1790598357000, "clearsAt": None, "dimmed": False, "shown": False},
        ],
        "gauge": None,
    },
    "lastTouch": None,
    "occurrences": [
        {"id": 3, "state": "due", "start": 1790598000000, "end": 1790601600000},
        {"id": 4, "state": "upcoming", "start": 1790605200000, "end": 1790608800000},
    ],
}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={
            CONF_HOST: "192.0.2.5",
            CONF_PORT: 8080,
            CONF_DEVICE_ID: DEVICE,
            CONF_GRANT_ID: 9,
            CONF_GRANT_KEY: "00" * 32,
            CONF_GENERATION: 1,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def lamp():
    command = AsyncMock(return_value={"outcome": "applied"})
    with (
        patch("custom_components.pill_pal.api.PillPalClient.state", AsyncMock(return_value=SNAPSHOT)),
        patch("custom_components.pill_pal.api.PillPalClient.command", command),
        patch("custom_components.pill_pal.coordinator.PillPalStream.start"),
    ):
        yield command


async def test_entities(hass: HomeAssistant, entry, lamp) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    light = hass.states.get("light.pill_pal_ambient_light")
    assert light is not None and light.state == "on"
    assert light.attributes["brightness"] == 128
    assert light.attributes["effect"] == "sunrise"
    assert tuple(light.attributes["rgb_color"]) == (255, 180, 120)

    assert hass.states.get("sensor.pill_pal_reminders_showing").state == "1"
    assert hass.states.get("sensor.pill_pal_next_reminder").state.startswith("2026-09-")
    statuses = hass.states.get("sensor.pill_pal_statuses")
    assert statuses.state == "2"
    owned = [s["set_by_home_assistant"] for s in statuses.attributes["statuses"]]
    assert owned == [True, False]


async def test_a_touch_becomes_an_event(hass: HomeAssistant, entry, lamp) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_dispatcher_send(
        hass,
        SIGNAL_TOUCH.format(device_id=DEVICE),
        {"gesture": "long_press", "pad": 1, "mode": "status",
         "target": {"kind": "status", "owner": 9, "id": "garage"}, "action": "event_only"},
    )
    await hass.async_block_till_done()
    event = hass.states.get("event.pill_pal_touch")
    assert event.attributes["event_type"] == "long_press"
    assert event.attributes["mode"] == "status"
    assert event.attributes["status_id"] == "garage"
    assert event.attributes["action"] == "event_only"


async def test_actions_reach_the_lamp(hass: HomeAssistant, entry, lamp) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE)})

    await hass.services.async_call(
        DOMAIN, "set_status",
        {"device_id": device.id, "status_id": "garage", "color": [255, 136, 0],
         "label": "Garage door open"},
        blocking=True,
    )
    operation, payload = lamp.call_args.args
    assert operation == "set_status"
    assert payload["id"] == "garage" and payload["colour"] == "#ff8800"

    await hass.services.async_call(
        "light", "turn_on",
        {"entity_id": "light.pill_pal_ambient_light", "rgb_color": [10, 20, 30], "brightness": 40},
        blocking=True,
    )
    operation, payload = lamp.call_args.args
    assert operation == "set_ambient"
    assert payload == {"on": True, "level": 40, "colour": "#0a141e", "scene": 5}


async def test_a_refusal_is_reported(hass: HomeAssistant, entry, lamp) -> None:
    from homeassistant.exceptions import HomeAssistantError

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE)})
    lamp.side_effect = PillPalCommandError("status_full", {"outcome": "status_full"})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "set_status",
            {"device_id": device.id, "status_id": "ninth", "color": [1, 2, 3]},
            blocking=True,
        )
