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

from .const import (DOMAIN, DUENGER_TYPEN, PHASES, SELECT_DEVICE_PARAMS,
                    SELECT_PARAMS,
                    VEG_ZYKLEN, ZELT_PHASES)
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
    ents.append(NotifyRemoveSelect(entry))
    ents.append(StrainSelect(entry))
    ents.append(DuengerTypSelect(entry))
    ents.append(DuengerProduktSelect(entry))
    ents.append(DuengerStrainSelect(entry))
    ents.append(DuengerHerstellerSelect(entry))
    ents.append(DuengerExtraSelect(entry))
    ents.append(DuengerMengeEinheitSelect(entry))
    ents.append(DuengerRegelSelect(entry))
    async_add_entities(ents)


class ControlosSelect(ControlosBaseEntity, SelectEntity):
    """Modus-Select mit festen Optionen."""

    def __init__(self, entry: ConfigEntry, key: str, cfg: dict):
        super().__init__(entry, key, cfg, "select")
        self._attr_options = list(cfg.get("options", []))
        self._full_options = list(self._attr_options)
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

    def _coord(self):
        return (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("coordinator"))

    def refresh_options(self) -> None:
        # Zelt-Typ beschraenkt: wuchsphase/phase_editor auf die erlaubten Phasen,
        # licht_zyklus im Mutter-/Stecklingszelt auf vegetative Zyklen.
        if self._key not in ("wuchsphase", "phase_editor", "licht_zyklus"):
            return
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        zt = getattr(ents.get("zelt_typ"), "current_option", None)
        if self._key == "licht_zyklus":
            allowed = (list(VEG_ZYKLEN) if zt in ("Mutterzelt", "Stecklingszelt")
                       else list(self._full_options))
        else:
            allowed = list(ZELT_PHASES.get(zt, self._full_options))
        snap = self._attr_current_option not in allowed
        if allowed == self._attr_options and not snap:
            return
        self._attr_options = allowed
        if snap and allowed:
            self._attr_current_option = allowed[0]
            self.async_write_ha_state()
            coord = self._coord()
            if coord and self._key == "wuchsphase":
                self.hass.async_create_task(
                    coord.async_on_phase_change(allowed[0]))
            elif coord and self._key == "phase_editor":
                self.hass.async_create_task(
                    coord.async_on_phase_editor_change(allowed[0]))
            # licht_zyklus: kein Hook noetig (Coordinator leitet Ende im Tick ab)
        else:
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        changed = option != self._attr_current_option
        self._attr_current_option = option
        self.async_write_ha_state()
        if not changed:
            return
        coord = self._coord()
        if not coord:
            return
        # Wuchsphase gewechselt -> Phasenprofil laden (Override sonst Standard)
        if self._key == "wuchsphase":
            self.hass.async_create_task(coord.async_on_phase_change(option))
        # Phasen-Editor gewechselt -> Profil in die pe_-Regler laden (nur Anzeige)
        elif self._key == "phase_editor":
            self.hass.async_create_task(coord.async_on_phase_editor_change(option))
        # Zelt-Typ gewechselt -> Tick anstossen (beschraenkt die Phasen-Optionen)
        elif self._key == "zelt_typ":
            self.hass.async_create_task(coord.async_request_refresh())


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


class StrainSelect(ControlosBaseEntity, SelectEntity):
    """Auswahl eines Strains des aktiven Grows (zum Entfernen).

    Optionen kommen dynamisch aus dem Store (Coordinator ruft refresh_options)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "strain_auswahl",
                         {"name": "Strain (zum Entfernen)", "icon": "mdi:cannabis"},
                         "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        strains = store.strains(self._entry.entry_id) if store else []
        opts = ["%d. %s" % (i + 1, s.get("name") or "?")
                for i, s in enumerate(strains)]
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_index(self) -> int:
        """0-basierter Index des gewaehlten Strains, -1 wenn keiner."""
        try:
            return self._attr_options.index(self._attr_current_option)
        except ValueError:
            return -1


class DuengerTypSelect(ControlosBaseEntity, SelectEntity):
    """Produkt-Typ; Optionen haengen von der gewaehlten Kategorie ab."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_typ",
                         {"name": "Typ", "icon": "mdi:tag"}, "select")
        self._attr_options = list(DUENGER_TYPEN["Dünger"])
        self._attr_current_option = self._attr_options[0]

    def _compute(self) -> list[str]:
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        kat = getattr(ents.get("duenger_kategorie"), "current_option", None)
        return list(DUENGER_TYPEN.get(kat or "Dünger", DUENGER_TYPEN["Dünger"]))

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()


class DuengerProduktSelect(ControlosBaseEntity, SelectEntity):
    """Auswahl eines angelegten Duengeplan-Produkts (global)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_produkt",
                         {"name": "Produkt (Auswahl)",
                          "icon": "mdi:bottle-tonic-outline"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        prod = store.duenger_produkte() if store else []
        opts = ["%d. %s" % (i + 1, p.get("name") or "?")
                for i, p in enumerate(prod)]
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_id(self) -> str | None:
        """Produkt-ID der aktuellen Auswahl (None wenn keine)."""
        store = self._store()
        if not store:
            return None
        prod = store.duenger_produkte()
        try:
            idx = self._attr_options.index(self._attr_current_option)
        except ValueError:
            return None
        return prod[idx].get("id") if 0 <= idx < len(prod) else None


class DuengerStrainSelect(ControlosBaseEntity, SelectEntity):
    """Strain-Auswahl fuer die Duenger-Verknuepfung (eigener Select, damit
    der Entfernen-Select der Grow-Verwaltung unberuehrt bleibt)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_strain",
                         {"name": "Strain (für Verknüpfung)",
                          "icon": "mdi:cannabis"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        strains = store.strains(self._entry.entry_id) if store else []
        opts = ["%d. %s" % (i + 1, s.get("name") or "?")
                for i, s in enumerate(strains)]
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_index(self) -> int:
        try:
            return self._attr_options.index(self._attr_current_option)
        except ValueError:
            return -1


class DuengerRegelSelect(ControlosBaseEntity, SelectEntity):
    """Anwendungs-Regeln des gewaehlten Produkts (zum Entfernen)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_regel_sel",
                         {"name": "Regel (zum Entfernen)",
                          "icon": "mdi:format-list-numbered"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        from .duengerplan import menge_einheit, regel_txt
        store = self._store()
        if not store:
            return ["—"]
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        psel = ents.get("duenger_produkt")
        pid = psel.selected_id() if psel is not None else None
        p = next((x for x in store.duenger_produkte()
                  if x.get("id") == pid), None)
        if not p:
            return ["—"]
        opts = ["%d. %s" % (i + 1, regel_txt(r, menge_einheit(p)))
                for i, r in enumerate(p.get("regeln") or [])]
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_index(self) -> int:
        try:
            return self._attr_options.index(self._attr_current_option)
        except ValueError:
            return -1


class DuengerMengeEinheitSelect(ControlosBaseEntity, SelectEntity):
    """Mengen-Einheit; Optionen folgen der Form: Fluessig = ml/L,
    Trocken = g/kg."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_menge_einheit",
                         {"name": "Mengen-Einheit", "icon": "mdi:scale"},
                         "select")
        self._attr_options = ["ml", "L"]
        self._attr_current_option = "ml"

    def _compute(self) -> list[str]:
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        form = getattr(ents.get("duenger_form"), "current_option", "") or ""
        return ["g", "kg"] if form.startswith("Trocken") else ["ml", "L"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("ml", "L", "g", "kg"):
            self._attr_current_option = last.state
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()


class DuengerHerstellerSelect(ControlosBaseEntity, SelectEntity):
    """Hersteller-Auswahl (dynamisch aus den angelegten Produkten)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_hersteller_sel",
                         {"name": "Hersteller (Methode)",
                          "icon": "mdi:factory"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        if not store:
            return ["—"]
        # Angelegte Hersteller + die aus bestehenden Produkten
        opts = set(store.hersteller_liste())
        opts |= {(p.get("hersteller") or "").strip()
                 for p in store.duenger_produkte()}
        return sorted(opts - {""}) or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()


class DuengerExtraSelect(ControlosBaseEntity, SelectEntity):
    """Extra-Regeln des gerade gewaehlten Strains (zum Entfernen)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "duenger_extra_sel",
                         {"name": "Extra-Regel (zum Entfernen)",
                          "icon": "mdi:star"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        if not store:
            return ["—"]
        ents = (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))
        ssel = ents.get("duenger_strain")
        idx = ssel.selected_index() if ssel is not None else -1
        strains = store.strains(self._entry.entry_id)
        if not (0 <= idx < len(strains)):
            return ["—"]
        pmap = {p.get("id"): p.get("name", "?")
                for p in store.duenger_produkte()}
        opts = []
        for i, r in enumerate(strains[idx].get("extra_regeln") or []):
            if r.get("modus") == "Wiederholend":
                plan = "alle %s %s" % (r.get("intervall"), r.get("einheit"))
            else:
                plan = "%s %s %s" % (r.get("phase"), r.get("einheit"),
                                     r.get("wert"))
            art = " · ersetzt" if r.get("art") == "ersetzt" else ""
            opts.append("%d. %s (%s%s)" % (i + 1,
                                           pmap.get(r.get("pid"), "?"),
                                           plan, art))
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_index(self) -> int:
        try:
            return self._attr_options.index(self._attr_current_option)
        except ValueError:
            return -1


class NotifyTargetSelect(RestoreEntity, SelectEntity):
    """Geraete-Picker fuer die Benachrichtigungs-Auswahl (ein mobile_app-Gerat,
    das per Button zur Ziel-Liste hinzugefuegt wird). Optionen dynamisch aus den
    notify-Diensten der Companion-Apps."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:cellphone-message"
    _attr_name = "Zielgerät wählen"

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = "%s_benachrichtigung_geraet" % entry.entry_id
        self._attr_options = ["—"]
        self._attr_current_option = "—"
        self.entity_id = ("select.controlos_%s_benachrichtigung_geraet"
                          % area_slug(entry.title))

    @property
    def device_info(self):
        return device_info_for(self._entry)

    def _compute(self) -> list[str]:
        dienste = self.hass.services.async_services().get("notify", {})
        apps = sorted(k for k in dienste if k.startswith("mobile_app_"))
        return apps or ["—"]

    def refresh_options(self) -> None:
        neu = self._compute()
        if neu != self._attr_options:
            self._attr_options = neu
            if self._attr_current_option not in neu:
                self._attr_current_option = neu[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state
        else:
            self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, "benachrichtigung_geraet", self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_service(self) -> str | None:
        cur = self._attr_current_option
        return cur if cur and cur != "—" else None


class NotifyRemoveSelect(ControlosBaseEntity, SelectEntity):
    """Auswahl eines Zielgeraets aus der Benachrichtigungs-Liste (zum Entfernen).
    Optionen dynamisch aus dem Store (Coordinator ruft refresh_options)."""

    def __init__(self, entry: ConfigEntry):
        super().__init__(entry, "benachrichtigung_entfernen",
                         {"name": "Zielgerät (zum Entfernen)",
                          "icon": "mdi:cellphone-remove"}, "select")
        self._attr_options = ["—"]
        self._attr_current_option = "—"

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _compute(self) -> list[str]:
        store = self._store()
        ziele = store.notify_targets(self._entry.entry_id) if store else []
        opts = ["%d. %s" % (i + 1, d.replace("mobile_app_", ""))
                for i, d in enumerate(ziele)]
        return opts or ["—"]

    def refresh_options(self) -> None:
        new = self._compute()
        if new != self._attr_options:
            self._attr_options = new
            if self._attr_current_option not in new:
                self._attr_current_option = new[0]
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_options = self._compute()
        self._attr_current_option = self._attr_options[0]
        store_entity(self.hass, self._entry, self._key, self)

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()

    def selected_index(self) -> int:
        try:
            return self._attr_options.index(self._attr_current_option)
        except ValueError:
            return -1


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
