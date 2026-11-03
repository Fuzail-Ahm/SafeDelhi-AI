"""H3 Spatial Grid Generator and Tessellation Module for SafeDelhi AI.

Generates an Uber H3 hexagonal discrete global grid (default resolution 8)
over the National Capital Territory of Delhi.

Key capabilities:
1. Differentiates between:
   - Hexagons whose centroids lie strictly inside Delhi.
   - Hexagons intersecting the Delhi outer boundary.
2. Produces two distinct GeoJSON layers:
   - Full hexagonal grid (for spatial indexing, spatial joins, and neighbors).
   - Clipped hexagonal grid (strictly bounded to Delhi boundary for clean visualization).
3. Preserves original H3 cell IDs across both representations.
4. Generates and persists comprehensive reproducibility metadata.
"""

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd
import h3
import pandas as pd
import shapely
from shapely.geometry import Polygon, MultiPolygon, Point, mapping
from shapely.validation import make_valid

from config import (
    DELHI_BOUNDARY_PATH,
    GRID_GEOJSON_PATH,
    GRID_CLIPPED_GEOJSON_PATH,
    METADATA_PATH,
    H3_RESOLUTION,
)
from src.utils.logger import setup_logger

logger = setup_logger("grid_generator")


def _gather_environment_metadata() -> Dict[str, str]:
    """Captures runtime environment and dependency versions for reproducibility."""
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "h3_version": h3.__version__,
        "geopandas_version": gpd.__version__,
        "shapely_version": shapely.__version__,
        "pandas_version": pd.__version__,
    }


def generate_delhi_grid(
    resolution: int = H3_RESOLUTION,
    boundary_path: Path = DELHI_BOUNDARY_PATH,
    force_refresh: bool = False,
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, Dict[str, Any]]:
    """Generates full and boundary-clipped H3 hexagonal grids for Delhi.

    Args:
        resolution: H3 resolution level (default 8).
        boundary_path: Path to validated Delhi boundary GeoJSON.
        force_refresh: Overwrite cached files if True.

    Returns:
        Tuple containing:
        - full_grid_gdf: GeoDataFrame with full hexagonal geometries.
        - clipped_grid_gdf: GeoDataFrame with boundary-clipped geometries.
        - metadata: Dictionary containing configuration and execution statistics.
    """
    GRID_GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    if (
        not force_refresh
        and GRID_GEOJSON_PATH.exists()
        and GRID_CLIPPED_GEOJSON_PATH.exists()
        and METADATA_PATH.exists()
    ):
        logger.info("Loading precomputed H3 grid from cache...")
        full_grid = gpd.read_file(GRID_GEOJSON_PATH)
        clipped_grid = gpd.read_file(GRID_CLIPPED_GEOJSON_PATH)
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        return full_grid, clipped_grid, metadata

    logger.info(f"Generating H3 grid at Resolution {resolution} for Delhi...")
    if not boundary_path.exists():
        raise FileNotFoundError(
            f"Boundary file not found at {boundary_path}. Run boundary_loader first."
        )

    boundary_gdf = gpd.read_file(boundary_path)
    delhi_geom = boundary_gdf.geometry.iloc[0]
    if not delhi_geom.is_valid:
        delhi_geom = make_valid(delhi_geom)

    # 1. Polyfill interior cells (centroids inside boundary)
    poly_dict = mapping(delhi_geom)
    initial_cells = set(h3.polyfill(poly_dict, resolution, geo_json_conformant=True))
    logger.info(f"Polyfilled cells with centroids inside Delhi: {len(initial_cells)}")

    # 2. Expand with 1-ring neighbors to capture all intersecting boundary cells
    candidate_cells = set(initial_cells)
    for c in initial_cells:
        for neighbor in h3.k_ring(c, 1):
            candidate_cells.add(neighbor)
    logger.info(f"Total candidate cells after 1-ring expansion: {len(candidate_cells)}")

    full_cells_records = []
    clipped_cells_records = []

    for cell_id in sorted(candidate_cells):
        # Coordinates in GeoJSON order: [(lon, lat), ...]
        coords = h3.h3_to_geo_boundary(cell_id, geo_json=True)
        hex_poly = Polygon(coords)
        if not hex_poly.is_valid:
            hex_poly = make_valid(hex_poly)

        # Check intersection with Delhi boundary
        if not hex_poly.intersects(delhi_geom):
            continue

        lat, lon = h3.h3_to_geo(cell_id)
        centroid_point = Point(lon, lat)

        centroid_within = centroid_point.within(delhi_geom)
        is_interior = hex_poly.within(delhi_geom)
        is_boundary = not is_interior

        # Clipped geometry for visualization
        clipped_geom = hex_poly.intersection(delhi_geom)
        if not clipped_geom.is_valid:
            clipped_geom = make_valid(clipped_geom)

        base_record = {
            "cell_id": str(cell_id),
            "resolution": int(resolution),
            "centroid_lat": round(float(lat), 6),
            "centroid_lon": round(float(lon), 6),
            "centroid_within_delhi": bool(centroid_within),
            "intersects_delhi": True,
            "is_interior_cell": bool(is_interior),
            "is_boundary_cell": bool(is_boundary),
        }

        # Full hexagon record
        full_record = dict(base_record)
        full_record["geometry"] = hex_poly
        full_cells_records.append(full_record)

        # Clipped hexagon record (preserving original cell_id!)
        if not clipped_geom.is_empty:
            clipped_record = dict(base_record)
            clipped_record["geometry"] = clipped_geom
            clipped_cells_records.append(clipped_record)

    full_grid_gdf = gpd.GeoDataFrame(full_cells_records, crs="EPSG:4326")
    clipped_grid_gdf = gpd.GeoDataFrame(clipped_cells_records, crs="EPSG:4326")

    # Calculate metric areas using UTM Zone 43N (EPSG:32643)
    full_utm = full_grid_gdf.to_crs("EPSG:32643")
    clipped_utm = clipped_grid_gdf.to_crs("EPSG:32643")
    delhi_utm = boundary_gdf.to_crs("EPSG:32643")

    full_grid_gdf["full_area_sqkm"] = (full_utm.geometry.area / 1e6).round(4)
    clipped_grid_gdf["clipped_area_sqkm"] = (clipped_utm.geometry.area / 1e6).round(4)
    clipped_grid_gdf["full_area_sqkm"] = full_grid_gdf.set_index("cell_id")["full_area_sqkm"].loc[
        clipped_grid_gdf["cell_id"]
    ].values
    clipped_grid_gdf["coverage_ratio"] = (
        clipped_grid_gdf["clipped_area_sqkm"] / clipped_grid_gdf["full_area_sqkm"]
    ).round(4)

    total_cells = len(full_grid_gdf)
    centroid_in_count = int(full_grid_gdf["centroid_within_delhi"].sum())
    boundary_cells_count = int(full_grid_gdf["is_boundary_cell"].sum())
    interior_cells_count = int(full_grid_gdf["is_interior_cell"].sum())
    delhi_area_sqkm = float(delhi_utm.geometry.iloc[0].area / 1e6)
    sum_clipped_area_sqkm = float(clipped_utm.geometry.area.sum() / 1e6)

    logger.info(f"Grid Generation Complete:")
    logger.info(f"  Total Intersecting Cells: {total_cells}")
    logger.info(f"  Cells with Centroid in Delhi: {centroid_in_count}")
    logger.info(f"  Strictly Interior Cells: {interior_cells_count}")
    logger.info(f"  Boundary Intersecting Cells: {boundary_cells_count}")
    logger.info(f"  Delhi Boundary Area: {delhi_area_sqkm:.2f} sq km")
    logger.info(f"  Sum of Clipped Cells Area: {sum_clipped_area_sqkm:.2f} sq km")

    # Persist files
    full_grid_gdf.to_file(GRID_GEOJSON_PATH, driver="GeoJSON")
    clipped_grid_gdf.to_file(GRID_CLIPPED_GEOJSON_PATH, driver="GeoJSON")
    logger.info(f"Saved full grid to {GRID_GEOJSON_PATH}")
    logger.info(f"Saved clipped grid to {GRID_CLIPPED_GEOJSON_PATH}")

    # Compile reproducibility metadata
    metadata = {
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "h3_resolution": resolution,
            "nominal_edge_length_meters": 461,
            "nominal_hex_area_sqkm": 0.737,
            "boundary_source_file": str(boundary_path.name),
            "utm_crs_for_metric_calculations": "EPSG:32643 (UTM Zone 43N)",
        },
        "grid_statistics": {
            "total_intersecting_cells": total_cells,
            "cells_with_centroid_inside": centroid_in_count,
            "strictly_interior_cells": interior_cells_count,
            "boundary_cells": boundary_cells_count,
            "delhi_boundary_area_sqkm": round(delhi_area_sqkm, 4),
            "sum_clipped_cells_area_sqkm": round(sum_clipped_area_sqkm, 4),
            "area_coverage_concordance_pct": round(
                (sum_clipped_area_sqkm / delhi_area_sqkm) * 100.0, 4
            ),
        },
        "environment": _gather_environment_metadata(),
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved reproducibility metadata to {METADATA_PATH}")

    return full_grid_gdf, clipped_grid_gdf, metadata


if __name__ == "__main__":
    full_g, clipped_g, meta = generate_delhi_grid(force_refresh=True)
    print("Successfully generated Delhi H3 grid!")
    print(f"Total cells: {meta['grid_statistics']['total_intersecting_cells']}")
    print(f"Coverage concordance: {meta['grid_statistics']['area_coverage_concordance_pct']}%")
