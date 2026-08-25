"""Placebo test: how much of our event recall is earned, and how much is duration?

    python -m evaluation.run_placebo

Event recall in evaluation/metrics.py uses ANY-OVERLAP -- an event counts as
detected if the detector fires even once inside it. For a spike lasting 3 hours
that is a fair question. For a calibration_drift lasting 640 hours it may not be,
because at an alert budget of 1/station/week a 640-hour window contains ~3.8
expected alerts even on perfectly clean data. P(at least one) is then 0.98
whether or not the fault is visible.

So this script scores PLACEBO events: same station, same duration distribution,
placed on windows with no injected fault at all. A placebo "recall" near zero
means our recall is earned. A placebo recall near the real one means the metric
is measuring event length, not detection, and the honest headline is much lower.

This is a falsification test of our own metric, and it is worth more than another
detector. If it fails we have to report the corrected number, not this one.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import LearnedDetector, conformalize, ensemble, ensemble_budgeted
from evaluation.metrics import threshold_for_budget

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"


def placebo_events(g: pd.DataFrame, var: str, durations: np.ndarray,
                   rng: np.random.Generator, n: int) -> list[tuple[int, int]]:
    """Windows of the given durations that contain NO injected fault.

    Drawn from the same station and the same test period as the real events, so
    the only thing that differs is whether a fault is present.
    """
    bad = g[f"is_fault_{var}"].to_numpy().astype(bool)
    # cumulative sum lets us reject a candidate window in O(1)
    c = np.concatenate([[0], np.cumsum(bad)])
    out, tries = [], 0
    while len(out) < n and tries < 400 * n:
        tries += 1
        d = int(rng.choice(durations))
        d = min(d, len(g) - 1)
        if d < 1:                       # spikes are single points: d == 1 is
            continue                    # the case we most need a placebo for
        a = int(rng.integers(0, len(g) - d))
        if c[a + d] - c[a] == 0:            # window is entirely clean
            out.append((a, a + d))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1 / 7)
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--rh-as-dewpoint", dest="rh_td", action="store_true",
                    help="difference DEWPOINT rather than raw RH in the "
                         "neighbour channel. RH is temperature-slaved and is "
                         "not spatially smooth -- it is a ratio whose "
                         "denominator swings with local T -- so a neighbour "
                         "difference on raw RH compares two quantities that "
                         "were never comparable. Dewpoint is conserved within "
                         "an air mass and is the physically right thing to "
                         "difference. Labels are unchanged: this still scores "
                         "against is_fault_rh, so the two arms are comparable.")
    args = ap.parse_args()

    rng = np.random.default_rng(11)
    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    graph = json.loads(Path(args.graph).read_text())

    if args.rh_td:
        from physics.relations import dew_point
        df["td"] = [dew_point(t, r) for t, r in zip(df.temp, df.rh)]

    fitvars = VARIABLES + (("td",) if args.rh_td else ())
    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in fitvars}

    # Only the NEIGHBOUR channel switches to dewpoint. Persistence stays on raw
    # RH, because a stuck hygrometer repeats raw RH values -- that fault lives
    # in the reported number, not in the derived one.
    nbr_var = {"temp": "temp", "pres": "pres",
               "rh": "td" if args.rh_td else "rh"}
    # Full frame first, subset after -- see the long note in run_full.py. Built
    # the other way round, a holdout station loses its neighbours and 37.6 % of
    # test rows get a NaN primary channel, which the flag turns into a miss.
    ref_mask = (df.timestamp < pd.Timestamp(REF_END, tz="UTC")).to_numpy()
    test_mask = (df.split == "test").to_numpy()
    ref = df[ref_mask].reset_index(drop=True)
    test = df[test_mask].reset_index(drop=True)

    print("building features ...")
    F_all = FT.build(df, coefs, graph)
    F_ref = F_all[ref_mask].reset_index(drop=True)
    F_test = F_all[test_mask].reset_index(drop=True)

    def split_channel(fn, *a, **k):
        v = np.asarray(fn(df, *a, **k), dtype=float)
        return v[ref_mask], v[test_mask]
    dets = {v: LearnedDetector(variable=v).fit(F_ref) for v in VARIABLES}

    rows, dur_rows = [], []
    for var in VARIABLES:
        miss = ~np.isfinite(test[var].to_numpy(dtype=float))
        p_learn = conformalize(dets[var].distance(F_ref), dets[var].distance(F_test))
        nv = nbr_var[var]
        p_nz = conformalize(*split_channel(B.neighbour_z, nv, coefs[nv],
                                           graph, True))
        p_per = conformalize(*split_channel(B.persistence, var))
        p_ham = conformalize(*split_channel(B.local_outlier, nv, coefs[nv], graph))
        p_dis = conformalize(*split_channel(B.dispersion, nv, coefs[nv], graph))
        sc = ensemble_budgeted([p_learn, p_nz, p_per, p_ham, p_dis], args.budget,
                               weights=[3, 3, 2, 1, 1], certain=miss)

        # Threshold from the alert budget on CLEAN points only, exactly as in
        # run_full -- otherwise the faults would set their own threshold.
        clean = sc[~test[f"is_fault_{var}"].to_numpy().astype(bool)]
        thr = threshold_for_budget(clean, len(clean) / 24.0, args.budget)
        flag = np.nan_to_num(sc, nan=0.0) >= thr

        t = test.assign(_f=flag)
        eid, ft = f"event_id_{var}", f"fault_type_{var}"

        # ---- real events
        real = []
        for (run, e), g in t[t[eid] >= 0].groupby(["run_id", eid], sort=False):
            real.append({"fault_type": g[ft].iloc[0], "dur": len(g),
                         "hit": bool(g._f.any())})
        real = pd.DataFrame(real)
        if real.empty:
            continue
        durs = real.dur.to_numpy()

        # ---- placebo events, matched per station
        pl = []
        for (run, st), g in t.groupby(["run_id", "station_name"], sort=False):
            g = g.sort_values("timestamp")
            f = g._f.to_numpy().astype(bool)
            for a, b in placebo_events(g, var, durs, rng, 12):
                pl.append({"dur": b - a, "hit": bool(f[a:b].any())})
        pl = pd.DataFrame(pl)

        rows.append({"variable": var,
                     "real events": len(real),
                     "real recall": round(float(real.hit.mean()), 3),
                     "placebo events": len(pl),
                     "PLACEBO recall": round(float(pl.hit.mean()), 3)})

        # The comparison only means anything within a duration band, because the
        # real fault types have very different lengths.
        bins = [0, 6, 24, 96, 384, 10 ** 6]
        names = ["<6h", "6-24h", "1-4d", "4-16d", ">16d"]
        real["band"] = pd.cut(real.dur, bins, labels=names, right=False)
        pl["band"] = pd.cut(pl.dur, bins, labels=names, right=False)
        for nm in names:
            r, q = real[real.band == nm], pl[pl.band == nm]
            if not len(r):
                continue
            dur_rows.append({
                "variable": var, "duration": nm, "n real": len(r),
                "real recall": round(float(r.hit.mean()), 3),
                "n placebo": len(q),
                "placebo recall": round(float(q.hit.mean()), 3) if len(q) else np.nan,
                "excess": (round(float(r.hit.mean() - q.hit.mean()), 3)
                           if len(q) else np.nan)})

    print(f"\nalert budget {args.budget:.4f}/station/day (1/week), any-overlap "
          "scoring\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nsplit by event duration -- 'excess' is the recall actually earned")
    print("by the fault being present, i.e. real minus placebo:\n")
    print(pd.DataFrame(dur_rows).to_string(index=False))


if __name__ == "__main__":
    main()
