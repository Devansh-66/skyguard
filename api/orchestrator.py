"""The triage panel: three agents, one adjudicator, one recommended action.

WHAT THIS REPLACES

The board used to call a single function, `_action(bias, drift, noise, trust,
hk_moved)`, which returned one of two strings and a paragraph of prose. Two
problems with that. It could only ever say DISPATCH or CORRECT CENTRALLY, so a
technician was told to go, but never what to do on arrival. And the reasoning
was a sentence built by string formatting, so nothing downstream could show
WHICH evidence drove the call, or disagree with part of it.

The design that was planned -- and that the architecture diagram describes --
is a panel: specialists that each look at one kind of evidence and report
independently, and an adjudicator that combines their verdicts into a decision
and a named action. That is what this module is.

    Data Quality Agent      the observation stream itself: offset, drift, noise
    Hardware Health Agent   the device: housekeeping, failed checks, gaps
    Context Validation      is it the instrument, or is it the weather?
                                |
                          Adjudicator  ->  decision + action + priority

WHAT THESE AGENTS ARE, HONESTLY

They are deterministic evaluators over published evidence, not language models.
Each returns a verdict with a status, a confidence, and the numbers it used, and
the adjudicator combines them by stated rules. Calling them "agents" describes
the ARCHITECTURE -- independent specialists, one arbiter, every verdict
inspectable -- not an LLM in a loop. The value is the same either way: the
board can show three separate opinions and say which one carried the decision,
which a single if/else could never do.

The panel is the only place these rules live. `POST /api/board/triage` serves
the simulated network and the live node from it, so two screens cannot
disagree about the same evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .neighbours import (comparison_series, flagged_rows, parse_sim_id,
                         regional_movement)

router = APIRouter()

Status = Literal["ok", "watch", "alarm", "unknown"]

# Days until anyone is next at the station. The dispatch question is really a
# question about this interval: will a coefficient typed in today still be
# right when someone finally visits?
SERVICE_INTERVAL_D = 90.0

# Below this much evidence the belief has not seen enough to spend an
# operator's time on, however far it has moved.
MIN_EVIDENCE = 40.0

# Sigma at which an offset is worth raising at all.
RAISE_AT = 3.0


@dataclass
class Evidence:
    """Everything the panel is allowed to look at, from any of the three sources.

    Fields are optional because the sources genuinely differ: the simulated
    export carries grades and gaps but no housekeeping channels, and the live
    node carries the same but is happening now. A real AWS will carry logger
    voltage and temperature, which is why those fields exist unused. An agent
    that cannot see its evidence returns `unknown` and says so, rather than
    defaulting to ok and quietly voting.
    """
    source: str = "sim"                 # sim | live | (aws, later)
    sensor: str = ""
    label: str = ""
    band: str | None = None             # ok | watch | fault
    bias_sigma: float | None = None
    drift_sigma_day: float | None = None
    noise_sigma: float | None = None
    trust: float | None = None
    evidence_n: float | None = None
    checks_passed: int | None = None
    housekeeping_moved: bool | None = None
    neighbours_agree: bool | None = None
    analyst_confirmed: bool | None = None
    flat_fraction: float | None = None
    gap_fraction: float | None = None
    episodes: int | None = None
    days_open: float | None = None
    # Measured regional movement, filled in by the service from the network's
    # own readings. `neighbours_agree` used to be asserted by the caller; these
    # are the numbers behind it, so the agent can say how strongly rather than
    # only whether. See api/neighbours.py.
    region_z: float | None = None
    region_share: float | None = None
    neighbour_count: int | None = None


@dataclass
class AgentVerdict:
    agent: str
    title: str
    status: Status
    confidence: float          # 0..1, how much weight the adjudicator gives it
    headline: str              # one line, technician-readable
    metrics: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------- the agents

def data_quality_agent(e: Evidence) -> AgentVerdict:
    """Does the observation stream itself look wrong?"""
    m = {"bias_sigma": e.bias_sigma, "drift_sigma_day": e.drift_sigma_day,
         "noise_sigma": e.noise_sigma}

    if e.evidence_n is not None and e.evidence_n < MIN_EVIDENCE:
        return AgentVerdict(
            "data_quality", "Data quality", "unknown", 0.2,
            "Too few readings so far to judge this sensor", m)

    if e.band == "fault" or (e.bias_sigma is not None
                             and abs(e.bias_sigma) >= 8.0):
        b = abs(e.bias_sigma) if e.bias_sigma is not None else None
        return AgentVerdict(
            "data_quality", "Data quality", "alarm", 0.9,
            (f"Reading {b:.1f} sigma away from what this place should show"
             if b is not None else
             "Reading far outside what this place should show"), m)

    if e.band == "watch" or (e.bias_sigma is not None
                             and abs(e.bias_sigma) >= RAISE_AT):
        b = abs(e.bias_sigma) if e.bias_sigma is not None else None
        return AgentVerdict(
            "data_quality", "Data quality", "watch", 0.7,
            (f"Drifting away from its neighbours, now {b:.1f} sigma"
             if b is not None else "Drifting away from its neighbours"), m)

    if e.band == "ok" or e.bias_sigma is not None:
        return AgentVerdict("data_quality", "Data quality", "ok", 0.8,
                            "Readings agree with the surrounding stations", m)

    return AgentVerdict("data_quality", "Data quality", "unknown", 0.2,
                        "No residual available for this sensor", m)


def hardware_health_agent(e: Evidence) -> AgentVerdict:
    """Is the DEVICE unwell -- power, logger, wiring, link?"""
    m = {"trust": e.trust, "checks_passed": e.checks_passed,
         "housekeeping_moved": e.housekeeping_moved,
         "flat_fraction": e.flat_fraction, "gap_fraction": e.gap_fraction}

    if e.gap_fraction is not None and e.gap_fraction > 0.2:
        return AgentVerdict(
            "hardware", "Hardware health", "alarm", 0.9,
            f"Missing {e.gap_fraction * 100:.0f}% of its reports — the link or "
            "the power is failing", m)

    if e.flat_fraction is not None and e.flat_fraction > 0.5:
        return AgentVerdict(
            "hardware", "Hardware health", "alarm", 0.85,
            "Value has stopped changing — the probe or the logger is stuck", m)

    if e.housekeeping_moved:
        return AgentVerdict(
            "hardware", "Hardware health", "alarm", 0.9,
            "Logger voltage or temperature moved with the fault — this is the "
            "hardware, not the calibration", m)

    if e.trust is not None and e.trust < 0.5:
        return AgentVerdict(
            "hardware", "Hardware health", "watch", 0.7,
            f"Failing most of its automatic checks (trust {e.trust:.2f})", m)

    # ANY housekeeping evidence is enough to say "ok". This used to require
    # `housekeeping_moved is False or trust is not None`, which meant a node
    # reporting a healthy supply, 0% gaps, 3% flat and twelve passed self-test
    # checks still came back "this station reports no housekeeping channels" --
    # a statement that was false, and false in the direction that makes a
    # working agent look absent.
    if any(v is not None for v in (e.gap_fraction, e.flat_fraction,
                                   e.housekeeping_moved, e.trust,
                                   e.checks_passed)):
        return AgentVerdict("hardware", "Hardware health", "ok", 0.7,
                            "Power, logger and link all reporting normally", m)

    return AgentVerdict(
        "hardware", "Hardware health", "unknown", 0.2,
        "This station reports no housekeeping channels", m)


def context_validation_agent(e: Evidence) -> AgentVerdict:
    """The question that decides everything: instrument, or weather?

    This is the agent the problem statement is really about. A genuine squall
    produces a large fast excursion and so does a failing barometer; what
    separates them is that the weather arrives at the neighbours too.
    """
    m = {"neighbours_agree": e.neighbours_agree,
         "analyst_confirmed": e.analyst_confirmed, "episodes": e.episodes,
         "days_open": e.days_open, "region_z": e.region_z,
         "region_share": e.region_share, "neighbour_count": e.neighbour_count}

    if e.analyst_confirmed:
        return AgentVerdict(
            "context", "Weather or fault?", "alarm", 0.95,
            "An analyst inspected this instrument and confirmed the fault", m)

    if e.neighbours_agree is True:
        # Say how much of it the region accounts for when that was measured.
        # "The neighbours moved too" is an assertion; "the region moved 3.1
        # sigma and covers all of this station's excursion" is evidence.
        detail = ""
        if e.region_z is not None and e.neighbour_count:
            share = (f", covering {e.region_share:.0%} of this excursion"
                     if e.region_share is not None else "")
            detail = (f" — {e.neighbour_count} neighbours moved "
                      f"{abs(e.region_z):.1f} sigma{share}")
        return AgentVerdict(
            "context", "Weather or fault?", "ok", 0.85,
            f"The surrounding stations show the same movement{detail}"
            if detail else
            "Neighbouring stations show the same movement — this is weather", m)

    if e.neighbours_agree is False:
        extra = ""
        if e.days_open is not None and e.days_open >= 1:
            extra = f", and has for {e.days_open:.0f} days"
        quiet = ""
        if e.region_z is not None and e.neighbour_count:
            quiet = (f" Its {e.neighbour_count} neighbours moved only "
                     f"{abs(e.region_z):.1f} sigma.")
        return AgentVerdict(
            "context", "Weather or fault?", "alarm", 0.85,
            f"No neighbouring station shows this{extra} — it is the "
            f"instrument.{quiet}".rstrip(),
            m)

    if e.episodes is not None and e.episodes >= 2:
        return AgentVerdict(
            "context", "Weather or fault?", "watch", 0.5,
            f"Has gone wrong {e.episodes} separate times — weather does not "
            "repeat like that", m)

    return AgentVerdict("context", "Weather or fault?", "unknown", 0.2,
                        "Too few usable neighbours to compare against", m)


PANEL = (data_quality_agent, hardware_health_agent, context_validation_agent)


# ----------------------------------------------------------- the adjudicator

# The action vocabulary is closed on purpose. A technician is dispatched with a
# job, and "anomaly detected" is not a job. These four are the ones the
# maintenance workflow actually branches into.
ACTIONS = {
    "INSPECT":   "Inspect sensor, wiring and logger",
    "CALIBRATE": "Calibrate or replace the sensor",
    "COMMS":     "Check power and communications",
    "MONITOR":   "No visit — keep monitoring",
}


@dataclass
class Assessment:
    decision: str              # normal | warning | critical
    action: str                # key into ACTIONS
    action_label: str
    priority: int              # 1 = today, 2 = this week, 3 = next visit
    confidence: float
    why: str                   # ONE sentence: which agent carried the call
    can_fix_remotely: bool
    verdicts: list[dict]
    # The rules the adjudicator walked, in the order it reached them,
    # including the ones that did NOT fire -- a check that was asked and
    # answered no is part of why the answer is believable.
    trace: list[dict] = field(default_factory=list)
    # Filled by assess(). Absent when a coalition is being evaluated, which is
    # what stops the attribution from recursing into itself.
    attribution: dict | None = None

    def dict(self) -> dict:
        return asdict(self)


def adjudicate(e: Evidence, verdicts: list[AgentVerdict]) -> Assessment:
    """Combine the three verdicts into one decision, action and priority.

    The rules are checked in a fixed order and the FIRST one that matches
    decides. Every check is recorded on the way past -- see `trace` -- because
    the rules that did not fire are part of the explanation too: knowing the
    weather check was asked and answered no is what makes a dispatch
    believable.
    """
    by = {v.agent: v for v in verdicts}
    dq, hw, ctx = by["data_quality"], by["hardware"], by["context"]
    out = [
        {"agent": v.agent, "title": v.title, "status": v.status,
         "confidence": round(v.confidence, 2), "headline": v.headline,
         "metrics": {k: val for k, val in v.metrics.items() if val is not None}}
        for v in verdicts
    ]

    trace: list[dict] = []

    def check(question: str, hit: bool | None, note: str,
              agent: str | None = None) -> bool:
        """Record one rule, in the order it was actually reached.

        `hit` of None means the question could not be answered at all -- the
        evidence for it is missing. That is a THIRD state and it is recorded as
        one. Reporting it as "no" reads as a finding when it is an absence, and
        a trace that quietly turns "I cannot tell" into "no" is the one thing
        on this screen that would be worth not believing.
        """
        trace.append({"step": len(trace) + 1, "question": question,
                      "answer": "yes" if hit else "no" if hit is False else "n/a",
                      "note": note, "agent": agent, "decided": bool(hit)})
        return bool(hit)

    def done(decision, action, priority, conf, why, remote=False):
        return Assessment(decision, action, ACTIONS[action], priority,
                          round(min(conf, 0.99), 2), why, remote, out,
                          trace=trace)

    # ORDER MATTERS, AND THIS IS THE ORDER.
    #
    # 1. Hardware alarms come first because a dead link or a stuck logger is a
    #    fault in any weather -- the context agent has nothing to say about it,
    #    and a coefficient cannot fix it. Sending someone with the wrong job
    #    wastes the visit.
    if check("Is the device itself unwell?", hw.status == "alarm",
             hw.headline if hw.status == "alarm"
             else "No alarm from the hardware checks.", "hardware"):
        gap = (e.gap_fraction or 0) > 0.2
        action = "COMMS" if gap else "INSPECT"
        check("Is it missing reports rather than misreading?", gap,
              "Most reports are arriving, so this is the sensor or its wiring"
              if not gap else
              f"Missing {(e.gap_fraction or 0) * 100:.0f}% of reports — power "
              "or communications", "hardware")
        return done("critical", action, 1, hw.confidence,
                    "Hardware health is the strongest signal here: "
                    + hw.headline.lower() + ".")

    # 2. Then context has an unconditional veto over the readings. If the
    #    neighbours moved the same way, a large deviation is exactly what
    #    weather looks like, and the size of it changes nothing.
    #
    #    This condition used to read `ctx.status == "ok" and dq.status !=
    #    "alarm"`, which disabled the veto precisely when it mattered: a big
    #    excursion made the data-quality agent alarm, which switched off the
    #    one agent whose job is to explain big excursions. A confirmed
    #    region-wide warm front came back as CALIBRATE THE SENSOR.
    if check("Did the neighbouring stations move the same way?",
             ctx.status == "ok", ctx.headline, "context"):
        return done("normal", "MONITOR", 3, ctx.confidence,
                    "The neighbouring stations show the same movement, so this "
                    "is weather rather than a fault.")

    # 3. Nothing wrong with the readings.
    if check("Do the readings agree with the surrounding stations?",
             dq.status == "ok", dq.headline, "data_quality"):
        return done("normal", "MONITOR", 3, dq.confidence,
                    "Readings agree with the surrounding stations and the "
                    "device is healthy.")

    # 4. Not enough evidence yet to spend anyone's time.
    if check("Is there too little evidence to judge?",
             dq.status == "unknown", dq.headline, "data_quality"):
        return done("normal", "MONITOR", 3, 0.3,
                    "Not enough readings yet to tell a fault from ordinary "
                    "variation.")

    # 5. A real deviation with healthy hardware: calibration. The remaining
    #    question is whether a coefficient typed in today survives until the
    #    next visit, or whether the drift outruns it.
    drift = abs(e.drift_sigma_day or 0.0)
    noise = max(e.noise_sigma or 0.0, 1e-9)
    growth = drift * SERVICE_INTERVAL_D
    stable = growth <= RAISE_AT * noise

    answerable = e.noise_sigma is not None
    if check("Would a correction typed in today still hold at the next visit?",
             bool(stable) if answerable else None,
             (f"It drifts {growth:.1f} sigma over the next "
              f"{SERVICE_INTERVAL_D:.0f} days"
              if answerable else
              "No noise estimate for this sensor, so this cannot be answered "
              "either way — the visit is scheduled rather than assumed away"),
             "data_quality"):
        return done("warning", "MONITOR", 3, dq.confidence,
                    f"A steady offset that grows only {growth:.1f} sigma before "
                    f"the next service visit, so a correction applied centrally "
                    f"holds until then.", remote=True)

    priority = 1 if dq.status == "alarm" else 2
    check("How far past the threshold is it?", True,
          dq.headline, "data_quality")
    tail = (f" It moves a further {growth:.0f} sigma before the next "
            f"{SERVICE_INTERVAL_D:.0f}-day visit, so a correction applied today "
            f"would be wrong long before anyone arrives." if growth else "")
    return done("critical" if priority == 1 else "warning",
                "CALIBRATE", priority, dq.confidence,
                dq.headline + "." + tail)


# --------------------------------------------------- who actually decided it

"""HOW MUCH DID EACH AGENT MATTER? THE EXACT ANSWER, NOT AN ESTIMATE.

`why` names the agent that carried the call, which is a label. This is the
number behind the label.

WHY SHAPLEY, AND WHY IT IS EXACT HERE

Shapley values come from cooperative game theory: the fair division of a
payout among players who only produce value in coalitions. SHAP, the library
everyone reaches for, is an APPROXIMATION of that idea applied to model
features, and it is approximate because a model has hundreds of features and
2^n coalitions is impossible to enumerate.

We have three players. 2^3 is eight. So we enumerate every coalition and get
the true Shapley value -- the original theorem, not a sampled estimate of it.
Three adjudications more expensive than the verdict itself.

An agent is absent from a coalition by being SILENCED: it returns `unknown`
with no confidence, which is exactly what the adjudicator already does with an
agent that cannot see its evidence. So absence is a state the rules already
understand, and nothing had to be special-cased to support this.

THE PAYOUT IS ESCALATION -- how hard this coalition pushes toward a visit.
Ordinal, and the one thing everyone in the loop cares about.

The empty coalition scores zero: with all three silent the adjudicator reaches
"not enough readings yet" and recommends monitoring. That makes the
contributions sum EXACTLY to the final escalation, with nothing left over --
the property a force plot claims and usually only approximates.
"""

ESCALATION = {"normal": 0.0, "warning": 0.5, "critical": 1.0}

# Weights for n=3: |S|! (n-|S|-1)! / n!
_SHAPLEY_W = {0: 1 / 3, 1: 1 / 6, 2: 1 / 3}


def _silent(agent) -> AgentVerdict:
    """An agent that was not consulted, in the form the adjudicator expects."""
    spoken = agent(Evidence())          # cheap, and only to learn its identity
    return AgentVerdict(spoken.agent, spoken.title, "unknown", 0.0,
                        "Not consulted.", {})


def _coalition(e: Evidence, present: frozenset[int]) -> Assessment:
    """Adjudicate with only the agents in `present` allowed to speak."""
    return adjudicate(e, [
        agent(e) if i in present else _silent(agent)
        for i, agent in enumerate(PANEL)
    ])


def attribute(e: Evidence) -> dict:
    """Exact Shapley value per agent, plus the counterfactual for each.

    The counterfactual is the useful half for a reader: not "hardware
    contributed 0.52" but "silence hardware and this becomes MONITOR". One is a
    number to trust, the other is a sentence to act on.
    """
    n = len(PANEL)
    idx = range(n)
    cache: dict[frozenset[int], Assessment] = {}

    def value(s: frozenset[int]) -> float:
        if s not in cache:
            cache[s] = _coalition(e, s)
        return ESCALATION.get(cache[s].decision, 0.0)

    full = frozenset(idx)
    subsets = [frozenset(c) for r in range(n + 1)
               for c in _combinations(list(idx), r)]
    for s in subsets:
        value(s)

    out = []
    for i in idx:
        phi = 0.0
        for s in subsets:
            if i in s:
                continue
            phi += _SHAPLEY_W[len(s)] * (value(s | {i}) - value(s))
        without = cache[full - {i}]
        spoken = PANEL[i](e)
        out.append({
            "agent": spoken.agent,
            "title": spoken.title,
            "phi": round(phi, 4),
            # What the panel would have said without this agent in the room.
            "without_action": without.action,
            "without_decision": without.decision,
        })

    return {
        "base": round(value(frozenset()), 4),      # nobody consulted
        "total": round(value(full), 4),            # the verdict as issued
        "contributions": out,
        "exact": True,
        "coalitions": len(subsets),
    }


def _combinations(pool: list[int], r: int):
    """itertools.combinations, inlined to keep this module dependency-free."""
    if r == 0:
        yield ()
        return
    for i, x in enumerate(pool):
        for rest in _combinations(pool[i + 1:], r - 1):
            yield (x,) + rest


def assess(e: Evidence) -> Assessment:
    """Run the panel and adjudicate. The one entry point."""
    a = adjudicate(e, [agent(e) for agent in PANEL])
    a.attribution = attribute(e)
    return a


# ------------------------------------------------------------------- the API

class EvidenceIn(BaseModel):
    id: str = Field(..., description="caller's id, echoed back")
    source: str = "sim"
    sensor: str = ""
    label: str = ""
    band: str | None = None
    bias_sigma: float | None = None
    drift_sigma_day: float | None = None
    noise_sigma: float | None = None
    trust: float | None = None
    evidence_n: float | None = None
    checks_passed: int | None = None
    housekeeping_moved: bool | None = None
    neighbours_agree: bool | None = None
    analyst_confirmed: bool | None = None
    flat_fraction: float | None = None
    gap_fraction: float | None = None
    episodes: int | None = None
    days_open: float | None = None
    # The flagged window, in STEPS of the grade string. Supplied so the service
    # can ask what the region was doing during exactly that stretch rather than
    # averaging the answer over a month.
    window_from: int | None = None
    window_to: int | None = None


@router.post("/api/board/triage")
def triage(items: list[EvidenceIn]) -> dict:
    """Assess a batch of items.

    Batched because the board holds the whole simulated network: one request
    per item would be hundreds of round trips to answer one screen.
    """
    out = {}
    for it in items[:2000]:
        data = it.model_dump()
        ident = data.pop("id")
        frm = data.pop("window_from", None)
        to = data.pop("window_to", None)

        # MEASURE THE NEIGHBOURS RATHER THAN BE TOLD ABOUT THEM.
        #
        # The board used to send `neighbours_agree: false` on every simulated
        # row, on the reasoning that a flagged station is one its neighbours
        # disagree with. That handed the context agent its own conclusion: it
        # could never veto, and its Shapley value on this board was
        # structurally zero -- three agents, one of them unable to affect any
        # outcome. Here the service works it out from the network's own
        # readings, and only when the caller did not claim to know.
        if data.get("neighbours_agree") is None:
            parsed = parse_sim_id(ident)
            if parsed:
                r = regional_movement(parsed[0], parsed[1], frm, to)
                if r:
                    data["neighbours_agree"] = r["agree"]
                    data["region_z"] = r["region_z"]
                    data["region_share"] = r["share_explained"]
                    data["neighbour_count"] = r["neighbours"]

        out[ident] = assess(Evidence(**data)).dict()
    return {"assessments": out, "panel": [f.__name__ for f in PANEL],
            "actions": ACTIONS}


@router.get("/api/board/region")
def region(station: str, channel: str) -> dict:
    """This station's anomaly and its region's, for the detail chart.

    Separate from /triage because it is one station's worth of series and the
    board asks for hundreds of verdicts at once; folding it into the batch
    would send a megabyte to draw one chart.
    """
    r = comparison_series(station, channel)
    if r is None:
        return {"available": False}
    return {"available": True, **r}


@router.get("/api/board/behaviour")
def behaviour() -> dict:
    """How the PANEL behaves across the whole network, not one sensor.

    Every other explanation on this site is about a single verdict. This is the
    one that audits the design: run the panel over every flagged row, keep the
    Shapley values, and ask two questions nothing else can answer.

    Is this really three agents? An agent whose contribution is zero on every
    row of the network is an ornament, and that is invisible one row at a time.

    And what does each agent catch? Grouping by the INJECTED fault -- which the
    panel is never shown -- turns the answer into a capability map, where an
    empty column is a fault class nothing on the panel detects. Found by
    arithmetic instead of by losing a station.

    Counts ship with every cell. This network has fourteen injected faults
    across six kinds, so some cells rest on two rows, and a thin cell must read
    as thin rather than as a finding.
    """
    rows = flagged_rows()
    per_agent: dict[str, list[float]] = {}
    by_kind: dict[str, dict[str, list[float]]] = {}
    actions: dict[str, int] = {}
    saved = 0.0

    for r in rows:
        ev = Evidence(
            source="sim", sensor=r["channel"], band=r["band"],
            episodes=r["episodes"], days_open=r["days_open"],
            gap_fraction=r["gap_fraction"], evidence_n=200,
        )
        rm = regional_movement(r["station"], r["channel"],
                               r["window_from"], r["window_to"])
        if rm:
            ev.neighbours_agree = rm["agree"]
            ev.region_z = rm["region_z"]
            ev.region_share = rm["share_explained"]
            ev.neighbour_count = rm["neighbours"]

        a = assess(ev)
        actions[a.action] = actions.get(a.action, 0) + 1
        kind = r["injected"] or "none injected"
        for c in (a.attribution or {}).get("contributions", []):
            per_agent.setdefault(c["agent"], []).append(c["phi"])
            by_kind.setdefault(kind, {}).setdefault(c["agent"], []).append(c["phi"])
            if c["phi"] < 0:
                saved += -c["phi"]

    def summarise(vals: list[float]) -> dict:
        n = len(vals)
        pos = sum(1 for v in vals if v > 0.001)
        neg = sum(1 for v in vals if v < -0.001)
        return {"n": n, "mean": round(sum(vals) / n, 3) if n else 0.0,
                "pushed": pos, "argued_against": neg,
                "no_effect": n - pos - neg,
                "values": [round(v, 3) for v in vals]}

    titles = {"data_quality": "Data quality", "hardware": "Hardware health",
              "context": "Weather or fault?"}
    return {
        "rows": len(rows),
        "agents": [{"agent": k, "title": titles.get(k, k), **summarise(v)}
                   for k, v in per_agent.items()],
        "by_kind": {
            kind: {"n": len(next(iter(d.values()))) if d else 0,
                   "mean": {k: round(sum(v) / len(v), 3) for k, v in d.items()}}
            for kind, d in sorted(by_kind.items())
        },
        "actions": actions,
        # Escalation argued away, in units of "a visit that did not happen".
        "dispatches_avoided": round(saved, 2),
    }


@router.get("/api/board/panel")
def panel_info() -> dict:
    """What the panel is, for the interface to explain itself."""
    return {
        "agents": [
            {"agent": "data_quality", "title": "Data quality",
             "watches": "the observation stream — offset, drift, noise"},
            {"agent": "hardware", "title": "Hardware health",
             "watches": "the device — power, logger, link, stuck values"},
            {"agent": "context", "title": "Weather or fault?",
             "watches": "the neighbouring stations, to rule out real weather"},
        ],
        "actions": ACTIONS,
        "note": "Deterministic evaluators over published evidence, not language "
                "models. Each reports independently and the adjudicator states "
                "which one carried the decision.",
    }
