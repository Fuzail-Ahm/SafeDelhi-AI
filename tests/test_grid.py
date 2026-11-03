"""Unit and spatial validation tests for H3 grid generation."""

import json
from pathlib import Path
import geopandas as gpd
import h3
import pytest

from config import (
    GRID_GEOJSON_PATH,
    GRID_CLIPPED_GEOJSON_PATH,
    METADATA_PATH,
    DELHI_BOUNDARY_PATH,
    H3_RESOLUTION,
)


def test_grid_files_exist():
    """Verifies that full grid, clipped grid, and metadata files exist."""
    assert GRID_GEOJSON_PATH.exists(), f"Missing full grid at {GRID_GEOJSON_PATH}"
    assert GRID_CLIPPED_GEOJSON_PATH.exists(), f"Missing clipped grid at {GRID_CLIPPED_GEOJSON_PATH}"
    assert METADATA_PATH.exists(), f"Missing metadata at {METADATA_PATH}"


def test_grid_cell_counts_and_classification():
    """Verifies cell counts, interior vs boundary partitions, and centroid checks."""
    full_grid = gpd.read_file(GRID_GEOJSON_PATH)
    assert not full_grid.empty, "Full grid GeoDataFrame is empty."
    
    # Expected cells for Delhi NCT at Res 8 is between 2,000 and 2,200
    total_cells = len(full_grid)
    assert 2000 <= total_cells <= 2200, f"Unexpected total cell count: {total_cells}"
    
    interior_count = full_grid["is_interior_cell"].sum()
    boundary_count = full_grid["is_boundary_cell"].sum()
    centroid_in_count = full_grid["centroid_within_delhi"].sum()
    
    assert interior_count + boundary_count == total_cells, "Interior + boundary count mismatch."
    assert 1700 <= interior_count <= 1850, f"Unexpected interior cell count: {interior_count}"
    assert 250 <= boundary_count <= 350, f"Unexpected boundary cell count: {boundary_count}"
    assert 1900 <= centroid_in_count <= 2000, f"Unexpected centroid-inside count: {centroid_in_count}"


def test_h3_cell_ids_validity_and_resolution():
    """Verifies that all cell_ids are valid H3 indexes matching the configured resolution."""
    full_grid = gpd.read_file(GRID_GEOJSON_PATH)
    for cell_id in full_grid["cell_id"]:
        assert h3.h3_is_valid(cell_id), f"Invalid H3 cell ID: {cell_id}"
        res = h3.h3_get_resolution(cell_id)
        assert res == H3_RESOLUTION, f"Cell {cell_id} has resolution {res}, expected {H3_RESOLUTION}"


def test_clipped_grid_preserves_cell_ids():
    """Verifies that clipped visualization cells preserve original H3 cell IDs."""
    full_grid = gpd.read_file(GRID_GEOJSON_PATH)
    clipped_grid = gpd.read_file(GRID_CLIPPED_GEOJSON_PATH)
    
    full_ids = set(full_grid["cell_id"])
    clipped_ids = set(clipped_grid["cell_id"])
    
    # Every clipped cell must exist in the full grid
    assert clipped_ids.issubset(full_ids), "Clipped grid contains unknown cell IDs."
    # Every cell intersecting Delhi should have a non-empty clipped geometry
    assert len(clipped_ids) == len(full_ids), "Count mismatch between clipped and full cells."


def test_no_empty_or_invalid_geometries():
    """Verifies that neither full nor clipped grid contains null or invalid geometries."""
    full_grid = gpd.read_file(GRID_GEOJSON_PATH)
    clipped_grid = gpd.read_file(GRID_CLIPPED_GEOJSON_PATH)
    
    assert not full_grid.geometry.isnull().any(), "Full grid contains null geometries."
    assert not full_grid.geometry.is_empty.any(), "Full grid contains empty geometries."
    assert full_grid.geometry.is_valid.all(), "Full grid contains invalid geometries."
    
    assert not clipped_grid.geometry.isnull().any(), "Clipped grid contains null geometries."
    assert not clipped_grid.geometry.is_empty.any(), "Clipped grid contains empty geometries."
    assert clipped_grid.geometry.is_valid.all(), "Clipped grid contains invalid geometries."


def test_area_concordance_and_coverage():
    """Verifies that the sum of clipped cell areas equals the Delhi boundary area."""
    boundary_gdf = gpd.read_file(DELHI_BOUNDARY_PATH)
    clipped_grid = gpd.read_file(GRID_CLIPPED_GEOJSON_PATH)
    
    delhi_area = boundary_gdf.to_crs("EPSG:32643").geometry.iloc[0].area / 1e6
    clipped_area_sum = clipped_grid.to_crs("EPSG:32643").geometry.area.sum() / 1e6
    
    diff = abs(delhi_area - clipped_area_sum)
    diff_pct = (diff / delhi_area) * 100.0
    
    # Area difference must be less than 0.01%
    assert diff_pct < 0.01, f"Area coverage discrepancy: {diff_pct:.4f}% ({diff:.4f} sq km difference)"


def test_grid_topological_union_and_overlap():
    """Verifies topological union completeness and zero inter-cell overlap."""
    boundary_gdf = gpd.read_file(DELHI_BOUNDARY_PATH).to_crs("EPSG:32643")
    clipped_grid = gpd.read_file(GRID_CLIPPED_GEOJSON_PATH).to_crs("EPSG:32643")
    
    delhi_poly = boundary_gdf.geometry.iloc[0]
    grid_union = clipped_grid.geometry.union_all()
    
    # Missing gaps between boundary and grid union
    missing_gaps_sqm = delhi_poly.difference(grid_union).area
    # Inter-cell overlap: sum of individual areas minus union area
    overlap_sqm = clipped_grid.geometry.area.sum() - grid_union.area
    # Symmetric difference
    sym_diff_sqm = delhi_poly.symmetric_difference(grid_union).area
    
    # Missing gaps must be negligible (< 500 sq m across 1.48B sq m, < 0.00005%)
    assert missing_gaps_sqm < 500.0, f"Missing gaps {missing_gaps_sqm:.2f} sq m exceed tolerance"
    # Inter-cell overlap must be virtually zero (< 1.0 sq m)
    assert abs(overlap_sqm) < 1.0, f"Unexpected inter-cell overlap {overlap_sqm:.2f} sq m"
    # Total symmetric difference must be negligible (< 500 sq m)
    assert sym_diff_sqm < 500.0, f"Symmetric difference {sym_diff_sqm:.2f} sq m exceeds tolerance"


def test_h3_neighbor_geodesic_distances():
    """Verifies empirical geodesic neighbor distances for H3 Res 8 across Delhi."""
    import pyproj
    import numpy as np
    
    full_grid = gpd.read_file(GRID_GEOJSON_PATH)
    cell_set = set(full_grid["cell_id"])
    geod = pyproj.Geod(ellps="WGS84")
    
    # Sample 50 cells and measure distance to all valid neighbors
    distances = []
    for cell in list(cell_set)[:50]:
        lat1, lon1 = h3.h3_to_geo(cell)
        for n in h3.hex_ring(cell, 1):
            if n in cell_set:
                lat2, lon2 = h3.h3_to_geo(n)
                _, _, d = geod.inv(lon1, lat1, lon2, lat2)
                distances.append(d)
                
    assert len(distances) > 0, "No adjacent neighbor pairs found."
    mean_dist = float(np.mean(distances))
    min_dist = float(np.min(distances))
    max_dist = float(np.max(distances))
    
    # In Delhi, adjacent centroid spacing is 920m - 970m (mean ~940m)
    assert 920.0 <= min_dist <= 940.0, f"Unexpected min neighbor distance: {min_dist:.2f} m"
    assert 950.0 <= max_dist <= 970.0, f"Unexpected max neighbor distance: {max_dist:.2f} m"
    assert 930.0 <= mean_dist <= 950.0, f"Unexpected mean neighbor distance: {mean_dist:.2f} m"


def test_reproducibility_metadata():
    """Verifies that reproducibility metadata file contains all required tracking fields."""
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    assert "configuration" in meta, "Missing configuration section in metadata."
    assert "grid_statistics" in meta, "Missing grid_statistics in metadata."
    assert "environment" in meta, "Missing environment in metadata."
    
    assert meta["configuration"]["h3_resolution"] == H3_RESOLUTION
    assert meta["grid_statistics"]["total_intersecting_cells"] == 2093
    assert meta["grid_statistics"]["area_coverage_concordance_pct"] == 100.0
    
    env = meta["environment"]
    for key in ["python_version", "h3_version", "geopandas_version", "shapely_version", "pandas_version"]:
        assert key in env and len(env[key]) > 0, f"Missing {key} in environment metadata."
