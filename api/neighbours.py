"""Did the neighbouring stations move too?

WHY THIS FILE EXISTS

The board used to answer that question by asserting it. `simEvidence` set
`neighbours_agree: false` on every row, reasoning that a flagged station is by
definition one its neighbours disagree with. That is not quite circular -- the
grade really was produced by neighbour differencing -- but it collapses a
spectrum into a constant, and it means the context agent is handed its own
conclusion and can never veto. Its Shapley value on the simulated board was
structurally zero: three agents, one of which could not affect any outcome.

THE DISTINCTION THAT MAKES THIS A REAL MEASUREMENT

The grade encodes the RESIDUAL: this station minus the median of its
neighbours. Large residual means the station is out of step with the region.

That is not the same question as "did the region move?" A regional warm front
moves every station, including this one; the residual stays small, so nothing
is flagged. But when a station is flagged, the residual tells you nothing about
whether the region was ALSO doing something at the time -- and that is exactly
what separates "the instrument is drifting in still conditions" from "there is
weather here and this station is exaggerating it".

So the quantity here is the NEIGHBOUR MEDIAN ANOMALY -- what the surrounding
stations were doing relative to their own normal -- which is independent of the
residual and is not what the grade was computed from.

WHERE THE NUMBERS COME FROM

dashboard/sim_map.json, the same file the map draws. No new data, no
regeneration: the readings are already shipped, they were simply never read on
this side. Values are quantised to a byte over a per-channel range, so the
worst case here is a resolution of (hi-lo)/254 -- about 0.2 degrees for
temperature -- which is far below the effects being measured.
"""
from __future__ import annotations

import base64
import json
import math
import os
from functools import lru_cache

import numpy as np

CHANNELS = ("temp", "rh", "pres")
_KEY = {"temp": "vt", "rh": "vh", "pres": "vp"}

# The radius the network was graded at. Kept identical on purpose: a context
# agent that used a different neighbourhood than the grader would be answering
# about a different set of stations than the one that raised the flag.
RADIUS_KM = 250.0

# Below this many neighbours the median is not a median. The grader uses the
# same floor and declines to score a station that cannot reach it.
MIN_NEIGHBOURS = 3

# How far the region has to move, in its own quiet-period sigmas, before
# "the neighbours moved too" is a claim worth making.
REGION_SIGMA = 2.0

# And how much of this station's excursion the region has to account for. A
# region that moved 2 sigma while the station moved 30 does not excuse the
# station -- that is weather plus a fault, and the fault is the part worth
# dispatching for.
SHARE = 0.4

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "dashboard", "sim_map.json")


@lru_cache(maxsize=1)
def _network() -> dict | None:
    """Decode the whole network once: readings, anomalies, neighbour sets.

    Roughly 1.5 million floats. Held for the life of the process because the
    board asks about a few hundred stations per request and re-deriving this
    per row would be the difference between a screen and a spinner.
    """
    if not os.path.isfile(_PATH):
        return None
    with open(_PATH, encoding="utf-8") as fh:
        sim = json.load(fh)

    sts = sim["stations"]
    n = len(sts)
    ids = [s["id"] for s in sts]
    index = {sid: i for i, sid in enumerate(ids)}
    lat = np.array([s["lat"] for s in sts], dtype=np.float64)
    lon = np.array([s["lon"] for s in sts], dtype=np.float64)

    step_min = sim.get("step_minutes", 15)
    every = sim.get("field_every", 2)          # steps per shipped frame

    values, anoms = {}, {}
    for ch in CHANNELS:
        lo, hi = sim["range"][ch]
        raw = np.stack([
            np.frombuffer(base64.b64decode(s[_KEY[ch]]), dtype=np.uint8)
            for s in sts
        ]).astype(np.float32)                   # (n, frames)
        # Byte 0 is the missing marker; 1..255 spans the channel's range.
        vals = np.where(raw == 0, np.nan, lo + ((raw - 1) / 254.0) * (hi - lo))
        values[ch] = vals

        # REMOVE EACH STATION'S OWN SHAPE BEFORE COMPARING ANYTHING.
        #
        # The same reason the grader does it: a mast at 4,196 m and one at
        # 200 m differ by a large constant AND by the shape of their daily
        # swing, so a raw difference oscillates every day for reasons that have
        # nothing to do with any instrument. Subtracting each station's own
        # mean by hour of day, learned on the early clean stretch, leaves
        # weather plus faults -- which is the only part worth differencing.
        frames = vals.shape[1]
        hod = ((np.arange(frames) * every * step_min // 60) % 24)
        clean = max(1, frames // 3)             # early stretch, before faults
        clim = np.full((24, n), np.nan, dtype=np.float32)
        for h in range(24):
            m = hod[:clean] == h
            if m.any():
                with np.errstate(invalid="ignore"):
                    clim[h] = np.nanmean(vals[:, :clean][:, m[:clean]], axis=1)
        anoms[ch] = vals - clim[hod].T

    # Neighbour sets, once. Equirectangular distance: at 250 km and Indian
    # latitudes the error against haversine is centimetres, and it is one
    # vectorised expression instead of 344 great-circle solves.
    latr, lonr = np.radians(lat), np.radians(lon)
    coslat = np.cos(latr.mean())
    dx = (lonr[:, None] - lonr[None, :]) * coslat
    dy = latr[:, None] - latr[None, :]
    dist = np.sqrt(dx * dx + dy * dy) * 6371.0
    np.fill_diagonal(dist, np.inf)
    near = [np.flatnonzero(dist[i] <= RADIUS_KM) for i in range(n)]

    return {"index": index, "anoms": anoms, "near": near,
            "every": every, "frames": values["temp"].shape[1]}


def regional_movement(station_id: str, channel: str,
                      from_step: int | None, to_step: int | None) -> dict | None:
    """What the neighbours were doing while this station was flagged.

    Returns None where the question cannot be answered -- an unknown station, a
    channel with no readings, too few neighbours. The caller must pass that
    through as `unknown` rather than defaulting it, which is the whole reason
    the agents have an `unknown` status.
    """
    net = _network()
    if net is None or channel not in CHANNELS:
        return None
    i = net["index"].get(station_id)
    if i is None:
        return None
    idx = net["near"][i]
    if idx.size < MIN_NEIGHBOURS:
        return None

    a = net["anoms"][channel]
    every = net["every"]
    frames = net["frames"]

    # The episode window arrives in STEPS, and readings are shipped every
    # `field_every` steps. Conflating the two silently reads the wrong days --
    # the same trap that once reported 34 days on a 30-day record.
    lo = 0 if from_step is None else max(0, int(from_step) // every)
    hi = frames if to_step is None else min(frames, int(to_step) // every + 1)
    if hi - lo < 2:
        hi = min(frames, lo + 2)
    if hi <= lo:
        return None

    with np.errstate(invalid="ignore", all="ignore"):
        region = np.nanmedian(a[idx], axis=0)          # what the region did
        # Its own quiet spread, over the whole record, robustly.
        med = np.nanmedian(region)
        mad = np.nanmedian(np.abs(region - med))
        sigma = float(mad * 1.4826) if np.isfinite(mad) else 0.0

        region_dev = float(np.nanmedian(region[lo:hi]))
        station_dev = float(np.nanmedian(a[i, lo:hi]))

    if not (np.isfinite(region_dev) and np.isfinite(station_dev)):
        return None
    if sigma <= 1e-6:
        sigma = 0.0

    z = region_dev / sigma if sigma else 0.0
    moved = abs(z) >= REGION_SIGMA
    same_way = (region_dev * station_dev) > 0
    # Did the region account for a real share of what this station did?
    explains = abs(region_dev) >= SHARE * abs(station_dev) if station_dev else False

    return {
        "agree": bool(moved and same_way and explains),
        "region_z": round(z, 2),
        "region_dev": round(region_dev, 3),
        "station_dev": round(station_dev, 3),
        "neighbours": int(idx.size),
        "moved": bool(moved),
        "same_direction": bool(same_way),
        "share_explained": round(
            min(1.0, abs(region_dev) / abs(station_dev)), 2) if station_dev else None,
    }


def parse_sim_id(ident: str) -> tuple[str, str] | None:
    """`sim:<station>:<channel>` -> (station, channel). The board's row id."""
    parts = ident.split(":")
    if len(parts) == 3 and parts[0] == "sim" and parts[2] in CHANNELS:
        return parts[1], parts[2]
    return None


def comparison_series(station_id: str, channel: str,
                      points: int = 240) -> dict | None:
    """This station against its region, over the whole record.

    THE CHART THE BOARD WAS MISSING.

    The detail pane used to show the station's three raw channels with their
    ranges, which is a picture of the weather and not of the verdict: a
    plausible line, no reference, and nothing in it that could tell a reader
    why anyone had been dispatched. The evidence is not the reading, it is the
    reading MINUS what everyone nearby was doing -- so that is what this
    returns, both halves of it, on one axis.

    Anomalies rather than raw values, because the two lines only belong on the
    same axis once each station's own altitude and daily shape have been taken
    out. Downsampled by plain striding: the reader is looking for a gap opening
    between two lines over days, and no feature that matters survives at one
    point and dies at the next.
    """
    net = _network()
    if net is None or channel not in CHANNELS:
        return None
    i = net["index"].get(station_id)
    if i is None:
        return None
    idx = net["near"][i]
    if idx.size < MIN_NEIGHBOURS:
        return None

    a = net["anoms"][channel]
    with np.errstate(invalid="ignore", all="ignore"):
        region = np.nanmedian(a[idx], axis=0)
        med = np.nanmedian(region)
        mad = np.nanmedian(np.abs(region - med))
    sigma = float(mad * 1.4826) if np.isfinite(mad) and mad > 0 else 0.0

    step = max(1, a.shape[1] // points)
    take = slice(None, None, step)

    def clean(arr) -> list[float | None]:
        return [None if not np.isfinite(v) else round(float(v), 3)
                for v in arr[take]]

    return {
        "station": clean(a[i]),
        "region": clean(region),
        "neighbours": int(idx.size),
        "sigma": round(sigma, 3),
        "every": net["every"] * step,   # steps per returned point
        "channel": channel,
    }
