# What changed in the four blueprint charts

Written against the charts as they stand, decoded from the rendered SVGs so nothing below
is from memory. File mapping, since the export names do not match the order they appear
on the page:

- `mermaid-diagram.svg` — **The system end to end**
- `mermaid-diagram3.svg` — **The reasoning layer, and where the labels come from**
- `mermaid-diagram1.svg` — **What the operator sees**
- `mermaid-diagram2.svg` — **What the operator does**

---

## The system end to end

The biggest change is a deletion. The whole **offline training and calibration** cluster
comes out, and everything inside it goes with it: the ARM measurements and human DQR fault
windows, the USCRN preserved raw stream, the train/evaluate/calibrate box, and the two
edges labelled *approved model version + thresholds* and *approved clean reference only*.
None of it exists any more. The corpus was deleted from the project — twenty-four Python
files and eight web files — and the classifier that consumed it went with it, having
reached a lift of only 1.22× over its base rate. The **learned precursor model** inside the
central service goes for the same reason: it was never built at all.

One survivor should come out of that cluster rather than be deleted with it. The synthetic
fault injector still exists and still runs, so it belongs on the diagram — just not as part
of a training loop. It is now simply the offline generator that writes the simulated
network: 344 stations at real IMD sites, 28 injected faults, run by hand.

The second change is that **five checkers became three agents**, and the reason is worth
carrying in the caption because it is not a simplification for its own sake. The
physical-consistency checker did not disappear — it moved down onto the station, where it
is now the level-0 screen that rejects a reading before it costs any bandwidth. Of what
remained centrally, the spatial-and-history checker became the **Data Quality Agent** and
the hardware-health checker became the **Hardware Health Agent**, and a third arrived that
had no equivalent before: a **Weather-or-Fault Agent** that asks whether the surrounding
region was itself moving at the time. That question is genuinely independent of the
residual, which is why it earns a box of its own.

The **evidence adjudicator** keeps its name and its ability to abstain, but its subtitle is
wrong now. It does not corroborate and score; it walks a fixed order of rules and stops at
the first one that fires. Two new things should hang off it, both dashed, both feeding the
explainable verdict: the exact Shapley value per agent, computed by re-running the panel on
all eight coalitions, and the decision trace, which records every check in the order it was
reached. Those two are the explainability, and neither existed when the chart was drawn.

Smaller corrections. The **reference builder** says *frozen seasonal baseline* — it is not
frozen, and that was the single worst bug in the project: a fixed sigma inflated the scoring
period by 1.61× and produced a 7.6% false-alarm rate. It should read as a trailing, lagged,
rolling estimate. A **SQLite (WAL)** box belongs after ingest, because every reading really
is stored durably and the board reads faults back from it. The **persistent sensor-health
state** should be dashed or dropped — the module exists but the API never imports it. And
the cluster label *on-premise VM* should become *one FastAPI process*, since that is
literally what serves the JSON, the WebSocket, the panel and the compiled app.

The station cluster, the ingest box, the local record, the maintenance work order and the
audit trail are all still accurate and want no changes.

---

## The reasoning layer, and where the labels come from

This chart is closest to what was built, and the change is mostly one branch coming out.
**ARM Historical DQR Labels**, **Offline Training Pipeline** and **Fault Detection Model**
all go. That branch is what the second half of the title refers to, so the title needs to
change too — there are no labels any more, and nothing is trained. Something like *"The
reasoning layer — three agents, one adjudicator"* is honest.

**Central AI Adjudicator** should lose the word AI, or at least the implication. It is a
fixed rule order, evaluated deterministically, and calling it AI invites exactly the
question we cannot answer well. The three agents keep their names — those were right.

Two nodes need their subtitles corrected because they promise inputs that do not exist.
**Weather Context** reads *Nearby stations • Forecast • History*; there is no forecast feed
and no history feed, and what the agent actually consumes is a measured regional movement
computed from the neighbours' own anomalies. **Logger & Device Data** should carry a note
saying live node only — it is genuinely absent on every simulated row, which is why the
hardware agent contributes exactly zero across all sixty flagged sensors on the board.

Then the same two additions as the first chart, dashed off the adjudicator and into the
dashboard alert: the exact Shapley contribution per agent, and the decision trace.
**Technician Feedback** should stay but be drawn dashed — the loop is designed and not
built, and it is the sort of thing a judge will ask to see.

---

## What the operator sees

Three screens became four routes, so the hub should say so. Most of the panels survive
unchanged: the network map, the live sensor charts, the alert panel, the network KPIs, the
station health summary. What changed is what sits beside them.

**Device Health** is the one that moved rather than grew. It is no longer a dashboard panel
at all — it became one of the three agents, and it should carry the live-node-only caveat
for the same reason as in the previous chart.

Four things want adding, and they are the parts a judge will look for. A **why-this-verdict
panel** carrying the Shapley waterfall, the counterfactual per agent and the collapsed
decision trace. A **station-versus-region chart**, which is the actual evidence the verdict
rests on — the station's anomaly against the median of its neighbours, with the flagged
window shaded. A **panel-behaviour view**, which is the same Shapley values gathered across
the whole network and answers whether all three agents are doing work. And the **team
route**, which carries the problem statement verbatim.

---

## What the operator does

The shape of this chart is right and most of it survives. What changed is that two steps
stopped being human.

**Remote Validation** is now automatic. **Confirmed Fault?** should become *Did the region
move?*, and it is worth putting the actual test underneath it, because it is specific and
defensible: the region has to have moved at least two sigma of its own quiet spread, in the
same direction, and account for at least forty per cent of this station's excursion. A
region that moved two sigma while the station moved thirty does not excuse the station.

That makes the **Mark as Weather Event** branch a measured claim rather than an operator's
judgement, and it is worth annotating: across all sixty flagged rows it fires nine times,
eight of them correctly, removing seventeen per cent of the false alarms at the cost of one
real fault — which the hardware agent catches anyway, because hardware is adjudicated
before the weather veto.

**AI Recommended Action** should just be *Adjudicator action*. The three actions below it —
inspect, calibrate, check power — are exactly the built vocabulary and need no change, but
a fourth belongs beside them: **Monitor, no visit needed**, which is a real outcome and the
one the whole veto branch produces. **Prioritise by Severity • Confidence • Impact** should
become the priority language the board actually uses: 1 today, 2 this week, 3 next visit.

Finally, **Close Case + Feed Result Back to AI Model** cannot stay as written, because
there is no model to feed. The case closes when the episode clears, which happens after six
consecutive clean steps — deliberately slower than the three it takes to open one, so that
a drifting sensor wobbling across the band cannot close its own alert.

---

## When the charts come back

The four `<img src="data:image/svg+xml;base64,…">` blocks in `docs/blueprint.html` are
currently live mermaid holding the corrected content — a placeholder that is right rather
than a rendered picture that is wrong, since the reasoning-layer chart on the page today
still shows a training pipeline that does not exist. Send the four rendered SVGs and they
drop straight back into the same four slots. Nothing else in the document has to move.
