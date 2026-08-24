"""Inline every asset into the template and write a standalone console.

    python -m dashboard.build

The published page must be self-contained. The artifact CSP blocks requests to
any external host, so a CDN import for Leaflet or a runtime fetch of
snapshot.json would silently return nothing and the console would render empty.
Inlining is not a shortcut; it is the only thing that works in both places.

Four substitutions:

    /*__LEAFLET_CSS__*/   vendored Leaflet stylesheet
    /*__LEAFLET_JS__*/    vendored Leaflet, so the map works with no network
    /*__BOUNDARY__*/null  NCMRWF's india_boundary, simplified, so the border
                          still draws offline -- and is the official depiction
    /*__DATA__*/null      the snapshot
"""
from __future__ import annotations
import json
from pathlib import Path

TPL = Path("dashboard/template.html")
SNAP = Path("dashboard/snapshot.json")
VENDOR = Path("dashboard/vendor")
OUT = Path("dashboard/console.html")

SUBS = [
    ("/*__LEAFLET_CSS__*/", VENDOR / "leaflet.css", "leaflet stylesheet"),
    ("/*__LEAFLET_JS__*/", VENDOR / "leaflet.js", "leaflet"),
    ("/*__BOUNDARY__*/null", VENDOR / "india_boundary.min.json", "boundary"),
    ("/*__DATA__*/null", SNAP, "snapshot"),
]


def main() -> None:
    html = TPL.read_text(encoding="utf-8")
    for token, path, label in SUBS:
        if token not in html:
            raise SystemExit(f"template has no {token} placeholder")
        if not path.exists():
            raise SystemExit(
                f"missing {label}: {path}\n"
                "Leaflet and the boundary are vendored under dashboard/vendor/;\n"
                "the snapshot comes from `python -m dashboard.export`.")
        body = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            # Leaflet's CSS points at marker and layer-control PNGs we do not
            # ship and do not use -- stations are circleMarkers, which are SVG.
            # Left in place they would 404 on every load and train people to
            # ignore the console log.
            body = body.replace("url(images/", "url(data:,#")
            body = f"/* vendored leaflet */\n{body}"
        html = html.replace(token, body)

    OUT.write_text(html, encoding="utf-8")
    d = json.loads(SNAP.read_text(encoding="utf-8"))
    print(f"{OUT}  {OUT.stat().st_size/1024:.0f} kB  "
          f"{len(d['stations'])} stations  {len(d['alerts'])} alerts")


if __name__ == "__main__":
    main()
