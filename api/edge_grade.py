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

WHY THE WOKWI NODE IS AT PUNE AND THE FEEDER IS AT GANDHINAGAR

They are deliberately different stations in different places. The feeder is a
stand-in that generates its readings; the Wokwi node is a device that measures
them. Putting both at the same coordinates would make two rows that look like
one station reporting twice, and the first question anyone asks about the demo
is which of the two they are looking at. Pune also has the denser support --
ten simulated neighbours within 120 km against Gandhinagar's six.
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque

from simulate.faults_and_export import FAULT_SIGMA, WATCH_SIGMA

# Stations that arrive through /api/ingest from outside, with somewhere to
# stand. `name` is matched against the `station` field a node posts.
EDGE_STATIONS: dict[str, dict] = {
    "WOKWI-ESP32": {
        "id": "WOKWI-ESP32",
        "name": "WOKWI-ESP32",
        "label": "SkyGuard node (Wokwi)",
        "state": "Maharashtra",
        "lat": 18.5204,
        "lon": 73.8567,
        "elev": 560,
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
    if station not in EDGE_STATIONS or frame is None:
        return None

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

        prev = _standing.get(station)
        if prev is None or prev["band"] != band:
            since, since_frame = time.time(), frame
        else:
            since, since_frame = prev["since"], prev["since_frame"]

        out = {
            "station": station,
            "band": band,
            "z": round(z, 2),
            "residual": round(r, 3),
            "expected": {"temp": round(exp_t, 2), "rh": round(exp_h, 1),
                         "pres": round(exp_p, 2)},
            "reported": {"temp": round(temp, 2), "rh": round(rh, 1),
                         "pres": round(pres, 2)},
            "frame": frame,
            "readings": len(hist),
            "since": since,
            "since_frame": since_frame,
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


def reset(station: str | None = None) -> None:
    """Forget the learned scale. Used when the record is rewound, since a
    residual history built against one traverse does not describe the next."""
    with _lock:
        if station is None:
            _hist.clear()
            _standing.clear()
        else:
            _hist.pop(station, None)
            _standing.pop(station, None)
