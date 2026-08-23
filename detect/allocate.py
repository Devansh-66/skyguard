"""Per-fault-type alert budgets.

THE PROBLEM THIS SOLVES. One network-wide threshold makes every fault class
compete in the same auction, and the auction is decided by duration. A
ninety-day calibration drift contributes two thousand samples above the line; a
one-hour spike contributes one. The drift wins, every time, and no amount of
detector tuning changes it -- measured directly: raising the budget from 1 to 21
alerts per station-week moved humidity step-offset recall 0.42 -> 1.00 and
noise-burst 0.29 -> 0.86, while spike recall barely moved because spikes were
never crowded out, they were under the noise floor.

So the classes that are BUDGET-LIMITED need a budget of their own, and the ones
that are AMPLITUDE-LIMITED need to be told apart from them rather than lumped
in.

THE ORDERING PROBLEM. A per-fault-type budget needs the fault type, and the
fault type is only known after classification, which happens after detection.
So detection runs at a deliberately loose threshold to produce CANDIDATES, the
signature stage names each one, and the budget is then spent per class. The
loose pass is not a false-alarm problem: nothing is shown to an operator until
after allocation.

WHAT THE ALLOCATION ENCODES. It is an operational judgement, not a statistic,
and it belongs in one visible place rather than smeared through thresholds:

  calibration_drift  the fault nobody can see by eye, that silently corrupts a
                     climate record, and that we can already catch at 0.01
                     K/day. Worth the largest share.
  step_offset        equally invisible in a single series, and budget-limited.
  frozen, dropout,
  saturation         unambiguous once detected and cheap to confirm, so they
                     need enough budget to appear and no more.
  noise_burst        budget-limited: 0.29 -> 0.86 when given room.
  spike              deliberately small. Spikes below ~3 sigma are undetectable
                     at any budget, and a single bad hour rarely justifies a
                     van. Spending here buys the least.
  genuine_weather    ZERO. The classifier identifying real weather is the point
                     of the system; spending alert budget on it would be paying
                     to be told nothing is wrong.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = "allocate-1.0.0"

DEFAULT_ALLOCATION = {
    "calibration_drift": 0.24,
    "step_offset": 0.20,
    "frozen": 0.14,
    "noise_burst": 0.14,
    "dropout": 0.10,
    "saturation": 0.06,
    "spike": 0.07,
    "unknown": 0.05,
    "genuine_weather": 0.0,
}

# A loose first pass, as a multiple of the operator's budget. Wide enough that
# the classifier sees the borderline cases, since a window never detected can
# never be allocated to its class.
CANDIDATE_MULTIPLE = 12.0


def allocate(windows: pd.DataFrame, budget_per_station_day: float,
             station_days: float, allocation: dict | None = None,
             label_col: str = "label", score_col: str = "score",
             reserve: float = 0.35) -> pd.DataFrame:
    """Select the alerts an operator actually sees.

    `windows` is one row per candidate window with a predicted label and a
    score. Returns the selected subset with the reason it was kept, because an
    operator who cannot see why a quiet class stayed quiet will not trust the
    allocation.

    A FLOOR, NOT A PARTITION. The first version of this handed each class a
    slice and dropped whatever it did not use. Measured, that spent 431 alerts
    of a 1281 budget and lost recall in every class -- because the signature
    stage produced 5 candidate windows labelled calibration_drift and 0 labelled
    noise_burst, so quotas of 301 and 176 could not be filled by anything.
    Reserving budget for a label the classifier rarely emits does not protect
    that class; it just burns the budget.

    So `reserve` is spent per class as a guaranteed minimum, and everything left
    -- including every unfilled reservation -- is then spent globally by score.
    Short faults still get a floor no long fault can take from them, and no
    alert is thrown away. The anti-crowding-out property survives; the waste
    does not.
    """
    alloc = dict(allocation or DEFAULT_ALLOCATION)
    total = budget_per_station_day * station_days
    reserved_total = total * reserve

    picked, quotas = [], {}
    for label, group in windows.groupby(label_col, sort=False):
        share = alloc.get(label, alloc.get("unknown", 0.0))
        n = int(round(share * reserved_total))
        quotas[label] = n
        if n <= 0:
            continue
        top = group.nlargest(min(n, len(group)), score_col).copy()
        top["kept_by"] = "reserved"
        picked.append(top)

    taken = pd.concat(picked) if picked else windows.iloc[0:0]
    # Everything not reserved, plus every unfilled reservation, by score --
    # but never for a class allocated zero, which is a suppression and not a
    # shortfall.
    suppressed = {k for k, v in alloc.items() if v == 0.0}
    rest = windows.drop(index=taken.index, errors="ignore")
    rest = rest[~rest[label_col].isin(suppressed)]
    room = int(round(total)) - len(taken)
    if room > 0 and len(rest):
        extra = rest.nlargest(min(room, len(rest)), score_col).copy()
        extra["kept_by"] = "open"
        taken = pd.concat([taken, extra])

    out = taken.sort_values(score_col, ascending=False)
    out["quota"] = out[label_col].map(quotas).fillna(0).astype(int)
    return out


def quota_report(windows: pd.DataFrame, selected: pd.DataFrame,
                 budget_per_station_day: float, station_days: float,
                 allocation: dict | None = None,
                 label_col: str = "label", reserve: float = 0.35) -> pd.DataFrame:
    """What each class was given, what it used, and what it left on the table.

    The unused column is the useful one: a class that never fills its quota is
    either genuinely quiet or undetectable, and those need different responses.
    """
    alloc = dict(allocation or DEFAULT_ALLOCATION)
    total = budget_per_station_day * station_days * reserve
    rows = []
    for label in sorted(set(windows[label_col]) | set(alloc)):
        q = int(round(alloc.get(label, alloc.get("unknown", 0.0)) * total))
        rows.append({
            "label": label,
            "candidates": int((windows[label_col] == label).sum()),
            "quota": q,
            "used": int((selected[label_col] == label).sum()) if len(selected) else 0,
        })
    df = pd.DataFrame(rows)
    df["unused"] = df.quota - df.used
    return df.sort_values("quota", ascending=False)
