"""Freeze the ARM maintenance queue, for hosts without the archive.

    python -m scripts.export_queue

Building the queue reads 138 MB of netCDF across 591 files. The answer is two
hundred kilobytes and it cannot change: the ARM archive is closed, the analyst
reports are written, and the queue is a deterministic function of both.

This is not the same as freezing the live network. The simulated stations are
graded on every request; the ARM board is a retrospective study of a fixed
archive, and a study that cannot change is a file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "queue.json"
ITEMS_OUT = ROOT / "dashboard" / "queue_items.json"


def main() -> None:
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/api/queue")
        if r.status_code != 200:
            sys.exit(f"/api/queue returned {r.status_code}: {r.text[:200]}\n"
                     "The ARM archive has to be present to export it.")
        q = r.json()
        if q.get("source") == "precomputed":
            sys.exit("refusing to re-export from an existing export; "
                     "this host has no ARM archive.")
        OUT.write_text(json.dumps(q, indent=1), encoding="utf-8")
        print(f"  {OUT.stat().st_size / 1024:8.0f} kB  {OUT.name}  "
              f"({len(q['items'])} items)")

        # The details too, keyed by id: their ids carry colons, which make poor
        # filenames, and sixteen of them is 184 kB.
        bundle = {}
        for it in q["items"]:
            d = client.get("/api/queue/" + it["id"])
            if d.status_code != 200:
                sys.exit(f"detail for {it['id']} returned {d.status_code}")
            bundle[it["id"]] = d.json()
        ITEMS_OUT.write_text(json.dumps(bundle, separators=(",", ":")),
                             encoding="utf-8")
        print(f"  {ITEMS_OUT.stat().st_size / 1024:8.0f} kB  {ITEMS_OUT.name}")


if __name__ == "__main__":
    main()
