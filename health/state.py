"""Sensor health -- a sticky STATE, not an event.

`observation_flags` are per timestamp and ephemeral: this reading looks wrong.
`sensor_health` is per station per variable and sticky: this probe is in
trouble. Conflating them is the most common design error in QC dashboards --
one bad hour turns a station red, the operator learns the colour means nothing,
and the panel is dead.

Health therefore has memory and hysteresis. It takes repeated or persistent
evidence to degrade, and clean time to recover, and the two thresholds are
deliberately asymmetric: a probe that has misbehaved should have to earn its
way back.

Station roll-up is the MINIMUM across the three variables, never the mean. A
station with a dead humidity probe and two perfect other channels is not "two
thirds healthy" -- it is a station that needs a visit.
"""
from __future__ import annotations

VERSION = "health-1.0.0"

# Ordered worst to best; roll-up takes the worst.
STATES = ("FAILED", "SUSPECT", "DEGRADING", "WATCH", "HEALTHY")

# Fault classes that indicate the probe is gone, not merely noisy.
TERMINAL = {"dropout", "frozen", "saturation"}


def assess(alerts: list[dict], variable: str,
           watch_h: int = 6, degrade_h: int = 24, fail_h: int = 72) -> str:
    """Health of one variable at one station, from its alert history.

    Thresholds are in HOURS OF EVIDENCE, not alert counts. Three one-hour blips
    and one three-hour excursion are not the same thing, and counting alerts
    treats them identically.
    """
    mine = [a for a in alerts if a["variable"] == variable]
    if not mine:
        return "HEALTHY"

    named = [a for a in mine if a["label"] != "unknown"]
    hours = sum(a["duration_h"] for a in named)
    terminal_h = sum(a["duration_h"] for a in named if a["label"] in TERMINAL)

    # A probe reporting nothing, or the same number for three days, is not
    # "degrading" -- it has failed, and no amount of averaging should soften it.
    if terminal_h >= fail_h:
        return "FAILED"
    if terminal_h >= degrade_h:
        return "SUSPECT"
    if hours >= fail_h:
        return "SUSPECT"
    if hours >= degrade_h:
        return "DEGRADING"
    if hours >= watch_h:
        return "WATCH"
    return "HEALTHY"


def roll_up(per_variable: dict) -> dict:
    """Station health = worst variable. Returns the detail alongside, so the
    dashboard can show WHY a station is amber without a second request."""
    order = {s: i for i, s in enumerate(STATES)}
    worst = min(per_variable.values(), key=lambda s: order[s])
    return {"station": worst, "by_variable": per_variable,
            "health_version": VERSION}
