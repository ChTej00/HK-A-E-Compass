import numpy as np
import pytest

from aecompass.geo.geocode import parse
from aecompass.recommend.engine import Forecast, about_as_good, recommend, wait_at_arrival
from aecompass.travel.estimate import DistanceTravelTime, Params, TravelEstimate, region_of

HOSPITALS = {
    "Queen Mary Hospital": (22.2704, 114.13117),
    "Queen Elizabeth Hospital": (22.30886, 114.17519),
    "North Lantau Hospital": (22.282571, 113.93914),
    "St John Hospital": (22.208059, 114.03151),
}


def test_wait_at_arrival_hits_the_known_points_and_interpolates_between():
    pred, lo, hi = (100.0, 160.0, 130.0), (80.0, 120.0, 90.0), (130.0, 220.0, 190.0)
    assert wait_at_arrival(0, 60, pred, lo, hi) == (60, 60, 60)  # now: the published value, no band
    assert wait_at_arrival(60, 60, pred, lo, hi) == (100, 80, 130)
    assert wait_at_arrival(120, 60, pred, lo, hi) == (160, 120, 220)
    assert wait_at_arrival(500, 60, pred, lo, hi) == (130, 90, 190)  # beyond 3h: use +3h
    point, low, high = wait_at_arrival(90, 60, pred, lo, hi)
    assert (point, low, high) == (130, 100, 175)
    point, low, high = wait_at_arrival(15, 60, pred, lo, hi)
    assert point == 70 and low == pytest.approx(70 - 20 * 0.5) and high == pytest.approx(70 + 30 * 0.5)  # sqrt(15/60) = 0.5


def test_wait_at_arrival_works_on_arrays_and_never_goes_negative():
    travel = np.array([[10.0, 70.0], [0.0, 200.0]])
    now = np.full((2, 2), 30.0)
    pred = np.full((2, 2, 3), 20.0)
    point, low, high = wait_at_arrival(travel, now, pred, pred - 50, pred + 50)
    assert point.shape == (2, 2) and (low >= 0).all() and (high >= point).all()
    assert low[1, 0] == high[1, 0] == 30


def test_region_boxes_and_water_crossings():
    assert region_of((22.2835, 114.158)) == "hk_island"  # Central
    assert region_of((22.3188, 114.168)) == "kowloon_nt"  # Mong Kok
    assert region_of((22.2896, 113.940)) == "lantau"  # Tung Chung
    assert region_of((22.2086, 114.028)) == "cheung_chau"
    travel = DistanceTravelTime(HOSPITALS, Params())
    central = (22.2835, 114.158)
    same_side = travel.estimate(central, "Queen Mary Hospital")
    across = travel.estimate(central, "Queen Elizabeth Hospital")
    assert same_side.low < same_side.minutes < same_side.high
    no_penalty = DistanceTravelTime(HOSPITALS, Params(harbour_min=0)).estimate(central, "Queen Elizabeth Hospital")
    assert across.minutes - no_penalty.minutes == pytest.approx(10)
    assert DistanceTravelTime(HOSPITALS, Params(scale=2)).estimate(central, "Queen Mary Hospital").minutes == pytest.approx(2 * same_side.minutes)
    # ferry-only trips are not offered, in either direction
    cheung_chau = (22.2086, 114.028)
    assert travel.estimate(central, "St John Hospital") is None
    assert set(travel.to_all(central)) == set(HOSPITALS) - {"St John Hospital"}
    assert set(travel.to_all(cheung_chau)) == {"St John Hospital"}


def test_recommend_ranks_by_travel_plus_wait_on_arrival():
    flat = lambda v: Forecast(v, (v, v, v), (v - 20, v - 30, v - 40), (v + 20, v + 30, v + 40))
    forecasts = {"Near but slow": flat(240.0), "Far but quick": flat(60.0), "Rising": Forecast(60.0, (200.0,) * 3, (150.0,) * 3, (250.0,) * 3),
                 "No travel estimate": flat(10.0), "No data": flat(float("nan"))}
    trip = lambda m: TravelEstimate(m, m * 0.75, m * 1.25, "test")
    travel = {"Near but slow": trip(10), "Far but quick": trip(60), "Rising": trip(60), "No data": trip(5)}
    options = recommend(forecasts, travel)
    assert [o.hospital for o in options] == ["Far but quick", "Near but slow", "Rising"]
    best = options[0]
    assert best.total_min == 120 and best.total_low == 45 + 40 and best.total_high == 75 + 80
    assert options[2].wait_min == 200  # the forecast at arrival, not the wait now
    assert [o.hospital for o in about_as_good(options)] == ["Far but quick"]
    assert about_as_good([]) == []


def test_geocode_parse_reads_the_service_response():
    payload = {"SuggestedAddress": [
        {"Address": {"PremisesAddress": {
            "EngPremisesAddress": {"BuildingName": "TUEN MUN TOWN HALL", "EngDistrict": {"DcDistrict": "TUEN MUN DISTRICT"},
                                   "EngStreet": {"StreetName": "TUEN HI ROAD", "BuildingNoFrom": "3"}},
            "GeospatialInformation": {"Latitude": "22.39181", "Longitude": "113.97714"}}},
         "ValidationInformation": {"Score": 70.0}},
        {"Address": {"PremisesAddress": {"EngPremisesAddress": {}}}},  # no coordinates: skipped
    ]}
    places = parse("Tuen Mun Town Hall", payload)
    assert len(places) == 1
    assert places[0].matched_name == "Tuen Mun Town Hall, 3 Tuen Hi Road" and places[0].district == "Tuen Mun"
    assert places[0].point == (22.39181, 113.97714)
