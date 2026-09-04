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

    if e.housekeeping_moved is False or e.trust is not None:
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
         "days_open": e.days_open}

    if e.analyst_confirmed:
        return AgentVerdict(
            "context", "Weather or fault?", "alarm", 0.95,
            "An analyst inspected this instrument and confirmed the fault", m)

    if e.neighbours_agree is True:
        return AgentVerdict(
            "context", "Weather or fault?", "ok", 0.85,
            "Neighbouring stations show the same movement — this is weather", m)

    if e.neighbours_agree is False:
        extra = ""
        if e.days_open is not None and e.days_open >= 1:
            extra = f", and has for {e.days_open:.0f} days"
        return AgentVerdict(
            "context", "Weather or fault?", "alarm", 0.85,
            f"No neighbouring station shows this{extra} — it is the instrument",
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

    def dict(self) -> dict:
        return asdict(self)


def adjudicate(e: Evidence, verdicts: list[AgentVerdict]) -> Assessment:
    """Combine the three verdicts into one decision, action and priority."""
    by = {v.agent: v for v in verdicts}
    dq, hw, ctx = by["data_quality"], by["hardware"], by["context"]
    out = [
        {"agent": v.agent, "title": v.title, "status": v.status,
         "confidence": round(v.confidence, 2), "headline": v.headline,
         "metrics": {k: val for k, val in v.metrics.items() if val is not None}}
        for v in verdicts
    ]

    def done(decision, action, priority, conf, why, remote=False):
        return Assessment(decision, action, ACTIONS[action], priority,
                          round(min(conf, 0.99), 2), why, remote, out)

    # ORDER MATTERS, AND THIS IS THE ORDER.
    #
    # 1. Hardware alarms come first because a dead link or a stuck logger is a
    #    fault in any weather -- the context agent has nothing to say about it,
    #    and a coefficient cannot fix it. Sending someone with the wrong job
    #    wastes the visit.
    if hw.status == "alarm":
        gap = (e.gap_fraction or 0) > 0.2
        action = "COMMS" if gap else "INSPECT"
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
    if ctx.status == "ok":
        return done("normal", "MONITOR", 3, ctx.confidence,
                    "The neighbouring stations show the same movement, so this "
                    "is weather rather than a fault.")

    # 3. Nothing wrong with the readings.
    if dq.status == "ok":
        return done("normal", "MONITOR", 3, dq.confidence,
                    "Readings agree with the surrounding stations and the "
                    "device is healthy.")

    # 4. Not enough evidence yet to spend anyone's time.
    if dq.status == "unknown":
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

    if stable and e.noise_sigma is not None:
        return done("warning", "MONITOR", 3, dq.confidence,
                    f"A steady offset that grows only {growth:.1f} sigma before "
                    f"the next service visit, so a correction applied centrally "
                    f"holds until then.", remote=True)

    priority = 1 if dq.status == "alarm" else 2
    tail = (f" It moves a further {growth:.0f} sigma before the next "
            f"{SERVICE_INTERVAL_D:.0f}-day visit, so a correction applied today "
            f"would be wrong long before anyone arrives." if growth else "")
    return done("critical" if priority == 1 else "warning",
                "CALIBRATE", priority, dq.confidence,
                dq.headline + "." + tail)


def assess(e: Evidence) -> Assessment:
    """Run the panel and adjudicate. The one entry point."""
    return adjudicate(e, [agent(e) for agent in PANEL])


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
        out[ident] = assess(Evidence(**data)).dict()
    return {"assessments": out, "panel": [f.__name__ for f in PANEL],
            "actions": ACTIONS}


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
