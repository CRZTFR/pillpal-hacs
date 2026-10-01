"""Setting up an entry against a stand-in lamp."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.const import CONF_HOST, CONF_PORT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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

from .conftest import fixture

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
            {"owner": 9, "ownerLabel": "Home Assistant", "id": "garage", "colour": "#ff8800", "pattern": "solid",
             "brightness": 255, "label": "Garage door open", "priority": "high",
             "setAt": 1790598357000, "clearsAt": None, "dimmed": False, "shown": True},
            {"owner": 1, "ownerLabel": "Chris's phone", "id": "app", "colour": "#00ff00", "pattern": "solid",
             "brightness": 255, "label": None, "priority": "normal",
             "setAt": 1790598357000, "clearsAt": None, "dimmed": False, "shown": False},
        ],
        "gauge": None,
    },
    "lastTouch": None,
    "network": {"ip": "192.168.86.182", "ssid": "Cole wifi", "rssi": -57},
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
    assert [s["set_by"] for s in statuses.attributes["statuses"]] == [
        "Home Assistant", "Chris's phone"
    ]

    # Nothing set, so nothing to mirror.
    assert hass.states.get("sensor.pill_pal_gauge").state == "unknown"
    assert hass.states.get("binary_sensor.pill_pal_notification").state == "off"
    assert hass.states.get("sensor.pill_pal_last_reminder").state == "unknown"

    # A diagnostic, and off until someone turns it on.
    registry = er.async_get(hass)
    signal = registry.async_get("sensor.pill_pal_wi_fi_signal")
    assert signal is not None
    assert signal.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert signal.entity_category is EntityCategory.DIAGNOSTIC


def test_wifi_signal_reads_the_network_block() -> None:
    from custom_components.pill_pal.sensor import _wifi_attributes, _wifi_signal

    assert _wifi_signal(SNAPSHOT, 9) == -57
    assert _wifi_attributes(SNAPSHOT, 9) == {"network": "Cole wifi"}
    # Firmware before the field, or a lamp off its network.
    assert _wifi_signal({"network": {"ip": "10.0.0.2"}}, 9) is None
    assert _wifi_signal({}, 9) is None


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


# The contract's own example (indicators.md, "Reported state"), set by the phone at grant 1,
# at the lamp time the indicator fixtures use.
LAMP_NOW = datetime.fromtimestamp(fixture("indicator_payloads.json")["lamp"]["now"] / 1000, tz=UTC)
NOTIFY = {"owner": 1, "pattern": "pulse", "colour": "#00ff00", "endsAt": 1789635610000}
GAUGE = {"owner": 1, "value": 0.42, "colour": "#ffcc00", "colourEnd": None,
         "staleSeconds": 900, "updatedAt": 1789635500000, "stale": False, "shown": True}


def _with_indicators(**indicators) -> dict:
    return {**SNAPSHOT, "indicators": {**SNAPSHOT["indicators"], **indicators}}


async def test_a_gauge_set_from_the_phone(hass: HomeAssistant, entry, lamp) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator

    coordinator.async_set_updated_data(_with_indicators(gauge=GAUGE))
    await hass.async_block_till_done()
    gauge = hass.states.get("sensor.pill_pal_gauge")
    assert gauge.state == "42.0"
    assert gauge.attributes["unit_of_measurement"] == "%"
    assert gauge.attributes["color"] == "#ffcc00"
    assert gauge.attributes["color_end"] is None
    assert gauge.attributes["stale"] is False
    assert gauge.attributes["shown"] is True
    assert gauge.attributes["updated_at"] == "2026-09-17T08:58:20+00:00"
    # Borrowed from the status the same phone set.
    assert gauge.attributes["set_by"] == "Chris's phone"
    assert gauge.attributes["set_by_home_assistant"] is False

    coordinator.async_set_updated_data(_with_indicators(gauge={**GAUGE, "owner": 9, "value": 1}))
    await hass.async_block_till_done()
    gauge = hass.states.get("sensor.pill_pal_gauge")
    assert gauge.state == "100.0"
    assert gauge.attributes["set_by"] == "Home Assistant"
    assert gauge.attributes["set_by_home_assistant"] is True

    coordinator.async_set_updated_data(_with_indicators(gauge={**GAUGE, "owner": 5}))
    await hass.async_block_till_done()
    # A grant with no status here, so no name to borrow.
    assert hass.states.get("sensor.pill_pal_gauge").attributes["set_by"] is None

    coordinator.async_set_updated_data(SNAPSHOT)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pill_pal_gauge").state == "unknown"


async def test_a_notify_turns_off_when_it_ends(hass: HomeAssistant, entry, lamp, freezer) -> None:
    freezer.move_to(LAMP_NOW)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator

    coordinator.async_set_updated_data(_with_indicators(notify=NOTIFY))
    await hass.async_block_till_done()
    notification = hass.states.get("binary_sensor.pill_pal_notification")
    assert notification.state == "on"
    assert notification.attributes["pattern"] == "pulse"
    assert notification.attributes["color"] == "#00ff00"
    assert notification.attributes["ends_at"] == "2026-09-17T09:00:10+00:00"
    assert notification.attributes["set_by"] == "Chris's phone"
    assert notification.attributes["set_by_home_assistant"] is False

    # A second notify replaces the first and moves the end.
    later = {**NOTIFY, "owner": 9, "endsAt": NOTIFY["endsAt"] + 20_000}
    coordinator.async_set_updated_data(_with_indicators(notify=later))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pill_pal_notification").attributes["set_by_home_assistant"]

    # The lamp sends nothing when it runs out.
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pill_pal_notification").state == "on"

    freezer.tick(timedelta(seconds=20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    notification = hass.states.get("binary_sensor.pill_pal_notification")
    assert notification.state == "off"
    assert "pattern" not in notification.attributes


async def test_a_notify_that_has_already_ended_is_off(
    hass: HomeAssistant, entry, lamp, freezer
) -> None:
    freezer.move_to(LAMP_NOW + timedelta(minutes=1))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.coordinator.async_set_updated_data(_with_indicators(notify=NOTIFY))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pill_pal_notification").state == "off"


async def test_a_reminder_acknowledged_elsewhere(hass: HomeAssistant, entry, lamp) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.coordinator.async_set_updated_data({
        **SNAPSHOT,
        "recentOutcomes": [
            {"id": 2, "source": "native", "ownerId": 1, "state": "acknowledged",
             "endedAt": 1790598100000},
        ],
    })
    await hass.async_block_till_done()
    last = hass.states.get("sensor.pill_pal_last_reminder")
    assert last.state == "done"
    assert last.attributes["occurrence_id"] == 2
    assert last.attributes["options"] == ["done", "missed", "snoozed"]
