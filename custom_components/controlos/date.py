"""ControlOS - Datums-Entities je Bereich (Grow-Kalender).

grow_start   = Beginn des Grows (Basis fuer "Grow-Tag")
bluete_start = Beginn der Bluete (Basis fuer "Bluete-Tag"; wird von der
               Automatik gesetzt, wenn leer - manuell jederzeit korrigierbar)
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity_base import area_slug, device_info_for

DATE_PARAMS = {
    "grow_start":   {"name": "Grow-Startdatum",  "icon": "mdi:calendar-start"},
    "bluete_start": {"name": "Blüte-Startdatum", "icon": "mdi:flower"},
    "strain_start": {"name": "Strain-Startdatum", "icon": "mdi:calendar-plus"},
    "notiz_datum":  {"name": "Notiz fällig am",   "icon": "mdi:calendar-alert"},
    # Fuer den Ernten-Button: leer = heute; nachtraeglich korrigierbar
    # (Strain waehlen, Datum setzen, erneut "ernten" druecken)
    "ernte_datum":  {"name": "Ernte-Datum (leer = heute)",
                     "icon": "mdi:calendar-edit"},
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities(
        ControlosDate(entry, key, cfg) for key, cfg in DATE_PARAMS.items())


class ControlosDate(RestoreEntity, DateEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg["name"]
        self._attr_icon = cfg["icon"]
        self._attr_native_value = None
        self.entity_id = "date.controlos_%s_%s" % (area_slug(entry.title), key)

    @property
    def device_info(self):
        return device_info_for(self._entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state:
            try:
                self._attr_native_value = date.fromisoformat(last.state)
            except ValueError:
                pass
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self._entry.entry_id, {})
        data.setdefault("entities", {})[self._key] = self

    def set_internal(self, value: date | None) -> None:
        """Vom Coordinator gesetzt (Auto-Start/Reset), ohne Refresh-Schleife."""
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        coord = (self.hass.data.get(DOMAIN, {})
                 .get(self._entry.entry_id, {}).get("coordinator"))
        if coord:
            await coord.async_request_refresh()
