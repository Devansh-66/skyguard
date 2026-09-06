"""Where is the node stuck? Ask the server rather than guess.

"Stuck" has at least five causes and they need different fixes, so this asks
the server the questions that separate them and prints a verdict instead of a
dump:

  * the server is running old code, so today's fixes are not in it
  * nothing has ever posted, so there is nothing to be stuck
  * the scenario replay is running and fighting a real board for one station id
  * readings are arriving but the clock they carry is wrong, so the trace
    cannot advance
  * readings are arriving and everything is fine, so the stall is in the page

Run it against whichever server the node posts to:

    python -m scripts.diagnose_node                              # the Space
    python -m scripts.diagnose_node --server http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

SPACE = "https://dev-66-skyguard-api.hf.space"
REPLAY_FW = "replay-scenario"


def get(server: str, path: str, timeout: float = 60.0):
    try:
        with urllib.request.urlopen(server.rstrip("/") + path,
                                    timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_http": e.code}
    except Exception as e:                                  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", default=SPACE)
    ap.add_argument("--station", default="WOKWI-ESP32")
    ap.add_argument("--watch", type=float, default=8.0,
                    help="seconds to watch for a new reading arriving")
    a = ap.parse_args()
    s, st = a.server, a.station

    print(f"server  {s}")
    print(f"station {st}\n")

    problems: list[str] = []

    # --- 1. is this server running today's code at all?
    rep = get(s, "/api/edge/replay/status")
    if rep.get("_http") == 404 or rep.get("_error"):
        print("[1] replay endpoint   MISSING")
        problems.append(
            "This server predates the replay work. If it is your own, restart "
            "it -- uvicorn does not pick up edits by itself, and the database "
            "migration that stores which sender wrote each row only runs at "
            "startup.")
    else:
        print(f"[1] replay endpoint   present, running={rep.get('running')}"
              f" sent={rep.get('sent')} pass={rep.get('pass_no')}")

    # --- 2. is anything arriving, and from whom?
    hist = get(s, f"/api/ingest/history?station={st}&limit=50")
    rows = hist.get("readings") or []
    if not rows:
        print("[2] readings          NONE stored for this station")
        problems.append(
            "Nothing has ever posted as this station to this server. Check "
            "SERVER in skyguard_node.ino points where you think it does, and "
            "that the serial monitor shows a line 'uplink 200'.")
    else:
        writers: dict[str, int] = {}
        for r in rows:
            writers[r.get("fw") or "unknown"] = writers.get(r.get("fw") or "unknown", 0) + 1
        newest = rows[0]
        age = time.time() - float(newest.get("t") or 0)
        print(f"[2] readings          {len(rows)} recent, newest {age:.0f}s ago")
        print(f"    writers           {writers}")

        if "unknown" in writers:
            problems.append(
                "Some rows carry no firmware string, which means they were "
                "stored before the schema change. Delete data/skyguard.db and "
                "restart, or the replay cannot tell its own rows from the "
                "board's.")
        if len([w for w in writers if w != REPLAY_FW]) and REPLAY_FW in writers:
            problems.append(
                "BOTH a real board and the scenario replay have written here. "
                "Two senders on one station id produce a trace that is neither "
                "of them. Stop the replay (POST /api/edge/replay/stop) and let "
                "the board own the station.")
        if age > 60:
            problems.append(
                f"The newest reading is {age:.0f}s old, so nothing is arriving "
                f"now. That is the stall: look at the serial monitor for the "
                f"'uplink <code>' line -- a code that is not 200 says the "
                f"server refused it, and no line at all says the node never "
                f"got as far as sending.")

        # --- 3. the clock the readings carry
        dt = newest.get("dt_min")
        frame = newest.get("frame")
        print(f"[3] newest reading    frame={frame} dt_min={dt} "
              f"fw={newest.get('fw')}")
        if frame is None:
            problems.append(
                "Readings carry no frame, so the server cannot place them on "
                "the record's axis and the trace has nowhere to go. Old "
                "firmware -- reflash with the current sketch.")
        if dt in (None, 0):
            problems.append("Readings carry no dt_min; the server will time "
                            "them by arrival instead of by weather.")

    # --- 4. does the grader have a verdict?
    standing = (get(s, "/api/edge/standing").get("standing") or {}).get(st)
    if standing:
        print(f"[4] verdict           band={standing.get('band')} "
              f"case={standing.get('case')} z={standing.get('z')} "
              f"readings={standing.get('readings')}")
        if standing.get("band") == "learning":
            print("    (learning until 40 readings; that is not a stall)")
    else:
        print("[4] verdict           none yet")

    # --- 5. watch for a new one
    before = len(rows)
    print(f"\nwatching {a.watch:.0f}s for a new reading...")
    time.sleep(a.watch)
    after = len((get(s, f"/api/ingest/history?station={st}&limit=50")
                 .get("readings") or []))
    live = get(s, f"/api/ingest/history?station={st}&limit=1").get("readings") or []
    fresh = live and (time.time() - float(live[0].get("t") or 0)) < a.watch + 5
    print(f"  {'ARRIVING' if fresh else 'NOTHING ARRIVED'}"
          f" (stored rows {before} -> {after})")
    if not fresh:
        problems.append(
            "No reading arrived while watching. The stall is upstream of the "
            "server: the node is not sending, or not reaching it.")

    print("\n" + "-" * 68)
    if problems:
        for i, p in enumerate(problems, 1):
            print(f"{i}. {p}\n")
    else:
        print("Nothing wrong on the server side: readings are arriving, they "
              "carry a frame and a clock, and the grader has a verdict. If the "
              "chart still looks frozen, reload the page -- the trace is "
              "fetched, and a tab left open through a server restart holds the "
              "old one.")


if __name__ == "__main__":
    main()
