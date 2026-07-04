"""ControlOS - Switch-Entities (Aktiv, Vorhanden/Dimmbar-Flags, Modi)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SWITCH_PARAMS
from .entity_base import ControlosBaseEntity, store_entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities(
        ControlosSwitch(entry, key, cfg) for key, cfg in SWITCH_PARAMS.items()
    )


class ControlosSwitch(ControlosBaseEntity, SwitchEntity):
    """Persistente Switch-Entity (Zustand ueberlebt Neustart)."""

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "switch")
        self._attr_is_on = bool(cfg.get("default", False))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
        store_entity(self.hass, self._entry, self._key, self)

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
