"""API client for the Minol tenant portal (SAP NetWeaver eMonitoring)."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    EMDATA_REST,
    J_SECURITY_CHECK_URL,
    LOGIN_URL,
    NUDATA_REST,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class MinolAuthError(Exception):
    """Raised when authentication with the Minol portal fails."""


class MinolConnectionError(Exception):
    """Raised when the Minol portal cannot be reached."""


class MinolApiClient:
    """Async client for the Minol eMonitoring portal.

    Authentication flow:
      1. GET the SAP NetWeaver login page to seed session cookies.
      2. POST credentials to ``j_security_check``.
      3. Verify MYSAPSSO2 cookie was issued.

    Data flow (for a *tenant* / Mieter user):
      1. GET ``EMData/getUserTenants`` → tenant list with ``userNumber``.
      2. POST ``EMData/getLayerInfo`` → available views & periods.
      3. POST ``EMData/readData`` (dashboard) → current consumption values.
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Login via SAP j_security_check.  Returns True on success."""
        session = self._ensure_session()

        try:
            # Seed SAP cookies.
            async with session.get(LOGIN_URL, allow_redirects=True):
                pass

            # Submit credentials.
            async with session.post(
                J_SECURITY_CHECK_URL,
                data={"j_user": self._username, "j_password": self._password},
                allow_redirects=True,
            ) as resp:
                # Check for the SSO cookie that SAP issues on success.
                cookie_names = {c.key for c in session.cookie_jar}
                if "MYSAPSSO2" not in cookie_names:
                    raise MinolAuthError(
                        "Authentication failed – no MYSAPSSO2 cookie received"
                    )

                # Extra safety: make sure we weren't bounced back to logon.
                final = str(resp.url).lower()
                if "j_security_check" in final:
                    raise MinolAuthError(
                        "Authentication failed – redirected back to login"
                    )

        except aiohttp.ClientError as err:
            raise MinolConnectionError(
                f"Cannot reach Minol portal: {err}"
            ) from err

        _LOGGER.debug("Minol authentication successful")
        return True

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _get_json(self, url: str, **kwargs: Any) -> Any:
        """GET *url* and return parsed JSON.  Re-authenticates once on 401/403."""
        return await self._request("GET", url, **kwargs)

    async def _post_json(self, url: str, payload: Any = None, **kwargs: Any) -> Any:
        """POST *url* with a JSON body and return parsed JSON."""
        return await self._request("POST", url, payload=payload, **kwargs)

    async def _request(
        self,
        method: str,
        url: str,
        payload: Any = None,
        **kwargs: Any,
    ) -> Any:
        session = self._ensure_session()

        for attempt in range(2):
            try:
                kw: dict[str, Any] = {"allow_redirects": True, **kwargs}
                if method == "POST" and payload is not None:
                    kw["data"] = json.dumps(payload)
                    kw["headers"] = {
                        "Content-Type": "application/json; charset=utf-8",
                    }

                async with session.request(method, url, **kw) as resp:
                    if resp.status in (401, 403) and attempt == 0:
                        _LOGGER.debug("Session expired, re-authenticating")
                        await self.authenticate()
                        continue

                    if resp.status != 200:
                        _LOGGER.error(
                            "Minol %s %s returned HTTP %s",
                            method,
                            url,
                            resp.status,
                        )
                        return None

                    text = await resp.text()
                    if not text.strip():
                        return None
                    return json.loads(text)

            except aiohttp.ClientError as err:
                if attempt == 0:
                    _LOGGER.debug("Request failed (%s), re-authenticating", err)
                    await self.authenticate()
                    continue
                raise MinolConnectionError(
                    f"Cannot fetch {url}: {err}"
                ) from err

        return None

    # ------------------------------------------------------------------
    # Public data endpoints
    # ------------------------------------------------------------------

    async def get_user_tenants(self) -> list[dict[str, Any]]:
        """Return the list of tenant units for the logged-in user."""
        data = await self._get_json(f"{EMDATA_REST}/getUserTenants")
        return data if isinstance(data, list) else []

    async def get_layer_info(
        self, user_num: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch available views and periods for the NE (tenant) layer."""
        selection = {
            "userNum": user_num,
            "layer": "NE",
            "scale": "CALMONTH",
            "chartRefUnit": "ABS",
            "refObject": "PREV_YEAR",
            "consType": "HEIZUNG",
            "dashBoardKey": "PE",
            "valuesInKWH": True,
        }
        return await self._post_json(f"{EMDATA_REST}/getLayerInfo", selection)

    async def get_dashboard(
        self, user_num: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch the dashboard overview (current + previous year per type)."""
        selection = {
            "userNum": user_num,
            "layer": "NE",
            "scale": "CALMONTH",
            "chartRefUnit": "ABS",
            "refObject": "DIN_AVG",
            "consType": "HEIZUNG",
            "dashBoardKey": "PE",
            "valuesInKWH": True,
            "dlgKey": "dashboard",
        }
        return await self._post_json(f"{EMDATA_REST}/readData", selection)

    async def get_consumption_for_view(
        self,
        user_num: str | None,
        view_key: str,
        cons_type: str,
    ) -> dict[str, Any] | None:
        """Fetch detailed consumption data for a specific view / type."""
        is_overview = view_key in ("100EH", "100KWH", "200", "dashboard")
        selection = {
            "userNum": user_num,
            "layer": "NE",
            "scale": "CALMONTH",
            "chartRefUnit": "ABS",
            "refObject": "DIN_AVG" if is_overview else "UPPER_LEVEL",
            "consType": cons_type,
            "dashBoardKey": "PE",
            "valuesInKWH": True,
            "dlgKey": view_key,
        }
        return await self._post_json(f"{EMDATA_REST}/readData", selection)

    async def get_all_data(self) -> dict[str, Any]:
        """Collect all data needed by the integration sensors.

        Returns a dict with ``tenants``, ``layer_info``, and ``dashboard``.
        """
        tenants = await self.get_user_tenants()
        user_num = tenants[0]["userNumber"] if tenants else None
        tenant_info = tenants[0] if tenants else {}

        layer_info = await self.get_layer_info(user_num)
        dashboard = await self.get_dashboard(user_num)

        return {
            "tenants": tenants,
            "tenant_info": tenant_info,
            "user_num": user_num,
            "layer_info": layer_info or {},
            "dashboard": dashboard or {},
        }
