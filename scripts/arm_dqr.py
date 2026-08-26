"""Harvest ARM's human-written fault reports for temperature, pressure and humidity.

    python -m scripts.arm_dqr

WHY THIS IS THE IMPORTANT ONE

Every review of this project said the same thing: there is no labelled corpus of
real AWS sensor faults, so recall can only ever be measured against faults we
injected ourselves, which is circular. That is true for India. It is not true
everywhere.

The US Department of Energy's ARM programme runs surface meteorology stations
recording temperature, pressure and relative humidity at ONE MINUTE resolution,
and it operates a Data Quality Report system in which a human being who went and
looked at the instrument writes down what was wrong, which variables it affected,
and exactly when it started and stopped. Those reports are graded Incorrect (do
not use) or Suspect.

    a DQR is a real fault, on real hardware, dated, with a stated cause.

VERIFIED, AND WORTH KNOWING: the DQR service needs NO ACCOUNT. The measurements
themselves require a free registration at adc.arm.gov, but the LABELS are open.
So the fault taxonomy, the cause vocabulary and the duration statistics can all
be studied before anyone signs up for anything.

    https://dqr-web-service.svcs.arm.gov/docs

WHAT THIS IS FOR, AND WHAT IT IS NOT

This gives a real answer to "what actually goes wrong with these three sensors,
how often, and for how long" -- which is exactly the question our injector had
to guess at. Comparing our injected fault durations and types against this is
the honest way to check whether the synthetic faults resemble real ones.

It is NOT an Indian dataset and it never will be. ARM sites are US, Alaskan and
tropical field sites with research-grade instruments, better maintained than a
national operational network. Fault RATES here are a lower bound on IMD's, not
an estimate of them. Say so before someone else does.
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://dqr-web-service.svcs.arm.gov"
UA = ("SkyGuard/1.0 (SIH 2026 PS26073 research; public ARM DQR endpoint; "
      "contact via repository)")

# ARM surface-meteorology datastreams. The `met` systems are the ones carrying
# temperature, pressure and humidity together, which is the combination this
# project is limited to and which almost no other network publishes at 1 min.
DATASTREAMS = [
    "sgpmetE13.b1",   # Southern Great Plains central facility -- longest record
    "sgpmetE31.b1", "sgpmetE32.b1", "sgpmetE33.b1", "sgpmetE37.b1",
    "sgpmetE39.b1", "sgpmetE41.b1",
    "nsametC1.b1",    # North Slope of Alaska -- cold-climate failure modes
    "enametC1.b1",    # Eastern North Atlantic -- marine, salt, high humidity
    "twpmetC3.b1",    # Tropical Western Pacific -- hot and wet, closest to India
]

# The variables this project is allowed to use, plus the housekeeping channels
# that are the reason ARM is interesting at all.
OURS = {"temp_mean", "temp_std", "atmos_pressure", "rh_mean", "rh_std",
        "dew_point_mean", "vapor_pressure_mean",
        "logger_volt", "logger_temp"}


def get(path: str, timeout: int = 90):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20150101")
    ap.add_argument("--end", default="20260101")
    ap.add_argument("--out", default="data/arm")
    ap.add_argument("--pause", type=float, default=0.5)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    rows, raw = [], {}
    for ds in DATASTREAMS:
        for cat in ("incorrect", "suspect"):
            try:
                d = get(f"/dqr_full/{ds}/{args.start}/{args.end}/{cat}")
            except Exception as exc:
                print(f"  {ds} {cat}: {exc}")
                continue
            time.sleep(args.pause)
            block = (d or {}).get(ds, {})
            if not isinstance(block, dict):
                continue
            raw.setdefault(ds, {}).update(block)
            for grade, reports in block.items():
                if not isinstance(reports, dict):
                    continue
                for dqr_id, r in reports.items():
                    vs = [v for v in (r.get("variables") or [])]
                    hit = sorted(set(vs) & OURS)
                    if not hit:
                        continue
                    for win in (r.get("dates") or []):
                        rows.append({
                            "datastream": ds, "dqr": dqr_id, "grade": grade,
                            "subject": r.get("subject", ""),
                            "variables": ";".join(hit),
                            "start": win.get("start_date"),
                            "end": win.get("end_date"),
                            "reviewed": r.get("prb_reviewed", ""),
                            "description": (r.get("description") or "")[:400],
                        })
        print(f"{ds:16s} cumulative windows on our variables: {len(rows)}")

    (outdir / "dqr_raw.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    if not rows:
        raise SystemExit("no DQRs matched our variables")

    import pandas as pd
    df = pd.DataFrame(rows)
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["hours"] = (df["end"] - df["start"]).dt.total_seconds() / 3600.0
    df = df.dropna(subset=["start", "end"])
    df.to_csv(outdir / "dqr_tprh.csv", index=False)

    print(f"\n{len(df)} labelled fault windows on temperature, pressure, "
          f"humidity or logger housekeeping\n")

    print("=== by grade ===")
    print(df.grade.value_counts().to_string())

    print("\n=== which of our variables is affected ===")
    c = Counter(v for s in df.variables for v in s.split(";"))
    for v, n in c.most_common():
        print(f"  {v:22s} {n:4d}")

    print("\n=== how long do REAL faults last? ===")
    print("Our injector had to guess this. Here it is measured, in hours.\n")
    print(df.hours.describe(percentiles=[.1, .25, .5, .75, .9]).round(1).to_string())

    print("\n=== what actually goes wrong (the real cause vocabulary) ===")
    for s, n in Counter(df.subject).most_common(18):
        print(f"  {n:3d}  {s[:88]}")

    print(f"\nwrote {outdir/'dqr_tprh.csv'} and {outdir/'dqr_raw.json'}")
    print("\nNote: ARM sites are research-grade and better maintained than a")
    print("national operational network, so these fault RATES are a lower bound")
    print("on IMD's, not an estimate of them.")


if __name__ == "__main__":
    main()
