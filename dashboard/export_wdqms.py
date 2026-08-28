"""Reduce the WMO WDQMS departures to one compact record per real Indian station.

    python -m dashboard.export_wdqms

WHAT THIS DATA IS, AND WHY IT IS WORTH PLOTTING

data/wdqms/IND_quality.csv is WMO's operational Data Quality Monitoring System
for stations operated by India: real IMD masts, real identities, and for each
one the average observation-minus-background departure that four independent
forecast centres -- ECMWF, DWD, JMA and NCEP -- computed against their own
short-range forecasts.

That is a genuine quality signal on genuine Indian instruments, which is exactly
what the simulated ten-station network was standing in for. It is not, however,
a replacement for ARM: these are DAILY AVERAGES with no per-instrument fault
report behind them, so they can say a station disagrees with the background but
never that an engineer went out and found a failed probe. The board stays on
ARM for that reason; the map does not need to.

WHY THE CENTRES ARE AVERAGED AND THE SPREAD IS KEPT

A single centre's departure carries that centre's own model error as well as the
station's. Four centres disagreeing about a station is a different situation
from four agreeing, so the mean is reported with the spread beside it and the
number of centres that contributed. A large mean on a large spread is a claim
about models; a large mean on a small spread is a claim about the instrument.

ANTARCTICA IS NOT A BUG

MAITRI and BHARATI are India's Antarctic research stations (WMO block 89,
operated by NCPOR under MoES). They are legitimately Indian stations that are
not in India, and they are flagged rather than dropped -- a map that silently
deletes two of a country's stations is worse than one that has to handle them.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path("data/wdqms/IND_quality.csv")
OUT = Path("dashboard/wdqms.json")

# The three channels this project is about, mapped to the short keys the
# console already uses for its colour selector.
VARS = {"temperature": "temp", "humidity": "rh", "pressure": "pres"}

# India's mainland bounding box. Outside it a station is not wrong, it is
# elsewhere -- see the note about Antarctica above.
BOX = dict(lat=(6.0, 37.5), lon=(67.5, 97.5))


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing {SRC}\nfetch it with: python -m scripts.wdqms")

    df = pd.read_csv(SRC)
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df = df.dropna(subset=["date", "latitude", "longitude", "avg_bg_dep"])

    # The most recent DAY, not the most recent timestamp. WDQMS reports at the
    # four synoptic hours (00/06/12/18 UTC) and not every station reports at
    # every one of them, so filtering to the single latest instant silently
    # dropped two thirds of the network: 125 stations where the day holds 346.
    df["day"] = df["date"].dt.date
    day = max(df["day"])
    latest = df[df["day"] == day]

    stations: list[dict] = []
    for wid, g in latest.groupby("wigosid"):
        first = g.iloc[0]
        lat, lon = float(first["latitude"]), float(first["longitude"])
        rec: dict = {
            "id": str(wid),
            "name": str(first["name"]).strip(),
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "in_india": (BOX["lat"][0] <= lat <= BOX["lat"][1]
                         and BOX["lon"][0] <= lon <= BOX["lon"][1]),
            "dep": {},
        }
        for long_name, key in VARS.items():
            v = g[g["variable"] == long_name]["avg_bg_dep"].astype(float)
            if v.empty:
                continue
            rec["dep"][key] = {
                "mean": round(float(v.mean()), 3),
                # Spread over every (synoptic hour, centre) pair on the day, so
                # it carries both the diurnal swing and the disagreement between
                # centres. A single observation has no spread, and that is
                # reported as null rather than as a confident 0.
                "spread": (None if len(v) < 2 else round(float(v.std(ddof=0)), 3)),
                "n": int(len(v)),
                "centres": int(g[g["variable"] == long_name]["center"].nunique()),
            }
        if rec["dep"]:
            stations.append(rec)

    stations.sort(key=lambda s: s["name"])
    out = {
        "source": "WMO WDQMS (NWP land surface), observation minus background",
        "centres": sorted(latest["center"].dropna().unique().tolist()),
        "date": str(day),
        "note": ("Daily average departures from four independent forecast "
                 "centres. Real stations operated by India. No per-instrument "
                 "fault reports exist for these, which is why the maintenance "
                 "board is validated on ARM instead."),
        "stations": stations,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

    outside = [s["name"] for s in stations if not s["in_india"]]
    print(f"{OUT}  {OUT.stat().st_size/1024:.0f} kB")
    print(f"  {len(stations)} stations  ·  {day}  ·  centres: {', '.join(out['centres'])}")
    print(f"  outside the Indian box: {len(outside)} ({', '.join(outside) or 'none'})")
    for key in ("temp", "rh", "pres"):
        have = [s for s in stations if key in s["dep"]]
        if have:
            vals = [s["dep"][key]["mean"] for s in have]
            print(f"  {key:5s} {len(have):4d} stations   mean departure "
                  f"{sum(vals)/len(vals):+.3f}   range {min(vals):+.2f} to {max(vals):+.2f}")


if __name__ == "__main__":
    main()
