"""Post a generated Wokwi scenario to a server, as the node would.

WHY THIS EXISTS

The deployed Space shows the hardware node as a dot with nothing behind it, and
that is correct: nothing has ever posted as WOKWI-ESP32, so there is no trace,
no case and no chart. The node appears when readings arrive, and readings
arrive when somebody starts the simulation.

Starting it needs Wokwi -- the browser playground, or the CLI with a token to
drive the automation. This script is the third option: it reads the SAME
scenario file the simulator would play and posts the same JSON body the
firmware builds, so the server sees exactly what it would see from the board.

WHAT IT IS NOT

It is not evidence that the firmware works. It exercises everything downstream
of the sensor -- the screen, the ingest door, the neighbour grading, the
episode rule, the board -- and nothing at all upstream of it. Whether the ESP32
build compiles, fits in flash and keeps up at cadence is established by running
it, and by nothing here.

USAGE

    python -m scripts.replay_scenario                     # to the Space
    python -m scripts.replay_scenario --server http://127.0.0.1:8000
    python -m scripts.replay_scenario --rate 20 --limit 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCENARIO = Path(__file__).resolve().parent.parent / "firmware" / "skyguard_node" / "weather-scenario.yaml"
SPACE = "https://dev-66-skyguard-api.hf.space"

# The firmware's knob mapping. Kept in step with skyguard_node.ino by hand; a
# silent mismatch would show up as a pressure offset nobody could explain.
PRES_LO, PRES_HI = 950.0, 1050.0
SIM_MINUTES_PER_SAMPLE = 30.0

STEP = re.compile(
    r"control: temperature\s*\n\s*value: ([-\d.]+).*?"
    r"control: humidity\s*\n\s*value: ([-\d.]+).*?"
    r"control: position\s*\n\s*value: ([-\d.]+)", re.S)


def samples(path: Path):
    """(temp, rh, pressure) per sample, read out of the scenario itself.

    Read from the scenario rather than regenerated, so what is posted is
    literally what the simulator would set on the sensors -- not a second
    computation that could differ from it.
    """
    text = path.read_text(encoding="utf-8")
    for t, h, pos in STEP.findall(text):
        yield float(t), float(h), PRES_LO + (PRES_HI - PRES_LO) * float(pos)


def post(server: str, path: str, body: dict, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        server.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", default=SPACE)
    ap.add_argument("--station", default="WOKWI-ESP32")
    ap.add_argument("--scenario", default=str(SCENARIO))
    ap.add_argument("--rate", type=float, default=25.0,
                    help="readings per second; the point is to fill a demo, "
                         "not to imitate the node's own cadence")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many (0 = the whole scenario)")
    ap.add_argument("--start-frame", type=int, default=0)
    args = ap.parse_args()

    # The node's own screen. Imported rather than reimplemented: the server
    # compares its conclusion with the node's, and a second copy of these rules
    # here would make edge_screen_disagreement mean "two scripts disagree".
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from api.ingest import physics_screen

    rows = list(samples(Path(args.scenario)))
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise SystemExit(f"no samples in {args.scenario}")

    print(f"posting {len(rows)} readings as {args.station} -> {args.server}")
    gap = 1.0 / max(args.rate, 0.1)
    first_flag = None
    case_at = None
    bands: dict[str, int] = {}

    for i, (t, h, p) in enumerate(rows):
        body = {
            "station": args.station, "temp": t, "rh": h, "pres": p,
            "seq": i, "dt_min": SIM_MINUTES_PER_SAMPLE,
            "frame": args.start_frame + i, "pass_no": 0,
            "fw": "replay-scenario",
            "flags": physics_screen(t, h, p),
            "vbat_mv": 3900, "log_temp_c100": 3100,
            "flat_pct": 0, "gap_pct": 0, "selftest_mask": 0,
            "health": "S1", "boot_id": 1, "reboot_count": 0,
        }
        try:
            v = post(args.server, "/api/ingest", body)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"reading {i} refused: {e.code} {e.read()[:200]!r}")
        except Exception as e:                          # noqa: BLE001
            raise SystemExit(f"reading {i} failed: {type(e).__name__}: {e}")

        g = v.get("grade")
        if g:
            bands[g["band"]] = bands.get(g["band"], 0) + 1
            if first_flag is None and g["band"] in ("watch", "fault"):
                first_flag = (i, g["band"], g["z"])
            if case_at is None and g.get("case_open"):
                case_at = (i, g["case"], g.get("open_from_frame"))
        if i % 40 == 0:
            print(f"  {i:4d}/{len(rows)}  {t:5.1f} C  "
                  f"{(g or {}).get('band', '-')}")
        time.sleep(gap)

    print(f"\nbands over the run: {bands}")
    print(f"first reading flagged: {first_flag}")
    print(f"case opened at:        {case_at}")
    print(f"\nNow visible at {args.server}/app/network (the dashed marker) and "
          f"{args.server}/app/board")


if __name__ == "__main__":
    main()
