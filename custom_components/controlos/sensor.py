"""ControlOS - abgeleitete Sensoren (Temp/VPD/CO2/Ziel ...) via Coordinator."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_PARAMS, SHADOW_KEYS
from .entity_base import area_slug, device_info_for

_SHADOW_ICONS = {"status": "mdi:radar", "licht": "mdi:lightbulb-on",
                 "undercanopy": "mdi:lightbulb-group",
                 "uv": "mdi:sun-wireless",
                 "befeuchter": "mdi:air-humidifier",
                 "entfeuchter": "mdi:air-humidifier-off", "heizung": "mdi:radiator",
                 "klima": "mdi:air-conditioner", "abluft": "mdi:fan",
                 "co2": "mdi:molecule-co2", "ventilator": "mdi:fan-chevron-up",
                 "umluft": "mdi:weather-windy"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    ents = [ControlosDataSensor(coordinator, entry, key, cfg)
            for key, cfg in SENSOR_PARAMS.items()]
    ents += [ControlosDataSensor(
        coordinator, entry, "shadow_%s" % k,
        {"name": ("Steuerung %s" % k.capitalize()) if k != "status" else "Status",
         "icon": _SHADOW_ICONS.get(k)})
        for k in SHADOW_KEYS]
    async_add_entities(ents)


class ControlosDataSensor(CoordinatorEntity, SensorEntity):
    """Vom Coordinator berechneter Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = "%s_%s" % (entry.entry_id, key)
        self._attr_name = cfg.get("name") or key
        self._attr_icon = cfg.get("icon")
        self._attr_native_unit_of_measurement = cfg.get("unit")
        if cfg.get("device_class"):
            self._attr_device_class = cfg["device_class"]
        # Messwerte -> HA-Langzeitstatistik (unbegrenzt aufbewahrt)
        if key.startswith("data_") and key != "data_tag_nacht":
            self._attr_state_class = "measurement"
        self.entity_id = "sensor.controlos_%s_%s" % (area_slug(entry.title), key)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get(self._key)

    @property
    def icon(self):
        if self._key == "data_tag_nacht":
            return ("mdi:weather-sunny" if self.native_value == "Tag"
                    else "mdi:weather-night")
        return self._attr_icon

    @property
    def extra_state_attributes(self):
        if self._key == "grow_tag":
            data = self.coordinator.data or {}
            return {"phasen_historie": data.get("_history", []),
                    "strains": data.get("_strains", []),
                    "grow_archiv": data.get("_grow_archive", []),
                    "notify_targets": data.get("_notify_targets", [])}
        if self._key == "ki_vpd_prognose":
            data = self.coordinator.data or {}
            return {"prognose": data.get("_ki_prognose", [])}
        return None

    @property
    def device_info(self):
        return device_info_for(self._entry)
