"""ControlOS - native Home-Assistant-Integration (Grow-Bereiche).

Ein Config-Entry = ein Bereich (= ein Geraet). Zusaetzlich ein Hub-Entry
"Phasen-Standard" (zentrale Standard-Phasenprofile, automatisch angelegt).

Services: controlos.add_area {name} / controlos.remove_area {entry_id}
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import ControlosCoordinator
from .store import ControlosStore

_LOGGER = logging.getLogger(__name__)

HUB_PLATFORMS = ["number", "select"]


def is_hub(entry: ConfigEntry) -> bool:
    return bool(entry.data.get("hub"))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    data = hass.data.setdefault(DOMAIN, {})
    store = ControlosStore(hass)
    await store.async_load()
    data["store"] = store

    async def _add_area(call: ServiceCall) -> None:
        name = (call.data.get("name") or "").strip()
        if name:
            await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data={"name": name})

    async def _remove_area(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        if hass.config_entries.async_get_entry(entry_id):
            await hass.config_entries.async_remove(entry_id)
            store.drop_area(entry_id)
        else:
            _LOGGER.warning("remove_area: unbekannte entry_id %s", entry_id)

    hass.services.async_register(
        DOMAIN, "add_area", _add_area,
        schema=vol.Schema({vol.Required("name"): cv.string}))
    hass.services.async_register(
        DOMAIN, "remove_area", _remove_area,
        schema=vol.Schema({vol.Required("entry_id"): cv.string}))

    # Hub "Phasen-Standard" automatisch anlegen (einmalig)
    if not any(is_hub(e) for e in hass.config_entries.async_entries(DOMAIN)):
        hass.async_create_task(hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data={"hub": True}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if is_hub(entry):
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"entities": {}}
        await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
        _LOGGER.info("ControlOS Phasen-Standard eingerichtet")
        return True

    coordinator = ControlosCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "entities": {}, "coordinator": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_refresh()
    # Einstellungsaenderungen sofort uebernehmen (statt bis zu einen Tick warten)
    unsub = coordinator.setup_change_listener()
    if unsub:
        entry.async_on_unload(unsub)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("ControlOS-Bereich eingerichtet: %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = HUB_PLATFORMS if is_hub(entry) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
