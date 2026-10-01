"""The example blueprints, run as automations against a stand-in lamp.

Each one is loaded the way Home Assistant loads an imported blueprint, so a broken input,
template or action name fails here rather than in someone's home.
"""
from pathlib import Path
import shutil

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component

from custom_components.pill_pal.const import DOMAIN, SIGNAL_TOUCH

from .test_init import DEVICE, entry, lamp  # noqa: F401  (fixtures)

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "pill_pal"


async def _automate(hass: HomeAssistant, entry, lamp, path: str, inputs: dict) -> None:  # noqa: F811
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    shutil.copytree(BLUEPRINTS, hass.config.path("blueprints/automation/pill_pal"),
                    dirs_exist_ok=True)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE)})
    if "touch" not in inputs:
        inputs = {"lamp": device.id, **inputs}
    assert await async_setup_component(
        hass, "automation",
        {"automation": [{"id": "example", "use_blueprint": {"path": f"pill_pal/{path}", "input": inputs}}]},
    )
    await hass.async_block_till_done()
    assert hass.states.get("automation.automation_0").state == "on"
    lamp.reset_mock()


def _sent(lamp) -> list:  # noqa: F811
    return [call.args for call in lamp.call_args_list]


async def test_notify_when(hass: HomeAssistant, entry, lamp) -> None:  # noqa: F811
    hass.states.async_set("sensor.washer", "running")
    await _automate(hass, entry, lamp, "notify_when.yaml",
                    {"watched": "sensor.washer", "to_state": "finished"})

    hass.states.async_set("sensor.washer", "finished")
    await hass.async_block_till_done()
    assert _sent(lamp) == [("notify", {"pattern": "pulse", "durationSeconds": 10, "colour": "#0078ff"})]

    # Back from a dropout already finished: not a new finish.
    lamp.reset_mock()
    hass.states.async_set("sensor.washer", "unavailable")
    hass.states.async_set("sensor.washer", "finished")
    await hass.async_block_till_done()
    assert _sent(lamp) == []


async def test_status_while(hass: HomeAssistant, entry, lamp) -> None:  # noqa: F811
    hass.states.async_set("cover.garage", "closed")
    await _automate(hass, entry, lamp, "status_while.yaml",
                    {"watched": "cover.garage", "on_state": "open", "status_id": "garage",
                     "label": "Garage door open"})

    hass.states.async_set("cover.garage", "open")
    await hass.async_block_till_done()
    assert _sent(lamp) == [("set_status", {"id": "garage", "colour": "#ff8800", "pattern": "solid",
                                           "brightness": 255, "priority": "normal",
                                           "label": "Garage door open"})]

    lamp.reset_mock()
    hass.states.async_set("cover.garage", "closed")
    await hass.async_block_till_done()
    assert _sent(lamp) == [("clear_status", {"id": "garage"})]


async def test_status_while_without_a_label(hass: HomeAssistant, entry, lamp) -> None:  # noqa: F811
    hass.states.async_set("binary_sensor.door", "off")
    await _automate(hass, entry, lamp, "status_while.yaml",
                    {"watched": "binary_sensor.door", "on_state": "on", "status_id": "door"})
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()
    assert _sent(lamp) == [("set_status", {"id": "door", "colour": "#ff8800", "pattern": "solid",
                                           "brightness": 255, "priority": "normal"})]


async def test_gauge_from_sensor(hass: HomeAssistant, entry, lamp) -> None:  # noqa: F811
    hass.states.async_set("sensor.solar_export", "0")
    await _automate(hass, entry, lamp, "gauge_from_sensor.yaml",
                    {"sensor": "sensor.solar_export", "minimum": 0, "maximum": 5000,
                     "color_end": [0, 200, 80]})

    hass.states.async_set("sensor.solar_export", "2500")
    await hass.async_block_till_done()
    assert _sent(lamp) == [("set_gauge", {"value": 0.5, "colour": "#ffc800", "staleSeconds": 900,
                                          "colourEnd": "#00c850"})]

    # Past the high mark fills the lamp; it is not refused.
    lamp.reset_mock()
    hass.states.async_set("sensor.solar_export", "7200")
    await hass.async_block_till_done()
    assert _sent(lamp)[0][1]["value"] == 1.0

    # Nothing sent, so the lamp's stale cue can do its job.
    lamp.reset_mock()
    hass.states.async_set("sensor.solar_export", "unavailable")
    await hass.async_block_till_done()
    assert _sent(lamp) == []


@pytest.mark.parametrize(
    ("gesture", "mode", "when", "runs"),
    [
        ("long_press", "idle", "any", True),
        ("tap", "idle", "any", False),
        ("long_press", "status", "status", True),
        ("long_press", "idle", "status", False),
    ],
)
async def test_touch_action(hass: HomeAssistant, entry, lamp, gesture, mode, when, runs) -> None:  # noqa: F811
    await _automate(hass, entry, lamp, "touch_action.yaml",
                    {"touch": "event.pill_pal_touch", "when": when,
                     "actions": [{"action": "input_boolean.toggle",
                                  "target": {"entity_id": "input_boolean.hallway"}}]})
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"hallway": {}}})
    await hass.async_block_till_done()

    async_dispatcher_send(
        hass, SIGNAL_TOUCH.format(device_id=DEVICE),
        {"gesture": gesture, "pad": 0, "mode": mode, "target": None, "action": "event_only"},
    )
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.hallway").state == ("on" if runs else "off")
