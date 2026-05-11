"""CLI entry point — Click commands + Rich terminal REPL."""
from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .auth import get_valid_token, load_tokens, run_oauth_flow, save_tokens
from .config import ConfigError, ensure_data_dir, load_config
from .db import create_engine_for, create_tables, get_recent_activities, get_weekly_summary
from .formatters import format_activity_table, format_weekly_summary_table
from .sync import StravaClient, sync_activities

console = Console()


def _get_config():
    try:
        return load_config()
    except ConfigError as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)


@click.group()
def main():
    """Personal AI running coach powered by Strava + Claude."""
    pass


@main.command()
def setup():
    """One-time setup: authorize Strava and sync all activities."""
    config = _get_config()
    ensure_data_dir(config)

    console.print(Panel("[bold]Running Coach — First-Time Setup[/bold]", style="cyan"))

    # Step 1: OAuth
    existing = load_tokens(config.tokens_path)
    if existing:
        console.print("[green]✓[/green] Strava tokens already exist. Skipping authorization.")
    else:
        console.print("\n[bold]Step 1:[/bold] Strava Authorization")
        store = run_oauth_flow(config)
        save_tokens(store, config.tokens_path)
        console.print(f"[green]✓[/green] Authorized as athlete ID {store.athlete_id}")

    # Step 2: Full sync
    console.print("\n[bold]Step 2:[/bold] Syncing all activities from Strava")
    console.print("[dim]This may take a while for large training histories (rate limits apply)...[/dim]\n")

    result = sync_activities(config, full=True)
    console.print(f"\n[green]✓[/green] {result['message']}")
    console.print("\n[bold green]Setup complete![/bold green] Run [cyan]coach chat[/cyan] to start coaching.")


@main.command()
def sync():
    """Sync new activities from Strava (incremental)."""
    config = _get_config()
    ensure_data_dir(config)

    console.print("[dim]Syncing new activities...[/dim]")
    result = sync_activities(config, full=False)
    console.print(f"[green]✓[/green] {result['message']}")


@main.command()
def stats():
    """Quick training summary — no AI, just your data."""
    config = _get_config()

    if not config.db_path.exists():
        console.print("[yellow]No local database found. Run [cyan]coach setup[/cyan] first.[/yellow]")
        sys.exit(1)

    engine = create_engine_for(config.db_path)
    with engine.connect() as conn:
        recent = get_recent_activities(conn, n=10, sport_type=None)
        weekly = get_weekly_summary(conn, weeks=6)

    console.print(Panel("[bold]Recent Activities[/bold]", style="cyan"))
    if recent:
        console.print(format_activity_table(recent))
    else:
        console.print("[dim]No activities found.[/dim]")

    console.print()
    console.print(Panel("[bold]Weekly Summary (last 6 weeks)[/bold]", style="cyan"))
    if weekly:
        console.print(format_weekly_summary_table(weekly))
    else:
        console.print("[dim]No data for the past 6 weeks.[/dim]")


@main.command()
@click.argument("activity_id", type=int)
def activity(activity_id: int):
    """Show details for a specific activity by its Strava ID."""
    config = _get_config()

    if not config.db_path.exists():
        console.print("[yellow]No local database found. Run [cyan]coach setup[/cyan] first.[/yellow]")
        sys.exit(1)

    from .db import get_activity_detail
    from .formatters import format_distance, format_duration, format_pace

    engine = create_engine_for(config.db_path)
    with engine.connect() as conn:
        a = get_activity_detail(conn, activity_id)

    if not a:
        console.print(f"[red]Activity {activity_id} not found in local database.[/red]")
        sys.exit(1)

    dist = a.get("distance") or 0
    mt = a.get("moving_time") or 0
    pace = format_pace(dist / mt) if dist and mt else "—"

    console.print(Panel(f"[bold]{a.get('name', 'Activity')}[/bold]  [dim]{(a.get('start_date_local') or '')[:10]}[/dim]", style="cyan"))
    console.print(f"  Distance:   {format_distance(dist)}")
    console.print(f"  Time:       {format_duration(mt)}")
    console.print(f"  Avg pace:   {pace}")
    console.print(f"  Elevation:  {int(a.get('total_elevation_gain') or 0)}m")
    if a.get("average_heartrate"):
        console.print(f"  Avg HR:     {int(a['average_heartrate'])} bpm (max {int(a.get('max_heartrate') or 0)} bpm)")
    if a.get("average_cadence"):
        console.print(f"  Cadence:    {int(a['average_cadence'])} spm")

    splits = a.get("splits", [])
    if splits:
        console.print()
        console.print("[bold]Splits (km):[/bold]")
        for s in splits:
            hr_str = f"  HR {int(s['average_heartrate'])} bpm" if s.get("average_heartrate") else ""
            console.print(f"  km {s['split_number']:>2}  {s.get('pace', '—'):>9}{hr_str}")


@main.command()
def chat():
    """Chat with your AI running coach."""
    config = _get_config()

    if not config.db_path.exists():
        console.print("[yellow]No local database found. Run [cyan]coach setup[/cyan] first.[/yellow]")
        sys.exit(1)

    from .auth import get_valid_token
    from .coach import CoachSession
    from .sync import StravaClient

    # Load athlete profile for system prompt personalisation
    try:
        token = get_valid_token(config)
        strava = StravaClient(config)
        athlete = strava.get_athlete()
    except Exception:
        athlete = {}

    engine = create_engine_for(config.db_path)

    console.print(Panel(
        "[bold]Running Coach[/bold]\n"
        "[dim]Type your question and press Enter. Special commands: /quit, /reset, /sync[/dim]",
        style="cyan",
    ))
    if athlete.get("firstname"):
        console.print(f"[dim]Coaching: {athlete.get('firstname', '')} {athlete.get('lastname', '')}[/dim]\n")

    with engine.connect() as conn:
        session = CoachSession(config, conn)
        session.set_athlete(athlete)

        while True:
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye![/dim]")
                break

            if not user_input:
                continue

            if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
                console.print("[dim]Goodbye![/dim]")
                break

            if user_input.lower() == "/reset":
                session.reset()
                console.print("[dim]Conversation reset.[/dim]\n")
                continue

            if user_input.lower() == "/sync":
                console.print("[dim]Syncing new activities...[/dim]")
                result = sync_activities(config, full=False)
                console.print(f"[green]✓[/green] {result['message']}\n")
                continue

            with console.status("[dim]Thinking...[/dim]", spinner="dots"):
                try:
                    response = session.chat(user_input)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]\n")
                    continue

            console.print()
            console.print("[bold green]Coach:[/bold green]")
            console.print(Markdown(response))
            console.print()


if __name__ == "__main__":
    main()
