"""ControlOS - Pflanzenpflege: Terminberechnung (pure Funktionen).

Produkte (global) tragen ihren Anwendungsplan selbst:
  {id, name, hersteller, kategorie, typ, form, modus, einheit, phase,
   punkte: [{wert, einheit, phase, menge}], intervall, menge}
- modus "Einmalig": jeder Punkt = Tag/Woche N ab Phasen-Referenz.
- modus "Wiederholend": ab Phasen-Referenz alle <intervall> Tage/Wochen,
  solange die Phase laeuft. Menge je Anwendung optional (Einheit aus der
  Form: Fluessig = ml/L, Trocken = g/kg).

Ein Produkt gilt fuer einen Strain, wenn es direkt verknuepft ist
(st.duenger) ODER sein Hersteller als Methode verknuepft ist
(st.hersteller_links).

Regel-Arten (st.extra_regeln, Feld "art"):
- "sonder" (neu, Standard): Sonderregel NUR fuer diesen Strain. Ersetzt
  die PASSENDE Normalregel des Produkts (gleicher Modus + Phase, bei
  Einmalig gleicher Zeitpunkt) - z.B. 10 ml statt 5 ml woechentlich;
  passt keine Normalregel, wirkt sie zusaetzlich. Andere Normalregeln
  und andere Strains bleiben unberuehrt.
- "zusaetzlich" (Altdaten): immer additiv zum Normalplan.
- "ersetzt" (Altdaten): schaltet den GANZEN Normalplan des Produkts
  fuer diesen Strain ab.

Push-Einstellungen (erinnerung/-_intervall/-_einheit: einmalig oder
Intervall bis abgehakt) haengen an JEDER Regel; Altdaten ohne diese
Felder erben sie vom Produkt.

Phasen-Referenz je Strain: "Ganzer Grow"/"Vegetation" = Strain-Start;
"Bluete" = Bluete-Start (Photoperiodisch) bzw. Strain-Start (Autoflower).
"""
from __future__ import annotations

from datetime import date, timedelta

KATEGORIE_ICON = {"Dünger": "💧", "Pflanzenschutzmittel": "🛡️",
                  "Nützlinge": "🐞"}


def menge_einheit(p: dict) -> str:
    """Mengen-Einheit eines Produkts (ml/L/g/kg; Altdaten: aus der Form)."""
    e = p.get("menge_einheit")
    if e:
        return e
    return "g" if p.get("form") == "Trocken" else "ml"


def menge_txt(menge, einheit) -> str:
    """'5 ml' / '20 g' / '1 L' oder '' wenn keine Menge gesetzt."""
    try:
        m = float(menge)
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    return "%g %s" % (m, einheit or "ml")


def _tage(wert, einheit) -> int:
    try:
        w = int(float(wert))
    except (TypeError, ValueError):
        return 0
    return w * 7 if einheit == "Wochen" else w


def _ref(phase: str, strain_start: date | None,
         bluete_start: date | None, autoflower: bool) -> date | None:
    if phase == "Blüte" and not autoflower:
        return bluete_start
    return strain_start


def _phase_ende(phase: str, strain_start, bluete_start, autoflower,
                ernte: date | None, fallback: date) -> date:
    if phase == "Vegetation" and not autoflower and bluete_start:
        return bluete_start
    if ernte:
        return ernte
    return fallback


def _mit_erinnerung(plan: dict, p: dict, eintrag: dict) -> dict:
    """Push-Einstellungen der Regel in den Termin (Fallback: Produkt)."""
    return dict(
        eintrag,
        erinnerung=(plan.get("erinnerung") or p.get("erinnerung")
                    or "Einmalig"),
        erinnerung_intervall=(plan.get("erinnerung_intervall")
                              or p.get("erinnerung_intervall") or 4),
        erinnerung_einheit=(plan.get("erinnerung_einheit")
                            or p.get("erinnerung_einheit") or "Stunden"))


def _deckt(sonder: dict, regel: dict) -> bool:
    """True, wenn die Sonderregel diese Normalregel ersetzt: gleicher
    Modus + gleiche Phase; bei Einmalig zusaetzlich derselbe Zeitpunkt."""
    modus = sonder.get("modus", "Einmalig")
    if (modus != regel.get("modus", "Einmalig")
            or sonder.get("phase", "Ganzer Grow")
            != regel.get("phase", "Ganzer Grow")):
        return False
    if modus == "Einmalig":
        return (_tage(sonder.get("wert", 1), sonder.get("einheit", "Tage"))
                == _tage(regel.get("wert", 1), regel.get("einheit", "Tage")))
    return True


def _plan_termine(plan: dict, p: dict, eintrag: dict, strain_start, ernte,
                  bluete_start, autoflower, von, bis) -> list[dict]:
    """Termine eines Plans (Produkt-Plan ODER Extra-Regel)."""
    out: list[dict] = []
    eintrag = _mit_erinnerung(plan, p, eintrag)
    form = menge_einheit(p)
    if plan.get("modus") == "Wiederholend":
        phase = plan.get("phase", "Ganzer Grow")
        ref = _ref(phase, strain_start, bluete_start, autoflower)
        schritt = _tage(plan.get("intervall", 7), plan.get("einheit", "Tage"))
        if ref is None or schritt <= 0:
            return out
        ende = min(bis, _phase_ende(phase, strain_start, bluete_start,
                                    autoflower, ernte, bis))
        mt = menge_txt(plan.get("menge"), form)
        d = ref
        while d <= ende:
            if d >= von:
                out.append(dict(eintrag, datum=d, menge=mt))
            d += timedelta(days=schritt)
    else:  # Einmalig: jeder Punkt einzeln
        for punkt in (plan.get("punkte") or []):
            phase = punkt.get("phase", "Ganzer Grow")
            ref = _ref(phase, strain_start, bluete_start, autoflower)
            if ref is None:
                continue
            offset = _tage(punkt.get("wert", 1), punkt.get("einheit", "Tage"))
            d = ref + timedelta(days=max(0, offset - 1))
            if von <= d <= bis:
                out.append(dict(eintrag, datum=d,
                                menge=menge_txt(punkt.get("menge"), form)))
    return out


def termine_fuer_strain(produkte: list, st: dict, autoflower: bool,
                        bluete_start: date | None,
                        von: date, bis: date) -> list[dict]:
    if st.get("geerntet"):
        return []   # geerntete Strains brauchen keine Anwendungen mehr
    try:
        strain_start = date.fromisoformat(
            st.get("start") or st.get("added") or "")
    except (TypeError, ValueError):
        return []
    ernte = None
    dauer = _tage(st.get("wert", st.get("wochen", 0)),
                  st.get("einheit", "Wochen"))
    if dauer:
        basis = strain_start if autoflower else bluete_start
        if basis:
            ernte = basis + timedelta(days=dauer)

    ids = st.get("duenger") or []
    hlinks = [h.lower() for h in (st.get("hersteller_links") or [])]
    pmap = {p.get("id"): p for p in produkte}
    out: list[dict] = []

    def _eintrag(p):
        return {"produkt": p.get("name", "?"),
                "hersteller": p.get("hersteller", ""),
                "kategorie": p.get("kategorie", "Dünger"),
                "typ": p.get("typ", ""),
                "strain": st.get("name", "?"),
                "pid": p.get("id")}

    # Altdaten: "ersetzt"-Regeln schalten den GANZEN Normalplan des
    # Produkts fuer diesen Strain ab.
    ersetzt = {r.get("pid") for r in (st.get("extra_regeln") or [])
               if r.get("art") == "ersetzt"}
    # Sonderregeln je Produkt: ersetzen nur die passende Normalregel.
    sonder: dict = {}
    for r in (st.get("extra_regeln") or []):
        if r.get("art") in (None, "sonder"):
            sonder.setdefault(r.get("pid"), []).append(r)

    # Normaler Plan: direkt verknuepft ODER Hersteller-Methode. Produkte
    # tragen ihre Anwendungs-Regeln als Liste ("regeln"); die Altstruktur
    # (Plan direkt am Produkt) wird weiter verstanden.
    for p in produkte:
        if p.get("id") in ersetzt:
            continue
        if not (p.get("id") in ids
                or (p.get("hersteller") or "").lower() in hlinks):
            continue
        regeln = p.get("regeln")
        sk = sonder.get(p.get("id")) or []
        plaene = ([regel_zu_plan(r) for r in regeln
                   if not any(_deckt(sr, r) for sr in sk)] if regeln
                  else ([p] if p.get("modus") else []))
        for plan in plaene:
            out.extend(_plan_termine(plan, p, _eintrag(p), strain_start,
                                     ernte, bluete_start, autoflower,
                                     von, bis))

    # Extra-Regeln (nur dieser Strain)
    for r in (st.get("extra_regeln") or []):
        p = pmap.get(r.get("pid"))
        if not p:
            continue
        out.extend(_plan_termine(regel_zu_plan(r), p, _eintrag(p),
                                 strain_start, ernte, bluete_start,
                                 autoflower, von, bis))
    return out


def regel_zu_plan(r: dict) -> dict:
    """Anwendungs-Regel -> Plan-Dict fuer _plan_termine."""
    return {"modus": r.get("modus", "Einmalig"),
            "einheit": r.get("einheit", "Tage"),
            "phase": r.get("phase", "Ganzer Grow"),
            "intervall": r.get("intervall", 7),
            "menge": r.get("menge"),
            "erinnerung": r.get("erinnerung"),
            "erinnerung_intervall": r.get("erinnerung_intervall"),
            "erinnerung_einheit": r.get("erinnerung_einheit"),
            "punkte": [{"wert": r.get("wert", 1),
                        "einheit": r.get("einheit", "Tage"),
                        "phase": r.get("phase", "Ganzer Grow"),
                        "menge": r.get("menge")}]}


def regel_txt(r: dict, einheit_m: str) -> str:
    """Kurzbeschreibung einer Regel fuer Listen/Selects."""
    m = menge_txt(r.get("menge"), einheit_m)
    if r.get("modus") == "Wiederholend":
        s = "↻ alle %s %s (%s)" % (r.get("intervall"), r.get("einheit"),
                                   r.get("phase"))
    else:
        s = "📅 %s %s (%s)" % (
            "Woche" if r.get("einheit") == "Wochen" else "Tag",
            r.get("wert"), r.get("phase"))
    s += (" · " + m) if m else ""
    if r.get("erinnerung") == "Intervall":
        s += " · 🔔alle %s %s" % (
            r.get("erinnerung_intervall", 4),
            "Tage" if r.get("erinnerung_einheit") == "Tage" else "Std.")
    return s


def alle_termine(produkte: list, strains: list, autoflower: bool,
                 bluete_start: date | None, von: date, bis: date) -> list[dict]:
    out: list[dict] = []
    for st in strains:
        out.extend(termine_fuer_strain(produkte, st, autoflower,
                                       bluete_start, von, bis))
    out.sort(key=lambda t: t["datum"])
    return out


def termine_gruppiert(termine: list[dict]) -> list[dict]:
    """Gleiche Anwendung (Datum + Produkt + Menge) ueber mehrere Strains
    zu EINEM Eintrag buendeln - Strains gesammelt statt je Strain eine
    Zeile. Sonderdosierungen haben eine andere Menge und bleiben dadurch
    automatisch eigene Eintraege. Ergebnis-Dicts tragen "strains" (Liste)
    statt "strain"."""
    out: list[dict] = []
    gruppen: dict = {}
    for t in termine:
        key = (t["datum"], t.get("pid"), t.get("menge") or "")
        g = gruppen.get(key)
        if g is None:
            g = dict(t, strains=[t["strain"]])
            gruppen[key] = g
            out.append(g)
        elif t["strain"] not in g["strains"]:
            g["strains"].append(t["strain"])
    return out
