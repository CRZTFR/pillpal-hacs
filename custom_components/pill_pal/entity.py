"""The base every Pill Pal entity shares: one device per lamp.

Also how an entity says who set something. Only statuses carry their owner's name
(indicators.md, "Reported state"), so a notify or gauge borrows it from a status the same
grant set, as the app does, and this integration's own grant is always Home Assistant.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_NAME, SIGNAL_AVAILABILITY
from .coordinator import PillPalCoordinator


def wire_time(value: Any) -> datetime | None:
    """A snapshot's milliseconds since the epoch, or None for null or anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def set_by(data: dict[str, Any], owner: Any, grant: int) -> dict[str, Any]:
    label = None
    for status in ((data.get("indicators") or {}).get("statuses")) or []:
        if status.get("owner") == owner and status.get("ownerLabel"):
            label = status["ownerLabel"]
            break
    if label is None and owner == grant:
        label = INTEGRATION_NAME
    return {"set_by": label, "set_by_home_assistant": owner == grant}


class PillPalEntity(CoordinatorEntity[PillPalCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PillPalCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device_id = coordinator.client.device_id
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name="Pill Pal",
            manufacturer="Bindicator",
            model="Pill Pal",
            serial_number=device_id,
            configuration_url=None,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AVAILABILITY.format(device_id=self.coordinator.client.device_id),
                self._availability_changed,
            )
        )

    @callback
    def _availability_changed(self, _connected: bool) -> None:
        # Availability follows the coordinator's last read; the stream only says when to
        # look again. Redraw so a reconnect shows at once.
        self.async_write_ha_state()
