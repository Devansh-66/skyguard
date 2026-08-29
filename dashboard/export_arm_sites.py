"""Write the ARM validation instruments as a small map layer.

    python -m dashboard.export_arm_sites

These are the nine masts every number on the maintenance board is measured
against: real instruments at US Department of Energy ARM observatories, used
because ARM publishes fault reports written by engineers who physically
inspected the hardware. No Indian network publishes an equivalent answer key.

Everything here is read out of the data rather than typed in: the place names
and coordinates come from each .cdf file's own global attributes
(`location_description`, `lat`, `lon`), and the report count comes from the DQR
table. If a station moves or a report is added, re-running this is the only
thing needed.

THEY ARE A SEPARATE MAP LAYER, NOT AN OVERLAY ON INDIA. Drawing an Oklahoma
mast beside Ahmadabad would say this network monitors Oklahoma, which it does
not. The console offers them as their own choice of network, so both are
visible and neither is implied to be the other.
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAW = Path("data/arm/raw")
DQR = Path("data/arm/dqr_tprh.csv")
OUT = Path("dashboard/arm_sites.json")

OBSERVATORY = {
    "sgp": "Southern Great Plains",
    "nsa": "North Slope of Alaska",
    "ena": "Eastern North Atlantic",
}


def main() -> None:
    import netCDF4
    import pandas as pd

    files = sorted(glob.glob(str(RAW / "**" / "*.cdf"), recursive=True))
    if not files:
        raise SystemExit(f"no .cdf files under {RAW}")

    sites: dict[str, dict] = {}
    for f in files:
        ds = os.path.basename(f).split(".")[0]
        if ds in sites:
            continue
        try:
            d = netCDF4.Dataset(f)
        except Exception:
            continue
        try:
            if "lat" not in d.variables or "lon" not in d.variables:
                continue
            loc = str(getattr(d, "location_description", ""))
            # "Southern Great Plains (SGP), Lamont, Oklahoma" -> the tail is the
            # place. Split on the closing bracket so a site name containing a
            # comma cannot break it.
            place = loc.split(")", 1)[1].strip(" ,") if ")" in loc else loc
            sites[ds] = {
                "id": ds,
                "place": place,
                "observatory": OBSERVATORY.get(str(getattr(d, "site_id", "")),
                                               str(getattr(d, "site_id", ""))),
                "facility": str(getattr(d, "facility_id", "")),
                "latitude": round(float(d.variables["lat"][:]), 4),
                "longitude": round(float(d.variables["lon"][:]), 4),
                "reports": 0,
            }
        finally:
            d.close()

    # How many analyst fault reports we hold for each. A station with none is
    # not a healthy station -- it is one nobody filed a report about, which is a
    # different thing, and the tooltip says so rather than implying health.
    if DQR.exists():
        dq = pd.read_csv(DQR)
        for _, r in dq.iterrows():
            m = re.match(r"([a-z]+met[A-Z]\d+)", str(r.get("datastream", "")))
            if m and m.group(1) in sites:
                sites[m.group(1)]["reports"] += 1

    out = {
        "source": "US DOE ARM. Coordinates and place names from the data files' "
                  "own global attributes.",
        "note": ("Validation instruments, not a monitored network. Every figure "
                 "on the maintenance board is measured against these, because "
                 "ARM publishes fault reports written by engineers who "
                 "inspected the hardware."),
        "stations": sorted(sites.values(), key=lambda s: s["id"]),
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

    print(f"{OUT}  {OUT.stat().st_size/1024:.1f} kB")
    for s in out["stations"]:
        print(f"  {s['id']:12s} {s['place']:34s} {s['latitude']:9.4f} "
              f"{s['longitude']:10.4f}  {s['reports']} reports")


if __name__ == "__main__":
    main()
