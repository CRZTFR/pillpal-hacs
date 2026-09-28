"""Actions become the payloads the lamp's contract defines (indicator_payloads.json)."""
from datetime import UTC, datetime

from custom_components.pill_pal import SCHEMAS, _payload

from .conftest import fixture

CASES = {case["id"]: case for case in fixture("indicator_payloads.json")["cases"]}


def build(service: str, data: dict) -> tuple[str, dict | None]:
    return _payload(service, SCHEMAS[service]({"device_id": "d", **data}))


def test_notify_matches_the_contract() -> None:
    operation, payload = build("notify", {"pattern": "pulse", "color": [0, 255, 0], "duration": 5})
    assert operation == "notify"
    assert payload == CASES["notify-pulse"]["canonical"]


def test_rainbow_sends_no_colour() -> None:
    _, payload = build("notify", {"pattern": "rainbow", "duration": 60})
    assert "colour" not in payload
    assert payload["durationSeconds"] == 60


def test_status_with_everything() -> None:
    when = datetime.fromtimestamp(CASES["status-everything"]["canonical"]["clearsAt"] / 1000, tz=UTC)
    _, payload = build(
        "set_status",
        {
            "status_id": "door.front-1_a",
            "color": [0, 0, 255],
            "pattern": "pulse",
            "brightness": 40,
            "label": "Front door",
            "priority": "high",
            "clears_at": when,
        },
    )
    canonical = CASES["status-everything"]["canonical"]
    assert payload == canonical


def test_status_ids_the_lamp_refuses_are_refused_here() -> None:
    import pytest
    import voluptuous as vol

    for bad in ("garage door", "a" * 24, "", "garagé"):
        with pytest.raises(vol.Invalid):
            SCHEMAS["set_status"]({"device_id": "d", "status_id": bad, "color": [1, 2, 3]})


def test_gauge_matches_the_contract() -> None:
    _, payload = build(
        "set_gauge",
        {"value": 1, "color": [255, 0, 0], "color_end": [0, 255, 0], "stale_after": 60},
    )
    assert payload == CASES["gauge-full-gradient"]["canonical"]


def test_occurrence_actions() -> None:
    assert build("acknowledge", {"occurrence_id": 7}) == ("acknowledge", {"occurrenceId": 7})
    assert build("snooze", {"occurrence_id": 7}) == ("snooze", {"occurrenceId": 7})
    assert build("clear_gauge", {}) == ("clear_gauge", None)
