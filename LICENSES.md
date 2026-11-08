# Third-party components

The code uses these libraries and data formats. Versions are the ones the results were produced with.

- **pandas 3.1.1**, data handling, BSD-3-Clause.
- **NumPy 2.5.4**, numerics, BSD-3-Clause and others (see the package metadata).
- **scikit-learn 1.9.1**, grouped cross-validation and gradient boosting, BSD-3-Clause.
- **DuckDB 2.0.0**, queries on the dataset, MIT.
- **PyArrow 26.0.1**, Parquet reading, Apache-2.0.
- **PyYAML 6.0.3**, reading the Europress configuration, MIT.
- **jsonschema 4.23.0** and **referencing 0.37.0**, FIWARE record validation with local schema references, MIT.
- **Matplotlib 3.10.7**, report figures, Matplotlib License (PSF-based).
- **Smart Data Models WasteContainer schema 0.3.0** and its common schema, the FIWARE record format, CC BY 4.0. Both are downloaded by `scripts/get_schemas.sh` and not included.
- **Google Fonts** Barlow Condensed, Source Sans 3 and JetBrains Mono, the demo page typography, loaded from Google Fonts.
- **Mermaid**, the workflow diagram in `docs/value.md`, rendered by GitHub.
- **Tools used only to build `docs/report.pdf`**, not included: pandoc (GPL-2.0-or-later), Mermaid CLI (MIT) and Playwright with Chromium (Apache-2.0).

## Europress materials

The dataset and the data generator package (`Europress_SMART_Material_Value_Engine_v1.0.1`) were provided by Europress for the Since AI Hackathon 2026. No license file is included in the package. This repository does not contain the dataset or the package code. `sim/experiments.py` patches a local copy of the generator at run time.

## Prior art referenced

- BACE LLC, US10564029B2 and US11162834B2: load-cell weighing of waste containers and compactor retrofit.
- Canalytics, US12379240B1: compactor weighing with pistons and a pressure transducer under the casters.
- KAPASITY Oy, WO2021176137A1: counting compaction strokes from motor energy, used for fullness, not weight.
- US5558013A: motor current per compaction cycle, used for fullness.
- US4643087A: monitoring compactor fullness from hydraulic back pressure at the end of a fixed ram stroke.

## AI use

Claude, Claude Code, Gemini and ChatGPT were used for ideation, research, drafting and running the analysis code and simulations, the demo page, and the narrated video with an AI voice (Kokoro) and subtitles. Also, they were used as assistive aids for reports' language refinement, drafting, restructuring, and assistance with organizing and verifying technical material which I directed and finalized.