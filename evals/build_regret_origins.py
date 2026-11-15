"""Starting points for the recommendation eval: one well-known building in each of the 18 districts.

    python evals/build_regret_origins.py      # geocode and write evals/regret_origins.csv

Coordinates come from the government's Address Lookup Service. A match is accepted only if the service
places it in the expected district. One point per district is a coarse picture of where people start
from, and the points are not weighted by population (planned for the v2 care-deserts analysis).
"""

from __future__ import annotations

import csv
from pathlib import Path

import httpx

from aecompass.geo.geocode import geocode

OUT = Path("evals/regret_origins.csv")
LANDMARKS = {
    "Central & Western": "Exchange Square",
    "Wan Chai": "Southorn Centre",
    "Eastern": "Cityplaza",
    "Southern": "Aberdeen Centre",
    "Yau Tsim Mong": "Langham Place",
    "Sham Shui Po": "Sham Shui Po Police Station",
    "Kowloon City": "Kowloon City Municipal Services Building",
    "Wong Tai Sin": "Upper Wong Tai Sin Estate",
    "Kwun Tong": "Kwun Tong Plaza",
    "Tsuen Wan": "Tsuen Wan Town Hall",
    "Tuen Mun": "Tuen Mun Town Hall",
    "Yuen Long": "Yuen Long Theatre",
    "North": "Landmark North",
    "Tai Po": "Tai Po Civic Centre",
    "Sha Tin": "Sha Tin Town Hall",
    "Sai Kung": "Sai Kung Tseung Kwan O Government Complex",
    "Kwai Tsing": "Kwai Tsing Theatre",
    "Islands": "Citygate",
}


def main() -> None:
    rows = []
    with httpx.Client() as client:
        for district, query in LANDMARKS.items():
            matches = [p for p in geocode(query, 5, client) if p.district == district]
            if not matches:
                raise SystemExit(f"No match in {district} for {query!r}; pick another landmark.")
            place = matches[0]
            rows.append([district, query, place.matched_name, place.lat, place.lon])
            print(f"{district}: {place.matched_name} ({place.lat:.5f}, {place.lon:.5f})")
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["district", "query", "matched_name", "lat", "lon"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
