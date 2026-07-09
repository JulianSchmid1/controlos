"""ControlOS - Regel-Logik (1:1-Port der erprobten Add-on-Logik, V0.15).

Ziel-Hysterese mit Latch + Mindestlaufzeiten, Geraetepaar-Hysterese,
KI-Bias (Integral-Setpoint-Shift), CO2 Dauer/Intervall + Max-Laufzeit,
Abluft Haupt-/Backup-Rolle, Klima-Steuermodi (Area/Geraet/Hybrid/Autonom).

Rein synchron & zustandsbehaftet (ein Regler je Bereich). Liest alles ueber
das ctx-Interface, gibt Shadow-Texte + gewuenschte Geraetezustaende zurueck -
der Coordinator entscheidet je Betriebsmodus, ob geschaltet wird.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

from .const import MIN_SWITCH_S


class Regler:
    def __init__(self, name: str):
        self.name = name
        self._latch: dict = {}
        self._last_sw: dict = {}

    # ------------------------------------------------------------------
    def latch(self, key, on_cond, off_cond, force_off=False, min_s=None):
        now = time.time()
        ms = MIN_SWITCH_S if min_s is None else min_s
        prev = self._latch.get(key, False)
        if force_off:
            new = False
        elif on_cond and off_cond:
            new = prev
        elif on_cond:
            new = True
        elif off_cond:
            new = False
        else:
            new = prev
        if new != prev:
            # Mindestlaufzeit je Geraet: erst nach Ablauf schalten, dann sofort.
            if (now - self._last_sw.get(key, 0)) < ms and not force_off:
                return prev
            self._latch[key] = new
            self._last_sw[key] = now
        return self._latch.get(key, new)

    @staticmethod
    def _licht_window(now_t, start, ende):
        """Position im Licht-Fenster. Rueckgabe:
        (in_window, minuten_seit_start, minuten_bis_ende, fensterlaenge_min)."""
        def m(t):
            return t.hour * 60 + t.minute
        now_m = now_t.hour * 60 + now_t.minute + now_t.second / 60.0
        s, e = m(start), m(ende)
        if s == e:                       # 24/0 -> Dauerlicht
            return True, now_m, 1440.0, 1440.0
        if e > s:                        # normales Fenster
            if s <= now_m < e:
                return True, now_m - s, e - now_m, float(e - s)
            return False, 0.0, 0.0, float(e - s)
        # Fenster ueber Mitternacht
        length = (1440 - s) + e
        if now_m >= s:
            return True, now_m - s, (1440 - now_m) + e, float(length)
        if now_m < e:
            return True, (1440 - s) + now_m, e - now_m, float(length)
        return False, 0.0, 0.0, float(length)

    @staticmethod
    def _ramp_pct(since, until, sunrise, sunset, hmax):
        """Helligkeit inkl. Sonnenauf-/-untergangs-Rampe (0..hmax)."""
        if sunrise > 0 and since < sunrise:
            return max(0, min(hmax, round(hmax * since / sunrise)))
        if sunset > 0 and until < sunset:
            return max(0, min(hmax, round(hmax * until / sunset)))
        return hmax

    def _can(self, key, min_s=MIN_SWITCH_S):
        return (time.time() - self._last_sw.get(key, 0)) >= min_s

    def _mark(self, key):
        self._last_sw[key] = time.time()

    def reset_device(self, latch_keys) -> None:
        """Schaltgedaechtnis eines Geraets verwerfen (nach Geraetewechsel)."""
        for k in latch_keys:
            self._latch.pop(k, None)
            self._last_sw.pop(k, None)

    def pair_hyst(self, ka, kb, val, lo, hi, target, nz,
                  a_present, b_present, a_dual, b_dual, force_off=False,
                  a_min=None, b_min=None):
        # Einzelgeraet: am ZIEL abschalten (saubere Hysterese, kein Uebertrocknen
        # bis zur gegenueberliegenden Bandkante). Sind BEIDE Geraete vorhanden,
        # bleibt ein Deadband target±nz, damit sie sich nicht gegenseitig jagen.
        # a_min/b_min = geraetespezifische Mindestlaufzeit (Sekunden).
        both = a_present and b_present
        if a_present:
            a_off = (target + nz) if both else target
            a_on = self.latch(ka, val >= hi, val <= a_off,
                              force_off=force_off, min_s=a_min)
        else:
            a_on = self.latch(ka, False, True)
        if b_present:
            b_off = (target - nz) if both else target
            b_on = self.latch(kb, val <= lo, val >= b_off,
                              force_off=force_off, min_s=b_min)
        else:
            b_on = self.latch(kb, False, True)
        return a_on, b_on

    @staticmethod
    def power_pct(val, near, far, pmin):
        try:
            frac = (val - near) / (far - near)
        except ZeroDivisionError:
            return 100
        frac = max(0.0, min(1.0, frac))
        return int(round(pmin + frac * (100 - pmin)))

    @staticmethod
    def stage_pick(val, near, far, opts):
        if len(opts) < 2:
            return opts[0] if opts else None
        try:
            frac = (val - near) / (far - near)
        except ZeroDivisionError:
            frac = 1.0
        frac = max(0.0, min(0.999, frac))
        return opts[int(frac * len(opts))]

    @staticmethod
    def fan_interval(mode, ein_min, intervall_min, force_on=False):
        if force_on or mode != "Intervall":
            return True
        period = max(1, int(intervall_min * 60))
        on_dur = max(0, int(ein_min * 60))
        return (int(time.time()) % period) < on_dur

    # ------------------------------------------------------------------
    def ki_bias(self, ctx, eff_modus, ist_tag, sys_modus, tank_voll,
                vpd, vpd_ziel, bias_out, bef_da=False, ent_da=False,
                temp_lever=False):
        """Adaptiver Bias - AUSSCHLIESSLICH fuer die VPD-Tagsteuerung.

        Nachts (statische Regelung) und im Feuchte-Modus wird weder gelernt
        noch angewendet; bei vollem Entfeuchter-Tank stoppt das Rechnen
        (eingefrorener Wert wird tagsueber weiter angewendet). Anti-Windup:
        fehlt der Aktor, der den Fehler beheben koennte (kein Befeuchter bei
        zu trockener Luft / kein Entfeuchter bei zu feuchter), wird nicht
        integriert, sondern der Bias zerfaellt gegen 0. Die frueheren
        Temp-/Feuchte-Biases sind abgeschafft und zerfallen gegen 0."""
        ki_active = ctx.sw("ki_modus") and sys_modus == "Geschlossenes System"

        def dec(v, minstep, nd):
            return round(0.0 if abs(v) < minstep else v * 0.9, nd)

        def bget(m, ph):
            return ctx.num("%s_bias_%s" % (m, ph), 0.0)

        def bput(m, ph, val):
            if abs(val - bget(m, ph)) > 1e-6:
                bias_out["%s_bias_%s" % (m, ph)] = val

        # Ausgediente Biases (Temp/Feuchte + Nacht-VPD) kontinuierlich abbauen
        for p in ("tag", "nacht"):
            bput("temp", p, dec(bget("temp", p), 0.1, 1))
            bput("hum", p, dec(bget("hum", p), 0.5, 1))
        bput("vpd", "nacht", dec(bget("vpd", "nacht"), 0.01, 3))

        vb = bget("vpd", "tag")
        if not ki_active:
            vb = dec(vb, 0.01, 3)
            bput("vpd", "tag", vb)
            return vb if (ist_tag and eff_modus == "VPD") else 0.0
        if not ist_tag or eff_modus != "VPD":
            return 0.0  # Nacht/Statisch & Feuchte-Modus: Bias komplett aussen vor
        if tank_voll or vpd is None:
            return vb   # Rechnen gestoppt, eingefrorener Wert gilt weiter
        e = vpd_ziel - vpd
        if not temp_lever and ((e > 0 and not ent_da) or (e < 0 and not bef_da)):
            # Aktor fehlt strukturell (kein Be-/Entfeuchter fuer diese Richtung)
            # und keine VPD->Temp-Kopplung -> Windup abbauen statt integrieren.
            vb = dec(vb, 0.01, 3)
            bput("vpd", "tag", vb)
            return vb
        vb = max(-0.4, min(0.4, round(vb + 0.008 * e, 3)))
        bput("vpd", "tag", vb)
        return vb

    # ------------------------------------------------------------------
    def dev_out(self, ctx, on, d_main, dimmbar_key, dimmer_key, dim, pmin,
                stufe_key=None, dev_map=None, dev_name=None, stage_frac=None):
        """Shadow-Text + Soll-Zustand fuer ein Geraet.

        stage_frac: expliziter Stufen-Anteil 0..1 (Zonen-Logik) statt der
        kontinuierlichen Ableitung aus dim."""
        if not d_main:
            return "kein Gerät"
        if dev_map is not None and dev_name:
            dev_map[dev_name] = {"entity": d_main, "on": bool(on),
                                 "pct": None, "stufe": None, "stufe_entity": None}
        if not on:
            return "AUS -> %s" % d_main
        dimmbar = ctx.sw(dimmbar_key) if dimmbar_key else False
        dimmer = ctx.sel(dimmer_key) if dimmer_key else None
        if dimmbar and dimmer and dim:
            pct = self.power_pct(dim[0], dim[1], dim[2], pmin)
            if dev_map is not None and dev_name:
                dev_map[dev_name]["pct"] = pct
                dev_map[dev_name]["dimmer_entity"] = dimmer
            return "AN %d%% -> %s" % (pct, dimmer)
        if stufe_key:
            seid = ctx.sel(stufe_key)
            if seid and dim:
                opts = ctx.attr(seid, "options", []) or []
                stg = (self.stage_pick(stage_frac, 0.0, 1.0, opts)
                       if stage_frac is not None
                       else self.stage_pick(dim[0], dim[1], dim[2], opts))
                if stg:
                    if dev_map is not None and dev_name:
                        dev_map[dev_name]["stufe"] = stg
                        dev_map[dev_name]["stufe_entity"] = seid
                    return "AN [Stufe %s] -> %s" % (stg, seid)
        return "AN -> %s" % d_main

    # ------------------------------------------------------------------
    def tick(self, ctx, d):
        """Ein Regelzyklus. d = abgeleitete Daten des Coordinators.

        Rueckgabe: (shadow: dict, devices: dict, klima_cmds: list, bias: dict)
        """
        shadow: dict = {}
        devices: dict = {}
        klima_cmds: list = []
        bias_out: dict = {}

        def dev(vorh, sel):
            if not ctx.sw("vorhanden_%s" % vorh):
                return None
            e = ctx.sel("geraet_%s" % sel)
            return e or None

        if not ctx.sw("aktiv"):
            shadow["status"] = "[%s] Inaktiv" % self.name
            for k in ("licht", "undercanopy", "befeuchter", "entfeuchter",
                      "heizung", "klima", "abluft", "co2", "ventilator", "umluft"):
                shadow[k] = "-"
            return shadow, devices, klima_cmds, bias_out

        modus = ctx.sel_raw("klima_modus") or "VPD"
        sys_modus = ctx.sel_raw("system_modus") or "Geschlossenes System"
        ist_tag = bool(d.get("data_ist_tag"))

        temp = d.get("data_temp_luft")
        hum = d.get("data_feuchte_luft")
        vpd = d.get("data_vpd")
        co2 = d.get("data_co2")
        ziel_temp = d.get("data_ziel_temp") or 25.0
        ziel_hum = d.get("data_ziel_feuchte") or 60.0
        vpd_ziel = ctx.num("vpd_ziel", 1.2)
        vpd_tol = ctx.num("vpd_toleranz", 0.2)
        vpd_min, vpd_max = vpd_ziel - vpd_tol, vpd_ziel + vpd_tol
        co2_ziel = ctx.num("co2_ziel", 800.0)
        co2_tol = ctx.num("co2_toleranz", 200.0)
        co2_min, co2_max = co2_ziel - co2_tol, co2_ziel + co2_tol
        temp_tol = ctx.num("temp_toleranz", 0.5)
        f_tol = ctx.num("feuchte_toleranz", 5.0)
        pmin = ctx.num("dimm_mindestleistung", 30.0)
        # Geraetespezifische Mindestlaufzeiten (Minuten -> Sekunden); nach Ablauf
        # wird sofort geschaltet. Fallback = globaler MIN_SWITCH_S.
        entf_min_s = ctx.num("entfeuchter_min_laufzeit", MIN_SWITCH_S / 60.0) * 60.0
        klima_min_s = ctx.num("klima_min_laufzeit", MIN_SWITCH_S / 60.0) * 60.0

        d_bef = dev("befeuchter", "befeuchter")
        d_ent = dev("entfeuchter", "entfeuchter")
        d_heiz = dev("heizung", "heizung")
        d_klima = dev("klima", "klima")
        d_abluft = dev("abluft", "abluft")
        d_co2 = dev("co2", "co2_ventil")
        d_vent = dev("ventilator", "ventilator")
        d_umluft = dev("umluft", "umluft")
        d_licht = dev("licht", "licht")

        # ===== LICHT: Zeitplan (sensorunabhaengig, keine Mindestlaufzeit -    =====
        # ===== Photoperiode hat Prioritaet) + optionale Sunrise/Sunset-Rampen =====
        d_uc = dev("undercanopy", "undercanopy")
        l_start = ctx.t("licht_start")
        l_ende = ctx.t("licht_ende")
        l_zyklus = ctx.sel_raw("licht_zyklus") or "Manuell"
        l_modus = ctx.sel_raw("licht_modus") or "An/Aus"
        uc_als_sonne = ctx.sw("undercanopy_als_sonne")
        sunrise = int(ctx.num("sunrise_dauer", 30))
        sunset = int(ctx.num("sunset_dauer", 30))
        hell = int(ctx.num("licht_helligkeit", 100))

        in_win, since, until = False, 0.0, 0.0
        if l_start and l_ende:
            in_win, since, until, _ = self._licht_window(
                datetime.now().time(), l_start, l_ende)
        _fenster = "%s-%s" % (
            l_start.strftime("%H:%M") if l_start else "?",
            l_ende.strftime("%H:%M") if l_ende else "?")
        if l_zyklus != "Manuell":
            _fenster = "%s: %s" % (l_zyklus, _fenster)

        l_dimmer = ctx.sel("dimmer_licht")
        l_dimmbar = bool(ctx.sw("dimmbar_licht") and l_dimmer)
        uc_dimmer = ctx.sel("dimmer_undercanopy")
        uc_dimmbar = bool(ctx.sw("dimmbar_undercanopy") and uc_dimmer)

        # Sonnenauf-/-untergangs-Modus ist der Master: nur dann rampt ueberhaupt
        # etwas (weder UC-als-Sonne noch Hauptlicht-Rampe bei "An/Aus").
        sonne = l_modus == "Sonnenauf-/-untergang"

        # --- Undercanopy als Sonne: UC uebernimmt den Sonnenaufgang, Hauptlicht
        # kommt erst nach der Aufgangszeit (Kern). Dimmbare UC faehrt eine echte
        # Rampe; nicht dimmbare UC geht einfach an -> gestufter Sonnenaufgang. ---
        if sonne and uc_als_sonne and d_uc:
            if uc_dimmbar:
                uc_pct = self._ramp_pct(since, until, sunrise, sunset, hell) if in_win else 0
                uc_on = in_win and uc_pct > 0
            else:
                uc_pct, uc_on = None, in_win  # nicht dimmbar -> voll an im Fenster
            devices["undercanopy"] = {"entity": d_uc, "on": bool(uc_on),
                                      "pct": uc_pct if (uc_on and uc_dimmbar) else None,
                                      "dimmer_entity": uc_dimmer if uc_dimmbar else None,
                                      "stufe": None, "stufe_entity": None}
            if uc_dimmbar:
                phase_uc = ("Aufgang" if in_win and since < sunrise else
                            ("Untergang" if in_win and until < sunset else
                             ("Tag" if in_win else "Nacht")))
                shadow["undercanopy"] = "%s %d%% (%s) -> %s" % (
                    phase_uc, uc_pct, _fenster, uc_dimmer) if uc_on else \
                    "AUS (%s) -> %s" % (_fenster, d_uc)
            else:
                shadow["undercanopy"] = ("AN (Sonne, %s) -> %s" % (_fenster, d_uc)) \
                    if uc_on else "AUS (%s) -> %s" % (_fenster, d_uc)
            # Hauptlicht: an erst wenn Aufgang fertig, aus sobald Untergang startet
            kern_on = in_win and since >= sunrise and until >= sunset
            if d_licht:
                devices["licht"] = {"entity": d_licht, "on": bool(kern_on),
                                    "pct": (hell if l_dimmbar else None) if kern_on else None,
                                    "dimmer_entity": l_dimmer if l_dimmbar else None,
                                    "stufe": None, "stufe_entity": None}
                shadow["licht"] = ("AN%s (Kern %s) -> %s" % (
                    " %d%%" % hell if l_dimmbar else "", _fenster,
                    l_dimmer if l_dimmbar else d_licht)) if kern_on else \
                    "AUS (wartet auf Sonnenaufgang, %s) -> %s" % (_fenster, d_licht)
            else:
                shadow["licht"] = "kein Gerät"

        # --- Sonst: Hauptlicht selbst (An/Aus oder eigene Sunrise/Sunset-Rampe) ---
        else:
            if d_licht:
                if sonne and l_dimmbar:
                    l_pct = self._ramp_pct(since, until, sunrise, sunset, hell) if in_win else 0
                    l_on = in_win and l_pct > 0
                    devices["licht"] = {"entity": d_licht, "on": bool(l_on),
                                        "pct": l_pct if l_on else None,
                                        "dimmer_entity": l_dimmer,
                                        "stufe": None, "stufe_entity": None}
                    phase_l = ("Aufgang" if in_win and since < sunrise else
                               ("Untergang" if in_win and until < sunset else "Tag"))
                    shadow["licht"] = "%s %d%% (%s) -> %s" % (
                        phase_l, l_pct, _fenster, l_dimmer) if l_on else \
                        "AUS (%s) -> %s" % (_fenster, d_licht)
                else:
                    devices["licht"] = {"entity": d_licht, "on": bool(in_win),
                                        "pct": (hell if l_dimmbar else None) if in_win else None,
                                        "dimmer_entity": l_dimmer if l_dimmbar else None,
                                        "stufe": None, "stufe_entity": None}
                    if in_win and l_dimmbar:
                        shadow["licht"] = "AN %d%% (%s) -> %s" % (hell, _fenster, l_dimmer)
                    elif in_win:
                        shadow["licht"] = "AN (%s) -> %s" % (_fenster, d_licht)
                    else:
                        shadow["licht"] = "AUS (%s) -> %s" % (_fenster, d_licht)
            else:
                shadow["licht"] = "kein Gerät"
            # Undercanopy folgt (falls vorhanden) einfach dem Licht-Fenster
            if d_uc:
                devices["undercanopy"] = {"entity": d_uc, "on": bool(in_win),
                                          "pct": (hell if uc_dimmbar else None) if in_win else None,
                                          "dimmer_entity": uc_dimmer if uc_dimmbar else None,
                                          "stufe": None, "stufe_entity": None}
                shadow["undercanopy"] = ("AN (%s) -> %s" % (_fenster, d_uc)) if in_win \
                    else "AUS (%s) -> %s" % (_fenster, d_uc)
            else:
                shadow["undercanopy"] = "kein Gerät"

        # Nacht statisch: nachts Feuchte statt VPD regeln (Schimmelschutz)
        eff_modus = modus
        if modus == "VPD" and not ist_tag and ctx.sw("nacht_statisch"):
            eff_modus = "Statisch (Nacht)"

        # Geraete-Ausfall: zugewiesen, aber nicht erreichbar -> wie "nicht
        # vorhanden" behandeln (verfaelscht sonst Regelung und KI wie ein
        # voller Tank). Meldung uebernimmt der Coordinator.
        def geraet_ok(eid):
            return bool(eid) and ctx.state(eid) not in (None, "unavailable",
                                                        "unknown")
        ausgefallen = {}
        for gname, geid in (("befeuchter", d_bef), ("entfeuchter", d_ent),
                            ("heizung", d_heiz), ("klima", d_klima),
                            ("co2", d_co2), ("abluft", d_abluft),
                            ("ventilator", d_vent), ("umluft", d_umluft),
                            ("licht", d_licht)):
            if geid and not geraet_ok(geid):
                ausgefallen[gname] = geid

        bef_da = d_bef is not None and "befeuchter" not in ausgefallen
        ent_da = d_ent is not None and "entfeuchter" not in ausgefallen
        heiz_da = d_heiz is not None and "heizung" not in ausgefallen
        klima_da = d_klima is not None and "klima" not in ausgefallen
        bef_dual = ctx.sw("dual_befeuchter")
        ent_dual = ctx.sw("dual_entfeuchter")

        # VPD->Temperatur-Kopplung (wie Altsystem): geschlossenes System,
        # VPD-Modus, Prio "feuchte", AC verfuegbar -> die AC-Zieltemperatur
        # wird dynamisch aus dem VPD-Ziel abgeleitet. Damit ist die Temperatur
        # ein VPD-Stellglied, und der Bias darf in BEIDE Richtungen lernen.
        # NUR TAGSUEBER: die dynamische Zieltemperatur wird luftfeuchte-basiert
        # gerechnet; nachts (kaltes Blatt) weicht die blattbasierte VPD-Messung
        # zu stark ab -> sie wuerde gegen den Entfeuchter arbeiten.
        vpd_temp_kopplung = (sys_modus == "Geschlossenes System"
                             and eff_modus == "VPD" and ist_tag
                             and (ctx.sel_raw("prio") or "temperatur") == "feuchte"
                             and klima_da)

        # Entfeuchter-Tank
        tank_eid = ctx.sel("sensor_tank")
        tank_voll = bool(tank_eid and ctx.state(tank_eid) == "on")

        # KI-Bias: verschiebt NUR den VPD-Korridor am Tag; Temp-/Feuchteziele
        # (insbesondere die statische Nachtregelung) bleiben unangetastet.
        # Rechnen stoppt bei vollem Tank ODER ausgefallenem Feuchte-Aktor.
        ki_stopp = (tank_voll or "befeuchter" in ausgefallen
                    or "entfeuchter" in ausgefallen)
        vb = self.ki_bias(ctx, eff_modus, ist_tag, sys_modus, ki_stopp,
                          vpd, vpd_ziel, bias_out,
                          bef_da=bef_da, ent_da=ent_da,
                          temp_lever=vpd_temp_kopplung)
        vpd_min += vb
        vpd_max += vb
        vpd_ziel += vb

        # -- Feuchte / VPD --
        ent_stage_frac = bef_stage_frac = None
        if eff_modus == "VPD" and vpd is not None:
            # Zonen wie im Altsystem (GanjOS): innere Toleranz-Haelfte =
            # perfekt (alles aus), aeussere Haelfte = 50%-Zone (Stufe
            # niedrig; nicht regelbar -> einfach AN), ausserhalb der
            # Toleranz = 100%-Zone (Stufe hoch). Die Schalt-Hysterese
            # liegt damit komplett INNERHALB der Toleranz; nz verhindert
            # Flattern an der Zonengrenze (+ MIN_SWITCH_S).
            nz = max(0.02, vpd_tol / 8.0)
            lo_perf = (vpd_min + vpd_ziel) / 2.0
            hi_perf = (vpd_ziel + vpd_max) / 2.0
            ent_on = (self.latch("ent", vpd <= lo_perf, vpd >= lo_perf + nz,
                                 min_s=entf_min_s)
                      if ent_da else self.latch("ent", False, True))
            bef_on = (self.latch("bef", vpd >= hi_perf, vpd <= hi_perf - nz)
                      if bef_da else self.latch("bef", False, True))
            if bef_on and ent_on:  # Latch-Uebergang: nie beide gleichzeitig
                if vpd >= vpd_ziel:
                    ent_on = False
                else:
                    bef_on = False
            bef_dim = (vpd, hi_perf, vpd_max)
            ent_dim = (vpd, lo_perf, vpd_min)
            ent_stage_frac = 0.999 if vpd <= vpd_min else 0.0
            bef_stage_frac = 0.999 if vpd >= vpd_max else 0.0
            hum_info = "VPD %.2f [%.2f|%.2f|%.2f]" % (vpd, vpd_min, vpd_ziel, vpd_max)
        elif hum is not None:
            ent_on, bef_on = self.pair_hyst(
                "ent", "bef", hum, ziel_hum - f_tol, ziel_hum + f_tol,
                ziel_hum, 1.0, ent_da, bef_da, ent_dual, bef_dual,
                a_min=entf_min_s)
            bef_dim = (hum, ziel_hum, ziel_hum - f_tol)
            ent_dim = (hum, ziel_hum, ziel_hum + f_tol)
            hum_info = "Feuchte %.1f (Ziel %.0f +-%.0f)" % (hum, ziel_hum, f_tol)
        else:
            ent_on = self.latch("ent", False, True)
            bef_on = self.latch("bef", False, True)
            bef_dim = ent_dim = None
            hum_info = "Feuchte ?"

        # Entfeuchter-Steuermodus (eigene Quelle/Ziel)
        entf_sm = ctx.sel_raw("entfeuchter_steuermodus") or "Area-Sensor"
        if ent_da and entf_sm != "Area-Sensor":
            d_hsens = ctx.sel("sensor_entfeuchter")
            dev_hum = ctx.fnum(d_hsens)
            if entf_sm == "Geräte-Sensor":
                h_ent, e_ziel = (dev_hum if dev_hum is not None else hum), ziel_hum
            elif entf_sm == "Hybrid" and dev_hum is not None and hum is not None:
                w = ctx.num("entfeuchter_hybrid_gewicht", 50.0) / 100.0
                h_ent, e_ziel = w * hum + (1 - w) * dev_hum, ziel_hum
            elif entf_sm == "Autonom":
                h_ent = hum
                e_ziel = ctx.num("entfeuchter_autonom_ziel_tag" if ist_tag
                                 else "entfeuchter_autonom_ziel_nacht", ziel_hum)
            else:
                h_ent, e_ziel = hum, ziel_hum
            if h_ent is not None:
                ent_on = self.latch("ent_sm", h_ent >= e_ziel + f_tol,
                                    h_ent <= e_ziel, min_s=entf_min_s)
                ent_dim = (h_ent, e_ziel, e_ziel + f_tol)
                ent_stage_frac = None  # Stufe wieder aus dim ableiten
                hum_info += " | Entf[%s] %.1f->Z%.1f" % (entf_sm[:4], h_ent, e_ziel)

        if tank_voll:
            ent_on = False

        # -- Temperatur --
        if temp is not None:
            cool_need = self.latch("cool", temp >= ziel_temp + temp_tol, temp <= ziel_temp)
            heat_need = self.latch("heat", temp <= ziel_temp - temp_tol, temp >= ziel_temp)
            temp_info = "Temp %.1f (Ziel %.1f +-%.1f)" % (temp, ziel_temp, temp_tol)
        else:
            cool_need = self.latch("cool", False, True)
            heat_need = self.latch("heat", False, True)
            temp_info = "Temp ?"
        heiz_on = heat_need and heiz_da

        # -- Klima --
        klima_is_climate = bool(d_klima and d_klima.startswith("climate."))
        klima_modes = (ctx.attr(d_klima, "hvac_modes", []) or []) if klima_is_climate else []
        klima_sm = ctx.sel_raw("klima_steuermodus") or "Autonom"
        dev_temp = None
        if klima_is_climate:
            try:
                dev_temp = float(ctx.attr(d_klima, "current_temperature"))
            except (TypeError, ValueError):
                dev_temp = None
        if klima_sm == "Geräte-Sensor":
            ctrl_temp = dev_temp if dev_temp is not None else temp
        elif klima_sm == "Hybrid" and dev_temp is not None and temp is not None:
            w = ctx.num("klima_hybrid_gewicht", 50.0) / 100.0
            ctrl_temp = w * temp + (1 - w) * dev_temp
        else:
            ctrl_temp = temp

        # VPD->Temp-Kopplung: AC-Zieltemperatur = die Temperatur, die bei
        # aktueller Luftfeuchte den VPD-Zielwert ergibt (Magnus umgekehrt,
        # vpd_ziel enthaelt bereits den Bias). Sonst normales Temperatur-Ziel.
        klima_ziel_eff = ziel_temp
        if vpd_temp_kopplung and hum is not None and vpd_ziel is not None:
            svp_need = vpd_ziel / max(0.01, 1.0 - hum / 100.0)
            if 0.05 < svp_need < 8.0:
                lv = math.log(svp_need / 0.6108)
                klima_ziel_eff = max(16.0, min(
                    30.0, round(237.3 * lv / (17.27 - lv), 1)))

        klima_dry_need = False
        if hum is not None and not ent_da and "dry" in klima_modes:
            klima_dry_need = self.latch("kdry", hum >= ziel_hum + f_tol, hum <= ziel_hum)
        if ctrl_temp is not None:
            kcool = self.latch("kcool", ctrl_temp >= klima_ziel_eff + temp_tol, ctrl_temp <= klima_ziel_eff)
            kheat = self.latch("kheat", ctrl_temp <= klima_ziel_eff - temp_tol, ctrl_temp >= klima_ziel_eff)
        else:
            kcool = self.latch("kcool", False, True)
            kheat = self.latch("kheat", False, True)
        aktiv_mode = "off"
        if d_klima:
            if kcool:
                aktiv_mode = "cool"
            elif klima_is_climate and kheat and not heiz_da and "heat" in klima_modes:
                aktiv_mode = "heat"
            elif klima_dry_need:
                aktiv_mode = "dry"

        _mmap = {"Kühlen": "cool", "Heizen": "heat", "Auto": "auto", "Aus": "off"}
        spiegel = _mmap.get(ctx.sel_raw("klima_modus_tag" if ist_tag else "klima_modus_nacht") or "Aus", "off")
        klima_fan = ctx.sel_raw("klima_fan_tag" if ist_tag else "klima_fan_nacht") or "auto"

        if klima_sm == "Autonom":
            klima_mode = spiegel
            # Bei VPD->Temp-Kopplung gilt auch im Autonom-Modus das dynamische
            # Ziel (sonst das manuelle AC-Ziel Tag/Nacht).
            klima_target = (round(klima_ziel_eff, 1) if vpd_temp_kopplung
                            else ctx.num("klima_ziel_tag" if ist_tag
                                         else "klima_ziel_nacht", ziel_temp))
        else:
            klima_mode = aktiv_mode
            klima_target = round(klima_ziel_eff, 1)
        if not d_klima:
            klima_mode = "off"
        kuehl_on = klima_mode == "cool"
        klima_fan_eff = klima_fan if klima_mode in ("cool", "heat") else "auto"

        # LIVE-Klima (nur Diffs). Wird jetzt direkt vom Betriebsmodus gesteuert
        # (Steuern = live schalten, Monitor = nur Shadow) - kein separater
        # Scharfschalter mehr.
        klima_schalten = ctx.sel_raw("betriebsmodus") == "Steuern"
        klima_acted = ""
        if klima_schalten and klima_is_climate:
            if klima_sm in ("Area-Sensor", "Hybrid") and not d.get("_temp_fresh", True):
                klima_acted = " [HALT: Sensor veraltet]"
            else:
                cur_mode = ctx.state(d_klima)
                cur_temp = ctx.attr(d_klima, "temperature")
                cur_fan = ctx.attr(d_klima, "fan_mode")
                fan_ok = klima_fan_eff in (ctx.attr(d_klima, "fan_modes", []) or [])
                sent = []
                if klima_mode != cur_mode:
                    if self._can("rt_klima_mode", klima_min_s):
                        klima_cmds.append(("climate", "set_hvac_mode",
                                           {"entity_id": d_klima, "hvac_mode": klima_mode}))
                        self._mark("rt_klima_mode")
                        sent.append("Modus=" + klima_mode)
                    else:
                        klima_acted = " [warte Mindestzeit]"
                if klima_mode != "off":
                    try:
                        if cur_temp is None or abs(float(cur_temp) - float(klima_target)) >= 0.25:
                            klima_cmds.append(("climate", "set_temperature",
                                               {"entity_id": d_klima, "temperature": klima_target}))
                            sent.append("%.1fC" % klima_target)
                    except (TypeError, ValueError):
                        pass
                    if fan_ok and klima_fan_eff != cur_fan:
                        klima_cmds.append(("climate", "set_fan_mode",
                                           {"entity_id": d_klima, "fan_mode": klima_fan_eff}))
                        sent.append("Fan=" + klima_fan_eff)
                klima_acted = (" [-> " + ", ".join(sent) + "]") if sent else (klima_acted or " [synchron]")

        # -- CO2 --
        co2_auto = ctx.sw("co2_automatik")
        co2_betrieb = ctx.sel_raw("co2_betrieb_modus") or "Dauerbetrieb"
        co2_note = ""
        now_c = time.time()
        co2_maxlauf = ctx.num("co2_max_laufzeit_min", 15.0) * 60
        if not (d_co2 and co2 is not None and co2_auto and ist_tag):
            co2_on = self.latch("co2", False, True, force_off=True)
            self._last_sw["co2_on_start"] = 0
            if d_co2 and not co2_auto:
                co2_note = " [Automatik aus]"
        elif now_c < self._last_sw.get("co2_cooldown_until", 0):
            rest = int((self._last_sw["co2_cooldown_until"] - now_c) / 60) + 1
            co2_on = self.latch("co2", False, True, force_off=True)
            self._last_sw["co2_on_start"] = 0
            co2_note = " [Schutz-Pause %dmin]" % rest
        else:
            if co2_betrieb == "Intervall":
                iv = self.fan_interval("Intervall", ctx.num("co2_dauer_min", 5),
                                       ctx.num("co2_intervall_min", 30))
                want = iv and co2 < co2_max
                co2_on = self.latch("co2", want, not want)
                co2_note = " [Intervall]"
            else:
                co2_on = self.latch("co2", co2 <= co2_min, co2 >= co2_max)
                co2_note = " [Dauer]"
            if co2_on:
                if self._last_sw.get("co2_on_start", 0) == 0:
                    self._last_sw["co2_on_start"] = now_c
                elif now_c - self._last_sw["co2_on_start"] >= co2_maxlauf:
                    co2_on = False
                    self._last_sw["co2_cooldown_until"] = now_c + co2_maxlauf
                    self._last_sw["co2_on_start"] = 0
                    co2_note = " [Max-Laufzeit -> Pause]"
            else:
                self._last_sw["co2_on_start"] = 0

        # -- Ventilator / Umluft --
        vent_mode = ctx.sel_raw("ventilator_modus") or "Dauerbetrieb"
        umluft_mode = ctx.sel_raw("umluft_modus") or "Dauerbetrieb"
        vent_on = d_vent is not None and self.fan_interval(
            vent_mode, ctx.num("ventilator_ein_min", 5), ctx.num("ventilator_intervall_min", 15))
        umluft_force = (umluft_mode == "Intervall" and co2_on)
        umluft_on = d_umluft is not None and self.fan_interval(
            umluft_mode, ctx.num("umluft_ein_min", 5), ctx.num("umluft_intervall_min", 15),
            force_on=umluft_force)

        # -- Abluft: offen=Haupt, geschlossen=Backup --
        abluft_modus = ctx.sel_raw("abluft_modus") or "Auto"
        t_zu, h_zu = d.get("data_temp_zuluft"), d.get("data_feuchte_zuluft")
        ab_need_cool = temp is not None and temp >= ziel_temp + temp_tol
        ab_need_dehum = hum is not None and hum >= ziel_hum + f_tol
        ab_cool_ok = ab_need_cool and (t_zu is None or t_zu <= temp - 0.5)
        ab_dehum_ok = ab_need_dehum and (h_zu is None or h_zu <= hum - 2.0)
        ab_normal_on = ab_cool_ok or ab_dehum_ok

        bk_temp = ctx.num("abluft_backup_temp", 30.0)
        bk_hum = ctx.num("abluft_backup_hum", 70.0)
        bk_co2 = ctx.num("abluft_backup_co2", 1500.0)
        bk_vpd = ctx.num("abluft_backup_vpd", 2.0)
        bk_over = ((temp is not None and temp >= bk_temp) or
                   (hum is not None and hum >= bk_hum) or
                   (co2 is not None and co2 >= bk_co2) or
                   (vpd is not None and vpd >= bk_vpd))
        now_t = time.time()
        if ab_normal_on:
            self._last_sw["abluft_active"] = now_t
        disarm_s = ctx.num("abluft_backup_disarm_min", 10.0) * 60
        ab_idle = (now_t - self._last_sw.get("abluft_active", 0)) >= disarm_s
        bk_safe = ((temp is None or temp <= ziel_temp + 0.5) and
                   (hum is None or hum <= ziel_hum + f_tol) and
                   (co2 is None or co2 <= co2_max) and
                   (vpd is None or vpd <= vpd_max))
        backup_armed = self.latch("abluft_backup", bk_over, bk_safe and ab_idle)

        abluft_on, abluft_dim, abluft_role = False, None, "AUS"
        if not d_abluft or abluft_modus == "Deaktiviert":
            abluft_on = self.latch("abluft", False, True)
            abluft_role = "Deaktiviert" if abluft_modus == "Deaktiviert" else "AUS"
        else:
            offen = sys_modus == "Offenes System"
            if offen:
                abluft_on = self.latch("abluft", ab_normal_on, not ab_normal_on)
                abluft_role = "Haupt"
            elif backup_armed:
                abluft_on = self.latch("abluft", ab_normal_on, not ab_normal_on)
                abluft_role = "Backup-AKTIV"
            else:
                abluft_on = self.latch("abluft", False, True)
                abluft_role = "Backup-bereit"
            if abluft_on:
                far_t = (ziel_temp + 1.5) if offen else bk_temp
                far_h = (ziel_hum + f_tol) if offen else bk_hum
                if ab_cool_ok and temp is not None:
                    abluft_dim = (temp, ziel_temp, far_t)
                elif ab_dehum_ok and hum is not None:
                    abluft_dim = (hum, ziel_hum, far_h)

        # ===== Ausgabe =====
        shadow["befeuchter"] = self.dev_out(
            ctx, bef_on, d_bef, "dimmbar_befeuchter", "dimmer_befeuchter",
            bef_dim, pmin, dev_map=devices, dev_name="befeuchter",
            stage_frac=bef_stage_frac)
        if d_ent and tank_voll:
            devices["entfeuchter"] = {"entity": d_ent, "on": False, "pct": None,
                                      "stufe": None, "stufe_entity": None}
            shadow["entfeuchter"] = "PAUSE (Tank voll) -> %s" % d_ent
        else:
            shadow["entfeuchter"] = self.dev_out(
                ctx, ent_on, d_ent, "dimmbar_entfeuchter", "dimmer_entfeuchter",
                ent_dim, pmin, stufe_key="stufe_entfeuchter",
                dev_map=devices, dev_name="entfeuchter",
                stage_frac=ent_stage_frac)
        shadow["heizung"] = self.dev_out(
            ctx, heiz_on, d_heiz, "dimmbar_heizung", "dimmer_heizung",
            None, pmin, dev_map=devices, dev_name="heizung")

        _live = "LIVE" if klima_schalten else "Shadow"
        _sm = {"Area-Sensor": "Area", "Geräte-Sensor": "Gerät",
               "Autonom": "Auto-S", "Hybrid": "Hybrid"}.get(klima_sm, klima_sm)
        if not d_klima:
            shadow["klima"] = "kein Gerät"
        elif not klima_is_climate:
            _on = klima_mode == "cool"
            devices["klima"] = {"entity": d_klima, "on": _on, "pct": None,
                                "stufe": None, "stufe_entity": None}
            shadow["klima"] = "[%s/%s] %s -> %s%s" % (
                _live, _sm, "AN (Kühlen)" if _on else "AUS", d_klima, klima_acted)
        elif klima_mode == "off":
            shadow["klima"] = "[%s/%s] AUS -> %s%s" % (_live, _sm, d_klima, klima_acted)
        else:
            _ml = {"cool": "Kühlen", "heat": "Heizen", "dry": "Entfeuchten",
                   "auto": "Auto"}.get(klima_mode, klima_mode)
            _tgt = " @ %.1fC" % klima_target if klima_mode in ("cool", "heat", "auto") else ""
            shadow["klima"] = "[%s/%s] %s (%s%s, fan %s) -> %s%s" % (
                _live, _sm, klima_mode.upper(), _ml, _tgt, klima_fan_eff, d_klima, klima_acted)

        _ab = self.dev_out(ctx, abluft_on, d_abluft, "dimmbar_abluft",
                           "dimmer_abluft", abluft_dim, pmin,
                           dev_map=devices, dev_name="abluft")
        shadow["abluft"] = ("[%s] %s" % (abluft_role, _ab)) if d_abluft else _ab

        if d_co2:
            devices["co2"] = {"entity": d_co2, "on": bool(co2_on), "pct": None,
                              "stufe": None, "stufe_entity": None}
            shadow["co2"] = ("AN -> %s" % d_co2 if co2_on else "AUS -> %s" % d_co2) + co2_note
        else:
            shadow["co2"] = "kein Gerät"

        if not d_vent:
            shadow["ventilator"] = "kein Gerät"
        else:
            devices["ventilator"] = {"entity": d_vent, "on": bool(vent_on), "pct": None,
                                     "stufe": None, "stufe_entity": None}
            if not vent_on:
                shadow["ventilator"] = "AUS (%s) -> %s" % (vent_mode, d_vent)
            else:
                vdimmer = ctx.sel("dimmer_ventilator")
                if ctx.sw("dimmbar_ventilator") and vdimmer:
                    spd = int(ctx.num("ventilator_speed", 100))
                    devices["ventilator"]["pct"] = spd
                    devices["ventilator"]["dimmer_entity"] = vdimmer
                    shadow["ventilator"] = "AN %d%% (%s) -> %s" % (spd, vent_mode, vdimmer)
                else:
                    shadow["ventilator"] = "AN (%s) -> %s" % (vent_mode, d_vent)

        if not d_umluft:
            shadow["umluft"] = "kein Gerät"
        else:
            devices["umluft"] = {"entity": d_umluft, "on": bool(umluft_on), "pct": None,
                                 "stufe": None, "stufe_entity": None}
            if not umluft_on:
                shadow["umluft"] = "AUS (%s) -> %s" % (umluft_mode, d_umluft)
            elif umluft_force:
                shadow["umluft"] = "AN [CO2-Durchmischung] -> %s" % d_umluft
            else:
                shadow["umluft"] = "AN (%s) -> %s" % (umluft_mode, d_umluft)

        # Ausgefallene Geraete: nicht ansteuern + deutlich markieren
        for gname, geid in ausgefallen.items():
            devices.pop(gname, None)
            shadow[gname] = "⚠️ AUSGEFALLEN -> %s" % geid

        ki_status = (" | KI-VPD %+.2f" % vb) if (ctx.sw("ki_modus") and vb) else ""
        phase = ctx.sel_raw("wuchsphase") or "-"
        shadow["status"] = (
            "[%s] %s%s | %s | %s | %s -> %s | %s -> %s | CO2 %s -> %s%s" % (
                self.name, phase, " LIVE-Klima" if klima_schalten else "",
                "Tag" if ist_tag else "Nacht", eff_modus, hum_info,
                "entfeuchten" if ent_on else ("befeuchten" if bef_on else "halten"),
                temp_info,
                "heizen" if (heiz_on or klima_mode == "heat") else (
                    "kühlen" if kuehl_on else (
                        "entfeuchten(Klima)" if klima_mode == "dry" else "halten")),
                "?" if co2 is None else str(int(co2)),
                "dosieren" if co2_on else "aus", ki_status))
        return shadow, devices, klima_cmds, bias_out
