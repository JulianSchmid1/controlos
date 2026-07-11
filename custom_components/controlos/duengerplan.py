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
(st.hersteller_links). Zusaetzlich kann ein Strain Extra-Regeln haben
(st.extra_regeln: eigener Plan + Menge fuer ein Produkt, gilt nur fuer
diesen Strain und ADDITIV zum normalen Plan).

Phasen-Referenz je Strain: "Ganzer Grow"/"Vegetation" = Strain-Start;
"Bluete" = Bluete-Start (Photoperiodisch) bzw. Strain-Start (Autoflower).
"""
from __future__ import annotations

from datetime import date, timedelta

KATEGORIE_ICON = {"Dünger": "💧", "Pflanzenschutzmittel": "🛡️",
                  "Nützlinge": "🐞"}


def menge_txt(menge, form) -> str:
    """'5 ml/L' / '20 g/kg' oder '' wenn keine Menge gesetzt."""
    try:
        m = float(menge)
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    einheit = "g/kg" if form == "Trocken" else "ml/L"
    return "%g %s" % (m, einheit)


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


def _plan_termine(plan: dict, p: dict, eintrag: dict, strain_start, ernte,
                  bluete_start, autoflower, von, bis) -> list[dict]:
    """Termine eines Plans (Produkt-Plan ODER Extra-Regel)."""
    out: list[dict] = []
    form = p.get("form", "Flüssig")
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

    # "Ersetzt"-Regeln schalten den Normalplan des Produkts fuer diesen
    # Strain ab (komplett individuelle Angaben statt additiv).
    ersetzt = {r.get("pid") for r in (st.get("extra_regeln") or [])
               if r.get("art") == "ersetzt"}

    # Normaler Plan: direkt verknuepft ODER Hersteller-Methode
    for p in produkte:
        if p.get("id") in ersetzt:
            continue
        if (p.get("id") in ids
                or (p.get("hersteller") or "").lower() in hlinks):
            out.extend(_plan_termine(p, p, _eintrag(p), strain_start, ernte,
                                     bluete_start, autoflower, von, bis))

    # Extra-Regeln (nur dieser Strain, additiv zum normalen Plan)
    for r in (st.get("extra_regeln") or []):
        p = pmap.get(r.get("pid"))
        if not p:
            continue
        plan = {"modus": r.get("modus", "Einmalig"),
                "einheit": r.get("einheit", "Tage"),
                "phase": r.get("phase", "Ganzer Grow"),
                "intervall": r.get("intervall", 7),
                "menge": r.get("menge"),
                "punkte": [{"wert": r.get("wert", 1),
                            "einheit": r.get("einheit", "Tage"),
                            "phase": r.get("phase", "Ganzer Grow"),
                            "menge": r.get("menge")}]}
        out.extend(_plan_termine(plan, p, _eintrag(p), strain_start, ernte,
                                 bluete_start, autoflower, von, bis))
    return out


def alle_termine(produkte: list, strains: list, autoflower: bool,
                 bluete_start: date | None, von: date, bis: date) -> list[dict]:
    out: list[dict] = []
    for st in strains:
        out.extend(termine_fuer_strain(produkte, st, autoflower,
                                       bluete_start, von, bis))
    out.sort(key=lambda t: t["datum"])
    return out
