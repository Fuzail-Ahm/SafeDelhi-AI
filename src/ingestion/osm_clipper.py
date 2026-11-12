"""
SafeDelhi AI — Phase 2B, Step 1: Spatial OSM Clipper.

Performs reference-complete polygon clipping of the regional Geofabrik Northern
Zone PBF archive against the validated Delhi administrative boundary polygon
(data/raw/boundaries/delhi_boundary.geojson).

Uses libosmium/pyosmium with BackReferenceWriter to guarantee that:
- All nodes inside the Delhi boundary polygon are retained.
- All ways intersecting the Delhi boundary are preserved with complete node references
  (including back-referenced boundary-spanning road nodes).
- All retained relations (multipolygons, turn restrictions, public transit, local boundaries)
  have 100% of their member references present, preventing broken relations.
- Trans-boundary relations (interstate railway mainlines, Asian Highway AH1/AH2, national boundaries)
  are excluded so the spatial extent remains strictly consistent with Delhi.
- The output is a valid, reference-complete OSM PBF archive strictly covering Delhi.
"""

import datetime
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import geopandas as gpd
import osmium
import osmium.version
import shapely


DEFAULT_BOUNDARY_PATH = "data/raw/boundaries/delhi_boundary.geojson"
DEFAULT_SOURCE_PBF = "data/raw/osm/northern-zone-latest.osm.pbf"
DEFAULT_OUTPUT_PBF = "data/raw/osm/delhi_clipped.osm.pbf"


def compute_file_hashes(file_path: Path) -> Tuple[str, str, int]:
    """Computes MD5, SHA-256 and byte size of a file."""
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    size = 0
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    return md5.hexdigest(), sha256.hexdigest(), size


def clip_osm_to_delhi_boundary(
    source_pbf: str = DEFAULT_SOURCE_PBF,
    boundary_geojson: str = DEFAULT_BOUNDARY_PATH,
    output_pbf: str = DEFAULT_OUTPUT_PBF,
    relation_depth: int = 0,
) -> Dict[str, Any]:
    """
    Clips source_pbf to the polygon boundary in boundary_geojson,
    preserving topological reference-completeness.
    """
    src_path = Path(source_pbf)
    bnd_path = Path(boundary_geojson)
    out_path = Path(output_pbf)

    if not src_path.exists():
        raise FileNotFoundError(f"Source PBF not found: {src_path}")
    if not bnd_path.exists():
        raise FileNotFoundError(f"Boundary GeoJSON not found: {bnd_path}")

    start_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t_start = time.time()
    print(f"[{start_time_utc}] Starting spatial OSM clipping...")
    print(f"Source PBF: {src_path}")
    print(f"Boundary:   {bnd_path}")
    print(f"Output PBF: {out_path}")

    # 1. Load validated Delhi boundary polygon
    print("Loading validated Delhi boundary geometry...")
    gdf = gpd.read_file(bnd_path)
    delhi_geom = gdf.geometry.iloc[0]
    minx, miny, maxx, maxy = gdf.total_bounds
    delhi_box = osmium.osm.Box(minx, miny, maxx, maxy)
    print(f"Delhi Bounding Box: [{minx:.6f}, {miny:.6f}, {maxx:.6f}, {maxy:.6f}]")
    print(f"Delhi Boundary Area: {gdf.to_crs(epsg=32643).area.sum() / 1e6:.2f} sq km")

    # 2. Pass 1: Identify Delhi nodes, ways, and relations
    print("\n--- Pass 1: Scanning features for Delhi polygon intersection ---")
    delhi_node_tracker = osmium.IdTracker()
    delhi_way_tracker = osmium.IdTracker()
    delhi_relation_tracker = osmium.IdTracker()

    # Pass 1A: Scan Nodes
    t0 = time.time()
    total_nodes_scanned = 0
    box_nodes_count = 0
    delhi_nodes_count = 0

    print("Scanning nodes in Northern Zone PBF...")
    for obj in osmium.FileProcessor(str(src_path)).with_filter(osmium.filter.EntityFilter(osmium.osm.NODE)):
        total_nodes_scanned += 1
        if delhi_box.contains(obj.location):
            box_nodes_count += 1
            if shapely.contains_xy(delhi_geom, obj.location.lon, obj.location.lat):
                delhi_node_tracker.add_node(obj.id)
                delhi_nodes_count += 1

    t_nodes = time.time() - t0
    print(f"Nodes scan completed in {t_nodes:.2f}s:")
    print(f"  Total scanned: {total_nodes_scanned:,}")
    print(f"  In bounding box: {box_nodes_count:,}")
    print(f"  Strictly inside Delhi polygon: {delhi_nodes_count:,}")

    # Pass 1B: Scan Ways
    t0 = time.time()
    total_ways_scanned = 0
    delhi_ways_count = 0

    print("\nScanning ways intersecting Delhi...")
    for obj in osmium.FileProcessor(str(src_path)).with_filter(osmium.filter.EntityFilter(osmium.osm.WAY)):
        total_ways_scanned += 1
        if delhi_node_tracker.contains_any_references(obj):
            delhi_way_tracker.add_way(obj.id)
            delhi_ways_count += 1

    t_ways = time.time() - t0
    print(f"Ways scan completed in {t_ways:.2f}s:")
    print(f"  Total scanned: {total_ways_scanned:,}")
    print(f"  Intersecting Delhi: {delhi_ways_count:,}")

    # Pass 1C: Scan Relations
    t0 = time.time()
    total_relations_scanned = 0
    delhi_relations_count = 0
    excluded_transnational_count = 0

    delhi_way_id_set = delhi_way_tracker.way_ids()
    delhi_node_id_set = delhi_node_tracker.node_ids()

    print("\nScanning relations relevant to Delhi (checking full member containment)...")
    for obj in osmium.FileProcessor(str(src_path)).with_filter(osmium.filter.EntityFilter(osmium.osm.RELATION)):
        total_relations_scanned += 1
        if len(obj.members) == 0:
            continue

        # Check exclusion criteria for trans-national entities & other states
        admin_level = obj.tags.get("admin_level")
        network = obj.tags.get("network", "")
        name = obj.tags.get("name", "")

        # Exclude national (admin_level 2/3) and other state boundaries (admin_level 4 where not Delhi)
        if admin_level in ("2", "3"):
            excluded_transnational_count += 1
            continue
        if admin_level == "4" and name != "Delhi" and obj.id != 1942586:
            excluded_transnational_count += 1
            continue
        if network in ("AsianHighway", "IN:NH", "IN:railway") or "Asian Highway" in name:
            excluded_transnational_count += 1
            continue

        # Check if ALL member ways and nodes of the relation are inside Delhi
        all_members_in = True
        any_member_in = False
        for member in obj.members:
            if member.type == "w":
                if delhi_way_id_set.get(member.ref):
                    any_member_in = True
                else:
                    all_members_in = False
                    break
            elif member.type == "n":
                if delhi_node_id_set.get(member.ref):
                    any_member_in = True
                else:
                    all_members_in = False
                    break
            else:
                # Sub-relations
                all_members_in = False
                break

        if all_members_in and any_member_in:
            delhi_relation_tracker.add_relation(obj.id)
            delhi_relations_count += 1
        elif any_member_in:
            excluded_transnational_count += 1

    t_rels = time.time() - t0
    print(f"Relations scan completed in {t_rels:.2f}s:")
    print(f"  Total scanned: {total_relations_scanned:,}")
    print(f"  Trans-boundary/external relations excluded: {excluded_transnational_count:,}")
    print(f"  Retained complete Delhi relations: {delhi_relations_count:,}")

    # 3. Pass 2: Stream Write with BackReferenceWriter
    print("\n--- Pass 2: Writing reference-complete clipped PBF ---")
    t0 = time.time()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    delhi_rel_id_set = delhi_relation_tracker.relation_ids()

    written_nodes = 0
    written_ways = 0
    written_relations = 0

    print("Streaming elements to BackReferenceWriter...")
    with osmium.BackReferenceWriter(
        str(out_path),
        str(src_path),
        overwrite=True,
        remove_tags=False,
        relation_depth=relation_depth,
    ) as writer:
        for obj in osmium.FileProcessor(str(src_path)):
            if obj.is_node():
                if delhi_node_id_set.get(obj.id):
                    writer.add_node(obj)
                    written_nodes += 1
            elif obj.is_way():
                if delhi_way_id_set.get(obj.id):
                    writer.add_way(obj)
                    written_ways += 1
            elif obj.is_relation():
                if delhi_rel_id_set.get(obj.id):
                    writer.add_relation(obj)
                    written_relations += 1

    t_write = time.time() - t0
    print(f"BackReferenceWriter closed and completed in {t_write:.2f}s:")
    print(f"  Direct nodes written: {written_nodes:,}")
    print(f"  Ways written: {written_ways:,}")
    print(f"  Relations written: {written_relations:,}")

    # 4. Verification of the Clipped PBF
    print("\n--- Verification of Clipped PBF ---")
    t0 = time.time()
    reader = osmium.io.Reader(str(out_path))
    hdr = reader.header()
    reader.close()

    final_node_count = 0
    final_way_count = 0
    final_relation_count = 0
    min_lon_seen, max_lon_seen = 180.0, -180.0
    min_lat_seen, max_lat_seen = 90.0, -90.0

    for obj in osmium.FileProcessor(str(out_path)):
        if obj.is_node():
            final_node_count += 1
            lon, lat = obj.location.lon, obj.location.lat
            if lon < min_lon_seen: min_lon_seen = lon
            if lon > max_lon_seen: max_lon_seen = lon
            if lat < min_lat_seen: min_lat_seen = lat
            if lat > max_lat_seen: max_lat_seen = lat
        elif obj.is_way():
            final_way_count += 1
        elif obj.is_relation():
            final_relation_count += 1

    t_verify = time.time() - t0
    print(f"Verification scan completed in {t_verify:.2f}s:")
    print(f"  Final Node Count in PBF:     {final_node_count:,} (including {final_node_count - written_nodes:,} back-referenced boundary nodes)")
    print(f"  Final Way Count in PBF:      {final_way_count:,}")
    print(f"  Final Relation Count in PBF: {final_relation_count:,}")
    print(f"  Observed Coordinate Extent:  [{min_lon_seen:.6f}, {min_lat_seen:.6f}, {max_lon_seen:.6f}, {max_lat_seen:.6f}]")

    # Hashes and file sizes
    out_md5, out_sha256, out_bytes = compute_file_hashes(out_path)
    src_md5, src_sha256, src_bytes = compute_file_hashes(src_path)

    total_elapsed = time.time() - t_start
    end_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    metrics = {
        "source_url": "https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf",
        "resolved_url": "https://download.geofabrik.de/asia/india/northern-zone-261111.osm.pbf",
        "source_snapshot_timestamp": "Wed, 11 Nov 2026 23:54:44 GMT",
        "clipping_started_utc": start_time_utc,
        "clipping_completed_utc": end_time_utc,
        "elapsed_seconds": round(total_elapsed, 2),
        "source_pbf": {
            "path": str(src_path),
            "size_bytes": src_bytes,
            "md5_checksum": src_md5,
            "sha256_checksum": src_sha256,
            "total_nodes_scanned": total_nodes_scanned,
            "total_ways_scanned": total_ways_scanned,
            "total_relations_scanned": total_relations_scanned,
        },
        "boundary_filter": {
            "path": str(bnd_path),
            "bounding_box": [minx, miny, maxx, maxy],
            "nodes_in_bbox": box_nodes_count,
            "nodes_strictly_in_polygon": delhi_nodes_count,
            "ways_intersecting": delhi_ways_count,
            "relations_retained": delhi_relations_count,
            "relations_excluded_transboundary": excluded_transnational_count,
        },
        "clipped_pbf": {
            "path": str(out_path),
            "size_bytes": out_bytes,
            "md5_checksum": out_md5,
            "sha256_checksum": out_sha256,
            "total_nodes": final_node_count,
            "total_ways": final_way_count,
            "total_relations": final_relation_count,
            "back_referenced_nodes": final_node_count - written_nodes,
            "observed_extent": [min_lon_seen, min_lat_seen, max_lon_seen, max_lat_seen],
        },
        "tool_versions": {
            "osmium_pyosmium": getattr(osmium.version, "pyosmium_release", "unknown"),
            "libosmium": getattr(osmium.version, "libosmium_version", "unknown"),
            "protozero": getattr(osmium.version, "protozero_version", "unknown"),
            "shapely": shapely.__version__,
            "geopandas": gpd.__version__,
        }
    }

    # Save metadata to data/raw/osm/pbf_metadata.json
    metadata_path = Path("data/raw/osm/pbf_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved metadata record to {metadata_path}")

    return metrics


if __name__ == "__main__":
    metrics = clip_osm_to_delhi_boundary()
    print("\n--- Summary Metrics ---")
    print(json.dumps(metrics, indent=2))
