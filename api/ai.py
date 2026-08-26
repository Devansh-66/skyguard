"""Live orchestrator endpoints: pick a station, pick an hour, watch the panel run.

    GET  /api/ai/catalog                     stations and their known fault windows
    GET  /api/ai/replay?station=&dqr=        the hour-by-hour series for one window
    GET  /api/ai/evaluate?station=&dqr=&i=   run every checker at hour i, one result
                                             per checker, plus the adjudication

WHY THIS EXISTS SEPARATELY FROM THE EXPORTED PAGE

The exported page is a report: a snapshot of one conclusion, already reached.
That is the wrong shape for showing an ORCHESTRATOR, because the interesting
part is not the verdict, it is the sequence -- which checker looked at what,
which of them fired, and why the adjudicator refused or accepted. A report hides
exactly the part worth seeing.

So these endpoints run the panel on demand, per hour, and return each checker's
verdict separately, so a UI can show them arriving one at a time and let an
operator step along the timeline.

EVERYTHING HERE IS COMPUTED FROM REAL OBSERVATIONS. The catalog is built from
ARM's Data Quality Reports -- fault intervals a person wrote after inspecting
the instrument -- and the readings are the station's own one-minute data
aggregated to hours. Nothing is simulated. When the estimate is weak, the
endpoint says so in `reference.warning` rather than returning a confident number.
"""
from __future__ import annotations

import glob
import os
import re
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from detect.belief import Belief, BIAS_TOLERANCE
from detect.checkers import PANEL, adjudicate, DoubleFaultMatrix

router = APIRouter()

ROOT = os.environ.get("SKYGUARD_ARM_ROOT", "data/arm/raw")
DQR_CSV = os.environ.get("SKYGUARD_ARM_DQR", "data/arm/dqr_tprh.csv")
DFM_PATH = os.environ.get("SKYGUARD_DFM", "models/double_fault.json")

SENSORS = {"temp": ("temp_mean", "°C", "Temperature"),
           "pres": ("atmos_pressure", "hPa", "Pressure"),
           "rh": ("rh_mean", "%", "Relative humidity"),
           "volt": ("logger_volt", "V", "Logger voltage"),
           "ltemp": ("logger_temp", "°C", "Logger temperature")}
HK = ("volt", "ltemp")
PAD_BEFORE, PAD_AFTER = 6, 4          # days of context around a fault window


# --------------------------------------------------------------------- data

@lru_cache(maxsize=1)
def _dqr() -> pd.DataFrame:
    if not os.path.exists(DQR_CSV):
        return pd.DataFrame()
    d = pd.read_csv(DQR_CSV, parse_dates=["start", "end"])
    d["hours"] = (d["end"] - d["start"]).dt.total_seconds() / 3600.0
    return d


@lru_cache(maxsize=1)
def _held_days() -> dict:
    """Which days we actually hold files for, per station."""
    out: dict[str, set] = {}
    for f in glob.glob(os.path.join(ROOT, "**", "*.cdf"), recursive=True):
        b = os.path.basename(f)
        m = re.search(r"\.(\d{8})\.", b)
        if m:
            out.setdefault(b.split(".")[0], set()).add(m.group(1))
    return out


@lru_cache(maxsize=16)
def _station_hours(station: str, t0: str, t1: str) -> pd.DataFrame:
    """Hourly frame for one station over one padded window. Cached per window."""
    import netCDF4
    a, b = pd.Timestamp(t0), pd.Timestamp(t1)
    days = {d.strftime("%Y%m%d") for d in pd.date_range(a.floor("D"), b.ceil("D"))}
    frames = []
    for f in sorted(glob.glob(os.path.join(ROOT, "**", f"{station}.*.cdf"),
                              recursive=True)):
        m = re.search(r"\.(\d{8})\.", os.path.basename(f))
        if not m or m.group(1) not in days:
            continue
        try:
            d = netCDF4.Dataset(f)
        except Exception:
            continue
        try:
            if "temp_mean" not in d.variables:
                continue
            t = (pd.Timestamp(m.group(1))
                 + pd.to_timedelta(np.asarray(d.variables["time"][:]), unit="s"))
            row = {"timestamp": t}
            for short, (name, _u, _l) in SENSORS.items():
                if name in d.variables:
                    v = np.asarray(d.variables[name][:], float)
                    if short == "pres":
                        v = v * 10.0                       # ARM ships kPa
                    qc = "qc_" + name
                    if qc in d.variables:
                        v = np.where(np.asarray(d.variables[qc][:], int) == 0,
                                     v, np.nan)
                    row[short] = v
                else:
                    row[short] = np.full(len(t), np.nan)
            frames.append(pd.DataFrame(row))
        finally:
            d.close()
    if not frames:
        raise HTTPException(404, f"no data held for {station} in that window")
    df = (pd.concat(frames, ignore_index=True).sort_values("timestamp")
            .set_index("timestamp").resample("1h").mean(numeric_only=True)
            .reset_index())
    return df[(df.timestamp >= a) & (df.timestamp <= b)].reset_index(drop=True)


def _trailing_z(s: pd.Series, window: int = 168) -> np.ndarray:
    med = s.rolling(window, min_periods=24).median().shift(1)
    mad = (s - med).abs().rolling(window, min_periods=24).median().shift(1)
    return ((s - med) / (1.4826 * mad).replace(0, np.nan)).to_numpy()


def _reference_note(window_h: float, fault_h: float) -> dict:
    """How compromised the trailing reference is HERE, from the two numbers."""
    if fault_h >= window_h:
        sev = (f"this fault lasts {fault_h:.0f} h, longer than the "
               f"{window_h:.0f} h window, so the reference sits inside the fault "
               f"for most of it and the station looks healthier than it is")
    elif fault_h >= 0.5 * window_h:
        sev = (f"this fault lasts {fault_h:.0f} h against a {window_h:.0f} h "
               f"window, so the reference is partly contaminated and the "
               f"estimate is weakened")
    else:
        sev = (f"this fault lasts {fault_h:.0f} h against a {window_h:.0f} h "
               f"window, so the reference is mostly clean")
    return {"kind": "trailing", "window_hours": window_h,
            "fault_hours": round(fault_h, 1),
            "compromised": bool(fault_h >= 0.5 * window_h),
            "warning": "Reference is the station's own trailing window: " + sev
                       + ". A neighbour reference needs contemporaneous SGP "
                         "coverage — see scripts/fetch_sgp_block.ps1."}


@lru_cache(maxsize=16)
def _prepared(station: str, dqr_id: str):
    """Hourly frame, per-sensor z, and the belief trajectory for one window."""
    d = _dqr()
    row = d[(d.dqr == dqr_id) & (d.datastream.str.startswith(station))]
    if row.empty:
        raise HTTPException(404, f"unknown fault window {dqr_id} for {station}")
    r = row.iloc[0]
    t0, t1 = r["start"], r["end"]
    df = _station_hours(station,
                        (t0 - pd.Timedelta(days=PAD_BEFORE)).isoformat(),
                        (t1 + pd.Timedelta(days=PAD_AFTER)).isoformat())
    if len(df) < 24:
        raise HTTPException(404, "not enough data held around that window")
    df["faulty"] = (df.timestamp >= t0) & (df.timestamp <= t1)

    z = {k: _trailing_z(df[k]) for k in SENSORS if k in df}

    # belief trajectory, replayed causally so any hour can be asked about
    beliefs: dict[str, list] = {}
    for k in z:
        b = Belief(station=station, sensor=k)
        traj, prev = [], None
        for i, ts in enumerate(df.timestamp):
            if np.isfinite(z[k][i]):
                dt = 0.0 if prev is None else (ts - prev).total_seconds() / 86400.0
                b = b.update(float(z[k][i]), dt, ts.to_pydatetime())
                prev = ts
            traj.append(b)
        beliefs[k] = traj
    return df, z, beliefs, r


def _f(v):
    """JSON-safe float."""
    return None if v is None or not np.isfinite(v) else round(float(v), 3)


# ---------------------------------------------------------------- endpoints

@router.get("/api/ai/catalog")
def catalog() -> dict:
    """Stations we hold data for, and the fault windows we can replay."""
    d, held = _dqr(), _held_days()
    if d.empty:
        return {"stations": [], "note": f"no DQR table at {DQR_CSV}"}
    out: dict[str, list] = {}
    for _, r in d.iterrows():
        st = str(r["datastream"]).split(".")[0]
        if st not in held or not (2 <= r["hours"] <= 900):
            continue
        days = {x.strftime("%Y%m%d")
                for x in pd.date_range(r["start"].floor("D"), r["end"].ceil("D"))}
        covered = len(days & held[st])
        if covered < 2:
            continue
        out.setdefault(st, []).append({
            "dqr": r["dqr"], "subject": str(r["subject"]),
            "start": r["start"].isoformat(), "end": r["end"].isoformat(),
            "hours": round(float(r["hours"]), 1),
            "variables": str(r["variables"]),
            "days_held": covered,
            "housekeeping_named": any(v in str(r["variables"])
                                      for v in ("logger_volt", "logger_temp")),
        })
    # Best-covered station first, not alphabetical. The belief state needs a
    # run-up before the fault to be worth looking at -- the trailing reference
    # produces nothing for its first 24 hours -- so defaulting to whichever
    # station sorts first by name lands the user on an empty estimator.
    stations = [{"station": s,
                 "windows": sorted(v, key=lambda w: -w["days_held"]),
                 "best_days": max(w["days_held"] for w in v)}
                for s, v in out.items()]
    stations.sort(key=lambda x: (-x["best_days"], x["station"]))
    return {"stations": stations,
            "source": "ARM Data Quality Reports — intervals written by a person "
                      "who inspected the instrument"}


@router.get("/api/ai/replay")
def replay(station: str = Query(...), dqr: str = Query(...)) -> dict:
    """The hour-by-hour series a UI steps through."""
    df, z, beliefs, r = _prepared(station, dqr)
    hours = [{"i": i, "t": ts.isoformat(), "faulty": bool(df.faulty[i]),
              "has_data": bool(df[["temp", "pres", "rh"]].notna().all(axis=1)[i])}
             for i, ts in enumerate(df.timestamp)]
    series = {k: {"label": SENSORS[k][2], "unit": SENSORS[k][1],
                  "housekeeping": k in HK,
                  "named_in_report": SENSORS[k][0] in str(r["variables"]),
                  "v": [_f(x) for x in df[k]],
                  "z": [_f(x) for x in z[k]],
                  "bias": [_f(b.bias) for b in beliefs[k]],
                  "trust": [_f(b.trust) for b in beliefs[k]]}
              for k in z}
    # default to the worst hour the station actually reported
    # Prefer an hour where the belief has actually warmed up. Any hour before
    # the trailing reference starts producing values leaves every sensor sitting
    # at its prior, which shows a page full of zeros and teaches nothing.
    zt = z.get("temp", np.full(len(df), np.nan))
    has = df[["temp", "pres", "rh"]].notna().all(axis=1).to_numpy()
    warm = np.zeros(len(df), bool)
    warm[26:] = True
    cand = np.where(df.faulty.to_numpy() & has & warm, np.abs(zt), np.nan)
    if not np.isfinite(cand).any():                    # fall back progressively
        cand = np.where(df.faulty.to_numpy() & warm, 1.0, np.nan)
    if not np.isfinite(cand).any():
        cand = np.where(df.faulty.to_numpy(), 1.0, np.nan)
    start = int(np.nanargmax(cand)) if np.isfinite(cand).any() else 0
    return {"station": station,
            "dqr": {"id": dqr, "subject": str(r["subject"]),
                    "start": r["start"].isoformat(), "end": r["end"].isoformat(),
                    "hours": round(float(r["hours"]), 1),
                    "variables": str(r["variables"]),
                    "description": str(r["description"])[:400]},
            "reference": _reference_note(168, float(r["hours"])),
            "hours": hours, "series": series, "suggested_index": start}


@router.get("/api/ai/evaluate")
def evaluate(station: str = Query(...), dqr: str = Query(...),
             i: int = Query(..., ge=0)) -> dict:
    """Run every checker at one hour and adjudicate. One entry per checker."""
    df, z, beliefs, r = _prepared(station, dqr)
    if i >= len(df):
        raise HTTPException(400, "hour index out of range")

    ctx = {
        "temp": float(df.temp[i]), "pres": float(df.pres[i]), "rh": float(df.rh[i]),
        "neighbour_diff": None, "neighbour_sigma": None, "n_neighbours": 0,
        "own_resid": _f(z["temp"][i]) if "temp" in z else None, "own_sigma": 1.0,
        "flat_fraction": 0.0,
        "jump_sigma": _f(z["temp"][i]) or 0.0 if "temp" in z else 0.0,
        "clock_offset_min": None,
        "volt_z": _f(z["volt"][i]) if "volt" in z else None,
        "logger_temp_z": _f(z["ltemp"][i]) if "ltemp" in z else None,
    }
    verdicts = [c(ctx) for c in PANEL]
    dec = adjudicate(verdicts, DoubleFaultMatrix(DFM_PATH))

    state = {}
    for k, traj in beliefs.items():
        b = traj[i]
        lo, hi = b.bias_ci
        state[k] = {"label": SENSORS[k][2], "unit": SENSORS[k][1],
                    "housekeeping": k in HK,
                    "value": _f(df[k][i]), "z": _f(z[k][i]),
                    "bias": _f(b.bias), "bias_lo": _f(lo), "bias_hi": _f(hi),
                    "drift_per_day": _f(b.drift), "noise": _f(b.noise),
                    "trust": _f(b.trust), "evidence": _f(b.trust_confidence),
                    "checks": b.checks_passed,
                    "days_to_spec": _f(b.days_to_spec(BIAS_TOLERANCE))}

    return {
        "station": station, "i": i,
        "t": df.timestamp[i].isoformat(),
        "inside_fault_window": bool(df.faulty[i]),
        "reading": {k: _f(df[k][i]) for k in SENSORS if k in df},
        "verdicts": [{"checker": v.checker, "fired": bool(v.fired),
                      "score": _f(v.score), "reason": v.reason,
                      "evidence": {kk: (_f(vv) if isinstance(vv, (int, float))
                                        else vv)
                                   for kk, vv in v.evidence.items()}}
                     for v in verdicts],
        "decision": dec.verdict,
        "note": dec.note,
        "corroborated_by": list(dec.corroborated_by) if dec.corroborated_by else None,
        "explain": dec.explain(),
        "belief": state,
    }
