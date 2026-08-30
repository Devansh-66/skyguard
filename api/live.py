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
# Bhopal by default: central, and it has four simulated neighbours within
# 120 km. That last part is not decoration -- neighbour differencing needs
# three within 250 km, so a live station in the middle of nowhere could be
# watched and never judged.
LIVE_STATION = {
    "id": "ESP32-01",
    "name": "SKYGUARD ESP32",
    "state": "Madhya Pradesh",
    "lat": 23.26,
    "lon": 77.41,
    "elev": 523,
}

# What is wrong with the node, if anything. Set from the dashboard so a fault
# can be introduced while somebody is watching, which is the only way to show a
# detector detecting rather than to assert that it does.
_fault: dict = {"kind": "none", "since": 0, "amplitude": 0.0}

FAULTS = ("none", "drift", "stuck", "spike", "offset", "dropout")

# Readings per simulated half-hour. At two readings a second this advances the
# weather about one simulated day per two minutes -- slow enough that the
# baseline is nearly flat over the span of a demo, which is the only condition
# under which a slow drift is visible as a drift.
FRAMES_PER_READING = 60


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


def _synth(sim: dict, frame: int, nbrs, n: int) -> tuple[float, float, float]:
    """What this node would be reading, before anything goes wrong with it.

    Interpolated from its neighbours rather than invented: a station at Bhopal
    reporting Himalayan temperatures would be caught instantly by the very
    check this is meant to demonstrate, and for the wrong reason.
    """
    import random
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
        base = acc / wsum if wsum else 0.0
        # A real sensor is never exactly its neighbours' average.
        noise = {"temp": 0.25, "rh": 1.2, "pres": 0.15}[ch]
        out.append(base + random.gauss(0, noise))
    return tuple(out)  # type: ignore[return-value]


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


async def _run(per_second: float, limit: int) -> None:
    """The node, reporting.

    One station posting through /api/ingest at a steady cadence, which is what
    an ESP32 on a pole does. The readings are synthesised from its neighbours
    so they belong to the place it stands in, and whatever fault is currently
    set is applied on the way out -- to the READING, never to the verdict.
    """
    from api.ingest import Reading, ingest

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
            frame = (sent // FRAMES_PER_READING) % n_frames
            temp, rh, pres, dropped = _apply_fault(
                _synth(sim, frame, nbrs, sent), sent)
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
                ingest(Reading(station=LIVE_STATION["name"], temp=temp,
                               rh=rh, pres=pres, seq=sent))
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
    await HUB.publish({"type": "fault", "kind": kind,
                       "station": LIVE_STATION["name"]})
    return {"fault": kind, "since_reading": _fault["since"],
            "note": "Applied to the reading. The detector is not told."}


@router.post("/api/live/replay")
async def start_replay(
    per_second: float = Query(2.0, gt=0, le=50, description="readings/second"),
    limit: int = Query(100_000, gt=0, le=1_000_000),
) -> dict:
    """Start the node."""
    global _feeder
    if _state["running"]:
        raise HTTPException(409, "the node is already reporting; stop it first")
    _state.update(running=True, station=LIVE_STATION["id"], sent=0, rate=per_second)
    _feeder = asyncio.create_task(_run(per_second, limit))
    await HUB.publish({"type": "feeder", "running": True, "rate": per_second})
    return {"started": True, "per_second": per_second,
            "station": LIVE_STATION, "fault": _fault["kind"],
            "note": "One node reporting through the real ingest path. An ESP32 "
                    "posting to this same endpoint replaces it entirely."}


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
