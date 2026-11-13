"""
SafeDelhi AI — Phase 2B Step 2A Verification Tests.

Separates:
1. Lightweight pure unit tests (zero file dependencies, 100% portable).
2. Git-tracked dataset integration tests (portable across fresh clones).
3. Intermediate dataset integration tests (gated on local 124.51 MB road GeoJSON).
"""

import json
from pathlib import Path
import geopandas as gpd
import pyogrio
import pytest

from src.spatial.network_extractor import (
    classify_lit_status,
    classify_pedestrian_category,
)

ROAD_GEOJSON = Path("data/processed/delhi_road_network.geojson")
PED_GEOJSON = Path("data/processed/delhi_pedestrian_network.geojson")
LAMP_GEOJSON = Path("data/processed/delhi_lighting_fixtures.geojson")
CROSSING_GEOJSON = Path("data/processed/delhi_pedestrian_crossings.geojson")
METADATA_JSON = Path("data/processed/network_extraction_metadata.json")
BOUNDARY_GEOJSON = Path("data/raw/boundaries/delhi_boundary.geojson")

EXPECTED_ROAD_COUNT = 151964
EXPECTED_PED_COUNT = 14742
EXPECTED_LAMP_COUNT = 1462
EXPECTED_CROSSING_COUNT = 1959

ROAD_DATA_REQUIRED = pytest.mark.skipif(
    not ROAD_GEOJSON.exists(),
    reason=(
        "Requires local intermediate data/processed/delhi_road_network.geojson "
        "(reproduce via: .venv/bin/python src/spatial/network_extractor.py)"
    ),
)


# ==============================================================================
# 1. LIGHTWEIGHT UNIT TESTS (ZERO EXTERNAL FILE DEPENDENCIES)
# ==============================================================================


def test_unit_lighting_classification_logic():
  """Unit tests for classify_lit_status 4-state vocabulary and unlit-imputation invariants."""
  # Positive states
  assert classify_lit_status("yes") == "yes"
  assert classify_lit_status("YES") == "yes"
  assert classify_lit_status("24/7") == "yes"
  assert classify_lit_status("dusk-dawn") == "yes"
  assert classify_lit_status("night") == "yes"

  # Explicit negative states
  assert classify_lit_status("no") == "no"
  assert classify_lit_status("NO") == "no"
  assert classify_lit_status("unlit") == "no"
  assert classify_lit_status("off") == "no"

  # Limited states
  assert classify_lit_status("limited") == "limited"
  assert classify_lit_status("interval") == "limited"
  assert classify_lit_status("disused") == "limited"

  # Missing / unknown states
  assert classify_lit_status(None) == "unknown"

  # Critical Negative Assertion: None/empty must NEVER evaluate to 'no'
  assert classify_lit_status(None) != "no"


def test_unit_pedestrian_classification_logic():
  """Unit tests for classify_pedestrian_category distinctness."""
  # Indoor takes precedence
  assert (
      classify_pedestrian_category("footway", is_indoor=True)
      == "indoor_corridor"
  )
  assert (
      classify_pedestrian_category("corridor", is_indoor=False)
      == "indoor_corridor"
  )

  # Dedicated footway hierarchy
  assert (
      classify_pedestrian_category("footway", is_indoor=False)
      == "dedicated_footway"
  )
  assert (
      classify_pedestrian_category("pedestrian", is_indoor=False)
      == "dedicated_footway"
  )
  assert (
      classify_pedestrian_category("steps", is_indoor=False)
      == "dedicated_footway"
  )

  # Distinct specialized classes
  assert (
      classify_pedestrian_category("path", is_indoor=False) == "shared_path"
  )
  assert classify_pedestrian_category("track", is_indoor=False) == "track"
  assert classify_pedestrian_category("cycleway", is_indoor=False) == "cycleway"
  assert (
      classify_pedestrian_category("bridleway", is_indoor=False) == "bridleway"
  )


# ==============================================================================
# 2. GIT-TRACKED DATASET INTEGRATION TESTS (PORTABLE ACROSS CLONES)
# ==============================================================================


def test_tracked_layers_exist_and_non_empty():
  """Confirms all Git-tracked processed layers exist and meet minimum size thresholds."""
  for path, min_size in [
      (PED_GEOJSON, 5_000_000),
      (LAMP_GEOJSON, 200_000),
      (CROSSING_GEOJSON, 300_000),
      (METADATA_JSON, 1_000),
      (BOUNDARY_GEOJSON, 20_000),
  ]:
    assert path.exists(), f"File missing: {path}"
    assert (
        path.stat().st_size >= min_size
    ), f"File unexpectedly small ({path.stat().st_size} bytes): {path}"


def test_pedestrian_layer_integrity():
  """Verifies counts, geometries, distinct classes, and OSM IDs for pedestrian network."""
  ped_gdf = gpd.read_file(PED_GEOJSON, engine="pyogrio")
  assert (
      len(ped_gdf) == EXPECTED_PED_COUNT
  ), f"Pedestrian count mismatch: {len(ped_gdf)} != {EXPECTED_PED_COUNT}"
  assert (
      ped_gdf.crs.to_epsg() == 4326
  ), f"Pedestrian CRS should be EPSG:4326, got {ped_gdf.crs}"
  assert (
      ped_gdf.geom_type == "LineString"
  ).all(), "All pedestrian geometries must be LineString"
  assert ped_gdf.geometry.is_valid.all(), (
      "All pedestrian geometries must be valid"
  )
  assert "osm_id" in ped_gdf.columns
  assert len(ped_gdf["osm_id"].unique()) == EXPECTED_PED_COUNT

  # Category distinctness
  categories = set(ped_gdf["pedestrian_class"].unique())
  assert "dedicated_footway" in categories
  assert "shared_path" in categories
  assert "track" in categories
  assert "cycleway" in categories
  assert "indoor_corridor" in categories
  assert (
      ped_gdf.loc[
          ped_gdf["highway"] == "cycleway", "pedestrian_class"
      ]
      == "cycleway"
  ).all()
  assert (
      ped_gdf.loc[ped_gdf["highway"] == "track", "pedestrian_class"] == "track"
  ).all()
  assert (
      ped_gdf.loc[ped_gdf["highway"] == "corridor", "is_indoor"]
  ).all()


def test_lighting_fixtures_integrity():
  """Verifies counts, geometry types, and coordinate validity for street lamps."""
  lamp_gdf = gpd.read_file(LAMP_GEOJSON, engine="pyogrio")
  assert (
      len(lamp_gdf) == EXPECTED_LAMP_COUNT
  ), f"Street lamp count mismatch: {len(lamp_gdf)} != {EXPECTED_LAMP_COUNT}"
  assert (
      lamp_gdf.crs.to_epsg() == 4326
  ), f"Lamp CRS should be EPSG:4326, got {lamp_gdf.crs}"
  assert (
      lamp_gdf.geom_type == "Point"
  ).all(), "All lamp geometries must be Point"
  assert lamp_gdf.geometry.is_valid.all(), "All lamp geometries must be valid"
  assert len(lamp_gdf["osm_id"].unique()) == EXPECTED_LAMP_COUNT


def test_pedestrian_crossings_integrity():
  """Verifies counts, tags, and coordinates for pedestrian crossings."""
  crossing_gdf = gpd.read_file(CROSSING_GEOJSON, engine="pyogrio")
  assert (
      len(crossing_gdf) == EXPECTED_CROSSING_COUNT
  ), f"Crossing count mismatch: {len(crossing_gdf)} != {EXPECTED_CROSSING_COUNT}"
  assert (
      crossing_gdf.crs.to_epsg() == 4326
  ), f"Crossing CRS should be EPSG:4326, got {crossing_gdf.crs}"
  assert (
      crossing_gdf.geom_type == "Point"
  ).all(), "All crossing geometries must be Point"
  assert crossing_gdf.geometry.is_valid.all(), (
      "All crossing geometries must be valid"
  )
  assert len(crossing_gdf["osm_id"].unique()) == EXPECTED_CROSSING_COUNT

  sample_tags = json.loads(crossing_gdf["all_tags"].iloc[0])
  assert isinstance(sample_tags, dict)
  assert sample_tags.get("highway") == "crossing"


def test_geographic_consistency_with_delhi_boundary():
  """Verifies geographic consistency of point fixtures with the validated Delhi boundary envelope."""
  bnd_gdf = gpd.read_file(BOUNDARY_GEOJSON)
  minx, miny, maxx, maxy = bnd_gdf.total_bounds
  buffer = 0.05  # ~5 km

  lamp_gdf = gpd.read_file(LAMP_GEOJSON, engine="pyogrio")
  assert ((minx - buffer) <= lamp_gdf.geometry.x).all()
  assert (lamp_gdf.geometry.x <= (maxx + buffer)).all()
  assert ((miny - buffer) <= lamp_gdf.geometry.y).all()
  assert (lamp_gdf.geometry.y <= (maxy + buffer)).all()

  crossing_gdf = gpd.read_file(CROSSING_GEOJSON, engine="pyogrio")
  assert ((minx - buffer) <= crossing_gdf.geometry.x).all()
  assert (crossing_gdf.geometry.x <= (maxx + buffer)).all()
  assert ((miny - buffer) <= crossing_gdf.geometry.y).all()
  assert (crossing_gdf.geometry.y <= (maxy + buffer)).all()


def test_metadata_record_validity():
  """Verifies completeness, checksums, and limitations in the extraction metadata JSON."""
  assert METADATA_JSON.exists(), f"Metadata JSON missing: {METADATA_JSON}"
  with open(METADATA_JSON, "r", encoding="utf-8") as f:
    meta = json.load(f)

  assert meta["source_pbf"]["md5_checksum"] == "ada375536d08cd90a66d83b54d26882d"
  assert (
      meta["layers"]["delhi_road_network"]["feature_count"]
      == EXPECTED_ROAD_COUNT
  )
  assert (
      meta["layers"]["delhi_pedestrian_network"]["feature_count"]
      == EXPECTED_PED_COUNT
  )
  assert (
      meta["layers"]["delhi_lighting_fixtures"]["feature_count"]
      == EXPECTED_LAMP_COUNT
  )
  assert (
      meta["layers"]["delhi_pedestrian_crossings"]["feature_count"]
      == EXPECTED_CROSSING_COUNT
  )

  for layer_name in meta["layers"]:
    assert (
        meta["layers"][layer_name]["missing_geometries"] == 0
    ), f"Missing geometries in {layer_name}"

  assert "known_limitations" in meta
  assert (
      "boundary_crossing_ways_without_interior_nodes"
      in meta["known_limitations"]
  )
  assert "lighting_coverage_limitation" in meta["known_limitations"]


# ==============================================================================
# 3. INTERMEDIATE ROAD DATASET INTEGRATION TESTS (GATED ON LOCAL GEOJSON)
# ==============================================================================


@ROAD_DATA_REQUIRED
def test_road_network_layer_integrity():
  """Verifies feature counts, CRS, geometry validity, and unique IDs on the 124 MB road network."""
  assert ROAD_GEOJSON.stat().st_size >= 50_000_000
  road_gdf = gpd.read_file(ROAD_GEOJSON, engine="pyogrio")
  assert (
      len(road_gdf) == EXPECTED_ROAD_COUNT
  ), f"Road count mismatch: {len(road_gdf)} != {EXPECTED_ROAD_COUNT}"
  assert (
      road_gdf.crs.to_epsg() == 4326
  ), f"Road CRS should be EPSG:4326, got {road_gdf.crs}"
  assert (
      road_gdf.geom_type == "LineString"
  ).all(), "All road geometries must be LineString"
  assert road_gdf.geometry.is_valid.all(), "All road geometries must be valid"
  assert "osm_id" in road_gdf.columns
  assert len(road_gdf["osm_id"].unique()) == EXPECTED_ROAD_COUNT

  sample_tags = json.loads(road_gdf["all_tags"].iloc[0])
  assert isinstance(sample_tags, dict)
  assert "highway" in sample_tags


@ROAD_DATA_REQUIRED
def test_road_lighting_classification_distinguishability():
  """
  Verifies that road lighting tags are distinctly partitioned into 'yes', 'no', 'limited', and 'unknown'.
  Strictly asserts that missing tags are classified as 'unknown' and NEVER imputed as 'no'.
  """
  road_gdf = gpd.read_file(ROAD_GEOJSON, engine="pyogrio")
  assert "lit_status" in road_gdf.columns

  lit_counts = road_gdf["lit_status"].value_counts().to_dict()
  assert "unknown" in lit_counts
  assert "yes" in lit_counts
  assert "no" in lit_counts

  missing_lit_mask = road_gdf["lit"].isna() | (road_gdf["lit"] == "")
  assert (road_gdf.loc[missing_lit_mask, "lit_status"] == "unknown").all(), (
      "Fatal defect: Missing lighting tag was not classified as 'unknown'!"
  )
  assert not (road_gdf.loc[missing_lit_mask, "lit_status"] == "no").any(), (
      "Fatal defect: Missing lighting tag was converted to 'no' (unlit)!"
  )


@ROAD_DATA_REQUIRED
def test_road_way_topology_and_node_references():
  """Verifies that start_node, end_node, and node_refs are populated for topological graph builds."""
  road_gdf = gpd.read_file(ROAD_GEOJSON, engine="pyogrio")
  assert "start_node" in road_gdf.columns
  assert "end_node" in road_gdf.columns
  assert "node_refs" in road_gdf.columns

  assert (
      road_gdf["start_node"].notna().all()
  ), "start_node must be populated for all roads"
  assert (
      road_gdf["end_node"].notna().all()
  ), "end_node must be populated for all roads"

  sample_refs = [int(x) for x in road_gdf["node_refs"].iloc[0].split(",")]
  assert isinstance(sample_refs, list), "node_refs must parse as a list"
  assert (
      len(sample_refs) >= 2
  ), "LineString must have at least 2 node references"
  assert sample_refs[0] == road_gdf["start_node"].iloc[0]
  assert sample_refs[-1] == road_gdf["end_node"].iloc[0]
