"""Constants for the Minol Energy integration."""

DOMAIN = "minol_energy"

BASE_URL = "https://webservices.minol.com"
LOGIN_URL = (
    f"{BASE_URL}/irj/servlet/prt/portal/prttarget/uidpwlogon"
    "/prtroot/com.sap.portal.navigation.portallauncher.default"
)
J_SECURITY_CHECK_URL = (
    f"{BASE_URL}/irj/servlet/prt/portal/prtroot/j_security_check"
)
EMDATA_REST = f"{BASE_URL}/minol.com~kundenportal~em~web/rest/EMData"
NUDATA_REST = f"{BASE_URL}/minol.com~kundenportal~em~web/rest/NuData"

DEFAULT_SCAN_INTERVAL = 3600  # 1 hour in seconds

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
