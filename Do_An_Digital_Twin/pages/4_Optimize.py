import plotly.graph_objects as go
import streamlit as st

from analytics import (
    build_time_breakdown, build_top_time_blocks,
    build_microblock_report, build_saving_recommendations,
)
from utils import (
    inject_css, load_config, process_nc_data, get_cost_cfg,
    render_sidebar, render_sidebar_summary,
    page_header, section_label, callout_box, empty_state,
    recommendation_card,
    format_cycle_time, apply_plotly_defaults,
    INK, BODY, MUTED, CANVAS, PRIMARY, DANGER, SUCCESS, WARNING,
    DANGER_LIGHT, WARNING_LIGHT, SURFACE_STRONG,
    TIME_CATEGORY_COLORS,
)

st.set_page_config(layout="wide", page_title="Optimize — CNC Digital Twin", page_icon="⚡")
inject_css()

config = load_config()
if config is None:
    st.stop()

nc_files, selected_machine, _ignored, active_machine_cfg = render_sidebar(config)
config["active_machine_id"] = selected_machine
cost_cfg = get_cost_cfg()  # reads session state set by Costing page

if not nc_files:
    page_header("⚡ Optimization Opportunities")
    empty_state()
    st.stop()

for uploaded in nc_files:
    content = uploaded.getvalue().decode("utf-8", errors="ignore")

    with st.spinner("Analysing NC program…"):
        df_source, df = process_nc_data(content, config, selected_machine)

    if df.empty:
        st.warning(f"{uploaded.name} contains no valid trajectory data.")
        continue

    df_time_breakdown   = build_time_breakdown(df)
    df_top_blocks       = build_top_time_blocks(df, top_n=10)
    df_micro            = build_microblock_report(df)
    df_recs             = build_saving_recommendations(
        df_time_breakdown=df_time_breakdown,
        df_top_blocks=df_top_blocks,
        df_microblock=df_micro,
        cost_cfg=cost_cfg,
    )

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

    # ── Calculate total estimated savings ─────────────────────────────────────
    def _parse_seconds(s: str) -> float:
        try:
            return float(str(s).replace("s/part", "").strip())
        except Exception:
            return 0.0

    def _parse_vnd(s: str) -> float:
        try:
            return float(str(s).replace("VND", "").replace(",", "").strip())
        except Exception:
            return 0.0

    real_recs = df_recs[df_recs["Priority"] != "Monitoring"] if not df_recs.empty else df_recs
    total_saving_s   = sum(_parse_seconds(r) for r in real_recs.get("Estimated Time Saving", []))
    total_saving_vnd = sum(_parse_vnd(r) for r in real_recs.get("Saving per Part", []))

    page_header(
        title="⚡ Optimization Opportunities",

        subtitle=f"Estimated potential savings for {uploaded.name}",
    )

    # ── Savings summary callout ───────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:#f7f7f7;border:1px solid #dddddd;border-radius:14px;
                padding:18px 24px;margin-bottom:24px;
                box-shadow:rgba(0,0,0,.02) 0 0 0 1px, rgba(0,0,0,.04) 0 2px 6px 0;">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;">
            <span style="font-size:11px;font-weight:700;text-transform:uppercase;
                         letter-spacing:0.07em;color:{MUTED};">Estimated saving</span>
            <span style="font-size:22px;font-weight:700;color:{INK};letter-spacing:-0.02em;">
                {total_saving_s:.1f} s/part
            </span>
            <span style="font-size:16px;color:{MUTED};">≈</span>
            <span style="font-size:22px;font-weight:700;color:{SUCCESS};letter-spacing:-0.02em;">
                {total_saving_vnd:,.0f} VND/part
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Potential time savings chart ──────────────────────────────────────────
    section_label("Potential Time Savings", margin_top=0)

    priority_color_map = {
        "High":       DANGER,
        "Medium":     WARNING,
        "Low/Medium": WARNING,
        "Low":        MUTED,
        "Monitoring": MUTED,
    }
    category_color_map = {
        "Reduce Non-cutting Rapid Positioning Time":       TIME_CATEGORY_COLORS["Non-cutting Rapid Positioning Time"],
        "Review Non-cutting Rapid Positioning":            TIME_CATEGORY_COLORS["Non-cutting Rapid Positioning Time"],
        "Optimize Effective Cutting Interpolation Time":   TIME_CATEGORY_COLORS["Effective Cutting Interpolation Time"],
        "Validate Spindle Start or Speed Change Model":    TIME_CATEGORY_COLORS["Spindle Start or Speed Change Time"],
        "Review Automatic Tool Change Time":               TIME_CATEGORY_COLORS["Automatic Tool Change Time"],
        "Reduce Micro-block Density":                      "#5b6fa8",
    }

    savings_chart_rows = []
    for _, row in df_recs.iterrows():
        item     = str(row.get("Optimization Item", ""))
        priority = str(row.get("Priority", "Low"))
        saving_s = _parse_seconds(row.get("Estimated Time Saving", "0"))

        if priority == "Monitoring" or saving_s <= 0:
            continue

        bar_color = category_color_map.get(item, priority_color_map.get(priority, MUTED))
        savings_chart_rows.append((item, saving_s, priority, bar_color))

    if savings_chart_rows:
        savings_chart_rows.sort(key=lambda r: r[1])  # ascending: largest saving renders at the top of the h-bar

        items_sorted     = [r[0] for r in savings_chart_rows]
        savings_sorted   = [r[1] for r in savings_chart_rows]
        colors_sorted    = [r[3] for r in savings_chart_rows]
        priorities_sorted = [r[2] for r in savings_chart_rows]

        fig_savings = go.Figure(go.Bar(
            x=savings_sorted, y=items_sorted,
            orientation="h",
            marker_color=colors_sorted,
            text=[f"{s:.1f} s" for s in savings_sorted],
            textposition="outside",
            textfont=dict(size=11, color="#222222"),
            customdata=priorities_sorted,
            hovertemplate="%{y}<br>Saving: %{x:.2f} s/part<br>Priority: %{customdata}<extra></extra>",
        ))
        apply_plotly_defaults(
            fig_savings,
            height=max(200, len(savings_chart_rows) * 46 + 40),
            margin=dict(l=8, r=64, t=8, b=8),
        )
        fig_savings.update_layout(xaxis_title="Estimated Saving (s/part)", yaxis_title="", showlegend=False)
        fig_savings.update_yaxes(tickfont=dict(size=12, color="#111111", family="Inter, -apple-system, sans-serif"))
        st.plotly_chart(fig_savings, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("No time-saving opportunities identified for this NC program.")

    # ── Recommendation cards ──────────────────────────────────────────────────
    section_label("Recommendations", margin_top=8)

    monitoring_items = []
    for _, row in df_recs.iterrows():
        item     = str(row.get("Optimization Item", ""))
        priority = str(row.get("Priority", "Low"))
        saving_str = str(row.get("Estimated Time Saving", ""))
        saving_vnd = str(row.get("Saving per Part", ""))
        action   = str(row.get("Recommended Action", ""))
        current  = str(row.get("Current State", ""))

        if priority == "Monitoring":
            monitoring_items.append((item, action, current))
            continue

        display_saving = f"Saving: {saving_str}  ·  {saving_vnd}" if saving_str and saving_str != "0.000 s/part" else ""
        recommendation_card(priority, item, display_saving, detail=action)

    if monitoring_items:
        with st.expander("▸ Monitoring Items"):
            for m_item, m_action, m_current in monitoring_items:
                st.markdown(f"""
                <div style="padding:10px 0;border-bottom:1px solid #ebebeb;">
                    <div style="font-size:13px;font-weight:600;color:{INK};margin-bottom:3px;">{m_item}</div>
                    <div style="font-size:12px;color:{MUTED};">{m_current}</div>
                    <div style="font-size:12px;color:{BODY};margin-top:2px;">{m_action}</div>
                </div>
                """, unsafe_allow_html=True)

    st.divider()
