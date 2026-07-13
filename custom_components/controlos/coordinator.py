"""ControlOS - Coordinator: abgeleitete Sensoren + Regelung + Grow-Tracking.

Je Tick (30s): Geraete-Select-Optionen aktualisieren, abgeleitete Werte
berechnen, Regelung (regelung.Regler, 1:1 vom Add-on portiert) laufen lassen.
Betriebsmodus je Bereich: "Monitor" = nur Shadow-Sensoren, "Steuern" = echte
Service-Calls auf die zugeordneten Geraete (inkl. Klima-LIVE).
"""
from __future__ import annotations

import logging
import math
import time as _time
import uuid as _uuid
from datetime import date, datetime, timedelta
from datetime import time as dt_time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import (async_track_state_change_event,
                                          async_track_time_interval)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (DOMAIN, MQTT_BROKER_ADDON, MQTT_RESTART_COOLDOWN_S,
                    PHASE_KEYS, UPDATE_INTERVAL)
from .duengerplan import (KATEGORIE_ICON, alle_termine, menge_einheit,
                          menge_txt, regel_txt, termine_gruppiert)
from .entity_base import area_slug
from .ki import MIN_ROWS as KI_MIN_ROWS, KiEngine
from .regelung import Regler

_LOGGER = logging.getLogger(__name__)

_INVALID = ("unknown", "unavailable", "none", "")


def _vpd(t, rh, tl):
    if t is None or rh is None or tl is None:
        return None
    svp_blatt = 0.6108 * math.e ** (17.27 * tl / (tl + 237.3))
    svp_luft = 0.6108 * math.e ** (17.27 * t / (t + 237.3))
    return round(svp_blatt - svp_luft * rh / 100.0, 2)


class _Ctx:
    """Zugriffsschicht der Regelung auf Entities + HA-States."""

    def __init__(self, hass, ents):
        self._h = hass
        self._e = ents

    def num(self, key, default=0.0):
        e = self._e.get(key)
        try:
            return float(e.native_value)
        except (AttributeError, TypeError, ValueError):
            return default

    def sel_raw(self, key):
        e = self._e.get(key)
        return getattr(e, "current_option", None)

    def sel(self, key):
        v = self.sel_raw(key)
        return None if (not v or v == "Keine") else v

    def sw(self, key):
        e = self._e.get(key)
        return bool(getattr(e, "is_on", False))

    def state(self, eid):
        if not eid:
            return None
        st = self._h.states.get(eid)
        return st.state if st else None

    def attr(self, eid, key, default=None):
        if not eid:
            return default
        st = self._h.states.get(eid)
        return (st.attributes.get(key, default)) if st else default

    def fnum(self, eid):
        s = self.state(eid)
        if s is None or s.lower() in _INVALID:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def t(self, key):
        """datetime.time einer Zeit-Entity (oder None)."""
        e = self._e.get(key)
        return getattr(e, "native_value", None)


class ControlosCoordinator(DataUpdateCoordinator):
    """Ein Coordinator je Bereich (Config-Entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass, _LOGGER, name="controlos_%s" % entry.entry_id,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.entry = entry
        self.regler = Regler(entry.title)
        self._last_dev: dict = {}
        self.ki = KiEngine(hass.config.path("controlos_data"),
                           area_slug(entry.title))
        self._vpd_hist: list = []      # (ts, vpd) der letzten ~6 min
        self._ki_training = False
        self._ki_cleanup_ts = 0.0
        self._alerts: dict = {}        # Alarm-Key -> zuletzt gemeldet (ts)
        self._alert_on: dict = {}      # Alarm-Key -> aktueller Zustand
        self._dev_track: dict = {}     # geraet_*-Select -> zuletzt zugewiesen
        self._pe_loaded = False        # Phasen-Editor-Werte initial geladen?
        self._ramp_last: dict = {}     # Rampen-Ticker: zuletzt gesendetes %
        self._vpd_glatt: list = []     # (ts, vpd) der letzten ~5 min

    # -- Zugriff --
    def _ents(self):
        return (self.hass.data.get(DOMAIN, {})
                .get(self.entry.entry_id, {}).get("entities", {}))

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    # Entities, die der Coordinator SELBST je Tick schreibt -> nicht als
    # Ausloeser beobachten (sonst Rueckkopplung, v.a. der zerfallende Bias).
    _SELF_WRITTEN = frozenset((
        "vpd_bias_tag", "vpd_bias_nacht", "temp_bias_tag", "temp_bias_nacht",
        "hum_bias_tag", "hum_bias_nacht", "licht_ende", "bluete_start"))
    # Nur echte Eingabe-Entities beobachten (keine Sensor-Ausgaben, die sich
    # jeden Tick aendern und sonst eine Endlosschleife ausloesen wuerden).
    _INPUT_DOMAINS = ("select", "switch", "number", "time", "date", "text")

    def setup_change_listener(self):
        """Sofort neu regeln, sobald der Nutzer eine Einstellung aendert,
        statt bis zu einen 30s-Tick zu warten (async_request_refresh ist
        entprellt, mehrere Aenderungen werden zusammengefasst)."""
        ids = []
        for key, ent in self._ents().items():
            eid = getattr(ent, "entity_id", None)
            if (eid and key not in self._SELF_WRITTEN
                    and eid.split(".", 1)[0] in self._INPUT_DOMAINS):
                ids.append(eid)
        if not ids:
            return None

        async def _changed(_event):
            await self.async_request_refresh()

        return async_track_state_change_event(self.hass, ids, _changed)

    # -- Sonnenauf-/-untergang: feiner Dimm-Ticker -----------------------
    def _aktive_rampe(self, ctx):
        """(name, dimmer_eid, pct) fuer die gerade aktive Sonnenrampe,
        sonst None. Gleiche Formel/ Rundung wie die Regelung."""
        if not (ctx.sw("aktiv")
                and ctx.sel_raw("betriebsmodus") == "Steuern"
                and (ctx.sel_raw("licht_modus") or "An/Aus")
                == "Sonnenauf-/-untergang"):
            return None
        l_start, l_ende = ctx.t("licht_start"), ctx.t("licht_ende")
        if not (l_start and l_ende):
            return None
        in_win, since, until, _ = Regler._licht_window(
            datetime.now().time(), l_start, l_ende)
        sunrise = int(ctx.num("sunrise_dauer", 30))
        sunset = int(ctx.num("sunset_dauer", 30))
        if not in_win or (since >= sunrise and until >= sunset):
            return None  # keine Rampe aktiv (Kern-Tag oder Nacht)
        hell = int(ctx.num("licht_helligkeit", 100))
        # Rampendes Geraet wie in der Regelung: UC-als-Sonne rampt die UC,
        # sonst rampt das (dimmbare) Hauptlicht.
        if ctx.sw("undercanopy_als_sonne"):
            name, vorh, dimb, dsel = ("undercanopy", "vorhanden_undercanopy",
                                      "dimmbar_undercanopy",
                                      "dimmer_undercanopy")
        else:
            name, vorh, dimb, dsel = ("licht", "vorhanden_licht",
                                      "dimmbar_licht", "dimmer_licht")
        if not (ctx.sw(vorh) and ctx.sw(dimb)):
            return None
        dim = ctx.sel(dsel)
        if not dim:
            return None
        return name, dim, Regler._ramp_pct(since, until, sunrise, sunset, hell)

    def setup_ramp_ticker(self):
        """3s-Ticker fuer 1%-genaue Sonnenrampen: sendet den Dimmwert immer
        dann, wenn sich das ganzzahlige Prozent aendert (der 30s-Regeltick
        wuerde je nach Rampendauer 1-4%-Spruenge machen). Ausserhalb einer
        Rampe tut der Ticker nichts."""
        async def _tick(_now):
            ctx = _Ctx(self.hass, self._ents())
            rampe = self._aktive_rampe(ctx)
            if rampe is None:
                if self._ramp_last:
                    self._ramp_last.clear()
                return
            name, dim, pct = rampe
            if pct <= 0 or self._ramp_last.get(name) == pct:
                return
            self._ramp_last[name] = pct
            try:
                if dim.startswith("light."):
                    await self.hass.services.async_call(
                        "light", "turn_on",
                        {"entity_id": dim, "brightness_pct": pct},
                        blocking=False)
                elif dim.startswith("fan."):
                    await self.hass.services.async_call(
                        "fan", "set_percentage",
                        {"entity_id": dim, "percentage": pct}, blocking=False)
                elif dim.startswith("number."):
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": dim, "value": pct}, blocking=False)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Rampen-Ticker %s", dim)

        return async_track_time_interval(self.hass, _tick,
                                         timedelta(seconds=3))

    def _source(self, ctx, sel_key):
        return ctx.fnum(ctx.sel(sel_key))

    async def _mqtt_watchdog(self, ctx) -> None:
        """Broker neu starten, wenn die Klima-Quellsensoren zu lange nichts
        Frisches liefern (klassischer haengender MQTT-Broker)."""
        if not ctx.sw("mqtt_watchdog"):
            return
        fenster = ctx.num("mqtt_watchdog_min", 10)
        if not fenster or fenster <= 0:
            return

        # Neueste Aktualisierung unter den zugeordneten Klima-Quellsensoren
        newest = None
        for key in ("sensor_temp_luft", "sensor_feuchte_luft", "sensor_co2"):
            eid = ctx.sel(key)
            if not eid:
                continue
            st = self.hass.states.get(eid)
            if st is None:
                continue
            ts = st.last_updated
            if newest is None or ts > newest:
                newest = ts
        if newest is None:
            return  # keine Quellen zugeordnet -> nichts zu ueberwachen

        alt_s = (dt_util.utcnow() - newest).total_seconds()
        if alt_s < fenster * 60:
            return  # Daten sind frisch genug

        # Stale -> Broker neu starten (global gedrosselt gegen Schleifen)
        shared = self.hass.data.setdefault(DOMAIN, {}).setdefault("_mqtt_wd", {})
        if _time.time() - shared.get("last_restart", 0) < MQTT_RESTART_COOLDOWN_S:
            return
        shared["last_restart"] = _time.time()
        _LOGGER.warning(
            "MQTT-Watchdog [%s]: seit %.0f min keine frischen Sensordaten "
            "-> starte Broker '%s' neu", self.entry.title, alt_s / 60,
            MQTT_BROKER_ADDON)
        await self.hass.services.async_call(
            "hassio", "addon_restart", {"addon": MQTT_BROKER_ADDON},
            blocking=False)

    # ------------------------------------------------------------------
    async def _async_update_data(self):
        ents = self._ents()
        ctx = _Ctx(self.hass, ents)

        for ent in list(ents.values()):
            upd = getattr(ent, "refresh_options", None)
            if upd:
                try:
                    upd()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("refresh_options")

        # Phasen-Editor-Regler beim ersten Tick mit dem Profil der gewaehlten
        # Editor-Phase befuellen (danach nur noch bei Auswahl-Wechsel).
        if not self._pe_loaded and ents:
            self._pe_loaded = True
            editor = ents.get("phase_editor")
            if editor is not None and editor.current_option:
                await self.async_on_phase_editor_change(editor.current_option)

        # -- MQTT-Watchdog (haengender Broker -> Neustart) --
        try:
            await self._mqtt_watchdog(ctx)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("MQTT-Watchdog")

        # -- Geraetewechsel: Schalt-/Lernzustand des alten Geraets verwerfen --
        try:
            await self._geraetewechsel(ctx, ents)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Gerätewechsel")

        # -- abgeleitete Werte --
        temp_luft = self._source(ctx, "sensor_temp_luft")
        feuchte_luft = self._source(ctx, "sensor_feuchte_luft")
        co2 = self._source(ctx, "sensor_co2")
        temp_zuluft = self._source(ctx, "sensor_temp_zuluft")
        feuchte_zuluft = self._source(ctx, "sensor_feuchte_zuluft")
        tb_src = self._source(ctx, "sensor_temp_blatt")
        if tb_src is not None:
            temp_blatt = tb_src
        elif temp_luft is not None:
            temp_blatt = round(temp_luft - ctx.num("blatt_offset", 2.0), 2)
        else:
            temp_blatt = None
        vpd = _vpd(temp_luft, feuchte_luft, temp_blatt)

        # Tag/Nacht: zugeordnetes Licht ist massgebend; ohne Licht dient der
        # Sonnenstand als Fallback (ehrlicher als pauschal "Tag").
        licht = ctx.sel("geraet_licht")
        licht_on = (ctx.state(licht) == "on") if licht else None
        if licht_on is not None:
            ist_tag = licht_on
        else:
            sonne = ctx.state("sun.sun")
            ist_tag = (sonne == "above_horizon") if sonne else True
        ziel_temp = ctx.num("ziel_temp_tag", 24) if ist_tag else ctx.num("ziel_temp_nacht", 22)
        ziel_feuchte = ctx.num("ziel_feuchte_tag", 60) if ist_tag else ctx.num("ziel_feuchte_nacht", 60)

        # Frische-Check der Temp-Quelle (fuer LIVE-Klima-Sicherung)
        temp_fresh = True
        teid = ctx.sel("sensor_temp_luft")
        if teid:
            st = self.hass.states.get(teid)
            if st:
                age = (datetime.now(st.last_updated.tzinfo) - st.last_updated).total_seconds()
                temp_fresh = age <= 600

        data = {
            "data_temp_luft": temp_luft,
            "data_feuchte_luft": feuchte_luft,
            "data_co2": co2,
            "data_temp_zuluft": temp_zuluft,
            "data_feuchte_zuluft": feuchte_zuluft,
            "data_temp_blatt": temp_blatt,
            "data_vpd": vpd,
            "data_ziel_temp": round(ziel_temp, 1),
            "data_ziel_feuchte": round(ziel_feuchte, 1),
            "data_ist_tag": bool(ist_tag),
            "data_tag_nacht": "Tag" if ist_tag else "Nacht",
            "_temp_fresh": temp_fresh,
        }

        # Geglaetteter VPD (Mittel ueber ~5 min) fuer die Feuchte-Aktorik:
        # kurze VPD-Einbrueche waehrend der AC-Kompressorphasen sollen den
        # Entfeuchter nicht triggern (sonst Dauertakten + Uebertrocknen).
        jetzt = _time.time()
        if vpd is not None:
            self._vpd_glatt.append((jetzt, vpd))
        self._vpd_glatt = [(t, v) for t, v in self._vpd_glatt
                           if jetzt - t <= 300]
        data["data_vpd_glatt"] = (
            round(sum(v for _, v in self._vpd_glatt)
                  / len(self._vpd_glatt), 2)
            if self._vpd_glatt else None)

        # Ist-Helligkeit des Undercanopy-Dimmers (in %)
        uc_dim = ctx.sel("dimmer_undercanopy")
        uc_hell = None
        if uc_dim:
            st = self.hass.states.get(uc_dim)
            if st is not None and st.state == "on":
                b = st.attributes.get("brightness")
                uc_hell = round(b / 2.55) if b is not None else 100
            elif st is not None and st.state == "off":
                uc_hell = 0
        data["data_uc_helligkeit"] = uc_hell

        # -- Lichtzyklus: Ende automatisch = Start + Lichtstunden (ausser Manuell) --
        zyklus = ctx.sel_raw("licht_zyklus") or "Manuell"
        if zyklus != "Manuell" and "/" in zyklus:
            try:
                stunden = int(zyklus.split("/")[0])
                start = ctx.t("licht_start")
                ende_ent = ents.get("licht_ende")
                if start is not None and ende_ent is not None:
                    soll = dt_time((start.hour + stunden) % 24, start.minute)
                    if ende_ent.native_value != soll:
                        await ende_ent.async_set_value(soll)
            except (ValueError, AttributeError):
                _LOGGER.exception("Lichtzyklus %s", zyklus)

        # -- Echte KI: Datenlogger + VPD-Prognose --
        # (VOR der Regelung, damit die KI-Vorsteuerung die Prognose dieses
        # Zyklus nutzt statt der 30 s alten aus dem letzten Tick)
        try:
            await self._ki_tick(ctx, data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("KI-Tick")

        # -- Regelung --
        try:
            shadow, devices, klima_cmds, bias = self.regler.tick(ctx, data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Regelung %s", self.entry.title)
            shadow, devices, klima_cmds, bias = (
                {"status": "[%s] FEHLER (siehe Log)" % self.entry.title}, {}, [], {})

        for k, v in shadow.items():
            data["shadow_%s" % k] = str(v)[:255]

        # KI-Bias-Werte zurueckschreiben
        for key, val in bias.items():
            e = ents.get(key)
            if e is not None:
                try:
                    await e.async_set_native_value(val)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Bias %s", key)

        # -- Schalten -- (Steuern = alles inkl. Klima; Monitor = nichts)
        steuern = ctx.sel_raw("betriebsmodus") == "Steuern" and ctx.sw("aktiv")
        if steuern:
            await self._apply_devices(devices)
            for dmn, svc, sdata in klima_cmds:  # LIVE-Klima
                try:
                    await self.hass.services.async_call(dmn, svc, sdata, blocking=False)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Klima-Call %s.%s", dmn, svc)
        else:
            self._last_dev = {}

        # -- Grow-Tracking --
        store = self._store()
        gstart = None
        ge = ents.get("grow_start")
        if ge is not None:
            gstart = getattr(ge, "native_value", None)
        today = date.today()
        data["grow_tag"] = (today - gstart).days + 1 if isinstance(gstart, date) else None
        if store:
            g = store.grow(self.entry.entry_id)
            if not g.get("phase_start"):
                store.set_phase_start(self.entry.entry_id,
                                      ctx.sel_raw("wuchsphase") or "-",
                                      today.isoformat())
                g = store.grow(self.entry.entry_id)
            try:
                pstart = date.fromisoformat(g["phase_start"])
                data["phase_tag"] = (today - pstart).days + 1
            except (TypeError, ValueError):
                data["phase_tag"] = None
            data["_history"] = list(g.get("history") or [])
            data["_strains"] = list(g.get("strains") or [])
            data["_grow_archive"] = list(g.get("archive") or [])
            data["_notify_targets"] = store.notify_targets(self.entry.entry_id)

            # -- Duengeplan: Anzeige-Liste + Termine (Kalender/Meldungen) --
            produkte = store.duenger_produkte()
            autoflower = (ctx.sel_raw("grow_typ") == "Autoflowering")
            _bs = getattr(ents.get("bluete_start"), "native_value", None)
            bstart_d = _bs if isinstance(_bs, date) else None
            termine = alle_termine(produkte, data["_strains"], autoflower,
                                   bstart_d, today, today + timedelta(days=90))
            def _gilt(p, s):
                return (p.get("id") in (s.get("duenger") or [])
                        or (p.get("hersteller") or "").lower() in
                        [h.lower() for h in (s.get("hersteller_links") or [])])

            data["_duengerplan"] = [
                {"name": p.get("name"), "hersteller": p.get("hersteller"),
                 "kategorie": p.get("kategorie"), "typ": p.get("typ"),
                 "form": p.get("form", "Flüssig"),
                 "regeln": [regel_txt(r, menge_einheit(p))
                            for r in (p.get("regeln") or [])],
                 "strains": [s.get("name") for s in data["_strains"]
                             if _gilt(p, s)],
                 # Sonderregeln je Strain (eigene Dosierung) einzeln zeigen
                 "sonder": ["%s: %s%s" % (
                     s.get("name"), regel_txt(r, menge_einheit(p)),
                     {"ersetzt": " · ersetzt ganzen Plan",
                      "zusaetzlich": " · zusätzlich"}.get(r.get("art"), ""))
                     for s in data["_strains"]
                     for r in (s.get("extra_regeln") or [])
                     if r.get("pid") == p.get("id")]}
                for p in produkte]
            # Anzeige-Liste: gleiche Anwendung ueber mehrere Strains
            # gebuendelt (Sonderdosierung = eigene Zeile, andere Menge)
            data["_duenger_termine"] = [
                {"datum": t["datum"].isoformat(), "produkt": t["produkt"],
                 "strain": ", ".join(t["strains"]),
                 "kategorie": t["kategorie"],
                 "typ": t["typ"], "menge": t.get("menge") or ""}
                for t in termine_gruppiert(termine)[:40]]
            data["_duenger_heute"] = [
                {"datum": t["datum"].isoformat(), "produkt": t["produkt"],
                 "strain": t["strain"], "kategorie": t["kategorie"],
                 "typ": t["typ"], "pid": t["pid"],
                 "menge": t.get("menge") or "",
                 "erinnerung": t.get("erinnerung") or "Einmalig",
                 "erinnerung_intervall": t.get("erinnerung_intervall") or 4,
                 "erinnerung_einheit": t.get("erinnerung_einheit")
                 or "Stunden"}
                for t in termine if t["datum"] == today]

            # -- Bluetetage (je Grow-Typ) --
            # Quelle ist das Datumsfeld "Blüte-Startdatum" (manuell korrigier-
            # bar); die Automatik fuellt es nur, wenn es leer ist.
            be = ents.get("bluete_start")
            bstart = getattr(be, "native_value", None)
            # Neuer Grow (Startdatum geaendert) -> Bluete-Zaehler zuruecksetzen.
            # Nur bei ECHTER Aenderung (beide Seiten bekannt): direkt nach dem
            # Boot kann gstart noch un-restauriert (None) sein - dann nichts tun.
            gstart_iso = gstart.isoformat() if isinstance(gstart, date) else None
            if gstart_iso is not None and g.get("grow_start_ref") != gstart_iso:
                if (g.get("grow_start_ref") is not None
                        and be is not None and bstart is not None):
                    be.set_internal(None)
                    bstart = None
                store.set_grow_value(self.entry.entry_id, "grow_start_ref", gstart_iso)
            typ = ctx.sel_raw("grow_typ") or "Photoperiodisch"
            if typ == "Autoflowering":
                # Autos bluehen ab Tag 1: ab der Vorbluete wird der Grow-Tag
                # zum Grow/Bluete-Tag - kein separater Bluetenstart.
                in_bluete = (ctx.sel_raw("wuchsphase") or "") in (
                    "Vorblüte", "Hauptblüte", "Spätblüte")
                data["bluete_tag"] = data["grow_tag"] if in_bluete else None
            else:
                # Photoperiodisch: Bluetenstart sobald Lichtfenster <= 12 h
                if bstart is None:
                    ls, le = ctx.t("licht_start"), ctx.t("licht_ende")
                    if ls is not None and le is not None:
                        sm = ls.hour * 60 + ls.minute
                        em = le.hour * 60 + le.minute
                        dauer = 1440 if sm == em else (
                            em - sm if em > sm else 1440 - sm + em)
                        if dauer <= 720 and be is not None:
                            be.set_internal(today)
                            bstart = today
                data["bluete_tag"] = (
                    (today - bstart).days + 1 if isinstance(bstart, date) else None)
        else:
            data["phase_tag"] = None
            data["bluete_tag"] = None

        # -- Benachrichtigungen --
        try:
            await self._benachrichtigen(ctx, data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Benachrichtigungen")
        return data

    # ------------------------------------------------------------------
    _WECHSEL_RESET = {
        "geraet_befeuchter":  ("befeuchter",  ["bef"], True),
        "geraet_entfeuchter": ("entfeuchter", ["ent", "ent_sm"], True),
        "geraet_klima":       ("klima", ["cool", "kdry", "kcool", "kheat",
                                         "rt_klima_mode"], True),
        "geraet_heizung":     ("heizung", ["heat"], False),
        "geraet_co2_ventil":  ("co2", ["co2"], False),
        "geraet_abluft":      ("abluft", ["abluft", "abluft_backup"], False),
        "geraet_ventilator":  ("ventilator", [], False),
        "geraet_umluft":      ("umluft", [], False),
        "geraet_licht":       ("licht", [], False),
        "geraet_undercanopy": ("undercanopy", [], False),
    }

    async def _geraetewechsel(self, ctx, ents) -> None:
        for selkey, (name, latches, ki_reset) in self._WECHSEL_RESET.items():
            eid = ctx.sel(selkey)
            alt = self._dev_track.get(selkey)
            if selkey in self._dev_track and alt != eid:
                self.regler.reset_device(latches)
                self._last_dev.pop(name, None)
                _LOGGER.info("[%s] Gerätewechsel %s: %s → %s — Schaltzustand "
                             "zurückgesetzt", self.entry.title, name,
                             alt or "-", eid or "-")
                if ki_reset:
                    e = ents.get("vpd_bias_tag")
                    if e is not None:
                        try:
                            await e.async_set_native_value(0.0)
                            _LOGGER.info("[%s] KI-VPD-Bias nach Gerätewechsel "
                                         "auf 0 gesetzt", self.entry.title)
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception("Bias-Reset")
            self._dev_track[selkey] = eid

    # ------------------------------------------------------------------
    async def _benachrichtigen(self, ctx, data) -> None:
        """Alarme (Tank/CO2/Sensor) + faellige Notizen melden.

        Nur bei steigender Flanke, zusaetzlich Cooldown gegen Spam.
        Kanaele: persistente HA-Meldung + notify.notify (Companion-App)."""
        if not ctx.sw("benachrichtigungen"):
            return
        now = _time.time()
        name = self.entry.title

        def _ziel_dienste() -> list:
            """Zieldienste je Modus: 'Alle Geräte' -> notify.notify, sonst die
            ausgewaehlte Geraeteliste (Fallback notify.notify, wenn leer)."""
            modus = ctx.sel_raw("benachrichtigung_modus") or "Alle Geräte"
            dienste = []
            if modus == "Auswahl":
                store = self._store()
                dienste = [d for d in (store.notify_targets(self.entry.entry_id)
                                       if store else [])
                           if self.hass.services.has_service("notify", d)]
            if not dienste and self.hass.services.has_service("notify", "notify"):
                dienste = ["notify"]
            return dienste

        async def melde(key, titel, text, cooldown=3600):
            if now - self._alerts.get(key, 0) < cooldown:
                return
            self._alerts[key] = now
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {"title": titel, "message": text,
                 "notification_id": "controlos_%s_%s" % (
                     area_slug(name), key.split("_")[0])},
                blocking=False)
            for dienst in _ziel_dienste():
                await self.hass.services.async_call(
                    "notify", dienst,
                    {"title": titel, "message": text}, blocking=False)

        # Entfeuchter-Tank voll
        tank_eid = ctx.sel("sensor_tank")
        tank = bool(tank_eid) and ctx.state(tank_eid) == "on"
        if tank and not self._alert_on.get("tank") and ctx.sw("notify_tank"):
            await melde("tank", "🚰 ControlOS: Tank voll",
                        "[%s] Entfeuchter-Tank ist voll — bitte leeren, "
                        "das Entfeuchten pausiert." % name)
        self._alert_on["tank"] = tank

        # CO2 ueber Alarmgrenze
        co2 = data.get("data_co2")
        co2_max = ctx.num("co2_alarm_max", 1500)
        zu_hoch = co2 is not None and co2_max > 0 and co2 > co2_max
        if zu_hoch and not self._alert_on.get("co2") and ctx.sw("notify_co2"):
            await melde("co2", "⚠️ ControlOS: CO2 zu hoch",
                        "[%s] CO2 bei %.0f ppm (Alarm ab %.0f ppm)." % (
                            name, co2, co2_max))
        self._alert_on["co2"] = zu_hoch

        # Zugewiesene Geraete ausgefallen (unavailable/unknown)
        for selkey, (gname, _l, _k) in self._WECHSEL_RESET.items():
            geid = ctx.sel(selkey)
            defekt = bool(geid) and ctx.state(geid) in (None, "unavailable",
                                                        "unknown")
            akey = "dev_%s" % gname
            if defekt and not self._alert_on.get(akey) and ctx.sw("notify_geraet"):
                await melde(akey, "⚠️ ControlOS: Gerät ausgefallen",
                            "[%s] %s (%s) ist nicht mehr erreichbar — "
                            "Regelung behandelt es als nicht vorhanden." % (
                                name, gname.capitalize(), geid))
            self._alert_on[akey] = defekt

        # Klimasensor liefert nichts mehr
        ausfall = (bool(ctx.sel("sensor_temp_luft"))
                   and data.get("data_temp_luft") is None)
        if ausfall and not self._alert_on.get("sensor") and ctx.sw("notify_sensor"):
            await melde("sensor", "📡 ControlOS: Sensor-Ausfall",
                        "[%s] Der Klimasensor liefert keine Daten — "
                        "MQTT-Watchdog kümmert sich, bitte prüfen." % name)
        self._alert_on["sensor"] = ausfall

        # -- Klima-Alarme, 24/7. Je Parameter waehlbar (…_alarm_modus):
        #    "Toleranz" -> Alarm ab Sollwert +- (Toleranz + Margin)
        #    "Min/Max"  -> Alarm unterhalb …_alarm_min oder oberhalb …_alarm_max
        async def klima_alarm(akey, wert, ziel, modus, band, amin, amax,
                              toggle, icon, label, einheit):
            if wert is None:
                self._alert_on[akey] = False
                return
            if modus == "Min/Max":
                aus = (amin is not None and amax is not None
                       and (wert < amin or wert > amax))
                detail = "[%s] %s %.1f%s (erlaubt %.1f–%.1f%s)." % (
                    name, label, wert, einheit, amin, amax, einheit)
            else:
                aus = (ziel is not None and band > 0 and abs(wert - ziel) > band)
                detail = "[%s] %s %.1f%s (Ziel %.1f%s, Alarm ab ±%.1f%s)." % (
                    name, label, wert, einheit, ziel, einheit, band, einheit)
            if aus and not self._alert_on.get(akey) and ctx.sw(toggle):
                await melde(akey, "%s ControlOS: %s außerhalb" % (icon, label),
                            detail)
            self._alert_on[akey] = aus

        # Bei aktiver VPD->Temp-Kopplung (regelung: geschlossenes System, VPD,
        # Tag, Prio "feuchte", AC da) weicht die Temperatur BEWUSST vom
        # Temp-Ziel ab -> der Toleranz-Alarm wuerde faelschlich feuern.
        # Dann Temperatur nur im Min/Max-Modus bewachen.
        vpd_temp_kopplung = (
            (ctx.sel_raw("system_modus") or "") == "Geschlossenes System"
            and (ctx.sel_raw("klima_modus") or "VPD") == "VPD"
            and bool(data.get("data_ist_tag"))
            and (ctx.sel_raw("prio") or "temperatur") == "feuchte"
            and ctx.sw("vorhanden_klima") and ctx.sel("geraet_klima"))
        temp_alarm_modus = ctx.sel_raw("temp_alarm_modus") or "Toleranz"
        if vpd_temp_kopplung and temp_alarm_modus != "Min/Max":
            self._alert_on["ktemp"] = False
        else:
            await klima_alarm(
                "ktemp", data.get("data_temp_luft"), data.get("data_ziel_temp"),
                temp_alarm_modus,
                ctx.num("temp_toleranz", 0.5) + ctx.num("temp_alarm_margin", 3),
                ctx.num("temp_alarm_min", 16), ctx.num("temp_alarm_max", 30),
                "notify_temp", "🌡️", "Temperatur", "°C")
        await klima_alarm(
            "kfeuchte", data.get("data_feuchte_luft"), data.get("data_ziel_feuchte"),
            ctx.sel_raw("feuchte_alarm_modus") or "Toleranz",
            ctx.num("feuchte_toleranz", 5) + ctx.num("feuchte_alarm_margin", 15),
            ctx.num("feuchte_alarm_min", 30), ctx.num("feuchte_alarm_max", 70),
            "notify_feuchte", "💧", "Feuchte", "%")
        if (ctx.sel_raw("klima_modus") or "VPD") == "VPD":
            await klima_alarm(
                "kvpd", data.get("data_vpd"), ctx.num("vpd_ziel", 1.2),
                ctx.sel_raw("vpd_alarm_modus") or "Toleranz",
                ctx.num("vpd_toleranz", 0.2) + ctx.num("vpd_alarm_margin", 0.5),
                ctx.num("vpd_alarm_min", 0.4), ctx.num("vpd_alarm_max", 1.8),
                "notify_vpd", "💨", "VPD", " kPa")
        else:
            self._alert_on["kvpd"] = False

        # Faellige Notizen. Steuerwoerter in Titel/Beschreibung:
        #   (nichts)      -> einmalig am Faelligkeitstag
        #   !täglich      -> jeden Tag erinnern, bis erledigt
        #   !wöchentlich  -> alle 7 Tage
        #   !stumm        -> nie benachrichtigen
        store = self._store()
        if store and ctx.sw("notify_notizen"):
            heute = date.today()
            heute_iso = heute.isoformat()
            items = store.todos(self.entry.entry_id)
            geaendert = False
            for t in items:
                if (t.get("status") == "completed" or not t.get("due")
                        or t["due"] > heute_iso):
                    continue
                text = ("%s %s" % (t.get("summary") or "",
                                   t.get("description") or "")).lower()
                if "!stumm" in text:
                    continue
                letzte = t.get("erinnert_am")
                if "!täglich" in text or "!taeglich" in text:
                    faellig_erneut = letzte != heute_iso
                elif "!wöchentlich" in text or "!woechentlich" in text:
                    try:
                        tage = (heute - date.fromisoformat(letzte)).days
                    except (TypeError, ValueError):
                        tage = 99
                    faellig_erneut = tage >= 7
                else:
                    faellig_erneut = letzte is None  # einmalig
                if not faellig_erneut:
                    continue
                await melde("todo_%s" % t.get("uid"),
                            "📝 ControlOS: Erinnerung",
                            "[%s] %s (fällig %s)" % (
                                name, t.get("summary"), t["due"]),
                            cooldown=0)
                t["erinnert_am"] = heute_iso
                geaendert = True
            if geaendert:
                store.set_todos(self.entry.entry_id, items)

        # Pflanzenpflege: faellige Anwendungen -> abhakbarer Eintrag in der
        # Notizliste + Push. Je Produkt: einmalige Meldung ODER Wiederholung
        # alle X Stunden/Tage, bis der Eintrag abgehakt ist.
        if store:
            produkte_map = {p.get("id"): p
                            for p in store.duenger_produkte()}
            todos2 = store.todos(self.entry.entry_id)
            todos_neu = False
            jetzt_dt = dt_util.now()

            def _mit_menge(t):
                m = t.get("menge") or ""
                return t["produkt"] + ((" " + m) if m else "")

            async def _pflege_push(key, t, strains, zusatz=""):
                icon = KATEGORIE_ICON.get(t["kategorie"], "💧")
                await melde(
                    key, "%s ControlOS: %s anwenden" % (icon, _mit_menge(t)),
                    "[%s] Fällig: %s (%s) für %s.%s" % (
                        name, _mit_menge(t),
                        t.get("typ") or t["kategorie"], strains, zusatz),
                    cooldown=0)

            # 1) Heute faellige Termine: Notiz-Eintrag anlegen (je Strain
            #    abhakbar) + erste Meldung. Push gebuendelt: EINE Meldung
            #    je Produkt+Menge mit allen betroffenen Strains.
            push_gruppen: dict = {}
            for t in data.get("_duenger_heute") or []:
                key = "dg|%s|%s|%s" % (t["pid"], t["strain"], t["datum"])
                merk = store.duenger_erinnert(key)
                if isinstance(merk, str):   # Altformat: nur Datum gemerkt
                    merk = {"gemeldet": merk}
                merk = dict(merk or {})
                if not merk.get("uid"):
                    uid = _uuid.uuid4().hex
                    icon = KATEGORIE_ICON.get(t["kategorie"], "💧")
                    # !stumm: die Notiz-Engine soll nicht doppelt melden,
                    # die Pflege-Erinnerung uebernimmt das selbst.
                    todos2.append({
                        "uid": uid,
                        "summary": "%s %s – %s" % (icon, _mit_menge(t),
                                                   t["strain"]),
                        "status": "needs_action", "due": t["datum"],
                        "description": "%s · Pflanzenpflege !stumm" % (
                            t.get("typ") or t["kategorie"])})
                    todos_neu = True
                    merk["uid"] = uid
                    merk["pid"] = t["pid"]
                    merk["strain"] = t["strain"]
                    merk["kategorie"] = t["kategorie"]
                    merk["typ"] = t.get("typ")
                    merk["produkt"] = t["produkt"]
                    merk["menge"] = t.get("menge") or ""
                    # Push-Verhalten der ausloesenden Regel mitmerken
                    merk["erinnerung"] = t.get("erinnerung") or "Einmalig"
                    merk["erinnerung_intervall"] = t.get(
                        "erinnerung_intervall") or 4
                    merk["erinnerung_einheit"] = t.get(
                        "erinnerung_einheit") or "Stunden"
                if ctx.sw("notify_duenger") and not merk.get("gemeldet"):
                    g = push_gruppen.setdefault(
                        (t["pid"], t.get("menge") or ""),
                        dict(t, strains=[]))
                    g["strains"].append(t["strain"])
                    merk["gemeldet"] = jetzt_dt.isoformat()
                store.set_duenger_erinnert(key, merk)

            for g in push_gruppen.values():
                await _pflege_push(
                    "dg|%s|%s|%s" % (g["pid"], g.get("menge") or "",
                                     g["datum"]),
                    g, ", ".join(g["strains"]))

            if todos_neu:
                store.set_todos(self.entry.entry_id, todos2)
                todo_ent = self._ents().get("notizen")
                if todo_ent is not None:
                    todo_ent.async_write_ha_state()

            # 2) Intervall-Erinnerungen: offene Pflege-Eintraege wiederholt
            #    melden, bis sie abgehakt (oder geloescht) sind. Auch hier
            #    gebuendelt: gleichzeitig faellige Strains in EINER Meldung.
            if ctx.sw("notify_duenger"):
                offen = {x.get("uid"): x for x in todos2
                         if x.get("status") != "completed"}
                wieder_gruppen: dict = {}
                for key, merk in store.duenger_erinnert_alle().items():
                    if not (isinstance(merk, dict) and merk.get("uid")):
                        continue
                    # Push-Verhalten steht am Merker (= Regel); Alt-Merker
                    # ohne diese Felder erben es vom Produkt.
                    p = produkte_map.get(merk.get("pid")) or {}
                    modus = merk.get("erinnerung") or p.get("erinnerung")
                    if modus != "Intervall":
                        continue
                    if merk["uid"] not in offen:
                        continue   # abgehakt/geloescht -> Ruhe
                    step_h = max(1, int(
                        merk.get("erinnerung_intervall")
                        or p.get("erinnerung_intervall", 4))) * (
                        24 if (merk.get("erinnerung_einheit")
                               or p.get("erinnerung_einheit")) == "Tage"
                        else 1)
                    letzte = merk.get("gemeldet")
                    try:
                        wieder = (letzte is None or
                                  (jetzt_dt - datetime.fromisoformat(letzte))
                                  .total_seconds() >= step_h * 3600)
                    except (TypeError, ValueError):
                        wieder = True
                    if wieder:
                        g = wieder_gruppen.setdefault(
                            (merk.get("pid"), merk.get("menge", "")),
                            {"produkt": merk.get("produkt", "?"),
                             "kategorie": merk.get("kategorie", "Dünger"),
                             "typ": merk.get("typ"),
                             "menge": merk.get("menge", ""),
                             "strains": [], "merker": []})
                        g["strains"].append(merk.get("strain", "?"))
                        g["merker"].append((key, merk))
                for g in wieder_gruppen.values():
                    await _pflege_push(
                        "dgw|%s|%s" % (g["produkt"], g["menge"]),
                        g, ", ".join(g["strains"]), " (bis abgehakt)")
                    for key, merk in g["merker"]:
                        store.set_duenger_erinnert(
                            key, dict(merk, gemeldet=jetzt_dt.isoformat()))

    # ------------------------------------------------------------------
    async def _ki_tick(self, ctx, data) -> None:
        now = _time.time()
        vpd = data.get("data_vpd")
        slope = 0.0
        # Echte KI aus: weder Daten sammeln noch Prognosen rechnen
        if not ctx.sw("ki_engine"):
            data["ki_vpd_prognose"] = None
            data["_ki_prognose"] = []
            data["ki_status"] = "aus"
            return
        # Tank voll: Klima-Dynamik ist untypisch (Entfeuchter zwangspausiert)
        # -> weder Zeilen sammeln noch Prognosen ausgeben
        tank_eid = ctx.sel("sensor_tank")
        tank_voll = bool(tank_eid) and ctx.state(tank_eid) == "on"
        if tank_voll:
            data["ki_vpd_prognose"] = None
            data["_ki_prognose"] = []
            data["ki_status"] = ("pausiert (Tank voll) | %d Zeilen"
                                 % self.ki.n_rows)
            return
        if vpd is not None and data.get("data_temp_luft") is not None:
            # Steigung: VPD-Aenderung ueber ~5 Minuten
            self._vpd_hist.append((now, vpd))
            self._vpd_hist = [(t, v) for t, v in self._vpd_hist
                              if now - t <= 360]
            alt = [(t, v) for t, v in self._vpd_hist if now - t >= 240]
            if alt:
                slope = vpd - alt[-1][1]
            dev_on = {}
            dev_st = {}
            for key, name in (("geraet_befeuchter", "bef"),
                              ("geraet_entfeuchter", "ent"),
                              ("geraet_klima", "klima"),
                              ("geraet_licht", "licht"),
                              ("geraet_uv", "uv")):
                eid = ctx.sel(key)
                st = self.hass.states.get(eid) if eid else None
                dev_st[name] = st
                dev_on[name] = 1 if (st is not None and
                                     st.state not in ("off", "unavailable",
                                                      "unknown")) else 0

            # Geraete-Detailsignale: die Physik hinter den Schaltzustaenden
            # (AC-Kompressorphasen, Entfeuchter-Stufe, Licht-Abwaerme).
            def fattr(st, name):
                try:
                    return round(float(st.attributes.get(name)), 1)
                except (TypeError, ValueError, AttributeError):
                    return None

            kst = dev_st["klima"]
            # Hauptlicht-Dimmleistung (groesste Abwaermequelle): echter
            # Dimmerwert falls vorhanden, sonst 100 % sobald an.
            licht_pct = None
            l_dim = ctx.sel("dimmer_licht")
            lst = self.hass.states.get(l_dim) if l_dim else None
            if lst is not None and lst.state == "on":
                b = lst.attributes.get("brightness")
                licht_pct = round(b / 2.55) if b is not None else 100
            elif lst is not None and lst.state == "off":
                licht_pct = 0
            if licht_pct is None:
                licht_pct = 100 * dev_on["licht"]
            ent_stufe = None
            s_eid = ctx.sel("stufe_entfeuchter")
            sst = self.hass.states.get(s_eid) if s_eid else None
            if sst is not None:
                opts = sst.attributes.get("options") or []
                if sst.state in opts and len(opts) > 1:
                    ent_stufe = round(opts.index(sst.state) / (len(opts) - 1), 2)
            lt = datetime.now()
            row = {"ts": round(now, 1),
                   "temp": data["data_temp_luft"],
                   "hum": data.get("data_feuchte_luft"),
                   "vpd": vpd,
                   "blatt": data.get("data_temp_blatt"),
                   "co2": data.get("data_co2"),
                   "ist_tag": 1 if data.get("data_ist_tag") else 0,
                   "bef": dev_on["bef"], "ent": dev_on["ent"],
                   "klima": dev_on["klima"],
                   "minute": lt.hour * 60 + lt.minute,
                   "kwatt": fattr(kst, "realtime_power"),
                   "k_ist": fattr(kst, "current_temperature"),
                   "k_aussen": fattr(kst, "outdoor_temperature"),
                   "k_fan": fattr(kst, "fan_speed"),
                   "ent_stufe": ent_stufe,
                   "ent_hum": ctx.fnum(ctx.sel("sensor_entfeuchter")),
                   "licht": dev_on["licht"],
                   "licht_pct": licht_pct,
                   "uc_pct": data.get("data_uc_helligkeit"),
                   "uv": dev_on["uv"]}
            if row["hum"] is not None:
                await self.hass.async_add_executor_job(self.ki.append, row)
            kurve = self.ki.predict_curve(row, slope)
            # Sensor bleibt die 15-min-Prognose (Horizont 5 steht jetzt vorne)
            data["ki_vpd_prognose"] = next(
                (v for m, v in kurve if m == 15),
                kurve[0][1] if kurve else None)
            basis = dt_util.utcnow()
            data["_ki_prognose"] = [
                {"minuten": m,
                 "zeit": (basis + timedelta(minutes=m)).isoformat(),
                 "vpd": v,
                 "mae": self.ki.mae.get(m)}
                for m, v in kurve]
        else:
            data["ki_vpd_prognose"] = None
            data["_ki_prognose"] = []

        # Training stuendlich im Hintergrund
        if not self._ki_training and now - self.ki.trained_at > 3600:
            self._ki_training = True

            def _train():
                try:
                    self.ki.train()
                finally:
                    self._ki_training = False

            self.hass.async_add_executor_job(_train)

        # Status-Text
        if self.ki.modelle:
            alter_h = (now - self.ki.trained_at) / 3600
            mae_txt = " ".join(
                "%dmin ±%.2f" % (h, self.ki.mae.get(h, 0))
                for h in sorted(self.ki.modelle))
            data["ki_status"] = "bereit | %s | %d Zeilen | Modell %.1f h" % (
                mae_txt, self.ki.n_rows, alter_h)
        else:
            data["ki_status"] = "sammelt Daten (%d Zeilen, ab %d wird trainiert)" % (
                self.ki.n_rows, KI_MIN_ROWS)

        # Speicherzeit: taeglich aufraeumen
        if now - self._ki_cleanup_ts > 86400:
            self._ki_cleanup_ts = now
            wahl = ctx.sel_raw("speicherzeit") or "Unbegrenzt"
            monate = {"12 Monate": 12, "6 Monate": 6, "3 Monate": 3}.get(wahl, 0)
            if monate:
                await self.hass.async_add_executor_job(self.ki.cleanup, monate)

    # ------------------------------------------------------------------
    async def _apply_devices(self, devices: dict) -> None:
        """Soll-Zustaende anwenden (Betriebsmodus 'Steuern').

        Selbstheilend: verglichen wird gegen den ECHTEN Geraetezustand, nicht
        nur gegen den letzten eigenen Befehl - schaltet jemand (Altsystem,
        Hand, Geraetefehler) dazwischen, korrigiert der naechste Tick."""
        for name, want in devices.items():
            eid = want["entity"]
            if eid.startswith("climate."):
                continue  # climate laeuft ueber die LIVE-Klima-Kommandos
            st = self.hass.states.get(eid)
            actual_on = (st is not None and st.state == "on")
            actual_ok = (st is not None
                         and st.state not in ("unavailable", "unknown"))
            # Helligkeits-Drift: Soll-% gegen echten Dimmerwert pruefen
            pct_ok = True
            dim = want.get("dimmer_entity")
            if (want["on"] and want.get("pct") is not None
                    and dim and dim.startswith("light.")):
                dst = self.hass.states.get(dim)
                if dst is not None and dst.state == "on":
                    b = dst.attributes.get("brightness")
                    ist = round(b / 2.55) if b is not None else None
                    pct_ok = ist is None or abs(ist - want["pct"]) <= 3
                elif dst is not None and dst.state == "off":
                    pct_ok = False
            sig = (want["entity"], want["on"], want.get("pct"), want.get("stufe"))
            same_cmd = self._last_dev.get(name) == sig
            # Ueberspringen nur, wenn Befehl unveraendert UND Realzustand passt
            if same_cmd and (not actual_ok or actual_on == want["on"]) and pct_ok:
                continue
            if not same_cmd:
                self._last_dev[name] = sig
            elif actual_on != want["on"] or not pct_ok:
                _LOGGER.warning(
                    "[%s] %s extern verstellt (ist %s, soll %s%s) -> korrigiere",
                    self.entry.title, eid,
                    "an" if actual_on else "aus",
                    "an" if want["on"] else "aus",
                    " %d%%" % want["pct"] if want.get("pct") is not None else "")
            try:
                svc = "turn_on" if want["on"] else "turn_off"
                await self.hass.services.async_call(
                    "homeassistant", svc, {"entity_id": eid}, blocking=False)
                if want["on"] and want.get("pct") is not None:
                    dim = want.get("dimmer_entity")
                    if dim and dim.startswith("light."):
                        await self.hass.services.async_call(
                            "light", "turn_on",
                            {"entity_id": dim, "brightness_pct": want["pct"]},
                            blocking=False)
                    elif dim and dim.startswith("fan."):
                        await self.hass.services.async_call(
                            "fan", "set_percentage",
                            {"entity_id": dim, "percentage": want["pct"]},
                            blocking=False)
                    elif dim and dim.startswith("number."):
                        await self.hass.services.async_call(
                            "number", "set_value",
                            {"entity_id": dim, "value": want["pct"]},
                            blocking=False)
                if want["on"] and want.get("stufe") and want.get("stufe_entity"):
                    se = want["stufe_entity"]
                    if se.startswith("select."):
                        await self.hass.services.async_call(
                            "select", "select_option",
                            {"entity_id": se, "option": want["stufe"]},
                            blocking=False)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Geraet %s schalten", name)

    # ------------------------------------------------------------------
    async def async_on_phase_change(self, phase: str) -> None:
        """Wuchsphase gewechselt: Profil (Override sonst Standard) laden +
        Phasen-Start im Grow-Tracking setzen."""
        store = self._store()
        if store is None:
            return
        values = store.effective_phase(self.entry.entry_id, phase)
        ents = self._ents()
        for key in PHASE_KEYS:
            e = ents.get(key)
            if e is not None and key in values:
                try:
                    await e.async_set_native_value(float(values[key]))
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Phase laden %s", key)
        store.set_phase_start(self.entry.entry_id, phase, date.today().isoformat())
        await self.async_request_refresh()

    async def _load_into(self, prefix: str, values: dict) -> None:
        """Phasenwerte in die Entities mit gegebenem Praefix schreiben."""
        ents = self._ents()
        for key in PHASE_KEYS:
            e = ents.get(prefix + key)
            if e is not None and key in values:
                try:
                    await e.async_set_native_value(float(values[key]))
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Phase laden %s%s", prefix, key)

    async def async_on_phase_editor_change(self, phase: str) -> None:
        """Editor-Phase gewaehlt: deren Profil in die pe_-Regler laden.
        Rein zum Bearbeiten - keine Auswirkung auf die aktive Steuerung."""
        store = self._store()
        if store is None:
            return
        await self._load_into("pe_", store.effective_phase(self.entry.entry_id, phase))

    def _editor_phase(self, ctx) -> str | None:
        return ctx.sel_raw("phase_editor")

    async def async_save_override(self) -> None:
        """Aktuelle pe_-Regler als Override der EDITOR-Phase speichern."""
        ents = self._ents()
        ctx = _Ctx(self.hass, ents)
        phase = self._editor_phase(ctx)
        store = self._store()
        if not phase or store is None:
            return
        store.set_override(self.entry.entry_id, phase,
                           {k: ctx.num("pe_" + k, 0.0) for k in PHASE_KEYS})
        # Ist die bearbeitete Phase die aktive? Dann Steuerungswerte mitnehmen.
        if phase == ctx.sel_raw("wuchsphase"):
            await self._load_into("", store.effective_phase(self.entry.entry_id, phase))
        await self.async_request_refresh()

    async def async_reset_override(self) -> None:
        """Override der EDITOR-Phase loeschen, Standard in die pe_-Regler laden."""
        ents = self._ents()
        ctx = _Ctx(self.hass, ents)
        phase = self._editor_phase(ctx)
        store = self._store()
        if not phase or store is None:
            return
        store.clear_override(self.entry.entry_id, phase)
        std = store.get_std(phase)
        await self._load_into("pe_", std)
        if phase == ctx.sel_raw("wuchsphase"):
            await self._load_into("", std)
        await self.async_request_refresh()

    # -- Grow-Verwaltung --------------------------------------------------
    async def async_strain_add(self) -> None:
        store = self._store()
        ents = self._ents()
        if store is None:
            return
        ctx = _Ctx(self.hass, ents)
        name_e = ents.get("strain_name")
        wert_e = ents.get("strain_bluetezeit")
        start_e = ents.get("strain_start")
        name = (getattr(name_e, "native_value", "") or "").strip()
        wert = int(getattr(wert_e, "native_value", 9) or 9)
        einheit = ctx.sel_raw("bluetezeit_einheit") or "Wochen"
        sv = getattr(start_e, "native_value", None)
        start = sv.isoformat() if isinstance(sv, date) else None
        if not name:
            return
        store.add_strain(self.entry.entry_id, name, wert, einheit, start)
        if name_e is not None:
            await name_e.async_set_value("")
        await self.async_request_refresh()

    async def async_strain_remove(self) -> None:
        store = self._store()
        ents = self._ents()
        sel = ents.get("strain_auswahl")
        if store is None or sel is None:
            return
        idx = sel.selected_index()
        if 0 <= idx < len(store.strains(self.entry.entry_id)):
            store.remove_strain(self.entry.entry_id, idx)
            sel.refresh_options()
        await self.async_request_refresh()

    async def async_grow_beenden(self) -> None:
        """Laufenden Grow archivieren und OHNE neuen Grow weiterlaufen
        (Klima laeuft "leer" weiter, keine Grow-Dokumentation)."""
        store = self._store()
        ents = self._ents()
        if store is None:
            return
        ctx = _Ctx(self.hass, ents)
        gstart_e = ents.get("grow_start")
        old_start = getattr(gstart_e, "native_value", None)
        if not isinstance(old_start, date):
            return  # kein aktiver Grow
        store.archive_grow(self.entry.entry_id, {
            "name": (getattr(ents.get("grow_name"), "native_value", "")
                     or "Grow"),
            "grow_typ": ctx.sel_raw("grow_typ") or "Photoperiodisch",
            "start": old_start.isoformat(),
            "ende": date.today().isoformat(),
            "strains": store.strains(self.entry.entry_id),
        })
        gstart_e.set_internal(None)
        be = ents.get("bluete_start")
        if be is not None:
            be.set_internal(None)
        sel = ents.get("strain_auswahl")
        if sel is not None:
            sel.refresh_options()
        await self.async_request_refresh()

    async def async_strain_ernten(self) -> None:
        """Gewaehlten Strain als geerntet markieren (Kalender-Eintrag,
        Terminserien enden; Strain bleibt dokumentiert)."""
        store = self._store()
        ents = self._ents()
        sel = ents.get("strain_auswahl")
        idx = sel.selected_index() if sel is not None else -1
        if store is None or idx < 0:
            return
        store.strain_ernten(self.entry.entry_id, idx)
        await self.async_request_refresh()

    async def async_grow_neu(self) -> None:
        """Laufenden Grow archivieren + frischen Grow starten (Start = heute)."""
        store = self._store()
        ents = self._ents()
        if store is None:
            return
        ctx = _Ctx(self.hass, ents)
        name_e = ents.get("grow_name")
        gstart_e = ents.get("grow_start")
        bstart_e = ents.get("bluete_start")
        old_start = getattr(gstart_e, "native_value", None)
        snapshot = {
            "name": (getattr(name_e, "native_value", "") or "Grow"),
            "grow_typ": ctx.sel_raw("grow_typ") or "Photoperiodisch",
            "start": old_start.isoformat() if isinstance(old_start, date) else None,
            "ende": date.today().isoformat(),
            "strains": store.strains(self.entry.entry_id),
        }
        store.archive_grow(self.entry.entry_id, snapshot)
        # Frischer Grow: Start = heute, Blüte-Start leeren; Strain-Startdatum an
        # den Grow-Start koppeln (direkt angelegte Strains starten mit dem Grow).
        if gstart_e is not None:
            gstart_e.set_internal(date.today())
        if bstart_e is not None:
            bstart_e.set_internal(None)
        sstart_e = ents.get("strain_start")
        if sstart_e is not None:
            sstart_e.set_internal(date.today())
        sel = ents.get("strain_auswahl")
        if sel is not None:
            sel.refresh_options()
        await self.async_request_refresh()

    # -- Benachrichtigungs-Zielgeraete --
    async def async_notify_add(self) -> None:
        store = self._store()
        ents = self._ents()
        picker = ents.get("benachrichtigung_geraet")
        if store is None or picker is None:
            return
        dienst = picker.selected_service()
        if dienst:
            store.add_notify_target(self.entry.entry_id, dienst)
            rem = ents.get("benachrichtigung_entfernen")
            if rem is not None:
                rem.refresh_options()
        await self.async_request_refresh()

    async def async_notify_remove(self) -> None:
        store = self._store()
        ents = self._ents()
        rem = ents.get("benachrichtigung_entfernen")
        if store is None or rem is None:
            return
        idx = rem.selected_index()
        if 0 <= idx < len(store.notify_targets(self.entry.entry_id)):
            store.remove_notify_target(self.entry.entry_id, idx)
            rem.refresh_options()
        await self.async_request_refresh()

    async def async_notiz_anlegen(self) -> None:
        """Notiz/Erinnerung aus dem Formular anlegen. Die gewaehlte
        Erinnerungsart setzt intern das bewaehrte Steuerwort im Titel
        (!täglich / !wöchentlich / !stumm; Einmalig = ohne)."""
        store = self._store()
        ents = self._ents()
        text_ent = ents.get("notiz_text")
        text = (getattr(text_ent, "native_value", "") or "").strip()
        if store is None or not text:
            return
        art = (getattr(ents.get("notiz_erinnerung"), "current_option", None)
               or "Einmalig")
        suffix = ""
        if art.startswith("Täglich"):
            suffix = " !täglich"
        elif art.startswith("Wöchentlich"):
            suffix = " !wöchentlich"
        elif art.startswith("Stumm"):
            suffix = " !stumm"
        due = getattr(ents.get("notiz_datum"), "native_value", None)
        if not isinstance(due, date):
            due = date.today()
        items = store.todos(self.entry.entry_id)
        items.append({
            "uid": _uuid.uuid4().hex,
            "summary": text + suffix,
            "status": "needs_action",
            "due": due.isoformat(),
            "description": None,
        })
        store.set_todos(self.entry.entry_id, items)
        todo = ents.get("notizen")
        if todo is not None:
            todo.async_write_ha_state()
        # Formular leeren fuer die naechste Notiz
        if text_ent is not None:
            await text_ent.async_set_value("")

    # -- Duengeplan ------------------------------------------------------
    async def async_duenger_anlegen(self) -> None:
        """Produkt aus dem Formular anlegen (Einmalig: erster Zeitpunkt
        gleich mit; weitere per 'Zeitpunkt hinzufuegen')."""
        store = self._store()
        ents = self._ents()
        ctx = _Ctx(self.hass, ents)
        name_ent = ents.get("duenger_name")
        pname = (getattr(name_ent, "native_value", "") or "").strip()
        if store is None or not pname:
            return
        # Produkt = reine Stammdaten; Anwendungs-Regeln kommen separat dazu
        # Hersteller: gewaehlter aus der Liste; Freitext nur als Fallback
        h_sel = getattr(ents.get("duenger_hersteller_sel"),
                        "current_option", None)
        if not h_sel or h_sel == "—":
            h_sel = (getattr(ents.get("duenger_hersteller"),
                             "native_value", "") or "").strip()
        p = {"id": _uuid.uuid4().hex, "name": pname,
             "hersteller": h_sel,
             "kategorie": ctx.sel_raw("duenger_kategorie") or "Dünger",
             "typ": ctx.sel_raw("duenger_typ") or "",
             "regeln": [],
             "form": ("Trocken" if (ctx.sel_raw("duenger_form") or "")
                      .startswith("Trocken") else "Flüssig"),
             "menge_einheit": ctx.sel_raw("duenger_menge_einheit") or "ml"}
        store.add_duenger_produkt(p)
        sel = ents.get("duenger_produkt")
        if sel is not None:
            sel.refresh_options()
        if name_ent is not None:
            await name_ent.async_set_value("")
        await self.async_request_refresh()

    def _regel_aus_formular(self, ctx) -> dict:
        return {"modus": ctx.sel_raw("duenger_plan_modus") or "Einmalig",
                "einheit": ctx.sel_raw("duenger_zeiteinheit") or "Wochen",
                "phase": ctx.sel_raw("duenger_phase") or "Ganzer Grow",
                "wert": int(ctx.num("duenger_zeitpunkt", 1)),
                "intervall": int(ctx.num("duenger_intervall", 7)),
                "menge": ctx.num("duenger_menge", 0),
                # Push-Verhalten haengt an der Regel (nicht am Produkt)
                "erinnerung": ("Intervall" if (ctx.sel_raw(
                    "duenger_erinnerung_modus") or "").startswith("Intervall")
                    else "Einmalig"),
                "erinnerung_intervall": int(
                    ctx.num("duenger_erinnerung_intervall", 4)),
                "erinnerung_einheit": ctx.sel_raw(
                    "duenger_erinnerung_einheit") or "Stunden"}

    async def async_duenger_regel_add(self) -> None:
        """EIN Regel-Formular: 'Normale Regel' -> Anwendungs-Regel am
        Produkt (alle verknuepften Strains); 'Sonderregel' -> nur der
        gewaehlte Strain, ersetzt dort die passende Normalregel."""
        store = self._store()
        ents = self._ents()
        ctx = _Ctx(self.hass, ents)
        sel = ents.get("duenger_produkt")
        pid = sel.selected_id() if sel is not None else None
        if store is None or not pid:
            return
        art = ctx.sel_raw("duenger_regel_art") or ""
        if art.startswith("Sonderregel"):
            ssel = ents.get("duenger_strain")
            idx = ssel.selected_index() if ssel is not None else -1
            if idx < 0:
                return
            store.strain_extra_add(self.entry.entry_id, idx, dict(
                self._regel_aus_formular(ctx), pid=pid, art="sonder"))
            esel = ents.get("duenger_extra_sel")
            if esel is not None:
                esel.refresh_options()
        else:
            store.add_produkt_regel(pid, self._regel_aus_formular(ctx))
            rsel = ents.get("duenger_regel_sel")
            if rsel is not None:
                rsel.refresh_options()
        await self.async_request_refresh()

    async def async_duenger_regel_remove(self) -> None:
        store = self._store()
        ents = self._ents()
        sel = ents.get("duenger_produkt")
        rsel = ents.get("duenger_regel_sel")
        pid = sel.selected_id() if sel is not None else None
        idx = rsel.selected_index() if rsel is not None else -1
        if store is None or not pid or idx < 0:
            return
        store.remove_produkt_regel(pid, idx)
        rsel.refresh_options()
        await self.async_request_refresh()

    async def async_duenger_entfernen(self) -> None:
        store = self._store()
        ents = self._ents()
        sel = ents.get("duenger_produkt")
        pid = sel.selected_id() if sel is not None else None
        if store is None or not pid:
            return
        store.remove_duenger_produkt(pid)
        sel.refresh_options()
        await self.async_request_refresh()

    async def async_duenger_link(self, verbinden: bool) -> None:
        """Gewaehltes Produkt mit gewaehltem Strain verknuepfen/trennen."""
        store = self._store()
        ents = self._ents()
        psel = ents.get("duenger_produkt")
        ssel = ents.get("duenger_strain")
        pid = psel.selected_id() if psel is not None else None
        idx = ssel.selected_index() if ssel is not None else -1
        if store is None or not pid or idx < 0:
            return
        store.duenger_link(self.entry.entry_id, idx, pid, verbinden)
        await self.async_request_refresh()

    async def async_hersteller_anlegen(self) -> None:
        """Neuen Hersteller aus dem Textfeld in die Auswahl-Liste."""
        store = self._store()
        ents = self._ents()
        te = ents.get("duenger_hersteller")
        name = (getattr(te, "native_value", "") or "").strip()
        if store is None or not name:
            return
        store.add_hersteller(name)
        sel = ents.get("duenger_hersteller_sel")
        if sel is not None:
            sel.refresh_options()
            await sel.async_select_option(name)
        if te is not None:
            await te.async_set_value("")

    async def async_duenger_hersteller_link(self, verbinden: bool) -> None:
        """Hersteller-Methode: alle Produkte des Herstellers fuer den Strain."""
        store = self._store()
        ents = self._ents()
        hsel = ents.get("duenger_hersteller_sel")
        ssel = ents.get("duenger_strain")
        h = getattr(hsel, "current_option", None)
        idx = ssel.selected_index() if ssel is not None else -1
        if store is None or not h or h == "—" or idx < 0:
            return
        store.hersteller_link(self.entry.entry_id, idx, h, verbinden)
        await self.async_request_refresh()

    async def async_duenger_extra_remove(self) -> None:
        store = self._store()
        ents = self._ents()
        ssel = ents.get("duenger_strain")
        esel = ents.get("duenger_extra_sel")
        sidx = ssel.selected_index() if ssel is not None else -1
        eidx = esel.selected_index() if esel is not None else -1
        if store is None or sidx < 0 or eidx < 0:
            return
        store.strain_extra_remove(self.entry.entry_id, sidx, eidx)
        esel.refresh_options()
        await self.async_request_refresh()
