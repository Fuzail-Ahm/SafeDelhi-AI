# SafeDelhi AI 🛡️

### A Geospatial AI Platform for Urban Environmental Safety Analysis

SafeDelhi AI is an open-source, data-driven project focused on understanding urban environmental conditions across Delhi using geospatial analysis.

The project aims to combine publicly available geographical, infrastructure, accessibility, and other relevant datasets to develop a spatial understanding of environmental vulnerability across the city.

Rather than declaring an area absolutely safe or unsafe, SafeDelhi AI aims to provide evidence-based insights into environmental conditions, data availability, and potential infrastructure gaps.

---

## 🎯 Project Objectives

- Divide Delhi into standardized geographical cells for spatial analysis.
- Integrate publicly available urban and infrastructure datasets.
- Study environmental factors that may influence urban safety.
- Identify areas with potential infrastructure and accessibility gaps.
- Develop an interpretable, data-driven environmental vulnerability framework.
- Communicate findings through interactive geospatial visualizations.

## 🗺️ How It Works

The planned system follows a geospatial data-processing pipeline:

1. **Data Collection:** Obtain relevant datasets from verified public sources.
2. **Data Cleaning:** Validate, standardize, and preprocess geographical information.
3. **Spatial Grid Generation:** Divide Delhi into H3 hexagonal cells.
4. **Feature Extraction:** Associate relevant infrastructure and environmental indicators with each cell.
5. **Spatial Analysis:** Analyze geographical patterns and environmental conditions.
6. **Visualization:** Present results through interactive maps and analytical reports.

## 🏗️ Project Progress

### Phase 1 — Spatial Foundation and Boundary Verification

**Status: Completed**

The first phase established the geographical foundation required for subsequent analysis.

Implemented components:

- Delhi geographical boundary acquisition and processing.
- Cross-verification using two boundary datasets.
- H3-based spatial grid generation.
- Boundary clipping and geographical cell validation.
- Spatial topology and coverage verification.
- Reproducibility metadata generation.
- Static and interactive map generation.
- Automated test suite.

### Phase 1 Results

| Metric | Result |
|---|---:|
| H3 resolution | 8 |
| Intersecting grid cells | 2,093 |
| Strict interior cells | 1,782 |
| Boundary-intersecting cells | 311 |
| Unique adjacent cell pairs checked | 6,034 |
| Automated tests passed | 14/14 |
| Grid coverage | 99.999996% |

*These are outputs from the Phase 1 verification process. Coverage measures geometric agreement between the generated grid and the operational boundary; it does not independently establish the real-world accuracy of that boundary.*

### Phase 2 — Public Dataset Integration

**Status: Planned**

The next phase will focus on identifying, verifying, and integrating relevant public datasets.

Potential data categories include:

- Streetlight infrastructure.
- Road and pedestrian infrastructure.
- Police station locations and accessibility.
- Hospital and emergency facility accessibility.
- Public transportation accessibility.
- Publicly reported crime statistics, subject to available geographical resolution.

All datasets will be checked for source reliability, licensing, geographical coverage, and completeness before integration.

### Future Development

- Environmental vulnerability scoring.
- Interactive geographical analysis.
- Data completeness and confidence indicators.
- Comparative spatial analysis.
- An accessible visualization interface.

---

## 🧰 Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core development |
| GeoPandas | Geospatial data processing |
| H3 | Hexagonal spatial indexing |
| Shapely | Geometrical operations |
| Pandas | Data processing |
| PyProj | Coordinate transformations |
| Folium | Interactive map visualization |
| Matplotlib | Static visualizations |
| Pytest | Automated testing |

## 📁 Project Structure

```text
SafeDelhi-AI/
│
├── data/
│   ├── raw/
│   │   └── boundaries/
│   └── processed/
│
├── reports/
│   ├── delhi_boundary_and_grid.png
│   └── delhi_grid_interactive.html
│
├── src/
│   ├── ingestion/
│   │   └── boundary_loader.py
│   ├── spatial/
│   │   ├── grid_generator.py
│   │   └── visualizer.py
│   └── utils/
│       └── logger.py
│
├── tests/
│   ├── test_boundary.py
│   └── test_grid.py
│
├── config.py
├── requirements.txt
└── .gitignore
```

## ⚙️ Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Fuzail-Ahm/SafeDelhi-AI.git
cd SafeDelhi-AI
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows**

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the test suite

```bash
pytest -v
```

## 📊 Phase 1 Visualizations

The repository includes generated geographical visualizations:

- `reports/delhi_boundary_and_grid.png` — Static visualization of the Delhi boundary and H3 grid.
- `reports/delhi_grid_interactive.html` — Interactive geographical visualization.

## 🔍 Research Principles and Limitations

SafeDelhi AI follows several important principles:

- **Evidence-based analysis:** No fabricated incidents, geographical coordinates, or infrastructure observations.
- **Uncertainty awareness:** Missing information must not automatically be interpreted as negative infrastructure conditions.
- **Relative vulnerability:** The project does not label neighbourhoods or locations as absolutely safe or unsafe.
- **Data transparency:** Source, geographical resolution, completeness, and limitations should be documented.
- **Responsible interpretation:** Publicly reported crime statistics may be incomplete and subject to under-reporting.
- **Privacy:** The project is focused on aggregated geographical analysis, not tracking individuals.

The current implementation establishes the spatial foundation. It does not yet provide validated environmental vulnerability scores or real-time safety predictions.

## 🌍 Data Sources

The initial geographical foundation uses:

- OpenStreetMap geographical boundary data.
- DataMeet Delhi boundary reference data.

Additional dataset sources, licensing information, retrieval dates, and attribution will be documented as the project expands.

## 🤝 Contributions

Contributions, suggestions, research discussions, and improvements are welcome.

If you would like to contribute:

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Add or update tests where appropriate.
5. Submit a pull request.

## 📌 Project Status

SafeDelhi AI is currently under active development.

**Current milestone:** Phase 1 — Spatial Foundation and Boundary Verification completed.

**Next milestone:** Phase 2 — Public Dataset Verification and Integration.

## 📄 License

A project license will be added after the licensing and redistribution requirements of the incorporated geographical datasets have been reviewed.

---

**Built with Python, geospatial analysis, and a focus on responsible urban safety research.**
