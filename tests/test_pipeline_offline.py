"""End-to-end test of the real ADK agent graph, fully offline.

A scripted stand-in replaces Gemini (it just calls each agent's tool once),
the USGS request is mocked with the fixture data, and storage uses the
local backend. This proves the agents, tools, state hand-offs, report and
upload all wire together without needing API keys or cloud credentials.
"""

import asyncio
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

import run_pipeline
from quake_pipeline import agent as agent_module
from quake_pipeline import tools
from tests.fixtures import SAMPLE


class ScriptedLlm(BaseLlm):
    """Calls the agent's only tool once, then answers with a short text."""

    model: str = "scripted"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1] if llm_request.contents else None
        already_called = last and any(p.function_response for p in (last.parts or []))
        if already_called:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Stage done.")]))
            return
        tool_name = next(iter(llm_request.tools_dict))
        args = {"days": 7, "min_magnitude": 2.5} if tool_name == "fetch_earthquakes" else {}
        yield LlmResponse(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name=tool_name, args=args))]))


def build_offline_pipeline():
    llm = ScriptedLlm()
    stages = [agent_module.ingestion_agent, agent_module.processing_agent,
              agent_module.reporting_agent, agent_module.storage_agent]
    return SequentialAgent(name="earthquake_pipeline_test", sub_agents=[
        LlmAgent(name=a.name, model=llm, instruction=a.instruction, tools=a.tools,
                 output_key=a.output_key) for a in stages])


def test_full_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr(tools, "OUTPUT_ROOT", Path("output"))

    fake_response = MagicMock()
    fake_response.json.return_value = SAMPLE
    fake_response.raise_for_status.return_value = None

    with patch.object(tools.requests, "get", return_value=fake_response):
        state = asyncio.run(run_pipeline.run("past week, M2.5+", agent=build_offline_pipeline()))

    assert state["params"] == {"days": 7, "min_magnitude": 2.5}
    report = Path(state["report_path"]).read_text(encoding="utf-8")
    assert "Earthquake Activity Report" in report and "Hachinohe" in report
    assert len(state["uploaded_uris"]) == 5  # raw + csv + summary + quality + report
    bucket = tmp_path / "output" / "bucket" / "earthquakes"
    assert (bucket / "raw").is_dir() and (bucket / "processed").is_dir() and (bucket / "report").is_dir()
