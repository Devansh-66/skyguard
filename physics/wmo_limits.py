"""Instrument limits from WMO-No. 8, quoted rather than chosen.

SOURCE, EXACTLY

Guide to Instruments and Methods of Observation (WMO-No. 8), Volume I:
Measurement of Meteorological Variables, 2024 edition. ANNEX 1.A,
"Operational measurement uncertainty requirements and instrument performance"
-- PDF pages 46 to 48 of WMO-8-vI-2024_en.pdf.

The Guide states the provenance of that annex itself: the requirements were
established by the CBS Expert Team on Requirements for Data from Automatic
Weather Stations (2004) and approved by the president of CIMO; the achievable
figures were established by the CIMO Expert Team on Surface Technology and
Measurement Techniques (2004). Section 1.6.4.2 adds the caveat that they "are
the most authoritative at the time of writing... but they are not fully
definitive", and that "the achievable operational uncertainty in many cases does
not meet the stated requirements".

WHY THIS FILE EXISTS

Every threshold in this project was previously a number we picked. Defensible
ones -- typical NWP observation-error scales -- but ours, and a reviewer is
entitled to ask where they came from. These are the international standard for
the three variables the problem statement allows, and they are quoted with the
page they came from so anyone can check them.

WHAT IS NOT HERE

Volume I gives range, resolution and uncertainty. It does NOT give the numeric
step, persistence and internal-consistency limits used in automatic quality
control -- those live in Volume III (Observing Systems) and in the CBS
guidelines on QC procedures for AWS data. Searching pages 250-320 of Volume I
for step and persistence thresholds returned only a generic "jump filter" row
with no number attached. So the QC check limits in this project remain ours, and
are still marked as such.

THE GAP THIS MEASUREMENT OPENED

Our working tolerances were 1.5 K, 10 % and 1.0 hPa. WMO's ACHIEVABLE
uncertainties are 0.2 K, 3 % and 0.15 hPa. Ours are 7.5, 3.3 and 6.7 times
looser. That is not simply an error: our tolerance is applied to a NEIGHBOUR
DIFFERENCE, which carries representativeness error as well as instrument error,
and the measured neighbour-difference spread on the simulated network is about
0.37 K -- already twice WMO's achievable instrument uncertainty before any fault
is present. The two numbers answer different questions and both belong:

    ACHIEVABLE      what one instrument should manage on its own. A sensor whose
                    own short-term noise exceeds this is failing its spec, and
                    that is a per-station check needing no neighbour at all.
    TOLERANCE       what a difference between two stations can be before it
                    means something. Necessarily larger.
"""
from __future__ import annotations

# Keys are this project's channel names; the annex's own wording is in `note`.
WMO_ANNEX_1A: dict[str, dict] = {
    "temp": {
        "annex_row": "1.1 Air temperature",
        "range": (-80.0, 60.0),          # degC
        "reported_resolution": 0.1,      # K
        "required_uncertainty": 0.1,     # K, for -40 < T <= 40 degC
        "required_uncertainty_extremes": 0.3,   # K, outside that band
        "achievable_uncertainty": 0.2,   # K
        "time_constant_s": 20.0,
        "averaging_min": 1.0,
        "unit": "K",
        "note": ("Achievable uncertainty and effective time constant may be "
                 "affected by the design of the thermometer solar radiation "
                 "screen. Time constant depends on the airflow over the "
                 "sensing element."),
    },
    "rh": {
        "annex_row": "2.2 Relative humidity",
        "range": (0.0, 100.0),           # %
        "reported_resolution": 1.0,      # %
        "required_uncertainty": 1.0,     # %
        # The annex splits achievable by sensing method. An AWS -- and an ESP32
        # with a capacitive probe -- is the solid-state row, not the
        # psychrometer row, so 3% is the figure that applies to this project.
        "achievable_uncertainty": 3.0,   # %, solid state and others
        "achievable_uncertainty_psychrometer": 0.2,   # K on the wet bulb
        "time_constant_s": 40.0,         # solid state
        "averaging_min": 1.0,
        "unit": "%",
        "note": ("Time constant and achievable uncertainty of solid-state "
                 "sensing instruments may show significant temperature and "
                 "humidity dependence."),
    },
    "pres": {
        "annex_row": "3.1 Pressure",
        "range": (500.0, 1080.0),        # hPa
        "reported_resolution": 0.1,      # hPa
        "required_uncertainty": 0.1,     # hPa
        "achievable_uncertainty": 0.15,  # hPa
        "time_constant_s": 2.0,
        "averaging_min": 1.0,
        "unit": "hPa",
        "note": ("Both station pressure and MSL pressure. Measurement "
                 "uncertainty is seriously affected by dynamic pressure due to "
                 "wind if no precautions are taken. Inadequate temperature "
                 "compensation of the transducer may affect the measurement "
                 "uncertainty significantly."),
    },
    # Carried because pressure tendency is a separate annex row and this project
    # uses the barometer as a clock: 3.2 Tendency, required 0.2 hPa, achievable
    # 0.2 hPa, "difference between instantaneous values".
    "pres_tendency": {
        "annex_row": "3.2 Tendency",
        "reported_resolution": 0.1,
        "required_uncertainty": 0.2,
        "achievable_uncertainty": 0.2,
        "unit": "hPa",
        "note": "Difference between instantaneous values.",
    },
}

CITATION = ("WMO-No. 8, Guide to Instruments and Methods of Observation, "
            "Volume I: Measurement of Meteorological Variables, 2024 edition, "
            "Annex 1.A (pp. 25-27 / PDF pp. 46-48).")


def wmo_range(channel: str) -> tuple[float, float]:
    """The stated measuring range. A reading outside this is not an anomaly to
    be scored -- it is outside what the instrument is defined to report."""
    return WMO_ANNEX_1A[channel]["range"]


def achievable(channel: str) -> float:
    """Uncertainty a good instrument should achieve operationally. Used as the
    NOISE FLOOR: an estimated per-sensor noise below this is not credible, and
    one far above it is a sensor failing its own specification."""
    return WMO_ANNEX_1A[channel]["achievable_uncertainty"]


def resolution(channel: str) -> float:
    """Reported resolution. A channel whose values only ever land on multiples
    coarser than this is quantised more than the standard allows -- which is one
    of the few things a single station can detect about itself."""
    return WMO_ANNEX_1A[channel]["reported_resolution"]


def spec_ratio(channel: str, measured_noise: float) -> float:
    """How far a measured per-sensor noise sits above what WMO says is
    achievable. 1.0 is at spec; 5 is a sensor that should be looked at
    regardless of what its neighbours are doing."""
    a = achievable(channel)
    return float(measured_noise) / a if a > 0 else float("nan")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ours = {"temp": 1.5, "rh": 10.0, "pres": 1.0}   # what this project has used
    print(CITATION)
    print()
    print(f"{'channel':8s} {'range':>18s} {'res':>6s} {'required':>9s} "
          f"{'achievable':>11s} {'ours':>7s} {'ratio':>7s}")
    for k in ("temp", "rh", "pres"):
        w = WMO_ANNEX_1A[k]
        lo, hi = w["range"]
        o = ours[k]
        print(f"{k:8s} {f'{lo:g} to {hi:g}':>18s} "
              f"{w['reported_resolution']:>6g} "
              f"{w['required_uncertainty']:>9g} "
              f"{w['achievable_uncertainty']:>11g} "
              f"{o:>7g} {o / w['achievable_uncertainty']:>6.1f}x")
    print()
    print("ours = the neighbour-difference tolerance this project has been "
          "using; it is applied to a DIFFERENCE and so is necessarily larger "
          "than a single instrument's achievable uncertainty. Both belong.")
