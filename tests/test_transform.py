from quake_pipeline.transform import (aggregate, clean_events, depth_class,
                                      magnitude_band, region_from_place)
from tests.fixtures import SAMPLE


def test_region_parsing():
    assert region_from_place("5 km N of Ridgecrest, CA") == "California"
    assert region_from_place("10 km SSW of Volcano, Hawaii") == "Hawaii"
    assert region_from_place("Fiji region") == "Fiji region"
    assert region_from_place(None) == "Unknown"


def test_bands_and_depth():
    assert magnitude_band(1.99) == "< 2.0"
    assert magnitude_band(2.0) == "2.0 – 2.9"
    assert magnitude_band(6.1) == "6.0 +"
    assert depth_class(10) == "Shallow (0–70 km)"
    assert depth_class(70) == "Intermediate (70–300 km)"
    assert depth_class(550) == "Deep (300+ km)"


def test_cleaning_drops_bad_rows():
    rows, quality = clean_events(SAMPLE)
    assert quality["input_features"] == 9
    assert quality["clean_rows"] == 6
    assert quality["dropped_by_reason"] == {
        "duplicate_or_missing_id": 1, "not_an_earthquake": 1, "missing_magnitude": 1}
    assert all(r["depth_km"] >= 0 for r in rows)  # negative depth clamped


def test_aggregation():
    rows, _ = clean_events(SAMPLE)
    s = aggregate(rows)
    assert s["kpis"]["total_events"] == 6
    assert s["kpis"]["max_magnitude"] == 6.1
    assert s["kpis"]["events_m4_plus"] == 2
    assert s["kpis"]["tsunami_flagged"] == 1
    assert s["kpis"]["busiest_region"] == "California"
    assert [d["count"] for d in s["daily"]] == [2, 2, 2]
    assert sum(b["count"] for b in s["magnitude_bands"]) == 6
    assert s["strongest_events"][0]["magnitude"] == 6.1
    assert s["top_regions"][0] == {"region": "California", "count": 2, "avg_magnitude": 1.6,
                                   "max_magnitude": 2.0, "avg_depth_km": 4.0}


def test_empty_input():
    rows, quality = clean_events({"features": []})
    assert rows == [] and quality["clean_rows"] == 0
    assert aggregate(rows)["kpis"]["total_events"] == 0
