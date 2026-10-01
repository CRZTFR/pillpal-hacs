"""The last reminder, which may have ended at the lamp, in the app or here."""
from datetime import UTC, datetime

from custom_components.pill_pal.sensor import (
    _last_reminder_attributes,
    _last_reminder_state,
)

# Rows in the shape the lamp writes them (wire.cpp, `recentOutcomes` and `occurrences`).
DATA = {
    "schedules": [
        {"id": 1, "name": "Morning tablets", "recurrence": "daily", "time": "08:00",
         "durationMinutes": 60},
        {"id": 2, "name": "Evening tablets", "recurrence": "daily", "time": "20:00",
         "durationMinutes": 60},
    ],
    "occurrences": [],
    "recentOutcomes": [
        {"id": 30, "source": "native", "ownerId": 1, "state": "acknowledged",
         "endedAt": 1790560000000},
        {"id": 31, "source": "native", "ownerId": 2, "state": "expired",
         "endedAt": 1790600000000},
        {"id": 29, "source": "native", "ownerId": 2, "state": "cancelled",
         "endedAt": 1790610000000},
    ],
}


def _at(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def test_the_latest_outcome_wins() -> None:
    # Cancelled by a schedule edit is not something anyone did to a reminder.
    assert _last_reminder_state(DATA, 9) == "missed"
    assert _last_reminder_attributes(DATA, 9) == {
        "name": "Evening tablets",
        "at": _at(1790600000000),
        "occurrence_id": 31,
    }


def test_an_acknowledgement_reads_as_done() -> None:
    data = {**DATA, "recentOutcomes": DATA["recentOutcomes"][:1]}
    assert _last_reminder_state(data, 9) == "done"
    assert _last_reminder_attributes(data, 9)["name"] == "Morning tablets"


def test_a_snooze_after_the_last_outcome() -> None:
    deadline = 1790600000000 + 5 * 60_000 + 600_000
    data = {
        **DATA,
        "occurrences": [
            {"id": 32, "source": "native", "ownerId": 1, "state": "snoozed",
             "start": 1790599000000, "end": 1790602600000, "snoozeDeadline": deadline,
             "name": "Morning tablets"},
        ],
    }
    assert _last_reminder_state(data, 9) == "snoozed"
    # For a snooze, when it runs out.
    assert _last_reminder_attributes(data, 9) == {
        "name": "Morning tablets",
        "at": _at(deadline),
        "occurrence_id": 32,
    }


def test_a_snooze_before_the_last_outcome_loses() -> None:
    # Snoozed at 1790599000000, ten minutes before its deadline, and the expiry came later.
    data = {
        **DATA,
        "occurrences": [
            {"id": 32, "source": "native", "ownerId": 1, "state": "snoozed",
             "start": 1790598000000, "end": 1790601600000,
             "snoozeDeadline": 1790599000000 + 600_000},
        ],
    }
    assert _last_reminder_state(data, 9) == "missed"


def test_an_external_reminder_has_no_schedule_name() -> None:
    data = {
        "recentOutcomes": [
            {"id": 40, "source": "external", "ownerId": 1, "state": "acknowledged",
             "endedAt": 1790560000000},
        ],
        "schedules": DATA["schedules"],
    }
    assert _last_reminder_attributes(data, 9)["name"] is None


def test_nothing_has_ended_yet() -> None:
    assert _last_reminder_state({}, 9) is None
    assert _last_reminder_attributes({"recentOutcomes": [], "occurrences": []}, 9) == {}
