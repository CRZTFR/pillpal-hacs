"""What the lamp is doing, for dashboards and conditions.

How many reminders are signalling comes from the lamp's occurrences. The next reminder
needs the schedules too, because the lamp only turns a schedule into an occurrence once
its window opens, so tomorrow's reminder is never in the list; it is resolved here with
the lamp's own time zone rule, the same way the lamp will resolve it. The statuses sensor lists what every controller has set, with the ones this integration
owns marked, so an automation reconciling after a restart can see what is still there.
The Wi-Fi signal is a diagnostic, off by default like every signal-strength sensor, for
the day someone asks why the lamp keeps dropping out; firmware from 2026-09-29 reports it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillPalConfigEntry
from .coordinator import PillPalCoordinator
from .entity import PillPalEntity
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
                "set_by_home_assistant": s.get("owner") == grant,
            }
            for s in statuses
        ]
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
    ),
    PillPalSensorDescription(
        key="statuses",
        translation_key="statuses",
        value=_statuses,
        attributes=_status_attributes,
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
