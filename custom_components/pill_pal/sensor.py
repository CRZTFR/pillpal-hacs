"""What the lamp is doing, for dashboards and conditions.

How many reminders are signalling comes from the lamp's occurrences. The next reminder
needs the schedules too, because the lamp only turns a schedule into an occurrence once
its window opens, so tomorrow's reminder is never in the list; it is resolved here with
the lamp's own time zone rule, the same way the lamp will resolve it. The statuses sensor lists what every controller has set, with the ones this integration
owns marked, so an automation reconciling after a restart can see what is still there.
The Wi-Fi signal is a diagnostic, off by default like every signal-strength sensor, for
the day someone asks why the lamp keeps dropping out; firmware from 2026-09-29 reports it.

The gauge and the last reminder mirror what any controller did, so a gauge set from the
app or a reminder acknowledged at the lamp shows here as well. An occurrence that ends
leaves the live list, so how it ended comes from the snapshot's recent outcomes; a snooze
is not terminal and is read from the live occurrence instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillPalConfigEntry
from .const import SNOOZE_MS
from .coordinator import PillPalCoordinator
from .entity import PillPalEntity, set_by, wire_time
from .instants import Instant
from .posix_tz import PosixTzError, parse_posix_tz
from .windows import next_window_from

_LOGGER = logging.getLogger(__name__)


def _next_reminder(data: dict[str, Any], _grant: int) -> datetime | None:
    starts = [
        datetime.fromtimestamp(o["start"] / 1000, tz=UTC)
        for o in data.get("occurrences") or []
        if o.get("state") in ("upcoming", "snoozed") and isinstance(o.get("start"), int)
    ]
    starts.extend(_next_scheduled(data))
    return min(starts) if starts else None


def _next_scheduled(data: dict[str, Any]) -> list[datetime]:
    schedules = data.get("schedules") or []
    if not schedules or not data.get("timeZone"):
        return []
    try:
        zone = parse_posix_tz(data["timeZone"])
    except PosixTzError:
        _LOGGER.debug("Pill Pal reported a time zone it cannot use: %s", data["timeZone"])
        return []
    now = Instant(dt_util.utcnow().replace(tzinfo=None))
    starts = []
    for schedule in schedules:
        try:
            window = next_window_from(schedule, zone, now)
        except (KeyError, TypeError, ValueError):
            # A recurrence newer than this copy of the resolver, or a malformed entry.
            continue
        if window is not None:
            starts.append(window.start_utc.replace(tzinfo=UTC))
    return starts


def _signalling(data: dict[str, Any], _grant: int) -> int:
    return sum(1 for o in data.get("occurrences") or [] if o.get("state") == "due")


def _signalling_attributes(data: dict[str, Any], _grant: int) -> dict[str, Any]:
    """The reminders showing, with the occurrence IDs acknowledge and snooze need.

    The touch target is the one a tap on the lamp would act on, so an automation can
    acknowledge or snooze the same reminder a person at the lamp would.
    """
    schedules = {
        s.get("id"): s.get("name") for s in data.get("schedules") or [] if isinstance(s, dict)
    }
    target = data.get("touchTarget")
    reminders = []
    for o in data.get("occurrences") or []:
        if not isinstance(o, dict) or o.get("state") != "due":
            continue
        start, end = wire_time(o.get("start")), wire_time(o.get("end"))
        name = o.get("name")
        if name is None and o.get("source") == "native":
            name = schedules.get(o.get("ownerId"))
        reminders.append(
            {
                "occurrence_id": o.get("id"),
                "name": name,
                "due_at": start.isoformat() if start else None,
                "ends_at": end.isoformat() if end else None,
            }
        )
    return {
        "touch_target": target if isinstance(target, int) and not isinstance(target, bool) else None,
        "reminders": reminders,
    }


def _statuses(data: dict[str, Any], _grant: int) -> int:
    return len(((data.get("indicators") or {}).get("statuses")) or [])


def _wifi_signal(data: dict[str, Any], _grant: int) -> int | None:
    rssi = (data.get("network") or {}).get("rssi")
    return rssi if isinstance(rssi, int) and rssi != 0 else None


def _wifi_attributes(data: dict[str, Any], _grant: int) -> dict[str, Any]:
    network = data.get("network") or {}
    return {"network": network.get("ssid")}


def _status_attributes(data: dict[str, Any], grant: int) -> dict[str, Any]:
    statuses = ((data.get("indicators") or {}).get("statuses")) or []
    return {
        "statuses": [
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "shown": s.get("shown"),
                "dimmed": s.get("dimmed"),
                "priority": s.get("priority"),
                "set_by": s.get("ownerLabel"),
                "set_by_home_assistant": s.get("owner") == grant,
            }
            for s in statuses
        ]
    }


def _gauge(data: dict[str, Any]) -> dict[str, Any] | None:
    gauge = (data.get("indicators") or {}).get("gauge")
    return gauge if isinstance(gauge, dict) else None


def _gauge_value(data: dict[str, Any], _grant: int) -> float | None:
    gauge = _gauge(data)
    value = gauge.get("value") if gauge else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # The lamp keeps ten-thousandths, which is two decimal places of a percentage.
    return round(value * 100.0, 2)


def _gauge_attributes(data: dict[str, Any], grant: int) -> dict[str, Any]:
    gauge = _gauge(data)
    if gauge is None:
        return {}
    updated = wire_time(gauge.get("updatedAt"))
    return {
        "color": gauge.get("colour"),
        "color_end": gauge.get("colourEnd"),
        "stale": gauge.get("stale"),
        "shown": gauge.get("shown"),
        "updated_at": updated.isoformat() if updated else None,
        **set_by(data, gauge.get("owner"), grant),
    }


OUTCOMES = {"acknowledged": "done", "expired": "missed"}
LAST_REMINDER_STATES = ["done", "missed", "snoozed"]


def _last_reminder(data: dict[str, Any]) -> dict[str, Any] | None:
    """The latest acknowledgement, expiry or snooze, from whichever controller."""
    occurrences = [o for o in data.get("occurrences") or [] if isinstance(o, dict)]
    names = {o.get("id"): o.get("name") for o in occurrences}
    schedules = {
        s.get("id"): s.get("name") for s in data.get("schedules") or [] if isinstance(s, dict)
    }
    ended = set()
    candidates = []
    for row in data.get("recentOutcomes") or []:
        if not isinstance(row, dict):
            continue
        ended.add(row.get("id"))
        at = wire_time(row.get("endedAt"))
        if row.get("state") not in OUTCOMES or at is None:
            continue
        name = names.get(row.get("id"))
        if name is None and row.get("source") == "native":
            name = schedules.get(row.get("ownerId"))
        candidates.append((at, row.get("id"), OUTCOMES[row["state"]], at, name))
    for o in occurrences:
        until = wire_time(o.get("snoozeDeadline"))
        if o.get("state") == "snoozed" and o.get("id") not in ended and until is not None:
            snoozed_at = until - timedelta(milliseconds=SNOOZE_MS)
            candidates.append((snoozed_at, o.get("id"), "snoozed", until, o.get("name")))
    if not candidates:
        return None
    _, occurrence, state, at, name = max(candidates, key=lambda c: (c[0], c[1] or 0))
    return {"state": state, "at": at, "occurrence_id": occurrence, "name": name}


def _last_reminder_state(data: dict[str, Any], _grant: int) -> str | None:
    last = _last_reminder(data)
    return last["state"] if last else None


def _last_reminder_attributes(data: dict[str, Any], _grant: int) -> dict[str, Any]:
    last = _last_reminder(data)
    if last is None:
        return {}
    return {
        "name": last["name"],
        "at": last["at"].isoformat(),
        "occurrence_id": last["occurrence_id"],
    }


@dataclass(frozen=True, kw_only=True)
class PillPalSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any], int], Any]
    attributes: Callable[[dict[str, Any], int], dict[str, Any]] | None = None


SENSORS = (
    PillPalSensorDescription(
        key="next_reminder",
        translation_key="next_reminder",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_next_reminder,
    ),
    PillPalSensorDescription(
        key="signalling",
        translation_key="signalling",
        value=_signalling,
        attributes=_signalling_attributes,
    ),
    PillPalSensorDescription(
        key="statuses",
        translation_key="statuses",
        value=_statuses,
        attributes=_status_attributes,
    ),
    PillPalSensorDescription(
        key="gauge",
        translation_key="gauge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=_gauge_value,
        attributes=_gauge_attributes,
    ),
    PillPalSensorDescription(
        key="last_reminder",
        translation_key="last_reminder",
        device_class=SensorDeviceClass.ENUM,
        options=LAST_REMINDER_STATES,
        value=_last_reminder_state,
        attributes=_last_reminder_attributes,
    ),
    PillPalSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=_wifi_signal,
        attributes=_wifi_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PillPalConfigEntry, add: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(PillPalSensor(coordinator, description) for description in SENSORS)


class PillPalSensor(PillPalEntity, SensorEntity):
    entity_description: PillPalSensorDescription

    def __init__(self, coordinator: PillPalCoordinator, description: PillPalSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data or {}, self.coordinator.client.grant_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(
            self.coordinator.data or {}, self.coordinator.client.grant_id
        )
