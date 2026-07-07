"""Live integration tests for the Minol mobile app API (Mulesoft backend).

These tests require a valid OAuth2 access token obtained via the Minol app's
Azure B2C login flow.  Use ``scripts/get_token.py`` to obtain tokens
interactively, then export them as environment variables:

    export MINOL_ACCESS_TOKEN="eyJ..."
    export MINOL_REFRESH_TOKEN="0.A..."
    uv run pytest tests/test_api_live.py -v -s

Tests are automatically skipped in CI (``CI=true``) and when the token
env var is absent.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from custom_components.minol_energy.api import MinolApiClient
from custom_components.minol_energy.const import SERVICE_COLD_WATER, SERVICE_HEATING, SERVICE_HOT_WATER

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_ACCESS_TOKEN = os.environ.get("MINOL_ACCESS_TOKEN")
_REFRESH_TOKEN = os.environ.get("MINOL_REFRESH_TOKEN")
_IN_CI = os.environ.get("CI") == "true"

pytestmark = pytest.mark.skipif(
    _IN_CI or not _ACCESS_TOKEN,
    reason=(
        "Live tests require MINOL_ACCESS_TOKEN env var and must not run in CI. "
        "Run scripts/get_token.py to obtain a token."
    ),
)


def _make_client() -> MinolApiClient:
    return MinolApiClient(
        access_token=_ACCESS_TOKEN,
        refresh_token=_REFRESH_TOKEN,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_profiles_returns_list() -> None:
    """get_profiles() returns a non-empty list with the expected profile keys."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        assert isinstance(profiles, list), f"Expected list, got {type(profiles)}"
        assert len(profiles) > 0, "Expected at least one profile"
        profile = profiles[0]
        print(f"\nProfile: {profile}")
        assert "billingUnit" in profile, "Profile missing billingUnit"
        assert "residentialUnitReference" in profile, "Profile missing residentialUnitReference"
        assert "userID" in profile, "Profile missing userID"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_available_periods() -> None:
    """get_available_periods() returns a list of period dicts."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        periods = await client.get_available_periods(bu, ru)
        print(f"\nAvailable periods ({len(periods)}): {periods[:3]}")
        assert isinstance(periods, list)
        if periods:
            assert "period" in periods[0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_masterdata() -> None:
    """get_masterdata() returns billing period information."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        master = await client.get_masterdata(bu, ru)
        print(f"\nMasterdata keys: {list(master.keys()) if master else 'None'}")
        assert master is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_consumptions() -> None:
    """get_consumptions() returns a list of period consumption objects."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        now = datetime.now(timezone.utc)
        startdate = now.replace(day=1, month=1).strftime("%Y-%m-%d")
        enddate = now.strftime("%Y-%m-%d")

        consumptions = await client.get_consumptions(bu, ru, startdate, enddate)
        print(f"\nConsumption periods: {len(consumptions)}")
        if consumptions:
            period = consumptions[-1]
            print(f"Latest period: {period.get('period')}")
            print(f"Services: {[c.get('service') for c in period.get('consumptions', [])]}")
            for cons in period.get("consumptions", []):
                print(
                    f"  Service {cons['service']}: "
                    f"energy={cons.get('energyValue')} {cons.get('energyUnit')}, "
                    f"raw={cons.get('serviceValue')} {cons.get('serviceUnit')}, "
                    f"co2={cons.get('co2kg')} kg"
                )
        assert isinstance(consumptions, list)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_all_data_has_expected_keys() -> None:
    """get_all_data() returns a dict with all keys the sensors rely on."""
    client = _make_client()
    try:
        data = await client.get_all_data()
        print(f"\nData keys: {list(data.keys())}")

        for key in (
            "profile",
            "billing_unit_id",
            "residential_unit_id",
            "masterdata",
            "latest_consumption",
            "available_periods",
        ):
            assert key in data, f"Missing key: {key}"

        print(f"Billing unit: {data['billing_unit_id']}")
        print(f"Residential unit: {data['residential_unit_id']}")
        print(f"Available periods: {len(data['available_periods'])}")
        latest = data["latest_consumption"]
        print(f"Latest period: {latest.get('period')} status={latest.get('statusOverall')}")

        for svc_code, svc_name in [
            (SERVICE_HEATING, "Heating"),
            (SERVICE_HOT_WATER, "Hot Water"),
            (SERVICE_COLD_WATER, "Cold Water"),
        ]:
            val = MinolApiClient.get_service_value(latest, svc_code)
            print(f"  {svc_name}: {val}")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_devices_in_get_all_data() -> None:
    """Diagnose whether get_all_data() picks a latest_consumption that has devices."""
    client = _make_client()
    try:
        # --- get_all_data() path (3-month window) ---
        data = await client.get_all_data()
        latest = data["latest_consumption"]
        print(f"\n=== get_all_data() latest period ===")
        print(f"Period : {latest.get('period')}")
        print(f"Status : {latest.get('statusOverall')}")
        has_devices = False
        for cons in latest.get("consumptions", []):
            devices = cons.get("devices", [])
            rooms = [d.get("room") for d in devices if d.get("room")]
            print(f"  service {cons['service']}: {len(devices)} device(s), rooms={rooms}")
            if devices:
                has_devices = True
        print(f"Has devices: {has_devices}")

        # --- Full 1-year window: check every period for devices ---
        profiles = await client.get_profiles()
        bu = profiles[0]["billingUnit"]
        ru = profiles[0]["residentialUnitReference"]["residentialUnitID"]
        now = datetime.now(timezone.utc)
        start = now.replace(year=now.year - 1, month=1, day=1).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        all_periods = await client.get_consumptions(bu, ru, startdate=start, enddate=end)

        print(f"\n=== All periods in 1-year window ({len(all_periods)} total) ===")
        for p in all_periods:
            devices_in_period = sum(
                len(c.get("devices", [])) for c in p.get("consumptions", [])
            )
            print(
                f"  {p.get('period'):12s}  status={p.get('statusOverall'):20s}"
                f"  devices={devices_in_period}"
            )

        if not has_devices:
            print(
                "\nWARNING: get_all_data() selected a period WITHOUT devices."
                " Room sensors will not be created until a period with devices"
                " appears in the 3-month window."
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_masterdata_full_dump() -> None:
    """Dump the full masterdata response to understand the rooms structure."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]
        master = await client.get_masterdata(bu, ru)
        print(f"\nFull masterdata:\n{json.dumps(master, indent=2, ensure_ascii=False)}")
        assert master is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_explore_room_endpoints() -> None:
    """Probe potential room-level API endpoints to discover the rooms structure."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        base = f"/billingUnit/{bu}/residentialUnit/{ru}"
        candidates = [
            f"{base}/rooms",
            f"{base}/devices",
            f"{base}/meters",
            f"{base}/allocators",
            f"{base}/service/100/rooms",
            f"{base}/service/100/devices",
            f"{base}/service/100/meters",
        ]

        for path in candidates:
            result = await client._get(path)
            status = "OK GOT DATA" if result else "-- empty/None"
            print(f"\n{status}: GET {path}")
            if result:
                print(json.dumps(result, indent=2, ensure_ascii=False)[:500])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_consumptions_full_dump() -> None:
    """Dump a full consumption period to see if room-level data is embedded."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        now = datetime.now(timezone.utc)
        start = now.replace(year=now.year - 1, month=1, day=1).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        consumptions = await client.get_consumptions(bu, ru, startdate=start, enddate=end)
        print(f"\nTotal periods: {len(consumptions)}")
        if consumptions:
            print(f"\nLatest period full dump:\n{json.dumps(consumptions[-1], indent=2, ensure_ascii=False)}")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_explore_room_name_endpoints() -> None:
    """Probe API endpoints that might return human-readable room names."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]

        base_bu = f"/billingUnit/{bu}"
        base_ru = f"{base_bu}/residentialUnit/{ru}"
        candidates = [
            f"{base_bu}/rooms",
            f"{base_bu}/residentialUnit/{ru}/rooms",
            f"{base_ru}/roomNames",
            f"{base_ru}/room-names",
            f"{base_ru}/roomdetails",
            f"{base_ru}/roomDetails",
            f"{base_ru}/consumptions/rooms",
            "/rooms",
            f"/residentialUnit/{ru}/rooms",
            f"{base_ru}/service/100/roomdetails",
            f"{base_ru}/devices",
            f"{base_ru}/devicedetails",
        ]

        for path in candidates:
            result = await client._get(path)
            if result:
                print(f"\nOK: GET {path}")
                print(json.dumps(result, indent=2, ensure_ascii=False)[:600])
            else:
                print(f"404: GET {path}")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_explore_room_name_endpoints2() -> None:
    """Second round: probe available_periods detail, installation, and query variants."""
    client = _make_client()
    try:
        profiles = await client.get_profiles()
        profile = profiles[0]
        bu = profile["billingUnit"]
        ru = profile["residentialUnitReference"]["residentialUnitID"]
        base = f"/billingUnit/{bu}/residentialUnit/{ru}"

        # 1) Check availableData full response
        raw_avail = await client._get(f"{base}/consumptions/availableData")
        print(f"\navailableData response keys: {list(raw_avail.keys()) if isinstance(raw_avail, dict) else 'list'}")
        if isinstance(raw_avail, dict):
            print(json.dumps(raw_avail, indent=2, ensure_ascii=False)[:800])

        # 2) Other path guesses
        more = [
            f"{base}/installation",
            f"{base}/setup",
            f"{base}/configuration",
            f"{base}/consumptions/devices",
            f"{base}/consumptions/2026-02",
            f"{base}/consumptions/2025-12",
        ]
        for path in more:
            result = await client._get(path)
            if result:
                print(f"\nOK: GET {path}")
                print(json.dumps(result, indent=2, ensure_ascii=False)[:600])
            else:
                print(f"404: {path}")

        # 3) consumptions with extra params
        now = datetime.now(timezone.utc)
        start = now.replace(year=now.year - 1, month=1, day=1).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        result_with_rooms = await client._request(
            "GET",
            f"{base}/consumptions",
            params={"startdate": start, "enddate": end, "includeRooms": "true"},
        )
        if result_with_rooms and isinstance(result_with_rooms, list):
            print(f"\nconsumptions?includeRooms=true keys sample:")
            print(json.dumps(result_with_rooms[-1], indent=2, ensure_ascii=False)[:400])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_token_refresh() -> None:
    """Verify the token refresh callback fires when tokens are refreshed."""
    if not _REFRESH_TOKEN:
        pytest.skip("MINOL_REFRESH_TOKEN not set")

    refreshed: list[tuple[str, str | None, int]] = []

    client = MinolApiClient(
        access_token=_ACCESS_TOKEN,
        refresh_token=_REFRESH_TOKEN,
        on_tokens_refreshed=lambda a, r, exp: refreshed.append((a, r, exp)),
    )
    try:
        # Force a "token expired" scenario by corrupting the access token
        client._access_token = "invalid.token.here"
        # _request will get a 401, then try to refresh using the valid refresh token
        profiles = await client.get_profiles()
        if profiles:
            print(f"\nToken refresh worked: {len(profiles)} profile(s) returned")
            print(f"Refresh callback fired: {len(refreshed)} time(s)")
            assert len(refreshed) > 0, "Token refresh callback was never called"
        else:
            # If the API returned empty after refresh, something else is wrong
            print("No profiles returned after token refresh (refresh may have failed)")
    finally:
        await client.close()
