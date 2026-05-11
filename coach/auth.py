"""Strava OAuth2 authentication — one-time browser flow + token refresh."""
from __future__ import annotations

import json
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .config import Config

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
CALLBACK_PORT = 8080
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"


@dataclass
class TokenStore:
    access_token: str
    refresh_token: str
    expires_at: int   # Unix timestamp
    athlete_id: int


def load_tokens(path: Path) -> TokenStore | None:
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return TokenStore(**data)


def save_tokens(store: TokenStore, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(asdict(store), f, indent=2)


def is_expired(store: TokenStore) -> bool:
    return time.time() >= store.expires_at - 60  # 60s buffer


def refresh_access_token(store: TokenStore, config: Config) -> TokenStore:
    resp = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": config.strava_client_id,
            "client_secret": config.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": store.refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    new_store = TokenStore(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=body["expires_at"],
        athlete_id=store.athlete_id,
    )
    return new_store


def run_oauth_flow(config: Config) -> TokenStore:
    """
    Opens the Strava authorization page in the browser.
    Starts a temporary local HTTP server to catch the OAuth callback.
    Exchanges the auth code for tokens.
    """
    auth_url = (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={config.strava_client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&approval_prompt=auto"
    )

    # Shared container for the callback result
    result: dict = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/callback":
                params = parse_qs(parsed.query)
                if "code" in params:
                    result["code"] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h2>Authorization successful!</h2>"
                        b"<p>You can close this tab and return to the terminal.</p></body></html>"
                    )
                else:
                    result["error"] = params.get("error", ["unknown"])[0]
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress default server logging

    server = HTTPServer(("localhost", CALLBACK_PORT), CallbackHandler)
    server.timeout = 120  # wait up to 2 minutes for user to authorize

    print(f"\nOpening Strava authorization in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Handle one request (the callback)
    server.handle_request()
    server.server_close()

    if "error" in result:
        raise RuntimeError(f"Strava authorization failed: {result['error']}")
    if "code" not in result:
        raise RuntimeError("No authorization code received. Did you authorize the app?")

    # Exchange code for tokens
    resp = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": config.strava_client_id,
            "client_secret": config.strava_client_secret,
            "code": result["code"],
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()

    store = TokenStore(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=body["expires_at"],
        athlete_id=body["athlete"]["id"],
    )
    return store


def get_valid_token(config: Config) -> str:
    """
    Load stored tokens, refresh if expired, run OAuth flow if no tokens exist.
    Returns a valid access token string.
    """
    store = load_tokens(config.tokens_path)

    if store is None:
        print("No stored tokens found. Starting authorization flow...")
        store = run_oauth_flow(config)
        save_tokens(store, config.tokens_path)
        print("Authorization successful. Tokens saved.")
        return store.access_token

    if is_expired(store):
        store = refresh_access_token(store, config)
        save_tokens(store, config.tokens_path)

    return store.access_token
