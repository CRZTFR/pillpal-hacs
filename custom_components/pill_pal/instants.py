# Copied from bindicator services/device-api/device_api/instants.py (8ce64bf). The lamp's
# contract fixture recurrence_windows.json keeps the copies in step.
"""The contract's `{ "local": ..., "offsetMinutes": ... }` instant representation.

An instant is `local` read as if it were UTC, minus `offsetMinutes`. Internally
we carry an instant as a naive `datetime` that means "UTC", never attaching a
real tzinfo, because the whole point of the wire format is that offsets are
supplied by the caller rather than looked up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_LOCAL_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True, order=True)
class Instant:
    """A point in time, carried as a naive datetime standing for UTC."""

    utc: datetime

    def plus_minutes(self, minutes: int) -> "Instant":
        return Instant(self.utc + timedelta(minutes=minutes))

    def minus_minutes(self, minutes: int) -> "Instant":
        return Instant(self.utc - timedelta(minutes=minutes))


def instant_from_wire(data: dict) -> Instant:
    local = datetime.strptime(data["local"], _LOCAL_FORMAT)
    offset = data["offsetMinutes"]
    return Instant(local - timedelta(minutes=offset))


def instant_to_wire(instant: Instant, offset_minutes: int) -> dict:
    local = instant.utc + timedelta(minutes=offset_minutes)
    return {"local": local.strftime(_LOCAL_FORMAT), "offsetMinutes": offset_minutes}
