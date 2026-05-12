"""SQLite schema and all query functions used by Claude tools."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

activities_table = Table(
    "activities",
    metadata,
    Column("id", Integer, primary_key=True),  # Strava activity ID
    Column("name", String),
    Column("sport_type", String),
    Column("start_date", String),        # UTC ISO8601
    Column("start_date_local", String),  # local ISO8601
    Column("distance", Float),           # meters
    Column("moving_time", Integer),      # seconds
    Column("elapsed_time", Integer),     # seconds
    Column("total_elevation_gain", Float),
    Column("average_heartrate", Float),
    Column("max_heartrate", Float),
    Column("average_cadence", Float),
    Column("average_watts", Float),
    Column("suffer_score", Integer),
    Column("workout_type", Integer),     # 0=default,1=race,2=long run,3=workout
    Column("description", Text),
    Column("raw_json", Text),            # full Strava JSON
    Column("synced_at", String),
)

splits_table = Table(
    "splits",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("activity_id", Integer),
    Column("split_number", Integer),
    Column("distance", Float),
    Column("elapsed_time", Integer),
    Column("moving_time", Integer),
    Column("average_speed", Float),      # m/s
    Column("average_heartrate", Float),
    Column("average_cadence", Float),
    Column("elevation_difference", Float),
)

sync_state_table = Table(
    "sync_state",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", Text),
)

memories_table = Table(
    "memories",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("category", String),   # goal | preference | health | training | general
    Column("content", Text),
    Column("created_at", String), # UTC ISO8601
    Column("updated_at", String), # UTC ISO8601
)


def create_engine_for(db_path: Path) -> Engine:
    return create_engine(f"sqlite:///{db_path}", echo=False)


def create_tables(engine: Engine) -> None:
    metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    return dict(row._mapping)


def _format_pace(avg_speed_ms: float | None) -> str | None:
    """Convert m/s to min:sec/km string."""
    if not avg_speed_ms or avg_speed_ms <= 0:
        return None
    sec_per_km = 1000 / avg_speed_ms
    minutes = int(sec_per_km // 60)
    seconds = int(sec_per_km % 60)
    return f"{minutes}:{seconds:02d}/km"


def _enrich(row: dict) -> dict:
    """Add human-readable fields to a raw activity dict."""
    dist = row.get("distance") or 0
    row["distance_km"] = round(dist / 1000, 2)
    mt = row.get("moving_time") or 0
    row["moving_time_fmt"] = f"{mt // 3600}h {(mt % 3600) // 60}m" if mt >= 3600 else f"{mt // 60}m {mt % 60}s"
    # pace from distance + moving_time
    if dist and mt:
        row["avg_pace"] = _format_pace(dist / mt)
    return row


# ---------------------------------------------------------------------------
# Query functions (each maps to a Claude tool)
# ---------------------------------------------------------------------------

def get_recent_activities(conn: Connection, n: int = 10, sport_type: str | None = None) -> list[dict]:
    q = "SELECT * FROM activities"
    params: dict = {}
    if sport_type:
        q += " WHERE sport_type = :sport_type"
        params["sport_type"] = sport_type
    q += " ORDER BY start_date DESC LIMIT :n"
    params["n"] = n
    rows = conn.execute(text(q), params).fetchall()
    return [_enrich(_row_to_dict(r)) for r in rows]


def get_activities_in_range(conn: Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        text("SELECT * FROM activities WHERE start_date_local >= :s AND start_date_local <= :e ORDER BY start_date DESC"),
        {"s": start_date, "e": end_date},
    ).fetchall()
    return [_enrich(_row_to_dict(r)) for r in rows]


def get_weekly_summary(conn: Connection, weeks: int = 8) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    rows = conn.execute(
        text("""
            SELECT
                strftime('%Y-W%W', start_date_local) AS week,
                COUNT(*) AS runs,
                ROUND(SUM(distance) / 1000.0, 2) AS total_km,
                SUM(moving_time) AS total_seconds,
                ROUND(AVG(average_heartrate), 1) AS avg_hr,
                ROUND(SUM(total_elevation_gain), 0) AS total_elevation_m
            FROM activities
            WHERE start_date >= :cutoff AND sport_type IN ('Run', 'TrailRun', 'VirtualRun')
            GROUP BY week
            ORDER BY week DESC
        """),
        {"cutoff": cutoff},
    ).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        s = d.get("total_seconds") or 0
        d["total_time_fmt"] = f"{s // 3600}h {(s % 3600) // 60}m"
        result.append(d)
    return result


def get_activity_detail(conn: Connection, activity_id: int) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM activities WHERE id = :id"),
        {"id": activity_id},
    ).fetchone()
    if not row:
        return None
    activity = _enrich(_row_to_dict(row))
    splits = conn.execute(
        text("SELECT * FROM splits WHERE activity_id = :id ORDER BY split_number"),
        {"id": activity_id},
    ).fetchall()
    activity["splits"] = []
    for s in splits:
        sd = _row_to_dict(s)
        sd["pace"] = _format_pace(sd.get("average_speed"))
        sd["distance_km"] = round((sd.get("distance") or 0) / 1000, 2)
        activity["splits"].append(sd)
    return activity


def get_pace_trend(conn: Connection, weeks: int = 12, sport_type: str = "Run") -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    rows = conn.execute(
        text("""
            SELECT
                strftime('%Y-W%W', start_date_local) AS week,
                COUNT(*) AS runs,
                ROUND(AVG(distance / moving_time), 4) AS avg_speed_ms,
                ROUND(AVG(distance) / 1000.0, 2) AS avg_distance_km
            FROM activities
            WHERE start_date >= :cutoff
              AND sport_type = :sport_type
              AND moving_time > 0
              AND distance > 0
            GROUP BY week
            ORDER BY week DESC
        """),
        {"cutoff": cutoff, "sport_type": sport_type},
    ).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["avg_pace"] = _format_pace(d.get("avg_speed_ms"))
        result.append(d)
    return result


def get_hr_zone_distribution(conn: Connection, weeks: int | None = None) -> dict:
    """
    Returns approximate zone distribution based on max HR thresholds.
    Zones (% of max HR): Z1 <60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >90%
    Uses average_heartrate as proxy (not perfect, but useful without streams).
    """
    params: dict = {}
    where = "WHERE average_heartrate IS NOT NULL AND sport_type IN ('Run','TrailRun','VirtualRun')"
    if weeks:
        cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
        where += " AND start_date >= :cutoff"
        params["cutoff"] = cutoff

    rows = conn.execute(
        text(f"SELECT average_heartrate, moving_time FROM activities {where}"),
        params,
    ).fetchall()

    if not rows:
        return {"note": "No heart rate data found."}

    # Estimate max HR if not explicitly set (use 95th percentile of max_hr data)
    max_hrs = conn.execute(
        text(f"SELECT max_heartrate FROM activities {where} AND max_heartrate IS NOT NULL"),
        params,
    ).fetchall()
    if max_hrs:
        max_hr_values = sorted([r[0] for r in max_hrs])
        idx = int(len(max_hr_values) * 0.95)
        estimated_max_hr = max_hr_values[min(idx, len(max_hr_values) - 1)]
    else:
        estimated_max_hr = 185  # reasonable default

    zones = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}
    total_time = 0
    for avg_hr, mt in rows:
        mt = mt or 0
        pct = avg_hr / estimated_max_hr
        total_time += mt
        if pct < 0.60:
            zones["Z1"] += mt
        elif pct < 0.70:
            zones["Z2"] += mt
        elif pct < 0.80:
            zones["Z3"] += mt
        elif pct < 0.90:
            zones["Z4"] += mt
        else:
            zones["Z5"] += mt

    if total_time:
        zone_pcts = {k: round(v / total_time * 100, 1) for k, v in zones.items()}
    else:
        zone_pcts = {k: 0.0 for k in zones}

    return {
        "estimated_max_hr": estimated_max_hr,
        "total_activities": len(rows),
        "zone_distribution_pct": zone_pcts,
        "note": "Based on average HR per activity (not per-second streams). Z1<60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5>90% of estimated max HR.",
    }


def get_training_load_summary(conn: Connection) -> dict:
    """
    Acute Training Load (ATL) = weighted average of last 7 days effort
    Chronic Training Load (CTL) = weighted average of last 42 days effort
    Effort proxy = distance_km * (1 + elevation_gain/1000) * hr_multiplier
    TSB (Training Stress Balance) = CTL - ATL
    """
    now = datetime.now(timezone.utc)

    def load_for_days(days: int) -> float:
        cutoff = (now - timedelta(days=days)).isoformat()
        rows = conn.execute(
            text("""
                SELECT distance, total_elevation_gain, average_heartrate, moving_time
                FROM activities
                WHERE start_date >= :cutoff
                  AND sport_type IN ('Run','TrailRun','VirtualRun')
            """),
            {"cutoff": cutoff},
        ).fetchall()
        total = 0.0
        for dist, elev, hr, mt in rows:
            km = (dist or 0) / 1000
            elev_bonus = 1 + (elev or 0) / 1000
            hr_factor = 1.0 + ((hr or 140) - 140) / 200  # rough HR intensity
            total += km * elev_bonus * hr_factor
        return round(total, 1)

    atl = load_for_days(7)
    ctl = load_for_days(42)
    ratio = round(atl / ctl, 2) if ctl else None

    return {
        "acute_load_7d": atl,
        "chronic_load_42d": ctl,
        "atl_ctl_ratio": ratio,
        "interpretation": (
            "Ratio >1.3 suggests high acute load (elevated injury risk). "
            "Ratio 0.8-1.3 is the sweet spot for fitness gains. "
            "Ratio <0.8 may indicate detraining."
        ),
    }


def get_race_history(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text("SELECT * FROM activities WHERE workout_type = 1 ORDER BY start_date DESC"),
    ).fetchall()
    return [_enrich(_row_to_dict(r)) for r in rows]


def get_longest_runs(conn: Connection, n: int = 5) -> list[dict]:
    rows = conn.execute(
        text("""
            SELECT * FROM activities
            WHERE sport_type IN ('Run','TrailRun','VirtualRun')
            ORDER BY distance DESC
            LIMIT :n
        """),
        {"n": n},
    ).fetchall()
    return [_enrich(_row_to_dict(r)) for r in rows]


def search_activities(conn: Connection, query: str) -> list[dict]:
    like = f"%{query}%"
    rows = conn.execute(
        text("""
            SELECT * FROM activities
            WHERE name LIKE :q OR description LIKE :q
            ORDER BY start_date DESC
            LIMIT 20
        """),
        {"q": like},
    ).fetchall()
    return [_enrich(_row_to_dict(r)) for r in rows]


def upsert_activity(conn: Connection, data: dict) -> None:
    """Insert or replace a single activity row."""
    conn.execute(
        text("""
            INSERT OR REPLACE INTO activities
            (id, name, sport_type, start_date, start_date_local, distance,
             moving_time, elapsed_time, total_elevation_gain, average_heartrate,
             max_heartrate, average_cadence, average_watts, suffer_score,
             workout_type, description, raw_json, synced_at)
            VALUES
            (:id, :name, :sport_type, :start_date, :start_date_local, :distance,
             :moving_time, :elapsed_time, :total_elevation_gain, :average_heartrate,
             :max_heartrate, :average_cadence, :average_watts, :suffer_score,
             :workout_type, :description, :raw_json, :synced_at)
        """),
        data,
    )


def upsert_splits(conn: Connection, activity_id: int, splits: list[dict]) -> None:
    conn.execute(text("DELETE FROM splits WHERE activity_id = :id"), {"id": activity_id})
    for i, s in enumerate(splits, 1):
        conn.execute(
            text("""
                INSERT INTO splits
                (activity_id, split_number, distance, elapsed_time, moving_time,
                 average_speed, average_heartrate, average_cadence, elevation_difference)
                VALUES
                (:activity_id, :split_number, :distance, :elapsed_time, :moving_time,
                 :average_speed, :average_heartrate, :average_cadence, :elevation_difference)
            """),
            {
                "activity_id": activity_id,
                "split_number": i,
                "distance": s.get("distance"),
                "elapsed_time": s.get("elapsed_time"),
                "moving_time": s.get("moving_time"),
                "average_speed": s.get("average_speed"),
                "average_heartrate": s.get("average_heartrate"),
                "average_cadence": s.get("average_cadence"),
                "elevation_difference": s.get("elevation_difference"),
            },
        )


def get_sync_state(conn: Connection, key: str) -> str | None:
    row = conn.execute(text("SELECT value FROM sync_state WHERE key = :k"), {"k": key}).fetchone()
    return row[0] if row else None


def set_sync_state(conn: Connection, key: str, value: str) -> None:
    conn.execute(
        text("INSERT OR REPLACE INTO sync_state (key, value) VALUES (:k, :v)"),
        {"k": key, "v": value},
    )


# ---------------------------------------------------------------------------
# Memory / coaching notes
# ---------------------------------------------------------------------------

def get_all_memories(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, category, content, created_at, updated_at FROM memories ORDER BY category, id")
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def save_memory(conn: Connection, category: str, content: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    result = conn.execute(
        text("INSERT INTO memories (category, content, created_at, updated_at) VALUES (:cat, :content, :now, :now)"),
        {"cat": category, "content": content, "now": now},
    )
    conn.commit()
    return result.lastrowid


def update_memory(conn: Connection, memory_id: int, content: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    result = conn.execute(
        text("UPDATE memories SET content = :content, updated_at = :now WHERE id = :id"),
        {"content": content, "now": now, "id": memory_id},
    )
    conn.commit()
    return result.rowcount > 0


def delete_memory(conn: Connection, memory_id: int) -> bool:
    result = conn.execute(text("DELETE FROM memories WHERE id = :id"), {"id": memory_id})
    conn.commit()
    return result.rowcount > 0
