# Running Coach

A personal AI running coach powered by your Strava data and Claude. Chat in your terminal — ask about your training, recovery, pace trends, race preparation, and more.

```
You: Am I overtraining?

Coach: Your acute:chronic load ratio is 1.38 — slightly above the 1.3 threshold that
       typically signals elevated injury risk. Over the past 3 weeks you've ramped from
       42km to 61km, a 45% jump. I'd recommend dropping back to ~50km this week before
       building again. Your Z2 distribution is excellent at 74%, so the issue is volume,
       not intensity.
```

## How it works

Your COROS watch syncs runs to Strava. This tool pulls that data into a local SQLite database, then lets you chat with Claude. Claude has tools to query your training history on demand — so it always answers with your real numbers.

---

## Prerequisites

### 1. Create a Strava API Application

1. Log into Strava and go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
2. Fill in the form:
   - **Application Name**: e.g. "My Running Coach"
   - **Category**: Other
   - **Website**: `http://localhost`
   - **Authorization Callback Domain**: `localhost` ← important
3. Click **Create**
4. Copy your **Client ID** and **Client Secret**

### 2. Get an Anthropic API Key

1. Go to [https://console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Navigate to **API Keys** → **Create Key**
4. Copy the key (shown only once)

---

## Installation

### Requirements

- Python 3.12 or newer
- pip

### Steps

```bash
# 1. Navigate to the project directory
cd path/to/strava

# 2. Create a virtual environment
python -m venv .venv

# On Windows (PowerShell or Command Prompt):
.venv\Scripts\activate

# On macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -e .
```

### Configure credentials

```bash
# Copy the template
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```
STRAVA_CLIENT_ID=12345
STRAVA_CLIENT_SECRET=abc123...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## First-time setup

```bash
coach setup
```

This will:
1. Open your browser to authorize Strava access
2. Download and cache all your activities locally

> **Note:** The initial sync can take 20–60 minutes for large training histories due to Strava's rate limits (200 requests per 15 minutes). A progress bar shows the status.

---

## Usage

### Start chatting

```bash
coach chat
```

Example questions:
- "How was my training last week?"
- "Am I overtraining?"
- "What's my average pace trend over the last 3 months?"
- "How does my HR zone distribution look?"
- "Am I ready for a half marathon next month?"
- "What was my longest run ever?"
- "Find my parkrun activities"

Special commands in chat:
- `/reset` — clear conversation history
- `/sync` — sync new activities without leaving chat
- `/quit` — exit

### Sync new activities

Run this after completing a new run (once it's appeared in Strava):

```bash
coach sync
```

### View training stats (no AI)

```bash
coach stats
```

Shows a table of recent activities and a 6-week weekly mileage summary.

### View a specific activity

```bash
coach activity 12345678
```

Replace `12345678` with the Strava activity ID (visible in the URL when viewing an activity on strava.com).

---

## Data & privacy

- All data is stored locally in `data/coach.db` (SQLite)
- OAuth tokens are stored in `data/tokens.json`
- Nothing is sent to external services except:
  - Strava API (to fetch your activities)
  - Anthropic API (your questions + tool results, to generate coaching responses)
- The `data/` directory and `.env` are gitignored

---

## Future ideas

- **Web UI** — wrap the coaching session in FastAPI + a minimal HTML chat interface
- **Telegram bot** — get post-run coaching summaries on your phone
- **Strava webhooks** — auto-sync whenever a new activity is recorded
