"""ControlOS - gemeinsame Entity-Basis (Persistenz + Device-Zuordnung)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN


def area_slug(name: str) -> str:
    """ASCII-Slug aus dem Bereichsnamen (muss zum JS-Strategie-Slug passen)."""
    out = ""
    for ch in (name or "").lower():
        out += ch if (("a" <= ch <= "z") or ("0" <= ch <= "9")) else "_"
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "bereich"


def device_info_for(entry: ConfigEntry) -> dict:
    """Geraete-Zuordnung (ein Geraet je Bereich/Config-Entry)."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title,
        "manufacturer": "ControlOS",
        "model": "Grow-Bereich",
        "sw_version": "0.1.0",
    }


def store_entity(hass, entry: ConfigEntry, key: str, entity) -> None:
    """Macht eine Entity fuer den (spaeteren) Coordinator auffindbar."""
    data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    data.setdefault("entities", {})[key] = entity


class ControlosBaseEntity(RestoreEntity):
    """Basis aller ControlOS-Bereich-Entities.

    - Gehoert zum Bereichs-Geraet (ein Geraet je Config-Entry).
    - Stabile unique_id (config_entry + key) => HA-Registry bleibt erhalten.
    - Explizite entity_id `controlos_<slug>_<key>` (gut filterbar/zitierbar).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict, platform: str):
        self._entry = entry
        self._key = key
        self._cfg = cfg
        slug = area_slug(entry.title)
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key.replace("_", " ").title()
        self._attr_icon = cfg.get("icon")
        self.entity_id = "%s.controlos_%s_%s" % (platform, slug, key)

    @property
    def device_info(self):
        return device_info_for(self._entry)
