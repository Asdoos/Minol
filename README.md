# Minol Energy - Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz/)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

A custom [Home Assistant](https://www.home-assistant.io/) integration that reads
consumption data from the **Minol eMonitoring** tenant portal
([webservices.minol.com](https://webservices.minol.com/)).

The portal runs on SAP NetWeaver. This integration authenticates via
`j_security_check`, then queries the internal REST API at
`/minol.com~kundenportal~em~web/rest/EMData` that the portal's SAPUI5
front-end uses.

---

## Sensors

For each consumption type available on your account, the following sensors are
created:

| Sensor | Example value | Description |
|---|---|---|
| Heating Current Year | 1175.42 kWh | Total heating consumption this year |
| Heating Previous Year | 1171.11 kWh | Total heating consumption last year |
| Heating per m² Current Year | 17.31 kWh/m² | Heating per square metre (current) |
| Heating per m² Previous Year | 17.25 kWh/m² | Heating per square metre (previous) |
| Heating DIN Average | 41.65 kWh/m² | DIN reference average for the building |
| Heating Building Share % | 12 % | Your share of the building's total |
| Hot Water Current Year | 345.35 kWh | Hot water energy this year |
| Hot Water Previous Year | 347.62 kWh | Hot water energy last year |
| Hot Water per m² Current Year | 5.09 kWh/m² | Hot water per m² |
| Hot Water per m² Previous Year | 5.12 kWh/m² | Hot water per m² (previous) |
| Hot Water DIN Average | 9.63 kWh/m² | DIN reference |
| Hot Water Building Share % | 12 % | Your share |
| Cold Water Current Year | 21.47 m³ | Cold water volume this year |
| Cold Water Previous Year | 20.60 m³ | Cold water volume last year |
| Cold Water per m² Current Year | 0.32 m³/m² | Cold water per m² |
| Cold Water per m² Previous Year | 0.30 m³/m² | Cold water per m² (previous) |
| Cold Water DIN Average | 0.37 m³/m² | DIN reference |
| Cold Water Building Share % | 15 % | Your share |
| Tenant Info | Fabrikstr. 33, ... | Address with attributes (name, floor, move-in) |

The exact set of sensors depends on which meter types your property has.

---

## How it works

```
Home Assistant                      Minol Portal (SAP NetWeaver)
 ┌──────────────┐    aiohttp        ┌───────────────────────────┐
 │ Coordinator  │ ─────────────────►│ j_security_check (login)  │
 │ (polls 1/hr) │                   │                           │
 │              │ GET getUserTenants│ → [{userNumber, addr...}] │
 │              │ POST getLayerInfo │ → {views, periods, scales} │
 │              │ POST readData     │ → {dashboard: [...]}      │
 └──────┬───────┘ (dashboard)       └───────────────────────────┘
        │
   19 sensor entities
```

---

## Installation

### Via HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations** > three-dot menu > **Custom repositories**.
3. Enter the repository URL, category **Integration**.
4. Click **Add**, then search for **Minol Energy** and click **Download**.
5. **Restart Home Assistant.**

### Manual

Copy `custom_components/minol_energy/` into your HA config directory and restart.

---

## Configuration

1. **Settings** > **Devices & Services** > **Add Integration** > **Minol Energy**.
2. Enter your e-mail and password (same as [webservices.minol.com](https://webservices.minol.com/)).
3. Done. Sensors appear automatically.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"Cannot connect"** | Verify you can log in at [webservices.minol.com](https://webservices.minol.com/) in Chrome. |
| **"Invalid username or password"** | The integration checks for the `MYSAPSSO2` cookie. If SAP doesn't issue it, credentials are wrong. |
| **No sensors / all unknown** | Your portal account may not have eMonitoring enabled. Contact Minol. |

### Debug logging

```yaml
logger:
  logs:
    custom_components.minol_energy: debug
```

---

## Reverse-engineered API reference

All endpoints are on `https://webservices.minol.com`.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `.../rest/EMData/getUserTenants` | - | `[{lgnr, nenr, name, userNumber, addr*...}]` |
| POST | `.../rest/EMData/getLayerInfo` | `{userNum, layer, scale, consType...}` | `{views, periods, scales, head...}` |
| POST | `.../rest/EMData/readData` | `{userNum, layer, dlgKey, consType...}` | `{table, chart, dashboard}` |
| GET | `.../rest/NuData/getShowInfoState` | - | `{result: bool}` |
| GET | `.../rest/NuData/getPushServiceState` | - | `{result: bool}` |

---

## License

MIT
