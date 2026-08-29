"""Synthesise the Indian AWS network at the cadence the problem statement asks for.

    python -m simulate.network --days 30

WHY SYNTHETIC, WHEN REAL INDIAN DATA IS ALREADY ON THE MAP

WDQMS gives real stations and a real quality signal, and it gives them three
days deep at six-hourly. That is enough to colour a map once and nothing more:
there is no moving through time, no diurnal cycle, no drift developing over
weeks, and no control over where a fault sits. A demonstration of a monitoring
system needs to be able to run.

So the GEOGRAPHY stays real -- every station here is an actual IMD mast with its
real name, coordinates and state, taken from WMO's list -- and the READINGS are
generated. Nothing in the interface may present these as measurements.

CADENCE, AND WHY 15 MINUTES

IMD's own specification: "minimum data reception frequency is once every 15 mins
for AWS and ARG, with latency 10 mins". The 2018 GPRS server supports one-minute
intervals but does not require them. And this project has already measured what
finer sampling buys: evaluation/run_cadence.py found a 24-fold change of cadence
(15 min to 6 h) moves the neighbour-difference sigma from 0.875 to 0.921 K and
drift latency from 131 to 138 days. One-minute data would be fifteen times the
volume for a few percent, so 15 minutes it is -- the requirement, and enough to
exercise the edge tier honestly. The map export decimates to hourly, because a
map cannot carry 2,880 steps per station and does not need to.

WHAT IS MODELLED, AND WHAT IS NOT

Modelled, because the detector depends on all of it:
  - a diurnal temperature cycle in LOCAL SOLAR time, which is why longitude
    matters and why a single UTC clock would put noon in the wrong place across
    a country 29 degrees wide;
  - an annual cycle, latitude-dependent, so the north swings harder than the
    south;
  - synoptic weather as an AR(1) field SHARED between nearby stations, which is
    the whole point -- neighbour differencing only means something if genuine
    weather moves neighbours together while a fault moves one station alone;
  - the semidiurnal pressure tide S2, the atmosphere's most reliable clock;
  - elevation, through the barometric formula, so pressure is a station value
    rather than a sea-level one.

NOT modelled: real orography. Elevation comes from a crude analytic field with
a Himalayan wall, the Western Ghats and the Deccan plateau in roughly the right
places. It is wrong in detail and it is honest about that. Nothing downstream
depends on it: every feature the detector uses is relative to a station's own
history, so an elevation error moves the displayed pressure and nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATIONS_IN = Path("dashboard/wdqms.json")
OUT_DIR = Path("data/sim")

STEP_MIN = 15


def elevation_field(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """A crude analytic orography, in metres. See the module docstring: this is
    approximately right for the big features and wrong in detail, on purpose."""
    e = np.zeros_like(lat)
    # Himalayan wall: rises hard north of about 28 N.
    e += 4200.0 / (1.0 + np.exp(-(lat - 30.5) * 1.9))
    # Western Ghats: a narrow ridge inland of the west coast.
    e += 900.0 * np.exp(-(((lon - 74.6) / 1.1) ** 2) - (((lat - 15.5) / 6.5) ** 2))
    # Deccan plateau.
    e += 520.0 * np.exp(-(((lon - 77.5) / 4.5) ** 2) - (((lat - 17.5) / 4.0) ** 2))
    # Chota Nagpur / central highlands.
    e += 300.0 * np.exp(-(((lon - 84.0) / 4.0) ** 2) - (((lat - 23.0) / 3.0) ** 2))
    return np.maximum(e, 2.0)


def ar1_field(n_steps: int, n_st: int, lat, lon, rng, *,
              corr_km: float, tau_steps: float, sigma: float) -> np.ndarray:
    """Weather: red noise in time, spatially correlated between stations.

    THIS IS THE PART THAT MAKES THE DEMONSTRATION MEAN ANYTHING. If every
    station got independent noise, neighbour differencing would look
    miraculous -- any excursion at one mast would stand out against neighbours
    that never move together. Real weather moves a whole region at once, and it
    is only against that shared movement that a single drifting instrument is
    hard to find. So the field is built from a handful of smooth spatial modes
    with an AR(1) coefficient in time.
    """
    # Distance matrix, kilometres, small enough at 346 stations to build whole.
    la = np.radians(lat)[:, None]
    lo = np.radians(lon)[:, None]
    dlat = la - la.T
    dlon = lo - lo.T
    h = np.sin(dlat / 2) ** 2 + np.cos(la) * np.cos(la.T) * np.sin(dlon / 2) ** 2
    d_km = 2 * 6371.0 * np.arcsin(np.clip(np.sqrt(h), 0, 1))

    cov = np.exp(-(d_km / corr_km) ** 2)
    # Eigen-decomposition rather than Cholesky: the covariance is only positive
    # semi-definite once stations sit almost on top of each other.
    w, v = np.linalg.eigh(cov)
    w = np.clip(w, 0, None)
    root = v * np.sqrt(w)

    a = float(np.exp(-1.0 / tau_steps))
    innov = np.sqrt(1.0 - a * a)
    out = np.empty((n_steps, n_st), dtype=np.float32)
    state = (root @ rng.standard_normal(n_st)).astype(np.float32)
    for t in range(n_steps):
        state = a * state + innov * (root @ rng.standard_normal(n_st)).astype(np.float32)
        out[t] = state
    return out * sigma


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--end", default="2026-08-24")
    ap.add_argument("--seed", type=int, default=20260824)
    args = ap.parse_args()

    if not STATIONS_IN.exists():
        raise SystemExit(f"missing {STATIONS_IN}; run dashboard.export_wdqms first")
    src = json.loads(STATIONS_IN.read_text(encoding="utf-8"))
    st = [s for s in src["stations"] if s["in_india"]]
    n_st = len(st)

    lat = np.array([s["latitude"] for s in st], dtype=np.float64)
    lon = np.array([s["longitude"] for s in st], dtype=np.float64)
    elev = elevation_field(lat, lon)

    n_steps = args.days * 24 * (60 // STEP_MIN)
    end = np.datetime64(args.end + "T00:00")
    start = end - np.timedelta64(n_steps * STEP_MIN, "m")
    t_utc = start + np.arange(n_steps) * np.timedelta64(STEP_MIN, "m")

    rng = np.random.default_rng(args.seed)

    # Local solar time, so noon happens when the sun is overhead rather than
    # when a clock in Delhi says so. 29 degrees of longitude is nearly two
    # hours; using UTC would smear the diurnal cycle across the country.
    hours_utc = ((t_utc - t_utc.astype("datetime64[D]")).astype("timedelta64[m]")
                 .astype(np.float64) / 60.0)[:, None]
    solar = (hours_utc + lon[None, :] / 15.0) % 24.0
    doy = (t_utc.astype("datetime64[D]") - t_utc.astype("datetime64[Y]")
           ).astype(int)[:, None].astype(np.float64)

    # --- temperature -------------------------------------------------------
    # Annual mean falls with latitude and with height; the annual SWING grows
    # with latitude, which is why Srinagar has a winter and Kochi does not.
    mean_t = 30.5 - 0.30 * (lat - 8.0) - 0.0062 * elev
    swing = 2.0 + 0.42 * (lat - 8.0)
    diurnal = 4.0 + 3.2 * np.exp(-((lat - 26.0) / 12.0) ** 2)

    annual = -np.cos(2 * np.pi * (doy - 15.0) / 365.25) * swing[None, :]
    daily = -np.cos(2 * np.pi * (solar - 15.2) / 24.0) * diurnal[None, :]
    t_weather = ar1_field(n_steps, n_st, lat, lon, rng,
                          corr_km=520.0, tau_steps=2.5 * 96, sigma=2.4)
    temp = (mean_t[None, :] + annual + daily + t_weather).astype(np.float32)

    # --- pressure ----------------------------------------------------------
    # Station pressure by the barometric formula, plus synoptic systems, plus
    # the semidiurnal tide S2 -- about 1.2 hPa near the tropics, peaking near
    # 10 and 22 local solar time. It is the most repeatable signal in the
    # record and this project uses it as a per-station clock.
    p0 = 1013.25 * np.exp(-elev / 8434.0)
    p_weather = ar1_field(n_steps, n_st, lat, lon, rng,
                          corr_km=780.0, tau_steps=3.5 * 96, sigma=2.9)
    s2_amp = 1.25 * np.cos(np.radians(lat)) ** 3
    s2 = s2_amp[None, :] * np.cos(2 * np.pi * (solar - 9.7) / 12.0)
    pres = (p0[None, :] + p_weather + s2).astype(np.float32)

    # --- humidity ----------------------------------------------------------
    # Dew point is generated, and RH derived from it, rather than the other way
    # round. RH is a ratio and is not conserved: simulating it directly gives a
    # humidity that swings independently of temperature, which no real screen
    # ever does. A dew point that moves slowly with the airmass, with RH falling
    # as the afternoon warms, is what an instrument actually sees.
    td_base = 22.0 - 0.16 * (lat - 8.0) - 0.0035 * elev
    td_weather = ar1_field(n_steps, n_st, lat, lon, rng,
                           corr_km=430.0, tau_steps=2.0 * 96, sigma=2.2)
    td = (td_base[None, :] + 0.45 * annual + td_weather).astype(np.float32)
    td = np.minimum(td, temp - 0.15)

    a_w, b_w = 17.62, 243.12
    es = 6.112 * np.exp(a_w * temp / (b_w + temp))
    e = 6.112 * np.exp(a_w * td / (b_w + td))
    rh = np.clip(100.0 * e / es, 1.0, 100.0).astype(np.float32)

    # instrument noise, independent per station -- this is the only term that
    # does NOT move neighbours together, which is what makes it noise
    temp += rng.normal(0, 0.11, temp.shape).astype(np.float32)
    pres += rng.normal(0, 0.09, pres.shape).astype(np.float32)
    rh += rng.normal(0, 0.9, rh.shape).astype(np.float32)
    rh = np.clip(rh, 0.5, 100.0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT_DIR / "network_15min.npz",
        temp=temp, rh=rh, pres=pres,
        lat=lat, lon=lon, elev=elev,
        t0=str(start), step_min=STEP_MIN, n_steps=n_steps,
        ids=np.array([s["id"] for s in st], dtype=object),
        names=np.array([s["name"] for s in st], dtype=object),
        states=np.array([s["region"] for s in st], dtype=object),
    )

    f = OUT_DIR / "network_15min.npz"
    print(f"{f}  {f.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  {n_st} stations x {n_steps} steps at {STEP_MIN} min "
          f"= {n_st * n_steps:,} observations")
    print(f"  {start} to {t_utc[-1]}")
    print(f"  temp  {temp.min():6.1f} to {temp.max():6.1f} C   "
          f"mean {temp.mean():.1f}")
    print(f"  pres  {pres.min():6.1f} to {pres.max():6.1f} hPa  "
          f"mean {pres.mean():.1f}")
    print(f"  rh    {rh.min():6.1f} to {rh.max():6.1f} %    "
          f"mean {rh.mean():.1f}")
    print(f"  elevation {elev.min():.0f} to {elev.max():.0f} m")

    # Does the weather actually move neighbours together? If it does not, the
    # whole demonstration is rigged in the detector's favour.
    d = temp[:, :, None] if False else None
    del d
    i, j = 0, int(np.argmin(np.abs(lat - lat[0]) + np.abs(lon - lon[0]) + 1e6 * (np.arange(n_st) == 0)))
    print(f"  nearest-pair temperature correlation "
          f"({st[i]['name']} vs {st[j]['name']}): "
          f"{np.corrcoef(temp[:, i], temp[:, j])[0, 1]:.3f}")
    far = int(np.argmax(np.abs(lat - lat[0]) + np.abs(lon - lon[0])))
    print(f"  far-pair correlation ({st[i]['name']} vs {st[far]['name']}): "
          f"{np.corrcoef(temp[:, i], temp[:, far])[0, 1]:.3f}")


if __name__ == "__main__":
    main()
