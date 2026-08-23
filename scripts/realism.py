"""Degrade the ERA5 export into something that behaves like a real AWS network.

Why this exists
---------------
ERA5 is a reanalysis on a ~31 km grid. Neighbouring grid cells are smooth by
construction, so the neighbour-difference sigma measured on the raw export is an
optimistic LOWER BOUND and the noise-reduction gain is an UPPER BOUND. Tuning
thresholds on it would produce a detector that looks excellent in the report and
misses drift in the field.

Two real stations 50 km apart differ for reasons ERA5 cannot represent:

  representativeness  siting, land cover, a car park, a tree line, a valley
                      inversion the grid cell averages away. Time-varying and
                      autocorrelated over hours to days -- NOT white noise, and
                      NOT removable by a harmonic baseline.
  instrument          per-probe scatter within spec. Near-white, so it largely
                      averages out of a daily mean.
  quantisation        the logger reports 0.1 C, not 0.01 C. This is what forces
                      the MAD floor.

This script injects all three. It is a SIMULATION OF A NUISANCE, not a fault
injector -- no anomalies are added here; `inject/` does that separately.

THE PARAMETERS BELOW ARE ASSUMPTIONS, NOT MEASUREMENTS. They are stated in the
output so no downstream number can quietly inherit them as fact. Replace them
the moment real paired AWS data is available: the quantity to measure is the
sigma of the daily-mean difference between two nearby real stations, after
harmonic baseline removal. That single number replaces `daily_sigma`.

    python scripts/realism.py --raw skyguard_master_era5.csv --out data/
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.prepare import prepare, neighbour_graph  # noqa: E402

# --- ASSUMED, NOT MEASURED -------------------------------------------------
# daily_sigma  : sd of the station-local representativeness field on DAILY means
# efold_hours  : e-folding time of that field (sets how much survives averaging)
# instrument   : sd of near-white per-reading instrument scatter
# resolution   : reported resolution of the logger
REALISM = {
    "temp": {"daily_sigma": 0.45, "efold_hours": 12.0, "instrument": 0.10, "resolution": 0.1},
    "rh":   {"daily_sigma": 2.50, "efold_hours": 12.0, "instrument": 0.80, "resolution": 0.1},
    # pressure really is spatially smooth; the honest local term is small
    "pres": {"daily_sigma": 0.15, "efold_hours": 24.0, "instrument": 0.05, "resolution": 0.1},
}

CLIP = {"temp": (-30.0, 55.0), "rh": (0.0, 100.0), "pres": (500.0, 1085.0)}


def _ar1(n: int, efold_hours: float, rng: np.random.Generator) -> np.ndarray:
    """Unit-variance AR(1) at hourly step with the given e-folding time."""
    phi = float(np.exp(-1.0 / efold_hours))
    innov = rng.normal(0.0, np.sqrt(1.0 - phi * phi), n)
    x = np.empty(n)
    x[0] = rng.normal()
    for i in range(1, n):
        x[i] = phi * x[i - 1] + innov[i]
    return x


def _local_field(n: int, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    """AR(1) field rescaled so its DAILY-MEAN sd equals cfg['daily_sigma'].

    Rescaling on the daily mean rather than the hourly value is deliberate: the
    daily mean is the scale the drift detector works at, so that is the scale
    the assumption should be pinned to. Hourly sd comes out larger, which is
    correct -- hourly differences between real stations are noisier still.
    """
    x = _ar1(n, cfg["efold_hours"], rng)
    usable = (n // 24) * 24
    daily_sd = x[:usable].reshape(-1, 24).mean(axis=1).std()
    return x * (cfg["daily_sigma"] / max(daily_sd, 1e-9))


def add_realism(df: pd.DataFrame, seed: int = 20260823) -> pd.DataFrame:
    out = df.copy()
    for i, (station, g) in enumerate(out.groupby("station_name", sort=True)):
        idx = g.sort_values("timestamp").index
        # one stream per station, so a station's nuisance is reproducible alone
        rng = np.random.default_rng(seed + i * 7919)
        for col, cfg in REALISM.items():
            n = len(idx)
            v = (out.loc[idx, col].to_numpy()
                 + _local_field(n, cfg, rng)
                 + rng.normal(0.0, cfg["instrument"], n))
            lo, hi = CLIP[col]
            v = np.clip(v, lo, hi)
            # quantise last: this is what puts the MAD on a floor
            r = cfg["resolution"]
            out.loc[idx, col] = np.round(v / r) * r

    # dwpt and pres_msl were derived from the CLEAN values and are now
    # inconsistent with the degraded primaries. Drop them rather than leave a
    # contradiction in the file; prepare() recomputes td and q from primaries.
    return out.drop(columns=[c for c in ("dwpt", "pres_msl") if c in out.columns])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="skyguard_master_era5.csv")
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=20260823)
    args = ap.parse_args()

    raw = pd.read_csv(args.raw, parse_dates=["timestamp"])
    clean_graph = neighbour_graph(prepare(raw))

    degraded = add_realism(raw, seed=args.seed)
    # prepare() expects the two derived columns present so it can drop them;
    # they were removed by add_realism, so pass throwaway placeholders.
    prepared = prepare(degraded.assign(dwpt=0.0, pres_msl=0.0))
    dirty_graph = neighbour_graph(prepared)

    rows = []
    for s in sorted(dirty_graph):
        c, d = clean_graph[s], dirty_graph[s]
        rows.append({
            "station": s,
            "era5_sigma_K": c["combined_sigma_K"], "era5_gain": c["gain"],
            "realistic_sigma_K": d["combined_sigma_K"], "realistic_gain": d["gain"],
            "era5_latency_d": c["drift_latency_days_at_0.02K_per_day"],
            "realistic_latency_d": d["drift_latency_days_at_0.02K_per_day"],
        })
    comp = pd.DataFrame(rows).sort_values("realistic_sigma_K")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(outdir / "skyguard_realistic.csv", index=False)
    (outdir / "neighbours_realistic.json").write_text(json.dumps(dirty_graph, indent=2))
    (outdir / "realism_comparison.json").write_text(json.dumps({
        "assumptions": REALISM,
        "warning": "REALISM parameters are assumptions, not measurements. "
                   "Replace with the measured daily-mean difference sigma of two "
                   "nearby real AWS stations before any threshold is fixed.",
        "seed": args.seed,
        "per_station": rows,
    }, indent=2))

    print(comp.to_string(index=False))
    print(f"\nERA5       gain {comp.era5_gain.min():.2f}-{comp.era5_gain.max():.2f}"
          f"  (upper bound, reanalysis is smooth by construction)")
    print(f"realistic  gain {comp.realistic_gain.min():.2f}-{comp.realistic_gain.max():.2f}"
          f"  (under the stated assumptions)")
    print(f"\nwrote {outdir/'skyguard_realistic.csv'}")
    print(f"wrote {outdir/'neighbours_realistic.json'}")
    print(f"wrote {outdir/'realism_comparison.json'}")


if __name__ == "__main__":
    main()
