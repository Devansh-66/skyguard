"""Shrink the India state polygons to something a self-contained page can carry.

    python -m dashboard.simplify_states

The source is 15 MB, which cannot be inlined into console.html -- the page is
already a megabyte and the build embeds every asset so the console works with no
network. At the zoom levels this map uses, most of that 15 MB is coastline
detail finer than one screen pixel.

So: Douglas-Peucker per ring, then coordinates rounded to three decimals, which
is about 100 m and far below anything visible at zoom 4 to 8. Tiny islands below
a minimum area are dropped from the OUTLINES only; they are still inside the
national boundary the console already draws from NCMRWF, so nothing disappears
from the map, only from the state overlay.

PROVENANCE, WHICH MATTERS FOR A SUBMISSION TO MoES

Source: github.com/datameet/maps, docs/data/geojson/states.geojson. Datameet is
an Indian open-data community and the file carries 36 features -- 28 states and
8 union territories -- with one property, ST_NM.

IT IS OUT OF DATE IN TWO KNOWN WAYS, and both are labels rather than geometry:

  - Jammu & Kashmir is one feature. The 2019 reorganisation split it into Jammu
    & Kashmir and Ladakh, so a station in Ladakh is labelled "Jammu & Kashmir"
    here.
  - Dadara & Nagar Havelli and Daman & Diu are separate features. They merged
    into one union territory in 2020.

Neither affects which state a station falls in for the other 34, and neither
affects the NATIONAL boundary, which continues to come from NCMRWF and is the
official depiction. But state outlines drawn from this file should not be
presented as an authoritative administrative map, and the console says so.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path("data/geo/india_states_raw.geojson")
OUT = Path("dashboard/vendor/india_states.min.json")

TOLERANCE = 0.02      # degrees, roughly 2 km
DECIMALS = 3          # roughly 100 m
MIN_RING_AREA = 0.004  # square degrees; below this a ring is a speck


def perpendicular(p, a, b) -> float:
    """Distance from p to the segment a-b, in degrees. Planar is fine at this
    tolerance and this latitude range."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def douglas_peucker(pts: list, tol: float) -> list:
    """Iterative, not recursive: a coastline ring can be tens of thousands of
    points and Python's recursion limit is 1000."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        worst, wi = -1.0, lo
        for i in range(lo + 1, hi):
            d = perpendicular(pts[i], pts[lo], pts[hi])
            if d > worst:
                worst, wi = d, i
        if worst > tol:
            keep[wi] = True
            stack.append((lo, wi))
            stack.append((wi, hi))
    return [p for p, k in zip(pts, keep) if k]


def ring_area(pts: list) -> float:
    """Shoelace, absolute, in square degrees."""
    a = 0.0
    for i in range(len(pts) - 1):
        a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(a) / 2.0


def clean_ring(ring: list) -> list | None:
    pts = [(float(x), float(y)) for x, y in ring]
    if len(pts) < 4:
        return None
    if ring_area(pts) < MIN_RING_AREA:
        return None
    simp = douglas_peucker(pts, TOLERANCE)
    if len(simp) < 4:
        return None
    out = [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in simp]
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing {SRC}\nsee the module docstring for the source")

    src = json.loads(SRC.read_text(encoding="utf-8"))
    feats = []
    dropped = 0
    for f in src["features"]:
        name = str(f["properties"].get("ST_NM", "")).strip()
        geom = f.get("geometry") or {}
        polys = (geom.get("coordinates", []) if geom.get("type") == "MultiPolygon"
                 else [geom.get("coordinates", [])])
        keep_polys = []
        for poly in polys:
            rings = []
            for j, ring in enumerate(poly):
                r = clean_ring(ring)
                if r is None:
                    dropped += 1
                    # An outer ring dropped takes its holes with it.
                    if j == 0:
                        break
                    continue
                rings.append(r)
            if rings:
                keep_polys.append(rings)
        if not keep_polys:
            print(f"  WARNING: {name} vanished entirely")
            continue
        feats.append({
            "type": "Feature",
            "properties": {"st": name},
            "geometry": {"type": "MultiPolygon", "coordinates": keep_polys},
        })

    out = {"type": "FeatureCollection",
           "note": ("Simplified from datameet/maps states.geojson. Pre-2019 "
                    "labels: Jammu & Kashmir is undivided, Dadara & Nagar "
                    "Havelli and Daman & Diu are separate. The national "
                    "boundary on this console comes from NCMRWF, not from "
                    "this file."),
           "features": feats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

    n_pts = sum(len(r) for f in feats for p in f["geometry"]["coordinates"] for r in p)
    print(f"{OUT}  {OUT.stat().st_size / 1024:.0f} kB")
    print(f"  {len(feats)} of {len(src['features'])} features kept, "
          f"{n_pts:,} points, {dropped} specks dropped")
    print(f"  source was {SRC.stat().st_size / 1024 / 1024:.1f} MB "
          f"({SRC.stat().st_size / OUT.stat().st_size:.0f}x smaller)")


if __name__ == "__main__":
    main()
