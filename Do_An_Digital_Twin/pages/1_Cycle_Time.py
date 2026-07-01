import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    build_time_breakdown,
    build_event_diagnostics,
    extract_cutting_tool_ids,
    build_tool_life_summary,
    build_tool_life_warning_blocks,
)
from utils import (
    inject_css, load_config, process_nc_data, make_arrow_safe_display_df,
    render_sidebar, render_sidebar_summary,
    page_header, section_label, callout_box, empty_state,
    progress_bar_row, apply_plotly_defaults, format_cycle_time,
    status_badge,
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
            font=dict(family="Inter, -apple-system, sans-serif", size=11, color=BODY),
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

    # ── Tool Life Monitoring (full width) ─────────────────────────────────────
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)

    with st.expander("Tool Life Monitoring", expanded=True):
        cutting_tool_ids = extract_cutting_tool_ids(df)

        if not cutting_tool_ids:
            st.info("No active cutting tool detected in this NC program.")
        else:
            st.markdown(
                "<div style='font-size:12px;color:#6a6a6a;margin-bottom:10px;'>"
                "Enter remaining tool life before machining."
                "</div>",
                unsafe_allow_html=True,
            )

            remaining_life_hours = {}

            input_cols = st.columns(min(6, len(cutting_tool_ids)))

            for idx_tool, tool_id in enumerate(cutting_tool_ids):
                with input_cols[idx_tool % len(input_cols)]:
                    remaining_life_hours[tool_id] = st.number_input(
                        f"T{tool_id} remaining life (h)",
                        min_value=0.0,
                        value=20.0,
                        step=0.5,
                        format="%.2f",
                        key=f"tool_life_{selected_machine}_{uploaded.name}_{tool_id}",
                    )

            tool_life_summary = build_tool_life_summary(df, remaining_life_hours)
            tool_life_warnings = build_tool_life_warning_blocks(df, remaining_life_hours)

            if not tool_life_summary.empty:
                worst_status = str(tool_life_summary["Status"].iloc[0]).upper()

                if worst_status == "FAIL":
                    status_bg = "#fdf1f0"
                    status_border = "#f5b8b4"
                    status_color = "#e2483b"
                    status_title = "Tool life is not enough"
                    status_msg = "At least one tool may fail before this NC program finishes."
                elif worst_status == "CRITICAL":
                    status_bg = "#fff4e5"
                    status_border = "#f2c27b"
                    status_color = "#c97b10"
                    status_title = "Critical remaining tool life"
                    status_msg = "At least one tool will finish with less than 10% remaining life."
                elif worst_status == "WARNING":
                    status_bg = "#fff8e8"
                    status_border = "#efd38a"
                    status_color = "#a66d00"
                    status_title = "Low remaining tool life"
                    status_msg = "At least one tool will finish with less than 20% remaining life."
                else:
                    status_bg = "#edf7f2"
                    status_border = "#a3d9bc"
                    status_color = "#1a8a50"
                    status_title = "Tool life check passed"
                    status_msg = "All detected cutting tools can complete this NC program."

                st.markdown(
                    f"""
                    <div style="
                        background:{status_bg};
                        border:1px solid {status_border};
                        border-radius:12px;
                        padding:13px 16px;
                        margin:4px 0 14px 0;
                    ">
                        <div style="
                            font-size:13px;
                            font-weight:700;
                            color:{status_color};
                            margin-bottom:3px;
                        ">
                            {status_title}
                        </div>
                        <div style="
                            font-size:12px;
                            color:#3f3f3f;
                            line-height:1.45;
                        ">
                            {status_msg}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # ── Tool life usage chart ───────────────────────────────
                chart_df = tool_life_summary.copy()

                chart_df["Used Display (%)"] = pd.to_numeric(
                    chart_df["Life Used (%)"],
                    errors="coerce"
                ).fillna(0.0).clip(lower=0.0, upper=100.0)

                chart_df["Remaining Display (%)"] = pd.to_numeric(
                    chart_df["Remaining (%)"],
                    errors="coerce"
                ).fillna(0.0).clip(lower=0.0, upper=100.0)

                fig_tool_life = go.Figure()

                fig_tool_life.add_trace(go.Bar(
                    y=chart_df["Tool"],
                    x=chart_df["Used Display (%)"],
                    name="Used in program",
                    orientation="h",
                    marker_color=PRIMARY,
                    customdata=chart_df[[
                        "Cutting Time in Program (h)",
                        "Life Used (%)",
                        "Status"
                    ]],
                    hovertemplate=(
                        "Tool: %{y}<br>"
                        "Used: %{customdata[0]:.4f} h<br>"
                        "Life used: %{customdata[1]:.2f}%<br>"
                        "Status: %{customdata[2]}"
                        "<extra></extra>"
                    ),
                ))

                fig_tool_life.add_trace(go.Bar(
                    y=chart_df["Tool"],
                    x=chart_df["Remaining Display (%)"],
                    name="Remaining after run",
                    orientation="h",
                    marker_color=SUCCESS,
                    customdata=chart_df[[
                        "Remaining After (h)",
                        "Remaining (%)",
                        "Status"
                    ]],
                    hovertemplate=(
                        "Tool: %{y}<br>"
                        "Remaining: %{customdata[0]:.4f} h<br>"
                        "Remaining: %{customdata[1]:.2f}%<br>"
                        "Status: %{customdata[2]}"
                        "<extra></extra>"
                    ),
                ))

                chart_height = max(210, 80 + 44 * len(chart_df))

                apply_plotly_defaults(
                    fig_tool_life,
                    title="Tool Life Usage",
                    height=chart_height,
                    margin=dict(l=8, r=8, t=38, b=8),
                )

                fig_tool_life.update_layout(
                    barmode="stack",
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                        font=dict(size=10),
                    ),
                    xaxis=dict(
                        title="Tool life (%)",
                        range=[0, 100],
                        ticksuffix="%",
                    ),
                    yaxis=dict(title=""),
                )

                st.plotly_chart(
                    fig_tool_life,
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

                # ── Compact summary table ───────────────────────────────
                th_style = (
                    "font-size:10px;font-weight:700;text-transform:uppercase;"
                    "letter-spacing:0.06em;color:#6a6a6a;padding:8px 10px 8px 0;"
                    "border-bottom:1.5px solid #e8eaed;"
                )
                td_bold_style = "font-size:13px;padding:9px 10px 9px 0;border-bottom:1px solid #f0f2f5;font-weight:600;color:#1a1a1a;"
                td_muted_style = "font-size:13px;padding:9px 10px 9px 0;border-bottom:1px solid #f0f2f5;color:#6a6a6a;"
                td_base_style = "font-size:13px;padding:9px 10px 9px 0;border-bottom:1px solid #f0f2f5;"

                summary_rows_html = []
                for _, row in tool_life_summary.iterrows():
                    summary_rows_html.append(f"""
                    <tr>
                        <td style="{td_bold_style}">{row['Tool']}</td>
                        <td style="{td_muted_style}">{float(row['Remaining After (h)']):.2f} h</td>
                        <td style="{td_base_style}">{status_badge(str(row['Status']))}</td>
                    </tr>""")

                st.markdown(f"""
                <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif;margin-top:6px;">
                    <thead>
                        <tr>
                            <th style="{th_style}text-align:left;">TOOL</th>
                            <th style="{th_style}text-align:left;">REMAINING AFTER</th>
                            <th style="{th_style}text-align:left;">STATUS</th>
                        </tr>
                    </thead>
                    <tbody>{"".join(summary_rows_html)}</tbody>
                </table>
                """, unsafe_allow_html=True)

            if not tool_life_warnings.empty:
                st.markdown(
                    "<div style='font-size:12px;font-weight:700;color:#3f3f3f;"
                    "margin-top:12px;margin-bottom:6px;'>"
                    "Warning / Critical / Failure Blocks"
                    "</div>",
                    unsafe_allow_html=True,
                )

                warning_cols = [
                    "Tool",
                    "Level",
                    "Line",
                    "NC Block",
                    "Remaining Life (h)",
                    "Threshold",
                ]

                st.dataframe(
                    make_arrow_safe_display_df(tool_life_warnings[warning_cols]),
                    use_container_width=True,
                    hide_index=True,
                )

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
