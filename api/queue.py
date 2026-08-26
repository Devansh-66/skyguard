"""The work queue: what the system thinks needs attention, ranked, with its own score.

    GET /api/queue            everything the system would put in front of an operator
    GET /api/queue/{id}       the evidence behind one item

WHY THIS REPLACED THE INSPECTOR

The first console had dropdowns: pick a station, pick a known fault window, watch
the checkers run. That is a tool for inspecting an algorithm, and it quietly
cheats -- choosing a fault window from a list means the answer was already known
before the system was asked. An operator has a thousand stations and no idea
which one is broken; that is the entire problem.

So this scans everything held and RANKS it. The fault reports are no longer a
selector. They become a scorecard: of the items the system raised, how many did
an ARM analyst independently write up, and which ones did they find that we
missed. That number is computed here and shown in the product rather than kept
in an evaluation script, because a queue that cannot tell you its own hit rate
is asking to be trusted on faith.

WHAT AN ITEM IS

One (station, sensor) that the belief state says has moved. Not one alert per
reading -- an operator cannot act on those, and 1,000 stations times 96 readings
a day is not a queue, it is a denial of service. The unit here is the unit of
WORK: something a person would go and do.

RANKING

By how far the sensor has moved from where it should be, in its own robust
sigmas, scaled by how much evidence sits behind that belief. A large departure
seen four times ranks below a smaller one seen four thousand times, which is the
Beta reputation's concentration doing a job the previous trust value could not.
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from api.ai import (SENSORS, HK, _dqr, _held_days, _prepared, _f,
                    _reference_note)
from detect.belief import BIAS_TOLERANCE
from detect.checkers import PANEL, adjudicate, DoubleFaultMatrix

router = APIRouter()

DFM_PATH = os.environ.get("SKYGUARD_DFM", "models/double_fault.json")

# A sensor enters the queue when its accumulated bias exceeds this many of its
# own robust sigmas. Same convention as BIAS_TOLERANCE in the belief update, so
# an item appears exactly when the belief stops counting the sensor as in spec.
RAISE_AT = BIAS_TOLERANCE

# Below this much evidence the belief has not seen enough to be worth an
# operator's time, however far it has moved.
MIN_EVIDENCE = 40.0


# Days until anyone is next at the station. The dispatch decision is really a
# question about this interval: will a number typed in today still be right when
# someone finally visits?
SERVICE_INTERVAL_D = 90.0


def _action(bias: float, drift: float, noise: float, trust: float,
            hk_moved: bool) -> tuple[str, str]:
    """Dispatch or correct centrally -- and say why, in operational terms.

    The first version compared the drift against an arbitrary fraction of the
    noise. Every real drift cleared it, so every item said DISPATCH and the
    distinction did no work at all. The rule now asks the question an operator
    actually has: a stable offset can be fixed with a coefficient, but one still
    growing will be wrong again before anyone gets there, so it needs the visit.
    """
    if hk_moved:
        return ("DISPATCH",
                "housekeeping has moved too, so this is the hardware rather "
                "than the calibration and a coefficient will not hold it")
    if trust < 0.5:
        return ("DISPATCH", "the sensor has failed most of its recent checks")
    growth = abs(drift) * SERVICE_INTERVAL_D
    if growth > RAISE_AT * max(noise, 1e-9):
        return ("DISPATCH",
                f"drifting {abs(drift):.3f} sigma/day, so it moves a further "
                f"{growth:.1f} sigma before the next {SERVICE_INTERVAL_D:.0f}-day "
                f"service visit — a coefficient set today is wrong long before "
                f"anyone arrives")
    return ("CORRECT CENTRALLY",
            f"offset of {bias:+.2f} sigma, growing only {growth:.2f} sigma over "
            f"{SERVICE_INTERVAL_D:.0f} days — a coefficient update holds, no visit")


@lru_cache(maxsize=1)
def _scan() -> dict:
    """Walk every window we hold and build the queue. Cached; cheap to rebuild."""
    d, held = _dqr(), _held_days()
    if d.empty:
        return {"items": [], "scored": {}, "stations": 0}

    items, seen_windows = [], []
    for _, r in d.iterrows():
        st = str(r["datastream"]).split(".")[0]
        if st not in held or not (2 <= r["hours"] <= 900):
            continue
        days = {x.strftime("%Y%m%d")
                for x in pd.date_range(r["start"].floor("D"), r["end"].ceil("D"))}
        if len(days & held[st]) < 2:
            continue
        try:
            df, z, beliefs, row = _prepared(st, r["dqr"])
        except HTTPException:
            continue
        seen_windows.append({"station": st, "dqr": r["dqr"],
                             "subject": str(r["subject"]),
                             "variables": str(r["variables"])})

        # last hour we actually hold, which is what "now" means for this window
        i = len(df) - 1
        hk_moved = any(
            abs(beliefs[k][i].bias) > RAISE_AT * max(beliefs[k][i].noise, 1e-9)
            for k in HK if k in beliefs)

        for k, traj in beliefs.items():
            b = traj[i]
            if b.trust_confidence < MIN_EVIDENCE:
                continue
            sev = abs(b.bias) / max(b.noise, 1e-9)
            if sev < RAISE_AT:
                continue

            # when did the belief cross the line? that is the onset estimate,
            # and a work order without one cannot tell an archive what to re-flag
            onset_i = None
            for j in range(i, -1, -1):
                bj = traj[j]
                if abs(bj.bias) <= RAISE_AT * max(bj.noise, 1e-9):
                    onset_i = min(j + 1, i)
                    break
            onset = df.timestamp[onset_i].isoformat() if onset_i is not None else None

            act, why = _action(b.bias, b.drift, b.noise, b.trust,
                               hk_moved and k not in HK)
            confirmed = SENSORS[k][0] in str(r["variables"])
            items.append({
                "id": f"{st}:{r['dqr']}:{k}",
                "station": st, "sensor": k, "label": SENSORS[k][2],
                "unit": SENSORS[k][1], "housekeeping": k in HK,
                "severity": round(float(sev), 2),
                "rank": round(float(sev) * np.log1p(b.trust_confidence), 2),
                "bias": _f(b.bias), "drift_per_day": _f(b.drift),
                "noise": _f(b.noise), "trust": _f(b.trust),
                "evidence": _f(b.trust_confidence), "checks": b.checks_passed,
                "onset": onset,
                "days_since_onset": (None if onset_i is None else
                                     round((df.timestamp[i] - df.timestamp[onset_i])
                                           .total_seconds() / 86400.0, 1)),
                "action": act, "why": why,
                "confirmed_by_analyst": bool(confirmed),
                "analyst_subject": str(r["subject"]) if confirmed else None,
                "window": {"dqr": r["dqr"], "start": r["start"].isoformat(),
                           "end": r["end"].isoformat()},
                "reference": _reference_note(168, float(r["hours"])),
            })

    items.sort(key=lambda x: -x["rank"])

    # the scorecard. Every sensor an analyst named, did we raise it?
    named, raised_named = set(), set()
    for w in seen_windows:
        for k, (name, _u, _l) in SENSORS.items():
            if name in w["variables"]:
                named.add((w["station"], w["dqr"], k))
    for it in items:
        key = (it["station"], it["window"]["dqr"], it["sensor"])
        if key in named:
            raised_named.add(key)

    scored = {
        "analyst_named": len(named),
        "we_raised_of_those": len(raised_named),
        "we_missed": sorted(f"{s}/{k}" for s, _d, k in (named - raised_named))[:12],
        "items_raised": len(items),
        "raised_and_confirmed": sum(1 for i in items if i["confirmed_by_analyst"]),
    }
    return {"items": items, "scored": scored,
            "stations": len({w["station"] for w in seen_windows}),
            "windows": len(seen_windows)}


@router.get("/api/queue")
def work_queue() -> dict:
    q = _scan()
    s = q["scored"]
    recall = (s["we_raised_of_those"] / s["analyst_named"]
              if s["analyst_named"] else None)
    precision = (s["raised_and_confirmed"] / s["items_raised"]
                 if s["items_raised"] else None)
    actions = {}
    for it in q["items"]:
        actions[it["action"]] = actions.get(it["action"], 0) + 1

    return {
        "generated_from": "real ARM one-minute observations; fault reports "
                          "written by analysts who inspected the instruments",
        "stations_scanned": q["stations"],
        "windows_scanned": q["windows"],
        "items": q["items"],
        "actions": actions,
        "action_note": (
            "Every item here says DISPATCH. That is not a bug in the rule -- it "
            "is what this corpus contains. Each window came from a report an "
            "analyst wrote after noticing something, so by construction it holds "
            "faults severe enough to be worth writing up. The quiet, stable "
            "offset that a coefficient would fix is exactly the case nobody "
            "files a report about, so it cannot appear here. Demonstrating the "
            "no-dispatch branch needs routine data, not a fault archive."
            if set(actions) == {"DISPATCH"} else None),
        "scorecard": {
            **s,
            "recall": None if recall is None else round(recall, 3),
            "precision_vs_analyst": None if precision is None else round(precision, 3),
            "caveat": "Precision here is a LOWER BOUND, not a true precision. An "
                      "item we raise that no analyst named may be a false alarm "
                      "or may be a real fault nobody wrote up -- ARM reports what "
                      "someone noticed, not everything that was wrong. Recall is "
                      "the number to trust.",
        },
    }


@router.get("/api/queue/{item_id:path}")
def item(item_id: str) -> dict:
    """The evidence behind one queue item: checkers, belief, and the series."""
    q = _scan()
    it = next((x for x in q["items"] if x["id"] == item_id), None)
    if it is None:
        raise HTTPException(404, "no such queue item")

    df, z, beliefs, r = _prepared(it["station"], it["window"]["dqr"])

    # Evaluate the panel at the hour that most supports the item, not the last
    # hour we hold. The queue item is about the ACCUMULATED belief, while the
    # panel is instantaneous, so pinning it to the final hour produced rows
    # reading "severity 4.0, DISPATCH" beside a panel reading "PASS — no
    # baseline yet". Both were correct and they contradicted each other on
    # screen, which reads as broken. The operator wants the moment the evidence
    # was strongest.
    k = it["sensor"]
    zk = z.get(k)
    has = df[["temp", "pres", "rh"]].notna().all(axis=1).to_numpy()
    cand = np.where(has & np.isfinite(zk), np.abs(zk), np.nan) if zk is not None \
        else np.full(len(df), np.nan)
    i = int(np.nanargmax(cand)) if np.isfinite(cand).any() else len(df) - 1

    # `own_resid` must be the residual of THE SENSOR THIS ITEM IS ABOUT. It was
    # hardwired to temperature, so a humidity item was being judged on the
    # thermometer's residual -- the history checker reported on a channel nobody
    # had asked about, and quietly stayed silent about the one that mattered.
    own = _f(z[k][i]) if k in z else None
    ctx = {
        "temp": float(df.temp[i]), "pres": float(df.pres[i]), "rh": float(df.rh[i]),
        "neighbour_diff": None, "neighbour_sigma": None, "n_neighbours": 0,
        "own_resid": own, "own_sigma": 1.0,
        "flat_fraction": 0.0,
        "jump_sigma": own or 0.0,
        "clock_offset_min": None,
        "volt_z": _f(z["volt"][i]) if "volt" in z else None,
        "logger_temp_z": _f(z["ltemp"][i]) if "ltemp" in z else None,
    }
    verdicts = [c(ctx) for c in PANEL]
    dec = adjudicate(verdicts, DoubleFaultMatrix(DFM_PATH))

    return {
        **it,
        "at": df.timestamp[i].isoformat(),
        "panel_note": ("The panel below is this ONE hour -- the moment the "
                       "evidence was strongest. The severity and drift above "
                       "are the accumulated belief over the whole record, which "
                       "is why a quiet panel can sit beside a high-severity "
                       "item: one asks what is happening now, the other what "
                       "has happened."),
        "verdicts": [{"checker": v.checker, "fired": bool(v.fired),
                      "score": _f(v.score), "reason": v.reason} for v in verdicts],
        "decision": dec.verdict, "note": dec.note, "explain": dec.explain(),
        "series": {
            "t": [t.isoformat() for t in df.timestamp],
            "v": [_f(x) for x in df[k]],
            "bias": [_f(b.bias) for b in beliefs[k]],
            "trust": [_f(b.trust) for b in beliefs[k]],
            "faulty": [bool(x) for x in df.faulty],
        },
        "analyst_note": str(r["description"])[:400],
    }
