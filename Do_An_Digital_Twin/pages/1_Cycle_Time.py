import plotly.graph_objects as go
import streamlit as st

from analytics import build_time_breakdown, build_event_diagnostics
from utils import (
    inject_css, load_config, process_nc_data, make_arrow_safe_display_df,
    render_sidebar, render_sidebar_summary,
    page_header, section_label, callout_box, empty_state,
    progress_bar_row, apply_plotly_defaults, format_cycle_time,
    TIME_CATEGORY_COLORS, INK, BODY, MUTED, CANVAS, HAIRLINE,
    PRIMARY, SUCCESS, DANGER, SHADOW,
)

st.set_page_config(layout="wide", page_title="Cycle Time — CNC Digital Twin", page_icon="⏱")
inject_css()

config = load_config()
if config is None:
    st.stop()

nc_files, selected_machine, cost_cfg, active_machine_cfg = render_sidebar(config)
config["active_machine_id"] = selected_machine

if not nc_files:
    page_header("⏱ Cycle Time")
    empty_state()
    st.stop()

for uploaded in nc_files:
    content = uploaded.getvalue().decode("utf-8", errors="ignore")

    with st.spinner("Analysing NC program…"):
        df_source, df = process_nc_data(content, config, selected_machine)

    if df.empty:
        st.warning(f"{uploaded.name} contains no valid trajectory data.")
        continue

    df_time_breakdown = build_time_breakdown(df)

    total_row = df_time_breakdown[
        df_time_breakdown["Category"].astype(str).str.strip() == "Total Machining Cycle Time"
    ]
    total_time = float(total_row["Time (s)"].iloc[0]) if not total_row.empty else float(df["time"].max())
    cutting_row = df_time_breakdown[
        df_time_breakdown["Category"].astype(str).str.strip() == "Effective Cutting Interpolation Time"
    ]
    cutting_time = float(cutting_row["Time (s)"].iloc[0]) if not cutting_row.empty else 0.0
    efficiency = (cutting_time / total_time * 100.0) if total_time > 0 else 0.0
    df_errors = df[(df["ot_x"]) | (df["ot_y"]) | (df["ot_z"])]
    fault_blocks = int(df_errors["line_number"].nunique()) if not df_errors.empty else 0

    st.sidebar.divider()
    render_sidebar_summary(total_time, efficiency, fault_blocks)

    time_val, time_unit = format_cycle_time(total_time)

    page_header(
        title="⏱ Cycle Time",

        subtitle=f"Breakdown of {uploaded.name} — total {time_val} {time_unit}",
    )

    # ── Category order and labels ─────────────────────────────────────────────
    display_order = [
        "Effective Cutting Interpolation Time",
        "Non-cutting Rapid Positioning Time",
        "Automatic Tool Change Time",
        "Spindle Start or Speed Change Time",
        "Unclassified Motion Time",
        "Other Non-productive Event Time",
    ]
    short_labels = {
        "Effective Cutting Interpolation Time": "Cutting",
        "Non-cutting Rapid Positioning Time":   "Rapid",
        "Automatic Tool Change Time":           "Tool Change",
        "Spindle Start or Speed Change Time":   "Spindle",
        "Unclassified Motion Time":             "Other Motion",
        "Other Non-productive Event Time":      "Events",
    }

    cat_data = []
    for cat in display_order:
        row = df_time_breakdown[df_time_breakdown["Category"].astype(str).str.strip() == cat]
        if not row.empty:
            t = float(row["Time (s)"].iloc[0])
            pct = float(row["Share (%)"].iloc[0])
            cat_data.append((cat, t, pct))

    # ── Row: distribution chart (3) + share breakdown (2) ────────────────────
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        section_label("Time Distribution", margin_top=0)

        # Stacked bar (full-width strip)
        bar_fig = go.Figure()
        for cat, t, pct in cat_data:
            if pct > 0:
                bar_fig.add_trace(go.Bar(
                    name=short_labels.get(cat, cat),
                    x=[pct], y=[""],
                    orientation="h",
                    marker_color=TIME_CATEGORY_COLORS.get(cat, "#aab0be"),
                    hovertemplate=f"{short_labels.get(cat, cat)}: {t:.2f} s ({pct:.1f}%)<extra></extra>",
                ))
        bar_fig.update_layout(
            barmode="stack", height=72,
            margin=dict(l=0, r=0, t=4, b=4),
            showlegend=False,
            xaxis=dict(visible=False, range=[0, 100]),
            yaxis=dict(visible=False),
            paper_bgcolor=CANVAS, plot_bgcolor=CANVAS,
            font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#333333"),
        )
        st.plotly_chart(bar_fig, use_container_width=True, config={"displayModeBar": False})

        section_label("Category Breakdown", margin_top=12)

        # Horizontal bar chart per category
        cats_rev    = [short_labels.get(c, c) for c, _, _ in reversed(cat_data)]
        times_rev   = [t for _, t, _ in reversed(cat_data)]
        colors_rev  = [TIME_CATEGORY_COLORS.get(c, "#aab0be") for c, _, _ in reversed(cat_data)]

        bar2 = go.Figure(go.Bar(
            x=times_rev, y=cats_rev,
            orientation="h",
            marker_color=colors_rev,
            text=[f"{t:.1f} s" for t in times_rev],
            textposition="outside",
            textfont=dict(size=11, color="#222222"),
            hovertemplate="%{y}: %{x:.2f} s<extra></extra>",
        ))
        apply_plotly_defaults(bar2, height=max(180, len(cat_data) * 40 + 40), margin=dict(l=8, r=60, t=8, b=8))
        bar2.update_layout(xaxis_title="Time (s)", yaxis_title="", showlegend=False)
        bar2.update_xaxes(showgrid=True)
        bar2.update_yaxes(tickfont=dict(size=12, color="#222222", family="Inter, -apple-system, sans-serif"))
        st.plotly_chart(bar2, use_container_width=True, config={"displayModeBar": False})

    with col_right:
        section_label("Share", margin_top=0)
        for cat, t, pct in cat_data:
            progress_bar_row(short_labels.get(cat, cat), t, pct, TIME_CATEGORY_COLORS.get(cat, "#aab0be"))

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        callout_box("Total Cycle Time", time_val, time_unit)

    # ── M-code Event Diagnostics ──────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with st.expander("▸ M-code Event Diagnostics"):
        df_events = build_event_diagnostics(df)
        if df_events.empty:
            st.info("No M-code events found in this NC program.")
        else:
            st.dataframe(
                make_arrow_safe_display_df(df_events),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Line":                  st.column_config.NumberColumn("Line", width="small"),
                    "NC Block":              st.column_config.TextColumn("NC Block", width="medium"),
                    "M-code":               st.column_config.TextColumn("M-code", width="small"),
                    "Initial State":         st.column_config.TextColumn("Initial State", width="medium"),
                    "Target State":          st.column_config.TextColumn("Target State", width="medium"),
                    "Model Basis":           st.column_config.TextColumn("Model Basis", width="large"),
                    "Event Time (s)":        st.column_config.NumberColumn("Event Time", format="%.3f s", width="small"),
                    "Data Confidence":       st.column_config.TextColumn("Confidence", width="medium"),
                    "Required Calibration":  st.column_config.TextColumn("Calibration", width="large"),
                },
            )

    st.divider()
