"""Agent definitions for the earthquake data pipeline (Google ADK).

Architecture
------------
root_agent  (SequentialAgent "earthquake_pipeline")
  1. ingestion_agent   -> fetch_earthquakes         (USGS API -> raw GeoJSON)
  2. processing_agent  -> process_earthquakes       (clean, group, aggregate)
  3. reporting_agent   -> build_html_report         (HTML charts, map, tables)
  4. storage_agent     -> upload_to_cloud_storage   (raw + processed + report -> GCS/S3)

The SequentialAgent fixes the order of the stages. Each stage is an LLM agent
that decides how to call its tool (e.g. the ingestion agent turns "big quakes
from the last two weeks" into days=14, min_magnitude=4.5), checks the tool's
result, and writes a short note into session state via output_key. Stages pass
data to each other through ADK session state rather than by calling each other.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent

from .tools import (
    build_html_report,
    fetch_earthquakes,
    process_earthquakes,
    upload_to_cloud_storage,
)

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

STOP_RULE = (
    "If the tool returns status 'error', do not retry more than once. Reply with "
    "'STAGE FAILED:' followed by the error message so later stages and the user can see it."
)

ingestion_agent = LlmAgent(
    name="ingestion_agent",
    model=MODEL,
    description="Pulls raw earthquake data from the USGS public API.",
    instruction=(
        "You are the ingestion stage of a data pipeline. Read the user's request and "
        "call fetch_earthquakes exactly once.\n"
        "Choose the arguments from the request:\n"
        "- days: the look-back window (1-30). 'today' or 'past day' = 1, 'this week' = 7, "
        "'this month' = 30. Default 7.\n"
        "- min_magnitude: 'all' or 'small' = 1.0, 'felt' = 2.5, 'significant' or 'big' = 4.5. "
        "Default 2.5.\n"
        "Then reply in one sentence with the run id, the window and the number of features downloaded. "
        + STOP_RULE
    ),
    tools=[fetch_earthquakes],
    output_key="ingestion_result",
)

processing_agent = LlmAgent(
    name="processing_agent",
    model=MODEL,
    description="Cleans and aggregates the raw earthquake data.",
    instruction=(
        "You are the processing stage. Call process_earthquakes exactly once. It cleans the raw "
        "data (drops duplicates, non-earthquake events and rows with missing magnitude or "
        "coordinates) and aggregates it by day, magnitude band, depth class and region.\n"
        "Then reply with two or three sentences: total clean events, the strongest magnitude, "
        "the busiest region, and how many rows were dropped and why. If more than 20% of "
        "input rows were dropped, say 'DATA QUALITY WARNING' and explain. "
        + STOP_RULE
    ),
    tools=[process_earthquakes],
    output_key="processing_result",
)

reporting_agent = LlmAgent(
    name="reporting_agent",
    model=MODEL,
    description="Builds the HTML visualization page.",
    instruction=(
        "You are the visualization stage. Call build_html_report exactly once, then reply in "
        "one sentence with the path of the generated HTML report. " + STOP_RULE
    ),
    tools=[build_html_report],
    output_key="report_result",
)

storage_agent = LlmAgent(
    name="storage_agent",
    model=MODEL,
    description="Uploads raw data, processed data and the report to cloud object storage.",
    instruction=(
        "You are the storage stage and the last step of the pipeline. Call "
        "upload_to_cloud_storage exactly once.\n"
        "Then write the final run summary for the user as a short bulleted list: the run id, "
        "the storage backend, every uploaded object URI, and any failed uploads. End with one "
        "sentence on what the data shows (busiest region and strongest quake). " + STOP_RULE
    ),
    tools=[upload_to_cloud_storage],
    output_key="storage_result",
)

root_agent = SequentialAgent(
    name="earthquake_pipeline",
    description="End-to-end agentic pipeline: ingest -> process -> visualize -> store.",
    sub_agents=[ingestion_agent, processing_agent, reporting_agent, storage_agent],
)
