"""
SafeDelhi AI — Phase 2D: Interactive Environmental Vulnerability Map.

Constructs an interactive Folium visualization centered on Delhi using the
H3 Resolution 8 Environmental Infrastructure Vulnerability dataset (2,093 cells).

Key Features:
1. Six Independent Selectable Layers:
   - Layer 1: Environmental Vulnerability Deciles (1–10) [Default Active]
   - Layer 2: Data Confidence Tiers (High / Medium / Low)
   - Layer 3: Pedestrian Infrastructure Deficit
   - Layer 4: Pedestrian Crossing Deficit
   - Layer 5: Arterial Traffic Severance
   - Layer 6: Confirmed Lighting Evidence & Coverage
2. Strict Neutral Styling for Unassessed Cells:
   - Non-road cells (N=100) are rendered in a distinct dashed neutral grey (#9e9e9e).
   - Never colored as low vulnerability (green) and never assigned a decile.
3. Detailed Clickable Popups:
   - H3 Cell ID, assessment status, vulnerability score/decile, confidence score/tier,
     pedestrian indicators, crossing indicators, arterial severance, and lighting evidence.
4. UI Enhancements:
   - Floating header banner, collapsible legend, layer controls, and methodological disclaimer.
   - 100% free open tiles (OpenStreetMap) with proper attribution.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from branca.element import Element
import folium
import geopandas as gpd
import numpy as np
import pandas as pd

# Default Paths
DEFAULT_INPUT_GEOJSON = "data/processed/delhi_environmental_vulnerability.geojson"
DEFAULT_OUTPUT_HTML = "reports/delhi_environmental_vulnerability_map.html"
DEFAULT_DELHI_BOUNDARY = "data/raw/boundaries/delhi_boundary.geojson"

# Delhi Geographic Center (Centroid of Delhi H3 Grid: 28.6440° N, 77.1000° E)
DELHI_CENTER_LAT = 28.6440
DELHI_CENTER_LON = 77.1000
DEFAULT_ZOOM_START = 11

# Color Palettes
# 10-step sequential palette for Vulnerability Deciles (1 = lowest deficit to 10 = highest deficit)
VULNERABILITY_DECILE_COLORS: Dict[int, str] = {
    1: "#31a354",  # Light green (lowest physical deficit)
    2: "#74c476",
    3: "#a1d99b",
    4: "#c7e9c0",
    5: "#ffeda0",  # Soft yellow
    6: "#feb24c",  # Amber
    7: "#fd8d3c",  # Orange
    8: "#fc4e2a",  # Orange-red
    9: "#e31a1c",  # Red
    10: "#800026",  # Dark Crimson (highest physical deficit)
}

# Neutral style for unassessed cells (N=100)
UNASSESSED_STYLE = {
    "fillColor": "#9e9e9e",
    "color": "#616161",
    "weight": 1.2,
    "fillOpacity": 0.35,
    "dashArray": "4, 4",
}

# Confidence Tier Colors
CONFIDENCE_TIER_COLORS: Dict[str, str] = {
    "high": "#2b83ba",    # Blue (verified source attributes)
    "medium": "#a6bddb",  # Medium blue-gray (standard mapped geometry)
    "low": "#e0f3f8",     # Pale cyan-gray (sparse survey / boundary sliver)
}


def format_cell_popup_html(row: pd.Series) -> str:
  """Builds a rich, accessible, and compact HTML popup card for an H3 cell."""
  cell_id = row["cell_id"]
  status = row["vulnerability_assessment_status"]
  is_assessed = status == "assessed"

  conf_score = row["data_confidence_score"]
  conf_tier = str(row["data_confidence_tier"]).title()
  conf_color = CONFIDENCE_TIER_COLORS.get(row["data_confidence_tier"], "#555")

  if is_assessed:
    vuln_val = f"{row['baseline_vulnerability_index']:.4f}"
    decile_val = int(row["vulnerability_decile"])
    decile_color = VULNERABILITY_DECILE_COLORS.get(decile_val, "#e67e22")
    status_badge = '<span style="background:#27ae60;color:white;padding:1px 5px;border-radius:3px;font-size:10px;">Assessed</span>'
    vuln_html = f"""
    <div style="background:#fff;padding:4px 6px;margin:5px 0;border-left:4px solid {decile_color};border-radius:2px;box-shadow:0 1px 2px rgba(0,0,0,0.1);">
      <div style="font-size:10px;color:#777;">Baseline Environmental Vulnerability</div>
      <div style="font-size:13px;font-weight:bold;color:#2c3e50;">{vuln_val} &nbsp;<span style="font-size:11px;color:{decile_color};">(Decile {decile_val}/10)</span></div>
    </div>"""
  else:
    status_badge = '<span style="background:#7f8c8d;color:white;padding:1px 5px;border-radius:3px;font-size:10px;">Not Assessed (No Roads)</span>'
    vuln_html = """
    <div style="background:#fff;padding:4px 6px;margin:5px 0;border-left:4px solid #95a5a6;border-radius:2px;box-shadow:0 1px 2px rgba(0,0,0,0.1);">
      <div style="font-size:10px;color:#777;">Baseline Environmental Vulnerability</div>
      <div style="font-size:11px;font-style:italic;color:#7f8c8d;">Not Assessed (No Vehicular Roads)</div>
    </div>"""

  ped_dens = f"{row['ped_infrastructure_density_km_per_sqkm']:.2f}"
  ped_def = (
      f"{row['ped_infrastructure_deficit_score']:.4f}"
      if pd.notna(row["ped_infrastructure_deficit_score"])
      else "N/A"
  )

  cross_cnt = int(row["pedestrian_crossing_count"])
  cross_dens = f"{row['pedestrian_crossing_density_per_sqkm']:.2f}"
  cross_def = (
      f"{row['crossing_deficit_score']:.4f}"
      if pd.notna(row["crossing_deficit_score"])
      else "N/A"
  )

  road_dens = f"{row['road_density_km_per_sqkm']:.2f}"
  art_dens = f"{row['arterial_road_density_km_per_sqkm']:.2f}"
  art_sev = (
      f"{row['arterial_severance_score']:.4f}"
      if pd.notna(row["arterial_severance_score"])
      else "N/A"
  )

  lit_cov = f"{row['lighting_evidence_coverage'] * 100:.1f}%"
  if row["has_lighting_evidence"]:
    unlit_ratio = (
        f"{row['confirmed_unlit_ratio'] * 100:.1f}%"
        if pd.notna(row["confirmed_unlit_ratio"])
        else "N/A"
    )
    lit_info = f"Coverage: <b>{lit_cov}</b> | Unlit: <b>{unlit_ratio}</b>"
  else:
    lit_info = "Coverage: <b>0.0%</b> (Unknown / Missing Tags)"

  html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:11px;width:270px;line-height:1.35;color:#222;">
<div style="background:#1a252f;color:#fff;padding:6px 8px;border-radius:3px 3px 0 0;font-weight:bold;">
Cell: {cell_id} <span style="font-weight:normal;color:#bdc3c7;font-size:10px;">(Res 8, {row['clipped_area_sqkm']:.2f} km²)</span>
</div>
<div style="padding:6px 8px;background:#f8f9fa;border:1px solid #ddd;border-top:none;border-radius:0 0 3px 3px;">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
<div>{status_badge}</div>
<div style="color:{conf_color};font-weight:bold;font-size:10px;">Conf: {conf_score:.2f} ({conf_tier})</div>
</div>
{vuln_html}
<div style="border-top:1px solid #e2e8f0;padding-top:3px;margin-top:3px;">
<b>Pedestrian Infrastructure:</b> Density: {ped_dens} km/km² | Deficit: <b>{ped_def}</b><br>
<b>Pedestrian Crossings:</b> {cross_cnt} ({cross_dens}/km²) | Deficit: <b>{cross_def}</b><br>
<b>Arterial Traffic Severance:</b> Road: {road_dens} km/km² | Arterial: {art_dens} | Severance: <b>{art_sev}</b><br>
<b>Confirmed Lighting Evidence:</b> {lit_info}
</div>
</div>
</div>"""
  return html


def format_cell_tooltip_text(row: pd.Series) -> str:
  """Builds a concise, single-line tooltip displayed on hover."""
  cell_id = row["cell_id"]
  if row["vulnerability_assessment_status"] == "assessed":
    decile = int(row["vulnerability_decile"])
    idx = f"{row['baseline_vulnerability_index']:.2f}"
    return f"Cell {cell_id} | Assessed | Decile {decile}/10 (Vuln: {idx}) | Conf: {row['data_confidence_tier']}"
  else:
    return f"Cell {cell_id} | Not Assessed (No Roads) | Conf: {row['data_confidence_tier']}"


def build_environmental_vulnerability_map(
    input_geojson: str = DEFAULT_INPUT_GEOJSON,
    output_html: str = DEFAULT_OUTPUT_HTML,
    boundary_geojson: str = DEFAULT_DELHI_BOUNDARY,
) -> folium.Map:
  """Builds the comprehensive interactive Folium map with 6 independent selectable layers,

  compliant free basemaps, offline vector fallback, collapsible legend, layer controls,
  and methodological disclaimers.
  """
  in_file = Path(input_geojson)
  if not in_file.exists():
    raise FileNotFoundError(f"Input vulnerability GeoJSON not found at: {in_file}")

  print(f"Loading vulnerability dataset from {in_file}...")
  gdf = gpd.read_file(in_file)
  total_cells = len(gdf)
  print(f"Loaded {total_cells:,} cells with {len(gdf.columns)} columns.")

  # Add popup HTML and tooltip text to dataframe properties
  print("Formatting cell popup cards and tooltips...")
  gdf["popup_html"] = gdf.apply(format_cell_popup_html, axis=1)
  gdf["tooltip_text"] = gdf.apply(format_cell_tooltip_text, axis=1)

  # Initialize Base Folium Map centered on Delhi (tiles=None to avoid blocked OSM tile requests)
  m = folium.Map(
      location=[DELHI_CENTER_LAT, DELHI_CENTER_LON],
      zoom_start=DEFAULT_ZOOM_START,
      tiles=None,
      control_scale=True,
  )

  # ----------------------------------------------------------------------------
  # BASEMAPS: Compliant Free Tile Providers & Offline Vector Fallback
  # ----------------------------------------------------------------------------
  # 1. Esri World Light Gray Base (CORS-compliant, free, no API key required)
  esri_base = folium.TileLayer(
      tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
      name="Esri Light Gray Canvas",
      overlay=False,
      control=True,
      show=True,
      max_zoom=16,
  )
  esri_base.add_to(m)

  # 2. CartoDB Positron Raster (Free light basemap)
  carto_base = folium.TileLayer(
      tiles="https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png",
      attr="&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors &copy; <a href=\"https://carto.com/attributions\">CARTO</a>",
      name="CartoDB Positron (Light)",
      subdomains="abcd",
      overlay=False,
      control=True,
      show=False,
      max_zoom=19,
  )
  carto_base.add_to(m)

  # 3. Neutral Vector Canvas (Zero external tiles / Offline fallback using Delhi boundary)
  b_file = Path(boundary_geojson)
  b_gdf = None
  if b_file.exists():
    print(f"Loading Delhi administrative boundary from {b_file}...")
    b_gdf = gpd.read_file(b_file)
    folium.GeoJson(
        b_gdf,
        name="Neutral Vector Canvas (No External Tiles)",
        style_function=lambda x: {
            "fillColor": "#eef2f6",
            "color": "#64748b",
            "weight": 2.0,
            "dashArray": "4, 4",
            "fillOpacity": 0.85,
        },
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    # State Boundary Context Outline (Always visible under H3 cells)
    folium.GeoJson(
        b_gdf,
        name="Delhi State Boundary Outline",
        style_function=lambda x: {
            "fillColor": "#000000",
            "color": "#334155",
            "weight": 1.8,
            "dashArray": "4, 4",
            "fillOpacity": 0.0,
        },
        overlay=True,
        control=True,
        show=True,
    ).add_to(m)

  # Common highlight function for hover interaction
  highlight_fn = lambda x: {
      "weight": 2.5,
      "color": "#000000",
      "fillOpacity": 0.85,
  }

  # ----------------------------------------------------------------------------
  # LAYER 1: Environmental Vulnerability Deciles (1–10) [Default Active]
  # ----------------------------------------------------------------------------
  print("Building Layer 1: Environmental Vulnerability Deciles...")
  def style_vuln(feature):
    props = feature["properties"]
    if props["vulnerability_assessment_status"] == "not_assessed_no_roads":
      return UNASSESSED_STYLE
    decile = props.get("vulnerability_decile")
    if pd.isna(decile) or decile is None:
      return UNASSESSED_STYLE
    decile_int = int(decile)
    color = VULNERABILITY_DECILE_COLORS.get(decile_int, "#ffeda0")
    return {
        "fillColor": color,
        "color": "#37474f",
        "weight": 0.8,
        "fillOpacity": 0.70,
    }

  cols_layer1 = ["cell_id", "vulnerability_assessment_status", "vulnerability_decile", "popup_html", "tooltip_text", "geometry"]
  layer_vuln = folium.GeoJson(
      gdf[cols_layer1],
      name="1. Vulnerability Deciles (1-10)",
      style_function=style_vuln,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=True,
  )
  layer_vuln.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER 2: Data Confidence Tiers (High / Medium / Low)
  # ----------------------------------------------------------------------------
  print("Building Layer 2: Data Confidence Tiers...")
  def style_conf(feature):
    props = feature["properties"]
    tier = props.get("data_confidence_tier", "medium")
    color = CONFIDENCE_TIER_COLORS.get(tier, "#a6bddb")
    if tier == "low":
      return {
          "fillColor": color,
          "color": "#90a4ae",
          "weight": 0.8,
          "fillOpacity": 0.45,
          "dashArray": "3, 3",
      }
    return {
        "fillColor": color,
        "color": "#37474f",
        "weight": 0.8,
        "fillOpacity": 0.65,
    }

  cols_layer2 = ["cell_id", "vulnerability_assessment_status", "data_confidence_tier", "popup_html", "tooltip_text", "geometry"]
  layer_conf = folium.GeoJson(
      gdf[cols_layer2],
      name="2. Data Confidence Tiers",
      style_function=style_conf,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=False,
  )
  layer_conf.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER 3: Pedestrian Infrastructure Deficit
  # ----------------------------------------------------------------------------
  print("Building Layer 3: Pedestrian Infrastructure Deficit...")
  def style_ped_deficit(feature):
    props = feature["properties"]
    if props["vulnerability_assessment_status"] == "not_assessed_no_roads":
      return UNASSESSED_STYLE
    val = props.get("ped_infrastructure_deficit_score")
    if pd.isna(val) or val is None:
      return UNASSESSED_STYLE
    val = float(val)
    if val < 0.20:
      c = "#31a354"
    elif val < 0.40:
      c = "#a1d99b"
    elif val < 0.60:
      c = "#ffeda0"
    elif val < 0.80:
      c = "#feb24c"
    else:
      c = "#e31a1c"
    return {"fillColor": c, "color": "#424242", "weight": 0.8, "fillOpacity": 0.65}

  cols_layer3 = ["cell_id", "vulnerability_assessment_status", "ped_infrastructure_deficit_score", "popup_html", "tooltip_text", "geometry"]
  layer_ped = folium.GeoJson(
      gdf[cols_layer3],
      name="3. Pedestrian Deficit Score",
      style_function=style_ped_deficit,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=False,
  )
  layer_ped.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER 4: Pedestrian Crossing Deficit
  # ----------------------------------------------------------------------------
  print("Building Layer 4: Pedestrian Crossing Deficit...")
  def style_cross_deficit(feature):
    props = feature["properties"]
    if props["vulnerability_assessment_status"] == "not_assessed_no_roads":
      return UNASSESSED_STYLE
    val = props.get("crossing_deficit_score")
    if pd.isna(val) or val is None:
      return UNASSESSED_STYLE
    val = float(val)
    if val < 0.20:
      c = "#31a354"
    elif val < 0.40:
      c = "#a1d99b"
    elif val < 0.60:
      c = "#ffeda0"
    elif val < 0.80:
      c = "#feb24c"
    else:
      c = "#e31a1c"
    return {"fillColor": c, "color": "#424242", "weight": 0.8, "fillOpacity": 0.65}

  cols_layer4 = ["cell_id", "vulnerability_assessment_status", "crossing_deficit_score", "popup_html", "tooltip_text", "geometry"]
  layer_cross = folium.GeoJson(
      gdf[cols_layer4],
      name="4. Crossing Deficit Score",
      style_function=style_cross_deficit,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=False,
  )
  layer_cross.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER 5: Arterial Traffic Severance
  # ----------------------------------------------------------------------------
  print("Building Layer 5: Arterial Traffic Severance...")
  def style_art_severance(feature):
    props = feature["properties"]
    if props["vulnerability_assessment_status"] == "not_assessed_no_roads":
      return UNASSESSED_STYLE
    val = props.get("arterial_severance_score")
    if pd.isna(val) or val is None:
      return UNASSESSED_STYLE
    val = float(val)
    if val == 0.0:
      c = "#ffffcc"
    elif val < 0.25:
      c = "#fed976"
    elif val < 0.50:
      c = "#fd8d3c"
    elif val < 0.75:
      c = "#fc4e2a"
    else:
      c = "#800026"
    return {"fillColor": c, "color": "#424242", "weight": 0.8, "fillOpacity": 0.65}

  cols_layer5 = ["cell_id", "vulnerability_assessment_status", "arterial_severance_score", "popup_html", "tooltip_text", "geometry"]
  layer_art = folium.GeoJson(
      gdf[cols_layer5],
      name="5. Arterial Traffic Severance",
      style_function=style_art_severance,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=False,
  )
  layer_art.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER 6: Confirmed Lighting Evidence & Coverage
  # ----------------------------------------------------------------------------
  print("Building Layer 6: Confirmed Lighting Evidence...")
  def style_lighting_evidence(feature):
    props = feature["properties"]
    has_ev = bool(props.get("has_lighting_evidence", False))
    if not has_ev:
      # Clear neutral style for unknown/untagged lighting coverage
      return {
          "fillColor": "#d9d9d9",
          "color": "#9e9e9e",
          "weight": 0.6,
          "fillOpacity": 0.25,
          "dashArray": "3, 3",
      }
    # Where lighting evidence exists
    lit_d = float(props.get("confirmed_lit_density_km_per_sqkm", 0.0))
    unlit_d = float(props.get("confirmed_unlit_density_km_per_sqkm", 0.0))
    if unlit_d > 0 and lit_d == 0:
      c = "#de2d26"  # Red: confirmed unlit only
    elif lit_d > 0 and unlit_d == 0:
      c = "#2b83ba"  # Blue: confirmed lit only
    else:
      c = "#756bb1"  # Purple: mixed confirmed lit & unlit
    return {"fillColor": c, "color": "#2c3e50", "weight": 1.2, "fillOpacity": 0.75}

  cols_layer6 = [
      "cell_id",
      "vulnerability_assessment_status",
      "has_lighting_evidence",
      "confirmed_lit_density_km_per_sqkm",
      "confirmed_unlit_density_km_per_sqkm",
      "popup_html",
      "tooltip_text",
      "geometry",
  ]
  layer_light = folium.GeoJson(
      gdf[cols_layer6],
      name="6. Lighting Evidence (Unknown vs Confirmed)",
      style_function=style_lighting_evidence,
      highlight_function=highlight_fn,
      popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=320),
      tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], labels=False),
      show=False,
  )
  layer_light.add_to(m)

  # ----------------------------------------------------------------------------
  # LAYER CONTROL
  # ----------------------------------------------------------------------------
  folium.LayerControl(position="topright", collapsed=False).add_to(m)

  # ----------------------------------------------------------------------------
  # FLOATING TITLE BANNER & COLLAPSIBLE METHODOLOGICAL LEGEND
  # ----------------------------------------------------------------------------
  print("Injecting floating header banner and comprehensive legend...")
  custom_ui_html = f"""
  <style>
    #map {{ background: #f8fafc; }}
    .leaflet-tile-pane img:not([src]), .leaflet-tile-pane img[src=""] {{
      display: none !important;
    }}
  </style>

  <div id="map-header-banner" style="
      position: fixed;
      top: 12px;
      left: 56px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.96);
      padding: 10px 16px;
      border-radius: 6px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.2);
      border-left: 5px solid #2c3e50;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      max-width: 400px;
  ">
    <div style="font-size: 14px; font-weight: bold; color: #1a252f; margin-bottom: 2px;">
      SafeDelhi AI — Environmental Infrastructure Vulnerability
    </div>
    <div style="font-size: 11px; color: #555; line-height: 1.35;">
      Provisional Baseline Model (Phase 2D) | Uber H3 Res 8 Grid (2,093 Cells)<br>
      <b>Coverage:</b> 1,993 Assessed Road Cells &bull; 100 Non-Road Cells (Unassessed)
    </div>
  </div>

  <div id="collapsible-legend" style="
      position: fixed;
      bottom: 20px;
      left: 16px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.97);
      padding: 12px 14px;
      border-radius: 6px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.25);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      font-size: 11px;
      max-width: 320px;
      max-height: 480px;
      overflow-y: auto;
      border-top: 3px solid #e74c3c;
  ">
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-bottom: 6px;">
      <span style="font-weight: bold; font-size: 12px; color: #2c3e50;">Map Legend & Indicators</span>
      <button id="legend-toggle-btn" onclick="toggleLegend()" style="background: #e2e8f0; border: none; border-radius: 3px; padding: 2px 7px; font-size: 10px; cursor: pointer; color: #333; font-weight: 500;">&#8722; Collapse</button>
    </div>

    <div id="legend-content">
      <!-- Vulnerability Deciles Legend -->
      <div style="margin-bottom: 8px;">
        <div style="font-weight: bold; margin-bottom: 4px; color: #333;">1. Vulnerability Deciles:</div>
        <div style="display: flex; height: 14px; border-radius: 2px; overflow: hidden; margin-bottom: 4px;">
          <div style="flex: 1; background: #31a354;" title="Decile 1 (Lowest)"></div>
          <div style="flex: 1; background: #74c476;" title="Decile 2"></div>
          <div style="flex: 1; background: #a1d99b;" title="Decile 3"></div>
          <div style="flex: 1; background: #c7e9c0;" title="Decile 4"></div>
          <div style="flex: 1; background: #ffeda0;" title="Decile 5"></div>
          <div style="flex: 1; background: #feb24c;" title="Decile 6"></div>
          <div style="flex: 1; background: #fd8d3c;" title="Decile 7"></div>
          <div style="flex: 1; background: #fc4e2a;" title="Decile 8"></div>
          <div style="flex: 1; background: #e31a1c;" title="Decile 9"></div>
          <div style="flex: 1; background: #800026;" title="Decile 10 (Highest)"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #666;">
          <span>Decile 1 (Low Deficit)</span>
          <span>Decile 10 (High Deficit)</span>
        </div>
      </div>

      <!-- Unassessed Style Legend -->
      <div style="margin-bottom: 8px; padding: 4px 6px; background: #f0f0f0; border-radius: 4px; border: 1px dashed #999;">
        <div style="display: flex; align-items: center;">
          <div style="width: 14px; height: 14px; background: #9e9e9e; border: 1px dashed #616161; margin-right: 8px;"></div>
          <div style="font-weight: bold; color: #444;">Not Assessed (No Vehicular Roads)</div>
        </div>
        <div style="font-size: 10px; color: #666; margin-top: 2px;">
          N=100 cells. Road-pedestrian conflict cannot be evaluated. Never assigned a decile.
        </div>
      </div>

      <!-- Confidence Tiers Legend -->
      <div style="margin-bottom: 8px;">
        <div style="font-weight: bold; margin-bottom: 4px; color: #333;">2. Data Confidence Tiers:</div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; font-size: 10px;">
          <div style="display: flex; align-items: center;"><span style="display:inline-block;width:10px;height:10px;background:#2b83ba;margin-right:4px;"></span> High (≥0.80)</div>
          <div style="display: flex; align-items: center;"><span style="display:inline-block;width:10px;height:10px;background:#a6bddb;margin-right:4px;"></span> Med (0.50-0.80)</div>
          <div style="display: flex; align-items: center;"><span style="display:inline-block;width:10px;height:10px;background:#e0f3f8;border:1px dashed #90a4ae;margin-right:4px;"></span> Low (&lt;0.50)</div>
        </div>
      </div>

      <!-- Lighting Evidence Legend (Accurate Denominators) -->
      <div style="margin-bottom: 8px; border-top: 1px solid #eee; padding-top: 6px;">
        <div style="font-weight: bold; margin-bottom: 4px; color: #333;">6. Lighting Evidence Distribution:</div>
        <div style="font-size: 10px; color: #555; line-height: 1.4;">
          &bull; <span style="color:#2b83ba;font-weight:bold;">Blue</span>: Confirmed Lit &bull; <span style="color:#de2d26;font-weight:bold;">Red</span>: Confirmed Unlit &bull; <span style="color:#756bb1;font-weight:bold;">Purple</span>: Mixed<br>
          &bull; <span style="background:#eee;border:1px dashed #999;padding:0 3px;">Grey Dashed</span>: <b>Zero Mapped Lighting Tags</b>:<br>
          &nbsp;&nbsp;&bull; <b>H3 Cells:</b> 91.3% of cells (1,911 of 2,093) have zero lighting tags<br>
          &nbsp;&nbsp;&bull; <b>Road Network:</b> 99.5% of road length (23,373 of 23,480 km) untagged<br>
          &nbsp;&nbsp;&bull; <b>Pedestrian Paths:</b> 96.0% of path length (1,548 of 1,613 km) untagged<br>
          <span style="font-style: italic; color: #7f8c8d; font-size: 9.5px;">*Darkness is never inferred from missing tags. Missing tags indicate lack of OSM survey data, not absence of real-world lighting.</span>
        </div>
      </div>

      <!-- Methodological Disclaimer -->
      <div style="border-top: 1px solid #ddd; padding-top: 6px; font-size: 9.5px; color: #7f8c8d; line-height: 1.3;">
        <b>Disclaimer:</b> Models physical built-environment deficits only (pedestrian paths, crossings, arterial exposure).
        Does not predict crime or personal risk. Does not label locations safe or unsafe.
        Source: OpenStreetMap &bull; H3 Res 8.
      </div>
    </div>
  </div>

  <script>
    function toggleLegend() {{
      var content = document.getElementById('legend-content');
      var btn = document.getElementById('legend-toggle-btn');
      if (content.style.display === 'none') {{
        content.style.display = 'block';
        btn.innerHTML = '&#8722; Collapse';
      }} else {{
        content.style.display = 'none';
        btn.innerHTML = '&#43; Expand Legend';
      }}
    }}

    window.addEventListener('load', function() {{
      var map = {m.get_name()};
      var indicatorLayers = [
        {layer_vuln.get_name()},
        {layer_conf.get_name()},
        {layer_ped.get_name()},
        {layer_cross.get_name()},
        {layer_art.get_name()},
        {layer_light.get_name()}
      ];

      // Auto-exclusive indicator overlay behavior: single active indicator at a time
      map.on('overlayadd', function(e) {{
        if (indicatorLayers.indexOf(e.layer) !== -1) {{
          indicatorLayers.forEach(function(l) {{
            if (l !== e.layer && map.hasLayer(l)) {{
              map.removeLayer(l);
            }}
          }});
        }}
      }});

      // Graceful tile error handling: suppress broken image icons if tiles fail or offline
      map.eachLayer(function(l) {{
        if (l instanceof L.TileLayer) {{
          l.on('tileerror', function(error, tile) {{
            tile.style.display = 'none';
          }});
        }}
      }});
      map.on('baselayerchange', function(e) {{
        if (e.layer instanceof L.TileLayer) {{
          e.layer.on('tileerror', function(error, tile) {{
            tile.style.display = 'none';
          }});
        }}
      }});
    }});
  </script>
  """
  m.get_root().html.add_child(Element(custom_ui_html))

  # Save HTML output
  out_path = Path(output_html)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  print(f"Exporting interactive map to {out_path}...")
  m.save(str(out_path))
  html_bytes = out_path.stat().st_size
  print(f"  -> Successfully generated: {html_bytes:,} bytes ({html_bytes/(1024*1024):.2f} MB).")

  return m


if __name__ == "__main__":
  build_environmental_vulnerability_map()
