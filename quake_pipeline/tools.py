"""ADK function tools. Each agent in the pipeline owns one of these.

Large data never passes through the LLM. Tools write files to ./output/<run_id>/
and share only file paths and small summaries through ADK session state
(tool_context.state), which is how the agents hand work to each other.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from google.adk.tools import ToolContext

from .report import render_report
from .storage import get_backend
from .transform import aggregate, clean_events

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
OUTPUT_ROOT = Path("output")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _get_with_retry(url: str, params: dict, attempts: int = 3) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 ** attempt)  # 2s, 4s backoff
    raise RuntimeError(f"USGS API request failed after {attempts} attempts: {last_error}")


# ---------------------------------------------------------------- 1. ingest
def fetch_earthquakes(days: int, min_magnitude: float, tool_context: ToolContext) -> dict:
    """Downloads earthquake events from the USGS public API and saves the raw GeoJSON.

    Args:
        days: How many days back from now to fetch. Must be between 1 and 30.
        min_magnitude: Smallest magnitude to include, between 0 and 9 (e.g. 2.5).

    Returns:
        A dict with status, run_id, number of features downloaded and the raw file path.
    """
    if not 1 <= int(days) <= 30:
        return {"status": "error", "message": "days must be between 1 and 30"}
    if not 0 <= float(min_magnitude) <= 9:
        return {"status": "error", "message": "min_magnitude must be between 0 and 9"}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(days))
    query = {
        "format": "geojson",
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": float(min_magnitude),
        "orderby": "time",
        "limit": 20000,  # USGS maximum per request
    }
    try:
        geojson = _get_with_retry(USGS_QUERY_URL, query).json()
    except Exception as exc:  # noqa: BLE001 - surface the reason to the agent
        return {"status": "error", "message": str(exc)}

    run_id = end.strftime("%Y%m%dT%H%M%SZ")
    raw_path = OUTPUT_ROOT / run_id / "raw" / "earthquakes_raw.geojson"
    _write_json(raw_path, geojson)

    params = {"days": int(days), "min_magnitude": float(min_magnitude)}
    tool_context.state["run_id"] = run_id
    tool_context.state["params"] = params
    tool_context.state["raw_path"] = str(raw_path)

    return {
        "status": "success",
        "run_id": run_id,
        "features_downloaded": len(geojson.get("features", [])),
        "raw_path": str(raw_path),
        "params": params,
    }


# --------------------------------------------------------------- 2. process
def process_earthquakes(tool_context: ToolContext) -> dict:
    """Cleans the raw earthquake data and aggregates it (by day, magnitude band,
    depth class and region). Uses the raw file saved by the ingestion step.

    Returns:
        A dict with status, headline KPIs and the data-quality report.
    """
    raw_path = tool_context.state.get("raw_path")
    if not raw_path or not Path(raw_path).exists():
        return {"status": "error", "message": "No raw data found. The ingestion step must run first."}

    geojson = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    rows, quality = clean_events(geojson)
    if not rows:
        return {"status": "error", "message": "No valid earthquake rows after cleaning.", "quality": quality}

    summary = aggregate(rows)
    run_dir = OUTPUT_ROOT / tool_context.state["run_id"] / "processed"
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = run_dir / "earthquakes_clean.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary_path = run_dir / "summary.json"
    quality_path = run_dir / "quality_report.json"
    _write_json(summary_path, summary)
    _write_json(quality_path, quality)

    tool_context.state["processed_paths"] = [str(csv_path), str(summary_path), str(quality_path)]
    tool_context.state["summary_path"] = str(summary_path)
    tool_context.state["quality_path"] = str(quality_path)

    return {
        "status": "success",
        "kpis": summary["kpis"],
        "top_regions": [r["region"] for r in summary["top_regions"][:5]],
        "quality": quality,
    }


# ------------------------------------------------------------- 3. visualize
def build_html_report(tool_context: ToolContext) -> dict:
    """Builds the HTML web page (charts, map and tables) from the processed summary.

    Returns:
        A dict with status and the local path of the generated report.
    """
    summary_path = tool_context.state.get("summary_path")
    if not summary_path or not Path(summary_path).exists():
        return {"status": "error", "message": "No processed summary found. The processing step must run first."}

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    quality = json.loads(Path(tool_context.state["quality_path"]).read_text(encoding="utf-8"))
    run_id = tool_context.state["run_id"]
    page = render_report(summary, quality, tool_context.state.get("params", {}), run_id)

    report_path = OUTPUT_ROOT / run_id / "report" / "index.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(page, encoding="utf-8")
    # Convenience copy so the latest report is always at output/report.html
    (OUTPUT_ROOT / "report.html").write_text(page, encoding="utf-8")

    tool_context.state["report_path"] = str(report_path)
    return {"status": "success", "report_path": str(report_path), "latest_copy": str(OUTPUT_ROOT / "report.html")}


# --------------------------------------------------------------- 4. store
def upload_to_cloud_storage(tool_context: ToolContext) -> dict:
    """Uploads the raw data, processed data and HTML report for this run to cloud
    object storage (GCS or S3, chosen by the STORAGE_BACKEND environment variable).

    Returns:
        A dict with status, backend name and the URI of every uploaded object.
    """
    run_id = tool_context.state.get("run_id")
    if not run_id:
        return {"status": "error", "message": "Nothing to upload. The ingestion step must run first."}

    files = {"raw": [tool_context.state.get("raw_path")],
             "processed": tool_context.state.get("processed_paths", []),
             "report": [tool_context.state.get("report_path")]}
    try:
        backend = get_backend()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    uploaded, failed = [], []
    for layer, paths in files.items():
        for p in filter(None, paths):
            key = f"earthquakes/{layer}/run={run_id}/{Path(p).name}"
            try:
                uploaded.append(backend.upload(p, key))
            except Exception as exc:  # noqa: BLE001
                failed.append({"file": p, "error": str(exc)})

    tool_context.state["uploaded_uris"] = uploaded
    status = "success" if uploaded and not failed else ("partial" if uploaded else "error")
    return {"status": status, "backend": backend.name, "uploaded": uploaded, "failed": failed}
