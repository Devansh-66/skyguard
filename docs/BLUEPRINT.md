# SkyGuard Blueprint

**SIH 2026 · PS26073 · Ministry of Earth Sciences / India Meteorological Department**

> Open [`blueprint.html`](blueprint.html) locally for the full version — it carries the
> architecture diagram, the transformation chain with worked numbers, the accuracy
> figure, and the three dashboard wireframes. This Markdown digest holds the substance
> for reading on GitHub and for agent consumption.
>

---

## 1. The problem statement

Detect abnormal, inconsistent or faulty observations from Automatic Weather Stations in
real time, using **only** Temperature (°C), Atmospheric Pressure (hPa), Relative
Humidity (%). Distinguish genuine meteorological events from sensor/data anomalies while
minimising false alarms and enabling scalable deployment across large networks.

**Objectives:** real-time detection · identify sensor faults, spikes, frozen values,
communication errors · learn normal temporal and seasonal patterns · multivariate
consistency analysis · confidence scores and explainable reasoning · predict sensor
degradation and maintenance needs · optionally suggest corrected values.

**Required outputs:** real-time alerts · severity and confidence scores · root-cause
classification · visualization dashboard · sensor health status · corrected data (optional).

**Final deliverable:** *"Fully executable code with example usage and a document
explaining various use cases."* Not a prototype and slides.

### Scoring — published by the organisers

| Criterion | Weight | What earns it here |
|---|---:|---|
| Innovation & Novelty | **25%** | A signature classifier that names *which* fault or *which* event |
| Detection Accuracy | **20%** | Neighbour-difference channel; POD-vs-amplitude curves |
| Real-Time Capability | 15% | O(1) streaming state; published latency distributions |
| Explainability | 10% | Uncertainty-propagated physics confidence; exact Shapley |
| Scalability | 10% | Per-station auto-calibrated thresholds |
| Practical Deployability | 10% | Integer-arithmetic edge tier |
| Visualization / UI | 5% | Three screens: board, judgement, planner |
| Energy Efficiency | 5% | Measured uplink reduction |

Evaluation is on **anomaly-injected data**.

> **Innovation (25) + Explainability (10) outweighs Accuracy (20).** A classifier that
> names the fault and shows the physical reason scores on all three at once. A rarity
> score scores on one. That drives the architecture.

---

## 2. Three corrections that shaped this plan

An earlier draft got these wrong. They are recorded because the corrections teach more
than the original.

**The dew-point check was a tautology.** `Td ≤ T`, `RH ≤ 100 %` and `e ≤ e_s(T)` are
algebraically the same inequality when `Td` comes from T and RH via Magnus. Verified
numerically: `Td − T` is exactly 0 at RH = 100 %, negative below, positive above, at
every temperature. The old flagship example (`Td 33.1 °C, T 31.2 °C`) implies a reported
**RH of 111 %** — a range check, dressed up.

**The two-layer split is not the innovation.** Every physics-screen element is a named,
standardised operational QC test — gross-error, persistence, step/temporal-consistency,
internal-consistency, spatial-consistency (buddy) checks. An IMD reviewer recognises the
suite on sight. It stays as the credibility floor; it stops being the pitch.

**Health is a state, not an event.** "This reading is bad" and "this sensor is
deteriorating" are different objects with different lifetimes and need separate storage.

---

## 3. The one problem that matters

> *Distinguish between genuine meteorological events and sensor/data anomalies.*

A real weather event looks statistically like an anomaly. A cold front produces a sharp
pressure fall, a temperature fall and a humidity rise — three simultaneous multivariate
excursions. Flag enough real fronts and IMD stops trusting the system.

### The discriminator is cross-channel coherence, not magnitude

| Phenomenon | Joint signature across T / P / RH | Timescale |
|---|---|---|
| Thunderstorm gust front | Sharp T drop + RH jump + **pressure jump** (meso-high) | minutes |
| Synoptic front | P falls smoothly, T follows, RH rises; neighbours see an advection lag | hours |
| Monsoon onset | Sustained RH rise + compressed T diurnal range + modest P change | days |
| Heat wave | Sustained high T + low RH + persistent ridge; spatially broad | days |
| **T sensor step** | **T only. Nothing else moves.** Physically impossible for weather | instant |
| **RH element wetting** | RH pins at 100 % while T climbs away from `Td(onset)` | hours |

The rule inverts from *rarity ⇒ anomaly* to **rarity + wrong physical signature ⇒ fault**.

---

## 4. The physics you actually have

Only the first row is a hard impossibility. The rest are strong statistical-physical
regularities — label them as such.

| Relation | What it is | Catches |
|---|---|---|
| `RH > 100 %` (≡ `Td > T`) | **Hard impossibility** — one check, with propagated uncertainty | Gross RH failure, corrupt records |
| Dew point as airmass property | `Td` varies far less than T or RH over a diurnal cycle | T/RH faults that break `Td` smoothness |
| **Specific humidity `q`** | Conserved under dry adiabatic processes. **Needs all three parameters** | Turns the 3-parameter limit into a design choice |
| T–RH anti-correlation | Strongly negative at a healthy station; collapses toward 0 when RH sticks | RH degradation, O(1) streaming |
| Semidiurnal pressure tide (S2) | Solar-locked, strongest and most stable in the tropics | Pressure faults; distinctive for India |
| Saturation onset divergence | Genuine saturation has `T ≈ Td`; a wetted element stays pinned while T climbs away | **Separates fog from a failed RH sensor** |
| Spatial coherence *with advection* | Real fronts propagate with a lag consistent with distance | Strongest fault-vs-event signal |

### Worked: why `Td` and `q` are the useful variables

One airmass through a day's heating, computed not asserted:

```
   T (C)   RH (%)      Td (C)      q (g/kg)
   22.0     88.0       19.92         14.48
   28.0     64.0       20.55         15.07
   34.0     47.0       21.09         15.59
   30.0     57.0       20.55         15.07
   24.0     79.0       20.13         14.67

   swing:  12.0 K     41 pts        1.2 K        1.1 g/kg
```

The sensor reports T and RH. The *airmass* is described by `Td` and `q`. Model the second.

This is also the **radiation-shield discriminator**: a failed shield or lost aspiration
warms T and drops RH in a way that leaves `Td` approximately correct, whereas real
advection moves `Td`.

---

## 5. Detection, fault by fault

The largest single accuracy gain is switching the primary channel from the raw residual
to the **neighbour-difference series**, elevation-corrected. Weather cancels there.

| Fault | Detector | The discriminator that matters |
|---|---|---|
| Spike | Hampel filter, k = 5–11 | Excursion **and return** — without the return test, the first sample of a step reads as a spike |
| Frozen | Adaptive run-length | **Are the other two channels still moving?** Calm air flattens all three; a stuck sensor flattens one |
| Dropout | Gap + sentinel detection | Bit-identical across all three channels is essentially never natural → comms, not sensor |
| Saturation | RH pin + divergence test | T climbing away from `Td(onset)` — the **fog discriminator** |
| Step offset | CUSUM on neighbour-difference | Level shift, diurnal shape and variance unchanged, no recovery |
| Drift | Page-Hinkley on daily-mean difference | **Monotonically growing** divergence from neighbours |
| Noise burst | Rolling MAD-ratio / moving-range chart | Variance changes while the mean does not |

### Drift, honestly

Sensor aging drift is ~0.01–0.05 K/day; weather variability is two to three orders of
magnitude larger. Only neighbour-differencing fixes that.

**Publish the latency-versus-slope curve.** A team reporting *"3–6 weeks at 0.02 K/day,
here is the measured curve"* is far more credible than one claiming real-time drift
detection.

**What cannot be done statistically:** separate sensor drift from a genuine environmental
change — vegetation growth, a new building, a resited screen. Route it to metadata and
human confirmation, and say so.

---

## 6. The ML layer

### Four prediction targets, not one

| Task | Question | Type | Labels from | Output |
|---|---|---|---|---|
| **A** | Is this observation valid? | Binary, per record | Unsupervised + injection | `p_invalid = 0.94` |
| **B** | Which fault is it? | Multiclass, 7 + unknown | **Supervised — your injector** | `frozen 0.71 · drift 0.19` |
| **C** | What should the value have been? | Regression | Neighbours (self-supervised) | `62.5 % ± 1.8` |
| **D** | When will it exit spec? | Regression on slope | Drift fit | `47 d (18–140)` |

Health score is **not** a prediction — it is a state accumulated from A and B.
**Task B is where the 25 % lives**, and it is the only cleanly supervised problem —
because *you* generate the labels by injecting faults.

### Feature vector

```python
z = [ z_Td, z_q, z_P,           # residual levels (robust z, σ floored at resolution)
      Δz_Td, Δz_q, Δz_P ]       # 1-hour tendencies
+ [ d_T, d_P, d_RH,             # neighbour differences
    run_length, disp_ratio,     # frozen / noise-burst evidence
    corr_T_RH_24h,              # anti-correlation health
    n_neighbours_confirming ]
```

Twelve numbers. That is the model input.

### Models

**Task A — is it valid?**

| Model | Verdict |
|---|---|
| Robust z-score (median/MAD) | **Start here — the benchmark everything must beat** |
| Kalman / structural state-space | **Recommended.** Level + trend + seasonal in one recursive model; drift is literally a state you read off; O(1) memory |
| CUSUM / Page-Hinkley | **Recommended.** Correct trigger for step and drift |
| Mahalanobis + robust covariance | Partial — blind to frozen, dropout, drift, noise burst |
| Matrix Profile (STUMPY) | Worth a look — discord discovery, CPU-friendly |
| Isolation Forest / HS-Trees / RRCF | Timebox. Black box, costs explainability |
| LSTM / VAE autoencoder | **Avoid.** Everyone else's submission; most data, least explanation |
| One-Class SVM / LOF | **Avoid.** Won't scale |

**Task B — which fault?**

| Model | Verdict |
|---|---|
| **Gradient boosting** (LightGBM/XGBoost) | **Recommended** — TreeSHAP gives exact cheap attributions |
| **MiniRocket / ROCKET** | **Strong** — near-SOTA time-series classification, seconds to train on CPU |
| Random Forest | Fine |
| Logistic regression | Baseline — publish it |
| 1D CNN / InceptionTime | Overkill |
| Shapelets | Too slow to train |

**Tasks C & D** — neighbour-weighted regression and low-rank matrix completion for
imputation; Theil–Sen or Huber (robust is mandatory) or Kalman-with-drift-state for TTOS.
**No Weibull.**

### Where accuracy actually comes from

Simulation: 180 days, three stations, 0.02 K/day drift injected on day 60.

```
sigma of daily mean, SINGLE STATION       : 1.7958 K
sigma of daily mean, NEIGHBOUR-DIFFERENCE : 0.0875 K
noise reduction                           :  20.5x

single station  : NOT DETECTED in 120 days
neighbour-diff  : detected at day 14  (0.28 K accumulated)
```

**That gain came from a subtraction, not a model.** No architecture choice on Task A buys
an improvement of that size.

*Caveat: the simulated neighbours share an identical seasonal signal by construction, so
real-world gain will be smaller. Measure your own σ.*

---

## 7. Explainability

**Physics-propagated confidence** is the strongest result available and needs **no
training labels**. A violation is not automatically probability 1 — propagate the probe
accuracies through Magnus and:

```
confidence = Φ( margin / u_margin )
```

So an alert reads *"exceeds by 11.3 points; combined uncertainty ±2.7 %; 4.2σ"*. This
also auto-suppresses marginal-violation false alarms at high humidity.

**Exact Shapley, not approximate.** At 6–8 features that is 64–256 coalitions —
microseconds. KernelSHAP's sampling exists for d ≈ 200; using it here is strictly worse.
Use the **conditional** value function for Mahalanobis, `v(S) = z_Sᵀ (Σ_SS)⁻¹ z_S`.

**Grouped Shapley** over 3–4 groups for the operator view; per-feature in the analyst
drill-down.

**Three separate fields, never one blended number:**

| Field | Means |
|---|---|
| `p_invalid` | P(sensor artefact rather than real weather) |
| `p_rootcause[label]` | Distribution over fault types, given invalid |
| `false_alarm_bound` | Conformal p-value — **not a confidence, never display as one** |

Calibrate with isotonic regression; prove it with a **reliability diagram** (15
equal-mass bins) plus ECE and Brier. Watch the **base-rate trap**: injecting at 50 %
prevalence when the real rate is ~10⁻³ makes a calibrated 0.7 meaningless.

---

## 8. Sensor health

Two separate objects:

| Object | Grain | Lifetime |
|---|---|---|
| `observation_flags` | Per timestamp, per variable | Ephemeral — an event |
| `sensor_health` | **Per station, per variable** + roll-up | Persistent — a state |

Station roll-up is the **minimum** of the three variables, not the mean.

**Five components:** physical-plausibility rate (0.25) · bias/drift magnitude (0.25) ·
availability (0.20) · noise character (0.20, penalise `|log(σ_recent/σ_baseline)|` in
**both** directions) · spatial coherence (0.10, low weight — confounded by microclimate).

**Five states:** `HEALTHY` ≥85 · `WATCH` 70–85 · `DEGRADING` 50–70 · `SUSPECT` 25–50 ·
`FAILED`/`SILENT` <25. Distinguish SILENT from FAILED visually — the remedy differs.

**Asymmetric EWMA**: degradation must register faster than recovery. Only a logged
calibration event resets health quickly. Add hysteresis so stations don't flap.

### Bad reading vs deteriorating sensor vs genuine weather

| | Bad reading | Deteriorating | Genuine weather |
|---|---|---|---|
| Duration | seconds–minutes | days–weeks, monotone | minutes–hours |
| Neighbours | disagree | disagree, gap **grows** | agree, with advection lag |
| Recovery | returns to baseline | never returns | returns along a physical trajectory |
| Cross-variable | usually one variable | usually one variable | **coherent across T/P/RH** |

### Time-to-out-of-spec

```
TTOS = ( spec_limit − |b0_now| ) / |b1|      report the interval, always
```

Robust regression (Huber/Theil–Sen) **mandatory**. Present as `≈ 47 days (18–140)`.
**TTOS predicts specification excursion, not failure** — label it that way. Below ~30
days of history show *"insufficient history"*.

Sort the work queue by `urgency × criticality × (1 / accessibility_cost)`, and add a
**"nearby also due"** indicator — a field engineer's constraint is travel, not sensors.

---

## 9. Dashboard — three screens

**Network board.** Five counters; map at 60 % (colour = health state, size encodes
nothing, hex clusters coloured by **worst** state); triage queue at 40 % sorted by
severity × confidence, ~28 px rows, each carrying a 24 h residual sparkline. Link map
and queue bidirectionally.

The sparkline *shape* is the diagnosis: ramp → drift, flat-then-step → offset event,
dead-flat at non-zero → frozen, single needle → spike.

**Station detail.** Verdict card in plain sentences first, then three **x-axis-linked**
panels for T, P, RH with expected bands and flagged intervals. Shared time is the point —
a genuine front moves all three; an RH failure does not move pressure.

**Maintenance planner.** Priority-sorted work queue plus a 90-day horizon strip that
converts a table into a staffing plan.

**Avoid:** chart galleries, demos on three stations, refresh buttons instead of live
updates, everything red from untuned thresholds, missing empty/loading/error states.

---

## 10. Evaluation

| Metric | Why this one |
|---|---|
| Per-fault-type table | Aggregate F1 hides drift entirely |
| **PR-AUC, not ROC-AUC** | At <1 % prevalence ROC-AUC flatters a useless detector |
| Alerts per station-day | Prevalence-free; precision is not |
| **FPR split by weather activity** | 0.1/day overall but 8 during monsoon onset is unusable |
| Event-level *and* point-level | Point-level lets one drift contribute thousands of TPs |
| **Placebo events of matched duration** | Event-level any-overlap has the *opposite* bias — see below |
| Time-to-detection distribution | The Real-Time evidence |
| Calibration error (ECE, Brier) | Confidence is a scored output |

**Fix the alert budget across all methods compared.** Split by **whole stations and whole
time periods**, never random points.

### Event-level recall has its own duration bias — measured

Point-level scoring inflates recall on long faults, so the obvious fix is to score at the
event level with any-overlap: the event counts as detected if the detector fires even once
inside it. That fix has a bias of its own, in the opposite direction, and it is large.

At an alert budget of one per station per week, a *clean* 640-hour window already expects
~3.8 alerts. P(at least one) is 0.98 **whether or not a fault is there**. Any-overlap
therefore credits long events for detection they did not earn.

The control is a **placebo event**: same station, same duration, placed on a window with no
injected fault at all. Recall on placebos is the floor the metric hands you for free.
Report the **excess** — real minus placebo. Measured here (`evaluation/run_placebo.py`,
1 alert/station/week, 480 placebos per variable):

| Event duration | Real recall | Placebo | **Earned** |
|---|---|---|---|
| < 6 h (spikes) | 0.40 | 0.006 | **0.394** |
| 6–24 h | 0.80 | 0.105 | **0.695** |
| 1–4 d | 0.67 | 0.160 | **0.507** |
| 4–16 d | 0.83 | 0.347 | **0.487** |
| > 16 d | 1.00 | 0.526 | **0.474** |

*(temperature; pressure at 6–24 h is the strongest cell measured — 1.000 real against 0.010
placebo, earning 0.990.)*

Short faults are earned almost entirely. Long ones are not: a headline
`calibration_drift recall 1.00` is about half event length. And two cells are honest
failures — **relative humidity earns 0.011 at 4–16 days and −0.053 beyond 16 days**, i.e.
on long humidity faults this pipeline does no better than firing at random. That number is
reported rather than dropped, because a metric that cannot fail is not measuring anything.

**Rule:** never quote an event-level recall without the placebo floor beside it.

### Injection realism

Sweep magnitude and report a **POD-vs-amplitude curve**; headline the minimum detectable
amplitude at 90 % POD. Include sub-threshold magnitudes, hard cases (freeze at a value
plausible for that hour; pin RH at 99.9 or 100.5, not exactly 100), all four onset shapes
including **intermittent/flapping**, injections **during real weather events**,
multi-fault combinations, and matched clean negative controls.

---

## 11. Traps

| Trap | Consequence |
|---|---|
| **Online baseline updating** | **Slow drift absorbed into the baseline, permanently invisible.** The most dangerous item here |
| MAD = 0 on quantized data | Infinite z-score; floods false spikes on the calmest nights |
| Raw pressure neighbour comparison | ~1 hPa per 8–9 m; every hill station looks broken |
| Hour-of-day in UTC or IST | India spans ~2 h of solar time; smears every diurnal baseline |
| Fixed rate limits | Fire constantly in the pre-monsoon convective season |
| Night-time T neighbour comparison | Nocturnal decoupling makes differences large and non-stationary |
| Physics layer *filtering* | Learned layer can never reason about fault shape |
| Sentinel values | `-999` parsed as real poisons every baseline |
| MCD on contaminated data | Masking — covariance absorbs the anomalies |
| CUSUM ARL assumptions | Assume independence; met residuals are strongly autocorrelated |
| Centred-window detectors | Cost half-window latency — declare causal vs centred |

---

## 12. Build order

| Phase | Work |
|---|---|
| **0** | **Ingest audit** — sentinels, station-vs-MSLP, cadence, resolution, solar time. Half a day that prevents three weeks of wrong results |
| 1 | Residual layer — harmonic baselines, neighbour selection, elevation reduction |
| 2 | Physics screen — deterministic, testable |
| 3 | **Injector and harness — before any modelling** |
| 4 | Detectors — benchmark each against median/MAD, publish the losses |
| 5 | Signature classifier — the novelty |
| 6 | Explainability — uncertainty propagation, exact Shapley, calibration |
| 7 | Health state and TTOS |
| 8 | Dashboard and scale test |
| 9 | Hardware stations (optional, ≈₹1,120 each) |

### MVP — a walking skeleton

**One demo, working:** replay a real cold front → *nothing flags*. Inject a fault of the
same magnitude → *flags instantly, names it, says why it is not weather*.

One station + 3 neighbours, ~3 months. Three physics checks, three fault types, rules-only
signature classifier, terminal verdict card. **Done means:** a POD-vs-amplitude curve for
three faults, zero flags across the held-out front, an alerts-per-station-day figure, and
a verdict card with a named root cause.

**Do not** build the dashboard first, reach for an LSTM, or buy hardware yet.

---

## 13. Execution reality

**The injector is the largest line item** — roughly a third to 40 % of effort. That is
correct, not overhead: evaluation happens on injected data, so the injector *is* the
instrument producing every number you quote. It parallelises cleanly, and it builds in
tiers.

**Station density is the gate.** The whole spatial thesis assumes neighbours close enough
to be correlated. Compute σ of the pairwise difference series against distance in **week
one**, before writing the injector. If the radius is poor, much of the design falls back
to single-station self-consistency — and you want to know that while there is time.

**Two correctness traps that look like difficulty traps:** local solar time is three
lines (`utc + lon/15`; the equation of time swings ±16 min, well inside an hourly bin) —
the risk is forgetting it. MSLP is a *question* before it is maths.

**Sequencing rule:** harness before model, always.

---

## 14. Verify before you build

Nothing here substitutes for checking. Each can invalidate a subsystem.

- Station pressure or MSLP in the feed?
- Sentinel values and existing QC flags — audit ingest first
- Reporting cadence and sensor resolution
- Published probe accuracy specs and spec tolerances
- σ of inter-station difference by distance/hour/month — this table *is* the
  neighbour-selection rule
- **Station density / usable correlation radius** — the biggest risk
- Residual autocorrelation and the real ARL₀ for CUSUM
- Real fault base rate, for the prior correction
- WMO/IMD QC document numbers — **do not cite what you have not read**
- Whether IMD already runs an internal QC system, and its terminology

---

## 15. Production architecture

### The scale numbers come first

IMD operates on the order of **2,000 AWS stations** *(verify the current figure)*. At
15-minute reporting:

```
stations                        2,000
records / day                 192,000
records / year             70,080,000
raw bytes / year                 3.50 GB
compressed (~10x)                 350 MB
10 years compressed              3.50 GB

average ingest rate              2.22 rec/s
quarter-hour burst              2,000 records
  burst clear @ 200 us/rec, 1 core       0.40 s
```

**This is not a big-data problem.** A decade of national observations fits on a laptop
SSD; the quarter-hourly burst clears in under half a second on one core. Anyone proposing
Kafka, Spark and a cluster is overengineering it, and a domain judge will know. *Budget
those per-record timings, then measure them.*

### Topology

```
  STATION (RTU/ESP32)  physics screen only, integer arithmetic, O(1) state
        │              transmits flagged records + health digest
        ▼
  ┌─ ON-PREMISE / NIC CLOUD BOUNDARY ─────────────────────────────┐
  │  INGEST ──► WORKERS ×2-4 (stateless)                          │
  │  validate    residual · detect · signature · health · explain │
  │  dedupe            │              │                            │
  │  sentinels         ▼              ▼                            │
  │              TimescaleDB      Redis (current state)            │
  │              observations     2,000 small objects              │
  │              flags · alerts        │                           │
  │              health · tasks        ▼                           │
  │                            FastAPI ──WS──► Dashboard           │
  │                                                                │
  │  OFFLINE (weekly, never in request path):                      │
  │  training · calibration · baseline refit on APPROVED data only │
  └────────────────────────────────────────────────────────────────┘
```

Everything inside the boundary runs on **one modest VM** — 4–8 vCPU, 16 GB RAM. Workers
are stateless so you *can* scale out; at national scale you will not need to. **No GPU, no
model server, no message-broker cluster.**

> A national met agency will not put operational observations on a public-cloud SaaS.
> Designing for **on-premise** — and saying so — reads very differently from assuming a
> cloud provider and hoping nobody asks.

### Database — PostgreSQL + TimescaleDB

| Requirement | Why Timescale |
|---|---|
| Time-series partitioning | Hypertables, no partition management code |
| Chart rollups | Continuous aggregates maintain hourly/daily views |
| Storage | ~10× compression — 3.5 GB for a decade nationally |
| **Joins** | **You need them** — alerts → stations → health → tasks. A pure TSDB fights you |
| Deployability | Open source, installs inside a government network |

Not InfluxDB (weak relationally, licensing shifted), not ClickHouse (excellent
analytically, but you need transactional alert state). Plain PostgreSQL is genuinely fine;
Timescale mainly saves writing rollup logic.

### Where the ML runs

| Tier | Runs | Why there |
|---|---|---|
| Station | Physics screen only | Instant hard-fault detection, survives a dead link, cuts uplink. **No model, no ML runtime** |
| Server, online | Residual · detectors · signature · health · explain | Needs neighbour data |
| Server, offline | Training · calibration · baseline refit | Weekly, never in the request path |

**Inference needs no model server.** LightGBM on 12 features is microseconds — load the
model into the worker at startup as a versioned artifact. TF Serving or Triton would be a
liability to defend, for zero gain.

### Migration path — the code does not change

Keep the data-access layer thin (plain SQL or SQLAlchemy Core; SQLite and PostgreSQL both
speak it), then swap implementations behind the same interfaces.

| | Prototype now | Production later |
|---|---|---|
| Database | SQLite file (or DuckDB) | TimescaleDB |
| Current state | Python dict in-process | Redis |
| Process model | One `uvicorn` serving the React build | Ingest + workers + API |
| Deploy | `docker compose up` | Same compose file, more services |
| Demo | **Local laptop, zero network** | On-premise VM |

**Do not build the production topology now.** Two people building ingest queues and worker
pools will spend the timeline on infrastructure and arrive with nothing to demonstrate.

**For the finals demo: run locally.** Venue Wi-Fi failing mid-demo is a documented way to
lose. Hosting is for teammates and pre-round submission, not for the room.

### The line to say out loud

> *"Two thousand stations at fifteen-minute cadence is 70 million records a year and 2.2
> records a second. The entire national network's real-time quality control fits in a
> fraction of one CPU core, on one on-premise VM, with no GPU anywhere. We chose methods
> that make that true rather than methods that would need a cluster."*

Answers Scalability (10 %), Deployability (10 %) and Energy (5 %) in one breath — and it
is stronger than any architecture diagram, because it is measured rather than asserted.

---

## Measured so far

The sections above are design. These are results from the built pipeline, on ERA5 degraded
to AWS realism with injected labelled faults. They supersede any target stated above.

| Result | Measured | Where |
|---|---|---|
| Earned event recall, by duration | 0.394 → 0.474 (see §10) | `evaluation/run_placebo.py` |
| RH, faults longer than 16 d | **−0.053 earned — no better than random** | `evaluation/run_placebo.py` |
| σ, daily-mean neighbour difference | 0.876 K | `evaluation/run_cadence.py` |
| Drift latency at 0.02 K/day, 3σ | **131 days** | `evaluation/run_cadence.py` |
| Cadence dependence, 15 min → 6 h | σ 0.875 → 0.921 K; latency 131 → 138 d | `evaluation/run_cadence.py` |

**The drift latency is weeks, not real time, and that is the honest answer** — §7 predicted
exactly this and it is confirmed rather than assumed.

**Cadence-independence matters for deployment.** A 24× change in sampling rate moves σ by
5 %, so the drift result describes a physical timescale and transfers to the 15-minute
cadence real AWS report at. But **every window in the code is expressed in samples**: at
15-minute data the 720-sample scale window is 7.5 days rather than 30, and the 24-sample
Hampel window is 6 hours rather than a full diurnal cycle — it would no longer contain the
cycle it exists to normalise against. Any redeployment must rescale windows by *time*.

*Caveat on the 15-minute arm: ERA5 has no sub-hourly variability to resample, so that arm
is explicitly synthetic. It answers "do the windows scale", not "how good are we on real
15-minute data".*

---

*Design sections are a blueprint and their success criteria are targets. The "Measured so
far" table above, and the placebo table in §10, are measured. The Magnus tautology and the
specific-humidity example were verified numerically; everything else empirical must be
verified independently.*
