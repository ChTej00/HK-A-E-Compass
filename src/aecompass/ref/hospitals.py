"""Coordinates of the 18 public A&E hospitals, from the government's CSDI portal (Health Bureau dataset).

    python -m aecompass.ref.hospitals     # download and cache to data/ref/hospitals.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx

URL = "https://portal.csdi.gov.hk/server/rest/services/common/fhb_rcd_1636947932221_94410/FeatureServer/0/query"
QUERY = {"where": "1=1", "outFields": "hospName_EN,hospName_TC,LATITUDE,LONGITUDE", "outSR": "4326", "f": "json"}
CACHE = Path("data/ref/hospitals.json")


def _key(name: str) -> str:
    """The wait-time feed says 'St John Hospital', this dataset says 'St. John Hospital'."""
    return name.replace(".", "").strip()


def fetch(cache: Path = CACHE) -> Path:
    r = httpx.get(URL, params=QUERY, timeout=60, follow_redirects=True)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(r.content)
    return cache


def load(cache: Path = CACHE) -> dict[str, tuple[float, float]]:
    """{hospital name as used in the wait-time feed: (latitude, longitude)}."""
    if not cache.exists():
        fetch(cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    return {
        _key(f["attributes"]["hospName_EN"]): (float(f["attributes"]["LATITUDE"]), float(f["attributes"]["LONGITUDE"]))
        for f in data["features"]
    }


def chinese_names(cache: Path = CACHE) -> dict[str, str]:
    """{hospital name as used in the wait-time feed: official Traditional Chinese name}, from the same dataset."""
    if not cache.exists():
        fetch(cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    return {_key(f["attributes"]["hospName_EN"]): f["attributes"]["hospName_TC"].strip() for f in data["features"]}


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line (great-circle) distance between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest(coords: dict[str, tuple[float, float]], k: int = 3) -> dict[str, list[str]]:
    """For each hospital, its k closest other hospitals by straight-line distance, closest first."""
    return {
        name: sorted((other for other in coords if other != name), key=lambda o: distance_km(here, coords[o]))[:k]
        for name, here in coords.items()
    }


if __name__ == "__main__":
    fetch()
    for name, others in nearest(load()).items():
        print(f"{name}: {', '.join(others)}")
