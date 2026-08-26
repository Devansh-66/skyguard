"""What actually binds temperature, pressure and humidity -- measured, not asserted.

    python -m evaluation.run_physics_map

WHY THIS EXISTS

PS26073 gives three numbers and asks for "multivariate consistency analysis".
The temptation is to reach for a model. But three numbers are not three
independent signals -- they are one thermodynamic state, and the relations
between them are known exactly. The job of the AI is to AUTOMATE that physics
across a thousand stations, not to rediscover it badly from data.

So this script opens the domain: from T, P and RH it derives every quantity the
thermodynamics gives us, then MEASURES which of them the atmosphere holds
roughly constant and which it swings wildly. That split is the whole detection
thesis, because:

    a fault breaks an invariant.  weather preserves it.

The conserved quantities are therefore where a fault is visible against a quiet
background, and the swinging ones are where it is buried in natural variation.

THE UNCOMFORTABLE FACT THAT COMES FIRST

At a single instant there is NO redundancy. The local thermodynamic state of
moist air has three degrees of freedom, and T, P, RH are three numbers, so they
determine the state exactly and cannot cross-check one another. Every derived
quantity below is a re-expression of the same three numbers, not new
information. This is why a "dew point cannot exceed temperature" check turned
out to be unreachable -- it is not a constraint, it is an identity.

Redundancy has to come from somewhere else, and there are only three sources:

    TIME      the conserved quantities should not jump between samples
    SPACE     neighbouring stations share an air mass
    STRUCTURE the diurnal and annual cycles are deterministic

That is the honest answer to "perform multivariate consistency analysis": it is
impossible instantaneously, and becomes possible only through time, space and
cycle structure. Stating that clearly is worth more than a model that pretends
otherwise.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ constants
EPS = 0.622          # ratio of molar masses, water vapour to dry air
RD = 287.05          # gas constant for dry air, J/(kg K)
CP = 1004.6          # specific heat at constant pressure, J/(kg K)
LV = 2.501e6         # latent heat of vaporisation at 0 C, J/kg
KAPPA = RD / CP      # ~0.2857, the Poisson exponent


def es_hpa(t_c):
    """Saturation vapour pressure, Magnus form. Function of TEMPERATURE ALONE.

    This is the hinge of the whole system: humidity's meaning depends on
    temperature, which is why a thermometer fault propagates straight into
    every humidity-derived quantity and makes one broken sensor look like two.
    """
    t_c = np.asarray(t_c, dtype=float)
    a = np.where(t_c >= 0, 17.368, 17.966)
    b = np.where(t_c >= 0, 238.88, 247.15)
    return 6.1121 * np.exp(a * t_c / (b + t_c))


def derive(t, p, rh):
    """Every quantity the thermodynamics gives us from the three measured ones."""
    t = np.asarray(t, float); p = np.asarray(p, float); rh = np.asarray(rh, float)
    e = np.clip(rh, 0.01, None) / 100.0 * es_hpa(t)          # vapour pressure
    # dew point, by inverting Magnus
    a = np.where(t >= 0, 17.368, 17.966)
    b = np.where(t >= 0, 238.88, 247.15)
    g = np.log(np.clip(e / 6.1121, 1e-9, None))
    td = b * g / (a - g)
    q = EPS * e / (p - (1 - EPS) * e)                        # specific humidity
    r = EPS * e / (p - e)                                    # mixing ratio
    tk = t + 273.15
    tv = tk * (1 + 0.608 * q)                                # virtual temperature
    theta = tk * (1000.0 / p) ** KAPPA                       # potential temperature
    theta_e = theta * np.exp(LV * q / (CP * tk))             # equivalent potential
    rho = p * 100.0 / (RD * tv)                              # air density
    # wet bulb, Stull (2011) empirical -- good to ~0.3 K for 5 < RH < 99
    rhc = np.clip(rh, 5.0, 99.0)
    tw = (t * np.arctan(0.151977 * np.sqrt(rhc + 8.313659))
          + np.arctan(t + rhc) - np.arctan(rhc - 1.676331)
          + 0.00391838 * rhc ** 1.5 * np.arctan(0.023101 * rhc) - 4.686035)
    return {
        "T  temperature": t,
        "RH relative humidity": rh,
        "P  pressure": p,
        "Td dew point": td,
        "T-Td dew point depression": t - td,
        "Tw wet bulb": tw,
        "e  vapour pressure": e,
        "q  specific humidity": q * 1000.0,                  # g/kg
        "r  mixing ratio": r * 1000.0,                       # g/kg
        "theta potential temp": theta,
        "theta_e equivalent pot temp": theta_e,
        "rho density": rho,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_realistic.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    d = derive(df.temp, df.pres, df.rh)
    frame = pd.DataFrame(d)
    frame["station"] = df.station_name.values
    frame["day"] = df.timestamp.dt.floor("D").values

    print("=== 1. Which quantities does the atmosphere hold still? ===")
    print("For each derived quantity: how much it swings WITHIN a day (the")
    print("diurnal cycle) against how much its daily MEAN swings between days")
    print("(weather). A small ratio means the diurnal cycle barely moves it --")
    print("it is conserved through heating and cooling, so a fault that moves")
    print("it has nowhere to hide.\n")

    rows = []
    for name in d:
        g = frame.groupby(["station", "day"])[name]
        within = g.apply(lambda s: s.max() - s.min()).median()   # diurnal range
        between = g.mean().groupby(level=0).std().median()       # synoptic
        rows.append({"quantity": name,
                     "diurnal range": round(float(within), 3),
                     "synoptic sd": round(float(between), 3),
                     "ratio": round(float(within / between), 2) if between else np.nan})
    t1 = pd.DataFrame(rows).sort_values("ratio")
    print(t1.to_string(index=False))
    print("\nRead the top of that table: those are the CONSERVED coordinates.")
    print("The bottom are the ones the sun moves every single day.")

    print("\n\n=== 2. Which fault breaks which relation? ===")
    print("Each fault is applied to a clean sample and the perturbation of every")
    print("derived quantity is measured, in units of that quantity's own natural")
    print("diurnal range. A big number means the fault stands out THERE.\n")

    s = df.sample(min(4000, len(df)), random_state=0)
    base = derive(s.temp, s.pres, s.rh)
    scale = {k: max(float(np.percentile(np.abs(np.diff(np.sort(v))), 99) * 1e-9),
                    float(t1.loc[t1.quantity == k, "diurnal range"].iloc[0]))
             for k, v in base.items()}

    faults = {
        "T sensor +1.0 K": (s.temp + 1.0, s.pres, s.rh),
        "RH sensor +5 %": (s.temp, s.pres, np.clip(s.rh + 5.0, 0, 100)),
        "P sensor +2 hPa": (s.temp, s.pres + 2.0, s.rh),
        "shield fails (+1 K, vapour held)": None,     # computed below
        "RH wets to 100 %": (s.temp, s.pres, np.full(len(s), 100.0)),
    }
    # a failed radiation shield heats the probe at CONSTANT vapour content, so
    # RH must be recomputed rather than held -- this is the one fault whose
    # shape is derived from thermodynamics instead of chosen
    e_keep = np.clip(s.rh, 0.01, None) / 100.0 * es_hpa(s.temp)
    t_hot = s.temp + 1.0
    faults["shield fails (+1 K, vapour held)"] = (
        t_hot, s.pres, np.clip(100.0 * e_keep / es_hpa(t_hot), 0, 100))

    out = {}
    for fname, (ft, fp, frh) in faults.items():
        pert = derive(ft, fp, frh)
        out[fname] = {k: round(float(np.nanmedian(np.abs(pert[k] - base[k]))
                                     / scale[k]), 3) for k in base}
    t2 = pd.DataFrame(out)
    print(t2.to_string())

    print("\n\n=== 3. What this says ===")
    print("Every column is a different FINGERPRINT across the same three")
    print("measurements. That is the multivariate consistency the statement")
    print("asks for -- not a model asked whether a triple looks odd, but a")
    print("physical question: WHICH relation broke?\n")
    print("Note the shield column against the T-sensor column. Both raise")
    print("temperature by the same amount, and a detector watching temperature")
    print("alone cannot separate them. They differ in what they do to the")
    print("conserved quantities, and that difference is what names the fault.")
    print("\nAnd the fact underneath all of it: at one instant these three")
    print("numbers ARE the state, so no instantaneous cross-check exists.")
    print("Redundancy comes only from time, from neighbours, and from the")
    print("deterministic diurnal and annual cycles.")


if __name__ == "__main__":
    main()
