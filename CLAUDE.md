# SkyGuard — agent operating guide

Read this before touching code. It exists so that any teammate, or any AI agent
working on this repo, starts from the same constraints instead of rediscovering
them by breaking something.

Full reasoning lives in [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) and
[`docs/blueprint.html`](docs/blueprint.html) (open the HTML locally — it has the
architecture diagrams and dashboard wireframes).

---

## What this is

SIH 2026 **PS26073** (MoES / India Meteorological Department). Detect anomalies in
Automatic Weather Station data in real time using **only** temperature (°C),
atmospheric pressure (hPa) and relative humidity (%). Distinguish **genuine
meteorological events from sensor faults**, minimise false alarms, scale to a large
network.

Scoring is published: Innovation 25 · Accuracy 20 · Real-Time 15 · Explainability 10 ·
Scalability 10 · Deployability 10 · Visualization 5 · Energy 5. Evaluation is on
**anomaly-injected data**.

## Pipeline

```
1 RESIDUALISE   T,P,RH → Td, q  |  harmonic baseline  |  neighbour difference
2 PHYSICS       range · Hampel+return · frozen+cross-channel · conditional rate
3 LEARNED       6-dim residual vector · robust covariance · conformal p-value
4 SIGNATURE     match joint T/P/RH pattern → name WHICH fault or WHICH event
```

Stage 4 is the novelty. Stages 1–2 run on-station (integer arithmetic, O(1) state);
3–4 need neighbours so they run server-side.

---

## Hard rules — do not violate without discussion

1. **Never update the baseline online.** A climatology that refits on incoming data
   silently absorbs slow drift and makes it permanently undetectable. Fit on a frozen,
   verified-clean reference period; refit only on human-approved data.

2. **Physics flags, never filters.** A rejected sample must still reach the learned
   layer, or the learned layer can never reason about fault shape.

3. **Hour-of-day is local solar time.** `mean_solar_time = utc + longitude / 15`.
   India spans ~2 h of solar time; IST or UTC smears every diurnal baseline.

4. **Pressure needs elevation reduction before neighbour comparison.** ~1 hPa per
   8–9 m. Confirm whether the feed gives station pressure or MSLP — get this wrong and
   every hill station looks broken.

5. **Floor the MAD.** `σ̂ = max(1.4826·MAD, c·resolution)`, c ≈ 0.5–1.0. On quantized
   data MAD hits exactly zero on calm nights and the z-score goes infinite.

6. **Robust statistics everywhere.** Median/MAD not mean/σ; Huber or Theil–Sen not OLS.
   The history contains unlabelled faults — otherwise you fit what you are trying to detect.

7. **Emit `unknown`** rather than forcing a fault label. A confidently wrong root cause
   destroys operator trust faster than an honest "cause unclassified".

8. **Harness before model.** Nothing gets built in `detect/` or `signature/` until
   `evaluation/` can score it.

9. **`physics/` stays dependency-free.** Pure arithmetic over floats — no pandas, no
   sklearn. It must transliterate to C++ for the ESP32.

10. **Version-stamp detector, explainer and calibrator on every alert.** An explanation
    that cannot be reproduced is not an audit trail.

---

## Known-wrong things — do not reintroduce

- **`Td ≤ T`, `RH ≤ 100 %` and `e ≤ e_s(T)` are the same inequality.** When `Td` is
  computed from T and RH via Magnus, they are algebraically identical. Presenting them
  as three physics checks is a factual error. Keep **one** range check on RH, with
  propagated instrument uncertainty.
- **Do not put derived quantities in the SHAP feature set alongside their parents.**
  `Td` is an exact function of T and RH; including all three makes every attribution
  look small and meaningless.
- **Mahalanobis is a point detector.** Structurally blind to frozen, dropout, drift and
  noise burst — four of seven fault classes. Do not centre the architecture on it.
- **No Weibull / survival RUL.** No failure-history dataset exists; any hazard curve
  would be fabricated. Linear drift extrapolation with honest intervals only.
- **No transformer, no GNN, no LSTM autoencoder** unless it beats median/MAD on the
  harness and you can show the curve.
- **Supervised learning on injected labels — tried, measured, rejected.** Gradient
  boosting over the same six features (`detect/supervised.py`,
  `signature/supervised.py`); both are kept as documented negative results and are
  **off by default**. Reproduce with `python -m evaluation.run_supervised` and
  `python -m evaluation.run_signature_ml`.
  - *Detection*: no consistent win, and adding it as a fourth ensemble channel
    **hurt** pressure (PR-AUC 0.282 → 0.207). Leave-one-fault-type-out gap
    **+0.161**; `calibration_drift` on pressure fell from 1.00 recall to **0.00**
    when the class was withheld. It was recognising the injector's linear ramp,
    not drift.
  - *Naming*: **0.500 vs 0.710** for the hand-written templates, and it never
    abstains — 0 % `unknown` against the templates' 38 %. Withhold a class and it
    is *confidently wrong* on 100 % of `calibration_drift`, `dropout` and
    `frozen` windows. That is precisely the failure rule 7 exists to prevent.
  - The labels describe `inject/faults.py`, not IMD's sensors. Any future
    supervised model must pass leave-one-fault-type-out before it is believed.

---

## Conventions

- Python 3.11, CPU only. No GPU anywhere in this design.
- Robust estimators by default. If you use a mean, justify it in a comment.
- Every detector declares whether it is **causal or centred**, and the latency it costs.
- Fault taxonomy is fixed: `spike`, `frozen`, `dropout`, `saturation`, `step_offset`,
  `calibration_drift`, `noise_burst`, plus `unknown`.
- Health states are fixed: `HEALTHY`, `WATCH`, `DEGRADING`, `SUSPECT`, `FAILED`/`SILENT`.
- `observation_flags` (per timestamp, ephemeral) and `sensor_health` (per station per
  variable, sticky) are **separate objects**. Never derive health from a single event.
- Station health roll-up is the **minimum** of the three variables, not the mean.

## Metrics — report these, not accuracy

- **PR-AUC**, never ROC-AUC (prevalence is well under 1 %).
- **POD vs amplitude curve**; headline the minimum detectable amplitude at 90 % POD.
- **Event-level and point-level** recall both; the gap is informative.
- **False alarms per station-day, split by weather activity** (quiet vs active).
- **Time-to-detection distribution** per fault type.
- Compare methods **at a fixed alert budget** (e.g. 1 alert/station/week).
- Split by **whole stations and whole time periods**, never random points.

---

## Must be verified by a human — do not assume

These can each invalidate a subsystem. Nothing in the blueprint substitutes for checking.

- Station pressure or MSLP in the feed?
- Sentinel values (`-999`, `-9999`, `0.0`) and existing QC flags — audit ingest first.
- Reporting cadence and sensor resolution (sets every window and the MAD floor).
- Published accuracy specs for the actual probes (the physics-confidence maths needs them).
- Instrument spec tolerances (TTOS is meaningless without them).
- σ of the inter-station difference series by distance, hour, month — this table *is*
  the neighbour-selection rule and the threshold table.
- **Station density / usable correlation radius.** This is the project's biggest risk;
  answer it in week one, before writing the injector.
- Residual autocorrelation and the real ARL₀ for CUSUM.
- WMO/IMD QC document numbers before citing any of them. **Do not cite what you have
  not read.**

## Current status

Pre-Phase-0. Nothing has been built or measured. Any number in the blueprint is a
target or a simulation, never a result.
