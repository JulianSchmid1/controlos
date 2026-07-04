"""ControlOS - Select-Entities.

Bereich: Modus-Selects (statisch) + Geraete-Auswahl (dynamische Optionen).
Hub: Phasen-Editor-Select (laedt die Standard-Werte der gewaehlten Phase
in die std-Number-Entities).
Wuchsphasen-Select triggert das automatische Laden des Phasenprofils.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, PHASES, SELECT_DEVICE_PARAMS, SELECT_PARAMS
from .entity_base import (ControlosBaseEntity, area_slug, device_info_for,
                          store_entity)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    if entry.data.get("hub"):
        ents = [StdPhaseEditorSelect(entry)]
        ents += [HubDesignSelect(entry, k, c) for k, c in DESIGN_SELECTS.items()]
        async_add_entities(ents)
        return
    ents = [ControlosSelect(entry, k, c) for k, c in SELECT_PARAMS.items()]
    ents += [ControlosDeviceSelect(entry, k, c) for k, c in SELECT_DEVICE_PARAMS.items()]
    ents.append(NotifyTargetSelect(entry))
    async_add_entities(ents)


class ControlosSelect(ControlosBaseEntity, SelectEntity):
    """Modus-Select mit festen Optionen."""

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "select")
        self._attr_options = list(cfg.get("options", []))
        default = cfg.get("default")
        self._attr_current_option = (
            default if default in self._attr_options
            else (self._attr_options[0] if self._attr_options else None))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        changed = option != self._attr_current_option
        self._attr_current_option = option
        self.async_write_ha_state()
        # Wuchsphase gewechselt -> Phasenprofil laden (Override sonst Standard)
        if changed and self._key == "wuchsphase":
            coord = (self.hass.data.get(DOMAIN, {})
                     .get(self._entry.entry_id, {}).get("coordinator"))
            if coord:
                self.hass.async_create_task(coord.async_on_phase_change(option))


class ControlosDeviceSelect(ControlosBaseEntity, SelectEntity):
    """Geraete-/Sensor-Auswahl mit dynamischen Optionen (Domain-gefiltert)."""

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "select")
        self._domains = cfg.get("domains", [])
        self._attr_current_option = "Keine"
        self._attr_options = ["Keine"]

    def _compute(self) -> list[str]:
        opts = [eid for eid in self.hass.states.async_entity_ids()
                if eid.split(".", 1)[0] in self._domains]
        opts = ["Keine"] + sorted(opts)
        cur = self._attr_current_option
        if cur and cur not in opts:
            opts.append(cur)
        return opts

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state:
            self._attr_current_option = last.state
        self._attr_options = self._compute()
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        if option not in self._attr_options:
            self._attr_options = self._compute()
        self.async_write_ha_state()


class NotifyTargetSelect(RestoreEntity, SelectEntity):
    """Ziel fuer Benachrichtigungen: alle Geraete oder ein bestimmtes Handy.

    Optionen werden dynamisch aus den notify-Diensten der Companion-Apps
    befuellt (mobile_app_*), aktualisiert vom Coordinator-Tick."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:cellphone-message"
    _attr_name = "Benachrichtigungs-Ziel"

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = "%s_benachrichtigung_ziel" % entry.entry_id
        self._attr_options = ["Alle Geräte"]
        self._attr_current_option = "Alle Geräte"
        self.entity_id = ("select.controlos_%s_benachrichtigung_ziel"
                          % area_slug(entry.title))

    @property
    def device_info(self):
        return device_info_for(self._entry)

    def _compute(self) -> list[str]:
        dienste = self.hass.services.async_services().get("notify", {})
        return ["Alle Geräte"] + sorted(
            k for k in dienste if k.startswith("mobile_app_"))

    def refresh_options(self) -> None:
        neu = self._compute()
        if neu != self._attr_options:
            self._attr_options = neu
            if self._attr_current_option not in neu:
                self._attr_current_option = "Alle Geräte"
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        last = await self.async_get_last_state()
        if last is not None and last.state:
            self._attr_current_option = (
                last.state if last.state in self._attr_options
                else "Alle Geräte")
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self._entry.entry_id, {})
        data.setdefault("entities", {})["benachrichtigung_ziel"] = self

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()


DESIGN_SELECTS = {
    "design_stil": {
        "name": "Karten-Stil", "icon": "mdi:palette-swatch",
        "options": ["Bubble Groß", "Bubble Kompakt"],
        "default": "Bubble Groß"},
    "design_hintergrund": {
        "name": "Akzentfarbe", "icon": "mdi:format-color-fill",
        "options": ["Standard", "Grün", "Blau", "Violett", "Orange", "Rot"],
        "default": "Standard"},
}


class HubDesignSelect(RestoreEntity, SelectEntity):
    """Hub: globale Dashboard-Design-Einstellungen (liest die Strategie)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg["name"]
        self._attr_icon = cfg["icon"]
        self._attr_options = list(cfg["options"])
        self._attr_current_option = cfg["default"]
        self.entity_id = "select.controlos_%s" % key

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)},
                "name": "Phasen-Standard", "manufacturer": "ControlOS",
                "model": "Standard-Profile"}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()


class StdPhaseEditorSelect(RestoreEntity, SelectEntity):
    """Hub: Phase waehlen -> Standard-Werte in die std-Numbers laden."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:sprout-outline"
    _attr_name = "Phase wählen (Standard bearbeiten)"

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = "%s_std_phase_editor" % entry.entry_id
        self._attr_options = list(PHASES)
        self._attr_current_option = PHASES[1]  # Vegetation
        self.entity_id = "select.controlos_std_phase_editor"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)},
                "name": "Phasen-Standard", "manufacturer": "ControlOS",
                "model": "Standard-Profile"}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self._entry.entry_id, {})
        data.setdefault("entities", {})["std_phase_editor"] = self
        await self._load_phase()

    async def _load_phase(self) -> None:
        store = self.hass.data.get(DOMAIN, {}).get("store")
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        if not store:
            return
        values = store.get_std(self._attr_current_option)
        for key, val in values.items():
            e = ents.get("std_%s" % key)
            if e is not None:
                e.load_value(float(val))

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()
            await self._load_phase()
