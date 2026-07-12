"""ControlOS - Datenlogger + echte KI (VPD-Prognose).

Je Bereich werden Klima-Zeilen in Monats-CSVs gesammelt
(/config/controlos_data/<slug>-YYYY-MM.csv, Speicherzeit je Bereich
einstellbar). Auf diesen Daten trainiert stuendlich je Prognose-Horizont
(15/30/60/120 min) eine Ridge-Regression (pure Python, keine
Abhaengigkeiten) - Ergebnis ist eine VPD-Prognose-Kurve.

Alle Methoden ausser den reinen Property-Zugriffen sind blockierend und
laufen im Executor (async_add_executor_job).
"""
from __future__ import annotations

import csv
import logging
import math
import os
import threading
import time

_LOGGER = logging.getLogger(__name__)

FIELDS = ["ts", "temp", "hum", "vpd", "blatt", "co2", "ist_tag",
          "bef", "ent", "klima", "minute",
          # Geraete-Detailsignale (2026-07): AC-Kompressor/Fuehler/Aussen/
          # Luefter, Entfeuchter-Stufe/-Feuchte, Licht/UC/UV (Abwaerme).
          # Alte Zeilen ohne diese Spalten bekommen Naeherungs-Fallbacks.
          "kwatt", "k_ist", "k_aussen", "k_fan",
          "ent_stufe", "ent_hum", "licht", "uc_pct", "uv"]
HORIZONS_MIN = [5, 15, 30, 60, 120]   # Prognose-Horizonte (Minuten)
MIN_ROWS = 2000          # ab hier wird trainiert (~17 h Daten)
MAX_ROWS = 60000         # Trainings-Cap (~3 Wochen bei 30s-Takt)
RIDGE = 1.0              # L2-Regularisierung
FLUSH_EVERY = 10         # Zeilen puffern, dann schreiben (SD-schonend)


class KiEngine:
    def __init__(self, base_dir: str, slug: str):
        self.dir = base_dir
        self.slug = slug
        self._buf: list[dict] = []
        self._migrated: set[str] = set()
        self._lock = threading.Lock()
        self.modelle: dict[int, list[float]] = {}   # Horizont(min) -> Gewichte
        self.mae: dict[int, float] = {}             # Horizont(min) -> MAE
        self.n_rows = 0
        self.trained_at = 0.0

    @property
    def weights(self):
        """Abwaertskompatibel: wahr, sobald Modelle existieren."""
        return self.modelle or None

    # -- Dateien ------------------------------------------------------
    def _path(self, ym: str) -> str:
        return os.path.join(self.dir, "%s-%s.csv" % (self.slug, ym))

    def _months(self) -> list[str]:
        """Vorhandene Monats-Kennungen (YYYY-MM), alt -> neu."""
        try:
            pre = self.slug + "-"
            out = sorted(f[len(pre):-4] for f in os.listdir(self.dir)
                         if f.startswith(pre) and f.endswith(".csv"))
            return out
        except OSError:
            return []

    # -- Logging ------------------------------------------------------
    def append(self, row: dict) -> None:
        with self._lock:
            self._buf.append(row)
            if len(self._buf) < FLUSH_EVERY:
                return
            rows, self._buf = self._buf, []
        self._write(rows)

    def _migrate(self, path: str) -> None:
        """Bestehende Monatsdatei einmalig auf den aktuellen Header heben.

        Neue Spalten werden leer aufgefuellt (Features nutzen dann ihre
        Fallback-Naeherungen). Noetig, weil DictReader sonst die neuen
        Werte am alten Header vorbei ins Leere sortieren wuerde."""
        if path in self._migrated:
            return
        try:
            with open(path, newline="") as f:
                first = f.readline().rstrip("\r\n")
            if first == ",".join(FIELDS):
                self._migrated.add(path)
                return
            with open(path, newline="") as f:
                alt = list(csv.DictReader(f))
            tmp = path + ".tmp"
            with open(tmp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS, restval="",
                                   extrasaction="ignore")
                w.writeheader()
                for r in alt:
                    r.pop(None, None)
                    w.writerow(r)
            os.replace(tmp, path)
            self._migrated.add(path)
            _LOGGER.info("KI-Datenlog %s auf neues Spaltenformat migriert "
                         "(%d Zeilen)", os.path.basename(path), len(alt))
        except OSError:
            _LOGGER.exception("KI-Datenlog-Migration")

    def _write(self, rows: list[dict]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        path = self._path(time.strftime("%Y-%m"))
        neu = not os.path.exists(path)
        if not neu:
            self._migrate(path)
        try:
            with open(path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if neu:
                    w.writeheader()
                w.writerows(rows)
        except OSError:
            _LOGGER.exception("KI-Datenlog schreiben")

    def cleanup(self, keep_months: int) -> None:
        """Monats-Dateien loeschen, die aelter als keep_months sind."""
        months = self._months()
        for ym in months[:-keep_months] if keep_months > 0 else []:
            try:
                os.remove(self._path(ym))
                _LOGGER.info("KI-Datenlog %s-%s geloescht (Speicherzeit)",
                             self.slug, ym)
            except OSError:
                _LOGGER.exception("KI-Datenlog loeschen")

    # -- Features -----------------------------------------------------
    @staticmethod
    def _features(r: dict, slope: float) -> list[float]:
        minute = float(r["minute"])
        ang = 2 * math.pi * minute / 1440.0
        temp = float(r["temp"])
        ist_tag = float(r["ist_tag"])
        klima = float(r["klima"])
        ent = float(r["ent"])

        def g(key, fallback):
            """Geraete-Detailspalte lesen; Altbestand -> Naeherung."""
            try:
                return float(r.get(key, ""))
            except (TypeError, ValueError):
                return fallback

        # AC-Leistung sieht die Kompressorphasen (an/aus-Altdaten: ~300 W)
        kwatt = g("kwatt", 300.0 * klima)
        return [
            1.0,
            float(r["vpd"]),
            temp / 10.0,
            float(r["hum"]) / 10.0,
            float(r["co2"] or 0) / 1000.0,
            float(r["blatt"] or r["temp"]) / 10.0,
            ist_tag,
            math.sin(ang), math.cos(ang),
            float(r["bef"]), ent, klima,
            kwatt / 1000.0,
            g("k_ist", temp) / 10.0,
            g("k_aussen", temp) / 10.0,
            g("k_fan", 0.0) / 100.0,
            g("ent_stufe", ent),
            g("ent_hum", float(r["hum"])) / 10.0,
            g("licht", ist_tag),                    # Abwaerme Hauptlicht
            g("uc_pct", 100.0 * ist_tag) / 100.0,   # Abwaerme Undercanopy
            g("uv", 0.0),                           # Abwaerme UV
            slope * 10.0,
        ]

    # -- Training -----------------------------------------------------
    def _load_rows(self) -> list[dict]:
        rows: list[dict] = []
        for ym in self._months()[-2:]:  # aktueller + letzter Monat
            try:
                with open(self._path(ym), newline="") as f:
                    rows.extend(csv.DictReader(f))
            except OSError:
                continue
        return rows[-MAX_ROWS:]

    def train(self) -> None:
        try:
            self._train()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("KI-Training")
            self.trained_at = time.time()  # nicht sofort erneut versuchen

    def _train(self) -> None:
        with self._lock:
            rest = list(self._buf)
        rows = self._load_rows() + rest
        # Korrupte Zeilen (z.B. abgebrochene Schreibvorgaenge) vorab
        # aussortieren - eine einzelne defekte Zeile darf das Training
        # nicht abbrechen (ts/vpd werden unten ungeschuetzt gelesen).
        sauber = []
        for r in rows:
            try:
                float(r["ts"])
                float(r["vpd"])
                sauber.append(r)
            except (TypeError, ValueError, KeyError):
                continue
        rows = sauber
        self.n_rows = len(rows)
        self.trained_at = time.time()
        if len(rows) < MIN_ROWS:
            return

        # VPD-Steigung (~5 min) als Feature vorberechnen
        prev_ts = None
        prev_vpd = None
        slopes: dict[int, float] = {}
        for i, r in enumerate(rows):
            try:
                ts = float(r["ts"])
                v = float(r["vpd"])
            except (TypeError, ValueError):
                continue
            if prev_ts is not None and 200 <= ts - prev_ts <= 400:
                slopes[i] = v - prev_vpd
            if i % 10 == 0:
                prev_ts, prev_vpd = ts, v

        # Je Horizont ein eigenes Ridge-Modell trainieren
        neue_modelle: dict[int, list[float]] = {}
        neue_mae: dict[int, float] = {}
        for hmin in HORIZONS_MIN:
            hsek = hmin * 60
            tol = max(150, int(hsek * 0.15))
            xs: list[list[float]] = []
            ys: list[float] = []
            j = 0
            for i, r in enumerate(rows):
                try:
                    ts = float(r["ts"])
                except (TypeError, ValueError):
                    continue
                ziel = ts + hsek
                while (j < len(rows) - 1
                       and float(rows[j]["ts"]) < ziel - tol):
                    j += 1
                if abs(float(rows[j]["ts"]) - ziel) > tol:
                    continue
                try:
                    xs.append(self._features(r, slopes.get(i, 0.0)))
                    ys.append(float(rows[j]["vpd"]))
                except (TypeError, ValueError):
                    continue
            if len(xs) < MIN_ROWS // 2:
                continue
            # Ehrliche Validierung: Modell auf den ersten 80 % fitten, MAE
            # auf den letzten 20 % messen (out-of-sample). Das finale Modell
            # nutzt danach ALLE Daten.
            cut = int(len(xs) * 0.8)
            w_val = self._ridge(xs[:cut], ys[:cut])
            if w_val is None:
                continue
            fehler = [abs(sum(wi * xi for wi, xi in zip(w_val, x)) - y)
                      for x, y in zip(xs[cut:], ys[cut:])]
            w = self._ridge(xs, ys)
            if w is None:
                continue
            neue_modelle[hmin] = w
            neue_mae[hmin] = (round(sum(fehler) / len(fehler), 3)
                              if fehler else 0.0)

        if not neue_modelle:
            return
        self.modelle = neue_modelle
        self.mae = neue_mae
        _LOGGER.info("KI [%s]: trainiert (%d Zeilen) | MAE: %s",
                     self.slug, self.n_rows,
                     ", ".join("%dmin=%.3f" % (h, m)
                               for h, m in sorted(neue_mae.items())))

    @staticmethod
    def _ridge(xs: list[list[float]],
               ys: list[float]) -> list[float] | None:
        # Ridge: (X'X + lI) w = X'y, Gauss-Elimination (n Features klein)
        n = len(xs[0])
        xtx = [[RIDGE if a == b else 0.0 for b in range(n)] for a in range(n)]
        xty = [0.0] * n
        for x, y in zip(xs, ys):
            for a in range(n):
                xa = x[a]
                if xa == 0.0:
                    continue
                row_a = xtx[a]
                for b in range(a, n):
                    row_a[b] += xa * x[b]
                xty[a] += xa * y
        for a in range(n):
            for b in range(a):
                xtx[a][b] = xtx[b][a]
        return KiEngine._solve(xtx, xty)

    @staticmethod
    def _solve(m: list[list[float]], v: list[float]) -> list[float] | None:
        n = len(v)
        a = [row[:] + [v[i]] for i, row in enumerate(m)]
        for col in range(n):
            piv = max(range(col, n), key=lambda r: abs(a[r][col]))
            if abs(a[piv][col]) < 1e-12:
                return None
            a[col], a[piv] = a[piv], a[col]
            div = a[col][col]
            a[col] = [x / div for x in a[col]]
            for r in range(n):
                if r != col and a[r][col] != 0.0:
                    f = a[r][col]
                    a[r] = [x - f * y for x, y in zip(a[r], a[col])]
        return [a[i][n] for i in range(n)]

    # -- Prognose (nicht blockierend) ----------------------------------
    def predict_curve(self, row: dict,
                      slope: float) -> list[tuple[int, float]]:
        """Prognose-Kurve: [(Minuten, VPD), ...] sortiert nach Horizont."""
        if not self.modelle:
            return []
        try:
            x = self._features(row, slope)
        except (TypeError, ValueError):
            return []
        out: list[tuple[int, float]] = []
        for hmin in sorted(self.modelle):
            w = self.modelle[hmin]
            out.append(
                (hmin, round(sum(wi * xi for wi, xi in zip(w, x)), 3)))
        return out

    def predict(self, row: dict, slope: float) -> float | None:
        """Kuerzester Horizont (jetzt 5 min) - Abwaertskompatibilitaet."""
        kurve = self.predict_curve(row, slope)
        return kurve[0][1] if kurve else None
