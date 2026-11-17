"""Command-line entry point: runs the ADK agent pipeline once.

    python run_pipeline.py
    python run_pipeline.py "Show me significant earthquakes from the last 14 days"

You can also use ADK's own tools from the repo root:
    adk run quake_pipeline      # chat in the terminal
    adk web                     # browser dev UI, pick "quake_pipeline"
"""

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from quake_pipeline.agent import root_agent  # noqa: E402

APP_NAME = "quake_pipeline"
DEFAULT_REQUEST = "Build the earthquake report for the past 7 days, magnitude 2.5 and above."


async def run(request: str, agent=root_agent) -> dict:
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id="cli")
    message = types.Content(role="user", parts=[types.Part(text=request)])

    print(f"\nRequest: {request}\n")
    async for event in runner.run_async(user_id="cli", session_id=session.id, new_message=message):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call:
                print(f"[{event.author}] -> calling {part.function_call.name}({dict(part.function_call.args or {})})")
            elif part.function_response:
                status = (part.function_response.response or {}).get("status")
                print(f"[{event.author}] <- {part.function_response.name}: {status}")
            elif part.text and part.text.strip():
                print(f"[{event.author}] {part.text.strip()}\n")

    final = await runner.session_service.get_session(app_name=APP_NAME, user_id="cli", session_id=session.id)
    state = dict(final.state)
    print("=" * 70)
    if state.get("report_path"):
        print(f"Report:   {state['report_path']}  (latest copy: output/report.html)")
    for uri in state.get("uploaded_uris", []):
        print(f"Uploaded: {uri}")
    if not state.get("uploaded_uris"):
        print("Nothing was uploaded - see the agent messages above.")
    return state


if __name__ == "__main__":
    asyncio.run(run(" ".join(sys.argv[1:]) or DEFAULT_REQUEST))
