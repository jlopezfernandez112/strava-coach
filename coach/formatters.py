"""Human-readable formatting helpers."""
from __future__ import annotations

from rich.table import Table


def format_pace(avg_speed_ms: float | None) -> str:
    if not avg_speed_ms or avg_speed_ms <= 0:
        return "—"
    sec_per_km = 1000 / avg_speed_ms
    minutes = int(sec_per_km // 60)
    seconds = int(sec_per_km % 60)
    return f"{minutes}:{seconds:02d}/km"


def format_distance(meters: float | None) -> str:
    if meters is None:
        return "—"
    return f"{meters / 1000:.2f} km"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def format_activity_table(activities: list[dict]) -> Table:
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("ID", style="dim", width=12)
    table.add_column("Date", width=12)
    table.add_column("Name", width=30)
    table.add_column("Dist", justify="right", width=9)
    table.add_column("Time", justify="right", width=9)
    table.add_column("Pace", justify="right", width=9)
    table.add_column("HR", justify="right", width=6)
    table.add_column("Elev", justify="right", width=7)

    for a in activities:
        dist = a.get("distance") or 0
        mt = a.get("moving_time") or 0
        pace = format_pace(dist / mt) if dist and mt else "—"
        hr = f"{int(a['average_heartrate'])} bpm" if a.get("average_heartrate") else "—"
        elev = f"{int(a.get('total_elevation_gain') or 0)}m"
        date = (a.get("start_date_local") or "")[:10]
        table.add_row(
            str(a.get("id", "")),
            date,
            (a.get("name") or "")[:29],
            format_distance(dist),
            format_duration(mt),
            pace,
            hr,
            elev,
        )
    return table


def format_weekly_summary_table(weeks: list[dict]) -> Table:
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Week", width=10)
    table.add_column("Runs", justify="right", width=6)
    table.add_column("Total km", justify="right", width=10)
    table.add_column("Time", justify="right", width=10)
    table.add_column("Avg HR", justify="right", width=8)
    table.add_column("Elevation", justify="right", width=10)

    for w in weeks:
        avg_hr = f"{w['avg_hr']} bpm" if w.get("avg_hr") else "—"
        table.add_row(
            str(w.get("week", "")),
            str(w.get("runs", 0)),
            f"{w.get('total_km', 0)} km",
            w.get("total_time_fmt", "—"),
            avg_hr,
            f"{int(w.get('total_elevation_m') or 0)}m",
        )
    return table
