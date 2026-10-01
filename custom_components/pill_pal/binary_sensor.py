"""Whether a notify is playing, whoever sent it.

The snapshot reports a notify with the instant it ends (indicators.md, "Reported state").
The lamp may publish no `changed` when it runs out, so the entity schedules its own
redraw for that instant rather than waiting for the next read.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from . import PillPalConfigEntry
from .coordinator import PillPalCoordinator
from .entity import PillPalEntity, set_by, wire_time


async def async_setup_entry(
    hass: HomeAssistant, entry: PillPalConfigEntry, add: AddConfigEntryEntitiesCallback
) -> None:
    add([PillPalNotification(entry.runtime_data.coordinator)])


class PillPalNotification(PillPalEntity, BinarySensorEntity):
    _attr_translation_key = "notification"

    def __init__(self, coordinator: PillPalCoordinator) -> None:
        super().__init__(coordinator, "notification")
        self._unsub_end: CALLBACK_TYPE | None = None

    def _notify(self) -> dict[str, Any] | None:
        notify = ((self.coordinator.data or {}).get("indicators") or {}).get("notify")
        return notify if isinstance(notify, dict) else None

    def _ends_at(self) -> datetime | None:
        notify = self._notify()
        return wire_time(notify.get("endsAt")) if notify else None

    @property
    def is_on(self) -> bool:
        ends = self._ends_at()
        return ends is not None and ends > dt_util.utcnow()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        notify = self._notify()
        if notify is None or not self.is_on:
            return {}
        return {
            "pattern": notify.get("pattern"),
            "color": notify.get("colour"),
            "ends_at": self._ends_at().isoformat(),
            **set_by(self.coordinator.data, notify.get("owner"), self.coordinator.client.grant_id),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_end)
        self._schedule_end()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_end()
        super()._handle_coordinator_update()

    @callback
    def _schedule_end(self) -> None:
        self._cancel_end()
        ends = self._ends_at()
        if ends is not None and ends > dt_util.utcnow():
            self._unsub_end = async_track_point_in_utc_time(self.hass, self._ended, ends)

    @callback
    def _cancel_end(self) -> None:
        if self._unsub_end is not None:
            self._unsub_end()
            self._unsub_end = None

    @callback
    def _ended(self, _now: datetime) -> None:
        self._unsub_end = None
        self.async_write_ha_state()
