"""Claude tool definitions and executor dispatch."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from . import db

# ---------------------------------------------------------------------------
# Tool definitions — passed directly to the Claude API as tools=
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_recent_activities",
        "description": (
            "Get the N most recent activities with key stats (distance, pace, HR, elevation). "
            "Use this to answer questions about recent training or a specific recent run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of recent activities to return (default 10)", "default": 10},
                "sport_type": {"type": "string", "description": "Filter by sport type, e.g. 'Run', 'TrailRun'. Omit for all types."},
            },
        },
    },
    {
        "name": "get_weekly_mileage",
        "description": (
            "Get weekly training summary (total distance, time, elevation, avg HR) for the past N weeks. "
            "Use this to analyze training volume trends, weekly load, and consistency."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {"type": "integer", "description": "Number of past weeks to include (default 8)", "default": 8},
            },
        },
    },
    {
        "name": "get_activity_detail",
        "description": (
            "Get full details of a specific activity including km splits, HR per split, pace per split. "
            "Use when the athlete asks about a specific run by ID or when you need split-level data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer", "description": "The Strava activity ID"},
            },
            "required": ["activity_id"],
        },
    },
    {
        "name": "get_pace_trend",
        "description": (
            "Get average pace per week over time to identify whether the athlete is getting faster or slower. "
            "Use this for performance trend analysis or when asked about improvement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {"type": "integer", "description": "Number of past weeks to analyze (default 12)", "default": 12},
                "sport_type": {"type": "string", "description": "Sport type to analyze (default 'Run')", "default": "Run"},
            },
        },
    },
    {
        "name": "get_hr_zone_distribution",
        "description": (
            "Get heart rate zone distribution (Z1–Z5) across runs to assess training intensity balance. "
            "Use this to evaluate whether training follows the 80/20 principle (80% easy, 20% hard)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {"type": "integer", "description": "Limit to last N weeks. Omit for all-time distribution."},
            },
        },
    },
    {
        "name": "get_training_load",
        "description": (
            "Get acute training load (last 7 days), chronic training load (last 42 days), and their ratio. "
            "Use this to assess recovery status, overtraining risk, or readiness for a race. "
            "Ratio >1.3 indicates high stress. Ratio <0.8 may indicate detraining."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_race_history",
        "description": (
            "Get all races the athlete has recorded (activities marked as race type). "
            "Use this to discuss past race performances or track progress toward race goals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_longest_runs",
        "description": (
            "Get the N longest runs ever recorded. "
            "Use this when asked about longest efforts, long run preparation, or training history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of longest runs to return (default 5)", "default": 5},
            },
        },
    },
    {
        "name": "search_activities",
        "description": (
            "Search activities by keyword in their name or description. "
            "Use this when the athlete references a run by name (e.g. 'my parkrun last month', 'Sunday long run')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search for in activity names and descriptions"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_activities_in_range",
        "description": (
            "Get all activities within a specific date range. "
            "Use this when the athlete asks about training during a particular period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
            },
            "required": ["start_date", "end_date"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, tool_input: dict, conn: Connection) -> str:
    """
    Dispatch a Claude tool call to the appropriate db query function.
    Returns a JSON string to pass back as tool_result content.
    """
    try:
        if tool_name == "get_recent_activities":
            result = db.get_recent_activities(conn, n=tool_input.get("n", 10), sport_type=tool_input.get("sport_type"))
        elif tool_name == "get_weekly_mileage":
            result = db.get_weekly_summary(conn, weeks=tool_input.get("weeks", 8))
        elif tool_name == "get_activity_detail":
            result = db.get_activity_detail(conn, activity_id=tool_input["activity_id"])
            if result is None:
                result = {"error": f"Activity {tool_input['activity_id']} not found in local database."}
        elif tool_name == "get_pace_trend":
            result = db.get_pace_trend(conn, weeks=tool_input.get("weeks", 12), sport_type=tool_input.get("sport_type", "Run"))
        elif tool_name == "get_hr_zone_distribution":
            result = db.get_hr_zone_distribution(conn, weeks=tool_input.get("weeks"))
        elif tool_name == "get_training_load":
            result = db.get_training_load_summary(conn)
        elif tool_name == "get_race_history":
            result = db.get_race_history(conn)
        elif tool_name == "get_longest_runs":
            result = db.get_longest_runs(conn, n=tool_input.get("n", 5))
        elif tool_name == "search_activities":
            result = db.search_activities(conn, query=tool_input["query"])
        elif tool_name == "get_activities_in_range":
            result = db.get_activities_in_range(conn, start_date=tool_input["start_date"], end_date=tool_input["end_date"])
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": str(e)}

    return json.dumps(result, default=str)
