"""Local solar time.

India spans roughly 29 degrees of longitude — solar noon differs by nearly two
hours between Gujarat and Arunachal. Binning diurnal baselines by IST or UTC
smears the cycle across that span and degrades every downstream residual.

Mean solar time is enough: the equation of time swings +/- 16 minutes, which is
well inside an hourly bin, so it is deliberately ignored.
"""
from __future__ import annotations


def mean_solar_hour(utc_hour: float, longitude_deg: float) -> float:
    """Local mean solar hour in [0, 24) from UTC decimal hour and longitude."""
    return (utc_hour + longitude_deg / 15.0) % 24.0


def solar_hour_series(ts, longitude_deg: float):
    """Vectorised form for a pandas DatetimeIndex or Series (UTC)."""
    hours = ts.dt.hour + ts.dt.minute / 60.0 + ts.dt.second / 3600.0
    return (hours + longitude_deg / 15.0) % 24.0


# Approximate station longitudes. VERIFY these against an authoritative source
# before they drive anything — they set every diurnal baseline.
STATION_LONGITUDE = {
    "Dhubri": 89.98,
    "Guwahati": 91.75,
    "Jorhat": 94.22,
    "Silchar": 92.80,
    "Tezpur": 92.79,
    "Mahabaleshwar": 73.66,
    "Mumbai_Colaba": 72.82,
    "Mumbai_Santacruz": 72.85,
    "Pune": 73.86,
    "Ratnagiri": 73.31,
}

# Approximate station latitudes. UNVERIFIED, exactly like the longitudes above.
#
# These position the dots on the console map and nothing else -- no detector
# reads them. That is deliberate: a wrong longitude silently smears a diurnal
# baseline, whereas a wrong latitude here only puts a marker in the wrong place,
# which someone will notice.
#
# The map draws NO national or state boundary. Boundary depiction on Indian maps
# is regulated by Survey of India, this is an MoES/IMD submission, and an
# approximate outline near a disputed frontier is a legal problem rather than a
# cosmetic one. A graticule and a scale bar convey the geography that matters
# here -- which stations are near which -- without asserting a border.
STATION_LATITUDE = {
    "Dhubri": 26.02,
    "Guwahati": 26.14,
    "Jorhat": 26.75,
    "Silchar": 24.82,
    "Tezpur": 26.63,
    "Mahabaleshwar": 17.92,
    "Mumbai_Colaba": 18.90,
    "Mumbai_Santacruz": 19.10,
    "Pune": 18.53,
    "Ratnagiri": 16.99,
}
