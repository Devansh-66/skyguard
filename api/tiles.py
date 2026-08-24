"""Basemap tiles and boundary overlay, proxied and cached on disk.

WHY THESE TWO SOURCES, AND NOT A STREET MAP

This is the arrangement NCMRWF uses on its own operational dashboard
(nwp.ncmrwf.gov.in), and the reasoning behind it is worth stating because it
solves a problem that has no other clean answer.

    basemap   Esri World Imagery   satellite photography -- no political lines
                                   are drawn on it at all, so there are none to
                                   get wrong
    boundary  NCMRWF GeoServer     the national outline, served by a Ministry of
                                   Earth Sciences body, i.e. the official
                                   Government of India depiction

Boundary depiction on Indian maps is regulated, and the depiction of Jammu &
Kashmir and Aksai Chin by foreign community-mapped sources is not the official
one. Putting such a rendering on a screen shown to MoES/IMD is a problem no
accuracy number recovers from. Imagery carries no borders; the borders come from
an Indian government server. Verified: an Esri World Imagery tile over Kashmir
contains no lines or labels of any kind.

Both are proxied rather than fetched by the browser directly, for the same three
reasons as before: same origin, so no CORS; one place to set an identifying
User-Agent; and a disk cache, so a demo on a projector with no wifi still draws
its map once warm.

ATTRIBUTION IS NOT OPTIONAL. Esri's imagery service and NCMRWF's WMS both
require acknowledgement on any map that uses them. The console prints both.
"""
from __future__ import annotations
import hashlib
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter()

# Esri takes /tile/{z}/{y}/{x} -- row before column, unlike the {z}/{x}/{y} of
# most XYZ services. Getting this backwards produces a map that looks almost
# right and is transposed, which is worse than one that fails.
TILE_URL = os.environ.get(
    "SKYGUARD_TILE_URL",
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}")

# NCMRWF's own boundary layers, discovered from their GetCapabilities:
#   ncmrwf:india_boundary   national outline
#   ncmrwf:india_state      state polygons
#   ncmrwf:state_boundary   state outlines
#   ncmrwf:global_boundaries
BOUNDARY_WMS = os.environ.get(
    "SKYGUARD_BOUNDARY_WMS",
    "https://api.ncmrwf.gov.in/geoserver/ncmrwf/wms")
BOUNDARY_LAYER = os.environ.get("SKYGUARD_BOUNDARY_LAYER",
                                "ncmrwf:india_boundary")

CACHE = Path(os.environ.get("SKYGUARD_TILE_CACHE", "data/tilecache"))
USER_AGENT = os.environ.get(
    "SKYGUARD_TILE_UA",
    "SkyGuard/1.0 (SIH 2026 PS26073 prototype; contact via repository)")

ATTRIBUTION = ("Imagery &copy; Esri, Maxar, Earthstar Geographics &middot; "
               "Boundary &copy; NCMRWF, Ministry of Earth Sciences")

MAX_ZOOM = 12
TIMEOUT = 12
_R = 6378137.0                      # Web Mercator sphere radius


def _fetch(url: str, key: str) -> bytes:
    """Fetch once, then serve from disk forever.

    Tiles for a fixed area do not change on any timescale this project cares
    about, so a cached tile is never revalidated. That is what makes the offline
    demo work.
    """
    p = CACHE / key[:2] / f"{key}.img"
    if p.exists():
        return p.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # 503, not 500: an unreachable upstream is a normal state on a machine
        # with no network, and the console treats it as "no basemap" rather
        # than an error.
        raise HTTPException(503, f"tile upstream unavailable: {exc}") from exc
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def _check(z: int, x: int, y: int) -> None:
    if not (0 <= z <= MAX_ZOOM) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
        raise HTTPException(400, "tile coordinates out of range")


def _tile_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Web Mercator metre bounds of an XYZ tile -- what a WMS GetMap needs."""
    span = 2 * math.pi * _R / (2 ** z)
    minx = -math.pi * _R + x * span
    maxy = math.pi * _R - y * span
    return (minx, maxy - span, minx + span, maxy)


@router.get("/api/tiles/{z}/{x}/{y}.png")
def tile(z: int, x: int, y: int) -> Response:
    """One basemap tile."""
    _check(z, x, y)
    url = TILE_URL.format(z=z, x=x, y=y)
    key = hashlib.sha1(f"base|{url}".encode()).hexdigest()
    data = _fetch(url, key)
    return Response(data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000"})


@router.get("/api/boundary/{z}/{x}/{y}.png")
def boundary(z: int, x: int, y: int) -> Response:
    """One boundary tile, rendered by NCMRWF's WMS for this tile's extent."""
    _check(z, x, y)
    bbox = ",".join(f"{v:.6f}" for v in _tile_bbox_3857(z, x, y))
    q = urllib.parse.urlencode({
        "service": "WMS", "request": "GetMap", "version": "1.1.1",
        "layers": BOUNDARY_LAYER, "styles": "",
        "format": "image/png", "transparent": "true",
        "srs": "EPSG:3857", "width": 256, "height": 256, "bbox": bbox,
    })
    url = f"{BOUNDARY_WMS}?{q}"
    key = hashlib.sha1(f"bnd|{url}".encode()).hexdigest()
    data = _fetch(url, key)
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000"})


@router.get("/api/tiles/status")
def status() -> dict:
    """Whether a basemap is available, and how much is already cached.

    The console asks before offering the tile view, so it never presents a map
    mode that will render blank.
    """
    n = sum(1 for _ in CACHE.rglob("*.img")) if CACHE.exists() else 0
    reachable = {}
    for name, probe in (("basemap", TILE_URL.format(z=4, x=11, y=7)),
                        ("boundary", f"{BOUNDARY_WMS}?service=WMS&request=GetMap"
                                     "&version=1.1.1&layers=" + BOUNDARY_LAYER +
                                     "&styles=&format=image/png&transparent=true"
                                     "&srs=EPSG:4326&width=64&height=64"
                                     "&bbox=68,6,98,38")):
        try:
            req = urllib.request.Request(probe, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=6) as r:
                reachable[name] = r.status == 200
        except Exception:
            reachable[name] = False
    return {
        "available": any(reachable.values()) or n > 0,
        "upstream_reachable": reachable,
        "cached_tiles": n,
        "basemap": TILE_URL,
        "boundary_wms": BOUNDARY_WMS,
        "boundary_layer": BOUNDARY_LAYER,
        "attribution": ATTRIBUTION,
        "official_indian_boundary_source": "ncmrwf.gov.in" in BOUNDARY_WMS,
        "max_zoom": MAX_ZOOM,
    }
