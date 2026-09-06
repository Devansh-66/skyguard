# Blueprint charts, redrawn against the built system

The blueprint's four architecture figures are base64-rendered mermaid embedded as
`<img src="data:image/svg+xml;base64,...">` — about 279 KB of encoded SVG across four
lines. These are the replacements, as live mermaid source.

Artifacts render mermaid natively, so in the blueprint each `<img>` can be replaced by:

```html
<pre class="mermaid">
  ...source below...
</pre>
```

which is editable afterwards instead of being a picture of a diagram.

---

## 1 — The system end to end

**What changed:** the station tier now really exists (ESP32 in simulation, TLS to the
Space). The learned residual model is gone. The panel replaced the five-checker design.
The store is SQLite, not TimescaleDB.

```mermaid
flowchart LR
  subgraph NODE["On the node — no network needed"]
    S["Sensors<br/>T · P · RH"] --> SCR["WMO screen<br/>range · step · self-test"]
    SCR -->|"fails"| DROP["Dropped at the pole<br/>never transmitted"]
    HK["Housekeeping<br/>supply · logger · link"] --> SCR
  end

  SCR -->|"passes"| UP(["TLS uplink<br/>POST /api/ingest"])

  subgraph SRV["In the network — one FastAPI process"]
    UP --> ST[("SQLite WAL<br/>every reading, durable")]
    ST --> ANOM["Anomaly<br/>minus own hourly climatology"]
    ANOM --> NB["Neighbour difference<br/>minus median of N(s), 250 km"]
    NB --> SIG["Standardise<br/>trailing lagged rolling MAD"]
    SIG --> BAND{"Band<br/>6σ watch · 8σ fault"}
    BAND --> EP["Episode<br/>raise 3 · clear 6"]
    EP --> PANEL["Triage panel<br/>api/orchestrator.py"]
  end

  PANEL --> WO["Work order<br/>action · priority · why"]

  NB -.->|"fewer than 3 neighbours"| UNJ["Not scored<br/>said, not guessed"]

  classDef gone fill:#fff,stroke:#B32B22,stroke-dasharray:4 3,color:#B32B22
  class DROP,UNJ gone
```

---

## 2 — The reasoning layer  ← **the biggest change**

**What changed:** five checkers became **three agents and an adjudicator**. The offline
ARM/DQR label path is deleted entirely. Attribution is exact Shapley over the panel, not
SHAP over a model. There is no model.

```mermaid
flowchart TB
  EV["Evidence<br/>band · residual · gaps · episodes<br/>measured regional movement"]

  EV --> A1["Data quality<br/><i>the observation stream</i>"]
  EV --> A2["Hardware health<br/><i>the device</i>"]
  EV --> A3["Weather or fault?<br/><i>the neighbouring stations</i>"]

  A1 --> ADJ{{"Adjudicator<br/>fixed rule order"}}
  A2 --> ADJ
  A3 --> ADJ

  ADJ --> R1["1 · hardware alarm?<br/>a dead link is a fault in any weather"]
  R1 --> R2["2 · did the region move?<br/>unconditional veto"]
  R2 --> R3["3 · readings clean?"]
  R3 --> R4["4 · enough evidence?"]
  R4 --> R5["5 · will a correction hold<br/>until the next visit?"]

  R5 --> OUT["Decision · action · priority<br/>INSPECT | CALIBRATE | COMMS | MONITOR"]

  ADJ -.->|"re-run on all 2³ coalitions"| SHAP["Exact Shapley φ per agent<br/>Σφ = escalation, exactly"]
  SHAP --> CF["Counterfactual per agent<br/>'without it: MONITOR'"]
  ADJ -.-> TR["Decision trace<br/>every check, in order, with its answer"]

  OUT --> BOARD["Maintenance board"]
  SHAP --> BOARD
  CF --> BOARD
  TR --> BOARD

  classDef agent fill:#EEF5FD,stroke:#1F5FAE,color:#0E1720
  classDef xai fill:#fff,stroke:#15694A,color:#15694A
  class A1,A2,A3 agent
  class SHAP,CF,TR xai
```

**Note for the caption:** the old caption claims ARM historical DQR labels feed the
offline path. That corpus and its classifier were deleted — the caption has to go with
the diagram.

---

## 3 — What the operator sees

**What changed:** three screens became four routes, and "Device Health" is no longer a
panel on a dashboard — it is one of the three agents, and it is silent on simulated rows
because the export carries no housekeeping.

```mermaid
flowchart TB
  subgraph HOME["/ — the argument"]
    H1["What drift looks like"]
    H2["Three specialists, one decision"]
    H3["Explainability, running"]
    H4["Edge tier: node vs network"]
  end

  subgraph NET["/network — the whole country"]
    N1["Map · 344 stations · colour by channel"]
    N2["Clock driven by the node, not a browser timer"]
    N3["Per-station charts · ledger · index"]
  end

  subgraph BOARD["/board — the work"]
    B1["Queue, worst first<br/>each row names the agent that decided"]
    B2["Verdict · three opinions"]
    B3["Shapley attribution · counterfactuals"]
    B4["Decision trace, collapsed"]
    B5["Station vs its region"]
    B6["Empty state: how the panel behaves<br/>across the whole network"]
  end

  subgraph TEAM["/team — the submission"]
    T1["Who built it"]
    T2["The problem statement, verbatim"]
  end

  HOME --> NET
  HOME --> BOARD
  BOARD --> NET
```

---

## 4 — What the operator does

**What changed:** the loop still closes twice, but the "rejected → weather event" branch
is now a *measured* veto with a number on it, not an operator judgement.

```mermaid
flowchart LR
  EP["Episode opens<br/>3 consecutive flagged steps"] --> PANEL["Panel judges"]

  PANEL --> V{"Weather or fault?"}
  V -->|"region moved ≥2σ, same way,<br/>explains ≥40%"| WX["Weather<br/>no visit · keep monitoring"]
  V -->|"region quiet"| ACT{"Which job?"}

  ACT -->|"hardware alarm"| INS["INSPECT<br/>sensor, wiring, logger"]
  ACT -->|"link or power"| COM["COMMS<br/>check power and communications"]
  ACT -->|"readings adrift,<br/>device healthy"| CAL["CALIBRATE<br/>or replace the sensor"]
  ACT -->|"correction holds<br/>to the next visit"| REM["Correct centrally<br/>no site visit"]

  INS --> WO["Work order<br/>priority 1 today · 2 this week · 3 next visit"]
  COM --> WO
  CAL --> WO
  WO --> FIX["Technician attends"]
  FIX --> CLR["Episode clears<br/>6 consecutive clean steps"]
  WX --> CLR

  classDef ok fill:#fff,stroke:#15694A,color:#15694A
  class WX,REM ok
```

---

# Sections to remove or mark superseded

Ordered by how misleading they are now.

| § | Section | What to do |
|---|---|---|
| 319 | The AI architecture — a panel that must corroborate | **Replace the five-checker SVG** with chart 2. The built panel is three agents. |
| 702 | The learned layer, revised | **Delete.** The model was deleted; the section plans a thing that no longer exists. |
| 718 | The ML layer, concretely | **Delete.** The 12-element feature vector and its worked figure describe the deleted classifier. |
| 904 | Explainability, done properly | **Rewrite.** It plans SHAP over a model. Replace with exact Shapley over the panel — as-built §18 has the text. |
| 581 | Architecture (four-stage pipeline) | **Amend.** Stage 3 "learned residual model" does not exist. The pipeline is anomaly → neighbour → sigma → band → panel. |
| 1050 | The dashboard — three screens | **Mark superseded.** Three wireframes vs four built routes; keep as design history, point at chart 3. |
| 1829 | What carries over from the PS26178 work | **Delete.** Previous problem statement; nothing carries over that is still in the tree. |
| 1785 | Optional hardware — ₹1,120 per station | **Amend.** Firmware now runs end to end in Wokwi against the deployed Space. Not optional, not untested — just not on physical hardware. |
| 1515 | Production architecture | **Keep, marked aspirational.** TimescaleDB, Redis, worker pool — none built. Storage is one SQLite file. |
| 1730 | Work split · 1748 Demo script · 1677 Build order | **Delete or rewrite.** All predate the current shape of the work. |
| — | Every ARM mention | **Delete.** 24 Python and 8 web files removed; there is no ARM corpus in the project. |

**Keep untouched** — these are the reasoning that got us here and they still hold:
the problem statement, "the one problem that actually matters", the physics with three
parameters, where the accuracy comes from, traps that will bite you, evaluation protocol,
prior art and references.
