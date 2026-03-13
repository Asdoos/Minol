"""Unit tests for MinolApiClient (OAuth2 token-based client).

All HTTP traffic is mocked — no real network calls are made.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.minol_energy.api import MinolApiClient, MinolAuthError
from custom_components.minol_energy.config_flow import (
    _compute_code_challenge,
    _extract_code_from_url,
    _generate_code_verifier,
    _get_email_from_token,
)
from custom_components.minol_energy.const import (
    SERVICE_COLD_WATER,
    SERVICE_HEATING,
    SERVICE_HOT_WATER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resp(body: str | dict, status: int = 200) -> MagicMock:
    """Async-context-manager mock for an aiohttp response."""
    resp = MagicMock()
    resp.status = status
    text_value = json.dumps(body) if isinstance(body, dict) else body

    async def _text():
        return text_value

    resp.text = _text

    cm = MagicMock()

    async def _aenter(_self):
        return resp

    async def _aexit(_self, *args):
        return False

    cm.__aenter__ = _aenter
    cm.__aexit__ = _aexit
    return cm


# ---------------------------------------------------------------------------
# get_service_value
# ---------------------------------------------------------------------------


class TestGetServiceValue:
    def _period(self, services: list[dict]) -> dict:
        return {"consumptions": services}

    def test_returns_energy_value(self):
        period = self._period([
            {"service": SERVICE_HEATING, "energyValue": "123.45"},
        ])
        assert MinolApiClient.get_service_value(period, SERVICE_HEATING) == 123.45

    def test_returns_service_value_field(self):
        period = self._period([
            {"service": SERVICE_HOT_WATER, "serviceValue": "7.2"},
        ])
        result = MinolApiClient.get_service_value(
            period, SERVICE_HOT_WATER, field="serviceValue"
        )
        assert result == 7.2

    def test_returns_none_when_service_absent(self):
        period = self._period([
            {"service": SERVICE_HEATING, "energyValue": "10"},
        ])
        assert MinolApiClient.get_service_value(period, SERVICE_COLD_WATER) is None

    def test_returns_none_when_field_absent(self):
        period = self._period([
            {"service": SERVICE_HEATING},
        ])
        assert MinolApiClient.get_service_value(period, SERVICE_HEATING) is None

    def test_empty_consumptions(self):
        assert MinolApiClient.get_service_value({}, SERVICE_HEATING) is None

    def test_integer_value_coerced_to_float(self):
        period = self._period([
            {"service": SERVICE_COLD_WATER, "energyValue": 5},
        ])
        result = MinolApiClient.get_service_value(period, SERVICE_COLD_WATER)
        assert isinstance(result, float)
        assert result == 5.0


# ---------------------------------------------------------------------------
# Token expiry helpers
# ---------------------------------------------------------------------------


class TestTokenExpiry:
    def test_no_expiry_set_returns_false(self):
        client = MinolApiClient(access_token="tok")
        assert client._is_token_expired() is False

    def test_future_expiry_returns_false(self):
        client = MinolApiClient(access_token="tok")
        client.set_token_expiry(3600)
        assert client._is_token_expired() is False

    def test_past_expiry_returns_true(self):
        client = MinolApiClient(access_token="tok")
        # Manually set expiry to the past
        client._token_expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert client._is_token_expired() is True

    def test_within_60s_buffer_returns_true(self):
        client = MinolApiClient(access_token="tok")
        # Expires in 30 seconds — within the 60-second safety margin
        client._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert client._is_token_expired() is True


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


class TestRefreshAccessToken:
    async def test_no_refresh_token_returns_false(self):
        client = MinolApiClient(access_token="tok", refresh_token=None)
        result = await client._refresh_access_token()
        assert result is False

    async def test_successful_refresh_updates_tokens(self):
        client = MinolApiClient(access_token="old", refresh_token="refresh_tok")

        token_response = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }
        session = MagicMock()
        session.post = MagicMock(return_value=_make_resp(token_response, status=200))

        refreshed: list[tuple[str, str | None]] = []
        client._on_tokens_refreshed = lambda a, r: refreshed.append((a, r))

        with patch.object(client, "_ensure_session", return_value=session):
            result = await client._refresh_access_token()

        assert result is True
        assert client._access_token == "new_access"
        assert client._refresh_token == "new_refresh"
        assert refreshed == [("new_access", "new_refresh")]

    async def test_failed_refresh_returns_false(self):
        client = MinolApiClient(access_token="old", refresh_token="refresh_tok")

        error_body = {"error": "invalid_grant", "error_description": "Token expired"}
        session = MagicMock()
        session.post = MagicMock(return_value=_make_resp(error_body, status=400))

        with patch.object(client, "_ensure_session", return_value=session):
            result = await client._refresh_access_token()

        assert result is False
        assert client._access_token == "old"

    async def test_missing_access_token_in_response_returns_false(self):
        client = MinolApiClient(access_token="old", refresh_token="rt")
        session = MagicMock()
        session.post = MagicMock(return_value=_make_resp({"no_token_here": True}))

        with patch.object(client, "_ensure_session", return_value=session):
            result = await client._refresh_access_token()

        assert result is False


# ---------------------------------------------------------------------------
# Config flow helpers (pure functions — no mocking needed)
# ---------------------------------------------------------------------------


class TestExtractCodeFromUrl:
    def test_extracts_code(self):
        url = "https://oauth.pstmn.io/v1/callback?code=ABC123&state=xyz"
        assert _extract_code_from_url(url) == "ABC123"

    def test_returns_none_when_no_code(self):
        url = "https://oauth.pstmn.io/v1/callback?state=xyz"
        assert _extract_code_from_url(url) is None

    def test_handles_empty_string(self):
        assert _extract_code_from_url("") is None

    def test_handles_whitespace(self):
        url = "  https://oauth.pstmn.io/v1/callback?code=XYZ  "
        assert _extract_code_from_url(url) == "XYZ"


class TestPkce:
    def test_verifier_is_url_safe_base64(self):
        verifier = _generate_code_verifier()
        assert verifier
        # Should only contain URL-safe base64 chars (no padding)
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in verifier)

    def test_challenge_is_deterministic(self):
        challenge1 = _compute_code_challenge("my_verifier")
        challenge2 = _compute_code_challenge("my_verifier")
        assert challenge1 == challenge2

    def test_different_verifiers_produce_different_challenges(self):
        assert _compute_code_challenge("v1") != _compute_code_challenge("v2")


class TestGetEmailFromToken:
    def _make_token(self, claims: dict) -> dict:
        payload = base64.urlsafe_b64encode(
            json.dumps(claims).encode()
        ).rstrip(b"=").decode()
        return {"access_token": f"header.{payload}.sig"}

    def test_extracts_email_field(self):
        token_data = self._make_token({"email": "user@example.com"})
        assert _get_email_from_token(token_data) == "user@example.com"

    def test_falls_back_to_emails_array(self):
        token_data = self._make_token({"emails": ["list@example.com"]})
        assert _get_email_from_token(token_data) == "list@example.com"

    def test_falls_back_to_preferred_username(self):
        token_data = self._make_token({"preferred_username": "pref@example.com"})
        assert _get_email_from_token(token_data) == "pref@example.com"

    def test_returns_none_for_invalid_token(self):
        assert _get_email_from_token({"access_token": "not.a.jwt"}) is None

    def test_returns_none_for_empty(self):
        assert _get_email_from_token({}) is None
