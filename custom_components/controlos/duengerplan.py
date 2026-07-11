"""ControlOS - Duengeplan: Terminberechnung (pure Funktionen).

Produkte (global) tragen ihren Anwendungsplan selbst:
  {id, name, hersteller, kategorie, typ, modus, einheit, phase,
   punkte: [{wert, einheit, phase}], intervall}
- modus "Einmalig": jeder Punkt = Tag/Woche N ab Phasen-Referenz.
- modus "Wiederholend": ab Phasen-Referenz alle <intervall> Tage/Wochen,
  solange die Phase laeuft.
Phasen-Referenz je Strain: "Ganzer Grow"/"Vegetation" = Strain-Start;
"Bluete" = Bluete-Start (Photoperiodisch, gemeinsames Datum) bzw.
Strain-Start (Autoflower: Bluete zaehlt ab Tag 1).
"""
from __future__ import annotations

from datetime import date, timedelta

KATEGORIE_ICON = {"Dünger": "💧", "Pflanzenschutzmittel": "🛡️",
                  "Nützlinge": "🐞"}


def _tage(wert, einheit) -> int:
    try:
        w = int(float(wert))
    except (TypeError, ValueError):
        return 0
    return w * 7 if einheit == "Wochen" else w


def _ref(phase: str, strain_start: date | None,
         bluete_start: date | None, autoflower: bool) -> date | None:
    """Referenzdatum fuer eine Plan-Phase."""
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


def termine_fuer_strain(produkte: list, st: dict, autoflower: bool,
                        bluete_start: date | None,
                        von: date, bis: date) -> list[dict]:
    """Alle Anwendungs-Termine eines Strains im Fenster [von, bis].

    Rueckgabe: [{datum, produkt, hersteller, kategorie, typ, strain}].
    """
    try:
        strain_start = date.fromisoformat(
            st.get("start") or st.get("added") or "")
    except (TypeError, ValueError):
        return []
    # geschaetzte Ernte als Wiederholungs-Ende
    ernte = None
    dauer = _tage(st.get("wert", st.get("wochen", 0)),
                  st.get("einheit", "Wochen"))
    if dauer:
        basis = strain_start if autoflower else bluete_start
        if basis:
            ernte = basis + timedelta(days=dauer)

    ids = st.get("duenger") or []
    out: list[dict] = []
    for p in produkte:
        if p.get("id") not in ids:
            continue
        eintrag = {"produkt": p.get("name", "?"),
                   "hersteller": p.get("hersteller", ""),
                   "kategorie": p.get("kategorie", "Dünger"),
                   "typ": p.get("typ", ""),
                   "strain": st.get("name", "?"),
                   "pid": p.get("id")}
        if p.get("modus") == "Wiederholend":
            phase = p.get("phase", "Ganzer Grow")
            ref = _ref(phase, strain_start, bluete_start, autoflower)
            if ref is None:
                continue
            schritt = _tage(p.get("intervall", 7), p.get("einheit", "Tage"))
            if schritt <= 0:
                continue
            ende = min(bis, _phase_ende(phase, strain_start, bluete_start,
                                        autoflower, ernte, bis))
            d = ref
            while d <= ende:
                if d >= von:
                    out.append(dict(eintrag, datum=d))
                d += timedelta(days=schritt)
        else:  # Einmalig: jeder Punkt einzeln
            for punkt in (p.get("punkte") or []):
                phase = punkt.get("phase", "Ganzer Grow")
                ref = _ref(phase, strain_start, bluete_start, autoflower)
                if ref is None:
                    continue
                offset = _tage(punkt.get("wert", 1),
                               punkt.get("einheit", "Tage"))
                d = ref + timedelta(days=max(0, offset - 1))
                if von <= d <= bis:
                    out.append(dict(eintrag, datum=d))
    return out


def alle_termine(produkte: list, strains: list, autoflower: bool,
                 bluete_start: date | None, von: date, bis: date) -> list[dict]:
    out: list[dict] = []
    for st in strains:
        out.extend(termine_fuer_strain(produkte, st, autoflower,
                                       bluete_start, von, bis))
    out.sort(key=lambda t: t["datum"])
    return out
