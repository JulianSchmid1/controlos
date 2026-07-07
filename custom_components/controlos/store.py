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
                           "todo": {}, "events": {}}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.data = {"std": data.get("std", {}),
                         "override": data.get("override", {}),
                         "grow": data.get("grow", {}),
                         "todo": data.get("todo", {}),
                         "events": data.get("events", {})}

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
                   einheit: str = "Wochen") -> None:
        g = self.grow(entry_id)
        g.setdefault("strains", []).append(
            {"name": str(name or "?").strip(), "wert": int(wert),
             "einheit": einheit, "added": date.today().isoformat()})
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
        self._save()
