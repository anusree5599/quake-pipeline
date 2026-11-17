"""Small synthetic USGS-style GeoJSON used by the tests (no network needed)."""

DAY_MS = 86_400_000
BASE = 1_731_000_000_000  # an arbitrary UTC timestamp in ms


def feature(fid, mag, place, depth, day=0, etype="earthquake", lat=35.0, lon=-118.0, tsunami=0):
    return {
        "type": "Feature",
        "id": fid,
        "properties": {"mag": mag, "place": place, "time": BASE + day * DAY_MS,
                       "type": etype, "magType": "ml", "sig": 10, "tsunami": tsunami,
                       "alert": None, "url": f"https://example.org/{fid}"},
        "geometry": {"type": "Point", "coordinates": [lon, lat, depth]},
    }


SAMPLE = {
    "type": "FeatureCollection",
    "features": [
        feature("a1", 1.2, "5 km N of Ridgecrest, CA", 8.0, day=0),
        feature("a2", 2.7, "10 km SSW of Volcano, Hawaii", 2.1, day=0, lat=19.4, lon=-155.3),
        feature("a3", 4.6, "Fiji region", 550.0, day=1, lat=-17.8, lon=-178.4),
        feature("a4", 6.1, "120 km E of Hachinohe, Japan", 35.0, day=1, lat=40.5, lon=143.0, tsunami=1),
        feature("a5", 3.3, "20 km W of Anchorage, Alaska", 120.0, day=2, lat=61.2, lon=-150.2),
        feature("a6", 2.0, "3 km E of Ridgecrest, CA", -0.5, day=2),
        feature("a6", 2.0, "3 km E of Ridgecrest, CA", -0.5, day=2),          # duplicate id
        feature("b1", 1.9, "8 km S of Quarryville, PA", 0.0, etype="quarry blast"),
        feature("b2", None, "somewhere", 5.0),                                 # missing magnitude
    ],
}
