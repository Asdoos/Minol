"""Constants for the Minol Energy integration."""

DOMAIN = "minol_energy"

# ---------------------------------------------------------------------------
# Mobile app (Mulesoft) API – captured from MinolApp iOS traffic (Charles Proxy)
# ---------------------------------------------------------------------------

# Azure B2C authorization endpoint (starts the OAuth2 browser flow)
B2C_AUTH_URL = (
    "https://minolauth.b2clogin.com/tfp/"
    "minolauth.onmicrosoft.com/"
    "B2C_1A_SEAMLESS_MIGRATION_AND_GROUPS/oauth2/v2.0/authorize"
)

# Azure B2C token endpoint (code exchange and token refresh)
B2C_TOKEN_URL = (
    "https://minolauth.b2clogin.com/tfp/"
    "minolauth.onmicrosoft.com/"
    "B2C_1A_SEAMLESS_MIGRATION_AND_GROUPS/oauth2/v2.0/token"
)

# MSAL app registration client ID (iOS app, production tenant)
B2C_CLIENT_ID = "b751cea9-de3f-498b-9dcf-33a22a28d578"

# Native MSAL redirect URI of the mobile app ("msal{client_id}://auth").
# The app is a *public* client: PKCE only, no client secret.  A browser cannot
# open this scheme, so the user copies the URL (with ?code=…) from the browser
# console / address bar.  The former Postman redirect + client secret path
# was shut down by Minol in Nov 2026 (token endpoint answers AADB2C90085).
B2C_REDIRECT_URI = f"msal{B2C_CLIENT_ID}://auth"

# OAuth2 scopes requested by the mobile app
B2C_SCOPES = " ".join([
    "openid",
    "profile",
    "offline_access",
    "https://minolauth.onmicrosoft.com/"
    "e7cf3202-37a5-4b92-aae1-9e4f675ad9ed/access_as_user",
])

# Mulesoft Experience API (production)
API_BASE_URL = "https://minol-prod-minol-app-eapi.de-c1.eu1.cloudhub.io/api/app"

# Mulesoft API client credentials (shared, embedded in every app copy)
API_CLIENT_ID = "e846b9d0008344d58c532147ba3fa6d1"
API_CLIENT_SECRET = "a1DCEd2605424FecBB1046CbBD4ae3d6"

# App version sent in the appVersion header (API version, not app version)
APP_VERSION = "1.1"

# User-Agent mimicking the MSAL library used by the app
USER_AGENT = "MinolApp/2.11.14 (iOS; MSAL.Xamarin.iOS/4.78.0.0)"

# ---------------------------------------------------------------------------
# Service type codes  (from /lookup endpoint)
# ---------------------------------------------------------------------------
SERVICE_HEATING = "100"       # Heizung
SERVICE_HOT_WATER = "200"     # Warmwasser
SERVICE_COLD_WATER = "300"    # Kaltwasser

# Consumption period status returned by /consumptions when the billing period
# is finalised and ready for display.
STATUS_UVI_AVAILABLE = "UVI_AVAILABLE"

# ---------------------------------------------------------------------------
# Room type lookup table (source: MinolApp 2.11.16 lookupdata, domain "rooms")
#
# The "room" field in consumption device entries is a 7-digit zero-padded
# room-type code.  These codes map to standardised room names that are
# embedded in the Minol mobile app and returned by the /lookupdata endpoint.
# ---------------------------------------------------------------------------
ROOM_TYPE_NAMES: dict[str, str] = {
    "0000001": "Work room",
    "0000002": "Bathroom",
    "0000003": "Office",
    "0000004": "Shower",
    "0000005": "Dining room",
    "0000006": "Hall",
    "0000007": "Foreign room",
    "0000008": "Garage",
    "0000009": "Guest room",
    "0000010": "Business room",
    "0000011": "Hobby room",
    "0000012": "Cellar",
    "0000013": "Children's room",
    "0000014": "Kitchen",
    "0000015": "Shop",
    "0000016": "Store",
    "0000017": "Practice room",
    "0000018": "Sauna",
    "0000019": "Swimming pool",
    "0000020": "Bedroom",
    "0000021": "Stairwell",
    "0000023": "Toilet",
    "0000024": "Laundry",
    "0000025": "Workshop",
    "0000026": "Living area",
    "0000027": "Living room",
    "0000028": "Unknown",
    "0000029": "Fireplace room",
    "0000030": "Children's room",
    "0000031": "Heating room",
    "0000032": "Above ground",
    "0000033": "Underground",
    "0000034": "Training room",
    "0000035": "Laboratory",
    "0000036": "Sales room",
    "0000037": "Technical room",
    "0000038": "View window",
    "0000039": "Anteroom",
    "0000040": "Chamber",
    "0000041": "Treatment room",
    "0000042": "Waiting room",
    "0000043": "Winter garden",
    "0000044": "Rest room",
    "0000045": "Changing room",
    "0000046": "Ancillary room",
    "0000047": "Economic region",
    "0000048": "Hall",
    "0000049": "Underfloor heating",
    "0000050": "Room",
    "0000051": "Guest room",
    "0000053": "Garden water meter",
    "0000054": "Storage room",
    "0000055": "Bakery",
    "0000056": "Guest house",
    "0000058": "D+H toilet",
    "0000059": "WC personal",
    "0000061": "Disabled WC",
    "0000068": "Loggia",
    "0000069": "Greenhouse",
    "0000070": "Fitness room",
    "0000071": "Drying room",
    "0000072": "Skirting board",
    "0000073": "Main",
    "0000074": "Washing machine",
    "0000075": "Water wall",
    "0000076": "Room 1",
    "0000077": "Room 2",
    "0000078": "Room 3",
    "0000079": "Room 4",
    "0000080": "Room 5",
    "0000081": "Announcer cabin",
    "0000082": "Apprentice room",
    "0000083": "Meeting room",
    "0000084": "Reception room",
    "0000085": "Server room",
    "0000093": "Dressing room",
    "0000094": "Room 6",
    "0000095": "Room 7",
    "0000096": "Room 8",
    "0000097": "Room 9",
    "0000098": "Room 10",
    "0000099": "Room 11",
    "0000100": "Room 12",
    "0000101": "Room 13",
    "0000102": "Room 14",
    "0000103": "Room 15",
    "0000104": "Room 16",
    "0000105": "Room 17",
    "0000106": "Room 18",
    "0000107": "Room 19",
    "0000108": "Room 20",
    "0000109": "Emergency exit",
    "0000110": "Room Street",
    "0000111": "Room Garden",
    "0000112": "Heating centre",
    "0000113": "Ventilation centre",
    "0000114": "Cooling centre",
    "0000115": "Attic room",
    "0000116": "Pipe heat share VDI 2077",
    "0000117": "Stage",
    "0000118": "Total consumption",
    "0000119": "Conference room",
    "0000120": "Cafeteria",
    "0000121": "Room 101",
    "0000122": "Room 102",
    "0000123": "Room 103",
    "0000124": "Room 104",
    "0000125": "Room 105",
    "0000126": "Room 106",
    "0000127": "Room 107",
    "0000128": "Room 108",
    "0000129": "Room 109",
    "0000130": "Room 110",
    "0000131": "Room 111",
    "0000132": "Room 201",
    "0000133": "Room 202",
    "0000134": "Room 203",
    "0000135": "Room 204",
    "0000136": "Room 205",
    "0000137": "Room 206",
    "0000138": "Room 207",
    "0000139": "Room 208",
    "0000140": "Room 209",
    "0000141": "Room 210",
    "0000142": "Room 211",
}

ROOM_TYPE_NAMES_DE: dict[str, str] = {
    "0000001": "Arbeitszimmer",
    "0000002": "Badezimmer",
    "0000003": "Büro",
    "0000004": "Dusche",
    "0000005": "Esszimmer",
    "0000006": "Flur",
    "0000007": "Fremdraum",
    "0000008": "Garage",
    "0000009": "Gästezimmer",
    "0000010": "Gewerberaum",
    "0000011": "Hobbyraum",
    "0000012": "Keller",
    "0000013": "Kinderzimmer",
    "0000014": "Küche",
    "0000015": "Laden",
    "0000016": "Lager",
    "0000017": "Praxisraum",
    "0000018": "Sauna",
    "0000019": "Schwimmbad",
    "0000020": "Schlafzimmer",
    "0000021": "Treppenhaus",
    "0000023": "WC",
    "0000024": "Waschküche",
    "0000025": "Werkstatt",
    "0000026": "Wohnbereich",
    "0000027": "Wohnzimmer",
    "0000028": "Unbekannt",
    "0000029": "Kaminzimmer",
    "0000030": "Kinderzimmer",
    "0000031": "Heizungsraum",
    "0000032": "Oberirdisch",
    "0000033": "Unterirdisch",
    "0000034": "Schulungsraum",
    "0000035": "Labor",
    "0000036": "Verkaufsraum",
    "0000037": "Technikraum",
    "0000038": "Schaufenster",
    "0000039": "Vorraum",
    "0000040": "Kammer",
    "0000041": "Behandlungsraum",
    "0000042": "Wartezimmer",
    "0000043": "Wintergarten",
    "0000044": "Aufenthaltsraum",
    "0000045": "Umkleideraum",
    "0000046": "Nebenraum",
    "0000047": "Wirtschaftsraum",
    "0000048": "Halle",
    "0000049": "Fußbodenheizung",
    "0000050": "Zimmer",
    "0000051": "Gästezimmer",
    "0000053": "Gartenwasserzähler",
    "0000054": "Abstellraum",
    "0000055": "Bäckerei",
    "0000056": "Gästehaus",
    "0000058": "D+H WC",
    "0000059": "WC Personal",
    "0000061": "Behinderten-WC",
    "0000068": "Loggia",
    "0000069": "Gewächshaus",
    "0000070": "Fitnessraum",
    "0000071": "Trockenraum",
    "0000072": "Sockelleiste",
    "0000073": "Hauptzähler",
    "0000074": "Waschmaschine",
    "0000075": "Wasserwand",
    "0000076": "Zimmer 1",
    "0000077": "Zimmer 2",
    "0000078": "Zimmer 3",
    "0000079": "Zimmer 4",
    "0000080": "Zimmer 5",
    "0000081": "Sprecherkabine",
    "0000082": "Lehrlingsraum",
    "0000083": "Besprechungsraum",
    "0000084": "Empfangsraum",
    "0000085": "Serverraum",
    "0000093": "Ankleidezimmer",
    "0000094": "Zimmer 6",
    "0000095": "Zimmer 7",
    "0000096": "Zimmer 8",
    "0000097": "Zimmer 9",
    "0000098": "Zimmer 10",
    "0000099": "Zimmer 11",
    "0000100": "Zimmer 12",
    "0000101": "Zimmer 13",
    "0000102": "Zimmer 14",
    "0000103": "Zimmer 15",
    "0000104": "Zimmer 16",
    "0000105": "Zimmer 17",
    "0000106": "Zimmer 18",
    "0000107": "Zimmer 19",
    "0000108": "Zimmer 20",
    "0000109": "Notausgang",
    "0000110": "Zimmer Straße",
    "0000111": "Zimmer Garten",
    "0000112": "Heizzentrale",
    "0000113": "Lüftungszentrale",
    "0000114": "Kältezentrale",
    "0000115": "Dachgeschossraum",
    "0000116": "Rohrwärmeanteil VDI 2077",
    "0000117": "Bühne",
    "0000118": "Gesamtverbrauch",
    "0000119": "Konferenzraum",
    "0000120": "Cafeteria",
    "0000121": "Zimmer 101",
    "0000122": "Zimmer 102",
    "0000123": "Zimmer 103",
    "0000124": "Zimmer 104",
    "0000125": "Zimmer 105",
    "0000126": "Zimmer 106",
    "0000127": "Zimmer 107",
    "0000128": "Zimmer 108",
    "0000129": "Zimmer 109",
    "0000130": "Zimmer 110",
    "0000131": "Zimmer 111",
    "0000132": "Zimmer 201",
    "0000133": "Zimmer 202",
    "0000134": "Zimmer 203",
    "0000135": "Zimmer 204",
    "0000136": "Zimmer 205",
    "0000137": "Zimmer 206",
    "0000138": "Zimmer 207",
    "0000139": "Zimmer 208",
    "0000140": "Zimmer 209",
    "0000141": "Zimmer 210",
    "0000142": "Zimmer 211",
}

# ---------------------------------------------------------------------------
# Integration config / options keys
# ---------------------------------------------------------------------------
DEFAULT_SCAN_INTERVAL = 3600  # 1 hour in seconds

CONF_SCAN_INTERVAL = "scan_interval"
CONF_HEATING_PRICE = "heating_price"
CONF_HOT_WATER_PRICE = "hot_water_price"
CONF_COLD_WATER_PRICE = "cold_water_price"

# Config entry data keys for OAuth2 tokens
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
