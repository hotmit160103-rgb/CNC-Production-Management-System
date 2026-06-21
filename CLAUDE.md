# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
cd Do_An_Digital_Twin
pip install -r requirements.txt
streamlit run app.py
```

The app runs on port 8501. The Dev Container auto-launches it via `postAttachCommand` in [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json).

To run the CLI trajectory checker directly:
```bash
cd Do_An_Digital_Twin
python main.py
```

## Architecture

This is a **CNC Digital Twin** — a Streamlit web app that simulates CNC NC-program execution offline, predicts cycle time, detects overtravel, and generates cost/optimization reports.

### Data flow

1. User uploads `.nc` file(s) in the sidebar and selects a machine (EMCO_155 or HURCO_VM10I).
2. `GCodeEngine.parse_line()` ([src/engine.py](Do_An_Digital_Twin/src/engine.py)) tokenizes each NC line into a dict of G/M/X/Y/Z/F/S/T/H codes.
3. `DigitalTwinTransformer.apply_block()` ([transformation.py](Do_An_Digital_Twin/transformation.py)) consumes token dicts and returns a list of **segments** — either `type="motion"` (with `trajectory_slide`: a list of interpolated time-stamped MCS points) or `type="event"` (spindle start, tool change, dwell, etc. with a duration).
4. `process_nc_data()` in [app.py](Do_An_Digital_Twin/app.py) flattens all segments into a single time-series Pandas DataFrame (one row per trajectory point or event boundary).
5. Functions in [analytics.py](Do_An_Digital_Twin/analytics.py) (`build_time_breakdown`, `build_event_diagnostics`, `build_overtravel_table`, etc.) derive display tables from that DataFrame.
6. Plotly charts visualize MCS axis travel, feedrate, spindle speed, and tool sequence.

### Key coordinate systems

- **G53 (MCS)**: Machine Coordinate System — absolute machine limits from `config.json`. Overtravel is checked against these limits.
- **G54 (WCS)**: Work Coordinate System — workpiece origin offset stored as `work_offset_g54.offset_vector` in config.
- **Tool tip**: Slide position minus H-length compensation (G43).

### Machine configuration

All machine specs live in [config.json](Do_An_Digital_Twin/config.json). Two machines are defined:
- `EMCO_155`: EMCO Concept Mill 155, 3-axis, 10-station turret, 7500 mm/min rapid. G53 limits measured from real machine.
- `HURCO_VM10I`: Hurco VM10i, 3-axis VMC, 24-station ATC, 28000 mm/min rapid. G53 limits are temporary assumptions (not yet measured).

`DigitalTwinTransformer.__init__()` reads the active machine via `config["active_machine_id"]`. Tool data (H-lengths) currently comes from the legacy `tool_library` in config, but the intended schema separates tool data into per-run **Tool Setup Tables** (see [DATA_SCHEMA_DAY1.md](Do_An_Digital_Twin/DATA_SCHEMA_DAY1.md)).

### Three-layer tool data model

1. **NC-code layer**: T-code, H-code, D-code, M6 extracted from the NC program.
2. **Machine config layer**: number of tool stations, max tool dimensions.
3. **Tool setup layer**: actual tool identity (name, diameter, H-length) per run — currently stored in `config["tool_library"]`, designed to eventually come from a separate CSV/table per run.

### PyArrow / Streamlit display

Mixed-type DataFrame columns cause PyArrow serialization errors in `st.dataframe()`. Always pass DataFrames through `make_arrow_safe_display_df()` before display — it coerces `object` columns to `string` dtype while leaving numeric columns untouched.
