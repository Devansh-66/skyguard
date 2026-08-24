"""Do the ESP32's approximations still work? Measure before writing firmware.

    python -m evaluation.run_edge_approx

An ESP32 cannot do what the server does. It has no room to hold a year of
samples, so two batch computations have to become streaming ones:

    batch Huber IRLS      ->  one-pass online IRLS      (the baseline fit)
    720-sample median/MAD ->  P-square quantile sketch  (the robust scale)

Both are approximations, and an approximation that changes a detection is a
different detector. This script measures the divergence on real data instead of
assuming it is small, and it also checks the thing the robustness is FOR:
whether a fit survives a drift hidden in its own training window.

Nothing here is firmware. It is the evidence that firmware would be worth
writing.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd

from detect.baseline import harmonic_baseline, _huber_irls, MAD_FLOOR_C, RESOLUTION

VARIABLES = ("temp", "rh", "pres")


# --------------------------------------------------------------- online fit

def online_huber(X: np.ndarray, y: np.ndarray, c: float = 1.345,
                 warmup: int = 336, refit_every: int = 168) -> np.ndarray:
    """One pass, O(p^2) state, no sample stored.

    Accumulates the weighted normal equations X'WX and X'Wy incrementally. The
    weight for each sample comes from its residual against the CURRENT
    coefficients, which is the online analogue of IRLS -- batch IRLS reweights
    every sample every iteration, this one weights each sample once, as it
    arrives, and never revisits it.

    The scale needed for the weight is itself estimated online, as a running
    median of the absolute residual. During warm-up there are no coefficients
    yet, so every sample is weighted 1 and the fit is briefly plain least
    squares; that is unavoidable and is why warm-up is a stated cost rather
    than a hidden one.
    """
    n, p = X.shape
    XtX = np.zeros((p, p))
    Xty = np.zeros(p)
    beta = np.zeros(p)
    absr = []                      # only during warm-up, then discarded
    scale = 1.0

    for i in range(n):
        xi, yi = X[i], y[i]
        if i < warmup:
            w = 1.0
        else:
            r = abs(yi - xi @ beta)
            w = 1.0 if r <= c * scale else (c * scale) / max(r, 1e-9)
            # running median of |residual| via a cheap sign update, which is
            # what a P-square sketch does more precisely
            scale += 0.01 * scale * (1.0 if r > scale else -1.0)

        XtX += w * np.outer(xi, xi)
        Xty += w * xi * yi

        if i == warmup - 1:
            beta = np.linalg.lstsq(XtX, Xty, rcond=None)[0]
            r0 = np.abs(y[:warmup] - X[:warmup] @ beta)
            scale = float(np.median(r0)) or 1.0
        elif i >= warmup and (i - warmup) % refit_every == 0:
            beta = np.linalg.lstsq(XtX + np.eye(p) * 1e-9, Xty, rcond=None)[0]

    return np.linalg.lstsq(XtX + np.eye(p) * 1e-9, Xty, rcond=None)[0]


# ------------------------------------------------------ P-square quantile

class P2:
    """Jain & Chlamtac's P-square estimator: one quantile, five markers, O(1).

    Holds no samples. The five markers track the min, the q/2, q, (1+q)/2 and
    max positions, and each new observation nudges them along a piecewise
    parabola. Memory is 10 floats regardless of how many samples pass through,
    which is the entire reason it can live on a microcontroller.
    """

    def __init__(self, q: float = 0.5):
        self.q = q
        self.n = []
        self.qs = []
        self.count = 0

    def push(self, x: float) -> None:
        if not np.isfinite(x):
            return
        self.count += 1
        if len(self.qs) < 5:
            self.qs.append(x)
            if len(self.qs) == 5:
                self.qs.sort()
                self.n = [0, 1, 2, 3, 4]
                self.np_ = [0, 2 * self.q, 4 * self.q, 2 + 2 * self.q, 4]
                self.dn = [0, self.q / 2, self.q, (1 + self.q) / 2, 1]
            return

        q_ = self.qs
        if x < q_[0]:
            q_[0] = x; k = 0
        elif x >= q_[4]:
            q_[4] = x; k = 3
        else:
            k = next(i for i in range(4) if q_[i] <= x < q_[i + 1])

        for i in range(k + 1, 5):
            self.n[i] += 1
        for i in range(5):
            self.np_[i] += self.dn[i]

        for i in range(1, 4):
            d = self.np_[i] - self.n[i]
            if (d >= 1 and self.n[i + 1] - self.n[i] > 1) or \
               (d <= -1 and self.n[i - 1] - self.n[i] < -1):
                s = int(np.sign(d))
                # parabolic prediction, falling back to linear if it would
                # break the ordering of the markers
                a = (self.n[i] - self.n[i - 1] + s) * (q_[i + 1] - q_[i]) / \
                    (self.n[i + 1] - self.n[i])
                b = (self.n[i + 1] - self.n[i] - s) * (q_[i] - q_[i - 1]) / \
                    (self.n[i] - self.n[i - 1])
                cand = q_[i] + s * (a + b) / (self.n[i + 1] - self.n[i - 1])
                if q_[i - 1] < cand < q_[i + 1]:
                    q_[i] = cand
                else:
                    j = i + s
                    q_[i] += s * (q_[j] - q_[i]) / (self.n[j] - self.n[i])
                self.n[i] += s

    @property
    def value(self) -> float:
        if len(self.qs) < 5:
            return float(np.median(self.qs)) if self.qs else float("nan")
        return float(self.qs[2])


def p2_scale(x: np.ndarray, var: str) -> np.ndarray:
    """Streaming median and MAD via two chained P-square sketches.

    20 floats of state per variable, against 720 floats for the exact window.
    """
    med_est, mad_est = P2(0.5), P2(0.5)
    med_out = np.full(len(x), np.nan)
    sig_out = np.full(len(x), np.nan)
    for i, v in enumerate(x):
        m = med_est.value
        if np.isfinite(m):
            mad_est.push(abs(v - m))
        med_out[i] = m
        sig_out[i] = max(1.4826 * mad_est.value, MAD_FLOOR_C * RESOLUTION[var]) \
            if np.isfinite(mad_est.value) else np.nan
        med_est.push(v)
    return med_out, sig_out


# ------------------------------------------------------------------ report

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_realistic.csv")
    ap.add_argument("--drift", type=float, default=0.02,
                    help="K/day hidden in the fitting window, for test 2")
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.timestamp < pd.Timestamp("2023-10-01", tz="UTC")]

    # ---- test 1: online vs batch, on clean data --------------------------
    rows = []
    for var in VARIABLES:
        for st, g in df.groupby("station_name", sort=True):
            g = g.sort_values("timestamp")
            X, y = harmonic_baseline(g, var), g[var].to_numpy(dtype=float)
            ok = np.isfinite(y)
            b_batch = _huber_irls(X[ok], y[ok])
            b_online = online_huber(X[ok], y[ok])
            r_batch = y[ok] - X[ok] @ b_batch
            r_online = y[ok] - X[ok] @ b_online
            rows.append({
                "variable": var, "station": st,
                "resid_sd_batch": float(np.std(r_batch)),
                "resid_sd_online": float(np.std(r_online)),
                "max_coef_diff": float(np.max(np.abs(b_batch - b_online))),
                "resid_corr": float(np.corrcoef(r_batch, r_online)[0, 1]),
            })
    t1 = pd.DataFrame(rows)
    print("=== TEST 1: one-pass online IRLS vs batch IRLS, clean data ===")
    print(t1.groupby("variable")[["resid_sd_batch", "resid_sd_online",
                                  "resid_corr", "max_coef_diff"]]
          .mean().round(4).to_string())
    print(f"\nworst residual correlation across all stations: "
          f"{t1.resid_corr.min():.4f}")

    # ---- test 2: does the fit survive a drift hidden in its own window? ---
    print(f"\n=== TEST 2: a {args.drift} K/day drift hidden in the FITTING "
          f"window ===")
    print("If the fit absorbs the drift, the residual goes flat and the station")
    print("reports healthy precisely because it is broken. That is the whole")
    print("reason the estimator has to be robust.\n")
    rows = []
    for st, g in df.groupby("station_name", sort=True):
        g = g.sort_values("timestamp")
        X = harmonic_baseline(g, "temp")
        y = g["temp"].to_numpy(dtype=float).copy()
        days = (g.timestamp - g.timestamp.min()).dt.total_seconds().to_numpy() / 86400
        y_drift = y + args.drift * days

        for name, fit in (("OLS", lambda A, b: np.linalg.lstsq(A, b, rcond=None)[0]),
                          ("batch Huber", _huber_irls),
                          ("online Huber", online_huber)):
            beta = fit(X, y_drift)
            resid = y_drift - X @ beta
            # how much of the injected ramp survives in the residual?
            slope = np.polyfit(days, resid, 1)[0]
            rows.append({"station": st, "estimator": name,
                         "drift_recovered_K_per_day": slope,
                         "fraction_recovered": slope / args.drift})
    t2 = pd.DataFrame(rows)
    print(t2.groupby("estimator")[["drift_recovered_K_per_day",
                                   "fraction_recovered"]].mean().round(4).to_string())
    print("\nfraction_recovered near 1.0 = the drift stayed visible in the "
          "residual (good).\nNear 0.0 = the baseline ate it (the failure mode).")

    # ---- test 3: P-square vs the exact trailing window --------------------
    print("\n=== TEST 3: P-square sketch vs exact 720-sample median/MAD ===")
    rows = []
    for var in VARIABLES:
        for st, g in df.groupby("station_name", sort=True):
            g = g.sort_values("timestamp")
            X, y = harmonic_baseline(g, var), g[var].to_numpy(dtype=float)
            r = y - X @ _huber_irls(X, y)
            s = pd.Series(r).shift(1)
            med_x = s.rolling(720, min_periods=24).median()
            mad_x = (s - med_x).abs().rolling(720, min_periods=24).median()
            sig_x = np.maximum(1.4826 * mad_x.to_numpy(),
                               MAD_FLOOR_C * RESOLUTION[var])
            _, sig_p = p2_scale(r, var)
            ok = np.isfinite(sig_x) & np.isfinite(sig_p)
            z_x = np.abs(r[ok]) / sig_x[ok]
            z_p = np.abs(r[ok]) / sig_p[ok]
            # the number that matters is not sigma, it is whether the SAME
            # samples end up above a 3-sigma line
            agree = float(np.mean((z_x >= 3) == (z_p >= 3)))
            rows.append({"variable": var, "station": st,
                         "sigma_ratio_p2_over_exact": float(
                             np.median(sig_p[ok] / sig_x[ok])),
                         "flag_agreement_at_3sigma": agree})
    t3 = pd.DataFrame(rows)
    print(t3.groupby("variable")[["sigma_ratio_p2_over_exact",
                                  "flag_agreement_at_3sigma"]]
          .mean().round(4).to_string())
    print(f"\nworst flag agreement across all stations: "
          f"{t3.flag_agreement_at_3sigma.min():.4f}")
    print("\nState: 20 floats (P-square) against 720 floats (exact window).")


if __name__ == "__main__":
    main()
