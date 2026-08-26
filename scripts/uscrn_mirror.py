"""Mirror USCRN's raw transmitted stream before NCEI deletes it.

    python -m scripts.uscrn_mirror            # catch up on whatever is new
    python -m scripts.uscrn_mirror --status   # what we hold, without fetching

WHY THIS RUNS ON A CLOCK

NCEI publishes the raw satellite transmissions from every US Climate Reference
Network station at

    https://www.ncei.noaa.gov/pub/data/uscrn/operations/subhourly-tx/

and keeps roughly SIXTEEN DAYS of them. Measured on 2026-08-26: 2184 files
spanning 2026-08-11 to 2026-08-26. Everything older is gone from that endpoint.
The full history exists in the NCEI archive (gov.noaa.ncdc:C00309) but it is not
self-service -- it is an email order, in an 18-bit packed encoding with 26
format versions across network history, which NCEI's own documentation
discourages people from using.

So the cheap route to a long record is to start copying now. At roughly 40 kB
per 10-minute file this is about 5-6 MB a day for the entire national network,
or ~2 GB a year. That is nothing, and every day it does not run is a day that
cannot be recovered later.

WHAT IS IN HERE THAT THE PUBLISHED PRODUCT DOES NOT HAVE

The public QC product (products/subhourly01) gives ONE air temperature column
and no pressure at all. Each USCRN station actually carries THREE independent
platinum resistance thermometers, each in its own separately fan-aspirated
shield, and NCEI computes the official value afterwards by seeing which pairs
agree within 0.3 K. The transmitted stream carries the individual values, and
alongside them the diagnostics:

    three thermometers          disagreement is ground truth for a sensor fault,
                                with no model and no assumption behind it
    fan speed, per shield       a failing aspirator is the physical CAUSE of a
                                warm bias in one specific probe -- cause and
                                effect in the same record
    battery voltages            datalogger, and fan/transmitter under load
    DLDO                        minutes this hour the datalogger door was open,
                                which is a dated maintenance event

That combination -- redundant measurement, the physical cause channel, and a
maintenance log -- is the closest thing to a labelled sensor-fault dataset that
exists in the open, and none of it survives into the product most people
download.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO

It does not decode. The packed encoding has many versions and getting it wrong
silently is worse than not doing it, so this only preserves bytes faithfully and
records what it fetched. Decoding is a separate job against the format spec,
and it can be done at leisure once the bytes are safe.
"""
from __future__ import annotations
import argparse
import gzip
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.ncei.noaa.gov/pub/data/uscrn/operations/"
STREAMS = {"subhourly-tx": r'href="(Crn_[^"]+\.ncdc)"',
           "hourly-tx": r'href="([^"]+\.kwal)"'}
UA = ("SkyGuard/1.0 (SIH 2026 PS26073 research mirror; "
      "public NCEI endpoint; contact via repository)")
OUT = Path("data/uscrn_tx")


def _get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def listing(stream: str) -> list[str]:
    html = _get(BASE + stream + "/").decode("utf-8", "replace")
    return sorted(set(re.findall(STREAMS[stream], html)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", default="subhourly-tx,hourly-tx")
    ap.add_argument("--pause", type=float, default=0.25,
                    help="seconds between requests -- this is a public service "
                         "and it is not to be hammered")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    if args.status:
        for st in args.streams.split(","):
            d = OUT / st
            files = sorted(d.glob("**/*.gz")) if d.exists() else []
            size = sum(f.stat().st_size for f in files) / 1e6
            days = sorted({f.name[4:12] for f in files if f.name.startswith("Crn_")})
            print(f"{st:14s} {len(files):6d} files  {size:8.1f} MB"
                  + (f"  {days[0]}..{days[-1]}" if days else ""))
        return

    total_new = total_bytes = 0
    for st in args.streams.split(","):
        try:
            names = listing(st)
        except Exception as exc:
            print(f"{st}: listing failed: {exc}")
            continue
        d = OUT / st
        d.mkdir(parents=True, exist_ok=True)
        new = 0
        for n in names:
            # bucket by day so a directory never holds a year of files
            m = re.search(r"(\d{8})", n)
            sub = d / (m.group(1) if m else "misc")
            sub.mkdir(exist_ok=True)
            dest = sub / (n + ".gz")
            if dest.exists():
                continue
            try:
                raw = _get(BASE + st + "/" + n)
            except Exception as exc:
                print(f"  {n}: {exc}")
                continue
            # write via a temp name so an interrupted run never leaves a
            # truncated file that a later run would mistake for complete
            tmp = dest.with_suffix(".part")
            with gzip.open(tmp, "wb", compresslevel=6) as fh:
                fh.write(raw)
            tmp.replace(dest)
            new += 1
            total_bytes += len(raw)
            time.sleep(args.pause)
            if args.max and new >= args.max:
                break
        print(f"{st:14s} listed {len(names):5d}  fetched {new:5d} new")
        total_new += new

    log = OUT / "mirror_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "new_files": total_new, "raw_bytes": total_bytes}) + "\n")
    print(f"\n{total_new} new files, {total_bytes/1e6:.1f} MB raw this run")


if __name__ == "__main__":
    main()
