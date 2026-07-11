"""ControlOS - zentraler persistenter Speicher (.storage/controlos.data).

Haelt: Standard-Phasenprofile (zentral), Bereichs-Overrides je Phase,
Grow-Tracking (Phasen-Start + Historie) je Bereich.
"""
from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STD_PHASE_DEFAULTS

STORAGE_KEY = "controlos.data"
STORAGE_VERSION = 1


class ControlosStore:
    def __init__(self, hass: HomeAssistant):
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict = {"std": {}, "override": {}, "grow": {},
                           "todo": {}, "events": {}, "notify": {},
                           "duenger": {"produkte": [], "erinnert": {}}}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.data = {"std": data.get("std", {}),
                         "override": data.get("override", {}),
                         "grow": data.get("grow", {}),
                         "todo": data.get("todo", {}),
                         "events": data.get("events", {}),
                         "notify": data.get("notify", {}),
                         "duenger": data.get(
                             "duenger", {"produkte": [], "erinnert": {}})}

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 2)

    # -- Standard-Phasen (zentral) --
    def get_std(self, phase: str) -> dict:
        base = dict(STD_PHASE_DEFAULTS.get(phase, {}))
        base.update(self.data["std"].get(phase, {}))
        return base

    def set_std_value(self, phase: str, key: str, value: float) -> None:
        self.data["std"].setdefault(phase, {})[key] = value
        self._save()

    # -- Bereichs-Override je Phase --
    def get_override(self, entry_id: str, phase: str) -> dict | None:
        return self.data["override"].get(entry_id, {}).get(phase)

    def set_override(self, entry_id: str, phase: str, values: dict) -> None:
        self.data["override"].setdefault(entry_id, {})[phase] = dict(values)
        self._save()

    def clear_override(self, entry_id: str, phase: str) -> None:
        self.data["override"].get(entry_id, {}).pop(phase, None)
        self._save()

    def effective_phase(self, entry_id: str, phase: str) -> dict:
        ov = self.get_override(entry_id, phase)
        return dict(ov) if ov else self.get_std(phase)

    # -- Grow-Tracking --
    def grow(self, entry_id: str) -> dict:
        return self.data["grow"].setdefault(
            entry_id, {"phase_start": None, "history": [],
                       "strains": [], "archive": []})

    def set_grow_value(self, entry_id: str, key: str, value) -> None:
        self.grow(entry_id)[key] = value
        self._save()

    # -- Grow-Verwaltung: Strains + Archiv --
    def strains(self, entry_id: str) -> list:
        return list(self.grow(entry_id).get("strains") or [])

    def add_strain(self, entry_id: str, name: str, wert: int,
                   einheit: str = "Wochen", start: str | None = None) -> None:
        heute = date.today().isoformat()
        g = self.grow(entry_id)
        g.setdefault("strains", []).append(
            {"name": str(name or "?").strip(), "wert": int(wert),
             "einheit": einheit, "start": start or heute, "added": heute})
        self._save()

    def remove_strain(self, entry_id: str, index: int) -> None:
        g = self.grow(entry_id)
        lst = g.get("strains") or []
        if 0 <= index < len(lst):
            lst.pop(index)
            self._save()

    def archive_grow(self, entry_id: str, snapshot: dict) -> None:
        """Aktuellen Grow archivieren + aktiven Grow zuruecksetzen."""
        g = self.grow(entry_id)
        arch = g.setdefault("archive", [])
        arch.append(dict(snapshot))
        g["archive"] = arch[-50:]
        g["strains"] = []
        g["history"] = []
        g["phase_start"] = None
        g["grow_start_ref"] = None
        self._save()

    def grow_archive(self, entry_id: str) -> list:
        return list(self.grow(entry_id).get("archive") or [])

    # -- Benachrichtigungs-Zielgeraete (Auswahl) --
    def notify_targets(self, entry_id: str) -> list:
        return list(self.data.setdefault("notify", {}).get(entry_id, []))

    def add_notify_target(self, entry_id: str, dienst: str) -> None:
        lst = self.notify_targets(entry_id)
        if dienst and dienst not in lst:
            lst.append(dienst)
            self.data.setdefault("notify", {})[entry_id] = lst
            self._save()

    def remove_notify_target(self, entry_id: str, index: int) -> None:
        lst = self.notify_targets(entry_id)
        if 0 <= index < len(lst):
            lst.pop(index)
            self.data.setdefault("notify", {})[entry_id] = lst
            self._save()

    # -- Duengeplan (Produkte sind global, Verknuepfung je Bereich/Strain) --
    def duenger_produkte(self) -> list:
        return list(self.data.setdefault(
            "duenger", {"produkte": [], "erinnert": {}}).get("produkte") or [])

    def add_duenger_produkt(self, p: dict) -> None:
        self.data["duenger"].setdefault("produkte", []).append(p)
        self._save()

    def remove_duenger_produkt(self, pid: str) -> None:
        d = self.data["duenger"]
        d["produkte"] = [p for p in d.get("produkte", [])
                         if p.get("id") != pid]
        # Strain-Verknuepfungen in allen Bereichen mit aufraeumen
        for g in self.data["grow"].values():
            for st in g.get("strains") or []:
                if pid in (st.get("duenger") or []):
                    st["duenger"].remove(pid)
        self._save()

    def add_duenger_punkt(self, pid: str, punkt: dict) -> None:
        for p in self.data["duenger"].get("produkte", []):
            if p.get("id") == pid:
                p.setdefault("punkte", []).append(punkt)
                self._save()
                return

    def duenger_link(self, entry_id: str, strain_idx: int, pid: str,
                     verbinden: bool) -> None:
        strains = self.grow(entry_id).get("strains") or []
        if 0 <= strain_idx < len(strains):
            lst = strains[strain_idx].setdefault("duenger", [])
            if verbinden and pid not in lst:
                lst.append(pid)
            elif not verbinden and pid in lst:
                lst.remove(pid)
            self._save()

    def duenger_erinnert(self, key: str):
        return self.data["duenger"].setdefault("erinnert", {}).get(key)

    def duenger_erinnert_alle(self) -> dict:
        return dict(self.data["duenger"].setdefault("erinnert", {}))

    def set_duenger_erinnert(self, key: str, datum: str) -> None:
        e = self.data["duenger"].setdefault("erinnert", {})
        e[key] = datum
        if len(e) > 500:  # uralte Merker kappen
            for k in list(e)[: len(e) - 500]:
                e.pop(k, None)
        self._save()

    def set_phase_start(self, entry_id: str, phase: str, date_iso: str) -> None:
        g = self.grow(entry_id)
        g["phase_start"] = date_iso
        g["history"] = (g.get("history") or [])[-30:]
        g["history"].append({"phase": phase, "start": date_iso})
        self._save()

    # -- Grow-Notizen (Todo) --
    def todos(self, entry_id: str) -> list:
        return list(self.data.setdefault("todo", {}).get(entry_id, []))

    def set_todos(self, entry_id: str, items: list) -> None:
        self.data.setdefault("todo", {})[entry_id] = list(items)
        self._save()

    # -- Kalender-Termine --
    def events(self, entry_id: str) -> list:
        return list(self.data.setdefault("events", {}).get(entry_id, []))

    def set_events(self, entry_id: str, items: list) -> None:
        self.data.setdefault("events", {})[entry_id] = list(items)
        self._save()

    def drop_area(self, entry_id: str) -> None:
        self.data["override"].pop(entry_id, None)
        self.data["grow"].pop(entry_id, None)
        self.data.setdefault("todo", {}).pop(entry_id, None)
        self.data.setdefault("events", {}).pop(entry_id, None)
        self.data.setdefault("notify", {}).pop(entry_id, None)
        self._save()
