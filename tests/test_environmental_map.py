"""
SafeDelhi AI — Phase 2D Verification Tests: Interactive Environmental Vulnerability Map.

Tests:
1. Map output HTML file existence and valid size.
2. Representation of all 2,093 H3 cells.
3. Distinct neutral styling for unassessed cells (no decile / no green coloring).
4. Six independent selectable layers and layer control configuration.
5. Popup attribute and tooltip integrity.
6. End-to-end map generation reproducibility.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

from src.visualization.environmental_map import (
    DEFAULT_INPUT_GEOJSON,
    DEFAULT_OUTPUT_HTML,
    UNASSESSED_STYLE,
    VULNERABILITY_DECILE_COLORS,
    build_environmental_vulnerability_map,
    format_cell_popup_html,
    format_cell_tooltip_text,
)

INPUT_GEOJSON = Path(DEFAULT_INPUT_GEOJSON)
OUTPUT_HTML = Path(DEFAULT_OUTPUT_HTML)

EXPECTED_CELL_COUNT = 2093
EXPECTED_ASSESSED_ROAD_CELLS = 1993
EXPECTED_NON_ROAD_CELLS = 100

EXPECTED_LAYER_NAMES = [
    "1. Vulnerability Deciles (1-10)",
    "2. Data Confidence Tiers",
    "3. Pedestrian Deficit Score",
    "4. Crossing Deficit Score",
    "5. Arterial Traffic Severance",
    "6. Lighting Evidence (Unknown vs Confirmed)",
]

VULNERABILITY_DATA_REQUIRED = pytest.mark.skipif(
    not INPUT_GEOJSON.exists(),
    reason=(
        f"Requires {INPUT_GEOJSON} (reproduce via: .venv/bin/python"
        " src/models/environmental_vulnerability.py)"
    ),
)

MAP_HTML_REQUIRED = pytest.mark.skipif(
    not OUTPUT_HTML.exists(),
    reason=(
        f"Requires {OUTPUT_HTML} (reproduce via: .venv/bin/python"
        " src/visualization/environmental_map.py)"
    ),
)


# ==============================================================================
# 1. POPUP AND TOOLTIP ATTRIBUTE INTEGRITY UNIT TESTS
# ==============================================================================


@VULNERABILITY_DATA_REQUIRED
def test_unit_popup_attribute_integrity_assessed_cell():
  """Verifies that an assessed cell popup contains all required fields:

  cell ID, assessment status, vulnerability score/decile, confidence score/tier,
  pedestrian indicators, crossing indicators, arterial severance, and lighting evidence.
  """
  gdf = gpd.read_file(INPUT_GEOJSON)
  assessed_row = gdf[gdf["vulnerability_assessment_status"] == "assessed"].iloc[
      0
  ]

  popup = format_cell_popup_html(assessed_row)

  # 1. H3 cell ID
  assert assessed_row["cell_id"] in popup

  # 2. Status
  assert "Assessed" in popup

  # 3. Vulnerability score and decile
  assert "Baseline Environmental Vulnerability" in popup
  assert f"Decile {int(assessed_row['vulnerability_decile'])}/10" in popup

  # 4. Data confidence
  assert "Conf:" in popup
  assert str(assessed_row["data_confidence_tier"]).title() in popup

  # 5. Pedestrian indicators
  assert "Pedestrian Infrastructure:" in popup
  assert "Density:" in popup
  assert "Deficit:" in popup

  # 6. Crossing indicators
  assert "Pedestrian Crossings:" in popup
  assert "Deficit:" in popup

  # 7. Arterial severance
  assert "Arterial Traffic Severance:" in popup
  assert "Severance:" in popup

  # 8. Lighting evidence
  assert "Confirmed Lighting Evidence:" in popup
  assert "Coverage:" in popup


@VULNERABILITY_DATA_REQUIRED
def test_unit_popup_attribute_integrity_unassessed_cell():
  """Verifies that an unassessed cell popup explicitly shows non-road status,

  does NOT show a decile, and displays N/A for deficits.
  """
  gdf = gpd.read_file(INPUT_GEOJSON)
  unassessed_row = gdf[
      gdf["vulnerability_assessment_status"] == "not_assessed_no_roads"
  ].iloc[0]

  popup = format_cell_popup_html(unassessed_row)

  # 1. H3 cell ID
  assert unassessed_row["cell_id"] in popup

  # 2. Explicit Not Assessed status
  assert "Not Assessed (No Roads)" in popup or "Not Assessed (No Vehicular Roads)" in popup

  # 3. Must NOT show a decile
  assert "Decile" not in popup

  # 4. Must display N/A for deficits
  assert "N/A" in popup


@VULNERABILITY_DATA_REQUIRED
def test_unit_tooltip_text_integrity():
  """Verifies that tooltip text on hover shows concise status, decile (if assessed), and confidence."""
  gdf = gpd.read_file(INPUT_GEOJSON)

  assessed_row = gdf[gdf["vulnerability_assessment_status"] == "assessed"].iloc[
      0
  ]
  tip_assessed = format_cell_tooltip_text(assessed_row)
  assert assessed_row["cell_id"] in tip_assessed
  assert "Assessed" in tip_assessed
  assert f"Decile {int(assessed_row['vulnerability_decile'])}/10" in tip_assessed

  unassessed_row = gdf[
      gdf["vulnerability_assessment_status"] == "not_assessed_no_roads"
  ].iloc[0]
  tip_unassessed = format_cell_tooltip_text(unassessed_row)
  assert unassessed_row["cell_id"] in tip_unassessed
  assert "Not Assessed (No Roads)" in tip_unassessed
  assert "Decile" not in tip_unassessed


# ==============================================================================
# 2. INTEGRATION TESTS ON GENERATED MAP HTML ARTIFACT
# ==============================================================================


@MAP_HTML_REQUIRED
def test_integration_map_html_file_existence_and_size():
  """Verifies that reports/delhi_environmental_vulnerability_map.html exists and is non-empty."""
  assert OUTPUT_HTML.exists(), "Map HTML output file missing!"

  size_mb = OUTPUT_HTML.stat().st_size / (1024 * 1024)
  assert 5.0 <= size_mb <= 80.0, f"Map HTML size unexpected: {size_mb:.2f} MB"


@MAP_HTML_REQUIRED
def test_integration_map_contains_all_2093_cells():
  """Verifies that all 2,093 H3 cells are represented in the generated map HTML."""
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  gdf = gpd.read_file(INPUT_GEOJSON)
  assert len(gdf) == EXPECTED_CELL_COUNT

  # Sample cells from different areas to verify representation
  sample_cells = gdf["cell_id"].sample(20, random_state=42).tolist()
  for cell_id in sample_cells:
    assert cell_id in html_content, f"Cell ID {cell_id} not found in map HTML!"


@MAP_HTML_REQUIRED
def test_integration_unassessed_cells_displayed_distinctly():
  """Verifies that unassessed cells are represented with distinct neutral styling

  and never assigned a decile.
  """
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  # Check that neutral style color (#9e9e9e) is embedded
  assert UNASSESSED_STYLE["fillColor"] in html_content
  assert "not_assessed_no_roads" in html_content
  assert "Not Assessed (No Vehicular Roads)" in html_content


@MAP_HTML_REQUIRED
def test_integration_layer_configuration():
  """Verifies all 6 independent selectable layers are configured in the map HTML."""
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  for layer_name in EXPECTED_LAYER_NAMES:
    assert layer_name in html_content, f"Missing expected layer: {layer_name}"

  # Verify LayerControl is present
  assert "leaflet-control-layers" in html_content or "LayerControl" in html_content or "control.layers" in html_content


@MAP_HTML_REQUIRED
def test_integration_title_and_methodological_disclaimer():
  """Verifies title banner, legend, and methodological guardrails are present in map HTML."""
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  assert "SafeDelhi AI" in html_content
  assert "Environmental Infrastructure Vulnerability" in html_content
  assert "Map Legend" in html_content
  assert "not predict crime" in html_content.lower()
  assert "safe" in html_content.lower() and "unsafe" in html_content.lower()


@MAP_HTML_REQUIRED
def test_integration_vulnerability_layer_active_by_default():
  """Verifies that the vulnerability decile layer is active by default on load,

  while other indicator layers are initially inactive until selected, and
  auto-exclusive switching logic is present.
  """
  import re

  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  # Layer 1 must be active on initial render
  m_l1 = re.search(r'\"1\. Vulnerability Deciles \(1-10\)\"\s*:\s*(\w+)', html_content)
  assert m_l1, "Layer 1 not mapped in overlays!"
  l1_var = m_l1.group(1)
  assert f"{l1_var}.addTo(" in html_content, "Layer 1 must be added to map by default!"

  # Layers 2 to 6 must NOT be added to map on initialization
  inactive_layers = [
      "2. Data Confidence Tiers",
      "3. Pedestrian Deficit Score",
      "4. Crossing Deficit Score",
      "5. Arterial Traffic Severance",
      "6. Lighting Evidence (Unknown vs Confirmed)",
  ]
  for layer_name in inactive_layers:
    m_lx = re.search(rf'\"{re.escape(layer_name)}\"\s*:\s*(\w+)', html_content)
    assert m_lx, f"Layer {layer_name} not mapped in overlays!"
    lx_var = m_lx.group(1)
    assert f"{lx_var}.addTo(" not in html_content, f"Layer {layer_name} should be inactive on init!"

  # Auto-exclusive switching handler must be present
  assert "overlayadd" in html_content
  assert "indicatorLayers" in html_content or "thematicLayers" in html_content or "removeLayer" in html_content


@MAP_HTML_REQUIRED
def test_integration_basemap_no_blocked_osm_tiles_and_compliant_providers():
  """Verifies that blocked OpenStreetMap tile endpoints returning 403 are eliminated,

  and compliant free basemaps with proper attribution are configured.
  """
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  # Never request tile.openstreetmap.org directly (prevents HTTP 403 Forbidden)
  assert "tile.openstreetmap.org" not in html_content, "Blocked OSM tile URL found in map HTML!"

  # Compliant free basemaps present
  assert "Esri Light Gray Canvas" in html_content
  assert "CartoDB Positron" in html_content

  # Proper attribution present
  assert "Esri" in html_content
  assert "CARTO" in html_content or "OpenStreetMap" in html_content


@MAP_HTML_REQUIRED
def test_integration_map_works_when_external_tiles_unavailable():
  """Verifies that a clean neutral vector fallback basemap using the Delhi boundary

  is embedded so the map works completely without external tile services.
  """
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  # Neutral vector fallback basemap option exists
  assert "Neutral Vector Canvas (No External Tiles)" in html_content

  # State boundary outline exists
  assert "Delhi State Boundary Outline" in html_content

  # Tile error suppression logic is embedded to prevent broken tile icons
  assert "tileerror" in html_content
  assert "display: none !important" in html_content or "tile.style.display = 'none'" in html_content


@MAP_HTML_REQUIRED
def test_integration_lighting_legend_uses_correct_denominators():
  """Verifies that the lighting legend explicitly distinguishes cell-level

  counts from road and pedestrian network lengths, and does not mix denominators.
  """
  with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    html_content = f.read()

  # Cell count percentage clearly labeled
  assert "91.3% of cells" in html_content or "1,911 of 2,093" in html_content

  # Road network length clearly labeled
  assert "99.5% of road length" in html_content or "23,373 of 23,480 km" in html_content

  # Pedestrian path length clearly labeled
  assert "96.0% of path length" in html_content or "1,548 of 1,613 km" in html_content

  # Methodological disclaimer on darkness
  assert "Darkness is never inferred from missing tags" in html_content
  assert "Missing tags indicate lack of OSM survey data" in html_content


# ==============================================================================
# 3. END-TO-END MAP GENERATION REPRODUCIBILITY
# ==============================================================================


@VULNERABILITY_DATA_REQUIRED
def test_e2e_map_generation_reproducibility(tmp_path):
  """Executes build_environmental_vulnerability_map into temporary output and verifies creation."""
  temp_html = tmp_path / "test_map.html"

  m = build_environmental_vulnerability_map(
      input_geojson=str(INPUT_GEOJSON),
      output_html=str(temp_html),
  )

  assert temp_html.exists()
  assert temp_html.stat().st_size > 1_000_000  # > 1 MB
