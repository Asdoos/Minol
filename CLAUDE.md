# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A [HACS](https://hacs.xyz/) custom integration for Home Assistant that reads consumption data (heating, hot water, cold water) from the **Minol eMonitoring portal** using the same API as the official Minol iOS/Android app. Requires HA ≥ 2024.1. No Python package dependencies — only `aiohttp`, which ships with Home Assistant.

## Development commands

There is no local test runner or build step. Development is done by copying `custom_components/minol_energy/` into a Home Assistant config directory (or a dev container) and restarting HA.

Linting (run from repo root, also runs in CI on every push/PR):
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

To get a live token for testing:
```bash
uv run python scripts/get_token.py
# Follow prompts, then export the printed MINOL_ACCESS_TOKEN / MINOL_REFRESH_TOKEN
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
                   MinolConnectionError → UpdateFailed. Also feeds every period
                   to statistics.async_import_history(); failures there are
                   logged, never propagated (they would kill all sensors).

statistics.py      Imports the whole consumption history as *external* long-term
                   statistics (minol_energy:heating_energy, :hot_water_energy,
                   :cold_water_volume) so the Energy Dashboard shows data from
                   before the integration was installed. Re-imports everything
                   on every poll — rows are keyed by start time, so months are
                   updated instead of duplicated.

api.py             MinolApiClient — the only file that makes HTTP requests.
                   Takes OAuth2 tokens (access_token, refresh_token) obtained via
                   the config flow. Silently refreshes the access_token using the
                   refresh_token when needed.
                   get_all_data() calls /profiles, /masterdata, /consumptions/availableData,
                   and /consumptions for the last 3 months.
                   _request() retries once on 401/403 via token refresh.

sensor.py          Builds sensor entities from coordinator.data. Creates energy/volume,
                   CO₂ (heating and hot water only — not cold water), and (optional)
                   cost sensors per active service type.

config_flow.py     ConfigFlow + OptionsFlow. OAuth2 Authorization Code + PKCE flow:
                   HA builds the auth URL, user logs in via browser, pastes the
                   resulting redirect URL (msal<client_id>://auth/?code=…, copied
                   from the browser console) back into HA. HA exchanges the code for tokens and stores them.
                   Options: scan_interval, heating/hot_water/cold_water prices.

const.py           All constants. Key ones: B2C_AUTH_URL, B2C_TOKEN_URL (Azure B2C),
                   API_BASE_URL (Mulesoft), API_CLIENT_ID/SECRET, B2C_CLIENT_ID, B2C_REDIRECT_URI.

diagnostics.py     Async diagnostics export; redacts tokens and personal fields
                   (userID, email, name, address) before returning.
```

## Authentication

The app uses **Azure AD B2C OAuth2 Authorization Code + PKCE** via the Minol mobile app's B2C tenant (`minolauth.b2clogin.com`). It acts exactly like the app: **public client**, redirect URI `msal<B2C_CLIENT_ID>://auth` (MSAL native scheme), **no client secret**. Sending a secret is rejected (`AADB2C90084`). The former Postman callback (`https://oauth.pstmn.io/v1/callback`) + client secret path stopped working in Nov 2026 (`AADB2C90085` at the token endpoint, even though `/authorize` still accepts that URI).

`config_flow.py` auth flow:
1. HA generates a PKCE `code_verifier` / `code_challenge` and builds an authorization URL.
2. User opens the URL in their browser and logs in with their Minol account.
3. B2C redirects to `msal<client_id>://auth/?code=…`. The browser can't open that scheme; Chrome/Edge log it in the console (`Failed to launch 'msal…'`), Firefox shows it on an error page.
4. User pastes that URL, the console line or the bare code into HA; `_extract_code_from_url()` handles all three.
5. HA POSTs the `code` + PKCE verifier (no secret) to `B2C_TOKEN_URL` to get `access_token` + `refresh_token`.
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

A period dict has exactly these keys: `period`, `statusOverall`, `consumptions`,
`benchmarks`, `normalisedBenchmarks` — there is **no** start/end date field.

`period` labels one calendar month, but the two endpoints disagree on how:
- `/consumptions` → its **last** day, full ISO: `"2026-07-31T00:00:00Z"` = July
- `/consumptions/availableData` → its **first** day, date only: `"2023-07-01"`

Values are per month, not cumulative meter readings, so every sensor needs
`state_class: total` plus `last_reset` (`MinolApiClient.get_period_start()`,
which normalises both formats to the 1st of the month). With `total_increasing`
HA only adds the *increase* over the previous month and silently drops ~45 % of
the consumption — see the 0.7.2 fix.
