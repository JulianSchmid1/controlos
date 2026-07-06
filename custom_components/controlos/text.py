"""ControlOS - Text-Entities je Bereich (Grow-Verwaltung).

Freitext-Eingaben (Grow-Name, Strain-Name), persistent via RestoreEntity.
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TEXT_PARAMS
from .entity_base import ControlosBaseEntity, store_entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    if entry.data.get("hub"):
        return
    async_add_entities(
        ControlosText(entry, key, cfg) for key, cfg in TEXT_PARAMS.items())


class ControlosText(ControlosBaseEntity, TextEntity):
    """Persistente Freitext-Entity eines Bereichs."""

    _attr_native_min = 0
    _attr_native_max = 60
    _attr_mode = TextMode.TEXT

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "text")
        self._attr_native_value = cfg.get("default", "")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            self._attr_native_value = last.state
        store_entity(self.hass, self._entry, self._key, self)

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
