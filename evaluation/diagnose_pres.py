"""Why does the learned layer lose to a plain z-score on pressure?

    python -m evaluation.diagnose_pres

Diagnose before fixing. The gap is large (PR-AUC 0.12 vs 0.53) and there are at
least four plausible causes -- guessing at one of them and rerunning is how a
morning disappears.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import (LearnedDetector, conformalize,
                            conformalize_by_station, ensemble)
from evaluation.metrics import evaluate, mark_weather_activity

VAR = "pres"
REF_END = "2023-10-01"


def main() -> None:
    df = pd.read_csv("data/skyguard_injected.csv", parse_dates=["timestamp"])
    df = df[df.run_id < 4].reset_index(drop=True)
    events = pd.read_csv("data/injected_events.csv")
    graph = json.loads(Path("data/neighbours_realistic.json").read_text())

    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in ("temp", "rh", "pres")}
    ref = df[df.timestamp < pd.Timestamp(REF_END, tz="UTC")].reset_index(drop=True)
    test = df[df.split == "test"].reset_index(drop=True)
    F_ref, F_test = FT.build(ref, coefs, graph), FT.build(test, coefs, graph)
    t = mark_weather_activity(test, VAR)

    det = LearnedDetector(variable=VAR).fit(F_ref)

    nz_ref = B.neighbour_z(ref, VAR, coefs[VAR], graph)
    nz = B.neighbour_z(test, VAR, coefs[VAR], graph)
    per_ref = B.persistence(ref, VAR)
    per = B.persistence(test, VAR)

    miss = ~np.isfinite(test[VAR].to_numpy(dtype=float))
    p_learn = conformalize(det.distance(F_ref), det.distance(F_test))
    p_nz = conformalize(nz_ref, nz)
    p_per = conformalize(per_ref, per)
    p_per_st = conformalize_by_station(per_ref, ref.station_name.to_numpy(),
                                       per, test.station_name.to_numpy())
    p_nz_st = conformalize_by_station(nz_ref, ref.station_name.to_numpy(),
                                      nz, test.station_name.to_numpy())

    def simes(ps):
        """Simes: sorted p_(k) * m / k, minimised. Valid under positive
        dependence, and far less trigger-happy than a bare minimum."""
        P = np.sort(np.vstack(ps), axis=0)
        m = P.shape[0]
        k = np.arange(1, m + 1)[:, None]
        return -np.log10(np.clip(np.nanmin(P * m / k, axis=0), 1e-12, 1.0))

    def fisher(ps):
        """Fisher: -2 sum log p. Uses every channel's evidence rather than only
        the loudest, so a fault that shows weakly in two channels can outrank a
        single noisy excursion."""
        return np.nansum([-np.log10(np.clip(x, 1e-12, 1.0)) for x in ps], axis=0)

    def pin(x):
        return np.where(miss, 1e6, np.nan_to_num(x))

    cands = {
        "neighbour_z": nz,
        "learned_6d": det.score(F_test),
        "ens_min_3": ensemble([p_learn, p_nz, p_per], certain=miss),
        "ens_simes_3": pin(simes([p_learn, p_nz, p_per])),
        "ens_fisher_3": pin(fisher([p_learn, p_nz, p_per])),
        "ens_min_nz_per": ensemble([p_nz, p_per], certain=miss),
        "ens_fisher_nz_per": pin(fisher([p_nz, p_per])),
        "ens_min_nz_per_ST": ensemble([p_nz_st, p_per_st], certain=miss),
        "ens_min_3_ST": ensemble([p_learn, p_nz_st, p_per_st], certain=miss),
    }

    # Ablation: does the cross-channel context help or hurt on pressure? A
    # pressure fault has no reason to move temperature, so those two axes may be
    # contributing variance and nothing else.
    for name, feats in [
        ("learned_4d_no_context", (f"z_{VAR}", f"flat_{VAR}", f"jump_{VAR}", f"spread_{VAR}")),
        ("learned_level_only", (f"z_{VAR}",)),
        ("learned_no_spread", (f"z_{VAR}", f"flat_{VAR}", f"jump_{VAR}")),
    ]:
        d = LearnedDetector(variable=VAR, feature_names=feats).fit(F_ref)
        cands[name] = d.score(F_test)

    rows = []
    per_type = {}
    for name, s in cands.items():
        r = evaluate(t.assign(_s=s), events, VAR, "_s", 1 / 7)
        fa = r["false_alarms_per_station_day"]
        rows.append({"detector": name, "PR-AUC": round(r["pr_auc"], 4),
                     "event_recall": round(r["event_recall"], 3),
                     "FA quiet": round(fa["quiet"], 3),
                     "FA active": round(fa["active"], 3)})
        per_type[name] = r["event_recall_by_type"]

    print(pd.DataFrame(rows).to_string(index=False))
    print("\nevent recall by fault type:")
    print(pd.DataFrame(per_type).fillna(0).round(2).to_string())

    # How much of the 6-dim distance does each axis actually contribute on
    # flagged pressure faults? If z_pres is not dominant, the whitening is
    # burying the one informative direction.
    c = det.contributions(F_test)
    faulted = test[f"is_fault_{VAR}"].to_numpy().astype(bool)
    share = c[faulted].abs().mean() / c[faulted].abs().mean().sum()
    print("\nmean share of the distance on true pressure faults:")
    print(share.round(3).sort_values(ascending=False).to_string())

    print("\ncorrelation of the six axes on the reference window:")
    print(F_ref[list(det.feature_names)].corr().round(2).to_string())


if __name__ == "__main__":
    main()
