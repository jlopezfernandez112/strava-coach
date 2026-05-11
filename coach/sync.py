"""Strava API client and activity sync logic."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlalchemy.engine import Connection

from .auth import get_valid_token, load_tokens, save_tokens, is_expired, refresh_access_token
from .config import Config
from .db import (
    create_engine_for,
    create_tables,
    get_sync_state,
    set_sync_state,
    upsert_activity,
    upsert_splits,
)

STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Stay safely under 200 req / 15 min (one request every ~0.35s = ~170 req/15min)
REQUEST_DELAY = 0.35


class StravaClient:
    def __init__(self, config: Config):
        self.config = config
        self._token: str | None = None

    def _get_token(self) -> str:
        if self._token is None:
            self._token = get_valid_token(self.config)
        return self._token

    def _refresh_if_needed(self) -> None:
        store = load_tokens(self.config.tokens_path)
        if store and is_expired(store):
            store = refresh_access_token(store, self.config)
            save_tokens(store, self.config.tokens_path)
            self._token = store.access_token

    def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        self._refresh_if_needed()
        url = f"{STRAVA_API_BASE}/{endpoint.lstrip('/')}"
        for attempt in range(3):
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                params=params or {},
                timeout=20,
            )
            if resp.status_code == 429:
                # Rate limited — wait 60 seconds and retry
                retry_after = int(resp.headers.get("X-RateLimit-Usage", "0,0").split(",")[0])
                wait = 60 if attempt == 0 else 120
                print(f"\nRate limited. Waiting {wait}s before retrying...")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                # Token expired mid-sync — refresh and retry
                self._token = None
                self._refresh_if_needed()
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Failed to fetch {endpoint} after retries")

    def get_athlete(self) -> dict:
        return self.get("/athlete")

    def get_activities(self, after: int = 0, per_page: int = 200, page: int = 1) -> list[dict]:
        return self.get("/athlete/activities", {
            "after": after,
            "per_page": per_page,
            "page": page,
        })

    def get_activity_detail(self, activity_id: int) -> dict:
        return self.get(f"/activities/{activity_id}", {"include_all_efforts": False})


def _extract_activity_row(a: dict) -> dict:
    """Map a Strava API activity dict to our DB columns."""
    return {
        "id": a["id"],
        "name": a.get("name"),
        "sport_type": a.get("sport_type") or a.get("type"),
        "start_date": a.get("start_date"),
        "start_date_local": a.get("start_date_local"),
        "distance": a.get("distance"),
        "moving_time": a.get("moving_time"),
        "elapsed_time": a.get("elapsed_time"),
        "total_elevation_gain": a.get("total_elevation_gain"),
        "average_heartrate": a.get("average_heartrate"),
        "max_heartrate": a.get("max_heartrate"),
        "average_cadence": a.get("average_cadence"),
        "average_watts": a.get("average_watts"),
        "suffer_score": a.get("suffer_score"),
        "workout_type": a.get("workout_type"),
        "description": a.get("description"),
        "raw_json": json.dumps(a),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def sync_activities(config: Config, full: bool = False) -> dict:
    """
    Sync activities from Strava into the local SQLite DB.

    full=True  → fetch all activities from the beginning of time
    full=False → only fetch activities newer than last sync timestamp
    Returns a summary dict with counts.
    """
    engine = create_engine_for(config.db_path)
    create_tables(engine)
    client = StravaClient(config)

    with engine.begin() as conn:
        if full:
            after_ts = 0
        else:
            last_sync = get_sync_state(conn, "last_sync_timestamp")
            after_ts = int(last_sync) if last_sync else 0

        # --- Phase 1: collect all activity summaries ---
        all_summaries: list[dict] = []
        page = 1
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Fetching activity list..."),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("fetching", total=None)
            while True:
                batch = client.get_activities(after=after_ts, per_page=200, page=page)
                if not batch:
                    break
                all_summaries.extend(batch)
                page += 1
                time.sleep(REQUEST_DELAY)

        if not all_summaries:
            return {"added": 0, "updated": 0, "message": "No new activities found."}

        # --- Phase 2: fetch detailed data per activity ---
        added = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Syncing activities"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("syncing", total=len(all_summaries))
            for summary in all_summaries:
                activity_id = summary["id"]
                sport = summary.get("sport_type") or summary.get("type", "")

                # Only fetch detail for running activities (save rate limit budget)
                is_run = sport in ("Run", "TrailRun", "VirtualRun", "Hike", "Walk")
                if is_run:
                    try:
                        detail = client.get_activity_detail(activity_id)
                        time.sleep(REQUEST_DELAY)
                    except Exception:
                        detail = summary  # fall back to summary data
                else:
                    detail = summary

                row = _extract_activity_row(detail)
                with engine.begin() as inner_conn:
                    upsert_activity(inner_conn, row)
                    # Upsert metric splits if available
                    splits = detail.get("splits_metric") or []
                    if splits:
                        upsert_splits(inner_conn, activity_id, splits)

                added += 1
                progress.advance(task)

        # Update sync timestamp to now
        with engine.begin() as conn:
            set_sync_state(conn, "last_sync_timestamp", str(int(time.time())))

        return {
            "added": added,
            "message": f"Synced {added} activit{'y' if added == 1 else 'ies'}.",
        }
