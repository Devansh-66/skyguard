"""The T/P/RH conservation map, redone on REAL observations.

    python -m evaluation.run_physics_real

WHY THIS REPLACES run_physics_map.py

That script measured which thermodynamic quantities the atmosphere holds still,
and the answer -- dew point and specific humidity are conserved, relative
humidity is not -- drives the whole coordinate choice in this project. But it ran
on ERA5 degraded by OUR OWN noise assumptions, which makes the MAGNITUDES partly
a measurement of our own `REALISM` dictionary rather than of the atmosphere.
The relations are exact either way, since Magnus is Magnus, but a conservation
ratio computed from invented noise is not evidence.

This runs the same measurement on real 1-minute observations from DOE ARM
surface meteorology stations, which report temperature, pressure and relative
humidity together -- a combination almost no other open network publishes at
that cadence.

TWO FILTERS THAT MAKE IT HONEST

  qc == 0        ARM ships a per-variable quality flag with every field. Only
                 rows all three variables pass are used.
  not in a DQR   ARM's Data Quality Reports are human-written fault intervals.
                 Rows inside one are excluded, because the question here is what
                 the ATMOSPHERE does, and a faulted sensor would answer a
                 different question.

So this is real air, measured by real instruments, over intervals a human has
not flagged as broken.
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

EPS, RD, CP, LV = 0.622, 287.05, 1004.6, 2.501e6
KAPPA = RD / CP


def es_hpa(t_c):
    t_c = np.asarray(t_c, float)
    a = np.where(t_c >= 0, 17.368, 17.966)
    b = np.where(t_c >= 0, 238.88, 247.15)
    return 6.1121 * np.exp(a * t_c / (b + t_c))


def derive(t, p, rh):
    """Same derivation as the synthetic version, so the two are comparable."""
    e = np.clip(rh, 0.01, None) / 100.0 * es_hpa(t)
    a = np.where(t >= 0, 17.368, 17.966)
    b = np.where(t >= 0, 238.88, 247.15)
    g = np.log(np.clip(e / 6.1121, 1e-9, None))
    td = b * g / (a - g)
    q = EPS * e / (p - (1 - EPS) * e)
    tk = t + 273.15
    theta = tk * (1000.0 / p) ** KAPPA
    return {
        "T  temperature": t,
        "RH relative humidity": rh,
        "P  pressure": p,
        "Td dew point": td,
        "T-Td dew point depression": t - td,
        "e  vapour pressure": e,
        "q  specific humidity": q * 1000.0,
        "theta potential temp": theta,
        "theta_e equivalent pot temp": theta * np.exp(LV * q / (CP * tk)),
    }


def load(paths, dqr):
    """Read ARM files, keep only qc-clean rows outside any DQR interval."""
    import netCDF4
    frames = []
    for f in paths:
        try:
            d = netCDF4.Dataset(f)
        except Exception:
            continue
        try:
            need = ("temp_mean", "atmos_pressure", "rh_mean")
            if any(v not in d.variables for v in need):
                continue
            base = pd.Timestamp(re.search(r"\.(\d{8})\.", os.path.basename(f)).group(1))
            t = base + pd.to_timedelta(np.asarray(d.variables["time"][:]), unit="s")
            g = pd.DataFrame({
                "timestamp": t,
                "temp": np.asarray(d.variables["temp_mean"][:], float),
                # ARM reports pressure in kPa; everything here is hPa
                "pres": np.asarray(d.variables["atmos_pressure"][:], float) * 10.0,
                "rh": np.asarray(d.variables["rh_mean"][:], float),
            })
            ok = np.ones(len(g), bool)
            for v, qc in (("temp", "qc_temp_mean"), ("pres", "qc_atmos_pressure"),
                          ("rh", "qc_rh_mean")):
                if qc in d.variables:
                    ok &= np.asarray(d.variables[qc][:], int) == 0
            g = g[ok]
            g["station"] = os.path.basename(f).split(".")[0]
            frames.append(g)
        finally:
            d.close()
    if not frames:
        raise SystemExit("no readable ARM files")
    df = pd.concat(frames, ignore_index=True)

    # drop anything a human flagged as faulty
    before = len(df)
    for _, r in dqr.iterrows():
        m = ((df.timestamp >= r["start"]) & (df.timestamp <= r["end"])
             & (df.station == str(r["datastream"]).split(".")[0]))
        df = df[~m]
    df = df[(df.temp > -60) & (df.temp < 60) & (df.rh > 0) & (df.rh <= 105)
            & (df.pres > 500) & (df.pres < 1100)]
    print(f"{before:,} qc-clean rows, {before-len(df):,} removed as DQR-flagged "
          f"or out of range -> {len(df):,} used")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/arm/raw")
    ap.add_argument("--dqr", default="data/arm/dqr_tprh.csv")
    ap.add_argument("--max-files", type=int, default=400)
    args = ap.parse_args()

    dqr = pd.read_csv(args.dqr, parse_dates=["start", "end"])
    paths = sorted(glob.glob(os.path.join(args.root, "**", "*.cdf"), recursive=True))
    paths = paths[:args.max_files]
    print(f"reading {len(paths)} ARM files ...")
    df = load(paths, dqr)
    print(f"stations: {sorted(df.station.unique())}\n")

    d = derive(df.temp.to_numpy(), df.pres.to_numpy(), df.rh.to_numpy())
    frame = pd.DataFrame(d)
    frame["station"] = df.station.values
    frame["day"] = df.timestamp.dt.floor("D").values

    print("=== Which quantities does the atmosphere hold still? ===")
    print("REAL 1-minute observations. Diurnal range within a day against the")
    print("spread of daily means between days. Small ratio = conserved.\n")
    rows = []
    for name in d:
        g = frame.groupby(["station", "day"])[name]
        within = g.apply(lambda s: s.max() - s.min()).median()
        between = g.mean().groupby(level=0).std().median()
        rows.append({"quantity": name,
                     "diurnal range": round(float(within), 3),
                     "synoptic sd": round(float(between), 3),
                     "ratio": round(float(within / between), 2) if between else np.nan})
    t1 = pd.DataFrame(rows).sort_values("ratio")
    print(t1.to_string(index=False))

    rh = float(t1.loc[t1.quantity.str.startswith("RH"), "ratio"].iloc[0])
    td = float(t1.loc[t1.quantity.str.startswith("Td"), "ratio"].iloc[0])
    print(f"\nRH ratio {rh:.2f} against dew point {td:.2f} -- working in dew "
          f"point is {rh/td:.1f}x quieter, measured on real air.")
    print("\nThe synthetic run gave RH 3.26 and Td 0.87 (3.7x). If these differ")
    print("materially, the synthetic figure was reporting our own noise model")
    print("and the number to quote is this one.")


if __name__ == "__main__":
    main()
