"""
SafeDelhi AI — Phase 2B Step 2B Verification Tests: H3 Environmental Infrastructure Aggregation.

Separates:
1. Lightweight pure unit tests using synthetic geometries (zero file dependencies, 100% portable).
2. Git-tracked dataset integration tests (verifying aggregated indicators GeoJSON & metadata).
3. End-to-end pipeline execution test (gated on local road network GeoJSON).
"""

import json
from pathlib import Path
from typing import List

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from src.spatial.h3_indicator_aggregator import (
    METRIC_CRS,
    PEDESTRIAN_CLASSES,
    ROAD_HIERARCHY_CLASSES,
    aggregate_h3_indicators,
    aggregate_pedestrian_network,
    aggregate_points_to_grid,
    aggregate_road_network,
)

# Paths
GRID_GEOJSON = Path("data/processed/delhi_grid_res8_clipped.geojson")
ROAD_GEOJSON = Path("data/processed/delhi_road_network.geojson")
PED_GEOJSON = Path("data/processed/delhi_pedestrian_network.geojson")
LAMP_GEOJSON = Path("data/processed/delhi_lighting_fixtures.geojson")
CROSSING_GEOJSON = Path("data/processed/delhi_pedestrian_crossings.geojson")

INDICATOR_GEOJSON = Path(
    "data/processed/delhi_h3_environmental_indicators.geojson"
)
INDICATOR_METADATA = Path("data/processed/h3_indicator_metadata.json")

EXPECTED_CELL_COUNT = 2093
EXPECTED_COLUMNS = [
    "cell_id",
    "resolution",
    "centroid_lat",
    "centroid_lon",
    "centroid_within_delhi",
    "intersects_delhi",
    "is_interior_cell",
    "is_boundary_cell",
    "clipped_area_sqkm",
    "full_area_sqkm",
    "coverage_ratio",
    "road_total_length_m",
    "road_residential_length_m",
    "road_service_length_m",
    "road_living_street_length_m",
    "road_tertiary_length_m",
    "road_secondary_length_m",
    "road_primary_length_m",
    "road_trunk_length_m",
    "road_motorway_length_m",
    "road_unclassified_length_m",
    "road_lit_confirmed_length_m",
    "road_lit_unlit_length_m",
    "road_lit_limited_length_m",
    "road_lit_unknown_length_m",
    "road_sidewalk_length_m",
    "road_bridge_length_m",
    "road_tunnel_length_m",
    "ped_total_length_m",
    "ped_dedicated_footway_length_m",
    "ped_shared_path_length_m",
    "ped_track_length_m",
    "ped_indoor_corridor_length_m",
    "ped_cycleway_length_m",
    "ped_bridleway_length_m",
    "ped_lit_confirmed_length_m",
    "ped_lit_unlit_length_m",
    "ped_lit_limited_length_m",
    "ped_lit_unknown_length_m",
    "ped_bridge_length_m",
    "ped_tunnel_length_m",
    "street_lamp_count",
    "pedestrian_crossing_count",
    "road_lit_ratio",
    "road_lit_unknown_ratio",
    "ped_lit_ratio",
    "ped_lit_unknown_ratio",
    "road_density_km_per_sqkm",
    "ped_density_km_per_sqkm",
    "street_lamp_density_per_sqkm",
    "pedestrian_crossing_density_per_sqkm",
    "geometry",
]

ROAD_DATA_REQUIRED = pytest.mark.skipif(
    not ROAD_GEOJSON.exists(),
    reason=(
        "Requires local intermediate data/processed/delhi_road_network.geojson "
        "(git-ignored due to size; reproduce via: .venv/bin/python src/spatial/network_extractor.py)"
    ),
)

INDICATOR_DATA_REQUIRED = pytest.mark.skipif(
    not (INDICATOR_GEOJSON.exists() and INDICATOR_METADATA.exists()),
    reason=(
        "Requires aggregated indicator artifacts data/processed/delhi_h3_environmental_indicators.geojson "
        "and data/processed/h3_indicator_metadata.json "
        "(reproduce via: .venv/bin/python src/spatial/h3_indicator_aggregator.py)"
    ),
)


# ==============================================================================
# 1. PURE UNIT TESTS USING SYNTHETIC GEOMETRIES (ZERO EXTERNAL FILE DEPENDENCIES)
# ==============================================================================


@pytest.fixture
def mock_grid_2cells():
  """Creates two adjacent 10x10 square cells representing mock H3 cells in metric CRS."""
  # Cell A: [0, 0] to [10, 10]
  # Cell B: [10, 0] to [20, 10]
  poly_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
  poly_b = Polygon([(10, 0), (20, 0), (20, 10), (10, 10)])
  gdf = gpd.GeoDataFrame(
      {
          "cell_id": ["cell_a", "cell_b"],
          "geometry": [poly_a, poly_b],
          "clipped_area_sqkm": [0.0001, 0.0001],
      },
      crs=METRIC_CRS,
  )
  return gdf


def test_unit_line_splitting_across_cell_boundaries(mock_grid_2cells):
  """Verifies that line features crossing cell boundaries are accurately split

  and metric lengths are calculated within each cell without double-counting
  or centroid approximations.
  """
  # Line crosses from (2, 5) in Cell A to (18, 5) in Cell B. Total length: 16m.
  # Cell A intersection: (2, 5) to (10, 5) -> length 8m.
  # Cell B intersection: (10, 5) to (18, 5) -> length 8m.
  line = LineString([(2, 5), (18, 5)])
  road_gdf = gpd.GeoDataFrame(
      {
          "highway": ["residential"],
          "lit_status": ["yes"],
          "has_sidewalk": [False],
          "is_bridge": [False],
          "is_tunnel": [False],
          "geometry": [line],
      },
      crs=METRIC_CRS,
  )

  res = aggregate_road_network(road_gdf, mock_grid_2cells)

  assert "cell_a" in res.index
  assert "cell_b" in res.index

  assert pytest.approx(res.loc["cell_a", "road_total_length_m"], rel=1e-5) == 8.0
  assert pytest.approx(res.loc["cell_b", "road_total_length_m"], rel=1e-5) == 8.0

  # Length conservation: sum across cells equals total line length
  assert pytest.approx(res["road_total_length_m"].sum(), rel=1e-5) == 16.0


def test_unit_point_assignment_exclusivity(mock_grid_2cells):
  """Verifies that point features are assigned to at most one cell,

  including points that fall exactly on the shared boundary between cells.
  """
  # Point 1: inside Cell A (5, 5)
  # Point 2: exactly on shared border (10, 5)
  # Point 3: outside all cells (25, 5)
  pts = gpd.GeoDataFrame(
      {"geometry": [Point(5, 5), Point(10, 5), Point(25, 5)]},
      crs=METRIC_CRS,
  )

  counts, unassigned = aggregate_points_to_grid(
      pts, mock_grid_2cells, "lamp_count"
  )

  # Exactly 1 unassigned point outside boundary
  assert unassigned == 1

  # Total assigned points must be 2 (Point 1 and Point 2)
  assert counts.sum() == 2

  # Point on shared boundary (10, 5) must NOT be counted twice
  assert (counts.get("cell_a", 0) + counts.get("cell_b", 0)) == 2


def test_unit_lighting_state_preservation_and_reconciliation(mock_grid_2cells):
  """Verifies that all 4 lighting states ('yes', 'no', 'limited', 'unknown') are

  preserved distinctly, missing tags remain unknown (never converted to 'no'),
  and their sum exactly equals total road length.
  """
  # Create 4 road lines in Cell A with distinct lighting states
  lines = [
      LineString([(1, 1), (1, 3)]),  # len 2m, yes
      LineString([(2, 1), (2, 4)]),  # len 3m, no
      LineString([(3, 1), (3, 5)]),  # len 4m, limited
      LineString([(4, 1), (4, 6)]),  # len 5m, unknown
  ]
  road_gdf = gpd.GeoDataFrame(
      {
          "highway": ["residential", "service", "primary", "secondary"],
          "lit_status": ["yes", "no", "limited", "unknown"],
          "has_sidewalk": [False, False, True, False],
          "is_bridge": [False, False, False, False],
          "is_tunnel": [False, False, False, False],
          "geometry": lines,
      },
      crs=METRIC_CRS,
  )

  res = aggregate_road_network(road_gdf, mock_grid_2cells)

  assert pytest.approx(res.loc["cell_a", "road_lit_confirmed_length_m"]) == 2.0
  assert pytest.approx(res.loc["cell_a", "road_lit_unlit_length_m"]) == 3.0
  assert pytest.approx(res.loc["cell_a", "road_lit_limited_length_m"]) == 4.0
  assert pytest.approx(res.loc["cell_a", "road_lit_unknown_length_m"]) == 5.0
  assert pytest.approx(res.loc["cell_a", "road_total_length_m"]) == 14.0

  # Strict reconciliation invariant: sum(states) == total
  lit_sum = (
      res.loc["cell_a", "road_lit_confirmed_length_m"]
      + res.loc["cell_a", "road_lit_unlit_length_m"]
      + res.loc["cell_a", "road_lit_limited_length_m"]
      + res.loc["cell_a", "road_lit_unknown_length_m"]
  )
  assert (
      pytest.approx(lit_sum, abs=1e-4) == res.loc["cell_a", "road_total_length_m"]
  )


def test_unit_road_hierarchy_breakdown_and_normalization(mock_grid_2cells):
  """Verifies that road link types are normalized to parent classes and

  hierarchy breakdown reconciles to total road length.
  """
  lines = [
      LineString([(1, 1), (1, 4)]),  # len 3m, tertiary_link -> tertiary
      LineString([(2, 1), (2, 5)]),  # len 4m, motorway_link -> motorway
      LineString([(3, 1), (3, 6)]),  # len 5m, living_street
  ]
  road_gdf = gpd.GeoDataFrame(
      {
          "highway": ["tertiary_link", "motorway_link", "living_street"],
          "lit_status": ["unknown", "unknown", "unknown"],
          "has_sidewalk": [False, False, False],
          "is_bridge": [False, False, False],
          "is_tunnel": [False, False, False],
          "geometry": lines,
      },
      crs=METRIC_CRS,
  )

  res = aggregate_road_network(road_gdf, mock_grid_2cells)

  assert pytest.approx(res.loc["cell_a", "road_tertiary_length_m"]) == 3.0
  assert pytest.approx(res.loc["cell_a", "road_motorway_length_m"]) == 4.0
  assert pytest.approx(res.loc["cell_a", "road_living_street_length_m"]) == 5.0
  assert pytest.approx(res.loc["cell_a", "road_total_length_m"]) == 12.0

  # Hierarchy reconciliation invariant
  hw_sum = sum(
      res.loc["cell_a", f"road_{c}_length_m"] for c in ROAD_HIERARCHY_CLASSES
  )
  assert (
      pytest.approx(hw_sum, abs=1e-4) == res.loc["cell_a", "road_total_length_m"]
  )


def test_unit_pedestrian_class_breakdown_and_reconciliation(mock_grid_2cells):
  """Verifies that pedestrian classes are preserved separately and reconcile to

  total pedestrian length.
  """
  lines = [
      LineString([(1, 1), (1, 3)]),  # len 2m, dedicated_footway
      LineString([(2, 1), (2, 4)]),  # len 3m, shared_path
      LineString([(3, 1), (3, 5)]),  # len 4m, indoor_corridor
      LineString([(4, 1), (4, 6)]),  # len 5m, cycleway
  ]
  ped_gdf = gpd.GeoDataFrame(
      {
          "pedestrian_class": [
              "dedicated_footway",
              "shared_path",
              "indoor_corridor",
              "cycleway",
          ],
          "lit_status": ["yes", "no", "unknown", "limited"],
          "is_bridge": [False, False, False, False],
          "is_tunnel": [False, False, False, False],
          "geometry": lines,
      },
      crs=METRIC_CRS,
  )

  res = aggregate_pedestrian_network(ped_gdf, mock_grid_2cells)

  assert (
      pytest.approx(res.loc["cell_a", "ped_dedicated_footway_length_m"]) == 2.0
  )
  assert pytest.approx(res.loc["cell_a", "ped_shared_path_length_m"]) == 3.0
  assert pytest.approx(res.loc["cell_a", "ped_indoor_corridor_length_m"]) == 4.0
  assert pytest.approx(res.loc["cell_a", "ped_cycleway_length_m"]) == 5.0
  assert pytest.approx(res.loc["cell_a", "ped_total_length_m"]) == 14.0

  # Pedestrian class reconciliation invariant
  cls_sum = sum(
      res.loc["cell_a", f"ped_{c}_length_m"] for c in PEDESTRIAN_CLASSES
  )
  assert (
      pytest.approx(cls_sum, abs=1e-4) == res.loc["cell_a", "ped_total_length_m"]
  )


def test_unit_empty_layers_and_zero_feature_cells(mock_grid_2cells):
  """Verifies that empty feature layers return valid schemas with zero lengths

  and do not cause exceptions or NaNs.
  """
  empty_roads = gpd.GeoDataFrame(
      columns=[
          "highway",
          "lit_status",
          "has_sidewalk",
          "is_bridge",
          "is_tunnel",
          "geometry",
      ],
      crs=METRIC_CRS,
  )
  empty_peds = gpd.GeoDataFrame(
      columns=[
          "pedestrian_class",
          "lit_status",
          "is_bridge",
          "is_tunnel",
          "geometry",
      ],
      crs=METRIC_CRS,
  )
  empty_pts = gpd.GeoDataFrame(columns=["geometry"], crs=METRIC_CRS)

  road_res = aggregate_road_network(empty_roads, mock_grid_2cells)
  ped_res = aggregate_pedestrian_network(empty_peds, mock_grid_2cells)
  pts_res, unassigned = aggregate_points_to_grid(
      empty_pts, mock_grid_2cells, "count"
  )

  assert len(road_res) == 0
  assert len(ped_res) == 0
  assert len(pts_res) == 0
  assert unassigned == 0
  assert "road_total_length_m" in road_res.columns
  assert "ped_total_length_m" in ped_res.columns


# ==============================================================================
# 2. INTEGRATION TESTS ON DELHI AGGREGATED INDICATOR DATASETS
# ==============================================================================


@INDICATOR_DATA_REQUIRED
def test_integration_indicator_file_structure():
  """Verifies existence, size, and validity of generated indicator artifacts."""
  assert INDICATOR_GEOJSON.exists(), "Indicators GeoJSON output missing!"
  assert INDICATOR_METADATA.exists(), "Indicators metadata JSON missing!"

  size_mb = INDICATOR_GEOJSON.stat().st_size / (1024 * 1024)
  assert 2.0 <= size_mb <= 15.0, (
      f"Indicator GeoJSON size unexpected: {size_mb:.2f} MB"
  )

  with open(INDICATOR_METADATA, "r", encoding="utf-8") as f:
    meta = json.load(f)

  assert (
      meta["step"] == "Phase 2B Step 2B: H3 Environmental Indicator Aggregation"
  )
  assert meta["grid"]["total_cells"] == EXPECTED_CELL_COUNT
  assert meta["validation_invariants"]["geometry_validity_verified"] is True
  assert meta["validation_invariants"]["point_conservation_verified"] is True


@INDICATOR_DATA_REQUIRED
def test_integration_cell_preservation_and_geometry():
  """Verifies that all 2,093 cells are preserved with valid geometries and match

  input grid cell IDs exactly.
  """
  grid_gdf = gpd.read_file(GRID_GEOJSON)
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)

  assert (
      len(ind_gdf) == EXPECTED_CELL_COUNT
  ), f"Expected {EXPECTED_CELL_COUNT} cells, got {len(ind_gdf)}"
  assert ind_gdf["cell_id"].nunique() == EXPECTED_CELL_COUNT

  # 100% cell ID set identity
  assert set(ind_gdf["cell_id"]) == set(grid_gdf["cell_id"])

  # Geometry validity and non-emptiness
  assert ind_gdf.geometry.is_valid.all()
  assert (~ind_gdf.geometry.is_empty).all()

  # Coordinate reference system must be EPSG:4326 for final output
  assert ind_gdf.crs.to_epsg() == 4326


@INDICATOR_DATA_REQUIRED
def test_integration_schema_and_column_integrity():
  """Verifies all 52 expected columns exist and have non-null, valid numeric types."""
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)

  for col in EXPECTED_COLUMNS:
    assert col in ind_gdf.columns, f"Missing expected column: {col}"

  assert len(ind_gdf.columns) == len(EXPECTED_COLUMNS)

  # Check that no NaN values exist in indicator columns
  indicator_cols = [
      c
      for c in ind_gdf.columns
      if c.endswith("_length_m")
      or c.endswith("_count")
      or c.endswith("_ratio")
      or c.endswith("_per_sqkm")
  ]
  assert (
      not ind_gdf[indicator_cols].isna().any().any()
  ), "Detected NaN values in indicator columns!"

  # All counts must be non-negative integers
  assert (ind_gdf["street_lamp_count"] >= 0).all()
  assert (ind_gdf["pedestrian_crossing_count"] >= 0).all()

  # All lengths must be non-negative floats
  for col in ind_gdf.columns:
    if col.endswith("_length_m"):
      assert (
          ind_gdf[col] >= 0.0
      ).all(), f"Found negative values in length column {col}"


@INDICATOR_DATA_REQUIRED
def test_integration_road_lighting_and_hierarchy_reconciliation():
  """Verifies strict mathematical reconciliation across all 2,093 cells for road network:

  1. road_lit_confirmed + road_lit_unlit + road_lit_limited + road_lit_unknown == road_total_length_m (<= 0.05m tolerance)
  2. sum(road_{c}_length_m) == road_total_length_m (<= 0.05m tolerance)
  """
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)

  # 1. Lighting reconciliation
  lit_sum = (
      ind_gdf["road_lit_confirmed_length_m"]
      + ind_gdf["road_lit_unlit_length_m"]
      + ind_gdf["road_lit_limited_length_m"]
      + ind_gdf["road_lit_unknown_length_m"]
  ).round(2)
  lit_diff = np.abs(lit_sum - ind_gdf["road_total_length_m"])
  assert (lit_diff <= 0.05).all(), (
      f"Road lighting reconciliation failed! Max error: {lit_diff.max():.4f} m"
  )

  # 2. Hierarchy reconciliation
  hw_cols = [f"road_{c}_length_m" for c in ROAD_HIERARCHY_CLASSES]
  hw_sum = ind_gdf[hw_cols].sum(axis=1).round(2)
  hw_diff = np.abs(hw_sum - ind_gdf["road_total_length_m"])
  assert (hw_diff <= 0.05).all(), (
      f"Road hierarchy reconciliation failed! Max error: {hw_diff.max():.4f} m"
  )


@INDICATOR_DATA_REQUIRED
def test_integration_pedestrian_lighting_and_class_reconciliation():
  """Verifies strict mathematical reconciliation across all 2,093 cells for pedestrian network:

  1. ped_lit_confirmed + ped_lit_unlit + ped_lit_limited + ped_lit_unknown == ped_total_length_m (<= 0.05m tolerance)
  2. sum(ped_{c}_length_m) == ped_total_length_m (<= 0.05m tolerance)
  """
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)

  # 1. Lighting reconciliation
  lit_sum = (
      ind_gdf["ped_lit_confirmed_length_m"]
      + ind_gdf["ped_lit_unlit_length_m"]
      + ind_gdf["ped_lit_limited_length_m"]
      + ind_gdf["ped_lit_unknown_length_m"]
  ).round(2)
  lit_diff = np.abs(lit_sum - ind_gdf["ped_total_length_m"])
  assert (lit_diff <= 0.05).all(), (
      "Pedestrian lighting reconciliation failed! Max error:"
      f" {lit_diff.max():.4f} m"
  )

  # 2. Class reconciliation
  cls_cols = [f"ped_{c}_length_m" for c in PEDESTRIAN_CLASSES]
  cls_sum = ind_gdf[cls_cols].sum(axis=1).round(2)
  cls_diff = np.abs(cls_sum - ind_gdf["ped_total_length_m"])
  assert (cls_diff <= 0.05).all(), (
      f"Pedestrian class reconciliation failed! Max error: {cls_diff.max():.4f}"
      " m"
  )


@INDICATOR_DATA_REQUIRED
def test_integration_point_feature_conservation():
  """Verifies total point counts match assigned + unassigned totals from source datasets."""
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)
  with open(INDICATOR_METADATA, "r", encoding="utf-8") as f:
    meta = json.load(f)

  total_lamps_assigned = int(ind_gdf["street_lamp_count"].sum())
  total_crossings_assigned = int(ind_gdf["pedestrian_crossing_count"].sum())

  # Lamps: all 1,462 fall within Delhi H3 grid
  assert total_lamps_assigned == 1462
  assert meta["spatial_totals"]["unassigned_lamps_outside_boundary"] == 0

  # Crossings: 1,953 inside grid, 6 in boundary buffer outside grid cells
  assert total_crossings_assigned == 1953
  assert meta["spatial_totals"]["unassigned_crossings_outside_boundary"] == 6
  assert total_crossings_assigned + 6 == 1959


@INDICATOR_DATA_REQUIRED
def test_integration_zero_infrastructure_cells_preservation():
  """Verifies that cells with zero mapped infrastructure are correctly preserved

  with 0.0 / 0 values rather than dropped or populated with NaNs.
  """
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)
  zero_infra_mask = (
      (ind_gdf["road_total_length_m"] == 0)
      & (ind_gdf["ped_total_length_m"] == 0)
      & (ind_gdf["street_lamp_count"] == 0)
      & (ind_gdf["pedestrian_crossing_count"] == 0)
  )
  zero_infra_count = int(zero_infra_mask.sum())

  assert zero_infra_count == 56, (
      f"Expected exactly 56 zero-infrastructure cells, got {zero_infra_count}"
  )

  zero_cells = ind_gdf[zero_infra_mask]
  assert (zero_cells["road_lit_ratio"] == 0.0).all()
  assert (zero_cells["ped_lit_ratio"] == 0.0).all()
  assert (zero_cells["road_density_km_per_sqkm"] == 0.0).all()
  assert (zero_cells["ped_density_km_per_sqkm"] == 0.0).all()
  assert (zero_cells["street_lamp_density_per_sqkm"] == 0.0).all()


@INDICATOR_DATA_REQUIRED
def test_integration_macro_totals_and_osm_characteristics():
  """Verifies domain-specific network totals and high unknown-lighting proportion in Delhi OSM data."""
  ind_gdf = gpd.read_file(INDICATOR_GEOJSON)

  total_road_km = ind_gdf["road_total_length_m"].sum() / 1000.0
  total_ped_km = ind_gdf["ped_total_length_m"].sum() / 1000.0

  # Delhi vehicular road network is ~23,480 km
  assert 23000.0 <= total_road_km <= 24000.0

  # Delhi pedestrian network is ~1,613 km
  assert 1500.0 <= total_ped_km <= 1700.0

  # OSM lighting completeness in Delhi: unknown lit status exceeds 95% of road network
  road_unknown_lit_km = ind_gdf["road_lit_unknown_length_m"].sum() / 1000.0
  unknown_pct = (road_unknown_lit_km / total_road_km) * 100
  assert unknown_pct >= 95.0, (
      f"Expected high unknown lighting proportion in OSM Delhi, got"
      f" {unknown_pct:.2f}%"
  )


# ==============================================================================
# 3. END-TO-END PIPELINE EXECUTION TEST (GATED ON LOCAL ROAD NETWORK FILE)
# ==============================================================================


@ROAD_DATA_REQUIRED
def test_e2e_pipeline_execution_reproducibility(tmp_path):
  """Executes aggregate_h3_indicators into temporary outputs and verifies exact

  reproducibility with production outputs.
  """
  temp_geo = tmp_path / "test_indicators.geojson"
  temp_meta = tmp_path / "test_metadata.json"

  out_gdf, meta = aggregate_h3_indicators(
      output_geojson=str(temp_geo),
      output_metadata=str(temp_meta),
  )

  assert len(out_gdf) == EXPECTED_CELL_COUNT
  assert temp_geo.exists()
  assert temp_meta.exists()
  assert meta["spatial_totals"]["total_street_lamps_assigned"] == 1462
  assert meta["spatial_totals"]["total_pedestrian_crossings_assigned"] == 1953
