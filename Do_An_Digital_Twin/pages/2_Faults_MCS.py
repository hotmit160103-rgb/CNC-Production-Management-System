import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    build_time_breakdown,
    build_overtravel_table,
    build_top_time_blocks,
    build_microblock_report,
)
from utils import (
    inject_css, load_config, process_nc_data, make_arrow_safe_display_df,
    render_sidebar, render_sidebar_summary,
    page_header, section_label, status_banner, empty_state,
    apply_plotly_defaults, format_cycle_time,
    AXIS_COLORS, LIMIT_LINE_COLOR,
    INK, BODY, MUTED, CANVAS, PRIMARY, DANGER, SUCCESS, HAIRLINE, SHADOW,
    DANGER_LIGHT, DANGER_BORDER,
)

st.set_page_config(layout="wide", page_title="Faults & MCS — CNC Digital Twin", page_icon="⚠")
inject_css()

config = load_config()
if config is None:
    st.stop()

nc_files, selected_machine, cost_cfg, active_machine_cfg = render_sidebar(config)
config["active_machine_id"] = selected_machine
limits = active_machine_cfg["machine_g53"]["limits"]


def _block_label(raw_line: str, line_number) -> str:
    m = re.match(r"^(N\d+)", str(raw_line).strip().upper())
    return m.group(1) if m else f"N{int(line_number):04d}"


def _ot_log_html(df_ot: pd.DataFrame, axis_filter: str) -> str:
    """Render a custom HTML table for the overtravel log."""
    th = (
        "font-size:10px;font-weight:700;text-transform:uppercase;"
        "letter-spacing:0.06em;color:#6a6a6a;padding:8px 10px 8px 0;"
        "border-bottom:1.5px solid #e8eaed;"
    )
    td_base = "font-size:13px;padding:9px 10px 9px 0;border-bottom:1px solid #f0f2f5;"
    td_bold = td_base + "font-weight:600;color:#1a1a1a;"
    td_muted = td_base + "color:#6a6a6a;"
    td_red = td_base + "font-weight:700;color:#e2483b;"

    faulted = df_ot[df_ot["Safety Status"] == "FAULT"].copy()
    if axis_filter != "All":
        faulted = faulted[faulted["Axis"] == axis_filter]

    if faulted.empty:
        return '<p style="font-size:13px;color:#929292;padding:16px 0;">No overtravel events.</p>'

    rows = []
    for _, row in faulted.iterrows():
        raw_nc   = str(row.get("NC Block", ""))
        line_no  = row.get("Line", "—")
        axis     = str(row.get("Axis", ""))
        position = row.get("Checked MCS Position (mm)", 0)
        excess   = abs(float(row.get("Overtravel Amount (mm)", 0) or 0))

        # Which limit was exceeded?
        try:
            ax_key = axis.lower()
            l_min, l_max = limits[ax_key]
            pos_f = float(position)
            limit_str = f"+{l_max}" if pos_f > l_max else str(l_min)
        except Exception:
            limit_str = "—"

        try:
            pos_f = float(position)
            pos_str = f"+{pos_f:.1f} mm" if pos_f >= 0 else f"{pos_f:.1f} mm"
        except Exception:
            pos_str = str(position)

        block = _block_label(raw_nc, line_no)

        rows.append(f"""
        <tr>
            <td style="{td_bold}">{block}</td>
            <td style="{td_base}">{axis}</td>
            <td style="{td_muted}">{pos_str}</td>
            <td style="{td_muted}">{limit_str}</td>
            <td style="{td_red}">+{excess:.1f}</td>
        </tr>""")

    return f"""
    <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif;">
        <thead>
            <tr>
                <th style="{th}text-align:left;">BLOCK</th>
                <th style="{th}text-align:left;">AXIS</th>
                <th style="{th}text-align:left;">POSITION</th>
                <th style="{th}text-align:right;">LIMIT</th>
                <th style="{th}text-align:right;">EXCESS</th>
            </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
    </table>"""


def _pill_filter(options, selected_key: str, prefix: str) -> str:
    """Render inline pill radio using st.radio styled as pills."""
    return st.radio(
        "Axis filter",
        options,
        horizontal=True,
        key=f"{prefix}_{selected_key}",
        label_visibility="collapsed",
    )


if not nc_files:
    page_header("⚠ Faults & MCS")
    empty_state()
    st.stop()


for uploaded in nc_files:
    content = uploaded.getvalue().decode("utf-8", errors="ignore")

    with st.spinner("Analysing NC program…"):
        df_source, df = process_nc_data(content, config, selected_machine)

    if df.empty:
        st.warning(f"{uploaded.name} contains no valid trajectory data.")
        continue

    # ── Derived values ────────────────────────────────────────────────────────
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
    is_safe = fault_blocks == 0

    st.sidebar.divider()
    render_sidebar_summary(total_time, efficiency, fault_blocks)

    # ── Page header ───────────────────────────────────────────────────────────
    page_header(
        title="Faults & MCS Limits",

        subtitle=f"Machine Coordinate System overtravel check — {uploaded.name}",
    )

    # ── Status banner ─────────────────────────────────────────────────────────
    if is_safe:
        status_banner(True, "ALL AXES WITHIN LIMITS — No overtravel detected")
    else:
        # Find the axis with most faults and the peak overtravel amount
        worst_axis, peak_amount, peak_limit = "X", 0.0, 0.0
        for ax in ["X", "Y", "Z"]:
            amt_col = f"ot_amount_{ax.lower()}"
            if amt_col in df.columns:
                peak = float(df[amt_col].abs().max())
                if peak > peak_amount:
                    peak_amount = peak
                    worst_axis = ax
                    l_min, l_max = limits[ax.lower()]
                    ax_col = f"axis_{ax.lower()}"
                    if ax_col in df.columns:
                        max_pos = float(df[ax_col].max())
                        peak_limit = l_max if max_pos > l_max else l_min

        status_banner(
            False,
            f"{fault_blocks} OVERTRAVEL BLOCK{'S' if fault_blocks != 1 else ''} "
            f"— {worst_axis}-axis exceeded "
            f"{'+' if peak_limit >= 0 else ''}{peak_limit:.0f} mm limit "
            f"(peak {'+' if peak_amount >= 0 else ''}{peak_amount:.1f} mm)",
        )

    # ── Three axis charts ─────────────────────────────────────────────────────
    col_x, col_y, col_z = st.columns(3, gap="medium")

    for col, ax in zip([col_x, col_y, col_z], ["X", "Y", "Z"]):
        with col:
            col_name = f"axis_{ax.lower()}"
            ot_col   = f"ot_{ax.lower()}"
            color    = AXIS_COLORS[ax]
            l_min, l_max = limits[ax.lower()]

            # Card header above chart
            st.markdown(f"""
            <div class="chart-header">
                <div class="chart-title">{ax}-axis</div>
                <div class="chart-subtitle">Limit {l_min} to +{l_max} mm</div>
            </div>
            """, unsafe_allow_html=True)

            fig = go.Figure()
            if col_name in df.columns:
                plot_df = df.copy()
                plot_df[col_name] = pd.to_numeric(plot_df[col_name], errors="coerce")
                plot_df = plot_df.dropna(subset=[col_name, "time"])

                fig.add_trace(go.Scatter(
                    x=plot_df["time"], y=plot_df[col_name],
                    mode="lines", name=f"{ax}",
                    line=dict(color=color, width=1.8),
                    connectgaps=True,
                    hovertemplate="t=%{x:.2f}s  pos=%{y:.3f}mm<extra></extra>",
                ))

                for y_val, lbl in [(l_max, f"limit +{l_max}"), (l_min, f"limit {l_min}")]:
                    fig.add_hline(
                        y=y_val, line_dash="dash",
                        line_color=LIMIT_LINE_COLOR, line_width=1.2,
                        annotation_text=lbl,
                        annotation_position="right",
                        annotation_font=dict(size=9, color=DANGER),
                    )

                if ot_col in plot_df.columns and plot_df[ot_col].any():
                    df_ot_pts = plot_df[plot_df[ot_col]]
                    fig.add_trace(go.Scatter(
                        x=df_ot_pts["time"], y=df_ot_pts[col_name],
                        mode="markers", name="Overtravel",
                        marker=dict(color=DANGER, symbol="x", size=9, line=dict(width=2)),
                        hoverinfo="skip",
                    ))

                    # Peak overtravel annotation
                    ot_amt_col = f"ot_amount_{ax.lower()}"
                    if ot_amt_col in df_ot_pts.columns:
                        peak_idx = df_ot_pts[ot_amt_col].abs().idxmax()
                    else:
                        peak_idx = df_ot_pts[col_name].abs().idxmax()

                    peak = df_ot_pts.loc[peak_idx]
                    peak_t   = float(peak["time"])
                    peak_pos = float(peak[col_name])
                    peak_ln  = peak.get("line_number", "?")
                    peak_raw = str(peak.get("raw_line", ""))
                    blk_lbl  = _block_label(peak_raw, peak_ln)

                    fig.add_annotation(
                        x=peak_t, y=peak_pos,
                        text=f"<b>OVERTRAVEL</b><br>{blk_lbl} · {peak_pos:.1f} mm",
                        showarrow=True, arrowhead=2,
                        arrowcolor=DANGER, arrowwidth=1.5,
                        ax=0, ay=-50,
                        font=dict(size=9, color=DANGER),
                        bgcolor="rgba(255,255,255,0.92)",
                        bordercolor=DANGER, borderwidth=1,
                        borderpad=4,
                    )

            apply_plotly_defaults(
                fig, height=240,
                margin=dict(l=8, r=48, t=10, b=8),
            )
            fig.update_layout(
                xaxis_title="Time (s)", yaxis_title="mm (MCS)",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Critical Blocks + Overtravel Log ──────────────────────────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    col_bar, col_log = st.columns([3, 2], gap="large")

    with col_bar:
        section_label("Critical Blocks (Top 10)", margin_top=0)
        df_top = build_top_time_blocks(df, top_n=10)

        if not df_top.empty:
            top_plot = df_top.sort_values("Time (s)").tail(10)
            labels = [
                _block_label(str(r["NC Block"]), r["Line"])
                for _, r in top_plot.iterrows()
            ]
            times = top_plot["Time (s)"].tolist()

            fig_top = go.Figure(go.Bar(
                x=times, y=labels,
                orientation="h",
                marker_color=PRIMARY,
                marker_line_width=0,
                text=[f"{t:.1f}s" for t in times],
                textposition="outside",
                textfont=dict(size=11, color="#222222"),
                hovertemplate="%{y}: %{x:.3f} s<extra></extra>",
            ))
            apply_plotly_defaults(
                fig_top,
                height=max(220, len(labels) * 34 + 24),
                margin=dict(l=8, r=52, t=8, b=8),
            )
            fig_top.update_layout(
                xaxis_title="Duration (s)", yaxis_title="",
                showlegend=False,
            )
            fig_top.update_yaxes(tickfont=dict(size=12, color="#111111", family="Inter, -apple-system, sans-serif"))
            st.plotly_chart(fig_top, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No block statistics available.")

    with col_log:
        hdr_col, filter_col = st.columns([1, 2])
        with hdr_col:
            section_label("Overtravel Log", margin_top=0)

        # Pill filter buttons using radio
        ot_axis_filter = st.radio(
            "Axis",
            ["All", "X", "Y", "Z"],
            horizontal=True,
            key="ot_axis_filter",
            label_visibility="collapsed",
        )

        df_ot_table = build_overtravel_table(df=df, limits=limits)
        st.markdown(
            _ot_log_html(df_ot_table, ot_axis_filter),
            unsafe_allow_html=True,
        )

    # ── CAM Quality Notes ─────────────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with st.expander("▸ CAM Trajectory Quality Notes"):
        df_micro = build_microblock_report(df)
        if df_micro.empty:
            st.info("No microblock data available.")
        else:
            st.dataframe(
                make_arrow_safe_display_df(df_micro),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Metric": st.column_config.TextColumn("Metric", width="large"),
                    "Value":  st.column_config.TextColumn("Value", width="medium"),
                },
            )

    st.divider()
