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


async def _run(station_id: str | None, per_second: float, limit: int) -> None:
    from api.ingest import Reading, ingest

    sim = _sim()
    stations = sim["stations"]
    if station_id:
        stations = [s for s in stations if s["id"] == station_id] or stations[:1]
    n_frames = sim.get("n_fields") or 1
    delay = 1.0 / max(per_second, 0.05)
    sent = 0
    try:
        while _state["running"] and sent < limit:
            s = stations[sent % len(stations)]
            frame = (sent // max(len(stations), 1)) % n_frames
            temp, rh, pres = _decode(sim, s, frame)
            sent += 1
            _state["sent"] = sent
            if temp is None or rh is None or pres is None:
                await asyncio.sleep(delay)
                continue
            try:
                verdict = ingest(Reading(station=s["name"], temp=temp,
                                         rh=rh, pres=pres))
            except HTTPException as e:
                verdict = {"error": str(e.detail)}
            except Exception as e:
                verdict = {"error": f"{type(e).__name__}: {e}"}
            # NO PUBLISH HERE. ingest() broadcasts every reading it accepts,
            # and this used to broadcast the same one again -- every station
            # arrived twice on the socket. The feeder is a stand-in for an
            # ESP32, and an ESP32 posting to /api/ingest gets exactly one
            # event; the stand-in must not be a better citizen than the thing
            # it stands in for.
            del verdict
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        raise
    finally:
        _state["running"] = False
        with contextlib.suppress(Exception):
            await HUB.publish({"type": "feeder", "running": False, "sent": sent})


@router.post("/api/live/replay")
async def start_replay(
    station: str | None = Query(None, description="one station id, or all"),
    per_second: float = Query(4.0, gt=0, le=50, description="readings/second"),
    limit: int = Query(5000, gt=0, le=200_000),
) -> dict:
    """Start the stand-in for the hardware."""
    global _feeder
    if _state["running"]:
        raise HTTPException(409, "a replay is already running; stop it first")
    _state.update(running=True, station=station, sent=0, rate=per_second)
    _feeder = asyncio.create_task(_run(station, per_second, limit))
    await HUB.publish({"type": "feeder", "running": True, "rate": per_second})
    return {"started": True, "per_second": per_second, "station": station,
            "note": "Simulated readings through the real ingest path. The "
                    "ESP32 will post to this same endpoint."}


@router.post("/api/live/stop")
async def stop_replay() -> dict:
    global _feeder
    _state["running"] = False
    if _feeder is not None:
        _feeder.cancel()
        with contextlib.suppress(Exception):
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
