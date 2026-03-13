# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A [HACS](https://hacs.xyz/) custom integration for Home Assistant that reads consumption data (heating, hot water, cold water) from the **Minol eMonitoring portal** using the same API as the official Minol iOS/Android app. Requires HA ≥ 2024.1. No Python package dependencies — only `aiohttp`, which ships with Home Assistant.

## Development commands

There is no local test runner or build step. Development is done by copying `custom_components/minol_energy/` into a Home Assistant config directory (or a dev container) and restarting HA.

Linting (run from repo root):
```bash
ruff check custom_components/
ruff format custom_components/
```

Type checking:
```bash
pyright custom_components/
```

Tests:
```bash
uv run pytest tests/test_api_unit.py -v          # unit tests (no credentials needed)
uv run pytest tests/test_api_live.py -v -s       # live tests (requires MINOL_ACCESS_TOKEN)
```

## Architecture

All code lives in `custom_components/minol_energy/`. The integration follows the standard HA pattern: config entry → coordinator → sensor platform.

```
__init__.py        Entry setup/teardown. Creates MinolApiClient with stored OAuth2 tokens,
                   creates MinolDataCoordinator, forwards to PLATFORMS = [SENSOR].
                   Handles token persistence via on_tokens_refreshed callback.

coordinator.py     MinolDataCoordinator (DataUpdateCoordinator). Calls
                   client.get_all_data() on every poll, maps MinolAuthError →
                   ConfigEntryAuthFailed (triggers HA reauth flow) and
                   MinolConnectionError → UpdateFailed.

api.py             MinolApiClient — the only file that makes HTTP requests.
                   Takes OAuth2 tokens (access_token, refresh_token) obtained via
                   the config flow. Silently refreshes the access_token using the
                   refresh_token when needed.
                   get_all_data() calls /profiles, /masterdata, /consumptions/availableData,
                   and /consumptions for the last 3 months.
                   _request() retries once on 401/403 via token refresh.

sensor.py          Builds sensor entities from coordinator.data. Creates energy/volume,
                   CO₂, and (optional) cost sensors per active service type.

config_flow.py     ConfigFlow + OptionsFlow. OAuth2 Authorization Code + PKCE flow:
                   HA builds the auth URL, user logs in via browser, pastes the
                   resulting redirect URL (https://oauth.pstmn.io/v1/callback?code=…)
                   back into HA. HA exchanges the code for tokens and stores them.
                   Options: scan_interval, heating/hot_water/cold_water prices.

const.py           All constants. Key ones: B2C_AUTH_URL, B2C_TOKEN_URL (Azure B2C),
                   API_BASE_URL (Mulesoft), API_CLIENT_ID/SECRET, B2C_CLIENT_ID/SECRET.

diagnostics.py     Async diagnostics export; redacts tokens and personal fields
                   (userID, email, name, address) before returning.
```

## Authentication

The app uses **Azure AD B2C OAuth2 Authorization Code + PKCE** via the Minol mobile app's B2C tenant (`minolauth.b2clogin.com`). The redirect URI is `https://oauth.pstmn.io/v1/callback` (the Postman OAuth2 callback, registered in the B2C app alongside the native app scheme).

`config_flow.py` auth flow:
1. HA generates a PKCE `code_verifier` / `code_challenge` and builds an authorization URL.
2. User opens the URL in their browser and logs in with their Minol account.
3. B2C redirects to `https://oauth.pstmn.io/v1/callback?code=…`
4. User copies that full URL and pastes it into HA.
5. HA extracts the `code` and POSTs to `B2C_TOKEN_URL` to exchange it for `access_token` + `refresh_token`.
6. Tokens stored in config entry; access token (~1 h TTL) is silently refreshed using the refresh token (~14 days).

## API data shape

`get_all_data()` returns:
```python
{
    "profile": {...},              # from GET /profiles → data[0]
    "billing_unit_id": "...",      # profile["billingUnit"]
    "residential_unit_id": "...",  # profile["residentialUnitReference"]["residentialUnitID"]
    "masterdata": {...},           # from GET /billingUnit/{bu}/residentialUnit/{ru}/masterdata
    "latest_consumption": {...},   # most recent consumption period with UVI_AVAILABLE status
    "available_periods": [...],    # from GET .../consumptions/availableData
}
```

Consumption periods contain a `consumptions` list, one entry per service code:
- `"100"` = Heating (HEIZUNG)
- `"200"` = Hot Water (WARMWASSER)
- `"300"` = Cold Water (KALTWASSER)

Each entry has `energyValue` (kWh or m³), `serviceValue` (raw meter unit), `co2kg`, `estimated`, etc.
