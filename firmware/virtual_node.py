"""A station node in Python, speaking the same protocol as the firmware.

    python -m firmware.virtual_node --station Pune --n 40

WHY THIS EXISTS ALONGSIDE THE FIRMWARE

The ESP32 firmware can only run inside Wokwi (or on hardware), which means it
cannot run in CI, cannot run on a machine without the VS Code extension, and
cannot be checked by anyone reviewing the repository. This speaks the identical
wire protocol from Python, so the SERVER half is testable everywhere and always.

It is a protocol test, not a sensor simulation. It proves the endpoint accepts
what the node sends, rejects what it should, and reports the disagreement
between the node's screen and the server's. It proves nothing about the ESP32's
timing, memory, or radio -- only Wokwi or hardware can do that, and this file
does not pretend otherwise.

The fault cases below are the same ones the physics screen exists to catch, so a
green run here means the screen is wired correctly end to end.
"""
from __future__ import annotations
import argparse
import json
import random
import math
import urllib.error
import urllib.request

RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 105.0), "pres": (500.0, 1100.0)}
RATE = {"temp": 3.0, "rh": 20.0, "pres": 2.0}
FW = "virtual-node-1.0.0"


# One per process, like the firmware picks one per boot: a NEW id on the same
# station means a reboot, a gap without one means an outage.
BOOT_ID = random.getrandbits(32)


def node_screen(t: float, h: float, p: float,
                prev: tuple | None, dt_min: float) -> list[str]:
    """The firmware's physics screen, reimplemented exactly.

    Kept deliberately in step with firmware/skyguard_node/skyguard_node.ino. If
    the two drift apart the server reports `edge_screen_disagreement` on every
    reading, which is a loud failure rather than a silent one -- that is the
    point of the server re-running the same checks.
    """
    out = []
    for var, v in (("temp", t), ("rh", h), ("pres", p)):
        lo, hi = RAILS[var]
        if not math.isfinite(v):
            out.append(var + "_nonfinite")
        elif not (lo <= v <= hi):
            out.append(var + "_out_of_range")
    if math.isfinite(h) and 100.0 < h <= RAILS["rh"][1]:
        out.append("rh_supersaturated")
    # A rejected reading is not compared for rate. Differencing against a -999
    # sentinel produces a huge bogus rate flag on top of the range flag that
    # already explains the problem -- and the server skips it for the same
    # reason, so running it here would desynchronise the two screens.
    rejected = any(f.endswith("_out_of_range") or f.endswith("_nonfinite")
                   for f in out)
    if prev is not None and dt_min > 0 and not rejected:
        for var, v, pv in (("temp", t, prev[0]), ("rh", h, prev[1]),
                           ("pres", p, prev[2])):
            if math.isfinite(v) and abs(v - pv) > RATE[var] * dt_min:
                out.append(var + "_rate")
    return out


def post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--station", default="Pune")
    args = ap.parse_args()

    b = get(f"{args.server}/api/baseline/{args.station}")
    print(f"baseline for {args.station}: fitted={b['fitted']}"
          + ("" if b["fitted"] else f"  ({b.get('note','')})"))
    if b["fitted"]:
        print(f"  temp coefficients: {[round(x, 3) for x in b['coefs']['temp']]}")

    # Each case states what the SERVER should conclude, so a wrong answer is a
    # failed assertion rather than a line of output nobody reads.
    cases = [
        ("clean reading",             24.5, 61.0, 1008.2, True,  []),
        ("supersaturated in fog",     19.0, 100.6, 1008.2, True,  ["rh_supersaturated"]),
        ("sentinel value",          -999.0, 61.0, 1008.2, False, ["temp_out_of_range"]),
        ("RH above any real probe",   24.5, 140.0, 1008.2, False, ["rh_out_of_range"]),
        ("pressure of a spacecraft",  24.5, 61.0, 3.0,    False, ["pres_out_of_range"]),
    ]

    prev, seq, failures = None, 0, 0
    print(f"\n{'case':<28}{'accepted':>9}   server flags")
    print("-" * 78)
    for name, t, h, p, want_ok, want_flags in cases:
        seq += 1
        # dt is large so the rate check never fires -- these cases test the
        # rails, and a rate flag here would be an artifact of how fast the loop
        # happens to run, not a property of the reading.
        flags = node_screen(t, h, p, prev, dt_min=60.0)
        # HOUSEKEEPING TRAVELS TOO, so this node stays in parity with the
        # firmware. The point of this file is that the server half can be
        # tested without a simulator; that only holds while it sends the same
        # fields. Healthy values here -- the faults being exercised below are
        # sensor faults, not device faults.
        r = post(f"{args.server}/api/ingest",
                 {"station": args.station, "temp": t, "rh": h, "pres": p,
                  "seq": seq, "flags": flags, "fw": FW, "dt_min": 60.0,
                  "vbat_mv": 3980, "log_temp_c100": 4200,
                  "flat_pct": 0, "gap_pct": 0,
                  "selftest_mask": 0, "health": "S1",
                  "boot_id": BOOT_ID, "reboot_count": 0})
        got = [f for f in r["server_flags"] if f != "edge_screen_disagreement"]
        ok = (r["accepted"] == want_ok) and (set(got) == set(want_flags))
        agree = "edge_screen_disagreement" not in r["server_flags"]
        if not ok or not agree:
            failures += 1
        mark = "ok " if (ok and agree) else "FAIL"
        print(f"[{mark}] {name:<22}{str(r['accepted']):>9}   {', '.join(got) or '-'}")
        if not agree:
            print(f"         node said {flags}, server said {got}")
        prev = (t, h, p)

    rec = get(f"{args.server}/api/ingest/recent?station={args.station}&limit=3")
    print(f"\nserver buffered {rec['stations'].get(args.station, 0)} readings "
          f"for {args.station}")

    print()
    if failures:
        raise SystemExit(f"{failures} of {len(cases)} cases FAILED")
    print(f"all {len(cases)} cases behaved as specified, and the node's screen "
          "agreed with the server's on every one.")


if __name__ == "__main__":
    main()
