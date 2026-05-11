"""Claude agentic conversation loop and coaching system prompt."""
from __future__ import annotations

from typing import Any

import anthropic
from sqlalchemy.engine import Connection

from .config import Config
from .tools import TOOL_DEFINITIONS, execute_tool

MODEL = "claude-sonnet-4-6"
MAX_HISTORY_TURNS = 20  # keep last N user+assistant pairs to manage context


def build_system_prompt(athlete: dict) -> str:
    name = athlete.get("firstname", "the athlete")
    city = athlete.get("city", "")
    location = f" based in {city}" if city else ""

    return f"""You are a personal running coach for {name}{location}. You have access to their complete Strava training history via tools.

## Your coaching role
- Analyze training data honestly and specifically — always cite real numbers from the data
- Apply evidence-based training principles: 80/20 rule (80% easy/aerobic, 20% hard), progressive overload, periodisation, adequate recovery
- Use acute/chronic training load ratio to assess injury risk and readiness (ratio >1.3 = elevated risk, <0.8 = possible detraining)
- Give actionable, personalized advice — not generic tips

## Data source
{name} uses a COROS GPS watch that auto-syncs to Strava. All data comes from Strava. Fields that may be missing:
- Heart rate (requires HR monitor — check `average_heartrate` is not null)
- Power (requires power meter — check `average_watts`)
- Cadence (`average_cadence`)
Never invent numbers. If a field is null, acknowledge it and work with what's available.

## Tool usage
ALWAYS call the relevant tool(s) before answering data-related questions. Do not guess or estimate from memory — use the tools. You may call multiple tools in one turn if needed.

## Response style
- Be direct, warm, and specific
- Lead with the most important insight
- Use metric units (km, min/km pace)
- Format pace as MM:SS/km (e.g. 5:23/km)
- If the athlete asks about a race, check get_race_history first
- Keep responses focused — this is a terminal chat, not an essay

## Today's date
You should be aware that data cutoffs in the DB reflect what has been synced. Suggest `coach sync` if the athlete mentions a recent run that may not be in the data yet."""


class CoachSession:
    def __init__(self, config: Config, db_conn: Connection):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.db_conn = db_conn
        self.messages: list[dict] = []
        self._system_prompt: str | None = None

    def set_athlete(self, athlete: dict) -> None:
        self._system_prompt = build_system_prompt(athlete)

    def chat(self, user_message: str) -> str:
        """
        Send a user message, execute any tool calls, and return the final response text.
        Implements the standard Anthropic agentic tool-use loop.
        """
        if self._system_prompt is None:
            self._system_prompt = build_system_prompt({})

        self.messages.append({"role": "user", "content": user_message})
        self._trim_history()

        while True:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=self._system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            )

            # Collect all content blocks
            assistant_content = response.content

            # Build the assistant message (may include both text and tool_use blocks)
            self.messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                # Extract final text response
                text_blocks = [b.text for b in assistant_content if hasattr(b, "text")]
                return "\n".join(text_blocks).strip()

            if response.stop_reason == "tool_use":
                # Execute all tool calls and collect results
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        result_content = execute_tool(block.name, block.input, self.db_conn)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content,
                        })

                # Append tool results as a user message and loop back to Claude
                self.messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason
            text_blocks = [b.text for b in assistant_content if hasattr(b, "text")]
            return "\n".join(text_blocks).strip() or "(No response)"

    def reset(self) -> None:
        """Clear conversation history (system prompt is preserved)."""
        self.messages = []

    def _trim_history(self) -> None:
        """Keep only the last MAX_HISTORY_TURNS user+assistant pairs."""
        # Count only user/assistant turns (not tool result messages)
        # Simple approach: keep last MAX_HISTORY_TURNS * 2 messages
        max_messages = MAX_HISTORY_TURNS * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]
