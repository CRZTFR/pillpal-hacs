"""Touches on the lamp, as they happen.

Every tap, double tap and long press outside a pairing window, whatever the lamp did
with it locally (indicators.md, "Touch events"). The attributes say what the lamp was
showing and what it did, so an automation can act only on, say, a long press while a
particular status is showing.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillPalConfigEntry
from .const import GESTURES, SIGNAL_TOUCH
from .entity import PillPalEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: PillPalConfigEntry, add: AddConfigEntryEntitiesCallback
) -> None:
    add([PillPalTouch(entry.runtime_data.coordinator)])


class PillPalTouch(PillPalEntity, EventEntity):
    _attr_translation_key = "touch"
    _attr_event_types = GESTURES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "touch")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_TOUCH.format(device_id=self.coordinator.client.device_id),
                self._touched,
            )
        )

    @callback
    def _touched(self, event: dict[str, Any]) -> None:
        gesture = event.get("gesture")
        if gesture not in GESTURES:
            return
        target = event.get("target") or {}
        attributes = {
            "mode": event.get("mode"),
            "action": event.get("action"),
            "pad": event.get("pad"),
            "target_kind": target.get("kind"),
            "occurrence_id": target.get("id") if target.get("kind") == "occurrence" else None,
            "status_id": target.get("id") if target.get("kind") == "status" else None,
            "status_owner": target.get("owner") if target.get("kind") == "status" else None,
        }
        self._trigger_event(gesture, attributes)
        self.async_write_ha_state()
