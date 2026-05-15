# Running Coach — Project Context

## What this is
A personal AI running coach CLI. Pulls training data from Strava, caches it locally in SQLite, and provides a terminal chat interface powered by Claude (tool use). The user runs with a COROS GPS watch that auto-syncs to Strava — no direct COROS API exists.

## Architecture
```
COROS watch → Strava (auto-sync) → Strava API → Local SQLite DB → Claude tools → Terminal chat
```

## Environment
- **OS**: Windows 11 Enterprise (SAP SE corporate laptop)
- **Python**: 3.13 at `C:\Users\I757883\AppData\Local\Programs\Python\Python313\python.exe`
- **Shell**: Git Bash — cannot execute downloaded .exe files (blocked by corporate admin/AppLocker)
- **Virtual env**: `.venv` created via VSCode UI (`Ctrl+Shift+P` → Python: Create Environment → Venv → install from pyproject.toml)
- **NEVER** try to run `uv.exe`, downloaded `.exe` files, or `powershell Start-Process` — all blocked by admin policy
- **NEVER** run commands that trigger "This content is blocked by your admin" notifications
- Use `python -m pip`, `python -m venv`, etc. via PowerShell when command-line is needed

## Running the app (after venv is active)
```bash
# First-time setup (opens browser for Strava OAuth + full activity sync)
python -m coach.cli setup

# Or if installed as package:
coach setup
coach sync        # incremental sync after new runs
coach chat        # start the AI coaching session
coach stats       # quick stats table, no AI
coach activity <id>  # detail view of one activity
```

## Project structure
```
strava/
├── pyproject.toml
├── .env                  # credentials (gitignored) — copy from .env.example
├── .env.example
├── .gitignore
├── README.md
├── coach/
│   ├── __init__.py
│   ├── cli.py            # Click entry point + REPL
│   ├── config.py         # Config dataclass, load_config(), ensure_data_dir()
│   ├── auth.py           # Strava OAuth2 + token refresh + localhost:8080 callback
│   ├── sync.py           # Strava API client + sync_activities()
│   ├── db.py             # SQLite schema (SQLAlchemy Core) + all query functions
│   ├── tools.py          # Claude tool definitions + execute_tool() dispatcher
│   ├── coach.py          # CoachSession + agentic loop + system prompt
│   └── formatters.py     # pace/distance/duration + Rich tables
└── data/                 # gitignored, created at runtime
    ├── coach.db          # SQLite database
    └── tokens.json       # Strava OAuth tokens
```

## Dependencies (pyproject.toml)
- `anthropic>=0.40.0` — Claude API + tool use
- `httpx>=0.27.0` — HTTP client for Strava API
- `python-dotenv>=1.0.0` — .env loading
- `rich>=13.0.0` — terminal formatting + markdown rendering
- `click>=8.1.0` — CLI commands
- `SQLAlchemy>=2.0.0` — SQLite ORM/Core
- `python-dateutil>=2.9.0` — date arithmetic

## Credentials needed (in .env)
```
STRAVA_CLIENT_ID=       # from https://www.strava.com/settings/api
STRAVA_CLIENT_SECRET=   # same page — set callback domain to "localhost"
ANTHROPIC_API_KEY=      # from https://console.anthropic.com
```
All credentials are configured in `.env`. The `.env` file is gitignored and must never be committed.
- Strava app: created at strava.com/settings/api with Website=`http://localhost`, Callback Domain=`localhost`
- Anthropic API key: personal account at console.anthropic.com, pay-per-use (no subscription needed)

## Key design decisions
- **SQLite cache**: avoids hitting Strava rate limits (200 req/15min) during Claude conversations
- **Tool use over context stuffing**: Claude fetches data on demand, keeps token cost low
- **Local OAuth callback**: `auth.py` uses `http.server` on localhost:8080 — no Flask needed
- **Model**: `claude-sonnet-4-6`
- **Rate limit handling**: 0.35s sleep between Strava detail fetches during sync

## Claude tools available
| Tool | Description |
|------|-------------|
| `get_recent_activities` | Last N activities with stats |
| `get_weekly_mileage` | Weekly distance/time/HR summary |
| `get_activity_detail` | Single activity with km splits |
| `get_pace_trend` | Average pace per week over time |
| `get_hr_zone_distribution` | Z1-Z5 distribution (80/20 check) |
| `get_training_load` | Acute/chronic load ratio (ATL/CTL) |
| `get_race_history` | All recorded races |
| `get_longest_runs` | Top N longest runs |
| `search_activities` | Keyword search on name/description |
| `get_activities_in_range` | Activities in a date range |
| `save_memory` | Persist a coaching note (goal/preference/health/training/general) |
| `update_memory` | Update an existing coaching note by ID |
| `delete_memory` | Delete a stale or resolved coaching note |

## Implementation status
- All code complete, `.venv` working, all dependencies installed
- `.env` configured with all credentials (Strava + Anthropic)
- `coach setup` completed: Strava OAuth done, full activity history synced into `data/coach.db`
- All features merged to master and pushed to GitHub
- Persistent memory implemented: `memories` SQLite table + 3 Claude tools (`save_memory`, `update_memory`, `delete_memory`) + system prompt injection + end-of-session housekeeping on `/quit`
- `coach memories` command: prints all coaching notes as a Rich table

## Sync workflow (important)
- `setup` = one-time full sync, do NOT run again
- `sync` = incremental, only fetches activities newer than last sync timestamp — run after each new run
- `/sync` command works inside the chat session too (no need to exit)

## Tried and rejected
- **Streaming responses**: Implemented and tested. The Anthropic API delivers tokens in network-batched bursts (whole sentences/paragraphs at once), not a smooth word-by-word trickle like Claude.ai. Felt worse than the current single-chunk display. Reverted. Do not retry unless API delivery behaviour changes.
- **Per-second HR streams**: Considered pulling `/activities/{id}/streams` to get per-second HR data for accurate zone distribution. Rejected — practical coaching value doesn't justify ~100MB storage, extra API call per sync, and added query complexity. Most runs are steady-state so `average_heartrate` per activity is a sufficient proxy. Do not implement.

## Future roadmap (not yet built)
- **Training plan generator**: Given a race date + goal, generate a week-by-week structured plan. New Claude tool or CLI command.
- **Race predictor**: Estimate finish time for a target distance using Riegel/Vdot formulas applied to actual training data.
- **Strava webhooks**: Auto-sync `coach.db` on every new Strava activity — no manual `coach sync` needed.
- Web UI: FastAPI + minimal HTML (swap cli.py, CoachSession unchanged)
- Telegram bot: python-telegram-bot, each chat = CoachSession
