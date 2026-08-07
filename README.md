# Minol Energy — Home Assistant Integration

<img src="custom_components/minol_energy/icon.png" alt="Minol Energy" width="100">

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz/)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

A custom [Home Assistant](https://www.home-assistant.io/) integration that reads
consumption data from the **Minol eMonitoring portal** using the same API as the
official Minol iOS/Android app.

Authentication uses the same Azure B2C OAuth2 flow as the official app.
Tokens are refreshed silently in the background — you only need to log in once.

---

## Features

- **Energy Dashboard compatible** — dedicated `*_energy_total` sensors carry `last_reset`, so period totals add up correctly in long-term statistics
- **Heating, hot water, and cold water** sensors with kWh and volume values
- **CO₂ tracking** — carbon intensity sensor for heating and hot water
- **Cost estimation** — configure energy prices to see estimated monthly costs
- **Configurable update interval** — 15 min to 24 h polling
- **Silent token refresh** — access tokens are renewed automatically; the refresh token is good for 14 days
- **Reauthentication flow** — HA prompts for a new login if the refresh token expires
- **Diagnostics** — export anonymized data for debugging
- **English and German** translations

---

## Sensors

For each service type available on your account (heating, hot water, cold water):

| Sensor | Unit | State class | Description |
|---|---|---|---|
| Heating Latest Month | kWh | `total` | Consumption of the latest billing period; resets to a low value when a new period starts |
| Heating Total | kWh | `total` | Same value as *Heating Latest Month* — use this one as the source in the Energy Dashboard |
| Heating CO₂ Latest Month | kg | `measurement` | CO₂ equivalent for heating |
| Hot Water Latest Month | kWh | `total` | Hot water energy consumption of the latest billing period |
| Hot Water Total | kWh | `total` | Energy-Dashboard source for hot water |
| Hot Water CO₂ Latest Month | kg | `measurement` | CO₂ equivalent for hot water |
| Cold Water Latest Month | m³ | `total` | Cold water volume consumption of the latest billing period |
| Cold Water Total | m³ | `total` | Energy-Dashboard source for cold water |

Which sensors appear depends on which services your property has metered.
Cost sensors are created automatically when a non-zero price is set in Options.

All consumption sensors report the value of a **whole billing period**, so the state drops
back at every period boundary. They therefore expose `last_reset` (the start of the period)
alongside `state_class: total`. That is what makes Home Assistant's statistics engine add
each new period's value to the long-term sum *in full* instead of only its increase over
the previous period — a 250 kWh month following a 300 kWh one would otherwise contribute
nothing to the total.

### Full history in the Energy Dashboard

The API keeps every monthly period since move-in, so the integration imports all of them
as **long-term statistics** on each refresh — your Energy Dashboard starts at your move-in
month, not at the day you installed this integration:

| Statistic | Unit |
|---|---|
| `minol_energy:heating_energy` | kWh |
| `minol_energy:hot_water_energy` | kWh |
| `minol_energy:cold_water_volume` | m³ |

Pick these in *Settings → Dashboards → Energy* (they appear in the source picker next to
regular entities). They are statistics only — no entity, no current state — and are the
better dashboard source than the `*_energy_total` sensors, which can only record what
happened while Home Assistant was running. Each month lands on the 1st at 00:00 UTC as a
single bucket, because monthly totals are all the API reports. Remove them again under
*Developer tools → Statistics* if you don't want them.

> **Upgrading from 0.7.x:** the `*_energy_total` sensors used `total_increasing` there,
> which silently under-counted whenever a period was larger than the one before it.
> Replayed against 19 months of real data this lost 43 % of the heating energy,
> 48 % of the hot water and 53 % of the cold water. Long-term statistics recorded
> under 0.7.x are wrong and can be corrected in *Developer tools → Statistics*.

---

## How it works

```
Home Assistant                          Minol backend
 ┌─────────────────┐   Bearer token    ┌──────────────────────────────────────┐
 │  Coordinator    │──────────────────►│ Mulesoft Experience API              │
 │  (polls 1/hr)   │                   │  GET /api/app/profiles               │
 │                 │◄──────────────────│  GET /api/app/billingUnit/{}/...      │
 └────────┬────────┘   JSON data       │    /masterdata                       │
          │                            │    /consumptions/availableData        │
     sensor entities                   │    /consumptions?startdate=…&enddate=…│
                                       └──────────────────────────────────────┘

 ┌─────────────────┐
 │  Azure B2C      │  OAuth2 Authorization Code + PKCE
 │  (minolauth)    │  access_token valid 1 h, refresh_token 14 days
 └─────────────────┘
```

---

## Installation

### Via HACS (recommended)

1. Open **HACS** in Home Assistant.
2. **Integrations** → three-dot menu → **Custom repositories**.
3. Enter the repository URL, category **Integration**, click **Add**.
4. Search for **Minol Energy** and click **Download**.
5. **Restart Home Assistant.**

### Manual

Copy `custom_components/minol_energy/` into your HA `config/custom_components/` directory and restart.

---

## Setup

The integration uses the same login flow as the Minol mobile app (Azure B2C OAuth2 with PKCE).
There is no username/password field — you authenticate via your browser once.

1. **Settings → Devices & Services → Add Integration → Minol Energy**
2. Click the login link shown in the setup form.
3. Sign in with your Minol account in the browser.
4. After signing in, the browser navigates to a Postman callback page. Copy the full URL from the address bar (it starts with `https://oauth.pstmn.io/v1/callback?code=…`).
5. Paste it into the field in HA and click **Submit**.

Tokens are stored in the config entry and refreshed automatically. You will only need to repeat this if you haven't used HA for more than 14 days.

---

## Options

After setup, click **Configure** on the integration to adjust:

| Option | Default | Description |
|---|---|---|
| Update interval | 60 min | How often to poll the Minol API (15–1440 min) |
| Heating price | 0.00 €/kWh | Price per kWh for heating cost estimation |
| Hot water price | 0.00 €/kWh | Price per kWh for hot water cost estimation |
| Cold water price | 0.00 €/m³ | Price per m³ for cold water cost estimation |

Setting a price to `0` disables the corresponding cost sensor.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"Cannot connect"** | Check your internet connection and that the Minol app works on your phone. |
| **"Authentication failed"** | Your session may have expired. Click **Re-authenticate** on the integration card. |
| **No sensors** | Your Minol account may not have eMonitoring enabled. Contact Minol customer support. |
| **Sensors show unknown** | No consumption data was found for the last 3 months. Check the Minol app. |

### Debug logging

Go to **Settings → System → Logs**, find **Minol Energy** in the integration list, and click **Enable debug logging**. No `configuration.yaml` changes needed.

Alternatively, add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.minol_energy: debug
```

Debug logs include every API request/response, token expiry times, and refresh attempts.

### Diagnostics

**Settings → Devices & Services → Minol Energy → three-dot menu → Download diagnostics**

Sensitive fields (tokens, email) are redacted automatically.

---

## Development

### Running live tests

The test suite makes real API calls. You need a valid token first:

```bash
uv run python scripts/get_token.py
```

The script opens the Minol B2C login URL. Sign in, copy the redirect URL from the browser
address bar, paste it when prompted, and press Enter. The script prints two `export` commands:

```bash
export MINOL_ACCESS_TOKEN="eyJ..."
export MINOL_REFRESH_TOKEN="eyJ..."
```

Run those, then execute the tests:

```bash
uv run pytest tests/test_api_live.py -v -s
```

Tests are automatically skipped when `MINOL_ACCESS_TOKEN` is not set or when running in CI.

---

## License

MIT
