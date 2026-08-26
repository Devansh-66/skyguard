"""The checkers, and the adjudicator that will not take one of them at its word.

    from detect.checkers import run_panel, Verdict

WHAT THIS IS, NAMED HONESTLY

This is a BLACKBOARD architecture (Hearsay-II, 1980): independent knowledge
sources post evidence to a shared record, and a control component decides. In
meteorology specifically it is COMPLEX QUALITY CONTROL (Gandin, Monthly Weather
Review 116(5), 1988), which combines a complex of residuals through a decision
algorithm and has been operational since the 1980s. Neither is our invention and
both are better cited than reinvented.

What is ours is narrower: the pressure tide as a per-station clock, Level-0 on
the station itself, and the hardware channel as an independent evidence source.

THE RULE, STATED SO IT CAN BE FALSIFIED

An earlier version said "corroboration must come from checkers whose evidence
does not overlap". That asserts independence rather than measuring it, and the
ensemble literature is emphatic that assumed diversity does not deliver --
Kuncheva & Whitaker (2003) found the diversity-accuracy relationship "weak and
inconsistent on real problems", and Knight & Leveson (1986) showed 27
independently written programs failing together far more than independence
predicts.

So the rule here is: corroboration requires two checkers whose MEASURED
double-fault rate is below a stated threshold. The matrix is loaded from disk
and is empty until somebody measures it, at which point every pair is treated as
unproven and the panel says so.

WHY THE HARDWARE CHECKER MATTERS MORE THAN THE OTHERS

Every meteorological checker here ultimately reads the same three numbers. That
is a shared failure path -- common-cause failure, which in reliability
engineering floors even deliberately diverse redundant subsystems around 1e-3.
The hardware channel reads logger voltage and logger temperature, which come off
a DIFFERENT physical measurement chain. It is the only evidence in the panel
that can be right when the meteorology is wrong, and it is therefore the one
that makes corroboration mean anything.

Confirmed real rather than assumed: logger_volt and logger_temp each appear in
11 of ARM's human-written fault reports.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

# Pairs whose measured double-fault rate is below this may corroborate.
TAU_DOUBLE_FAULT = 0.05

# Innovation, in robust sigmas, at which a checker fires.
FIRE_AT = 3.0


@dataclass
class Verdict:
    """One checker's evidence. Never a decision."""

    checker: str
    fired: bool
    score: float                 # signed, in robust sigmas, comparable across checkers
    reason: str                  # the sentence an operator reads
    evidence: dict = field(default_factory=dict)


@dataclass
class Decision:
    """What the panel concluded, and why."""

    verdict: str                 # pass | alarm | unknown
    verdicts: list[Verdict]
    corroborated_by: tuple[str, str] | None = None
    note: str = ""

    @property
    def fired(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.fired]

    def explain(self) -> str:
        """Explainability without an explainer: the verdicts ARE the reasons."""
        if self.verdict == "pass":
            return "no checker fired"
        parts = [f"{v.checker} {v.score:+.1f}σ ({v.reason})" for v in self.fired]
        head = {"alarm": "ALARM", "unknown": "UNKNOWN"}[self.verdict]
        if self.corroborated_by:
            head += f" — corroborated by {self.corroborated_by[0]} + {self.corroborated_by[1]}"
        elif self.note:
            head += f" — {self.note}"
        return head + ": " + "; ".join(parts)


# --------------------------------------------------------------- the checkers
# Each takes (context dict) and returns a Verdict. Pure functions, no state, so
# they can be run in any order and tested one at a time.


def check_physics(ctx: dict) -> Verdict:
    """Hard thermodynamic bounds. Fires only on the physically impossible.

    Deliberately thin, because at a single instant T, P and RH ARE the state --
    three degrees of freedom, three numbers -- so they cannot cross-check one
    another. A "dew point cannot exceed temperature" test was removed after
    being shown unreachable: swept over the whole valid rail box, max(Td - T) is
    -0.039 K. It is an identity, not a constraint. Supersaturation is the check
    that does real work.
    """
    t, p, rh = ctx["temp"], ctx["pres"], ctx["rh"]
    bad, missing = [], []

    # A missing reading is NOT an out-of-range reading, and conflating them
    # produces "temperature nan °C outside instrument range", which is both
    # wrong and unreadable. Found when a real ARM lightning strike killed a
    # station: every channel went NaN and the panel reported nonsense.
    # Absence is its own fault class -- it means the link or the logger, not the
    # sensor -- and it points at a different repair.
    for name, val, unit, lo, hi in (("temperature", t, "°C", -40, 60),
                                    ("pressure", p, "hPa", 500, 1100),
                                    ("humidity", rh, "%", 0, 105)):
        if val is None or not math.isfinite(val):
            missing.append(name)
        elif not (lo <= val <= hi):
            bad.append(f"{name} {val:.1f} {unit} outside instrument range")
        elif name == "humidity" and val > 100:
            bad.append(f"supersaturated at {val:.1f} %")

    if missing:
        return Verdict("physics", True, 9.9,
                       "no reading for " + ", ".join(missing)
                       + " — the station or its link, not the sensor",
                       {"missing": missing, "mode": "dropout"})
    return Verdict("physics", bool(bad), 9.9 if bad else 0.0,
                   "; ".join(bad) or "within physical bounds",
                   {"n_violations": len(bad), "mode": "range" if bad else "ok"})


def check_neighbour(ctx: dict) -> Verdict:
    """Disagreement with the trust-weighted consensus of nearby stations.

    Works in SPECIFIC HUMIDITY rather than relative humidity for the moisture
    channel. Measured on real ARM observations, RH's diurnal swing is 1.39x its
    synoptic spread while q's is 0.45 -- the sun moves RH three times harder, so
    a fault of the same size is three times more buried there.
    """
    d = ctx.get("neighbour_diff")
    s = ctx.get("neighbour_sigma")
    if d is None or s is None or not math.isfinite(d) or not s:
        return Verdict("neighbour", False, 0.0, "no usable neighbours",
                       {"available": False})
    z = d / s
    n = ctx.get("n_neighbours", 0)
    return Verdict("neighbour", abs(z) > FIRE_AT, z,
                   f"{d:+.2f} against {n} neighbour(s)",
                   {"n_neighbours": n, "diff": d})


def check_history(ctx: dict) -> Verdict:
    """Disagreement with what this station itself normally does now.

    The reference is the station's own frozen seasonal baseline, never a
    refitted one. Measured: a baseline refitted over a window containing a
    0.02 K/day drift retains under 7 % of it, so a self-updating baseline goes
    blind to exactly the fault it should expose.
    """
    r = ctx.get("own_resid")
    s = ctx.get("own_sigma")
    if r is None or s is None or not math.isfinite(r) or not s:
        return Verdict("history", False, 0.0, "no baseline yet", {"available": False})
    z = r / s
    return Verdict("history", abs(z) > FIRE_AT, z,
                   f"{r:+.2f} against its own seasonal normal", {"resid": r})


def check_instrument(ctx: dict) -> Verdict:
    """Signature of a known failure mode in the recent window."""
    flat = ctx.get("flat_fraction", 0.0)
    jump = ctx.get("jump_sigma", 0.0)
    if flat >= 0.95:
        return Verdict("instrument", True, 6.0,
                       f"value unchanged in {flat*100:.0f} % of the window",
                       {"mode": "frozen"})
    if abs(jump) > 6.0:
        return Verdict("instrument", True, jump,
                       f"single-sample step of {jump:+.1f}σ", {"mode": "spike"})
    return Verdict("instrument", False, jump, "no known fault signature", {})


def check_clock(ctx: dict) -> Verdict:
    """Timing, from the phase of the semidiurnal pressure tide.

    The atmosphere has a twice-daily pressure oscillation, solar-locked and
    phase-stable, so a station's own barometer carries a clock. Measured on our
    data: amplitude 1.38-1.72 hPa, 30-day phase scatter equal to about 10
    minutes, and a known offset recovered exactly from 10 to 120 minutes.

    Scope it honestly: this buys the CLOCK and nothing else. A pressure span
    error moves the tide 0.02 hPa against ~1.5, and an additive offset leaves it
    untouched. "Incorrect data logger clock" is a real ARM fault report, so the
    fault class is documented rather than hypothesised.
    """
    off = ctx.get("clock_offset_min")
    sd = ctx.get("clock_sigma_min", 10.0)
    if off is None or not math.isfinite(off):
        return Verdict("clock", False, 0.0, "tide phase not available",
                       {"available": False})
    z = off / max(sd, 1e-6)
    return Verdict("clock", abs(z) > FIRE_AT, z,
                   f"tide phase implies a clock error of {off:+.0f} min",
                   {"offset_min": off})


def check_hardware(ctx: dict) -> Verdict:
    """Logger voltage and internal temperature.

    THE IMPORTANT ONE. Every other checker above reads the same three
    meteorological numbers and so shares a failure path with them. This reads a
    different physical measurement chain, which is what lets its agreement with
    another checker carry real information rather than restating the same
    evidence twice.

    It is also the only channel that can fire BEFORE the measurement degrades: a
    battery sags before the reading corrupts, and enclosure temperature tracks
    ambient before a seal failure shows up in the data.
    """
    z_v = ctx.get("volt_z")
    z_t = ctx.get("logger_temp_z")
    if z_v is None and z_t is None:
        return Verdict("hardware", False, 0.0, "no housekeeping reported",
                       {"available": False})
    parts, worst = [], 0.0
    if z_v is not None and math.isfinite(z_v):
        worst = max(worst, abs(z_v))
        if abs(z_v) > FIRE_AT:
            parts.append(f"logger voltage {z_v:+.1f}σ from its normal")
    if z_t is not None and math.isfinite(z_t):
        worst = max(worst, abs(z_t))
        if abs(z_t) > FIRE_AT:
            parts.append(f"logger temperature {z_t:+.1f}σ from its normal")
    return Verdict("hardware", bool(parts), worst,
                   "; ".join(parts) or "housekeeping nominal",
                   {"volt_z": z_v, "logger_temp_z": z_t})


PANEL: Sequence[Callable[[dict], Verdict]] = (
    check_physics, check_neighbour, check_history,
    check_instrument, check_clock, check_hardware,
)


# --------------------------------------------------------------- adjudication

class DoubleFaultMatrix:
    """Measured joint-failure rates between checkers.

    Empty until somebody measures it on labelled data, and an EMPTY MATRIX MEANS
    NO PAIR IS PROVEN INDEPENDENT. The panel then refuses to raise an alarm on
    corroboration alone and says why, rather than quietly assuming the thing the
    literature says is usually false.
    """

    def __init__(self, path: str | Path | None = None):
        self.m: dict[str, dict[str, float]] = {}
        self.regime: str = "all"
        p = Path(path) if path else None
        if p and p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            self.m = d.get("double_fault", {})
            self.regime = d.get("regime", "all")

    def rate(self, a: str, b: str) -> float | None:
        return self.m.get(a, {}).get(b, self.m.get(b, {}).get(a))

    def independent(self, a: str, b: str, tau: float = TAU_DOUBLE_FAULT) -> bool:
        r = self.rate(a, b)
        return r is not None and r < tau

    def __bool__(self) -> bool:
        return bool(self.m)


def adjudicate(verdicts: list[Verdict], dfm: DoubleFaultMatrix | None = None,
               tau: float = TAU_DOUBLE_FAULT) -> Decision:
    """Combine evidence. No single checker may raise an alarm.

    One exception, and it is deliberate: `physics` fires only on the
    impossible -- a value outside what the instrument can physically report --
    and an impossible reading needs no corroboration. Requiring a second opinion
    on a -999 sentinel would be theatre.
    """
    dfm = dfm or DoubleFaultMatrix()
    fired = [v for v in verdicts if v.fired]

    if not fired:
        return Decision("pass", verdicts)

    phys = next((v for v in fired if v.checker == "physics"), None)
    if phys is not None:
        return Decision("alarm", verdicts, note="physically impossible reading")

    if len(fired) == 1:
        return Decision("unknown", verdicts,
                        note=f"only {fired[0].checker} fired; nothing corroborates it")

    if not dfm:
        return Decision("unknown", verdicts,
                        note="no measured double-fault matrix, so no pair is "
                             "proven independent")

    for i in range(len(fired)):
        for j in range(i + 1, len(fired)):
            a, b = fired[i].checker, fired[j].checker
            if dfm.independent(a, b, tau):
                return Decision("alarm", verdicts, corroborated_by=(a, b))

    pairs = ", ".join(f"{fired[i].checker}+{fired[j].checker}"
                      for i in range(len(fired)) for j in range(i + 1, len(fired)))
    return Decision("unknown", verdicts,
                    note=f"{len(fired)} fired but no independent pair among them "
                         f"({pairs})")


def run_panel(ctx: dict, dfm: DoubleFaultMatrix | None = None) -> Decision:
    """Run every checker over one reading and adjudicate."""
    return adjudicate([c(ctx) for c in PANEL], dfm)
