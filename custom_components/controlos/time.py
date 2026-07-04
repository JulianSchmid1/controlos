"""ControlOS - Zeit-Entities je Bereich (Licht-Zeitplan)."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, TIME_PARAMS
from .entity_base import area_slug, device_info_for


def _parse(s: str) -> dt_time:
    h, m = s.split(":")
    return dt_time(int(h), int(m))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities(
        ControlosTime(entry, key, cfg) for key, cfg in TIME_PARAMS.items())


class ControlosTime(RestoreEntity, TimeEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key
        self._attr_icon = cfg.get("icon")
        self._attr_native_value = _parse(cfg.get("default", "00:00"))
        self.entity_id = "time.controlos_%s_%s" % (area_slug(entry.title), key)

    @property
    def device_info(self):
        return device_info_for(self._entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state and ":" in last.state:
            try:
                parts = last.state.split(":")
                self._attr_native_value = dt_time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self._entry.entry_id, {})
        data.setdefault("entities", {})[self._key] = self

    async def async_set_value(self, value: dt_time) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
