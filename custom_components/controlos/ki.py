"""ControlOS - Datenlogger + echte KI (VPD-Prognose).

Je Bereich werden Klima-Zeilen in Monats-CSVs gesammelt
(/config/controlos_data/<slug>-YYYY-MM.csv, Speicherzeit je Bereich
einstellbar). Auf diesen Daten trainiert stuendlich eine Ridge-Regression
(pure Python, keine Abhaengigkeiten) die VPD-Prognose 15 Minuten voraus.

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
          "bef", "ent", "klima", "minute"]
HORIZON_S = 900          # Prognose-Horizont: 15 min
PAIR_TOL_S = 150         # Toleranz beim Paaren von Trainingszeilen
MIN_ROWS = 2000          # ab hier wird trainiert (~17 h Daten)
MAX_ROWS = 60000         # Trainings-Cap (~3 Wochen bei 30s-Takt)
RIDGE = 1.0              # L2-Regularisierung
FLUSH_EVERY = 10         # Zeilen puffern, dann schreiben (SD-schonend)


class KiEngine:
    def __init__(self, base_dir: str, slug: str):
        self.dir = base_dir
        self.slug = slug
        self._buf: list[dict] = []
        self._lock = threading.Lock()
        self.weights: list[float] | None = None
        self.mae: float | None = None
        self.n_rows = 0
        self.trained_at = 0.0

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

    def _write(self, rows: list[dict]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        path = self._path(time.strftime("%Y-%m"))
        neu = not os.path.exists(path)
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
        return [
            1.0,
            float(r["vpd"]),
            float(r["temp"]) / 10.0,
            float(r["hum"]) / 10.0,
            float(r["co2"] or 0) / 1000.0,
            float(r["blatt"] or r["temp"]) / 10.0,
            float(r["ist_tag"]),
            math.sin(ang), math.cos(ang),
            float(r["bef"]), float(r["ent"]), float(r["klima"]),
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
        self.n_rows = len(rows)
        self.trained_at = time.time()
        if len(rows) < MIN_ROWS:
            return

        # Paare bilden: Zeile i -> VPD der Zeile ~15 min spaeter
        xs: list[list[float]] = []
        ys: list[float] = []
        j = 0
        prev_ts = None
        prev_vpd = None
        slopes: dict[int, float] = {}
        for i, r in enumerate(rows):
            ts = float(r["ts"])
            v = float(r["vpd"])
            if prev_ts is not None and 200 <= ts - prev_ts <= 400:
                slopes[i] = v - prev_vpd
            if i % 10 == 0:
                prev_ts, prev_vpd = ts, v
        for i, r in enumerate(rows):
            ts = float(r["ts"])
            ziel = ts + HORIZON_S
            while j < len(rows) - 1 and float(rows[j]["ts"]) < ziel - PAIR_TOL_S:
                j += 1
            if abs(float(rows[j]["ts"]) - ziel) > PAIR_TOL_S:
                continue
            try:
                xs.append(self._features(r, slopes.get(i, 0.0)))
                ys.append(float(rows[j]["vpd"]))
            except (TypeError, ValueError):
                continue
        if len(xs) < MIN_ROWS // 2:
            return

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
        w = self._solve(xtx, xty)
        if w is None:
            return

        # Guete: MAE ueber die letzten 20 % (grobe Validierung)
        cut = int(len(xs) * 0.8)
        fehler = [abs(sum(wi * xi for wi, xi in zip(w, x)) - y)
                  for x, y in zip(xs[cut:], ys[cut:])]
        self.mae = round(sum(fehler) / len(fehler), 3) if fehler else None
        self.weights = w
        _LOGGER.info("KI [%s]: trainiert (%d Paare, MAE %.3f kPa)",
                     self.slug, len(xs), self.mae or -1)

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
    def predict(self, row: dict, slope: float) -> float | None:
        if not self.weights:
            return None
        try:
            x = self._features(row, slope)
            return round(sum(w * xi for w, xi in zip(self.weights, x)), 3)
        except (TypeError, ValueError):
            return None
