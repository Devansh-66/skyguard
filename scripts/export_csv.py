"""The simulated network as a CSV, with its ground truth attached.

    python -m scripts.export_csv               # everything, gzipped
    python -m scripts.export_csv --hourly      # every 4th row
    python -m scripts.export_csv --plain       # uncompressed

WHAT THIS IS

344 real IMD station locations, 30 days at 15-minute cadence, with faults
injected into 28 of them. The geography is real -- the names, coordinates and
elevations come from WMO's WDQMS listing of stations India operates. The
readings are generated.

WHY THE TRUTH COLUMNS ARE HERE, AND WHY THAT IS SAFE

`fault_kind`, `fault_channel` and `fault_onset_step` say what was done to each
station. The grader never sees them: `grade` is computed by neighbour
differencing in simulate/faults_and_export.py, which is handed the readings and
nothing else. Shipping truth beside a verdict is what lets anyone check the
verdict instead of taking it on trust -- and it is the only reason the recall
and precision figures in this repository can be audited.

`in_fault_window` is derived, not injected: it is true where a row lies at or
after that station's onset on the affected channel. It is the label to score
against, and it is deliberately a separate column from `grade` so the two can
never be confused.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sim" / "network_faulted.npz"
# elevation lives only in the pre-injection file; the station order is the
# same in both, which is what makes this join safe.
CLEAN = ROOT / "data" / "sim" / "network_15min.npz"
SIM_MAP = ROOT / "dashboard" / "sim_map.json"
OUT_DIR = ROOT / "data"

GRADE_NAME = {"0": "ok", "1": "watch", "2": "fault", "-": "ungraded"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", action="store_true",
                    help="every 4th step instead of all 15-minute steps")
    ap.add_argument("--plain", action="store_true", help="do not gzip")
    args = ap.parse_args()

    if not SRC.exists():
        sys.exit(f"missing {SRC}; run `python -m simulate.faults_and_export`")
    if not SIM_MAP.exists():
        sys.exit(f"missing {SIM_MAP}; run `python -m simulate.faults_and_export`")

    d = np.load(SRC, allow_pickle=True)
    sim = json.loads(SIM_MAP.read_text(encoding="utf-8"))
    elev = (np.load(CLEAN, allow_pickle=True)["elev"] if CLEAN.exists()
            else np.full(d["temp"].shape[1], np.nan))

    temp, rh, pres = d["temp"], d["rh"], d["pres"]
    lat, lon = d["lat"], d["lon"]

    # THE INJECTED TRUTH, from the injector itself rather than the map export.
    # It carries the amplitude too, which the map does not, and it is indexed by
    # station POSITION -- the same order as every array in this file.
    events = {e["station"]: e
              for e in json.loads(str(d["events"].item()))}
    names = [str(x) for x in d["names"]]
    ids = [str(x) for x in d["ids"]]
    states = [str(x) for x in d["states"]]
    step_min = int(d["step_min"])
    t0 = np.datetime64(str(d["t0"]))
    n_steps, n_st = temp.shape

    # Grades and injected truth, keyed by station id. The grade string is one
    # character per step and comes from the export the dashboard reads, so the
    # CSV and the map cannot disagree about what was flagged.
    by_id = {s["id"]: s for s in sim["stations"]}

    every = 4 if args.hourly else 1
    stem = "skyguard_simulated_network" + ("_hourly" if args.hourly else "")
    out = OUT_DIR / (stem + ".csv" + ("" if args.plain else ".gz"))
    opener = (lambda p: open(p, "w", newline="", encoding="utf-8")) if args.plain \
        else (lambda p: gzip.open(p, "wt", newline="", encoding="utf-8"))

    cols = ["station_id", "station", "state", "lat", "lon", "elev_m",
            "timestamp_utc", "step", "temp_c", "rh_pct", "pres_hpa",
            "grade", "grade_temp", "grade_rh", "grade_pres",
            "fault_kind", "fault_channel", "fault_onset_step",
            "fault_amplitude", "in_fault_window"]

    written = 0
    with opener(out) as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for j in range(n_st):
            sid = ids[j]
            meta = by_id.get(sid, {})
            g = meta.get("g", "")
            gt, gh, gp = meta.get("gt", ""), meta.get("gh", ""), meta.get("gp", "")
            ev = events.get(j, {})
            kind = ev.get("kind", "")
            fch = ev.get("channel", "")
            amp = ev.get("amplitude", "")
            onset_step = ev.get("onset")           # already in 15-minute steps

            for i in range(0, n_steps, every):
                t = t0 + np.timedelta64(i * step_min, "m")
                inwin = kind != "" and onset_step is not None and i >= onset_step
                w.writerow([
                    sid, names[j], states[j],
                    f"{lat[j]:.4f}", f"{lon[j]:.4f}", f"{elev[j]:.0f}",
                    str(t) + "Z", i,
                    "" if not np.isfinite(temp[i, j]) else f"{temp[i, j]:.2f}",
                    "" if not np.isfinite(rh[i, j]) else f"{rh[i, j]:.2f}",
                    "" if not np.isfinite(pres[i, j]) else f"{pres[i, j]:.2f}",
                    GRADE_NAME.get(g[i:i + 1], ""),
                    GRADE_NAME.get(gt[i:i + 1], ""),
                    GRADE_NAME.get(gh[i:i + 1], ""),
                    GRADE_NAME.get(gp[i:i + 1], ""),
                    kind, fch, "" if onset_step is None else onset_step,
                    amp, int(inwin),
                ])
                written += 1

    mb = out.stat().st_size / 1024 / 1024
    print(f"wrote {out.relative_to(ROOT)}  {mb:.1f} MB  {written:,} rows")
    print(f"  {n_st} stations x {n_steps // every:,} steps at "
          f"{step_min * every} minutes")
    faulty = len(events)
    print(f"  {faulty} stations carry an injected fault; the rest are clean")
    print("  grade is this project's own verdict; fault_* columns are the truth "
          "the grader never saw")


if __name__ == "__main__":
    main()
