"""The per-sensor file: what the system remembers about each instrument.

    from detect.belief import Belief, BeliefStore

WHAT THIS IS, AND WHY IT IS THE ARCHITECTURE

A pipeline judges each reading from nothing and forgets it. This does not. Every
(station, sensor) pair carries a small state that persists and updates, and the
anomaly falls out of the update rather than being its goal. That inversion is
what collapses seven separate objectives in PS26073 into one mechanism:

    "predict sensor degradation"   read the drift rate off the file
    "confidence score"             the state's own uncertainty
    "root-cause classification"    which field moved
    "sensor health status"         trust
    "corrected value"              subtract the bias

THE PRECEDENT, WHICH IS TWENTY YEARS OLD AND OPERATIONAL

ECMWF has run variational bias correction since 2006: each instrument's bias
coefficients sit inside the analysis control vector and are estimated jointly
with the atmospheric state, every cycle, rather than fitted offline. This is the
same idea with a cheaper estimator. What is unclaimed is aiming it at
DIAGNOSING THE INSTRUMENT rather than at correcting the forecast -- VarBC exists
to make the analysis better and never emits a work order.

THE ESTIMATOR, AND THE ONE LINE THAT MATTERS

A scalar Kalman filter on (bias, drift) with a ROBUST gain. The gain is what
separates a bad reading from a bad sensor:

    a spike is one huge innovation      -> gain collapses, belief barely moves
    a drift is many small innovations   -> gain stays high, belief tracks it

Without that, one spike would rewrite the station's whole calibration, and the
system would chase noise. With it, the state is exactly the slow, structural
part of the disagreement, which is what a maintenance decision needs.

WHY THE PROCESS NOISE IS SMALL

The bias of a healthy instrument is nearly constant, so the filter is
deliberately sluggish. Making it responsive would let it absorb a genuine drift
into the "bias" state within days and report a healthy sensor -- the same
self-masking measured in evaluation/run_edge_approx.py, where a baseline fitted
over a window containing a 0.02 K/day drift retained under 7 % of it. A belief
that adapts fast enough to explain everything explains nothing.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path

# --- filter constants -------------------------------------------------------
# All chosen from stated reasoning rather than tuned against labels, because
# tuning them on injected faults would make every downstream number circular.

# Process noise. How much we believe the bias can genuinely move per day, in
# units of the innovation scale. Small: a healthy instrument's offset is
# near-constant, and a responsive filter absorbs real drift (see module docstring).
Q_BIAS = 0.004
Q_DRIFT = 0.0008

# Robust gain cutoff, in robust sigmas. At this innovation the gain is halved;
# far beyond it the reading barely moves the belief at all. Set to the same
# 3-sigma convention the detectors use, so the filter starts discounting a
# reading exactly where a detector would start flagging it.
HUBER_C = 3.0

# Trust is a Beta reputation, not a hand-rolled ratchet.
#
# The first version moved trust up or down by a fixed step per update. Measured
# on real ARM instruments it was LOWER inside a human-confirmed fault in only
# 12 % of cases -- worse than chance -- because a single quiet sample ratcheted
# it straight back up. Beta reputation is the established form (Ganeriwal &
# Srivastava, RFSN): every check is a Bernoulli trial, Beta is its conjugate, so
# the posterior is two counters and a forgetting factor.
#
# It also gives something the ratchet could not: CONFIDENCE. alpha+beta is the
# weight of evidence behind the trust value, so a station with 4 observations
# and a station with 4,000 are no longer indistinguishable.
TRUST_LAMBDA = 0.999          # forgetting; half-life ~29 days at hourly cadence
TRUST_PRIOR_A = 2.0           # mild optimism, so a new station is usable
TRUST_PRIOR_B = 1.0
TRUST_FLOOR = 0.05

# Noise-scale smoothing. Degradation shows in the second moment before the
# first, so this is tracked separately rather than inferred from the bias.
NOISE_ALPHA = 0.02

# The noise update sees the residual clipped at this many robust sigmas, and the
# scale is additionally not allowed to grow faster than NOISE_MAX_GROWTH per
# update. Clipping alone was not enough: the clip is relative to the current
# scale, so the scale ratchets up geometrically and still swallows the fault.
NOISE_CLIP = 3.0
NOISE_MAX_GROWTH = 1.01

# |bias| beyond this many robust sigmas counts as a FAILED check, independently
# of whether the innovation is currently small.
#
# THIS IS THE CORRECTION THAT MATTERS, and the first two attempts missed it. A
# bias estimator is SUPPOSED to absorb a sustained step -- that is its job -- so
# once the filter has adapted, the reading matches the model, the innovation
# collapses, and any trust defined on the innovation alone climbs back to full
# confidence while the sensor sits 5 sigma off. Trust was asking "does this
# reading match my model" when the operational question is "is this sensor
# sound". Those are different, and only the second one belongs in a work order.
BIAS_TOLERANCE = 2.0


@dataclass
class Belief:
    """What is known about one sensor on one station."""

    station: str
    sensor: str                      # temp | pres | rh | logger_volt | ...
    bias: float = 0.0                # current offset from the reference
    drift: float = 0.0               # rate of change of bias, per day
    var_bias: float = 1.0            # filter uncertainty on bias
    var_drift: float = 0.01          # filter uncertainty on drift
    noise: float = 1.0               # robust scale of the innovation
    alpha: float = TRUST_PRIOR_A     # Beta reputation: weight of checks passed
    beta: float = TRUST_PRIOR_B      # weight of checks failed
    n: int = 0                       # updates seen
    last_update: str | None = None
    last_service: str | None = None

    # ---------------------------------------------------------------- update
    def update(self, innovation: float, dt_days: float,
               when: datetime | None = None) -> "Belief":
        """Fold one observation-minus-reference into the state.

        `innovation` is the station's disagreement with whatever reference the
        caller trusts -- neighbours, a model, the station's own climatology.
        This function does not care which, which is what lets the same state
        serve the meteorological channels and the housekeeping ones.
        """
        if not math.isfinite(innovation):
            return self
        dt = max(float(dt_days), 0.0)

        # --- predict: bias moves along its drift, uncertainty grows
        b = self.bias + self.drift * dt
        d = self.drift
        vb = self.var_bias + self.var_drift * dt * dt + Q_BIAS * dt
        vd = self.var_drift + Q_DRIFT * dt

        resid = innovation - b
        scale = max(self.noise, 1e-6)
        z = abs(resid) / scale

        # --- robust gain. THE line that separates a bad reading from a bad
        # sensor: a large isolated innovation is discounted, a persistent small
        # one is not.
        w = 1.0 / (1.0 + (z / HUBER_C) ** 2)
        r = (scale * scale) / max(w, 1e-3)          # inflate R for outliers
        k_b = vb / (vb + r)
        k_d = (self.var_drift * dt) / (vb + r) if dt > 0 else 0.0

        b_new = b + k_b * resid
        d_new = d + k_d * resid
        vb_new = (1.0 - k_b) * vb
        vd_new = max(vd - k_d * k_d * (vb + r), 1e-9)

        # Noise scale, from the clipped residual and additionally rate-limited,
        # so a sustained fault cannot walk the scale up until it looks normal.
        capped = min(abs(resid), NOISE_CLIP * scale)
        noise_new = (1.0 - NOISE_ALPHA) * self.noise + NOISE_ALPHA * capped
        noise_new = min(noise_new, scale * NOISE_MAX_GROWTH)

        # Beta reputation. Each update is one Bernoulli trial, and the trial has
        # TWO conditions: the reading behaved, AND the sensor is not sitting on a
        # large accumulated offset. The second is what makes trust survive the
        # filter adapting to a fault -- see BIAS_TOLERANCE.
        in_spec = abs(b_new) <= BIAS_TOLERANCE * max(noise_new, 1e-6)
        passed = 1.0 if (z <= HUBER_C and in_spec) else 0.0
        a_new = TRUST_LAMBDA * self.alpha + passed
        b_beta = TRUST_LAMBDA * self.beta + (1.0 - passed)

        return Belief(
            station=self.station, sensor=self.sensor,
            bias=b_new, drift=d_new, var_bias=vb_new, var_drift=vd_new,
            noise=max(noise_new, 1e-6), alpha=a_new, beta=b_beta, n=self.n + 1,
            last_update=(when or datetime.utcnow()).isoformat(timespec="seconds"),
            last_service=self.last_service,
        )

    # ------------------------------------------------------------ reputation
    @property
    def trust(self) -> float:
        """Posterior mean of the Beta reputation."""
        return max(TRUST_FLOOR, self.alpha / max(self.alpha + self.beta, 1e-9))

    @property
    def trust_confidence(self) -> float:
        """Weight of evidence behind that trust value.

        A station seen four times and one seen four thousand times can both read
        0.9; this is what tells them apart, and it is what the previous
        hand-rolled ratchet could not express at all.
        """
        return self.alpha + self.beta

    @property
    def checks_passed(self) -> str:
        """The trust value in words an operator can act on."""
        total = self.alpha + self.beta
        return f"{self.alpha:.0f} of {total:.0f} recent checks passed"

    # ------------------------------------------------------------- readouts
    @property
    def bias_ci(self) -> tuple[float, float]:
        """Bias with a 2-sigma interval. A work order needs the interval."""
        s = 2.0 * math.sqrt(max(self.var_bias, 0.0))
        return (self.bias - s, self.bias + s)

    def days_to_spec(self, limit: float) -> float | None:
        """Days until |bias| crosses an instrument specification limit.

        This is the PS's "predict sensor degradation", and it is a division
        rather than a model. Returns None when the drift is not resolvable
        against its own uncertainty -- extrapolating an unresolved slope is how
        teams produce confident nonsense about failure dates.
        """
        sd = math.sqrt(max(self.var_drift, 0.0))
        if abs(self.drift) < 2.0 * sd or abs(self.drift) < 1e-9:
            return None
        remaining = limit - abs(self.bias)
        if remaining <= 0:
            return 0.0
        return remaining / abs(self.drift)

    def serviced(self, when: date | datetime) -> "Belief":
        """Reset after a confirmed repair.

        Without this a REPAIRED station stays condemned by its own history,
        which is a real and commonly-missed bug. The bias is zeroed and the
        uncertainty reopened; trust returns to a prior rather than to 1.0,
        because the repair is a claim until the data supports it.
        """
        return Belief(station=self.station, sensor=self.sensor,
                      bias=0.0, drift=0.0, var_bias=1.0, var_drift=0.01,
                      noise=self.noise,
                      alpha=TRUST_PRIOR_A, beta=TRUST_PRIOR_B, n=0,
                      last_update=self.last_update,
                      last_service=(when.isoformat() if hasattr(when, "isoformat")
                                    else str(when)))


class BeliefStore:
    """Every sensor's file, persisted.

    Deliberately a plain dict over a JSON file rather than a database. At 1,000
    stations by three sensors this is a few thousand small records -- the
    scaling axis here is per-station state, not throughput, and it fits in RAM
    with room to spare. Swapping in a real table later changes this class and
    nothing else.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._b: dict[tuple[str, str], Belief] = {}
        if self.path and self.path.exists():
            self.load()

    def get(self, station: str, sensor: str) -> Belief:
        key = (station, sensor)
        if key not in self._b:
            self._b[key] = Belief(station=station, sensor=sensor)
        return self._b[key]

    def update(self, station: str, sensor: str, innovation: float,
               dt_days: float, when: datetime | None = None) -> Belief:
        b = self.get(station, sensor).update(innovation, dt_days, when)
        self._b[(station, sensor)] = b
        return b

    def __len__(self) -> int:
        return len(self._b)

    def __iter__(self):
        return iter(self._b.values())

    def save(self) -> None:
        if not self.path:
            raise ValueError("no path set")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # write to a temp name first: a crash mid-write must not leave a
        # truncated file that looks like a valid, empty belief store
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(b) for b in self._b.values()],
                                  indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> None:
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        self._b = {(r["station"], r["sensor"]): Belief(**r) for r in rows}

    def to_frame(self):
        """The network's belief about itself, as a table an operator can read."""
        import pandas as pd
        rows = []
        for b in self._b.values():
            lo, hi = b.bias_ci
            rows.append({"station": b.station, "sensor": b.sensor,
                         "bias": round(b.bias, 4),
                         "bias_lo": round(lo, 4), "bias_hi": round(hi, 4),
                         "drift_per_day": round(b.drift, 5),
                         "noise": round(b.noise, 4),
                         "trust": round(b.trust, 3),
                         "trust_evidence": round(b.trust_confidence, 1),
                         "n": b.n,
                         "last_service": b.last_service})
        return pd.DataFrame(rows)
