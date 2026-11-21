"""Turn a Hong Kong place name or address into coordinates, using the government's Address Lookup Service.

    python -m aecompass.geo.geocode "Tuen Mun Town Hall"

The service matches *buildings*, not areas: "Kennedy Town" resolves to a building with that name in it.
Callers should show the matched name back to the user so a wrong match is visible.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import httpx

URL = "https://www.als.gov.hk/lookup"
HEADERS = {"Accept": "application/json", "Accept-Language": "en"}


@dataclass(frozen=True)
class Place:
    query: str
    matched_name: str
    district: str
    lat: float
    lon: float
    score: float  # the service's own match score, 0 to 100

    @property
    def point(self) -> tuple[float, float]:
        return (self.lat, self.lon)


def _name(address: dict) -> str:
    eng = address.get("EngPremisesAddress", {})
    street = eng.get("EngStreet", {})
    parts = [eng.get("BuildingName"), eng.get("EngEstate", {}).get("EstateName"),
             " ".join(filter(None, [street.get("BuildingNoFrom"), street.get("StreetName")]))]
    return ", ".join(p.title() for p in parts if p) or "(unnamed)"


def parse(query: str, payload: dict) -> list[Place]:
    places = []
    for item in payload.get("SuggestedAddress", []):
        address = item["Address"]["PremisesAddress"]
        geo = address.get("GeospatialInformation") or {}
        if "Latitude" not in geo:
            continue
        district = address.get("EngPremisesAddress", {}).get("EngDistrict", {}).get("DcDistrict", "")
        places.append(Place(query, _name(address), district.title().replace(" District", ""),
                            float(geo["Latitude"]), float(geo["Longitude"]),
                            float(item.get("ValidationInformation", {}).get("Score", 0))))
    return places


def geocode(query: str, n: int = 3, client: httpx.Client | None = None) -> list[Place]:
    """Best matches first. Empty list if nothing was found."""
    get = (client or httpx).get
    for attempt in range(3):  # the service sometimes drops a connection; a second try usually works
        try:
            r = get(URL, params={"q": query, "n": n}, headers=HEADERS, timeout=30, follow_redirects=True)
            break
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    r.raise_for_status()
    return parse(query, r.json())


if __name__ == "__main__":
    for place in geocode(" ".join(sys.argv[1:]) or "Tuen Mun Town Hall"):
        print(f"{place.matched_name} | {place.district} | {place.lat:.5f}, {place.lon:.5f} | score {place.score:.0f}")
