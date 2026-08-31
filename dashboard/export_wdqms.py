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


STATES_FILE = Path("dashboard/vendor/india_states.min.json")


def _load_states():
    """State polygons with a bounding box each, or None if not vendored.

    WDQMS publishes no state field -- its columns are name, WIGOS id, country,
    latitude, longitude, departure, variable, date and centre. The state comes
    from geometry instead, which is the only way to get it without inventing it.
    See dashboard/simplify_states.py for the source and its two known dating
    problems.
    """
    if not STATES_FILE.exists():
        return None
    d = json.loads(STATES_FILE.read_text(encoding="utf-8"))
    out = []
    for f in d.get("features", []):
        name = f["properties"]["st"]
        for poly in f["geometry"]["coordinates"]:
            ring = poly[0]
            holes = poly[1:]
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            out.append((name, min(xs), min(ys), max(xs), max(ys), ring, holes))
    return out


def _in_ring(x: float, y: float, ring) -> bool:
    """Ray casting. The ring is closed, so the last point repeats the first."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def state_of(lat: float, lon: float, polys) -> str | None:
    """Which state a point falls in. Bounding box first: 36 states become a
    handful of real tests per station."""
    if not polys:
        return None
    for name, x0, y0, x1, y1, ring, holes in polys:
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if _in_ring(lon, lat, ring) and not any(_in_ring(lon, lat, h) for h in holes):
            return name

    # NEAREST STATE, rather than a compass direction.
    #
    # Eighteen stations fell through this and were grouped as "South", "West",
    # "North-East" and "East" -- WDQMS regions, not states, listed beside real
    # ones as though they were peers. Every one is coastal or an island: the
    # outlines are simplified to a 2 km tolerance, which walks the coast
    # inland, so a mast on a headland sits a few hundred metres outside the
    # state it is plainly in. KOZHIKODE is in Kerala whatever the polygon says.
    #
    # TWO TESTS, because one number could not cover both cases. A coastal
    # station is a few kilometres out and any small cap catches it. An island
    # can be far from everything -- the simplifier drops islets entirely, so
    # MINICOY is 211 km from what remains of Lakshadweep -- and a cap generous
    # enough for that would start pulling mainland stations across borders.
    #
    # But MINICOY is not ambiguous: Lakshadweep is 211 km away and the next
    # candidate, Kerala, is 385. So a point is assigned to the nearest outline
    # when it is either CLOSE in absolute terms, or UNAMBIGUOUSLY nearest --
    # several times closer than the runner-up. A station that is neither keeps
    # a compass fallback, which is the honest answer for a point that really
    # does not belong to any of them.
    # RANK BY STATE, not by polygon. `polys` holds one entry per ring, so a
    # state made of islands contributes dozens of them under the same name --
    # and the "runner-up" was another islet of Lakshadweep, a kilometre from
    # the first. The ratio came out at 1.0 and the test never fired for the two
    # stations it was written for.
    nearest_by_state: dict[str, float] = {}
    for name, x0, y0, x1, y1, ring, holes in polys:
        d2 = min((px - lon) ** 2 + (py - lat) ** 2 for px, py in ring)
        if d2 < nearest_by_state.get(name, float("inf")):
            nearest_by_state[name] = d2
    ranked = sorted((d2, name) for name, d2 in nearest_by_state.items())
    if not ranked:
        return None
    nearest_d2, nearest = ranked[0]
    if nearest_d2 <= NEAR_COAST_DEG ** 2:
        return nearest
    if len(ranked) > 1 and ranked[1][0] >= nearest_d2 * (UNAMBIGUOUS ** 2):
        return nearest
    return None


# How far outside an outline a station may sit and still simply be assigned to
# it: about 55 km, which covers the simplifier's tolerance and a headland.
NEAR_COAST_DEG = 0.5

# Or, if further, how many times closer the nearest outline must be than the
# next one for the answer to be beyond argument. Three is deliberately strict:
# MINICOY clears it at 211 km against 385, and no mainland station comes near
# clearing it against a neighbouring state.
UNAMBIGUOUS = 1.8


def region(lat: float, lon: float, in_india: bool) -> str:
    """Fallback grouping when the polygons are not vendored, or a station falls
    outside every one of them -- which happens on small islands the simplifier
    dropped and just off the coast, where a mast can sit a few hundred metres
    outside a 2 km-tolerance outline.
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

    # The whole record per station, not just the graded day. It is short -- the
    # file holds 12 synoptic times and a typical station reports at six of them
    # -- but it is the difference between a number and a behaviour. A pressure
    # departure of +15 hPa once could be a bad cycle; the same +15 at every one
    # of six observations is a barometer reading high, and only a series shows
    # that. The health grade still comes from the latest day alone.
    series_by: dict[str, dict] = {}
    for wid, g in df.groupby("wigosid"):
        piv = (g.pivot_table(index="date", columns="variable",
                             values="avg_bg_dep", aggfunc="mean")
                .sort_index())
        rec = {"t": [t.strftime("%Y-%m-%d %H:%MZ") for t in piv.index]}
        for long_name, key in VARS.items():
            if long_name in piv.columns:
                rec[key] = [None if pd.isna(v) else round(float(v), 2)
                            for v in piv[long_name]]
        series_by[str(wid)] = rec

    polys = _load_states()
    if polys is None:
        print("  NOTE: dashboard/vendor/india_states.min.json missing -- "
              "falling back to computed regions")

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
            # The real state where the geometry gives one; the computed band
            # only where it cannot. Both go in the same field so the console has
            # one thing to group by, and `state_source` records which it was so
            # a coarse label is never mistaken for an administrative one.
            "region": (state_of(lat, lon, polys) or region(lat, lon, in_india)),
            "state_source": ("polygon" if state_of(lat, lon, polys) else "computed"),
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
            rec["series"] = series_by.get(str(wid), {"t": []})
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
    src = {}
    for st in stations:
        src[st["state_source"]] = src.get(st["state_source"], 0) + 1
    print(f"  state from polygon: {src.get('polygon', 0)}, "
          f"fell back to a computed band: {src.get('computed', 0)}")
    print(f"  areas: {len(reg)}")
    for k, v in sorted(reg.items(), key=lambda kv: (-kv[1][1], kv[0]))[:10]:
        print(f"    {k:28s} {v[0]:4d} stations  {v[1]:3d} flagged")
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
