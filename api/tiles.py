"""Basemap tile proxy with an on-disk cache.

WHY PROXY RATHER THAN LET THE BROWSER FETCH DIRECTLY

  * Same origin. The console is served by this app, so a proxied tile needs no
    CORS grant and no tile-host allowlist.
  * It works offline once warm. A demo on a projector with no wifi still draws
    its basemap, which is the difference between a working demo and an apology.
  * One place to set a correct User-Agent. OSM's tile usage policy requires an
    identifying UA and forbids bulk downloading; a proxy makes that a single
    line rather than a promise.

WHICH BASEMAP TO ACTUALLY SHIP -- READ THIS BEFORE THE SUBMISSION

The default below is OpenStreetMap, which is correct for DEVELOPMENT and wrong
for delivery. OSM renders international boundaries by its own community
convention, and its depiction of the boundaries of Jammu & Kashmir and Aksai
Chin is not the official Government of India depiction. Shipping it inside a
console submitted to MoES / IMD puts a foreign rendering of disputed frontiers
on a government screen.

For the submission use an Indian government source:

    Bhuvan (ISRO)      https://bhuvan.nrsc.gov.in  -- WMS/WMTS, registration
                       required, and it is the officially approved depiction.
    Survey of India    https://onlinemaps.surveyofindia.gov.in

Point SKYGUARD_TILE_URL at one of those and nothing else here changes. The
default is deliberately loud about being a development default rather than
quietly shipping.
"""
from __future__ import annotations
import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter()

# {z}/{x}/{y}. Override with SKYGUARD_TILE_URL -- see the warning above.
TILE_URL = os.environ.get(
    "SKYGUARD_TILE_URL",
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png")

CACHE = Path(os.environ.get("SKYGUARD_TILE_CACHE", "data/tilecache"))
USER_AGENT = os.environ.get(
    "SKYGUARD_TILE_UA",
    "SkyGuard/1.0 (SIH 2026 PS26073 prototype; contact via repository)")

MAX_ZOOM = 12          # a station network does not need building-level detail
TIMEOUT = 8


def _path(z: int, x: int, y: int) -> Path:
    key = hashlib.sha1(f"{TILE_URL}|{z}/{x}/{y}".encode()).hexdigest()
    return CACHE / key[:2] / f"{key}.png"


@router.get("/api/tiles/{z}/{x}/{y}.png")
def tile(z: int, x: int, y: int) -> Response:
    """One basemap tile, cached forever on disk.

    Tiles for a fixed area do not change on any timescale this project cares
    about, so a cached tile is never revalidated. That is what makes the
    offline demo work.
    """
    if not (0 <= z <= MAX_ZOOM) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
        raise HTTPException(400, "tile coordinates out of range")

    p = _path(z, x, y)
    if p.exists():
        return Response(p.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=31536000",
                                 "X-Tile-Cache": "hit"})

    url = TILE_URL.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        # 503, not 500: the upstream is unreachable, which is a normal state on
        # a machine with no network. The console treats it as "no basemap" and
        # falls back rather than showing an error.
        raise HTTPException(503, f"tile upstream unavailable: {exc}") from exc

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000",
                             "X-Tile-Cache": "miss"})


@router.get("/api/tiles/status")
def status() -> dict:
    """Whether a basemap is available, and how much of it is already cached.

    The console asks this before offering the tile view, so it never presents a
    map mode that will render blank.
    """
    n = sum(1 for _ in CACHE.rglob("*.png")) if CACHE.exists() else 0
    official = "bhuvan" in TILE_URL.lower() or "surveyofindia" in TILE_URL.lower()
    try:
        req = urllib.request.Request(TILE_URL.format(z=3, x=5, y=3),
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4) as r:
            reachable = r.status == 200
    except Exception:
        reachable = False
    return {
        "available": reachable or n > 0,
        "upstream_reachable": reachable,
        "cached_tiles": n,
        "source": TILE_URL,
        "official_indian_source": official,
        "warning": None if official else (
            "Development basemap. OpenStreetMap's depiction of the boundaries "
            "of Jammu & Kashmir and Aksai Chin is not the official Government "
            "of India depiction. Set SKYGUARD_TILE_URL to a Bhuvan (ISRO) or "
            "Survey of India endpoint before submitting."),
        "max_zoom": MAX_ZOOM,
    }
