"""The base every Pill Pal entity shares: one device per lamp."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_AVAILABILITY
from .coordinator import PillPalCoordinator


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
