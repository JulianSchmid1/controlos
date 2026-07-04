"""ControlOS - Number-Entities.

Bereich: Zielwerte/Toleranzen/Bias (persistent, RestoreNumber).
Hub: Standard-Phasen-Editor-Numbers - Aenderung speichert direkt in das
zentrale Standard-Profil der gerade im Editor gewaehlten Phase.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER_PARAMS, PHASE_KEYS
from .entity_base import ControlosBaseEntity, store_entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    if entry.data.get("hub"):
        async_add_entities(
            StdPhaseNumber(entry, key, NUMBER_PARAMS[key]) for key in PHASE_KEYS)
        return
    async_add_entities(
        ControlosNumber(entry, key, cfg) for key, cfg in NUMBER_PARAMS.items())


class ControlosNumber(ControlosBaseEntity, RestoreNumber):
    """Persistente Number-Entity eines Bereichs."""

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "number")
        self._attr_native_min_value = cfg.get("min", 0)
        self._attr_native_max_value = cfg.get("max", 100)
        self._attr_native_step = cfg.get("step", 1)
        self._attr_native_unit_of_measurement = cfg.get("unit")
        self._attr_mode = (NumberMode.SLIDER if cfg.get("mode") == "slider"
                           else NumberMode.BOX)
        self._attr_native_value = cfg.get("default", 0)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        store_entity(self.hass, self._entry, self._key, self)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class StdPhaseNumber(NumberEntity):
    """Hub: Standard-Wert der im Editor gewaehlten Phase (auto-save)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_std_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key
        self._attr_icon = cfg.get("icon")
        self._attr_native_min_value = cfg.get("min", 0)
        self._attr_native_max_value = cfg.get("max", 100)
        self._attr_native_step = cfg.get("step", 1)
        self._attr_native_unit_of_measurement = cfg.get("unit")
        self._attr_mode = NumberMode.BOX
        self._attr_native_value = cfg.get("default", 0)
        self.entity_id = "number.controlos_std_%s" % key

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)},
                "name": "Phasen-Standard", "manufacturer": "ControlOS",
                "model": "Standard-Profile"}

    def load_value(self, value: float) -> None:
        """Vom Editor-Select gesetzt (Phase gewechselt) - ohne Store-Write."""
        self._attr_native_value = value
        if self.hass:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self._entry.entry_id, {})
        data.setdefault("entities", {})["std_%s" % self._key] = self
        # Initialwert aus dem Store der aktuell gewaehlten Editor-Phase
        store = self.hass.data.get(DOMAIN, {}).get("store")
        editor = data.get("entities", {}).get("std_phase_editor")
        if store and editor is not None and editor.current_option:
            vals = store.get_std(editor.current_option)
            if self._key in vals:
                self._attr_native_value = float(vals[self._key])

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        store = self.hass.data.get(DOMAIN, {}).get("store")
        editor = (self.hass.data.get(DOMAIN, {})
                  .get(self._entry.entry_id, {}).get("entities", {})
                  .get("std_phase_editor"))
        if store and editor is not None and editor.current_option:
            store.set_std_value(editor.current_option, self._key, value)
