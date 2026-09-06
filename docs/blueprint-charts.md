# The four blueprint charts — what to change

Decoded from the rendered SVGs in the blueprint, so every node named below is a node
that actually exists in the current diagrams. Build them in the same tool and style;
this is only the content diff.

**Legend:** ✂️ delete · ✏️ reword · ➕ add · ✅ leave alone

---

## Chart 1 — "The system end to end"

*4 clusters, 23 nodes. This one needs the most work: a whole cluster goes.*

### Clusters

| Cluster | Change |
|---|---|
| AWS Station — ESP32 / datalogger | ✅ keep — it is real now, runs end to end in Wokwi with a TLS uplink |
| Central SkyGuard service — on-premise VM | ✏️ **"Central SkyGuard service — one FastAPI process"** (no VM, no worker pool) |
| Offline training and calibration — never in live request path | ✂️ **delete the entire cluster** — there is no model and no training |
| Operator outputs | ✅ keep |

### Nodes inside the deleted cluster — all go

✂️ `ARM measurements + human DQR fault windows`
✂️ `USCRN preserved raw stream — redundant probes + hardware diagnostics`
✂️ `Train / evaluate / calibrate — lead time · false alarms · coverage · model version approval`
✂️ `approved model version + thresholds` (edge label)
✂️ `approved clean reference only` (edge label)

➕ Keep one survivor, but move it **out** of the cluster and label it plainly, because it
still exists as `simulate/` + `inject/faults.py`:
> **Offline network generator** — 344 stations at real IMD sites · 28 injected faults · run by hand, writes `sim_map.json`

### The five checkers become three agents

| Old node | Change |
|---|---|
| `Physical-consistency checker — dew point · humidity · pressure · weather coherence` | ✂️ **delete from the central service.** This moved onto the station: it is the WMO screen in `Level-0 safety checks` |
| `Spatial and history checker — neighbour residual · drift · step · noise · dropout` | ✏️ **"Data Quality Agent — offset, drift and noise against the neighbours"** |
| `Hardware-health checker — housekeeping trends · voltage / logger temperature / QC` | ✏️ **"Hardware Health Agent — supply · logger · link · stuck values"** and add the small line *"silent on simulated rows — the export carries no housekeeping"* |
| `Learned precursor model — predicts risk of a future sensor fault from hardware patterns` | ✂️ **delete** — never built |
| — | ➕ **"Weather-or-Fault Agent — did the region move? measured neighbour median anomaly"** |

### The adjudicator and what hangs off it

| Old node | Change |
|---|---|
| `Evidence adjudicator — corroborate · score · abstain · UNKNOWN when evidence conflicts` | ✏️ **"Adjudicator — fixed rule order, first rule to fire decides"**. It does still abstain, so keep that word |
| — | ➕ dashed off the adjudicator: **"Exact Shapley — all 8 coalitions · contributions sum to the verdict"** |
| — | ➕ dashed off the adjudicator: **"Decision trace — every check, in order, with its answer"** |

Both new nodes should feed **Explainable verdict**.

### Everything else

| Old node | Change |
|---|---|
| `Reference builder — frozen seasonal baseline · trusted-neighbour consensus` | ✏️ **"Reference — hourly climatology removed · neighbour median · trailing lagged MAD"** (it is not frozen; that was the bug) |
| `Ingest and validation — deduplicate · timestamp · sentinel check` | ✅ keep |
| — | ➕ after ingest: **"SQLite (WAL) — every reading, durable"** |
| `Persistent sensor-health state — bias · drift · noise · trust · last service · uncertainty` | ✂️ delete or mark dashed — `health/state.py` exists but the API does not import it |
| `Explainable verdict — fault hypothesis · evidence · why it is not weather` | ✏️ **"Explainable verdict — which agent decided, by how much, and what it would say without them"** |
| `Live network board — health map + alert queue` | ✏️ **"Network map + maintenance board"** |
| `Maintenance work order — priority · onset estimate · inspect / replace / do not dispatch` | ✅ keep — this is exactly right |
| `Audit trail — raw reading is never overwritten` | ✅ keep |
| `T, Pressure, RH sensor readings` · `Available housekeeping…` · `Level-0 safety checks` · `Local record` · `15-minute readings / streamed records` | ✅ all keep |

---

## Chart 2 — "The reasoning layer, and where the labels come from"

*18 nodes. Closest to reality already — one branch goes, two nodes arrive.*

| Old node | Change |
|---|---|
| `ARM Historical DQR Labels — Verified past faults` | ✂️ **delete** |
| `Offline Training Pipeline` | ✂️ **delete** |
| `Fault Detection Model` | ✂️ **delete** |
| `Central AI Adjudicator` | ✏️ **"Adjudicator — fixed rule order"**. It is not a model, and the subtitle should not imply one |
| `Weather Context — Nearby stations • Forecast • History` | ✏️ **"Weather Context — nearby stations · measured regional movement"**. There is no forecast feed and no history feed |
| `Logger & Device Data — Voltage • Temperature • Network` | ✏️ add *"live node only"* — it is absent on every simulated row |
| `Technician Feedback` | ✏️ keep but **draw it dashed** — the loop is designed, not built |
| `Data Quality Agent` · `Hardware Health Agent` · `Context Validation Agent` · `Live Sensor Data` · `Decision` · `Normal` / `Warning` / `Critical Fault` · `Continue Monitoring` · `Dashboard Alert` · `Maintenance Workflow` | ✅ all keep |
| — | ➕ dashed from the adjudicator: **"Exact Shapley φ per agent — 8 coalitions"** → into `Dashboard Alert` |
| — | ➕ dashed from the adjudicator: **"Decision trace — the walk it took"** → into `Dashboard Alert` |

> **The title needs changing too.** "…and where the labels come from" described the ARM
> branch. There are no labels any more. Suggest: **"The reasoning layer — three agents,
> one adjudicator"**.

---

## Chart 3 — "What the operator sees"

*9 nodes. The dashboard grew from three screens to four routes.*

| Old node | Change |
|---|---|
| `SkyGuard Command Dashboard` | ✏️ **"SkyGuard — four routes"** |
| `🔋 Device Health — Battery • Logger • Connectivity` | ✏️ add *"live node only"*. It is no longer a dashboard panel — it is one of the three agents |
| `🗺 Network Map` · `📈 Live Sensor Charts` · `⚠ AI Alert Panel` · `📊 Network KPIs` · `Select Station` · `Station Health Summary` · `Live Weather Stations` | ✅ all keep |
| — | ➕ **"🔍 Why this verdict — Shapley waterfall · counterfactual · decision trace"** |
| — | ➕ **"📐 Station vs its region — the evidence the verdict rests on"** |
| — | ➕ **"🧪 Panel behaviour — how the three agents perform across the whole network"** |
| — | ➕ **"👥 Team — the problem statement, verbatim"** |

---

## Chart 4 — "What the operator does"

*15 nodes. The shape is right; two steps stopped being human.*

| Old node | Change |
|---|---|
| `Remote Validation` | ✏️ **"Weather-or-fault check — automatic"**. This is no longer a person looking |
| `Confirmed Fault?` | ✏️ **"Did the region move?"** with the test underneath: *≥2σ of its own spread · same direction · explains ≥40%* |
| `Mark as Weather Event / Continue Monitoring` | ✅ keep — and it is worth a note that this branch is now measured: **89% precision, removes 17% of false alarms** |
| `AI Recommended Action` | ✏️ **"Adjudicator action"** |
| `Prioritise by Severity • Confidence • Impact` | ✏️ **"Priority — 1 today · 2 this week · 3 next visit"** (that is the actual vocabulary) |
| `Inspect Sensor / Wiring / Logger` · `Calibrate or Replace Sensor` · `Check Power / Communication` | ✅ keep — these are exactly the built actions |
| — | ➕ fourth action: **"Monitor — no visit needed"** |
| `Close Case + Feed Result Back to AI Model` | ✏️ **"Close case — episode clears after 6 clean steps"**. There is no model to feed back into |
| `AI Fault Alert` · `Create Maintenance Case` · `Technician Work Order` · `Repair Verification` · `Yes` / `No` | ✅ all keep |

---

## Where they go when you have them

The four `<img src="data:image/svg+xml;base64,…">` blocks are gone from
`docs/blueprint.html` — I replaced them with live mermaid holding the corrected content,
because a placeholder that is *right* beats a rendered picture that is *wrong*. It does
not match the house style, which is the point you made.

Hand me the four rendered SVGs (or the base64) and I will drop them straight back into
the same four slots and republish. Nothing else in the document needs to move.
