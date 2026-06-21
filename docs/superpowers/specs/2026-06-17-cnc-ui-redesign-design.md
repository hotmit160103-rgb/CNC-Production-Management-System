# CNC Digital Twin — UI Redesign Spec

**Date:** 2026-06-17
**Status:** Approved

## Overview

Redesign the CNC Digital Twin Streamlit app from a single-file tab layout into a multi-page sidebar navigation app. Replace most data tables with charts, progress bars, and status components for faster visual scanning.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Theme | Light Professional | White/gray background, colored accents, readable in daylight |
| Layout | Streamlit Native Multi-Page | `pages/` folder, no new dependencies, clean file structure |
| Pages | 5 pages | Consolidates 8 tabs into logical groupings |
| Dashboard style | KPI Cards + Charts | 4 KPI cards + axis travel chart + progress bars breakdown |

## Architecture

### File structure

```
Do_An_Digital_Twin/
├── app.py                    ← entry point: page config, sidebar header, file uploader, session_state
├── pages/
│   ├── 1_Dashboard.py        ← KPI cards + axis chart + time breakdown
│   ├── 2_Cycle_Time.py       ← bar charts + progress bars + M-code events
│   ├── 3_Faults_MCS.py       ← overtravel chart + critical blocks + fault log
│   ├── 4_Costing.py          ← cost breakdown bars + batch calculator
│   └── 5_Optimize.py         ← savings chart + recommendation cards
├── src/engine.py             ← unchanged
├── analytics.py              ← unchanged, add chart helper functions if needed
├── transformation.py         ← unchanged
└── config.json               ← unchanged
```

### Shared state

`app.py` owns the file upload and `process_nc_data()` call. The resulting DataFrame is stored in `st.session_state["df"]`. All 5 pages read from `st.session_state` — no reprocessing on page navigation.

If no file is uploaded, each page shows an empty-state prompt: "Upload an NC file in the sidebar to get started."

## Pages

### `app.py` — Sidebar

- Logo + machine name + status badge (● SAFE in green / ⚠ N FAULTS in red) at top of sidebar
- NC file uploader (existing)
- Machine selector (existing)
- After parse: mini summary in sidebar — cycle time, fault count, efficiency %
- Custom CSS injected once via `st.markdown(..., unsafe_allow_html=True)`

### `1_Dashboard.py`

| Row | Layout | Components |
|---|---|---|
| 1 | 4 columns | KPI metric cards: Cycle Time · Efficiency % · Cost/Part · Fault Count |
| 2 | 3:2 columns | Plotly axis travel (X/Y/Z + red limit lines) \| Progress bars (Cutting/Rapid/Tool Change/Dwell) |
| 3 | 1:1 columns | Feedrate area chart \| Spindle RPM line chart |

KPI cards: `border-radius: 8px`, `border-top: 3px solid <color>` where color reflects status (blue=neutral, green=good, amber=warning, red=fault).

### `2_Cycle_Time.py`

- Stacked horizontal bar chart — all time categories (replaces current table)
- Individual progress bars per category with % and duration label
- Expandable `st.expander`: M-code events detail table (hidden by default)

### `3_Faults_MCS.py`

- Status banner at top: green (SAFE) or red (N FAULTS) — full width
- Plotly axis travel chart full width with overtravel regions highlighted in red
- Top-10 critical blocks: Plotly horizontal bar chart sorted by duration (replaces table)
- Overtravel log: table with axis filter (`st.selectbox`)

### `4_Costing.py`

- 3 metric cards: Cost/Part · Cost/Hour · Batch Cost
- Horizontal bar chart: machine time cost vs labour cost vs overhead
- Hourly rate inputs (`st.number_input`) directly on this page — removed from sidebar
- Results update live as inputs change (no submit button needed)

### `5_Optimize.py`

- Savings banner: "Potential saving: X% cycle time / $Y per part"
- Plotly horizontal bar chart: optimization items sorted by time impact (replaces table)
- Recommendation cards: each suggestion as a styled card with priority badge (High / Med / Low)

## Styling

### Color palette

| Token | Hex | Usage |
|---|---|---|
| Primary | `#3b82f6` | Cutting time, X-axis, primary actions |
| Success | `#22c55e` | Safe status, rapid moves, Y-axis |
| Warning | `#f59e0b` | Tool change, Z-axis, cost |
| Danger | `#ef4444` | Faults, overtravel, limit lines |
| BG | `#f8fafc` | Page background |
| Text | `#1e293b` | Headings, primary text |
| Muted | `#94a3b8` | Labels, secondary text |

### CSS rules (injected in `app.py`)

- KPI card: `border-radius: 8px`, `border-top: 3px solid <color>`, light box-shadow
- Sidebar: `background: #1e293b`, white text
- Font: Inter via Google Fonts
- Hide Streamlit footer and hamburger menu
- Custom progress bar colors (override Streamlit default green)

### Plotly

- Base template: `plotly_white`
- Chart heights: `300px` on Dashboard, `400px` on detail pages
- Colors follow the palette above consistently across all charts
- All charts: `config={"displayModeBar": False}` to hide toolbar clutter

## Data flow

No changes to `analytics.py` or `transformation.py`. The existing builder functions (`build_time_breakdown`, `build_overtravel_table`, etc.) continue to produce DataFrames. Each page imports the relevant builder and either renders the DataFrame directly (tables) or transforms it into a Plotly figure before rendering.

A `charts.py` module will be added to `Do_An_Digital_Twin/` to house reusable Plotly figure builders (e.g., `make_axis_travel_chart()`, `make_time_breakdown_bar()`), keeping page files concise.

## Out of scope

- No changes to the NC parsing engine or transformation logic
- No new machine configurations
- No authentication or multi-user support
- CAM Quality page is merged into Cycle Time page as an expandable section (low-traffic data)
