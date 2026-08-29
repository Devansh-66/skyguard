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

# What counts as a large departure, per channel, in the channel's own units.
# These are the rough observation-error scales NWP centres assume for surface
# synoptic reports: a degree and a half of screen temperature, ten percent
# relative humidity, one hectopascal of station pressure. A departure of one
# unit here is ordinary; five is not.
TOL = {"temp": 1.5, "rh": 10.0, "pres": 1.0}

# THREE states, not five.
#
# The previous version copied the simulated network's five-band scale, and on
# 346 dots that was false precision twice over: the underlying number is a
# threshold on a daily mean, which cannot support five grades of anything, and
# five similar hues a few pixels across are indistinguishable on a map -- every
# station genuinely did look the same. Three is what the data supports and what
# the eye can separate.
#
#   OK      inside twice the channel's observation error. No colour at all.
#   WATCH   two to five times. Worth a look.
#   FAULT   beyond five times. Almost certainly the instrument.
BANDS = [(2.0, "OK"), (5.0, "WATCH")]


def region(lat: float, lon: float, in_india: bool) -> str:
    """A coarse geographic band, computed from the coordinates.

    WDQMS PUBLISHES NO STATE FIELD. Its columns are name, WIGOS id, country,
    latitude, longitude, departure, variable, date and centre -- that is all.
    Assigning a real state would need a state-boundary polygon set, which is not
    vendored here, and guessing one from a nearest-city table would mislabel
    every border station while looking authoritative.

    So these are bands derived from latitude and longitude, and the interface
    calls them regions rather than states, because that is what they are.
    """
    if not in_india:
        return "Antarctic stations"
    if lat >= 28.0:
        return "North"
    if lon >= 88.0:
        return "North-East"
    if lat < 16.0:
        return "South"
    if lon < 76.0:
        return "West"
    if lon >= 82.0:
        return "East"
    return "Central"


# How far apart two stations can be and still be expected to see the same
# weather. 250 km is roughly the synoptic scale for surface temperature and
# pressure anomalies: closer than this, a real airmass feature moves both.
NEAR_KM = 250.0


def _km(a: dict, b: dict) -> float:
    """Great-circle distance, in kilometres."""
    import math
    p1, p2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dp = p2 - p1
    dl = math.radians(b["longitude"] - a["longitude"])
    h = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def add_isolation(stations: list[dict]) -> None:
    """Is a flagged station alone in being flagged, or is its whole area?

    THIS IS THE QUESTION THE MAP EXISTS TO ANSWER, and it is the project's own
    argument applied spatially. A departure at one mast while every neighbour
    sits quiet is evidence about that instrument. The same departure at twelve
    masts across one region is evidence about the forecast background over that
    region -- a front the model placed badly, a monsoon surge it ran early --
    and sending a technician to twelve stations for it would be twelve wasted
    journeys.

    Nothing here is inferred beyond what the geometry gives: the count of
    stations within NEAR_KM and how many of those are also flagged. The
    interpretation is offered to a person, not acted on.
    """
    for a in stations:
        near = [b for b in stations
                if b is not a and b["in_india"] == a["in_india"]
                and _km(a, b) <= NEAR_KM]
        flagged = [b for b in near if b["health"]["state"] != "OK"]
        a["near"] = {
            "n": len(near),
            "flagged": len(flagged),
            # Only meaningful with enough neighbours to be a neighbourhood at
            # all. Two stations agreeing is a coincidence, not a pattern.
            "share": (round(len(flagged) / len(near), 2) if len(near) >= 3
                      else None),
        }
        share = a["near"]["share"]
        if a["health"]["state"] == "OK" or share is None:
            a["near"]["verdict"] = None
        elif share <= 0.34:
            a["near"]["verdict"] = "isolated"
        elif share >= 0.6:
            a["near"]["verdict"] = "widespread"
        else:
            a["near"]["verdict"] = "mixed"


def classify(dep: dict) -> dict:
    """Grade a station from its departures.

    WHAT THIS IS, AND WHAT IT IS NOT

    This is a SCREEN, not the belief engine. It thresholds a daily-mean
    departure and nothing more: no baseline is fitted, no drift is estimated,
    no neighbour is consulted, and no checker panel adjudicates. A station can
    show a large departure because its instrument has failed or because the
    forecast background is poor over it -- a mast in complex terrain or at
    altitude will disagree with a model that cannot resolve its valley, and
    that is a statement about the model.

    The spread across centres is the one thing that separates those cases here.
    Four independent centres agreeing that a station is two degrees warm is
    evidence about the station; four disagreeing wildly is evidence about the
    models. So the spread is carried through to the UI rather than averaged
    away, and `confident` marks the stations where it is small relative to the
    departure itself.
    """
    worst_z, worst_k = 0.0, None
    for k, d in dep.items():
        # Per-channel severity is stored so the map can size a dot by the
        # channel it is CURRENTLY colouring. Sizing by the worst channel while
        # colouring by the selected one drew a station large for bad pressure
        # and neutral for fine temperature, in the same dot.
        d["z"] = round(abs(d["mean"]) / TOL[k], 2)
        if d["z"] > worst_z:
            worst_z, worst_k = d["z"], k
    state = "FAULT"
    for limit, name in BANDS:
        if worst_z < limit:
            state = name
            break
    spread = dep[worst_k]["spread"] if worst_k else None
    return {
        "state": state,
        "severity": round(worst_z, 2),
        "channel": worst_k,
        # Do the centres agree? Only meaningful once there is something to
        # agree about, so a healthy station is never marked "confident".
        "confident": (worst_z >= 2.0 and spread is not None
                      and spread < abs(dep[worst_k]["mean"]) * 0.5),
    }


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
        in_india = (BOX["lat"][0] <= lat <= BOX["lat"][1]
                    and BOX["lon"][0] <= lon <= BOX["lon"][1])
        rec: dict = {
            "id": str(wid),
            "name": str(first["name"]).strip(),
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "in_india": in_india,
            "region": region(lat, lon, in_india),
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
            rec["health"] = classify(rec["dep"])
            stations.append(rec)

    add_isolation(stations)

    # Worst first. The list is read from the top by someone deciding where to
    # send a technician, so the ordering is the product, not a detail.
    stations.sort(key=lambda s: -s["health"]["severity"])
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
    counts = {}
    for st in stations:
        counts[st["health"]["state"]] = counts.get(st["health"]["state"], 0) + 1
    print("  screened: " + "  ".join(
        f"{k} {counts.get(k, 0)}" for k in ("OK", "WATCH", "FAULT")))
    reg = {}
    for st in stations:
        r = reg.setdefault(st["region"], [0, 0])
        r[0] += 1
        if st["health"]["state"] != "OK":
            r[1] += 1
    print("  by region: " + "  ".join(
        f"{k} {v[0]}({v[1]} flagged)" for k, v in sorted(reg.items())))
    v = {}
    for st in stations:
        vd = st["near"].get("verdict")
        if vd:
            v[vd] = v.get(vd, 0) + 1
    print("  of the flagged, spatially: " + "  ".join(
        f"{k} {v.get(k, 0)}" for k in ("isolated", "mixed", "widespread"))
        + "   (isolated = neighbours quiet, so likely the instrument)")
    conf = sum(1 for st in stations if st["health"]["confident"])
    print(f"  of the flagged, {conf} have the four centres in agreement")
    for key in ("temp", "rh", "pres"):
        have = [s for s in stations if key in s["dep"]]
        if have:
            vals = [s["dep"][key]["mean"] for s in have]
            print(f"  {key:5s} {len(have):4d} stations   mean departure "
                  f"{sum(vals)/len(vals):+.3f}   range {min(vals):+.2f} to {max(vals):+.2f}")


if __name__ == "__main__":
    main()
