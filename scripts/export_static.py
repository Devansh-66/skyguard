"""Freeze every API response the frontend asks for into JSON files.

    python -m scripts.export_static

WHY THIS IS POSSIBLE, AND WHY IT IS THE RIGHT DEFAULT FOR NOW

Nothing this app serves is live. There is no ingest yet: the queue is a survey
of a fixed ARM archive, the maps are files a build step produced, and the
catalog is a listing of both. Every endpoint is a deterministic function of data
that does not change while the process runs -- and a server that only ever
returns the same bytes is a server that does not need to exist.

So the whole site can be static, which means it can go on GitHub Pages,
Cloudflare Pages or Vercel with no Python running anywhere.

WHAT THIS IS NOT

It is not a replacement for the API. The moment readings arrive over MQTT the
queue stops being a fixed answer and this export stops being honest. That is
what VITE_STATIC distinguishes: the archive can be frozen, the live network
cannot.

HOW

Through FastAPI's TestClient rather than over HTTP, so no server has to be
running and the export cannot silently capture a stale one.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "api"

# Everything the frontend fetches. Kept as a literal list rather than scraped
# from the router: an endpoint the app does not call has no business being
# frozen, and a new call that nobody added here fails loudly in the browser
# with the command that fixes it.
PATHS = [
    "/api/queue",
    "/api/ai/catalog",
    "/api/tiles/status",
    "/api/map/sim",
    "/api/map/wdqms",
    "/api/map/arm",
    "/api/map/states",
    "/api/map/boundary",
]


def _upstream_tiles(status: dict) -> bytes:
    """Point the map at the upstream tiles directly.

    THE TILE PROXY IS THE ONE THING HERE THAT IS GENUINELY DYNAMIC. It fetches
    Esri imagery, caches it on disk, and turns the NCMRWF boundary WMS into
    tiles. None of that can be frozen into a file, and a static build that kept
    the proxy's URLs would come up with a map that 404s every tile.

    Basemap tiles are plain images, so a browser can take them straight from
    Esri with no proxy and no CORS grant -- an <img> has never needed one. Note
    the axis order: this Esri service is {z}/{y}/{x}, not {z}/{x}/{y}.

    The boundary cannot be done that way, because turning a WMS into a tile
    template is exactly the arithmetic the proxy was doing. So it is set to null
    and the app draws the vendored NCMRWF geometry instead -- same source,
    different form.
    """
    status["tile_template"] = status["basemap"]
    status["boundary_template"] = None
    status["note"] = ("Static export: basemap direct from Esri, boundary drawn "
                      "from the vendored NCMRWF geometry. No tile proxy.")
    return json.dumps(status).encode()


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        sys.exit("needs httpx: pip install httpx")

    print("building the app (this runs the belief engine once)...")
    from api.main import app

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    total = 0
    with TestClient(app) as client:
        for path in PATHS:
            r = client.get(path)
            if r.status_code != 200:
                sys.exit(f"{path} returned {r.status_code}: {r.text[:200]}\n"
                         "Run `python -m scripts.build_site` first.")
            body = r.content
            if path == "/api/tiles/status":
                body = _upstream_tiles(r.json())
            dest = OUT.parent / (path.lstrip("/") + ".json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            total += len(body)
            print(f"  {len(body) / 1024:8.0f} kB  {path}")

        # THE QUEUE ITEMS GO IN ONE FILE, keyed by id. Their ids carry colons
        # -- "sgpmetE37:D160930.5:rh" -- which are illegal in Windows filenames
        # and awkward on several hosts, so sixteen files become one object.
        items = client.get("/api/queue").json()["items"]
        bundle = {}
        for it in items:
            enc = "/".join(it["id"].split("/"))
            r = client.get(f"/api/queue/{enc}")
            if r.status_code != 200:
                sys.exit(f"queue item {it['id']} returned {r.status_code}")
            bundle[it["id"]] = r.json()
        blob = json.dumps(bundle, separators=(",", ":")).encode()
        (OUT / "queue-items.json").write_bytes(blob)
        total += len(blob)
        print(f"  {len(blob) / 1024:8.0f} kB  /api/queue-items.json  "
              f"({len(bundle)} items)")

    print(f"\n{total / 1024 / 1024:.2f} MB into {OUT.relative_to(ROOT)}")
    print("Now build the frontend against it:")
    print("    cd web && VITE_STATIC=1 npm run build")


if __name__ == "__main__":
    main()
