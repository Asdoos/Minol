#!/usr/bin/env python3
"""Interactive OAuth2 token acquisition for Minol API testing.

Flow:
  1. Script opens the auth URL in your default browser automatically.
  2. Sign in to Minol — B2C redirects to msal<client_id>://auth/?code=…, which the
     browser cannot open.  Chrome/Edge log that URL in the developer console
     (F12, "Failed to launch 'msal…'"), Firefox shows it on an error page.
  3. Paste that URL (or the console line, or just the code) and press Enter.
  4. Tokens are exchanged and printed as export commands.

Usage:
    uv run python scripts/get_token.py

To use the tokens for live tests:
    export MINOL_ACCESS_TOKEN="eyJ..."
    export MINOL_REFRESH_TOKEN="eyJ..."
    uv run pytest tests/test_api_live.py -v -s
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import termios
import tty
from urllib.parse import urlencode

import aiohttp

from custom_components.minol_energy.config_flow import _extract_code_from_url
from custom_components.minol_energy.const import (
    B2C_AUTH_URL,
    B2C_CLIENT_ID,
    B2C_REDIRECT_URI,
    B2C_SCOPES,
    B2C_TOKEN_URL,
)


def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _build_auth_url(code_challenge: str, state: str) -> str:
    params = {
        "client_id": B2C_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": B2C_REDIRECT_URI,
        "scope": B2C_SCOPES,
        "state": state,
        "nonce": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return B2C_AUTH_URL + "?" + urlencode(params)


def _read_long_line(prompt: str) -> str:
    """Read a line from stdin in raw mode, bypassing the 4096-byte TTY buffer."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        chars: list[str] = []
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break
            if ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "".join(chars).strip()


async def _exchange_code(code: str, code_verifier: str) -> dict:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": B2C_REDIRECT_URI,
        "client_id": B2C_CLIENT_ID,
        "code_verifier": code_verifier,
        "scope": B2C_SCOPES,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            B2C_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                print(f"\n[ERROR] Token exchange failed (HTTP {resp.status}):")
                print(body[:500])
                sys.exit(1)
            return json.loads(body)


def main() -> None:
    code_verifier, code_challenge = _generate_pkce()
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    auth_url = _build_auth_url(code_challenge, state)

    print("=" * 72)
    print("Minol OAuth2 Token Acquisition")
    print("=" * 72)
    print()
    print("Open this URL in your browser and sign in:")
    print()
    print(auth_url)
    print()
    print("After signing in, the browser tries to open msal...://auth/?code=... and")
    print("fails. Chrome/Edge: open the developer console (F12) and copy the line")
    print("  \"Failed to launch 'msal...://auth/?code=...'\".")
    print("Firefox: copy the URL from the error page / address bar.")
    print("Paste it below (the whole line is fine) and press Enter.")
    print()
    redirect_url = _read_long_line("Paste redirect URL: ")

    code = _extract_code_from_url(redirect_url)
    if not code:
        print("\n[ERROR] No authorization code found in the URL.")
        sys.exit(1)

    print("Exchanging authorization code for tokens...")
    token_data = asyncio.run(_exchange_code(code, code_verifier))

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", "unknown")

    print(f"\n[OK] access_token received (expires in {expires_in}s)")
    print(f"     refresh_token: {'yes' if refresh_token else 'no'}")
    print()
    print("=" * 72)
    print("Export commands:")
    print("=" * 72)
    print()
    print(f'export MINOL_ACCESS_TOKEN="{access_token}"')
    if refresh_token:
        print(f'export MINOL_REFRESH_TOKEN="{refresh_token}"')
    print()
    print("Then run:  uv run pytest tests/test_api_live.py -v -s")
    print()


if __name__ == "__main__":
    main()
