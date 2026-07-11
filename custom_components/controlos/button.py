"""ControlOS - Buttons je Bereich (Phasen-Override speichern/zuruecksetzen)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BUTTON_PARAMS, DOMAIN
from .entity_base import area_slug, device_info_for


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities(
        ControlosButton(entry, key, cfg) for key, cfg in BUTTON_PARAMS.items())


class ControlosButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key
        self._attr_icon = cfg.get("icon")
        self.entity_id = "button.controlos_%s_%s" % (area_slug(entry.title), key)

    @property
    def device_info(self):
        return device_info_for(self._entry)

    async def async_press(self) -> None:
        coord = (self.hass.data.get(DOMAIN, {})
                 .get(self._entry.entry_id, {}).get("coordinator"))
        if coord is None:
            return
        if self._key == "phase_override_speichern":
            await coord.async_save_override()
        elif self._key == "phase_override_reset":
            await coord.async_reset_override()
        elif self._key == "strain_add":
            await coord.async_strain_add()
        elif self._key == "strain_remove":
            await coord.async_strain_remove()
        elif self._key == "grow_neu":
            await coord.async_grow_neu()
        elif self._key == "benachrichtigung_add":
            await coord.async_notify_add()
        elif self._key == "benachrichtigung_remove":
            await coord.async_notify_remove()
        elif self._key == "notiz_anlegen":
            await coord.async_notiz_anlegen()
        elif self._key == "duenger_anlegen":
            await coord.async_duenger_anlegen()
        elif self._key == "duenger_punkt_add":
            await coord.async_duenger_punkt_add()
        elif self._key == "duenger_entfernen":
            await coord.async_duenger_entfernen()
        elif self._key == "duenger_link":
            await coord.async_duenger_link(True)
        elif self._key == "duenger_unlink":
            await coord.async_duenger_link(False)
        elif self._key == "duenger_h_link":
            await coord.async_duenger_hersteller_link(True)
        elif self._key == "duenger_h_unlink":
            await coord.async_duenger_hersteller_link(False)
        elif self._key == "duenger_extra_add":
            await coord.async_duenger_extra_add()
        elif self._key == "duenger_extra_remove":
            await coord.async_duenger_extra_remove()
