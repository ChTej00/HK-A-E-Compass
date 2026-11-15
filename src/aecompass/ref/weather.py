"""Hourly weather for Hong Kong from Open-Meteo's historical archive.

    python -m aecompass.ref.weather       # download and cache to data/ref/weather_hourly.parquet

One point (Kowloon, near the Observatory) stands in for the whole city. Open-Meteo's archive is a
reanalysis: a weather model's reconstruction of the past, not a station reading. See DECISIONS.md D5.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE = Path("data/ref/weather_hourly.parquet")
LAT, LON = 22.30, 114.17
VARIABLES = {"temperature_2m": "temp_c", "precipitation": "rain_mm", "relative_humidity_2m": "humidity_pct"}
TZ = "Asia/Hong_Kong"


def fetch(start: date = date(2025, 10, 1), end: date | None = None, cache: Path = CACHE) -> pd.DataFrame:
    end = end or date.today() - timedelta(days=2)  # the archive rejects very recent dates
    r = httpx.get(
        URL,
        params={
            "latitude": LAT, "longitude": LON,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "hourly": ",".join(VARIABLES), "timezone": TZ,
        },
        timeout=60,
    )
    r.raise_for_status()
    hourly = r.json()["hourly"]
    df = pd.DataFrame(hourly).rename(columns=VARIABLES)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(TZ)
    df = df.set_index("time").dropna(how="all")
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def load(cache: Path = CACHE) -> pd.DataFrame:
    """Hourly table indexed by Hong Kong time, columns temp_c, rain_mm, humidity_pct."""
    return pd.read_parquet(cache) if cache.exists() else fetch(cache=cache)


if __name__ == "__main__":
    df = fetch()
    print(f"{len(df):,} hours, {df.index.min()} to {df.index.max()}")
    print(df.describe().loc[["min", "mean", "max"]].round(1))
