# Copied from bindicator services/device-api/device_api/windows.py (8ce64bf). The lamp's
# contract fixture recurrence_windows.json keeps the copies in step.
"""Resolving a schedule to occurrence windows.

Takes a *canonical, valid* schedule (see `device_api.schedule`) and a
`PosixTz`, and answers the two questions the contract's recurrence-windows
fixture asks: the window open at a given instant, and the first window
starting at or after a given instant.

A window's duration is elapsed time from its resolved start, not a fixed
local-clock end, so it keeps its length across a daylight-saving transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .instants import Instant, instant_to_wire
from .posix_tz import PosixTz, offset_at_utc, resolve_local

WEEKDAY_TO_PYTHON = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# Safety bound on how many candidate dates next_window_from will scan before
# giving up. Every recurrence in the contract reaches its next occurrence
# within a handful of days except every_n_weeks (<=12 weeks) and weekdays
# (<=7 days), so this is generous headroom rather than a tight limit.
_MAX_SCAN_DATES = 4000


@dataclass(frozen=True)
class Window:
    schedule_id: int
    start_utc: datetime
    start_offset_minutes: int
    end_utc: datetime
    end_offset_minutes: int
    scheduled_local: datetime
    resolution: str

    def to_wire(self) -> dict:
        result = {
            "found": True,
            "start": instant_to_wire(Instant(self.start_utc), self.start_offset_minutes),
            "end": instant_to_wire(Instant(self.end_utc), self.end_offset_minutes),
            "scheduledLocal": self.scheduled_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "resolution": self.resolution,
        }
        elapsed = int((self.end_utc - self.start_utc).total_seconds() // 60)
        result["elapsedMinutes"] = elapsed
        return result


def iter_occurrence_dates(schedule: dict, from_date: date):
    """Yield candidate local dates for a schedule's occurrences, ascending, from `from_date`."""
    recurrence = schedule["recurrence"]

    if recurrence == "daily":
        current = from_date
        while True:
            yield current
            current += timedelta(days=1)

    elif recurrence == "weekdays":
        wanted = {WEEKDAY_TO_PYTHON[day] for day in schedule["weekdays"]}
        current = from_date
        while True:
            if current.weekday() in wanted:
                yield current
            current += timedelta(days=1)

    elif recurrence == "one_off":
        target = date.fromisoformat(schedule["date"])
        if target >= from_date:
            yield target
        return

    elif recurrence == "every_n_weeks":
        anchor = date.fromisoformat(schedule["date"])
        interval_days = schedule["intervalWeeks"] * 7
        if from_date <= anchor:
            k = 0
        else:
            diff_days = (from_date - anchor).days
            k = -(-diff_days // interval_days)  # ceil division
        while True:
            yield anchor + timedelta(days=interval_days * k)
            k += 1

    else:
        raise ValueError(f"unknown recurrence {recurrence!r}")


def occurs_on_date(schedule: dict, candidate: date) -> bool:
    """Whether `candidate` is itself one of the schedule's occurrence dates."""
    first = next(iter_occurrence_dates(schedule, candidate), None)
    return first == candidate


def occurrence_window(schedule: dict, tz: PosixTz, occ_date: date) -> Window:
    hour, minute = (int(part) for part in schedule["time"].split(":"))
    scheduled_local = datetime(occ_date.year, occ_date.month, occ_date.day, hour, minute)
    start_utc, start_offset, resolution = resolve_local(tz, scheduled_local)
    end_utc = start_utc + timedelta(minutes=schedule["durationMinutes"])
    end_offset = offset_at_utc(tz, end_utc)
    return Window(
        schedule_id=schedule["id"],
        start_utc=start_utc,
        start_offset_minutes=start_offset,
        end_utc=end_utc,
        end_offset_minutes=end_offset,
        scheduled_local=scheduled_local,
        resolution=resolution,
    )


def next_window_from(schedule: dict, tz: PosixTz, from_instant: Instant) -> Optional[Window]:
    """The first window starting at or after `from_instant`, or None."""
    if not schedule.get("enabled", True):
        return None

    approx_offset = tz.dst_offset_minutes if tz.has_dst else tz.std_offset_minutes
    start_date = (from_instant.utc + timedelta(minutes=approx_offset)).date() - timedelta(days=2)

    for index, occ_date in enumerate(iter_occurrence_dates(schedule, start_date)):
        if index >= _MAX_SCAN_DATES:
            return None
        window = occurrence_window(schedule, tz, occ_date)
        if window.start_utc >= from_instant.utc:
            return window
    return None


def window_open_at(schedule: dict, tz: PosixTz, at_instant: Instant) -> Optional[Window]:
    """The window open at `at_instant`, or None.

    Weekday eligibility refers to a window's start date, so a window that
    starts late one day and crosses midnight is checked against the date it
    started on, not the date `at_instant` falls on.
    """
    if not schedule.get("enabled", True):
        return None

    approx_offset = tz.dst_offset_minutes if tz.has_dst else tz.std_offset_minutes
    center_date = (at_instant.utc + timedelta(minutes=approx_offset)).date()

    for delta_days in (-2, -1, 0, 1):
        occ_date = center_date + timedelta(days=delta_days)
        if not occurs_on_date(schedule, occ_date):
            continue
        window = occurrence_window(schedule, tz, occ_date)
        if window.start_utc <= at_instant.utc < window.end_utc:
            return window
    return None
