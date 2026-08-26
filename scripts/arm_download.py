"""Download an ARM meteorology window without storing credentials in the repo.

Example (PowerShell):
  $env:ARM_USER='your-arm-id'
  $env:ARM_TOKEN='token from https://adc.arm.gov/armlive/home'
  python -m scripts.arm_download sgpmetE31.b1 2017-09-14 2017-09-28

The ARM Live Data service returns one daily NetCDF file per matching day.  The
script preserves those original files and writes the returned manifest beside
them, so a DQR-labelled fault interval can always be traced back to its source.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://adc.arm.gov/armlive"
UA = "SkyGuard/1.0 (SIH 2026 PS26073 research download)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("datastream", help="for example sgpmetE31.b1")
    parser.add_argument("start", help="YYYY-MM-DD")
    parser.add_argument("end", help="YYYY-MM-DD")
    parser.add_argument("--out", default="data/arm/raw")
    args = parser.parse_args()

    user, token = os.environ.get("ARM_USER"), os.environ.get("ARM_TOKEN")
    if not user or not token:
        raise SystemExit("Set ARM_USER and ARM_TOKEN; never put either in source code.")

    auth = urllib.parse.quote(f"{user}:{token}", safe="")
    query = (f"{BASE}/query?user={auth}&ds={urllib.parse.quote(args.datastream)}"
             f"&start={args.start}&end={args.end}&wt=json")
    manifest = json.loads(fetch(query))
    if manifest.get("status") != "success":
        raise SystemExit(f"ARM query failed: {manifest}")

    outdir = Path(args.out) / f"{args.datastream}_{args.start.replace('-', '')}_{args.end.replace('-', '')}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    downloaded = 0
    for name in manifest["files"]:
        target = outdir / name
        if target.exists() and target.stat().st_size:
            continue
        url = f"{BASE}/saveData?user={auth}&file={urllib.parse.quote(name)}"
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(fetch(url))
        temp.replace(target)
        downloaded += 1

    files = sorted(outdir.glob("*.cdf"))
    print(f"{len(files)} files present ({downloaded} downloaded) in {outdir}")


if __name__ == "__main__":
    main()
