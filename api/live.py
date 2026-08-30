"""The live path: readings arrive, get judged, and appear on screen.

WHY THIS EXISTS

PS26073 asks for detection "in real time" on AWS data streams, and real-time
capability is 15% of the evaluation. Until now the dashboard replayed a file:
every grade was computed by a build step and shipped as JSON. That is a
recording of a detector, not a detector.

Nothing about the data has to be real for the PIPELINE to be real. A reading
posted to /api/ingest is screened against the WMO rails, judged, and pushed to
every open socket in the same request. Whether it came from a simulated station
or from an ESP32 over MQTT changes the source and nothing else -- which is the
point, because the ESP32 will post to this same endpoint.

WHAT THE FEEDER IS, AND IS NOT

/api/live/replay walks the simulated network and posts its readings through the
real path at a chosen rate. It is a STAND-IN FOR THE HARDWARE, not a simulation
of the detector: every reading it sends is screened by the same code, in the
same process, as one arriving from a mast. When the ESP32 exists it replaces the
feeder, and nothing downstream changes.

The socket is broadcast-only. A browser that misses a message has missed a
moment, not a record -- the archive is what /api/map/* is for, and mixing the
two would give a live feed the job of being a database.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

router = APIRouter()


@dataclass
class Hub:
    """Every open socket, and the last few events for someone who just joined.

    The backlog is deliberately tiny. A viewer opening the page mid-stream
    should see that something is happening rather than an empty panel, and
    should not be handed a history the archive already holds.
    """

    sockets: set[WebSocket] = field(default_factory=set)
    recent: list[dict] = field(default_factory=list)
    sent: int = 0
    BACKLOG: int = 20

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.sockets.add(ws)
        await ws.send_text(json.dumps({
            "type": "hello", "backlog": self.recent,
            "listeners": len(self.sockets),
        }))

    def leave(self, ws: WebSocket) -> None:
        self.sockets.discard(ws)

    async def publish(self, event: dict) -> None:
        self.recent.append(event)
        del self.recent[:-self.BACKLOG]
        self.sent += 1
        if not self.sockets:
            return
        payload = json.dumps(event)
        # Iterate a COPY: a socket that fails is discarded here, and mutating
        # the set being iterated is how a broadcast loop crashes on exactly the
        # disconnection it is trying to handle.
        for ws in list(self.sockets):
            try:
                await ws.send_text(payload)
            except Exception:
                self.sockets.discard(ws)


HUB = Hub()

_feeder: asyncio.Task | None = None
_state: dict = {"running": False, "station": None, "sent": 0, "rate": 0.0}


@router.websocket("/api/live")
async def live(ws: WebSocket) -> None:
    await HUB.join(ws)
    try:
        while True:
            # The client never sends anything. This read exists so a disconnect
            # is noticed promptly rather than at the next broadcast.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        HUB.leave(ws)


def _sim() -> dict:
    p = Path(__file__).resolve().parent.parent / "dashboard" / "sim_map.json"
    if not p.exists():
        raise HTTPException(503, "sim_map.json has not been generated. Run: "
                                 "python -m simulate.faults_and_export")
    return json.loads(p.read_text(encoding="utf-8"))


def _decode(sim: dict, s: dict, frame: int):
    """Quantised bytes back into units. Byte 0 is the missing marker, so the
    usable band is 1..255 across the channel's fixed range."""
    out = []
    for key, ch in (("vt", "temp"), ("vh", "rh"), ("vp", "pres")):
        raw = base64.b64decode(s[key])
        if frame >= len(raw) or raw[frame] == 0:
            out.append(None)
            continue
        lo, hi = sim["range"][ch]
        out.append(lo + ((raw[frame] - 1) / 254.0) * (hi - lo))
    return tuple(out)


# THE LIVE STATION: one node, standing where the ESP32 will stand.
#
# Streaming an existing simulated station was the wrong demo. It showed one of
# the 344 being replayed faster, which is the same recording at a different
# speed. The thing worth showing is a NEW station -- a device reporting into a
# network that does not yet know about it -- because that is what the finished
# system is: 344 stations on file and a box on a pole sending readings in.
#
# In the end there is no difference between them, and that is the point. It
# reports temperature, pressure and humidity like every other station, it is
# graded against its neighbours like every other station, and the only thing
# that makes it special is that its numbers arrive instead of being loaded.
#
# Gandhinagar: six simulated neighbours within 120 km and fourteen within 250.
# That is not decoration -- neighbour differencing needs three inside 250 km, so
# a live station in the middle of nowhere could be watched forever and never
# judged. The nearest are the simulated GANDHINAGAR at 8 km and AHMADABAD at
# 17 km, which is what a new AWS beside existing ones actually looks like.
LIVE_STATION = {
    "id": "ESP32-01",
    "name": "SKYGUARD ESP32",
    "state": "Gujarat",
    "lat": 23.2156,
    "lon": 72.6369,
    "elev": 81,
}

# What is wrong with the node, if anything. Set from the dashboard so a fault
# can be introduced while somebody is watching, which is the only way to show a
# detector detecting rather than to assert that it does.
_fault: dict = {"kind": "none", "since": 0, "amplitude": 0.0}

FAULTS = ("none", "drift", "stuck", "spike", "offset", "dropout")

# ONE READING, ONE FRAME.
#
# This was 60, on the theory that a slow frame advance kept the diurnal cycle
# still so a drift could be seen against it. That reasoning was wrong. The
# grader compares the reading with the NEIGHBOURS' estimate at the same frame,
# so the daily cycle is in both terms and cancels in the residual -- the test
# that seemed to show otherwise was measuring raw temperature, not the
# residual, and measured the sunrise.
#
# What 60 did cost was real: the node covered thirty minutes of record every
# thirty seconds, so crossing the month took twelve HOURS and the pen barely
# left the first day of a thirty-day axis. At one frame per reading the same
# sweep takes twelve minutes, which is what a recorder looks like.
FRAMES_PER_READING = 1

# What one reading represents: a frame is thirty simulated minutes, and one
# reading now covers one. The server needs this to judge rate of change, and
# without it, it times the gap with a wall clock and measures the demo's speed
# rather than the weather's.
SIM_MINUTES_PER_READING = 30.0


def _neighbours(sim: dict, lat: float, lon: float, k: int = 6):
    """The k nearest simulated stations, with inverse-distance weights."""
    import math
    d = []
    for i, st in enumerate(sim["stations"]):
        dx = (st["lon"] - lon) * math.cos(math.radians(lat)) * 111.0
        dy = (st["lat"] - lat) * 111.0
        d.append((dx * dx + dy * dy, i))
    d.sort()
    picked = d[:k]
    w = [1.0 / max(dist, 1.0) for dist, _ in picked]
    tot = sum(w) or 1.0
    return [(i, wi / tot) for (_, i), wi in zip(picked, w)]


def _expected(sim: dict, frame: int, nbrs) -> tuple[float, float, float]:
    """What the NEIGHBOURS say this place should be reading, right now.

    This is the reference the node is judged against, and it must not contain
    anything the node contributed -- not its noise, and certainly not its
    fault. The first version compared the reading with the value the reading
    was generated from, so the residual was identically zero, the baseline
    spread was zero, and the first drift scored z = 789,154. A detector whose
    healthy residual is exactly 0.00 is not measuring anything.
    """
    out = []
    for key, ch in (("vt", "temp"), ("vh", "rh"), ("vp", "pres")):
        acc = 0.0
        wsum = 0.0
        for i, w in nbrs:
            raw = base64.b64decode(sim["stations"][i][key])
            if frame >= len(raw) or raw[frame] == 0:
                continue
            lo, hi = sim["range"][ch]
            acc += w * (lo + ((raw[frame] - 1) / 254.0) * (hi - lo))
            wsum += w
        out.append(acc / wsum if wsum else 0.0)
    return tuple(out)  # type: ignore[return-value]


# What this node's own sensors add on top of the neighbours' estimate. A real
# station is never exactly the interpolation of its neighbours, and the spread
# of that difference is what the grader learns as normal.
SENSOR_NOISE = {"temp": 0.25, "rh": 1.2, "pres": 0.15}


def _reading(expected: tuple[float, float, float]) -> tuple[float, float, float]:
    """The node's honest reading: the neighbours' estimate plus its own noise."""
    import random
    return (expected[0] + random.gauss(0, SENSOR_NOISE["temp"]),
            expected[1] + random.gauss(0, SENSOR_NOISE["rh"]),
            expected[2] + random.gauss(0, SENSOR_NOISE["pres"]))


def _apply_fault(vals: tuple[float, float, float], n: int):
    """Break the node, the way the injector breaks a simulated one.

    Same fault vocabulary as simulate/faults_and_export.py on purpose: a demo
    that showed a fault this system was never tested against would be theatre.
    """
    import random
    temp, rh, pres = vals
    kind = _fault["kind"]
    if kind == "none":
        return temp, rh, pres, False
    elapsed = max(n - _fault["since"], 0)
    if kind == "drift":
        # 0.02 C per reading: invisible at any single moment, unmistakable
        # after a few minutes. This is the fault the whole project exists for.
        temp += 0.02 * elapsed
    elif kind == "stuck":
        temp, rh, pres = _fault.setdefault("held", (temp, rh, pres))
    elif kind == "spike":
        if random.random() < 0.25:
            temp += random.choice([-1, 1]) * random.uniform(6, 14)
    elif kind == "offset":
        temp += 4.5
    elif kind == "dropout":
        return temp, rh, pres, True
    return temp, rh, pres, False


# GRADING THE NODE AGAINST ITS NEIGHBOURS, ONLINE.
#
# The WMO rails catch gross errors and nothing else. Measured on this node:
#
#     none    passed        drift   PASSED
#     spike   temp_rate     stuck   PASSED
#                           offset  PASSED
#
# Drift, stuck and offset are all physically plausible readings. A range check
# cannot see them, which is the entire reason this project exists -- and a demo
# where the map never reacts to a drifting sensor would demonstrate the
# opposite of the claim.
#
# So the node is differenced against its neighbours as each reading arrives,
# which is the same method the map uses, run one reading at a time instead of
# over a month. The baseline is the first BASELINE_N readings: a deployed node
# would use its own history the same way, and a station that has just been
# switched on genuinely cannot be judged yet.
BASELINE_N = 40
_resid: list[float] = []

# The node's standing right now, so the maintenance board can show it as an
# item like any other. A live station that faults and appears nowhere a
# technician looks is a station nobody will be sent to.
# WHICH FRAME THE NODE IS REPORTING FOR.
#
# It used to be the node's own counter, advancing independently of the
# dashboard's clock -- so the map showed 344 stations at one moment of the
# record and the node at another, nearly a month apart. Same axis, two
# positions on it, which is the worst kind of mismatch because both look
# right on their own.
#
# The page owns the clock and the node follows it. Set through /api/live/seek
# as the slider moves; None means nobody has said, and the node falls back to
# its own counter so it still reports on a page nobody is watching.
_target_frame: list[int | None] = [None]
_last_frame = [0]

_standing: dict = {"band": "learning", "z": 0.0, "since": None,
                   "since_frame": None, "readings": 0,
                   "expected": None, "last": None}


def _grade_live(reported: float, expected: float) -> tuple[float, str]:
    """|z| of this reading's residual, and the band it falls in.

    Same 6 and 8 sigma as simulate/faults_and_export.py, deliberately: a demo
    that used friendlier thresholds than the measured pipeline would be
    showing a detector nobody evaluated.
    """
    r = reported - expected
    if len(_resid) < BASELINE_N:
        _resid.append(r)
        return 0.0, "learning"
    import statistics
    med = statistics.median(_resid)
    mad = statistics.median([abs(x - med) for x in _resid]) or 1e-6
    sigma = 1.4826 * mad
    z = abs(r - med) / max(sigma, 1e-6)
    return z, "fault" if z >= 8 else "watch" if z >= 6 else "ok"


async def _run(per_second: float, limit: int) -> None:
    """The node, reporting.

    One station posting through /api/ingest at a steady cadence, which is what
    an ESP32 on a pole does. The readings are synthesised from its neighbours
    so they belong to the place it stands in, and whatever fault is currently
    set is applied on the way out -- to the READING, never to the verdict.
    """
    from api.ingest import Reading, ingest, physics_screen

    sim = _sim()
    nbrs = _neighbours(sim, LIVE_STATION["lat"], LIVE_STATION["lon"])
    n_frames = sim.get("n_fields") or 1
    delay = 1.0 / max(per_second, 0.05)
    sent = 0
    try:
        while _state["running"] and sent < limit:
            # HOW FAST THE WEATHER MOVES.
            #
            # This was one frame per reading, and a frame is thirty simulated
            # minutes: at two readings a second that is a day of weather every
            # twenty seconds, and the station's temperature swings ten degrees
            # while you watch. A drift of 0.02 C per reading is invisible
            # underneath that -- the first test of the fault button measured
            # the diurnal cycle and called it a result.
            #
            # One frame per FRAMES_PER_READING readings instead, so the
            # background is nearly still and a fault is the thing that moves.
            frame = (_target_frame[0] if _target_frame[0] is not None
                     else (sent // FRAMES_PER_READING) % n_frames)
            frame = max(0, min(frame, n_frames - 1))
            exp = _expected(sim, frame, nbrs)
            # The neighbours' estimate, which the node never sees, and the
            # node's own reading, which is that estimate plus its own noise and
            # then whatever is wrong with it.
            temp, rh, pres, dropped = _apply_fault(_reading(exp), sent)
            sent += 1
            _state["sent"] = sent
            if dropped:
                # A dead node sends nothing. Publishing "nothing arrived" is
                # the only way a viewer can tell silence from a paused feed.
                await HUB.publish({"type": "silence", "t": time.time(),
                                   "station": LIVE_STATION["name"],
                                   "fault": _fault["kind"]})
                await asyncio.sleep(delay)
                continue
            try:
                # dt_min IS NOT OPTIONAL HERE, and leaving it out was a real
                # bug: the server falls back to wall-clock, and this node posts
                # several readings a second while REPRESENTING half a simulated
                # minute each. The rate check then allowed a change of
                # 3.0 C/min x 0.0033 min = 0.01 C, against sensor noise of
                # 0.25 C, so every healthy reading was flagged temp_rate. The
                # check was right and the feeder was lying to it.
                #
                # A real ESP32 reports every fifteen minutes and would say so.
                # Compressing time for a demo means saying which time.
                #
                # The node also declares what its OWN screen found. That is the
                # edge tier in miniature: the server compares its conclusion
                # with the node's, and edge_screen_disagreement means the two
                # saw different things -- which was firing constantly for the
                # same reason.
                # WHICH FRAME OF THE RECORD THIS READING IS FOR.
                #
                # The node's readings are synthesised at fifteen-minute steps
                # exactly like every simulated station's, so they belong on the
                # same axis. Publishing the frame is what lets the dashboard
                # draw this station in the same chart as the other 344 instead
                # of on a wall clock beside them.
                _last_frame[0] = frame
                node_flags = physics_screen(temp, rh, pres)
                ingest(Reading(station=LIVE_STATION["name"], temp=temp,
                               rh=rh, pres=pres, seq=sent,
                               dt_min=SIM_MINUTES_PER_READING,
                               flags=node_flags, frame=frame))
                z, band = _grade_live(temp, exp[0])
                if band != _standing["band"]:
                    # Date the condition from where it STARTED, not from where
                    # we became confident about it -- the same rule the alert
                    # ledger uses for the simulated network. Kept in BOTH
                    # clocks: wall time for the board, record frames for the
                    # ledger, because those two surfaces measure in different
                    # units and each should be given its own rather than
                    # converting one into the other on screen.
                    live = band in ("watch", "fault")
                    _standing["since"] = time.time() if live else None
                    _standing["since_frame"] = frame if live else None
                _standing.update(band=band, z=z, readings=sent,
                                 expected=exp[0], last=temp)
                open_frames = (frame - _standing["since_frame"]
                               if _standing["since_frame"] is not None else None)
                await HUB.publish({
                    "type": "grade", "t": time.time(), "frame": frame,
                    "station": LIVE_STATION["name"],
                    "z": round(z, 2), "band": band,
                    "open_frames": open_frames,
                    "expected": round(exp[0], 2),
                    "baseline": min(len(_resid), BASELINE_N),
                    "baseline_needed": BASELINE_N,
                })
            except HTTPException as e:
                await HUB.publish({"type": "rejected", "t": time.time(),
                                   "station": LIVE_STATION["name"],
                                   "why": str(e.detail)})
            except Exception as e:
                await HUB.publish({"type": "rejected", "t": time.time(),
                                   "station": LIVE_STATION["name"],
                                   "why": f"{type(e).__name__}: {e}"})
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        raise
    finally:
        _state["running"] = False
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await HUB.publish({"type": "feeder", "running": False, "sent": sent})


@router.get("/api/live/station")
def live_station() -> dict:
    """Where the node stands, and what is currently wrong with it."""
    sim = _sim()
    nbrs = _neighbours(sim, LIVE_STATION["lat"], LIVE_STATION["lon"])
    return {
        **LIVE_STATION,
        "fault": dict(_fault),
        "faults_available": list(FAULTS),
        "neighbours": [sim["stations"][i]["name"] for i, _ in nbrs],
        "note": "A station like any other. It reports temperature, pressure "
                "and humidity, it is graded against its neighbours, and the "
                "only difference is that its readings arrive rather than being "
                "loaded from a file.",
    }


@router.post("/api/live/fault")
async def set_fault(kind: str = Query("none")) -> dict:
    """Break the node, or repair it, while somebody is watching.

    The fault vocabulary is the injector's, not a new one invented for the
    demo: showing a fault this system was never tested against would be
    theatre. It changes the READING only -- nothing downstream is told, which
    is the entire point of pressing it.
    """
    if kind not in FAULTS:
        raise HTTPException(400, f"unknown fault {kind!r}; have {', '.join(FAULTS)}")
    _fault.update(kind=kind, since=_state.get("sent", 0))
    _fault.pop("held", None)
    # Changing what is wrong with the node starts its standing again. This
    # belongs HERE and was briefly in _apply_fault, which runs once per
    # reading -- so the band was reset to "learning" every reading, the band
    # always "changed", and the clock on how long a fault had been open
    # restarted continuously. It read 0.0 seconds after twenty.
    _standing.update(band="learning", z=0.0, since=None, since_frame=None)
    if kind == "none":
        # Repairing the node clears the learned baseline. Keeping residuals
        # gathered while it was broken would teach it that broken is normal --
        # the self-masking failure, reproduced by hand.
        _resid.clear()
    await HUB.publish({"type": "fault", "kind": kind,
                       "station": LIVE_STATION["name"]})
    return {"fault": kind, "since_reading": _fault["since"],
            "note": "Applied to the reading. The detector is not told."}


async def start_node(per_second: float = 2.0, limit: int = 1_000_000) -> dict:
    """Start the node. Plain function, callable from anywhere.

    The endpoint below is a thin wrapper over this. Calling the ENDPOINT
    directly from application startup looked like it worked and did not: a
    FastAPI handler's defaults are Query objects, not values, so `limit` was a
    Query instance, `sent < limit` raised inside the task, and the exception
    died with the task -- no traceback, no log line, just a node that never
    reported and a startup that claimed success.
    """
    global _feeder
    if _state["running"]:
        raise HTTPException(409, "the node is already reporting; stop it first")
    _state.update(running=True, station=LIVE_STATION["id"], sent=0, rate=per_second)
    _resid.clear()
    _feeder = asyncio.create_task(_run(per_second, limit))
    await HUB.publish({"type": "feeder", "running": True, "rate": per_second})
    return {"started": True, "per_second": per_second,
            "station": LIVE_STATION, "fault": _fault["kind"],
            "note": "One node reporting through the real ingest path. An ESP32 "
                    "posting to this same endpoint replaces it entirely."}


@router.post("/api/live/replay")
async def start_replay(
    per_second: float = Query(2.0, gt=0, le=50, description="readings/second"),
    limit: int = Query(100_000, gt=0, le=1_000_000),
) -> dict:
    """Start the node."""
    return await start_node(per_second, limit)


@router.post("/api/live/stop")
async def stop_replay() -> dict:
    global _feeder
    _state["running"] = False
    if _feeder is not None:
        _feeder.cancel()
        # asyncio.CancelledError inherits from BaseException, NOT Exception, so
        # suppress(Exception) does not catch it and awaiting a task you just
        # cancelled re-raises straight through the endpoint. /api/live/stop
        # returned 500 while stopping the feed perfectly well.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _feeder
        _feeder = None
    return {"stopped": True, "sent": _state["sent"]}


@router.get("/api/live/status")
def status() -> dict:
    return {
        "listeners": len(HUB.sockets),
        "published": HUB.sent,
        "feeder": dict(_state),
        "socket": "/api/live",
        "note": "Broadcast only. A missed message is a missed moment, not a "
                "lost record; the archive is /api/map/*.",
    }


@router.get("/api/live/standing")
def standing() -> dict:
    """The node's current verdict, for anything that lists work to be done.

    Deliberately the same shape of answer the board gives a simulated station:
    a band, how far it is from its neighbours, and how long it has been that
    way. The live node is a station like any other and should appear in the
    queue like any other -- a device that faults and shows up nowhere a
    technician looks is a device nobody will be sent to.
    """
    open_for = (time.time() - _standing["since"]) if _standing["since"] else None
    return {
        "station": LIVE_STATION,
        "band": _standing["band"],
        "z": round(_standing["z"], 2),
        "readings": _standing["readings"],
        "expected": _standing["expected"],
        "last": _standing["last"],
        "open_seconds": round(open_for, 1) if open_for else None,
        "reporting": _state["running"],
        # Which moment of the record the node is reporting for, and whether the
        # page told it. Exposed because "is the live station on the same date
        # as the map" is a question worth being able to answer directly.
        "frame": _last_frame[0],
        "frame_follows_page": _target_frame[0] is not None,
        "injected_fault": _fault["kind"],
        "note": "Graded by neighbour differencing against six simulated "
                "stations within 120 km, at the same 6 and 8 sigma bands the "
                "map uses.",
    }


@router.post("/api/live/seek")
async def seek(frame: int = Query(..., ge=0)) -> dict:
    """Tell the node which moment of the record the page is looking at.

    The dashboard owns the clock -- it has the slider -- so the node follows it
    rather than keeping a second one. Without this the two drifted apart and
    the map showed the network at one date and the live station at another,
    which is the worst kind of mismatch: each is internally consistent and only
    the pair is wrong.
    """
    _target_frame[0] = frame
    return {"frame": frame}


@router.get("/api/live/series")
def series() -> dict:
    """The node's whole record, the same thirty days every other station has.

    WHY THIS EXISTS

    The node began with no history and filled frames in as it reported, so its
    chart was a stub on a thirty-day axis while its neighbours were complete.
    That is not what a station looks like: a device on a pole has been reading
    since it was installed, and the interesting question is whether the last
    few readings depart from that history -- which cannot be asked of a chart
    that has none.

    So it is given the same record as everyone else, synthesised the same way
    its live readings are: interpolated from its six neighbours, plus its own
    sensor noise. Nothing here is injected. The live feed then overwrites
    individual frames as it reports them, which is where a fault appears.

    Deterministic on purpose -- a fixed seed -- so a reload does not silently
    redraw the station's past.
    """
    import random

    sim = _sim()
    nbrs = _neighbours(sim, LIVE_STATION["lat"], LIVE_STATION["lon"])
    n = sim.get("n_fields") or 1
    rng = random.Random(20260725)
    out: dict[str, list[float]] = {"temp": [], "rh": [], "pres": []}
    for f in range(n):
        exp = _expected(sim, f, nbrs)
        for (ch, v) in zip(("temp", "rh", "pres"), exp):
            out[ch].append(round(v + rng.gauss(0, SENSOR_NOISE[ch]), 2))
    return {
        "station": LIVE_STATION,
        "n_fields": n,
        "field_every": sim.get("field_every", 1),
        "t0": sim.get("t0"),
        "values": out,
        "note": "Its history, interpolated from six neighbours within 120 km "
                "plus sensor noise. No fault is injected here -- injected "
                "faults appear in the frames the node reports live.",
    }
