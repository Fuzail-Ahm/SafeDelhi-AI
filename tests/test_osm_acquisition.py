"""
SafeDelhi AI — Phase 2B Step 1 Automated Verification Tests.

Verifies:
1. Original Geofabrik Northern Zone archive integrity and immutability.
2. Clipped Delhi PBF existence, header readability, and compression size.
3. Feature richness (nodes, ways, and relations).
4. Geographic concentration and consistency with the validated Delhi boundary.
5. Exhaustive reference completeness across ALL ways (zero broken ways).
6. Exhaustive reference completeness across ALL relations (zero broken relations).
7. Reproducibility metadata completeness, relation distribution sum, and known limitations.
"""

import json
from pathlib import Path
import geopandas as gpd
import osmium
import pytest


SOURCE_PBF = Path("data/raw/osm/northern-zone-latest.osm.pbf")
CLIPPED_PBF = Path("data/raw/osm/delhi_clipped.osm.pbf")
BOUNDARY_GEOJSON = Path("data/raw/boundaries/delhi_boundary.geojson")
METADATA_JSON = Path("data/raw/osm/pbf_metadata.json")

EXPECTED_SOURCE_SIZE = 224864535
EXPECTED_SOURCE_MD5 = "74a58d850f10edfedd7b1e50303bbb02"
EXPECTED_CLIPPED_RELATIONS = 5000
EXPECTED_CLIPPED_WAYS = 456837


def test_original_archive_exists_and_intact():
    """Confirms the original Northern Zone PBF archive is present and immutable."""
    assert SOURCE_PBF.exists(), f"Source PBF not found at {SOURCE_PBF}"
    assert SOURCE_PBF.stat().st_size == EXPECTED_SOURCE_SIZE, (
        f"Source PBF size changed! Expected {EXPECTED_SOURCE_SIZE}, got {SOURCE_PBF.stat().st_size}"
    )


def test_original_archive_readable():
    """Confirms the original PBF can be read by libosmium."""
    reader = osmium.io.Reader(str(SOURCE_PBF))
    hdr = reader.header()
    assert hdr is not None
    assert hdr.box().valid()
    reader.close()


def test_clipped_pbf_exists_and_readable():
    """Confirms the clipped Delhi PBF exists, is non-empty, and readable."""
    assert CLIPPED_PBF.exists(), f"Clipped PBF not found at {CLIPPED_PBF}"
    size = CLIPPED_PBF.stat().st_size
    assert size > 15_000_000, f"Clipped PBF suspiciously small: {size} bytes"
    assert size < EXPECTED_SOURCE_SIZE, f"Clipped PBF should be smaller than regional source: {size} bytes"

    reader = osmium.io.Reader(str(CLIPPED_PBF))
    hdr = reader.header()
    assert hdr is not None
    reader.close()


def test_clipped_pbf_contains_features():
    """Verifies that the clipped PBF contains non-zero nodes, ways, and relations."""
    node_count = 0
    way_count = 0
    rel_count = 0

    for obj in osmium.FileProcessor(str(CLIPPED_PBF)):
        if obj.is_node():
            node_count += 1
        elif obj.is_way():
            way_count += 1
        elif obj.is_relation():
            rel_count += 1

    assert node_count >= 2_000_000, f"Expected at least 2M nodes in Delhi, found {node_count:,}"
    assert way_count >= 400_000, f"Expected at least 400k ways in Delhi, found {way_count:,}"
    assert rel_count >= 4_000, f"Expected at least 4k relations in Delhi, found {rel_count:,}"


def test_clipped_pbf_geographic_concentration():
    """
    Verifies that features are overwhelmingly concentrated within Delhi and its immediate
    boundary-spanning road buffer (>99.8%).
    """
    gdf = gpd.read_file(BOUNDARY_GEOJSON)
    minx, miny, maxx, maxy = gdf.total_bounds

    # Buffer for legitimate boundary-spanning road segments (~0.05 deg / ~5 km)
    margin = 0.05
    allowed_minx, allowed_maxx = minx - margin, maxx + margin
    allowed_miny, allowed_maxy = miny - margin, maxy + margin

    total_nodes = 0
    in_delhi_zone = 0

    for obj in osmium.FileProcessor(str(CLIPPED_PBF)).with_filter(osmium.filter.EntityFilter(osmium.osm.NODE)):
        total_nodes += 1
        lon, lat = obj.location.lon, obj.location.lat
        if allowed_minx <= lon <= allowed_maxx and allowed_miny <= lat <= allowed_maxy:
            in_delhi_zone += 1

    pct = (in_delhi_zone / total_nodes) * 100
    assert pct > 99.8, (
        f"Only {pct:.2f}% of nodes are in the Delhi urban envelope (expected > 99.8%)"
    )


def test_clipped_pbf_way_reference_completeness():
    """
    Exhaustively verifies that ALL ways in the clipped PBF have all referenced nodes
    present in the file (100.00% reference integrity, zero broken ways).
    """
    # 1. Index all node IDs
    all_node_ids = set()
    for obj in osmium.FileProcessor(str(CLIPPED_PBF)).with_filter(osmium.filter.EntityFilter(osmium.osm.NODE)):
        all_node_ids.add(obj.id)

    assert len(all_node_ids) > 0, "No nodes found in clipped PBF"

    # 2. Check every way
    total_ways_checked = 0
    broken_ways = []

    for obj in osmium.FileProcessor(str(CLIPPED_PBF)).with_filter(osmium.filter.EntityFilter(osmium.osm.WAY)):
        total_ways_checked += 1
        for n in obj.nodes:
            if n.ref not in all_node_ids:
                broken_ways.append((obj.id, n.ref))
                break

    assert total_ways_checked == EXPECTED_CLIPPED_WAYS, (
        f"Expected {EXPECTED_CLIPPED_WAYS:,} ways, checked {total_ways_checked:,}"
    )
    assert len(broken_ways) == 0, (
        f"Exhaustive check failed! Found {len(broken_ways)} broken ways out of {total_ways_checked:,} ways checked: {broken_ways[:5]}"
    )


def test_clipped_pbf_relation_member_completeness():
    """
    Exhaustively verifies that ALL relations in the clipped PBF have all member
    ways and nodes present in the file (100.00% member integrity, zero broken relations).
    """
    # 1. Index all node IDs and way IDs
    all_node_ids = set()
    all_way_ids = set()

    for obj in osmium.FileProcessor(str(CLIPPED_PBF)):
        if obj.is_node():
            all_node_ids.add(obj.id)
        elif obj.is_way():
            all_way_ids.add(obj.id)

    assert len(all_node_ids) > 0, "No nodes found in clipped PBF"
    assert len(all_way_ids) > 0, "No ways found in clipped PBF"

    # 2. Check every relation
    total_relations_checked = 0
    broken_relations = []

    for obj in osmium.FileProcessor(str(CLIPPED_PBF)).with_filter(osmium.filter.EntityFilter(osmium.osm.RELATION)):
        total_relations_checked += 1
        for m in obj.members:
            if m.type == "w" and m.ref not in all_way_ids:
                broken_relations.append((obj.id, "way", m.ref))
                break
            elif m.type == "n" and m.ref not in all_node_ids:
                broken_relations.append((obj.id, "node", m.ref))
                break

    assert total_relations_checked == EXPECTED_CLIPPED_RELATIONS, (
        f"Expected {EXPECTED_CLIPPED_RELATIONS:,} relations, checked {total_relations_checked:,}"
    )
    assert len(broken_relations) == 0, (
        f"Exhaustive check failed! Found {len(broken_relations)} broken relations out of {total_relations_checked:,} checked: {broken_relations[:5]}"
    )


def test_metadata_file_validity():
    """Verifies the reproducibility metadata record, relation breakdown sum, and known limitations."""
    assert METADATA_JSON.exists(), f"Metadata record not found at {METADATA_JSON}"
    with open(METADATA_JSON, "r", encoding="utf-8") as f:
        meta = json.load(f)

    assert "source_url" in meta
    assert "source_pbf" in meta
    assert "clipped_pbf" in meta
    assert meta["source_pbf"]["md5_checksum"] == EXPECTED_SOURCE_MD5
    assert meta["source_pbf"]["size_bytes"] == EXPECTED_SOURCE_SIZE
    assert meta["clipped_pbf"]["total_nodes"] > 2_000_000
    assert meta["clipped_pbf"]["total_ways"] == EXPECTED_CLIPPED_WAYS
    assert meta["clipped_pbf"]["total_relations"] == EXPECTED_CLIPPED_RELATIONS
    assert "tool_versions" in meta

    # Verify relation type distribution sums to exactly 5000
    assert "relation_type_distribution" in meta["clipped_pbf"]
    dist = meta["clipped_pbf"]["relation_type_distribution"]
    assert sum(dist.values()) == EXPECTED_CLIPPED_RELATIONS, (
        f"Relation breakdown sum mismatch: {sum(dist.values())} != {EXPECTED_CLIPPED_RELATIONS}"
    )

    # Verify known limitations documentation
    assert "known_limitations" in meta
    limitations = meta["known_limitations"]
    assert "boundary_crossing_ways_without_interior_nodes" in limitations
    bnd_lim = limitations["boundary_crossing_ways_without_interior_nodes"]
    assert bnd_lim["total_missed_ways"] == 159
    assert bnd_lim["non_highway_features"] == 154
    assert bnd_lim["highway_features"] == 5
    assert "outer_reference_nodes_explanation" in limitations
