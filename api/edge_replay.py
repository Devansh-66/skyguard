"""Replay the node's scenario into ingest, on demand, from the service itself.

WHY THIS IS A BUTTON AND NOT A STARTUP TASK

The Space's disk is ephemeral: every rebuild clears the readings, and the
hardware node goes back to being a dot with nothing behind it. That is not a
bug to work around -- it is what a reset looks like, and re-seeding it by hand
after each deploy only hides who is doing the work.

It is also not a reason to start the replay automatically. The feeder next to
it deliberately does not start with the service, because the node drives the
dashboard clock and a record that begins replaying the moment anyone opens the
page is one nobody asked for. The same argument applies here. So: nothing runs
until somebody presses something, and pressing it is one call rather than a
script somebody has to find.

WHAT IT REPLAYS

The same scenario file the Wokwi simulator would play, posted through the same
`/api/ingest` path the board uses, with the same body the firmware builds. It
exercises everything downstream of the sensor and nothing upstream of it: it is
a way to see the pipeline run, and it is not evidence that the firmware works.

Readings carry `fw="replay-scenario"` so their origin is visible in the store
and on the wire. And the replay YIELDS: if a reading arrives from anything else
-- a real board in Wokwi -- it stops and leaves the station to the device.
"""
from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

SCENARIO = (Path(__file__).resolve().parent.parent / "firmware"
            / "skyguard_node" / "weather-scenario.yaml")

# The firmware's knob mapping, and how much weather one sample stands for.
PRES_LO, PRES_HI = 950.0, 1050.0
SIM_MINUTES_PER_SAMPLE = 30.0

_STEP = re.compile(
    r"control: temperature\s*\n\s*value: ([-\d.]+).*?"
    r"control: humidity\s*\n\s*value: ([-\d.]+).*?"
    r"control: position\s*\n\s*value: ([-\d.]+)", re.S)

_lock = threading.Lock()
_state: dict = {"running": False, "sent": 0, "total": 0, "station": None,
                "stopped_by": None}


def samples(path: Path = SCENARIO):
    """(temp, rh, pressure) per sample, read out of the scenario itself.

    Read rather than regenerated: what is posted must be literally what the
    simulator would set on the sensors, not a second computation of it.
    """
    text = path.read_text(encoding="utf-8")
    for t, h, pos in _STEP.findall(text):
        yield float(t), float(h), PRES_LO + (PRES_HI - PRES_LO) * float(pos)


async def _run(station: str, rate: float, limit: int) -> None:
    from api import edge_grade, store
    from api.ingest import Reading, ingest, physics_screen

    rows = list(samples())
    if limit:
        rows = rows[:limit]
    _state.update(total=len(rows), sent=0, station=station, stopped_by=None)

    gap = 1.0 / max(rate, 0.1)
    try:
        for i, (t, h, p) in enumerate(rows):
            if not _state["running"]:
                _state["stopped_by"] = "stopped"
                return
            flags = physics_screen(t, h, p)
            ingest(Reading(station=station, temp=t, rh=h, pres=p, seq=i,
                           dt_min=SIM_MINUTES_PER_SAMPLE, frame=i, pass_no=0,
                           fw="replay-scenario", flags=flags,
                           vbat_mv=3900, log_temp_c100=3100,
                           flat_pct=0, gap_pct=0, selftest_mask=0,
                           health="S1", boot_id=1, reboot_count=0))
            _state["sent"] = i + 1

            # YIELD TO A REAL BOARD.
            #
            # If something else is posting as this station -- an ESP32 in
            # Wokwi -- two senders are writing the same frames and the trace
            # is neither of them. The device wins; this is the stand-in.
            last = store.history(station, 1)
            if last and last[0].get("fw") not in (None, "replay-scenario"):
                _state["stopped_by"] = f"a real node ({last[0].get('fw')})"
                edge_grade.reset(station)
                return
            await asyncio.sleep(gap)
    finally:
        _state["running"] = False


@router.post("/api/edge/replay")
async def replay(station: str = Query("WOKWI-ESP32"),
                 rate: float = Query(20.0, gt=0, le=200),
                 limit: int = Query(0, ge=0)) -> dict:
    """Reset the node's record and play the scenario into it again."""
    from api import edge_grade, store
    if not edge_grade.is_edge_station(station):
        raise HTTPException(404, f"{station!r} is not a registered edge station")
    if not SCENARIO.exists():
        raise HTTPException(503, "no scenario file; generate one with "
                                 "python -m scripts.make_wokwi_scenario")
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "a replay is already running")
        _state["running"] = True

    # A CLEAN SHEET, NOT A SECOND LAYER.
    #
    # Replaying without clearing draws the same frames twice with different
    # values, and the chart appears to double back on itself. The learned
    # scale goes too: a residual history built against the last run does not
    # describe this one.
    removed = store.forget(station)
    edge_grade.reset(station)

    asyncio.create_task(_run(station, rate, limit))
    return {"started": True, "station": station, "cleared_readings": removed,
            "rate_per_second": rate,
            "note": "Replays the Wokwi scenario through /api/ingest. Not "
                    "evidence the firmware runs -- it exercises everything "
                    "downstream of the sensor and nothing upstream of it."}


@router.post("/api/edge/replay/stop")
async def stop() -> dict:
    _state["running"] = False
    return {"stopped": True, "sent": _state["sent"]}


@router.get("/api/edge/replay/status")
def status() -> dict:
    return {**_state, "scenario": str(SCENARIO),
            "scenario_present": SCENARIO.exists()}
