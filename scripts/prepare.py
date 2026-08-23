"""Phase 0 — ingest audit and preparation.

Reads the raw ERA5 export, audits it, and writes a prepared dataset plus a
data-derived neighbour graph.

    python scripts/prepare.py --raw skyguard_master_era5.csv --out data/

What this deliberately does NOT do: impute missing values. There are none. If a
future export has gaps, they must be flagged as `dropout`, never filled — an
imputed value that looks like an observation is worse than a hole.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from physics.relations import dew_point, specific_humidity, reduce_to_msl  # noqa: E402
from residual.solartime import STATION_LONGITUDE  # noqa: E402

RAW_COLS = ["timestamp", "temp", "rh", "pres", "pres_msl", "dwpt",
            "station_name", "cluster", "elevation"]

# Physically possible ranges. Wider than climatology on purpose — this is a
# gross-error check, not a climatological one.
RANGES = {"temp": (-30.0, 55.0), "rh": (0.0, 100.0), "pres": (500.0, 1085.0)}

# Sentinel values by column. Note 999.0 is a VALID pressure, so it must not be
# treated as a sentinel for pressure columns.
SENTINELS = {"temp": [-999, -9999, 999, 9999],
             "rh": [-999, -9999, 999, 9999],
             "pres": [-999, -9999]}


def audit(df: pd.DataFrame) -> dict:
    rep: dict = {}
    rep["rows"] = len(df)
    rep["stations"] = int(df.station_name.nunique())
    rep["nan_cells"] = int(df.isna().sum().sum())

    rep["sentinels"] = {c: int(df[c].isin(v).sum()) for c, v in SENTINELS.items()}
    rep["out_of_range"] = {
        c: int(((df[c] < lo) | (df[c] > hi)).sum()) for c, (lo, hi) in RANGES.items()
    }

    # timestamp integrity, per station
    gaps, dups = 0, 0
    for _, g in df.groupby("station_name"):
        g = g.sort_values("timestamp")
        dups += int(g.timestamp.duplicated().sum())
        step = g.timestamp.diff().dropna().dt.total_seconds() / 3600.0
        gaps += int((step != 1).sum())
    rep["duplicate_timestamps"] = dups
    rep["non_hourly_steps"] = gaps

    # is dwpt an independent measurement, or derived from temp+rh?
    td_calc = np.array([dew_point(t, r) for t, r in zip(df.temp, df.rh)])
    rep["dwpt_max_abs_error_vs_magnus"] = float(np.abs(df.dwpt - td_calc).max())

    # is pres_msl independent, or derived from pres+elevation+temp?
    msl_calc = np.array([reduce_to_msl(p, e, t)
                         for p, e, t in zip(df.pres, df.elevation, df.temp)])
    rep["pres_msl_max_abs_error_vs_barometric"] = float(np.abs(df.pres_msl - msl_calc).max())

    # RH ceiling: the ONE hard physical check (Td > T is the same inequality)
    rep["rh_above_100"] = int((df.rh > 100.0).sum())
    rep["rh_at_exactly_100"] = int((df.rh == 100.0).sum())
    rep["dwpt_above_temp"] = int((df.dwpt > df.temp).sum())
    rep["dwpt_above_temp_by_gt_0.1C"] = int((df.dwpt - df.temp > 0.1).sum())
    return rep


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out.timestamp, utc=True)

    # local solar time — never IST, never UTC
    out["longitude"] = out.station_name.map(STATION_LONGITUDE)
    if out.longitude.isna().any():
        missing = sorted(out.loc[out.longitude.isna(), "station_name"].unique())
        raise ValueError(f"No longitude for stations: {missing}")
    hours = out.timestamp.dt.hour + out.timestamp.dt.minute / 60.0
    out["solar_hour"] = (hours + out.longitude / 15.0) % 24.0
    out["doy"] = out.timestamp.dt.dayofyear

    # the two variables the model should actually see
    out["td"] = [dew_point(t, r) for t, r in zip(out.temp, out.rh)]
    out["q"] = [specific_humidity(t, r, p) for t, r, p in zip(out.temp, out.rh, out.pres)]

    # drop derived columns that carry no independent information
    out = out.drop(columns=["dwpt", "pres_msl"])

    # quality flags — flag, never filter, and never impute
    out["flag_rh_over_100"] = out.rh > 100.0
    out["flag_rh_saturated"] = out.rh >= 99.9
    out["flag_out_of_range"] = False
    for c, (lo, hi) in RANGES.items():
        out["flag_out_of_range"] |= (out[c] < lo) | (out[c] > hi)

    return out.sort_values(["station_name", "timestamp"]).reset_index(drop=True)


def harmonic_residual(g: pd.DataFrame, col: str) -> np.ndarray:
    """2 diurnal + 2 annual harmonics. ~10 parameters, continuous, no 288 cells."""
    sh, doy = g.solar_hour.values, g.doy.values
    X = [np.ones(len(g))]
    for k in (1, 2):
        X += [np.sin(2 * np.pi * k * sh / 24), np.cos(2 * np.pi * k * sh / 24),
              np.sin(2 * np.pi * k * doy / 365.25), np.cos(2 * np.pi * k * doy / 365.25)]
    X = np.column_stack(X)
    beta, *_ = np.linalg.lstsq(X, g[col].values, rcond=None)
    return g[col].values - X @ beta


def neighbour_graph(df: pd.DataFrame, col: str = "temp", k: int = 2) -> dict:
    """Select neighbours by LOWEST sigma of the daily residual difference.

    Not by distance, and not by the `cluster` label — the data decides. A hill
    station and a coastal station 60 km apart are worse neighbours than two
    coastal stations 300 km apart.
    """
    res = {}
    for s, g in df.groupby("station_name"):
        g = g.sort_values("timestamp")
        res[s] = pd.Series(harmonic_residual(g, col), index=g.timestamp.values)
    daily = pd.DataFrame(res).resample("D").mean()

    graph = {}
    for a in daily.columns:
        sig = {b: float((daily[a] - daily[b]).std()) for b in daily.columns if b != a}
        best = sorted(sig.items(), key=lambda kv: kv[1])[:k]
        med = daily[[b for b, _ in best]].median(axis=1)
        combined = float((daily[a] - med).std())
        graph[a] = {
            "neighbours": [b for b, _ in best],
            "pair_sigma_K": {b: round(v, 4) for b, v in best},
            "combined_sigma_K": round(combined, 4),
            "own_sigma_K": round(float(daily[a].std()), 4),
            "gain": round(float(daily[a].std() / combined), 2),
            "drift_latency_days_at_0.02K_per_day": round(3 * combined / 0.02),
        }
    return graph


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="skyguard_master_era5.csv")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    raw = pd.read_csv(args.raw, parse_dates=["timestamp"])
    missing = set(RAW_COLS) - set(raw.columns)
    if missing:
        raise ValueError(f"Missing expected columns: {sorted(missing)}")

    rep = audit(raw)
    print(json.dumps(rep, indent=2))

    prepared = prepare(raw)
    graph = neighbour_graph(prepared)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(outdir / "skyguard_prepared.csv", index=False)
    (outdir / "audit_report.json").write_text(json.dumps(rep, indent=2))
    (outdir / "neighbours.json").write_text(json.dumps(graph, indent=2))

    print(f"\nwrote {outdir/'skyguard_prepared.csv'}  ({len(prepared):,} rows, "
          f"{len(prepared.columns)} cols)")
    print(f"wrote {outdir/'audit_report.json'}")
    print(f"wrote {outdir/'neighbours.json'}")


if __name__ == "__main__":
    main()
