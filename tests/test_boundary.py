"""Unit and validation tests for Delhi administrative boundary."""

import json
from pathlib import Path
import geopandas as gpd
import pytest

from config import (
    DELHI_BOUNDARY_PATH,
    DATAMEET_BOUNDARY_PATH,
    OSM_BOUNDARY_PATH,
    PROCESSED_DATA_DIR,
    DELHI_BBOX,
    EXPECTED_DELHI_AREA_SQKM_MIN,
    EXPECTED_DELHI_AREA_SQKM_MAX,
)


def test_boundary_files_exist():
    """Verifies that both operational and reference boundaries were downloaded."""
    assert DELHI_BOUNDARY_PATH.exists(), f"Missing primary boundary at {DELHI_BOUNDARY_PATH}"
    assert OSM_BOUNDARY_PATH.exists(), f"Missing OSM boundary at {OSM_BOUNDARY_PATH}"
    assert DATAMEET_BOUNDARY_PATH.exists(), f"Missing DataMeet boundary at {DATAMEET_BOUNDARY_PATH}"


def test_boundary_crs_and_geometry():
    """Verifies standard WGS84 CRS and valid polygon geometry."""
    gdf = gpd.read_file(DELHI_BOUNDARY_PATH)
    assert not gdf.empty, "Delhi boundary GeoDataFrame is empty."
    assert gdf.crs == "EPSG:4326", f"Expected EPSG:4326, got {gdf.crs}"
    
    geom = gdf.geometry.iloc[0]
    assert geom.is_valid, "Delhi boundary geometry is invalid."
    assert geom.geom_type in ["Polygon", "MultiPolygon"], f"Unexpected geometry type: {geom.geom_type}"


def test_boundary_bounding_box():
    """Verifies that boundary coordinates strictly fall within Delhi NCT bounds."""
    gdf = gpd.read_file(DELHI_BOUNDARY_PATH)
    minx, miny, maxx, maxy = gdf.total_bounds
    
    margin = 0.05
    assert miny >= (DELHI_BBOX["min_lat"] - margin), f"Min lat {miny} exceeds southern bound"
    assert maxy <= (DELHI_BBOX["max_lat"] + margin), f"Max lat {maxy} exceeds northern bound"
    assert minx >= (DELHI_BBOX["min_lon"] - margin), f"Min lon {minx} exceeds western bound"
    assert maxx <= (DELHI_BBOX["max_lon"] + margin), f"Max lon {maxx} exceeds eastern bound"


def test_boundary_metric_area():
    """Verifies physical area in UTM Zone 43N matches official Delhi territory (~1,483 sq km)."""
    gdf = gpd.read_file(DELHI_BOUNDARY_PATH)
    gdf_utm = gdf.to_crs("EPSG:32643")
    area_sqkm = gdf_utm.geometry.iloc[0].area / 1e6
    
    assert EXPECTED_DELHI_AREA_SQKM_MIN <= area_sqkm <= EXPECTED_DELHI_AREA_SQKM_MAX, (
        f"Computed area {area_sqkm:.2f} sq km is outside expected range "
        f"[{EXPECTED_DELHI_AREA_SQKM_MIN}, {EXPECTED_DELHI_AREA_SQKM_MAX}]"
    )


def test_cross_check_report():
    """Verifies cross-check report metrics between OSM and DataMeet."""
    report_path = PROCESSED_DATA_DIR / "boundary_verification_report.json"
    assert report_path.exists(), f"Missing verification report at {report_path}"
    
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
        
    cross_check = report.get("cross_check", {})
    iou = cross_check.get("intersection_over_union_iou", 0)
    status = cross_check.get("cross_check_status")
    
    assert status == "CONCORDANT", f"Cross check status is {status}, expected CONCORDANT"
    assert iou >= 0.95, f"Intersection over Union {iou} is below the 0.95 tolerance"
    assert cross_check.get("area_difference_percentage", 100) < 5.0, "Area difference exceeds 5%"
