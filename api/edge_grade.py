"""Grade a hardware node against its neighbours, as its readings arrive.

WHY THIS EXISTS SEPARATELY FROM api/live.py

`api/live.py` runs one node and grades it inside its own loop: it synthesises
the reading, so it already holds the neighbours' estimate when the grading
happens. A real board does not work that way. The ESP32 in Wokwi produces its
own readings from its own sensors and posts them; by the time the server sees
one, the only things it knows are the station name, the three values, and which
frame of the record the node says it is reporting for.

That is enough. The neighbours' estimate can be recomputed from the same
simulated field the map is drawn from, and the residual differenced exactly the
way the 344 stations are. So a physical node becomes a station like any other,
which is the entire claim the edge tier is making.

WHAT MAKES A NODE ELIGIBLE

A location. Neighbour differencing needs at least three stations inside 250 km,
so a node is registered here with coordinates before it can be judged; anything
posting to /api/ingest without an entry is still screened, stored and shown,
just not graded. That is the honest degradation: less capable, not broken.

WHERE THE NODES STAND, AND WHY NOT ON TOP OF ANYTHING

They are deliberately different stations in different places. The feeder is a
stand-in that generates its readings; the Wokwi node is a device that measures
them. Putting both at the same coordinates would make two rows that look like
one station reporting twice, and the first question anyone asks about the demo
is which of the two they are looking at.

The first placement put this node 1.6 km from the simulated PUNE, which is
realistic -- a new AWS does go up beside existing ones -- and unreadable: at
every zoom the two dots drew on top of each other, so the marker that is
supposed to say "this is the hardware" was hidden behind a station. Moved
north-west into the Ghats, where the nearest simulated station is 45 km away
and the neighbour support is actually better: eleven within 120 km against
Pune's ten.
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque

from api.neighbours import CLEAR_AFTER, RAISE_AFTER
from simulate.faults_and_export import FAULT_SIGMA, WATCH_SIGMA

# Stations that arrive through /api/ingest from outside, with somewhere to
# stand. `name` is matched against the `station` field a node posts.
EDGE_STATIONS: dict[str, dict] = {
    "WOKWI-ESP32": {
        "id": "WOKWI-ESP32",
        "name": "WOKWI-ESP32",
        "label": "SkyGuard node (Wokwi)",
        "state": "Maharashtra",
        "lat": 18.9400,
        "lon": 73.8500,
        "elev": 600,
    },
}

# How many readings a node reports before it can be judged. Same value and the
# same reason as the feeder's: a station that was switched on a minute ago has
# no spread to measure a residual against, and saying "learning" is the honest
# answer rather than grading against a scale built from four samples.
BASELINE_N = 40

# Residual history and standing, per station. A deque so a node that runs for a
# week does not grow without limit; the MAD only needs the recent record.
_hist: dict[str, deque[float]] = {}
_standing: dict[str, dict] = {}
# Episode state per station: how many bad steps in a row, how many clean ones,
# whether a case is open, and the frame it opened at.
_ep: dict[str, dict] = {}
# Why a station has no verdict, when readings ARE arriving. Without this the
# board simply shows nothing and the reason lives only in someone's head: a
# node on firmware that predates the `frame` field posts happily, is stored,
# is screened -- and cannot be placed on the record's axis, so it is never
# graded and never drawn. That looked exactly like a stuck node and took a
# serial log to diagnose.
_blocked: dict[str, dict] = {}
_lock = threading.Lock()


def is_edge_station(station: str) -> bool:
    return station in EDGE_STATIONS


def _expectation(station: str, frame: int):
    """What the neighbours say this place should be reading at this frame.

    Imported lazily: api.live imports api.ingest, and api.ingest calls this, so
    a module-level import would close the circle at startup.
    """
    from api.live import _expected, _neighbours, _sim

    st = EDGE_STATIONS[station]
    sim = _sim()
    n_frames = None
    try:
        import base64
        n_frames = len(base64.b64decode(sim["stations"][0]["vt"]))
    except Exception:
        n_frames = None
    if n_frames:
        frame = max(0, min(int(frame), n_frames - 1))

    nbrs = _neighbours(sim, st["lat"], st["lon"], k=6)
    return _expected(sim, frame, nbrs)


def observe(station: str, temp: float, rh: float, pres: float,
            frame: int | None) -> dict | None:
    """Difference one arriving reading against its neighbours and band it.

    Returns None when the station is not registered or the frame is unknown --
    a node that does not say which moment it is reporting for cannot be placed
    on the same axis as the record, and guessing a frame would compare its
    reading against the wrong weather.
    """
    if station not in EDGE_STATIONS:
        return None
    if frame is None:
        # A reading that does not say WHICH MOMENT it is for cannot be
        # differenced against what the neighbours were doing then, and guessing
        # would compare it against the wrong weather.
        with _lock:
            _blocked[station] = {
                "reason": "no_frame",
                "detail": "This node is not reporting which frame of the "
                          "record its readings are for, so they cannot be "
                          "placed on the same axis as the network or "
                          "differenced against its neighbours. Firmware "
                          "before skyguard-node-1.3.0 did not send one.",
                "t": time.time(),
            }
        return None

    with _lock:
        _blocked.pop(station, None)

    try:
        exp_t, exp_h, exp_p = _expectation(station, frame)
    except Exception:
        # No simulated field loaded, or it is being rebuilt. Grading is a
        # bonus on top of ingest; it must never be the reason a reading is
        # refused.
        return None

    r = temp - exp_t

    with _lock:
        hist = _hist.setdefault(station, deque(maxlen=2000))
        if len(hist) < BASELINE_N:
            hist.append(r)
            band, z = "learning", 0.0
        else:
            med = statistics.median(hist)
            mad = statistics.median([abs(x - med) for x in hist]) or 1e-6
            sigma = max(1.4826 * mad, 1e-6)
            z = abs(r - med) / sigma
            band = ("fault" if z >= FAULT_SIGMA
                    else "watch" if z >= WATCH_SIGMA else "ok")
            # THE BASELINE IS FROZEN AFTER THE LEARNING PHASE. IT DOES NOT
            # KEEP LEARNING WHILE THE NODE LOOKS HEALTHY.
            #
            # The first version here appended every reading that came back
            # "ok", which sounds careful and is the bug this project exists to
            # catch. A slow drift never looks like an outlier, so each drifting
            # reading was banded ok, folded into the scale, and moved the
            # median a little further along with it. Measured on the generated
            # scenario at 1.0 K per simulated day: the residual reached 2.48 K
            # against a clean-run sigma of 0.240 K -- ten sigma of real
            # excursion -- and scored z = 4.0, never crossing the band. The
            # detector had talked itself out of its own finding.
            #
            # Frozen, the same 2.48 K scores as it should. This is the node-side
            # form of the trailing, lagged window the network pipeline uses, and
            # it is here for the same reason.

        # THE EPISODE, WITH THE SAME HYSTERESIS AS EVERY OTHER ALERT.
        #
        # `band` above is this reading's own verdict. `case` is whether a
        # technician has a job, and those are not the same question: three bad
        # steps in a row to raise it, six clean ones to put it down. Harder to
        # close than to open, deliberately -- an intermittent fault that clears
        # for one reading has not been fixed.
        ep = _ep.setdefault(station, {"hot": 0, "cold": 0, "open": False,
                                      "from_frame": None, "since": None,
                                      "peak": "ok"})
        bad = band in ("watch", "fault")
        if not ep["open"]:
            ep["hot"] = ep["hot"] + 1 if bad else 0
            if ep["hot"] >= RAISE_AFTER:
                ep.update(open=True, cold=0, peak=band,
                          # Dated from where the run STARTED, not from where we
                          # became sure of it. The board's other rows do the
                          # same.
                          from_frame=frame - RAISE_AFTER + 1,
                          since=time.time())
        else:
            ep["cold"] = 0 if bad else ep["cold"] + 1
            if bad and band == "fault":
                ep["peak"] = "fault"
            if ep["cold"] >= CLEAR_AFTER:
                ep.update(open=False, hot=0, from_frame=None, since=None,
                          peak="ok")

        case = ep["peak"] if ep["open"] else "ok"
        if band == "learning":
            case = "learning"

        out = {
            "station": station,
            # What this reading alone says.
            "band": band,
            # What the technician is being told, after hysteresis. The board
            # reads this one; the map colours by it too, so the dot and the
            # work card cannot disagree.
            "case": case,
            "case_open": bool(ep["open"]),
            "open_frames": (None if not ep["open"] or ep["from_frame"] is None
                            else max(1, frame - ep["from_frame"] + 1)),
            "open_from_frame": ep["from_frame"],
            "z": round(z, 2),
            "residual": round(r, 3),
            "expected": {"temp": round(exp_t, 2), "rh": round(exp_h, 1),
                         "pres": round(exp_p, 2)},
            "reported": {"temp": round(temp, 2), "rh": round(rh, 1),
                         "pres": round(pres, 2)},
            "frame": frame,
            "readings": len(hist),
            # Wall time is kept because "is this node reporting" is a real
            # question, but it is NOT what the ledger measures a case in.
            "since": ep["since"],
            "since_frame": ep["from_frame"],
            "neighbours": 6,
        }
        _standing[station] = out
    return out


def _with_age(row: dict) -> dict:
    """The same verdict, plus how long it has been the verdict.

    The board sorts by how long a case has been open, so a standing without an
    age is a row it cannot place. Computed on read rather than stored, since
    the answer changes every second whether anyone asks or not.
    """
    out = dict(row)
    since = out.get("since")
    out["open_seconds"] = round(time.time() - since, 1) if since else None
    return out


def standing(station: str | None = None) -> dict:
    """The current verdict per edge station, for the board and the API."""
    with _lock:
        if station is not None:
            row = _standing.get(station)
            return _with_age(row) if row else {}
        return {k: _with_age(v) for k, v in _standing.items()}


def blocked(station: str | None = None) -> dict:
    """Why a station that IS reporting still has no verdict.

    A silent absence is the worst answer here: readings arrive, are screened
    and stored, and nothing appears -- which reads as a broken dashboard rather
    than as a node whose firmware cannot say when its readings are from.
    """
    with _lock:
        if station is not None:
            return dict(_blocked.get(station) or {})
        return {k: dict(v) for k, v in _blocked.items()}


def reset(station: str | None = None) -> None:
    """Forget the learned scale. Used when the record is rewound, since a
    residual history built against one traverse does not describe the next."""
    with _lock:
        if station is None:
            _hist.clear()
            _standing.clear()
            _ep.clear()
            _blocked.clear()
        else:
            _hist.pop(station, None)
            _standing.pop(station, None)
            _ep.pop(station, None)
            _blocked.pop(station, None)
