"""Live ingest from a station node, and the baseline it is given to work with.

WHY THIS EXISTS SEPARATELY FROM THE REPLAY ENGINE

Everything else in this API replays a precomputed CSV: it answers "what did the
pipeline conclude about this dataset". That is the right shape for a console
demo and the wrong shape for a station, which has no dataset -- it has one
reading, now, and a few hundred bytes of state.

So this router is the other half: the edge tier posts readings here, and the
server keeps the small amount of state a real deployment would keep in Redis.
It is deliberately in-memory. Wiring a database in before the protocol is
settled would be building the production topology first, which the blueprint
argues against at some length.

THE DIVISION OF LABOUR, AND WHY IT IS THIS ONE

    station   physics screen + residual against a FROZEN baseline + P-square
              scale. O(1) state, no history, no ML runtime.
    server    everything needing neighbours: neighbour differencing, the
              learned stage, conformal p-values, signature naming.

The station cannot do the neighbour comparison -- it has no neighbours, it has
a radio. That is not a limitation to engineer around; it is the reason the
server tier exists.

WHY THE STATION IS SENT ITS BASELINE INSTEAD OF FITTING ONE

Measured, in evaluation/run_edge_approx.py: a baseline fitted on a window that
CONTAINS a 0.02 K/day drift absorbs essentially all of it. Fraction of the drift
still visible in the residual afterwards:

    OLS            0.035
    batch Huber    0.008
    online Huber   0.064

All three are near zero, and the robust ones are no better -- batch Huber is the
worst of them. Robustness does not protect against a fault that grows slowly
inside your own training window, because a slow drift never looks like an
outlier. A station that refits on its own data therefore goes blind to exactly
the failure this project exists to catch, and reports healthy while it does it.

So the server fits on an approved reference window and pushes nine coefficients;
the station uses them and never refits. That is also why the fit is a harmonic
one -- nine floats is a baseline a node can hold.
"""
from __future__ import annotations
import math
import os
import time
from collections import deque
from threading import Lock
from typing import Deque

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

MAX_PER_STATION = int(os.environ.get("SKYGUARD_INGEST_BUFFER", "512"))

# Hard physical rails. A reading outside these is not an anomaly to be scored,
# it is a broken sensor or a broken frame, and it must never reach the detector
# -- a -999 sentinel averaged into a neighbour median corrupts every station
# around it. Same limits as evaluation/run_full.RAILS.
# RH's upper rail is 105, not 100, on purpose. Real capacitive RH probes read
# slightly above saturation in fog and rain -- 100.5 is a healthy sensor, not a
# broken one -- and rejecting those readings would throw away exactly the
# conditions the network exists to record. 100-105 is flagged and clamped;
# above 105 is a fault.
# THE RAILS ARE NOW WMO-No. 8's, NOT OURS.
#
# Annex 1.A of Volume I (2024) states the measuring range for each variable, and
# a reading outside it is not an anomaly to be scored -- it is outside what the
# instrument is defined to report at all. Taking the ranges from the standard
# replaces three numbers we chose with three anyone can check, and the two
# places this project deliberately departs from it are now named rather than
# silently baked in.
#
# What changed, and why each one was wrong before:
#
#   temp   was -40, WMO says -80. Ours was a CLIMATOLOGY limit wearing an
#          instrument rail's clothes: -40 is generous for India but India's
#          record low is about -45 at Dras, so the old rail would have rejected
#          a real reading as a broken frame. Plausibility for a given site is a
#          different check from what the sensor can report, and conflating them
#          throws away good data.
#   pres   was 1100, WMO says 1080. Ours was simply looser than the standard for
#          no reason anyone had written down.
#   rh     was 105 and STAYS 105. This is a deliberate, documented departure:
#          the annex gives the REPORTED range as 0-100%, but real capacitive
#          probes read slightly above saturation in fog and rain, and 100.5 is a
#          healthy sensor rather than a broken one. Rejecting those would throw
#          away exactly the conditions the network exists to record. 100-105 is
#          flagged and clamped; above 105 is a fault.
from physics.wmo_limits import WMO_ANNEX_1A

RAILS = {
    "temp": WMO_ANNEX_1A["temp"]["range"],
    "rh": (WMO_ANNEX_1A["rh"]["range"][0], 105.0),   # see the note above
    "pres": WMO_ANNEX_1A["pres"]["range"],
}
RH_SATURATED = WMO_ANNEX_1A["rh"]["range"][1]   # 100.0, from the annex

# Largest believable change per minute. Generous on purpose: this rejects
# transmission corruption, not weather.
RATE_LIMIT = {"temp": 3.0, "rh": 20.0, "pres": 2.0}


class Reading(BaseModel):
    """One observation as a node reports it.

    `flags` and `seq` are what make this an edge tier rather than a sensor: the
    node states what it already checked and how many samples it has seen, so the
    server can tell a quiet station from a dead one.
    """
    station: str = Field(min_length=1, max_length=64)
    temp: float
    rh: float
    pres: float
    seq: int = 0
    flags: list[str] = []
    dt_min: float | None = None        # minutes since the node's previous sample
    # Which frame of the shared record this reading is for, when the sender
    # knows it. A real ESP32 would not, and would leave it unset.
    frame: int | None = None
    # Which traverse of the record this belongs to. A node that keeps reporting
    # comes back to the start; without this the dashboard cannot tell the tail
    # of one pass from the head of the next.
    pass_no: int | None = None
    residual: float | None = None      # against the pushed baseline, if it has one
    scale: float | None = None         # node's P-square sigma estimate
    fw: str = ""


_buf: dict[str, Deque[dict]] = {}
_lock = Lock()


def physics_screen(temp: float, rh: float, pres: float) -> list[str]:
    """The same checks the firmware runs, re-run server-side.

    Deliberately duplicated rather than trusted. A node's flags are a claim
    about a node, and a node with a corrupted screen is one of the faults we are
    supposed to catch -- so the server verifies rather than believes, and a
    disagreement between the two is itself a signal.
    """
    out = []
    for var, v in (("temp", temp), ("rh", rh), ("pres", pres)):
        lo, hi = RAILS[var]
        if not math.isfinite(v):
            out.append(var + "_nonfinite")
        elif not (lo <= v <= hi):
            out.append(var + "_out_of_range")

    # There was a "dew point cannot exceed air temperature" check here. It was
    # removed because it is UNREACHABLE, which was proven rather than argued:
    # swept over the whole valid rail box, max(Td - T) is -0.039 K. Magnus gives
    # Td <= T identically for every RH <= 100, so the check can only fire on
    # floating-point noise. A screen that cannot fail tests nothing and costs a
    # log call per reading on a battery-powered node.
    #
    # Supersaturation is the check that actually does work here.
    if math.isfinite(rh) and RH_SATURATED < rh <= RAILS["rh"][1]:
        out.append("rh_supersaturated")
    return out


@router.post("/api/ingest")
def ingest(r: Reading) -> dict:
    """Accept one reading from a node."""
    server_flags = physics_screen(r.temp, r.rh, r.pres)
    accepted = not any(f.endswith("_out_of_range") or f.endswith("_nonfinite")
                       for f in server_flags)

    with _lock:
        q = _buf.setdefault(r.station, deque(maxlen=MAX_PER_STATION))
        prev = q[-1] if q else None
        # The rate check needs the previous sample, which the node also has --
        # but the node's clock is not trusted, so the server uses its own
        # arrival times.
        # dt comes from the NODE, not from arrival time.
        #
        # The rate check asks how fast the air changed, which is a question in
        # the sensor's time frame. Using arrival time instead means a node that
        # buffers through a link outage and flushes ten readings in one second
        # trips every rate check on the way back up -- store-and-forward would
        # look like catastrophic sensor failure. Arrival time is only the
        # fallback for a node that does not report dt, and it is clamped so a
        # bad clock cannot disable the check entirely.
        if prev is not None and accepted:
            if r.dt_min is not None and math.isfinite(r.dt_min) and r.dt_min > 0:
                dt_min = min(r.dt_min, 60.0)
            else:
                dt_min = max((time.time() - prev["t"]) / 60.0, 1e-3)
            for var in ("temp", "rh", "pres"):
                if abs(getattr(r, var) - prev[var]) > RATE_LIMIT[var] * dt_min:
                    server_flags.append(var + "_rate")

        # Did the node and the server reach the same conclusion?
        if set(r.flags) != set(server_flags):
            server_flags.append("edge_screen_disagreement")

        rec = {"t": time.time(), "station": r.station, "seq": r.seq,
               "temp": r.temp, "rh": r.rh, "pres": r.pres,
               "node_flags": list(r.flags), "server_flags": server_flags,
               "residual": r.residual, "scale": r.scale, "fw": r.fw,
               "dt_min": r.dt_min,
               "accepted": accepted}
        q.append(rec)
        n = len(q)

    # DURABLE, not just recent. The deque above is a window for the dashboard;
    # this is the record. A fault is only visible against history, and history
    # that evaporates on restart is not history.
    from api import store
    store.record(rec)

    verdict = {"ok": True, "accepted": accepted, "station": r.station,
               "server_flags": server_flags, "buffered": n}

    # PUSH IT, so a reading arriving is something anyone watching can see.
    #
    # Fire-and-forget on purpose: a browser that has gone away, or a socket
    # that blocks, must not make an ingest fail. The reading is already
    # recorded by the time this runs, and losing the broadcast loses a moment
    # rather than a measurement.
    try:
        import asyncio

        from api.live import HUB
        loop = asyncio.get_running_loop()
        loop.create_task(HUB.publish({
            "type": "reading", "t": rec["t"], "station": r.station,
            "temp": r.temp, "rh": r.rh, "pres": r.pres,
            "node_flags": list(r.flags), "server_flags": server_flags,
            "accepted": accepted, "verdict": verdict, "source": "ingest",
            # Which step of the record this reading belongs to, when the sender
            # knows. The dashboard draws the live node on the same axis as
            # every other station, and an axis needs a position.
            "frame": r.frame,
            "pass": r.pass_no,
        }))
    except RuntimeError:
        # No running loop: called from a worker thread or a test. Nothing to
        # push to, and nothing to complain about.
        pass

    return verdict


@router.get("/api/ingest/recent")
def recent(station: str | None = None, limit: int = 50) -> dict:
    """What has arrived. This is how a node is verified end to end."""
    with _lock:
        if station is not None:
            rows = list(_buf.get(station, []))[-limit:]
        else:
            rows = [x for q in _buf.values() for x in q]
            rows = sorted(rows, key=lambda r: r["t"])[-limit:]
        stations = {k: len(v) for k, v in _buf.items()}
    return {"stations": stations, "n": len(rows), "readings": rows}


@router.get("/api/baseline/{station}")
def baseline(station: str) -> dict:
    """The frozen harmonic coefficients a node should use.

    Nine per variable: mean, two diurnal harmonics, two annual harmonics. The
    node evaluates them against local solar hour and day of year and subtracts.

    Served as zeros when no fitted model is loaded. A node given zeros still
    runs its physics screen, which is the tier's real job -- it degrades to less
    capable, not to broken.
    """
    coefs = None
    try:
        from api import main as _m
        eng = getattr(_m, "ENGINE", None)
        coefs = getattr(eng, "coefs", None) if eng is not None else None
    except Exception:
        coefs = None

    # coefs is {variable: {station_name: 9 floats}} -- the fit is PER STATION,
    # since the diurnal and annual shape of a coastal site is not that of a hill
    # station. A node is only ever sent its own.
    out = {}
    if coefs:
        for v in ("temp", "rh", "pres"):
            per_station = coefs.get(v) or {}
            if station in per_station:
                out[v] = [float(x) for x in per_station[station]]

    if not out:
        return {"station": station, "fitted": False,
                "note": "no fitted baseline for this station; "
                        "node runs physics screen only",
                "coefs": {v: [0.0] * 9 for v in ("temp", "rh", "pres")}}
    return {"station": station, "fitted": True, "coefs": out}


@router.get("/api/ingest/history")
def ingest_history(station: str | None = None, limit: int = 200) -> dict:
    """What a node has actually sent, from disk rather than from the buffer.

    /api/ingest/recent answers "what arrived in the last few minutes" out of a
    512-deep ring buffer. This answers "what has this station ever sent", which
    is a different question and the one that survives a restart.
    """
    from api import store
    limit = max(1, min(limit, 5000))
    return {"station": station, "readings": store.history(station, limit),
            "store": store.stats()}
