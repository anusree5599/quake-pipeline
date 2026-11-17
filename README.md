# Agentic earthquake data pipeline (Google ADK)

This project pulls recent earthquake data from the USGS public API, cleans and aggregates it, builds an HTML report with charts, a map and tables, and uploads the raw data, processed data and report to cloud object storage (Google Cloud Storage or AWS S3). Four Google ADK agents run the steps in order.

## How it works

```
User request ("big quakes from the last 2 weeks")
        |
        v
SequentialAgent: earthquake_pipeline
  1. ingestion_agent   --tool-->  fetch_earthquakes        USGS API -> raw GeoJSON
  2. processing_agent  --tool-->  process_earthquakes      clean, group, aggregate
  3. reporting_agent   --tool-->  build_html_report        HTML page (Chart.js + Leaflet)
  4. storage_agent     --tool-->  upload_to_cloud_storage  raw/processed/report -> GCS or S3
```

The `SequentialAgent` fixes the order. Each stage is a Gemini-backed `LlmAgent` with one tool:

- The ingestion agent reads the request and picks the arguments (look-back window of 1 to 30 days, minimum magnitude). "Significant quakes this month" becomes `days=30, min_magnitude=4.5`. With no details it uses 7 days and M2.5+.
- The processing agent runs the transformation, reads the data-quality numbers that come back, and flags a warning if more than 20% of rows were dropped.
- The reporting agent builds the web page.
- The storage agent uploads everything and writes the final run summary.

Agents hand work to each other through ADK session state (`tool_context.state`). The tools write files to `output/<run_id>/` and put the file paths in state, so large datasets never go through the LLM. If a tool fails, it returns `status: "error"` with a message. The agent reports it, and later stages see the missing state and stop cleanly instead of crashing.

### Processing logic (`quake_pipeline/transform.py`)

Cleaning:
- drops duplicate event IDs
- drops events that aren't earthquakes (quarry blasts, explosions, ice quakes)
- drops rows with no magnitude or invalid coordinates
- clamps small negative depths (events above sea level) to 0
- writes every drop reason and count to a data-quality report

Derived fields: UTC date, region (parsed from the USGS `place` string, so "5 km N of Ridgecrest, CA" becomes "California"), magnitude band, and depth class (shallow 0-70 km, intermediate 70-300 km, deep 300+ km).

Aggregations: daily count, average and max magnitude; counts per magnitude band; counts and share per depth class; top 10 regions by event count with average/max magnitude and average depth; the 10 strongest events; and headline numbers (total, strongest, average, M4+ count, tsunami-flagged count, busiest region).

### Storage layout

Objects are written with a Hive-style `run=` partition so runs never overwrite each other:

```
earthquakes/raw/run=20261117T060000Z/earthquakes_raw.geojson
earthquakes/processed/run=20261117T060000Z/earthquakes_clean.csv
earthquakes/processed/run=20261117T060000Z/summary.json
earthquakes/processed/run=20261117T060000Z/quality_report.json
earthquakes/report/run=20261117T060000Z/index.html
```

## Setup

Requires Python 3.10+.

```bash
git clone <this-repo-url>
cd quake-pipeline
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env
```

### 1. Gemini API key

The agents use Gemini. Get a free key at https://aistudio.google.com/apikey and put it in `.env` as `GOOGLE_API_KEY`. The model defaults to `gemini-2.5-flash`. Change `GEMINI_MODEL` if you want a different one.

### 2. Cloud storage (pick one)

Google Cloud Storage:
```bash
gcloud auth application-default login
gcloud storage buckets create gs://YOUR-BUCKET-NAME --location=us-central1
```
Then set `STORAGE_BACKEND=gcs` and `GCS_BUCKET=YOUR-BUCKET-NAME` in `.env`.

AWS S3:
```bash
aws configure
aws s3 mb s3://YOUR-BUCKET-NAME
```
Then set `STORAGE_BACKEND=s3`, `S3_BUCKET=YOUR-BUCKET-NAME` and `AWS_REGION` in `.env`.

No cloud account handy? `STORAGE_BACKEND=local` copies the files into `output/bucket/` with the same layout, so the rest of the pipeline can still be checked. That mode is for testing only.

Credentials come from each SDK's normal credential chain (gcloud ADC, `~/.aws/credentials`). Nothing secret lives in this repo, and `.env` is git-ignored.

## Running it

```bash
python run_pipeline.py
python run_pipeline.py "Show me significant earthquakes from the last 14 days"
```

The console shows each agent's tool calls and messages. The report is written to `output/report.html` (open it in a browser) and to `output/<run_id>/report/index.html`, and the cloud URIs are printed at the end.

You can also use ADK's own tools from the repo root:

```bash
adk run quake_pipeline     # chat with the pipeline in the terminal
adk web                    # browser dev UI; choose "quake_pipeline" and inspect each event and state change
```

## Tests

```bash
pytest
```

`tests/test_transform.py` checks the cleaning and aggregation rules on a small fixture. `tests/test_pipeline_offline.py` runs the real four-agent ADK graph end to end with no network or keys: a scripted model stands in for Gemini, the USGS call is mocked, and storage uses the local backend. It confirms the tools, state hand-offs, report and uploads all connect.

## Project structure

```
quake_pipeline/
  agent.py       ADK agents (root_agent = SequentialAgent of 4 LlmAgents)
  tools.py       the four tool functions the agents call
  transform.py   cleaning and aggregation (pure Python, unit-tested)
  report.py      HTML report template and renderer
  storage.py     GCS, S3 and local backends
run_pipeline.py  command-line runner
tests/           unit and offline end-to-end tests
```

## Notes

- Data source: USGS FDSN event web service, `https://earthquake.usgs.gov/fdsnws/event/1/query`. It's public and needs no key. One request returns at most 20,000 events, which covers 30 days at M2.5+ easily. Asking for very small magnitudes over a long window can hit that cap.
- On ADK 2.x you'll see a deprecation warning saying `SequentialAgent` will be replaced by `Workflow`. It still works. Moving to `Workflow` is listed in the future improvements document.
