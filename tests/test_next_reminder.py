"""The next reminder, which the lamp only lists once its window opens."""
from datetime import UTC, datetime

import pytest

from custom_components.pill_pal.instants import instant_from_wire
from custom_components.pill_pal.posix_tz import parse_posix_tz
from custom_components.pill_pal.sensor import _next_reminder
from custom_components.pill_pal.windows import next_window_from, window_open_at

from .conftest import fixture

SYDNEY = "AEST-10AEDT,M10.1.0,M4.1.0/3"

# PP-162120 at 15:34 on 30 September 2026: both of today's windows had expired and
# nothing was listed, so the sensor showed unknown.
AFTERNOON = {
    "timeZone": SYDNEY,
    "schedules": [
        {"id": 1, "recurrence": "daily", "time": "10:40", "durationMinutes": 60, "enabled": True},
        {"id": 2, "recurrence": "daily", "time": "10:45", "durationMinutes": 60, "enabled": True},
    ],
    "occurrences": [],
}


def _matches(expected, actual) -> bool:
    if isinstance(expected, dict):
        return all(k in actual and _matches(v, actual[k]) for k, v in expected.items())
    return expected == actual


def test_the_resolver_agrees_with_the_contract() -> None:
    cases = fixture("recurrence_windows.json")
    zones = {name: parse_posix_tz(rule) for name, rule in cases["zones"].items()}
    for case in cases["cases"]:
        zone = zones[case["zone"]]
        if "nextFrom" in case:
            window = next_window_from(case["schedule"], zone, instant_from_wire(case["nextFrom"]))
        else:
            window = window_open_at(case["schedule"], zone, instant_from_wire(case["openAt"]))
        if case["expect"].get("found") is False:
            assert window is None, case["id"]
        else:
            assert window is not None and _matches(case["expect"], window.to_wire()), case["id"]


@pytest.mark.freeze_time("2026-09-30T05:34:42+00:00")
def test_tomorrows_reminder_after_todays_have_ended() -> None:
    assert _next_reminder(AFTERNOON, 11) == datetime(2026, 10, 1, 0, 40, tzinfo=UTC)


@pytest.mark.freeze_time("2026-09-30T05:34:42+00:00")
def test_an_upcoming_occurrence_sooner_than_any_schedule_wins() -> None:
    data = {**AFTERNOON, "occurrences": [{"id": 20, "state": "snoozed", "start": 1790747000000}]}
    assert _next_reminder(data, 11) == datetime.fromtimestamp(1790747000, tz=UTC)


@pytest.mark.freeze_time("2026-09-30T05:34:42+00:00")
def test_disabled_and_unknown_schedules_are_skipped() -> None:
    data = {
        **AFTERNOON,
        "schedules": [
            {**AFTERNOON["schedules"][0], "enabled": False},
            {"id": 3, "recurrence": "fortnightly_someday", "time": "09:00", "durationMinutes": 60},
        ],
    }
    assert _next_reminder(data, 11) is None


def test_no_time_zone_means_no_guess() -> None:
    assert _next_reminder({**AFTERNOON, "timeZone": None}, 11) is None
    assert _next_reminder({**AFTERNOON, "timeZone": "not a zone"}, 11) is None
