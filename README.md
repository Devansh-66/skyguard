# SkyGuard

**Intelligent real-time anomaly detection for Automatic Weather Stations.**

SIH 2026 · Problem Statement **26073** · Ministry of Earth Sciences / India Meteorological Department

---

## The problem

AWS observations contain anomalies from sensor malfunction, communication failures,
calibration drift, power fluctuations and data corruption. Threshold-based quality
control misses the complex ones.

Detect them in real time using **only three parameters** — temperature (°C),
atmospheric pressure (hPa), relative humidity (%) — while distinguishing **genuine
meteorological events from sensor faults**, minimising false alarms, and scaling
across a large station network.

## The approach

Physics decides first; the model learns only what physics could not.

```
1 RESIDUALISE   T,P,RH → Td, q   |  harmonic baseline  |  neighbour difference
2 PHYSICS       range · Hampel+return · frozen+cross-channel · conditional rate
3 LEARNED       6-dim residual vector · robust covariance · conformal p-value
4 SIGNATURE     match the joint T/P/RH pattern → name WHICH fault or WHICH event
```

The novelty is stage 4. Operational QC tells you a value is wrong; this names the
failure mode, states a calibrated confidence, and predicts when the sensor needs
servicing.

Two facts that shape everything:

- **Cross-channel coherence separates weather from faults.** A real front moves all
  three parameters in a physically consistent pattern. A failing sensor moves one.
- **Neighbour differencing is where accuracy comes from.** In simulation it cut the
  daily-mean noise floor by ~20×, taking drift detection latency from ~269 days to 14.
  That gain came from a subtraction, not a model.

## Layout

| Path | Contents |
| --- | --- |
| `physics/` | Stage 2 — pure functions, **zero dependencies** (ports to ESP32) |
| `residual/` | Stage 1 — harmonic baselines, neighbour selection, solar time |
| `detect/` | Stage 3 — CUSUM, Page-Hinkley, dispersion, Mahalanobis |
| `signature/` | Stage 4 — the fault + event classifier |
| `health/` | Sensor health state machine, time-to-out-of-spec |
| `explain/` | Exact Shapley, grouped attribution, counterfactuals |
| `inject/` | Fault generator with ground truth |
| `evaluation/` | The harness — **build before any model** |
| `api/` | FastAPI service, WebSocket alert stream |
| `dashboard/` | React + MapLibre, three screens |
| `firmware/` | ESP32 edge tier, mirrors `physics/` |
| `data/` | Station history, cached (gitignored) |

## Build order

Phase 0 is not optional — half a day here prevents three weeks of wrong results.

0. **Ingest audit** — sentinel values, station-vs-MSLP pressure, cadence, resolution, local solar time
1. **Residual layer** — everything downstream depends on this being right
2. **Physics screen** — deterministic, testable, no training data
3. **Injector and harness** — *before any modelling*
4. **Detectors** — benchmark each against median/MAD and publish the losses
5. **Signature classifier** — the novelty
6. **Explainability** — uncertainty propagation, exact Shapley, calibration
7. **Health state and TTOS**
8. **Dashboard and scale test**
9. **Hardware stations** (optional, ≈₹1,120 each)

## Non-negotiables

- **Harness before model.** Otherwise no number you produce is comparable.
- **Never update the baseline online.** It silently absorbs drift and makes it
  permanently invisible.
- **Physics flags, never filters.** Rejected samples must still reach the learned layer.
- **Emit `unknown`** rather than forcing a fault label.
- **Hour-of-day in local solar time**, referenced to longitude — India spans ~2 hours of it.

## Deliverable

Per the problem statement: *fully executable code with example usage, and a document
explaining various use cases.* Not a prototype and slides.

## Status

Pre-Phase-0. Nothing measured yet.
