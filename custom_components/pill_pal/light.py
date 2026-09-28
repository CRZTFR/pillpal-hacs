"""The lamp's ambient light.

A due reminder keeps signalling whatever this does; ambient changes update what the lamp
returns to once reminders end (development plan, "What the Home Assistant grant may do").
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillPalConfigEntry
from .api import PillPalError
from .const import DOMAIN, SCENE_CUSTOM, SCENES
from .entity import PillPalEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: PillPalConfigEntry, add: AddConfigEntryEntitiesCallback
) -> None:
    add([PillPalAmbient(entry.runtime_data.coordinator)])


def _rgb(text: str | None) -> tuple[int, int, int] | None:
    if not text or len(text) != 7 or not text.startswith("#"):
        return None
    try:
        return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
    except ValueError:
        return None


class PillPalAmbient(PillPalEntity, LightEntity):
    _attr_translation_key = "ambient"
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = SCENES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ambient")

    @property
    def _ambient(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("ambient") or {}

    @property
    def is_on(self) -> bool | None:
        return self._ambient.get("on")

    @property
    def brightness(self) -> int | None:
        return self._ambient.get("level")

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return _rgb(self._ambient.get("colour"))

    @property
    def effect(self) -> str | None:
        scene = self._ambient.get("scene")
        if isinstance(scene, int) and 0 <= scene < len(SCENES):
            return SCENES[scene]
        return None

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            await self.coordinator.client.command("set_ambient", payload)
        except PillPalError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refused",
                translation_placeholders={"outcome": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"on": True}
        if ATTR_BRIGHTNESS in kwargs:
            payload["level"] = int(kwargs[ATTR_BRIGHTNESS])
        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            payload["colour"] = f"#{red:02x}{green:02x}{blue:02x}"
            payload["scene"] = SCENE_CUSTOM
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in SCENES:
            payload["scene"] = SCENES.index(kwargs[ATTR_EFFECT])
        await self._send(payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"on": False})
