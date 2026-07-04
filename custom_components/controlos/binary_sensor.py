"""ControlOS - abgeleitete Binary-Sensoren (Tag/Nacht ...) via Coordinator."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_PARAMS, DOMAIN
from .entity_base import area_slug, device_info_for


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        ControlosDataBinary(coordinator, entry, key, cfg)
        for key, cfg in BINARY_PARAMS.items()
    )


class ControlosDataBinary(CoordinatorEntity, BinarySensorEntity):
    """Vom Coordinator berechneter Binary-Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key
        self._attr_icon = cfg.get("icon")
        if cfg.get("device_class"):
            self._attr_device_class = cfg["device_class"]
        self.entity_id = "binary_sensor.controlos_%s_%s" % (area_slug(entry.title), key)

    @property
    def is_on(self):
        data = self.coordinator.data or {}
        return bool(data.get(self._key))

    @property
    def device_info(self):
        return device_info_for(self._entry)
