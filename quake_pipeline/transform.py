"""Pure transformation logic for USGS earthquake GeoJSON.

Kept free of ADK, network and storage code so it can be unit-tested on its own.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean

# USGS writes some US locations with a state abbreviation ("5 km N of Ridgecrest, CA").
STATE_ABBREVIATIONS = {
    "CA": "California", "NV": "Nevada", "OR": "Oregon", "WA": "Washington",
    "ID": "Idaho", "MT": "Montana", "WY": "Wyoming", "UT": "Utah",
    "NM": "New Mexico", "AZ": "Arizona", "CO": "Colorado", "TX": "Texas",
    "OK": "Oklahoma", "KS": "Kansas", "AK": "Alaska", "HI": "Hawaii",
    "TN": "Tennessee", "AR": "Arkansas", "MO": "Missouri", "KY": "Kentucky",
    "IL": "Illinois", "IN": "Indiana", "OH": "Ohio", "SC": "South Carolina",
    "NC": "North Carolina", "VA": "Virginia", "NY": "New York", "ME": "Maine",
    "PR": "Puerto Rico", "B.C.": "British Columbia", "MX": "Mexico",
}

MAGNITUDE_BANDS = [
    ("< 2.0", None, 2.0),
    ("2.0 – 2.9", 2.0, 3.0),
    ("3.0 – 3.9", 3.0, 4.0),
    ("4.0 – 4.9", 4.0, 5.0),
    ("5.0 – 5.9", 5.0, 6.0),
    ("6.0 +", 6.0, None),
]

# Standard seismology depth classes (km).
DEPTH_CLASSES = [("Shallow (0–70 km)", 70), ("Intermediate (70–300 km)", 300), ("Deep (300+ km)", None)]


def region_from_place(place: str | None) -> str:
    """'12 km SSW of Volcano, Hawaii' -> 'Hawaii'; 'Fiji region' -> 'Fiji region'."""
    if not place:
        return "Unknown"
    region = place.rsplit(",", 1)[-1].strip() if "," in place else place.strip()
    return STATE_ABBREVIATIONS.get(region, region)


def magnitude_band(mag: float) -> str:
    for label, low, high in MAGNITUDE_BANDS:
        if (low is None or mag >= low) and (high is None or mag < high):
            return label
    return MAGNITUDE_BANDS[-1][0]


def depth_class(depth_km: float) -> str:
    for label, upper in DEPTH_CLASSES:
        if upper is None or depth_km < upper:
            return label
    return DEPTH_CLASSES[-1][0]


def clean_events(geojson: dict) -> tuple[list[dict], dict]:
    """Flatten GeoJSON features into rows and apply data-quality rules.

    Returns (clean_rows, quality_report).
    """
    features = geojson.get("features", [])
    dropped = Counter()
    seen_ids: set[str] = set()
    rows: list[dict] = []

    for f in features:
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        event_id = f.get("id")

        if not event_id or event_id in seen_ids:
            dropped["duplicate_or_missing_id"] += 1
            continue
        if props.get("type") != "earthquake":
            dropped["not_an_earthquake"] += 1  # quarry blasts, explosions, ice quakes...
            continue
        if props.get("mag") is None:
            dropped["missing_magnitude"] += 1
            continue
        if len(coords) < 3 or coords[2] is None:
            dropped["missing_coordinates"] += 1
            continue
        lon, lat, depth = float(coords[0]), float(coords[1]), float(coords[2])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            dropped["invalid_coordinates"] += 1
            continue

        seen_ids.add(event_id)
        mag = round(float(props["mag"]), 2)
        ts = datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc)
        depth = max(depth, 0.0)  # tiny negative depths (above sea level) are clamped to 0
        rows.append({
            "id": event_id,
            "time_utc": ts.isoformat(timespec="seconds"),
            "date": ts.date().isoformat(),
            "magnitude": mag,
            "mag_type": props.get("magType"),
            "place": props.get("place") or "Unknown",
            "region": region_from_place(props.get("place")),
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "depth_km": round(depth, 2),
            "depth_class": depth_class(depth),
            "magnitude_band": magnitude_band(mag),
            "significance": props.get("sig"),
            "tsunami_flag": bool(props.get("tsunami")),
            "alert": props.get("alert"),
            "url": props.get("url"),
        })

    quality = {
        "input_features": len(features),
        "clean_rows": len(rows),
        "dropped_total": sum(dropped.values()),
        "dropped_by_reason": dict(dropped),
    }
    return rows, quality


def aggregate(rows: list[dict], top_n: int = 10) -> dict:
    """Group and aggregate cleaned rows into the datasets the report needs."""
    if not rows:
        return {"kpis": {"total_events": 0}, "daily": [], "magnitude_bands": [],
                "depth_classes": [], "top_regions": [], "strongest_events": [], "map_points": []}

    mags = [r["magnitude"] for r in rows]

    by_day: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r["magnitude"])
    daily = [
        {"date": d, "count": len(m), "avg_magnitude": round(mean(m), 2), "max_magnitude": max(m)}
        for d, m in sorted(by_day.items())
    ]

    band_counts = Counter(r["magnitude_band"] for r in rows)
    magnitude_bands = [{"band": b, "count": band_counts.get(b, 0)} for b, _, _ in MAGNITUDE_BANDS]

    depth_counts = Counter(r["depth_class"] for r in rows)
    depth_classes = [
        {"class": c, "count": depth_counts.get(c, 0),
         "share_pct": round(100 * depth_counts.get(c, 0) / len(rows), 1)}
        for c, _ in DEPTH_CLASSES
    ]

    by_region: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_region[r["region"]].append(r)
    regions = [
        {"region": name, "count": len(evts),
         "avg_magnitude": round(mean(e["magnitude"] for e in evts), 2),
         "max_magnitude": max(e["magnitude"] for e in evts),
         "avg_depth_km": round(mean(e["depth_km"] for e in evts), 1)}
        for name, evts in by_region.items()
    ]
    regions.sort(key=lambda x: (-x["count"], -x["max_magnitude"]))

    strongest = sorted(rows, key=lambda r: (-r["magnitude"], r["time_utc"]))[:top_n]
    strongest_events = [
        {k: r[k] for k in ("time_utc", "magnitude", "place", "depth_km", "tsunami_flag", "url")}
        for r in strongest
    ]

    # Map shows the 1,500 strongest events so the page stays light.
    map_points = [
        [r["latitude"], r["longitude"], r["magnitude"], r["place"]]
        for r in sorted(rows, key=lambda r: -r["magnitude"])[:1500]
    ]

    kpis = {
        "total_events": len(rows),
        "days_covered": len(daily),
        "first_event_utc": min(r["time_utc"] for r in rows),
        "last_event_utc": max(r["time_utc"] for r in rows),
        "average_magnitude": round(mean(mags), 2),
        "max_magnitude": max(mags),
        "events_m4_plus": sum(1 for m in mags if m >= 4.0),
        "tsunami_flagged": sum(1 for r in rows if r["tsunami_flag"]),
        "regions": len(by_region),
        "busiest_region": regions[0]["region"],
    }

    return {
        "kpis": kpis,
        "daily": daily,
        "magnitude_bands": magnitude_bands,
        "depth_classes": depth_classes,
        "top_regions": regions[:top_n],
        "strongest_events": strongest_events,
        "map_points": map_points,
    }
