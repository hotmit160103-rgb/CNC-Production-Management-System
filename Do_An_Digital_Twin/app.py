import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    build_time_breakdown,
    build_production_summary,
)
from utils import (
    inject_css, load_config, process_nc_data, make_arrow_safe_display_df,
    render_sidebar, render_sidebar_summary,
    page_header, kpi_card, section_label, callout_box, empty_state,
    progress_bar_row, apply_plotly_defaults, format_cycle_time,
    TIME_CATEGORY_COLORS, AXIS_COLORS, LIMIT_LINE_COLOR,
    INK, BODY, MUTED, HAIRLINE, CANVAS, PRIMARY, SUCCESS, DANGER,
)

st.set_page_config(
    layout="wide",
    page_title="CNC Digital Twin",
    page_icon="⚙️",
)

inject_css()

config = load_config()
if config is None:
    st.stop()

nc_files, selected_machine, cost_cfg, active_machine_cfg = render_sidebar(config)
config["active_machine_id"] = selected_machine
limits = active_machine_cfg["machine_g53"]["limits"]

# ── Empty state ───────────────────────────────────────────────────────────────
if not nc_files:
    page_header("Dashboard", "Upload an NC program to begin simulation.")
    empty_state()
    st.stop()


# ── Process NC data ───────────────────────────────────────────────────────────
for uploaded in nc_files:
    content = uploaded.getvalue().decode("utf-8", errors="ignore")

    with st.spinner("Analysing NC program…"):
        df_source, df = process_nc_data(content, config, selected_machine)

    if df.empty:
        st.warning(f"{uploaded.name} contains no valid trajectory data.")
        continue

    # ── Derive KPI values ─────────────────────────────────────────────────────
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

    total_pts = len(df)
    df_errors = df[(df["ot_x"]) | (df["ot_y"]) | (df["ot_z"])]
    fault_blocks = int(df_errors["line_number"].nunique()) if not df_errors.empty else 0
    is_safe = fault_blocks == 0

    if "tool_length_warning" in df.columns:
        warnings = sorted(
            set(str(x) for x in df["tool_length_warning"].dropna().unique() if str(x).strip())
        )
        if warnings:
            st.warning("Tool data: " + "; ".join(warnings))

    # ── Sidebar mini-summary ──────────────────────────────────────────────────
    st.sidebar.divider()
    render_sidebar_summary(total_time, efficiency, fault_blocks)

    # ── Page header ───────────────────────────────────────────────────────────
    page_header(
        title=uploaded.name,

        subtitle=f"{active_machine_cfg.get('machine_name', selected_machine)}  ·  {active_machine_cfg.get('control', '')}",
    )

    # ── KPI cards ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    time_val, time_unit = format_cycle_time(total_time)

    with k1:
        kpi_card("Cycle Time", time_val, time_unit, accent=PRIMARY)
    with k2:
        kpi_card("Efficiency", f"{efficiency:.1f}", "%", delta="Cutting vs total", accent=SUCCESS)
    with k3:
        kpi_card("Traj. Points", f"{total_pts:,}", accent="#5b6fa8")
    with k4:
        if is_safe:
            kpi_card("MCS Safety", "SAFE", delta="No overtravel", accent=SUCCESS)
        else:
            kpi_card("MCS Safety", "FAULT", delta=f"{fault_blocks} block(s)", accent=DANGER)

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Row 1: Axis travel (3) + Cycle breakdown (2) ──────────────────────────
    col_axis, col_breakdown = st.columns([3, 2], gap="large")

    with col_axis:
        section_label("Axis Travel — MCS", margin_top=0)
        tab_x, tab_y, tab_z = st.tabs(["X Axis", "Y Axis", "Z Axis"])

        for tab, ax in zip([tab_x, tab_y, tab_z], ["X", "Y", "Z"]):
            with tab:
                col_name = f"axis_{ax.lower()}"
                ot_col   = f"ot_{ax.lower()}"
                color    = AXIS_COLORS[ax]

                fig = go.Figure()
                if col_name in df.columns:
                    plot_df = df.copy()
                    plot_df[col_name] = pd.to_numeric(plot_df[col_name], errors="coerce")
                    plot_df = plot_df.dropna(subset=[col_name, "time"])

                    fig.add_trace(go.Scatter(
                        x=plot_df["time"], y=plot_df[col_name],
                        mode="lines", name=f"{ax} position",
                        line=dict(color=color, width=2),
                        connectgaps=True,
                        customdata=plot_df[["line_number", "raw_line"]],
                        hovertemplate=(
                            "Time: %{x:.2f} s<br>"
                            "Position: %{y:.3f} mm<br>"
                            "Line %{customdata[0]}: %{customdata[1]}"
                            "<extra></extra>"
                        ),
                    ))

                    l_min, l_max = limits[ax.lower()]
                    for y_val, label in [(l_max, f"Max {ax}: {l_max}"), (l_min, f"Min {ax}: {l_min}")]:
                        fig.add_hline(
                            y=y_val, line_dash="dash",
                            line_color=LIMIT_LINE_COLOR, line_width=1.2,
                            annotation_text=label,
                            annotation_font=dict(size=10, color=DANGER),
                        )

                    if ot_col in plot_df.columns:
                        df_ot = plot_df[plot_df[ot_col]]
                        if not df_ot.empty:
                            fig.add_trace(go.Scatter(
                                x=df_ot["time"], y=df_ot[col_name],
                                mode="markers", name="Overtravel",
                                marker=dict(color=DANGER, symbol="x", size=9),
                                hoverinfo="skip",
                            ))

                apply_plotly_defaults(fig, title=f"{ax}-axis MCS Position (mm)", height=300)
                fig.update_layout(xaxis_title="Time (s)", yaxis_title="Position (mm)", showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with col_breakdown:
        section_label("Cycle Time Breakdown", margin_top=0)

        # Stacked bar
        categories = [
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
            "Automatic Tool Change Time":           "Tool Chg",
            "Spindle Start or Speed Change Time":   "Spindle",
            "Unclassified Motion Time":             "Other",
            "Other Non-productive Event Time":      "Events",
        }

        cat_data = []
        for cat in categories:
            row = df_time_breakdown[df_time_breakdown["Category"].astype(str).str.strip() == cat]
            if not row.empty:
                t = float(row["Time (s)"].iloc[0])
                pct = float(row["Share (%)"].iloc[0])
                if t > 0:
                    cat_data.append((cat, t, pct))

        # Small stacked bar
        bar_fig = go.Figure()
        for cat, t, pct in cat_data:
            bar_fig.add_trace(go.Bar(
                name=short_labels.get(cat, cat),
                x=[pct], y=[""],
                orientation="h",
                marker_color=TIME_CATEGORY_COLORS.get(cat, "#aab0be"),
                hovertemplate=f"{short_labels.get(cat, cat)}: {t:.1f} s ({pct:.1f}%)<extra></extra>",
            ))
        bar_fig.update_layout(
            barmode="stack", height=70,
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
            xaxis=dict(visible=False, range=[0, 100]),
            yaxis=dict(visible=False),
            paper_bgcolor=CANVAS, plot_bgcolor=CANVAS,
            font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#333333"),
        )
        st.plotly_chart(bar_fig, use_container_width=True, config={"displayModeBar": False})

        # Progress bar rows
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        for cat, t, pct in cat_data:
            progress_bar_row(short_labels.get(cat, cat), t, pct, TIME_CATEGORY_COLORS.get(cat, "#aab0be"))

        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
        callout_box("Total Cycle Time", time_val, time_unit)

    # ── Row 2: Feedrate + Spindle ─────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    col_feed, col_rpm = st.columns([3, 2], gap="large")

    with col_feed:
        section_label("Feedrate", margin_top=0)
        fig_feed = go.Figure()
        fig_feed.add_trace(go.Scatter(
            x=df["time"], y=df["feedrate"],
            mode="lines", fill="tozeroy",
            line=dict(color=PRIMARY, width=1.5),
            fillcolor=f"rgba(26,43,74,0.08)",
            name="Feedrate",
            hovertemplate="Time: %{x:.2f} s<br>Feedrate: %{y:.0f} mm/min<extra></extra>",
        ))
        apply_plotly_defaults(fig_feed, height=260)
        fig_feed.update_layout(xaxis_title="Time (s)", yaxis_title="Feedrate (mm/min)", showlegend=False)
        st.plotly_chart(fig_feed, use_container_width=True, config={"displayModeBar": False})

    with col_rpm:
        section_label("Spindle Speed", margin_top=0)
        fig_rpm = go.Figure()
        fig_rpm.add_trace(go.Scatter(
            x=df["time"], y=df["rpm"],
            mode="lines",
            line=dict(color="#c97b10", width=1.5),
            name="Spindle",
            hovertemplate="Time: %{x:.2f} s<br>Speed: %{y:.0f} rpm<extra></extra>",
        ))
        apply_plotly_defaults(fig_rpm, height=260)
        fig_rpm.update_layout(xaxis_title="Time (s)", yaxis_title="Spindle Speed (rpm)", showlegend=False)
        st.plotly_chart(fig_rpm, use_container_width=True, config={"displayModeBar": False})

    st.divider()
