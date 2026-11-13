"""
SafeDelhi AI — Phase 2B Step 2B: H3 Environmental Infrastructure Indicator Aggregation.

Aggregates linear and point infrastructure layers from OpenStreetMap into the validated
Delhi Uber H3 Resolution 8 spatial grid (2,093 cells).

Key Invariants:
1. Exact Line Intersection: Line features are projected to EPSG:32643 (UTM 43N) and
   intersected with cell boundaries. Length is computed strictly inside each cell.
   No midpoint/centroid approximation; zero double-counting across cells.
2. 4-State Lighting Invariant:
   road_lit_confirmed + road_lit_unlit + road_lit_limited + road_lit_unknown == road_total_length
   Missing lighting tags are strictly classified as 'unknown' and never converted to 'no'.
3. Point Exclusivity: Every street lamp and crossing point is assigned to at most ONE cell.
4. Total Cell Preservation: All 2,093 cells are preserved; zero infrastructure cells have 0.0.
5. Separation of Concerns: Measured absence is recorded as 0.0; unknown attributes are kept distinct.
"""

from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

# Default Paths
DEFAULT_GRID_PATH = "data/processed/delhi_grid_res8_clipped.geojson"
DEFAULT_ROAD_PATH = "data/processed/delhi_road_network.geojson"
DEFAULT_PED_PATH = "data/processed/delhi_pedestrian_network.geojson"
DEFAULT_LAMP_PATH = "data/processed/delhi_lighting_fixtures.geojson"
DEFAULT_CROSSING_PATH = "data/processed/delhi_pedestrian_crossings.geojson"
DEFAULT_OUTPUT_GEOJSON = (
    "data/processed/delhi_h3_environmental_indicators.geojson"
)
DEFAULT_METADATA_JSON = "data/processed/h3_indicator_metadata.json"

METRIC_CRS = "EPSG:32643"  # UTM Zone 43N (metres)
WGS84_CRS = "EPSG:4326"

# Road Hierarchy Normalization
ROAD_HIERARCHY_MAP = {
    "residential": "residential",
    "service": "service",
    "living_street": "living_street",
    "tertiary": "tertiary",
    "tertiary_link": "tertiary",
    "secondary": "secondary",
    "secondary_link": "secondary",
    "primary": "primary",
    "primary_link": "primary",
    "trunk": "trunk",
    "trunk_link": "trunk",
    "motorway": "motorway",
    "motorway_link": "motorway",
    "unclassified": "unclassified",
}

ROAD_HIERARCHY_CLASSES = [
    "residential",
    "service",
    "living_street",
    "tertiary",
    "secondary",
    "primary",
    "trunk",
    "motorway",
    "unclassified",
]

PEDESTRIAN_CLASSES = [
    "dedicated_footway",
    "shared_path",
    "track",
    "indoor_corridor",
    "cycleway",
    "bridleway",
]

LIGHTING_STATES = ["yes", "no", "limited", "unknown"]


def compute_file_hashes(file_path: Path) -> Tuple[str, str, int]:
  """Computes MD5 and SHA-256 checksums and returns file size."""
  md5 = hashlib.md5()
  sha256 = hashlib.sha256()
  size_bytes = 0
  with open(file_path, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
      md5.update(chunk)
      sha256.update(chunk)
      size_bytes += len(chunk)
  return md5.hexdigest(), sha256.hexdigest(), size_bytes


def aggregate_road_network(
    road_gdf: gpd.GeoDataFrame,
    grid_32643: gpd.GeoDataFrame,
) -> pd.DataFrame:
  """Intersects vehicular roads with H3 cells in EPSG:32643.

  Computes total lengths, hierarchy breakdown, 4-state lighting lengths,
  and infrastructure attribute lengths (sidewalks, bridges, tunnels).
  """
  if road_gdf.empty:
    cols = (
        ["road_total_length_m"]
        + [f"road_{c}_length_m" for c in ROAD_HIERARCHY_CLASSES]
        + [
            "road_lit_confirmed_length_m",
            "road_lit_unlit_length_m",
            "road_lit_limited_length_m",
            "road_lit_unknown_length_m",
            "road_sidewalk_length_m",
            "road_bridge_length_m",
            "road_tunnel_length_m",
        ]
    )
    return pd.DataFrame(columns=cols, index=pd.Index([], name="cell_id"))

  # Overlay intersection
  inter = gpd.overlay(road_gdf, grid_32643, how="intersection")
  inter["seg_len_m"] = inter.geometry.length

  # Filter out degenerated segments (e.g. point intersections)
  inter = inter[inter["seg_len_m"] > 0]

  # 1. Total road length
  road_tot = (
      inter.groupby("cell_id")["seg_len_m"].sum().rename("road_total_length_m")
  )

  # 2. Road Hierarchy breakdown
  inter["norm_hw"] = (
      inter["highway"].map(ROAD_HIERARCHY_MAP).fillna("unclassified")
  )
  road_hw_pivot = inter.pivot_table(
      index="cell_id",
      columns="norm_hw",
      values="seg_len_m",
      aggfunc="sum",
      fill_value=0.0,
  )
  for c in ROAD_HIERARCHY_CLASSES:
    if c not in road_hw_pivot.columns:
      road_hw_pivot[c] = 0.0
  road_hw = road_hw_pivot[ROAD_HIERARCHY_CLASSES].rename(
      columns={c: f"road_{c}_length_m" for c in ROAD_HIERARCHY_CLASSES}
  )

  # 3. 4-State Lighting breakdown
  road_lit_pivot = inter.pivot_table(
      index="cell_id",
      columns="lit_status",
      values="seg_len_m",
      aggfunc="sum",
      fill_value=0.0,
  )
  for s in LIGHTING_STATES:
    if s not in road_lit_pivot.columns:
      road_lit_pivot[s] = 0.0
  road_lit_rename = {
      "yes": "road_lit_confirmed_length_m",
      "no": "road_lit_unlit_length_m",
      "limited": "road_lit_limited_length_m",
      "unknown": "road_lit_unknown_length_m",
  }
  road_lit = road_lit_pivot[LIGHTING_STATES].rename(columns=road_lit_rename)

  # 4. Infrastructure features
  road_sw = (
      inter[inter["has_sidewalk"] == True]
      .groupby("cell_id")["seg_len_m"]
      .sum()
      .rename("road_sidewalk_length_m")
  )
  road_br = (
      inter[inter["is_bridge"] == True]
      .groupby("cell_id")["seg_len_m"]
      .sum()
      .rename("road_bridge_length_m")
  )
  road_tn = (
      inter[inter["is_tunnel"] == True]
      .groupby("cell_id")["seg_len_m"]
      .sum()
      .rename("road_tunnel_length_m")
  )

  # Combine into single DataFrame
  res = (
      road_tot.to_frame()
      .join(road_hw)
      .join(road_lit)
      .join(road_sw)
      .join(road_br)
      .join(road_tn)
      .fillna(0.0)
  )

  return res


def aggregate_pedestrian_network(
    ped_gdf: gpd.GeoDataFrame,
    grid_32643: gpd.GeoDataFrame,
) -> pd.DataFrame:
  """Intersects pedestrian paths with H3 cells in EPSG:32643.

  Computes total lengths, dedicated class breakdown, 4-state lighting lengths,
  and pedestrian bridges and tunnels.
  """
  if ped_gdf.empty:
    cols = (
        ["ped_total_length_m"]
        + [f"ped_{c}_length_m" for c in PEDESTRIAN_CLASSES]
        + [
            "ped_lit_confirmed_length_m",
            "ped_lit_unlit_length_m",
            "ped_lit_limited_length_m",
            "ped_lit_unknown_length_m",
            "ped_bridge_length_m",
            "ped_tunnel_length_m",
        ]
    )
    return pd.DataFrame(columns=cols, index=pd.Index([], name="cell_id"))

  # Overlay intersection
  inter = gpd.overlay(ped_gdf, grid_32643, how="intersection")
  inter["seg_len_m"] = inter.geometry.length
  inter = inter[inter["seg_len_m"] > 0]

  # 1. Total pedestrian length
  ped_tot = (
      inter.groupby("cell_id")["seg_len_m"].sum().rename("ped_total_length_m")
  )

  # 2. Pedestrian classes breakdown
  ped_cls_pivot = inter.pivot_table(
      index="cell_id",
      columns="pedestrian_class",
      values="seg_len_m",
      aggfunc="sum",
      fill_value=0.0,
  )
  for c in PEDESTRIAN_CLASSES:
    if c not in ped_cls_pivot.columns:
      ped_cls_pivot[c] = 0.0
  ped_cls = ped_cls_pivot[PEDESTRIAN_CLASSES].rename(
      columns={c: f"ped_{c}_length_m" for c in PEDESTRIAN_CLASSES}
  )

  # 3. 4-State Lighting breakdown
  ped_lit_pivot = inter.pivot_table(
      index="cell_id",
      columns="lit_status",
      values="seg_len_m",
      aggfunc="sum",
      fill_value=0.0,
  )
  for s in LIGHTING_STATES:
    if s not in ped_lit_pivot.columns:
      ped_lit_pivot[s] = 0.0
  ped_lit_rename = {
      "yes": "ped_lit_confirmed_length_m",
      "no": "ped_lit_unlit_length_m",
      "limited": "ped_lit_limited_length_m",
      "unknown": "ped_lit_unknown_length_m",
  }
  ped_lit = ped_lit_pivot[LIGHTING_STATES].rename(columns=ped_lit_rename)

  # 4. Infrastructure features
  ped_br = (
      inter[inter["is_bridge"] == True]
      .groupby("cell_id")["seg_len_m"]
      .sum()
      .rename("ped_bridge_length_m")
  )
  ped_tn = (
      inter[inter["is_tunnel"] == True]
      .groupby("cell_id")["seg_len_m"]
      .sum()
      .rename("ped_tunnel_length_m")
  )

  # Combine into single DataFrame
  res = (
      ped_tot.to_frame()
      .join(ped_cls)
      .join(ped_lit)
      .join(ped_br)
      .join(ped_tn)
      .fillna(0.0)
  )

  return res


def aggregate_points_to_grid(
    points_gdf: gpd.GeoDataFrame,
    grid_32643: gpd.GeoDataFrame,
    col_name: str,
) -> Tuple[pd.Series, int]:
  """Spatially assigns point features to H3 cells using spatial intersection.

  Ensures strict point exclusivity: if a point lands on a boundary between cells,
  it is deduplicated so it counts in at most one cell.

  Returns (counts_series, unassigned_point_count).
  """
  if points_gdf.empty:
    return pd.Series(dtype=int, name=col_name), 0

  # Spatial join
  sj = gpd.sjoin(points_gdf, grid_32643, predicate="intersects", how="inner")

  # Deduplicate points that intersect shared cell borders (keep first occurrence)
  sj_dedup = sj[~sj.index.duplicated(keep="first")]

  unassigned_count = len(points_gdf) - len(sj_dedup)
  counts = sj_dedup.groupby("cell_id").size().rename(col_name)

  return counts, unassigned_count


def aggregate_h3_indicators(
    grid_path: str = DEFAULT_GRID_PATH,
    road_path: str = DEFAULT_ROAD_PATH,
    ped_path: str = DEFAULT_PED_PATH,
    lamp_path: str = DEFAULT_LAMP_PATH,
    crossing_path: str = DEFAULT_CROSSING_PATH,
    output_geojson: str = DEFAULT_OUTPUT_GEOJSON,
    output_metadata: str = DEFAULT_METADATA_JSON,
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
  """Executes the complete H3 indicator aggregation workflow and exports

  GeoJSON and JSON metadata artifacts.
  """
  t_start = time.time()
  start_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
  print(
      f"[{start_utc}] Initiating H3 Environmental Indicator Aggregation (Step"
      " 2B)"
  )

  # 1. Load Clipped H3 Grid
  grid_file = Path(grid_path)
  if not grid_file.exists():
    raise FileNotFoundError(f"Clipped grid file not found at: {grid_file}")
  grid_gdf = gpd.read_file(grid_file)
  total_cells = len(grid_gdf)
  print(f"Loaded H3 Grid: {total_cells:,} cells from {grid_file}")

  grid_32643 = grid_gdf[["cell_id", "geometry"]].to_crs(METRIC_CRS)

  # 2. Load Infrastructure Layers
  road_file = Path(road_path)
  ped_file = Path(ped_path)
  lamp_file = Path(lamp_path)
  crossing_file = Path(crossing_path)

  for p in (road_file, ped_file, lamp_file, crossing_file):
    if not p.exists():
      raise FileNotFoundError(f"Required layer file not found at: {p}")

  print("Loading and reprojecting infrastructure layers to EPSG:32643...")
  road_gdf = gpd.read_file(road_file).to_crs(METRIC_CRS)
  ped_gdf = gpd.read_file(ped_file).to_crs(METRIC_CRS)
  lamp_gdf = gpd.read_file(lamp_file).to_crs(METRIC_CRS)
  crossing_gdf = gpd.read_file(crossing_file).to_crs(METRIC_CRS)

  print(
      f"  Roads: {len(road_gdf):,} ways | Pedestrian: {len(ped_gdf):,} ways |"
      f" Lamps: {len(lamp_gdf):,} nodes | Crossings: {len(crossing_gdf):,} nodes"
  )

  # Record source hashes
  src_hashes = {
      "grid": compute_file_hashes(grid_file),
      "road": compute_file_hashes(road_file),
      "pedestrian": compute_file_hashes(ped_file),
      "lighting_fixtures": compute_file_hashes(lamp_file),
      "pedestrian_crossings": compute_file_hashes(crossing_file),
  }

  # 3. Aggregate Road Network
  print("\n--- Aggregating Road Network Lines ---")
  t0 = time.time()
  road_df = aggregate_road_network(road_gdf, grid_32643)
  print(
      f"  Road aggregation completed in {time.time()-t0:.2f}s across"
      f" {len(road_df):,} active cells"
  )

  # 4. Aggregate Pedestrian Network
  print("\n--- Aggregating Pedestrian Network Lines ---")
  t0 = time.time()
  ped_df = aggregate_pedestrian_network(ped_gdf, grid_32643)
  print(
      f"  Pedestrian aggregation completed in {time.time()-t0:.2f}s across"
      f" {len(ped_df):,} active cells"
  )

  # 5. Aggregate Point Indicators
  print("\n--- Aggregating Point Infrastructure ---")
  t0 = time.time()
  lamp_counts, unassigned_lamps = aggregate_points_to_grid(
      lamp_gdf, grid_32643, "street_lamp_count"
  )
  crossing_counts, unassigned_crossings = aggregate_points_to_grid(
      crossing_gdf, grid_32643, "pedestrian_crossing_count"
  )
  print(
      f"  Points aggregated in {time.time()-t0:.2f}s: "
      f"{lamp_counts.sum():,} lamps assigned ({unassigned_lamps} unassigned outside boundary), "
      f"{crossing_counts.sum():,} crossings assigned ({unassigned_crossings} unassigned outside boundary)"
  )

  # 6. Join All Indicators to the H3 Grid
  print("\n--- Joining Indicators to Master H3 Grid ---")
  df = grid_gdf.copy().set_index("cell_id")

  # Join line tables
  df = df.join(road_df).join(ped_df)

  # Join point tables
  df = df.join(lamp_counts).join(crossing_counts)

  # Fill measured absence with 0
  for col in df.columns:
    if col.endswith("_length_m"):
      df[col] = df[col].fillna(0.0).round(2)
    elif col in ("street_lamp_count", "pedestrian_crossing_count"):
      df[col] = df[col].fillna(0).astype(int)

  # Compute Lighting and Infrastructure Ratios
  # Road lighting ratios
  road_len = df["road_total_length_m"]
  df["road_lit_ratio"] = np.where(
      road_len > 0,
      (df["road_lit_confirmed_length_m"] / road_len).round(4),
      0.0,
  )
  df["road_lit_unknown_ratio"] = np.where(
      road_len > 0,
      (df["road_lit_unknown_length_m"] / road_len).round(4),
      0.0,
  )

  # Pedestrian lighting ratios
  ped_len = df["ped_total_length_m"]
  df["ped_lit_ratio"] = np.where(
      ped_len > 0,
      (df["ped_lit_confirmed_length_m"] / ped_len).round(4),
      0.0,
  )
  df["ped_lit_unknown_ratio"] = np.where(
      ped_len > 0,
      (df["ped_lit_unknown_length_m"] / ped_len).round(4),
      0.0,
  )

  # Density Indicators (per km^2 of clipped cell area)
  area = df["clipped_area_sqkm"]
  df["road_density_km_per_sqkm"] = np.where(
      area > 0,
      ((df["road_total_length_m"] / 1000.0) / area).round(2),
      0.0,
  )
  df["ped_density_km_per_sqkm"] = np.where(
      area > 0,
      ((df["ped_total_length_m"] / 1000.0) / area).round(2),
      0.0,
  )
  df["street_lamp_density_per_sqkm"] = np.where(
      area > 0,
      (df["street_lamp_count"] / area).round(2),
      0.0,
  )
  df["pedestrian_crossing_density_per_sqkm"] = np.where(
      area > 0,
      (df["pedestrian_crossing_count"] / area).round(2),
      0.0,
  )

  # Reset index and convert back to GeoDataFrame in original CRS (EPSG:4326)
  df = df.reset_index()
  out_gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=grid_gdf.crs)

  # 7. Rigorous Mathematical Reconciliation & Quality Validations
  print("\n--- Executing Mathematical Quality & Invariant Validations ---")

  # Validation A: Total cell count preservation
  assert (
      len(out_gdf) == total_cells
  ), f"Cell count changed! Expected {total_cells}, got {len(out_gdf)}"
  assert (
      out_gdf["cell_id"].nunique() == total_cells
  ), "Duplicate or missing cell_id values detected!"
  assert set(out_gdf["cell_id"]) == set(
      grid_gdf["cell_id"]
  ), "Mismatch between output cell IDs and input grid IDs!"

  # Validation B: Road lighting reconciliation
  road_lit_sum = (
      out_gdf["road_lit_confirmed_length_m"]
      + out_gdf["road_lit_unlit_length_m"]
      + out_gdf["road_lit_limited_length_m"]
      + out_gdf["road_lit_unknown_length_m"]
  ).round(2)
  road_lit_diff = np.abs(road_lit_sum - out_gdf["road_total_length_m"])
  max_road_lit_error = float(road_lit_diff.max())
  assert max_road_lit_error <= 0.05, (
      f"Fatal: Road lighting sum discrepancy exceeds numerical tolerance: {max_road_lit_error} m"
  )

  # Validation C: Road hierarchy reconciliation
  road_hw_cols = [f"road_{c}_length_m" for c in ROAD_HIERARCHY_CLASSES]
  road_hw_sum = out_gdf[road_hw_cols].sum(axis=1).round(2)
  road_hw_diff = np.abs(road_hw_sum - out_gdf["road_total_length_m"])
  max_road_hw_error = float(road_hw_diff.max())
  assert max_road_hw_error <= 0.05, (
      f"Fatal: Road hierarchy sum discrepancy exceeds numerical tolerance: {max_road_hw_error} m"
  )

  # Validation D: Pedestrian lighting reconciliation
  ped_lit_sum = (
      out_gdf["ped_lit_confirmed_length_m"]
      + out_gdf["ped_lit_unlit_length_m"]
      + out_gdf["ped_lit_limited_length_m"]
      + out_gdf["ped_lit_unknown_length_m"]
  ).round(2)
  ped_lit_diff = np.abs(ped_lit_sum - out_gdf["ped_total_length_m"])
  max_ped_lit_error = float(ped_lit_diff.max())
  assert max_ped_lit_error <= 0.05, (
      f"Fatal: Pedestrian lighting sum discrepancy exceeds numerical tolerance: {max_ped_lit_error} m"
  )

  # Validation E: Pedestrian class reconciliation
  ped_cls_cols = [f"ped_{c}_length_m" for c in PEDESTRIAN_CLASSES]
  ped_cls_sum = out_gdf[ped_cls_cols].sum(axis=1).round(2)
  ped_cls_diff = np.abs(ped_cls_sum - out_gdf["ped_total_length_m"])
  max_ped_cls_error = float(ped_cls_diff.max())
  assert max_ped_cls_error <= 0.05, (
      f"Fatal: Pedestrian class sum discrepancy exceeds numerical tolerance: {max_ped_cls_error} m"
  )

  # Validation F: Point count conservation
  total_assigned_lamps = int(out_gdf["street_lamp_count"].sum())
  total_assigned_crossings = int(out_gdf["pedestrian_crossing_count"].sum())
  assert (
      total_assigned_lamps + unassigned_lamps == len(lamp_gdf)
  ), "Lamp count conservation mismatch!"
  assert (
      total_assigned_crossings + unassigned_crossings == len(crossing_gdf)
  ), "Crossing count conservation mismatch!"

  # Validation G: Geometry validity
  assert (
      out_gdf.geometry.is_valid.all()
  ), "Detected invalid geometries in aggregated output!"
  assert (
      ~out_gdf.geometry.is_empty
  ).all(), "Detected empty geometries in aggregated output!"

  print("All 7 mathematical and topological quality invariants PASSED.")

  # 8. Export GeoJSON Output
  out_geo_path = Path(output_geojson)
  out_geo_path.parent.mkdir(parents=True, exist_ok=True)
  print(f"\nWriting aggregated indicators to: {out_geo_path}...")
  out_gdf.to_file(out_geo_path, driver="GeoJSON", engine="pyogrio")
  out_geo_md5, out_geo_sha256, out_geo_bytes = compute_file_hashes(out_geo_path)
  print(
      f"  -> Successfully written: {out_geo_bytes:,} bytes"
      f" ({out_geo_bytes/(1024*1024):.2f} MB)"
  )

  # 9. Build Summary Provenance Metadata
  elapsed_sec = round(time.time() - t_start, 2)
  end_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

  # Calculate cell occupancy statistics
  cells_with_roads = int((out_gdf["road_total_length_m"] > 0).sum())
  cells_with_ped = int((out_gdf["ped_total_length_m"] > 0).sum())
  cells_with_lamps = int((out_gdf["street_lamp_count"] > 0).sum())
  cells_with_crossings = int((out_gdf["pedestrian_crossing_count"] > 0).sum())
  cells_with_zero_infra = int(
      (
          (out_gdf["road_total_length_m"] == 0)
          & (out_gdf["ped_total_length_m"] == 0)
          & (out_gdf["street_lamp_count"] == 0)
          & (out_gdf["pedestrian_crossing_count"] == 0)
      ).sum()
  )

  metadata: Dict[str, Any] = {
      "step": "Phase 2B Step 2B: H3 Environmental Indicator Aggregation",
      "aggregation_started_utc": start_utc,
      "aggregation_completed_utc": end_utc,
      "elapsed_seconds": elapsed_sec,
      "metric_crs": METRIC_CRS,
      "output_crs": WGS84_CRS,
      "grid": {
          "source_file": str(grid_file),
          "total_cells": total_cells,
          "resolution": 8,
          "md5_checksum": src_hashes["grid"][0],
          "sha256_checksum": src_hashes["grid"][1],
      },
      "source_layers": {
          "roads": {
              "path": str(road_file),
              "feature_count": len(road_gdf),
              "md5_checksum": src_hashes["road"][0],
              "sha256_checksum": src_hashes["road"][1],
          },
          "pedestrian": {
              "path": str(ped_file),
              "feature_count": len(ped_gdf),
              "md5_checksum": src_hashes["pedestrian"][0],
              "sha256_checksum": src_hashes["pedestrian"][1],
          },
          "lighting_fixtures": {
              "path": str(lamp_file),
              "feature_count": len(lamp_gdf),
              "md5_checksum": src_hashes["lighting_fixtures"][0],
              "sha256_checksum": src_hashes["lighting_fixtures"][1],
          },
          "pedestrian_crossings": {
              "path": str(crossing_file),
              "feature_count": len(crossing_gdf),
              "md5_checksum": src_hashes["pedestrian_crossings"][0],
              "sha256_checksum": src_hashes["pedestrian_crossings"][1],
          },
      },
      "spatial_totals": {
          "road_total_length_km": round(
              float(out_gdf["road_total_length_m"].sum() / 1000.0), 2
          ),
          "ped_total_length_km": round(
              float(out_gdf["ped_total_length_m"].sum() / 1000.0), 2
          ),
          "total_street_lamps_assigned": total_assigned_lamps,
          "total_pedestrian_crossings_assigned": total_assigned_crossings,
          "unassigned_lamps_outside_boundary": unassigned_lamps,
          "unassigned_crossings_outside_boundary": unassigned_crossings,
      },
      "road_hierarchy_distribution_km": {
          c: round(float(out_gdf[f"road_{c}_length_m"].sum() / 1000.0), 2)
          for c in ROAD_HIERARCHY_CLASSES
      },
      "pedestrian_class_distribution_km": {
          c: round(float(out_gdf[f"ped_{c}_length_m"].sum() / 1000.0), 2)
          for c in PEDESTRIAN_CLASSES
      },
      "road_lighting_distribution_km": {
          "confirmed_lit": round(
              float(out_gdf["road_lit_confirmed_length_m"].sum() / 1000.0), 2
          ),
          "confirmed_unlit": round(
              float(out_gdf["road_lit_unlit_length_m"].sum() / 1000.0), 2
          ),
          "limited": round(
              float(out_gdf["road_lit_limited_length_m"].sum() / 1000.0), 2
          ),
          "unknown": round(
              float(out_gdf["road_lit_unknown_length_m"].sum() / 1000.0), 2
          ),
      },
      "pedestrian_lighting_distribution_km": {
          "confirmed_lit": round(
              float(out_gdf["ped_lit_confirmed_length_m"].sum() / 1000.0), 2
          ),
          "confirmed_unlit": round(
              float(out_gdf["ped_lit_unlit_length_m"].sum() / 1000.0), 2
          ),
          "limited": round(
              float(out_gdf["ped_lit_limited_length_m"].sum() / 1000.0), 2
          ),
          "unknown": round(
              float(out_gdf["ped_lit_unknown_length_m"].sum() / 1000.0), 2
          ),
      },
      "cell_occupancy_metrics": {
          "total_cells": total_cells,
          "cells_with_roads": cells_with_roads,
          "cells_with_roads_pct": round(
              (cells_with_roads / total_cells) * 100, 2
          ),
          "cells_with_pedestrian_infra": cells_with_ped,
          "cells_with_pedestrian_infra_pct": round(
              (cells_with_ped / total_cells) * 100, 2
          ),
          "cells_with_street_lamps": cells_with_lamps,
          "cells_with_street_lamps_pct": round(
              (cells_with_lamps / total_cells) * 100, 2
          ),
          "cells_with_pedestrian_crossings": cells_with_crossings,
          "cells_with_pedestrian_crossings_pct": round(
              (cells_with_crossings / total_cells) * 100, 2
          ),
          "cells_with_zero_mapped_infrastructure": cells_with_zero_infra,
          "cells_with_zero_mapped_infrastructure_pct": round(
              (cells_with_zero_infra / total_cells) * 100, 2
          ),
      },
      "validation_invariants": {
          "max_road_lighting_reconciliation_error_m": max_road_lit_error,
          "max_road_hierarchy_reconciliation_error_m": max_road_hw_error,
          "max_ped_lighting_reconciliation_error_m": max_ped_lit_error,
          "max_ped_class_reconciliation_error_m": max_ped_cls_error,
          "point_conservation_verified": True,
          "geometry_validity_verified": True,
          "cell_id_concordance_verified": True,
      },
      "output_artifacts": {
          "geojson": {
              "path": str(out_geo_path),
              "size_bytes": out_geo_bytes,
              "feature_count": len(out_gdf),
              "column_count": len(out_gdf.columns),
              "md5_checksum": out_geo_md5,
              "sha256_checksum": out_geo_sha256,
          }
      },
      "library_versions": {
          "shapely": shapely.__version__,
          "geopandas": gpd.__version__,
          "pyogrio": getattr(pyogrio, "__version__", "unknown"),
          "pandas": pd.__version__,
          "numpy": np.__version__,
      },
  }

  out_meta_path = Path(output_metadata)
  with open(out_meta_path, "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)
    f.write("\n")
  print(f"Saved metadata record to: {out_meta_path}")

  return out_gdf, metadata


if __name__ == "__main__":
  gdf, meta = aggregate_h3_indicators()
  print("\n--- Summary Execution Stats ---")
  print(f"  H3 Grid Cells: {len(gdf):,}")
  print(f"  Total Road Network: {meta['spatial_totals']['road_total_length_km']:,} km")
  print(f"  Total Pedestrian Network: {meta['spatial_totals']['ped_total_length_km']:,} km")
  print(f"  Street Lamps Assigned: {meta['spatial_totals']['total_street_lamps_assigned']:,}")
  print(f"  Pedestrian Crossings Assigned: {meta['spatial_totals']['total_pedestrian_crossings_assigned']:,}")
  print(f"  Zero-Infrastructure Cells: {meta['cell_occupancy_metrics']['cells_with_zero_mapped_infrastructure']:,} ({meta['cell_occupancy_metrics']['cells_with_zero_mapped_infrastructure_pct']}%)")
