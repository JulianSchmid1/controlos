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
from .entity_base import area_slug, device_info_for


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([ControlosCalendar(entry)])


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
            # Phasen-Zeitraeume aus dem Tagebuch
            g = store.grow(self._entry.entry_id)
            hist = sorted((h for h in (g.get("history") or [])
                           if h.get("start")), key=lambda h: h["start"])
            for i, h in enumerate(hist):
                start = _as_date(h["start"])
                if start is None:
                    continue
                if i + 1 < len(hist):
                    end = _as_date(hist[i + 1]["start"]) or start
                else:
                    end = heute
                if end <= start:
                    end = start
                evs.append(CalendarEvent(
                    start=start, end=end + timedelta(days=1),
                    summary="🌿 %s" % h.get("phase", "?")))

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
