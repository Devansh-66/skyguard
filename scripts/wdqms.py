"""Pull WMO's own station-quality monitoring for India.

    python -m scripts.wdqms --days 14

WHAT THIS IS

WDQMS is the WMO Data Quality Monitoring System (wdqms.wmo.int). Four NWP
centres -- DWD, ECMWF, JMA and NCEP -- compare every station's reported value
against their own model background and publish the average departure, O minus B,
per station per six-hour cycle. It covers exactly the three variables PS26073
gives us: surface pressure, 2m temperature and 2m relative humidity.

It is public, unauthenticated, and has a REST endpoint. It is the closest thing
to published ground truth about Indian station quality that exists.

WHY IT MATTERS TO THIS PROJECT, IN BOTH DIRECTIONS

As a THREAT: a judge can reasonably ask why IMD needs us when WMO already
monitors station quality and four centres already publish suspect departures.
Not having an answer to that would be fatal. The answer is measured, not
asserted, and this script is what measures it -- see below.

As an OPPORTUNITY: every review of this project has said there is no labelled
Indian AWS fault corpus. There is a partial one, it is public, and this fetches
it. A station that four independent NWP centres agree is departing from
background is about as close to a labelled fault as this domain offers.

THE GAP THAT IS THE PITCH

WDQMS monitors on the order of 125 Indian stations, at six-hourly synoptic
cadence, and only those reporting on the GTS. IMD operates 1,000+ AWS reporting
every 15 minutes. So the great majority of the AWS network is not covered by
this at all, and nothing here runs at the station. That is the space this
project occupies, and the numbers this script prints are the evidence for it.

THE CAVEAT THAT MUST TRAVEL WITH ANY USE OF O-B

The background has already assimilated the station it is being compared against.
That is the same self-masking NCMRWF documents in its own QC (NMRF/TR/02/2022):
a slowly drifting station partly drags the background with it, so O-B
understates slow drift. O-B is excellent for spotting a gross or sudden
departure and progressively blinder the slower the fault. Our neighbour
difference has the opposite bias -- noisier, but not self-masked -- which is why
the two are complementary rather than competing.
"""
from __future__ import annotations
import argparse
import io
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

API = ("https://wdqms.wmo.int/wdqmsapi/v1/download/nwp/synop/six_hour/"
       "{cat}/?date={d}&period={p}&variable={v}&centers=COMBINED&baseline=OSCAR")

VARIABLES = ("temperature", "pressure", "humidity")
PERIODS = ("00", "06", "12", "18")
UA = "SkyGuard/1.0 (SIH 2026 PS26073 prototype; public WDQMS download endpoint)"


def fetch(cat: str, d: str, period: str, var: str) -> pd.DataFrame:
    url = API.format(cat=cat, d=d, p=period, v=var)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read().decode("utf-8", "replace")
    if not raw.lstrip().lower().startswith(("name,", "﻿name,")):
        raise RuntimeError(f"unexpected response for {var} {d} {period}")
    return pd.read_csv(io.StringIO(raw))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--country", default="IND")
    ap.add_argument("--out", default="data/wdqms")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="seconds between requests -- this is somebody else's "
                         "public service, so it is not hammered")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # Two days back: the most recent cycles are still filling as centres report.
    end = date.today() - timedelta(days=2)
    frames = []
    for n in range(args.days):
        d = (end - timedelta(days=n)).isoformat()
        for var in VARIABLES:
            for p in PERIODS:
                try:
                    df = fetch("quality", d, p, var)
                except Exception as exc:
                    print(f"  skip {var} {d} {p}: {exc}")
                    continue
                frames.append(df[df["country code"] == args.country])
                time.sleep(args.pause)
        print(f"{d} done")

    if not frames:
        raise SystemExit("nothing fetched")
    q = pd.concat(frames, ignore_index=True)
    q.to_csv(outdir / f"{args.country}_quality.csv", index=False)

    print(f"\n{len(q):,} rows, {q.wigosid.nunique()} {args.country} stations, "
          f"{q.center.nunique()} monitoring centres\n")

    print("=== Typical departure from the NWP background, by variable ===")
    print("This is the scale at which the professionals disagree with a")
    print("station. Any claim we make about detectable fault size has to be")
    print("read against it.\n")
    t = (q.assign(a=q.avg_bg_dep.abs())
           .groupby("variable")["a"]
           .agg(stations="size", median="median", p90=lambda s: s.quantile(0.90),
                worst="max").round(3))
    print(t.to_string())

    print("\n=== Stations the centres most disagree with ===")
    print("Ranked by median |O-B| across all cycles and centres. A station that")
    print("several independent centres put near the top is the nearest thing to")
    print("a labelled fault available for India.\n")
    for var in VARIABLES:
        s = q[q.variable == var]
        if s.empty:
            continue
        g = (s.assign(a=s.avg_bg_dep.abs())
               .groupby(["name", "wigosid"])
               .agg(med=("a", "median"), n=("a", "size"),
                    centres=("center", "nunique"))
               .query("n >= 4 and centres >= 2")
               .sort_values("med", ascending=False).head(5))
        print(f"{var}:")
        print(g.round(3).to_string())
        print()

    print("=== The coverage gap ===")
    n = q.wigosid.nunique()
    print(f"WDQMS is monitoring {n} Indian stations here, six-hourly, and only")
    print("those reporting on the GTS. IMD operates 1,000+ AWS reporting every")
    print("15 minutes, and runs no station-level QC at all (Ranalkar et al.,")
    print("MAUSAM 66(1), 2015 records Level-0 as not implemented). The")
    print("uncovered majority of the network is the space this project is for.")


if __name__ == "__main__":
    main()
