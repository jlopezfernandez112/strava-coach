"""Configuration loading and validation."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass
class Config:
    strava_client_id: str
    strava_client_secret: str
    anthropic_api_key: str
    data_dir: Path
    db_path: Path
    tokens_path: Path


def load_config() -> Config:
    # Load .env from project root (parent of coach/)
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")

    missing = []
    client_id = os.getenv("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if not client_id:
        missing.append("STRAVA_CLIENT_ID")
    if not client_secret:
        missing.append("STRAVA_CLIENT_SECRET")
    if not anthropic_key:
        missing.append("ANTHROPIC_API_KEY")

    if missing:
        raise ConfigError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in your credentials."
        )

    data_dir = project_root / "data"
    return Config(
        strava_client_id=client_id,
        strava_client_secret=client_secret,
        anthropic_api_key=anthropic_key,
        data_dir=data_dir,
        db_path=data_dir / "coach.db",
        tokens_path=data_dir / "tokens.json",
    )


def ensure_data_dir(config: Config) -> None:
    config.data_dir.mkdir(exist_ok=True)
