"""Configuration constants and paths for SafeDelhi AI (Phase 1).
"""
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
BOUNDARIES_DIR = RAW_DATA_DIR / "boundaries"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

# File Paths
DELHI_BOUNDARY_PATH = BOUNDARIES_DIR / "delhi_boundary.geojson"
DATAMEET_BOUNDARY_PATH = BOUNDARIES_DIR / "datameet_delhi.geojson"
OSM_BOUNDARY_PATH = BOUNDARIES_DIR / "osm_delhi.geojson"
GRID_GEOJSON_PATH = PROCESSED_DATA_DIR / "delhi_grid_res8.geojson"
GRID_CLIPPED_GEOJSON_PATH = PROCESSED_DATA_DIR / "delhi_grid_res8_clipped.geojson"
METADATA_PATH = PROCESSED_DATA_DIR / "reproducibility_metadata.json"

STATIC_DIAGNOSTIC_PLOT_PATH = REPORTS_DIR / "delhi_boundary_and_grid.png"
INTERACTIVE_MAP_PATH = REPORTS_DIR / "delhi_grid_interactive.html"

# Bounding Box (NCT of Delhi)
# min_lon, min_lat, max_lon, max_lat (WGS84 EPSG:4326)
DELHI_BBOX = {
    "min_lat": 28.404,
    "max_lat": 28.883,
    "min_lon": 76.838,
    "max_lon": 77.348,
}

# Physical Area Range (sq km) for Validation (Survey of India official is ~1,483 - 1,484 sq km)
EXPECTED_DELHI_AREA_SQKM_MIN = 1440.0
EXPECTED_DELHI_AREA_SQKM_MAX = 1520.0

# H3 Spatial Grid Settings
H3_RESOLUTION = 8

# Lighting Data Classification States
LIGHTING_CONFIRMED_LIT = "confirmed_lit"
LIGHTING_CONFIRMED_UNLIT = "confirmed_unlit"
LIGHTING_UNKNOWN = "unknown"

# Boundary Sources
DATAMEET_GEOJSON_URLS = [
    # DataMeet State/UT boundary GeoJSON repository
    "https://raw.githubusercontent.com/datameet/maps/master/States/Admin2.geojson",
    # DataMeet Assembly Constituencies (Delhi aggregated)
    "https://raw.githubusercontent.com/datameet/maps/master/Assembly_Constituencies/Delhi_AC.geojson",
]

OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_DELHI_RELATION_ID = 1942586  # NCT of Delhi admin_level=4
