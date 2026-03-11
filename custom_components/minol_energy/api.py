import asyncio
import http.cookiejar
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import urlparse

import aiohttp
from yarl import URL

from .const import (
    B2C_ENTRY_URL,
    BASE_URL,
    EMDATA_REST,
    NUDATA_REST,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class MinolAuthError(Exception):
    """Raised when authentication with the Minol portal fails."""


class MinolConnectionError(Exception):
    """Raised when the Minol portal cannot be reached."""


def _extract_b2c_settings(html: str) -> dict[str, Any]:
    """Extract the Azure B2C page settings JSON from the login page HTML.

    B2C login pages embed a JSON config object in a script tag.  The exact
    variable name has changed over time; we try several known patterns:

    * ``$Config={...}`` (older B2C pages)
    * ``var SETTINGS = {...}`` (intermediate variant)
    * ``window.SETTINGS = {...}`` (current Minol B2C page as of 2025/2026)

    For robustness the JSON body is extracted with a brace-counter rather than
    a character-class regex, so embedded ``<`` characters don't cause failures.
    """
    # Patterns that precede the opening '{' of the settings object.
    _PREFIXES = (
        r"\$Config\s*=\s*",
        r"var\s+SETTINGS\s*=\s*",
        r"window\.SETTINGS\s*=\s*",
    )

    for prefix in _PREFIXES:
        # Find the start of the JSON object.
        m = re.search(prefix, html)
        if not m:
            continue
        start = m.end()
        if start >= len(html) or html[start] != "{":
            continue

        # Walk forward counting braces to find the matching '}'.
        depth = 0
        end = start
        for i, ch in enumerate(html[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        else:
            continue  # unmatched braces – try next pattern

        try:
            return json.loads(html[start:end])  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            continue

    return {}


def _b2c_base_url(url: str) -> str:
    """Return ``scheme://host/tenant/policy`` from a full B2C URL.

    Example::

        https://minolauth.b2clogin.com/minolauth.onmicrosoft.com/B2C_1A_XYZ/api/...
        → https://minolauth.b2clogin.com/minolauth.onmicrosoft.com/B2C_1A_XYZ
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        return f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/{parts[1]}"
    return f"{parsed.scheme}://{parsed.netloc}"


def _b2c_login_sync(username: str, password: str) -> dict[str, str]:
    """Perform B2C login synchronously using urllib.

    Azure B2C security checks (specifically for SelfAsserted endpoint) often
    conflict with how aiohttp handles cookies (quote preservation) and URL
    encoding in query parameters. urllib is more permissive/standard in ways
    that Azure B2C expects.
    """
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.addheaders = [("User-Agent", USER_AGENT)]

    # 1. Start SAML login flow → get redirected to B2C login page
    try:
        resp = opener.open(B2C_ENTRY_URL)
        b2c_page_url = resp.url
        html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        raise MinolAuthError(f"Failed to reach B2C login page: {exc}") from exc

    # 2. Extract settings (CSRF, TransID, Policy)
    settings = _extract_b2c_settings(html)
    if not settings:
        raise MinolAuthError("Could not parse B2C settings from login page")

    csrf = settings.get("csrf", "")
    trans_id = settings.get("transId", "")
    policy = settings.get("policy", "")

    # Fallback for policy extraction from URL
    if not policy:
        parsed = urlparse(b2c_page_url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            policy = parts[1]

    if not (csrf and trans_id and policy):
        raise MinolAuthError("Incomplete B2C settings found")

    base = _b2c_base_url(b2c_page_url)

    # 3. POST credentials to SelfAsserted
    self_asserted_url = f"{base}/SelfAsserted?tx={trans_id}&p={policy}"
    post_data = urllib.parse.urlencode(
        {
            "request_type": "RESPONSE",
            "signInName": username,
            "password": password,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        self_asserted_url,
        data=post_data,
        headers={
            "X-CSRF-TOKEN": csrf,
            "Referer": b2c_page_url,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )

    try:
        resp = opener.open(req)
        body = resp.read().decode("utf-8")
        result = json.loads(body)
    except Exception as exc:
        _LOGGER.debug(f"B2C credential post failed: {exc}")
        raise MinolAuthError(f"B2C credential post failed: {exc}") from exc

    if result.get("status") != "200":
        msg = result.get("message", "Invalid username or password")
        raise MinolAuthError(f"Authentication failed: {msg}")

    # 4. Finalize/Confirm login → returns first SAML POST form
    confirmed_url = (
        f"{base}/api/CombinedSigninAndSignup/confirmed"
        f"?csrf_token={csrf}&tx={trans_id}&p={policy}"
    )
    req_confirm = urllib.request.Request(
        confirmed_url,
        headers={
            "X-CSRF-TOKEN": csrf,
            "Referer": b2c_page_url,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    try:
        resp_conf = opener.open(req_confirm)
        conf_html = resp_conf.read().decode("utf-8")
        
        # Step 5: First SAML POST to ACS
        saml_match = re.search(r'name=[\'\"]SAMLResponse[\'\"]\s+id=[\'\"]SAMLResponse[\'\"]\s+value=[\'\"](.*?)[\'\"]', conf_html)
        relay_match = re.search(r'name=[\'\"]RelayState[\'\"]\s+id=[\'\"]RelayState[\'\"]\s+value=[\'\"](.*?)[\'\"]', conf_html)
        
        if saml_match and relay_match:
            acs_url = "https://webservices.minol.com/saml2/sp/acs"
            acs_data = urllib.parse.urlencode({
                "SAMLResponse": saml_match.group(1),
                "RelayState": relay_match.group(1)
            }).encode("utf-8")
            
            req_acs = urllib.request.Request(
                acs_url, 
                data=acs_data, 
                headers={"Referer": confirmed_url}
            )
            resp_acs = opener.open(req_acs)
            acs_body = resp_acs.read().decode("utf-8")
            
            # Step 6: Second SAML POST to Portal
            saml_match2 = re.search(r'name=[\'\"]SAMLResponse[\'\"]\s+value=[\'\"](.*?)[\'\"]', acs_body)
            relay_match2 = re.search(r'name=[\'\"]RelayState[\'\"]\s+value=[\'\"](.*?)[\'\"]', acs_body)
            
            if saml_match2 and relay_match2:
                portal_url = "https://webservices.minol.com/minol.com~kundenportal~login~saml/?logonTargetUrl=https%3A%2F%2Fwebservices.minol.com%2F&saml2idp=B2C-Minol-Tenant"
                portal_data = urllib.parse.urlencode({
                    "SAMLResponse": saml_match2.group(1),
                    "RelayState": relay_match2.group(1),
                    "saml2post": "false"
                }).encode("utf-8")
                
                req_portal = urllib.request.Request(
                    portal_url, 
                    data=portal_data, 
                    headers={"Referer": acs_url}
                )
                opener.open(req_portal)

    except Exception as exc:
        _LOGGER.debug("Error during SAML post-login steps: %s", exc)
        # We continue to cookie extraction anyway, might have enough partial state

    # 5. Extract authenticated cookies for minol.com
    auth_cookies = {}
    for cookie in cookie_jar:
        if "minol.com" in cookie.domain:
            auth_cookies[cookie.name] = cookie.value

    if "MYSAPSSO2" not in auth_cookies:
        _LOGGER.debug("MYSAPSSO2 cookie not found in jar: %s", list(auth_cookies.keys()))
        # If we got NO cookies, that's a hard error
        if not auth_cookies:
            raise MinolAuthError("No authentication cookies received following B2C flow")

    return auth_cookies


class MinolApiClient:
    """Async client for the Minol eMonitoring portal.

    Authentication flow (Azure B2C / SAML):
      1. GET ``/?redirect2=true`` → follows redirects to Azure B2C login page.
      2. Parse ``$Config`` settings: CSRF token, transId, policy.
      3. POST credentials to the B2C SelfAsserted endpoint.
      4. GET the confirmed endpoint → triggers SAML redirect back to Minol.
      5. Verify ``MYSAPSSO2`` cookie was issued.

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
        """Authenticate with Minol using Azure B2C SAML flow.

        Uses urllib in a background thread for the B2C interaction because
        aiohttp has known incompatibilities with Azure B2C security filters.
        """
        session = self._ensure_session()
        session.cookie_jar.clear()

        try:
            _LOGGER.debug("Starting B2C authentication flow via urllib thread")
            cookies = await asyncio.to_thread(
                _b2c_login_sync, self._username, self._password
            )

            _LOGGER.debug("B2C authentication successful, updating aiohttp session")
            session.cookie_jar.update_cookies(cookies, URL(BASE_URL))

            # Verify by attempting to fetch tenants (which requires valid session)
            tenants = await self.get_user_tenants()
            if not tenants:
                _LOGGER.error("Authentication verified but no tenants found")
                return True

            _LOGGER.debug("Authentication verified successfully")
            return True

        except MinolAuthError as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise
        except Exception as exc:
            _LOGGER.error("Unexpected error during authentication: %s", exc)
            raise MinolAuthError(f"Unexpected error: {exc}") from exc

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

    async def get_room_data(
        self,
        user_num: str | None,
        view_key: str,
        cons_type: str,
    ) -> dict[str, Any] | None:
        """Fetch per-room / per-meter data for a RAUM view."""
        selection = {
            "userNum": user_num,
            "layer": "NE",
            "scale": "CALYEAR",
            "chartRefUnit": "ABS",
            "refObject": "NOREF",
            "consType": cons_type,
            "dashBoardKey": "PE",
            "valuesInKWH": True,
            "dlgKey": view_key,
        }
        return await self._post_json(f"{EMDATA_REST}/readData", selection)

    async def get_all_data(self) -> dict[str, Any]:
        """Collect all data needed by the integration sensors.

        Returns a dict with ``tenants``, ``layer_info``, ``dashboard``,
        and ``rooms`` (per-meter / per-room data).
        """
        tenants = await self.get_user_tenants()
        user_num = tenants[0]["userNumber"] if tenants else None
        tenant_info = tenants[0] if tenants else {}

        layer_info = await self.get_layer_info(user_num)
        dashboard = await self.get_dashboard(user_num)

        # Fetch per-room data for every RAUM view available.
        rooms: dict[str, list[dict[str, Any]]] = {}
        raum_views = {
            "100EHRAUM": "HEIZUNG",
            "200RAUM": "WARMWASSER",
            "300RAUM": "KALTWASSER",
        }
        available_keys = {
            v["key"] for v in (layer_info or {}).get("views", [])
        }
        for view_key, cons_type in raum_views.items():
            if view_key not in available_keys:
                continue
            result = await self.get_room_data(user_num, view_key, cons_type)
            if result and isinstance(result.get("table"), list):
                rooms[cons_type] = result["table"]

        return {
            "tenants": tenants,
            "tenant_info": tenant_info,
            "user_num": user_num,
            "layer_info": layer_info or {},
            "dashboard": dashboard or {},
            "rooms": rooms,
        }
