"""Thermodynamic relations for T / P / RH.

Deliberately dependency-free — pure arithmetic over floats, no numpy, no pandas.
This module must transliterate to C++ for the ESP32 edge tier, so keep it that way.

Magnus coefficients differ over water and over ice. Using the water set below 0 C
manufactures spurious violations at high-altitude and northern stations, so the
coefficient set is selected by temperature.
"""
from __future__ import annotations
import math

# Magnus / Arden Buck coefficients
_A_WATER, _B_WATER = 17.62, 243.12   # valid roughly -40..+50 C over water
_A_ICE,   _B_ICE   = 22.46, 272.62   # over ice, below 0 C

# Saturation vapour pressure at 0 C, hPa
_ES0 = 6.112


def _magnus_coeffs(t_c: float) -> tuple[float, float]:
    return (_A_ICE, _B_ICE) if t_c < 0.0 else (_A_WATER, _B_WATER)


def saturation_vapour_pressure(t_c: float) -> float:
    """e_s(T) in hPa."""
    a, b = _magnus_coeffs(t_c)
    return _ES0 * math.exp(a * t_c / (b + t_c))


def vapour_pressure(t_c: float, rh_pct: float) -> float:
    """Actual vapour pressure e in hPa."""
    return max(rh_pct, 0.0) / 100.0 * saturation_vapour_pressure(t_c)


def dew_point(t_c: float, rh_pct: float) -> float:
    """Dew point in C, from temperature and relative humidity.

    NOTE: `dew_point(T, RH) <= T` is true if and only if `RH <= 100`. The two are
    the same inequality, not two independent checks. Keep exactly one of them.
    """
    a, b = _magnus_coeffs(t_c)
    rh = min(max(rh_pct, 0.01), 200.0)
    gamma = math.log(rh / 100.0) + (a * t_c) / (b + t_c)
    return (b * gamma) / (a - gamma)


def specific_humidity(t_c: float, rh_pct: float, p_hpa: float) -> float:
    """Specific humidity q in g/kg.

    Requires all three parameters — this is what pressure is for. q is conserved
    under dry adiabatic processes and diurnal heating, whereas RH is not, so a
    sensor fault usually breaks q while genuine advection moves it coherently.
    """
    e = vapour_pressure(t_c, rh_pct)
    return 0.622 * e / (p_hpa - 0.378 * e) * 1000.0


def reduce_to_msl(p_station_hpa: float, elevation_m: float, t_c: float) -> float:
    """Barometric reduction of station pressure to mean sea level.

    Mandatory before comparing pressure between stations: pressure falls roughly
    1 hPa per 8-9 m, so two stations 100 m apart in elevation differ by ~12 hPa
    with zero anomaly. Skipping this makes every hill station look broken.
    """
    return p_station_hpa * math.exp(elevation_m / (29.271 * (t_c + 273.15)))


def rh_from_dew_point(t_c: float, td_c: float) -> float:
    """Inverse of dew_point, for round-trip checks."""
    return 100.0 * saturation_vapour_pressure(td_c) / saturation_vapour_pressure(t_c)
