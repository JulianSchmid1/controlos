"""ControlOS - Grow-Kalender je Bereich (Kalender-Entity).

Zeigt automatisch: Phasen-Zeitraeume (aus dem Phasen-Tagebuch), Grow-/
Bluete-Start sowie Notizen mit Faelligkeitsdatum. Eigene Termine koennen
ueber calendar.create_event bzw. das HA-Kalender-Panel angelegt werden
(persistiert im ControlOS-Store).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import (CalendarEntity, CalendarEvent,
                                               CalendarEntityFeature)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .duengerplan import KATEGORIE_ICON, alle_termine
from .entity_base import area_slug, device_info_for


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([ControlosCalendar(entry)])


def _strain_tage(st: dict) -> int | None:
    """Bluetezeit eines Strains in Tagen (unterstuetzt Wochen/Tage +
    Altformat mit 'wochen')."""
    try:
        if "wert" in st:
            wert = int(st.get("wert") or 0)
            return wert * 7 if st.get("einheit") == "Wochen" else wert
        return int(st.get("wochen") or 0) * 7
    except (TypeError, ValueError):
        return None


def _as_date(val) -> date | None:
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except (TypeError, ValueError):
        return None


class ControlosCalendar(CalendarEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-month"
    _attr_name = "Grow-Kalender"
    _attr_supported_features = (CalendarEntityFeature.CREATE_EVENT
                                | CalendarEntityFeature.DELETE_EVENT)

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = "%s_kalender" % entry.entry_id
        self.entity_id = "calendar.controlos_%s_kalender" % area_slug(entry.title)

    @property
    def device_info(self):
        return device_info_for(self._entry)

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _ents(self):
        return (self.hass.data.get(DOMAIN, {})
                .get(self._entry.entry_id, {}).get("entities", {}))

    # -- Ereignisse zusammenstellen ------------------------------------
    def _alle_events(self) -> list[CalendarEvent]:
        evs: list[CalendarEvent] = []
        store = self._store()
        heute = date.today()

        # Marker: Grow-Start / Bluete-Start
        for key, label in (("grow_start", "🌱 Grow-Start"),
                           ("bluete_start", "🌸 Blüte-Start")):
            d = getattr(self._ents().get(key), "native_value", None)
            if isinstance(d, date):
                evs.append(CalendarEvent(start=d, end=d + timedelta(days=1),
                                         summary=label))

        if store:
            # Ernte-Termine je Strain - nur im Growzelt (Mutter-/Stecklingszelt
            # haben keine Ernte, sondern zeigen das Alter der Pflanzen).
            zelt = getattr(self._ents().get("zelt_typ"), "current_option", None)
            if zelt in (None, "Growzelt"):
                typ = getattr(self._ents().get("grow_typ"),
                              "current_option", None) or "Photoperiodisch"
                auto = typ == "Autoflowering"
                # Photoperiodisch: gemeinsamer Blüte-Start (12/12). Autoflower:
                # jeder Strain zählt ab seinem eigenen Anlege-/Startdatum.
                shared = (None if auto else
                          _as_date(getattr(self._ents().get("bluete_start"),
                                           "native_value", None)))
                for st in store.strains(self._entry.entry_id):
                    tage = _strain_tage(st)
                    if tage is None:
                        continue
                    ref = (_as_date(st.get("start") or st.get("added"))
                           if auto else shared)
                    if ref is None:
                        continue
                    ernte = ref + timedelta(days=tage)
                    evs.append(CalendarEvent(
                        start=ernte, end=ernte + timedelta(days=1),
                        summary="🌾 Ernte: %s" % (st.get("name") or "?")))

            # Phasen-Zeitraeume als Balken - nur im Growzelt (Mutter-/Steckling-
            # zelt bleiben in einer Phase). Historie konsolidieren: mehrere
            # Wechsel am selben Tag -> letzter gilt; aufeinanderfolgende
            # gleiche Phasen -> ein durchgehender Balken.
            g = store.grow(self._entry.entry_id)
            if zelt in (None, "Growzelt"):
                raw = sorted((h for h in (g.get("history") or [])
                              if h.get("start")), key=lambda h: h["start"])
                tag = []
                for h in raw:
                    d = _as_date(h["start"])
                    if d is None:
                        continue
                    ph = h.get("phase", "?")
                    if tag and tag[-1][0] == d:
                        tag[-1] = (d, ph)          # selber Tag -> letzter Wechsel
                    else:
                        tag.append((d, ph))
                phasen = []
                for d, ph in tag:
                    if phasen and phasen[-1][1] == ph:
                        continue                    # gleiche Phase -> verlaengern
                    phasen.append((d, ph))
                for i, (start, ph) in enumerate(phasen):
                    end = phasen[i + 1][0] if i + 1 < len(phasen) else heute
                    if end <= start:
                        end = start
                    evs.append(CalendarEvent(
                        start=start, end=end + timedelta(days=1),
                        summary="🌿 %s" % ph))
            else:
                # Mutter-/Stecklingszelt: keine Phasen, sondern je Sorte ein
                # Balken vom Anlege-Datum bis heute (Lebensdauer der Pflanzen).
                icon = "🌿" if zelt == "Mutterzelt" else "🌱"
                for st in store.strains(self._entry.entry_id):
                    start = _as_date(st.get("start") or st.get("added"))
                    if start is None:
                        continue
                    end = heute if heute > start else start
                    evs.append(CalendarEvent(
                        start=start, end=end + timedelta(days=1),
                        summary="%s %s" % (icon, st.get("name") or "?")))

            # Duengeplan: Anwendungs-Termine je Strain (90 Tage voraus)
            typ2 = getattr(self._ents().get("grow_typ"),
                           "current_option", None) or "Photoperiodisch"
            bstart2 = _as_date(getattr(self._ents().get("bluete_start"),
                                       "native_value", None))
            for t in alle_termine(store.duenger_produkte(),
                                  store.strains(self._entry.entry_id),
                                  typ2 == "Autoflowering", bstart2,
                                  heute - timedelta(days=30),
                                  heute + timedelta(days=90)):
                icon = KATEGORIE_ICON.get(t["kategorie"], "💧")
                evs.append(CalendarEvent(
                    start=t["datum"], end=t["datum"] + timedelta(days=1),
                    summary="%s %s – %s" % (icon, t["produkt"], t["strain"]),
                    description=(t.get("typ") or t["kategorie"])))

            # Notizen mit Faelligkeitsdatum
            for t in store.todos(self._entry.entry_id):
                due = _as_date(t.get("due"))
                if due is None:
                    continue
                haken = "✅ " if t.get("status") == "completed" else "📝 "
                evs.append(CalendarEvent(
                    start=due, end=due + timedelta(days=1),
                    summary=haken + t.get("summary", ""),
                    description=t.get("description")))

            # Eigene Termine
            for e in store.events(self._entry.entry_id):
                start = _as_date(e.get("start"))
                end = _as_date(e.get("end")) or start
                if start is None:
                    continue
                if end <= start:
                    end = start + timedelta(days=1)
                evs.append(CalendarEvent(
                    start=start, end=end, summary=e.get("summary", ""),
                    description=e.get("description"), uid=e.get("uid")))

        evs.sort(key=lambda e: e.start)
        return evs

    @property
    def event(self) -> CalendarEvent | None:
        heute = date.today()
        kommende = [e for e in self._alle_events() if e.end > heute]
        return kommende[0] if kommende else None

    async def async_get_events(self, hass, start_date, end_date):
        s = start_date.date() if isinstance(start_date, datetime) else start_date
        e = end_date.date() if isinstance(end_date, datetime) else end_date
        return [ev for ev in self._alle_events()
                if ev.start < e and ev.end > s]

    # -- Eigene Termine anlegen/loeschen --------------------------------
    async def async_create_event(self, **kwargs) -> None:
        store = self._store()
        if not store:
            return
        start = _as_date(kwargs.get("dtstart"))
        end = _as_date(kwargs.get("dtend")) or start
        if start is None:
            return
        events = store.events(self._entry.entry_id)
        events.append({
            "uid": uuid.uuid4().hex,
            "summary": kwargs.get("summary") or "Termin",
            "description": kwargs.get("description"),
            "start": start.isoformat(),
            "end": (end if end and end > start
                    else start + timedelta(days=1)).isoformat(),
        })
        store.set_events(self._entry.entry_id, events)
        self.async_write_ha_state()

    async def async_delete_event(self, uid: str, recurrence_id=None,
                                 recurrence_range=None) -> None:
        store = self._store()
        if not store:
            return
        events = [e for e in store.events(self._entry.entry_id)
                  if e.get("uid") != uid]
        store.set_events(self._entry.entry_id, events)
        self.async_write_ha_state()
