import plotly.graph_objects as go
import streamlit as st

from analytics import build_time_breakdown
from utils import (
    inject_css, load_config, process_nc_data,
    render_sidebar, render_sidebar_summary,
    page_header, kpi_card, section_label, callout_box, empty_state,
    progress_bar_row, apply_plotly_defaults, format_cycle_time,
    get_cost_cfg, _COST_DEFAULTS, _COST_KEYS,
    INK, BODY, MUTED, CANVAS, PRIMARY, SUCCESS, WARNING, SHADOW,
    HAIRLINE, HAIRLINE_SOFT,
)

st.set_page_config(layout="wide", page_title="Costing — CNC Digital Twin", page_icon="💰")
inject_css()

config = load_config()
if config is None:
    st.stop()

nc_files, selected_machine, _cost_cfg_ignored, active_machine_cfg = render_sidebar(config)
config["active_machine_id"] = selected_machine

if not nc_files:
    page_header("💰 Costing")
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
        title="Machining Cost Estimator",
        subtitle=f"{uploaded.name}  ·  {active_machine_cfg.get('machine_name', selected_machine)}",
    )

    # ── Layout: results (left 3) | cost parameters inputs (right 2) ──────────
    col_results, col_params = st.columns([3, 2], gap="large")

    with col_params:
        # ── Parameters panel ─────────────────────────────────────────────────
        st.markdown(
            '<div style="background:#f8faff;border:1.5px solid #e4eaf4;border-radius:14px;'
            'padding:20px 22px 24px;">'
            '<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.09em;color:#505a6a;margin-bottom:18px;">Cost Parameters</div>',
            unsafe_allow_html=True,
        )

        # Interactive inputs — values stored in session state and shared with Optimize page
        mhr  = st.number_input("Machine rate (VND/h)",  key=_COST_KEYS["machine_hour_rate"],
                               min_value=0.0, step=10000.0, value=float(_COST_DEFAULTS["machine_hour_rate"]))
        lhr  = st.number_input("Labour rate (VND/h)",   key=_COST_KEYS["labor_hour_rate"],
                               min_value=0.0, step=10000.0, value=float(_COST_DEFAULTS["labor_hour_rate"]))
        thr  = st.number_input("Tooling rate (VND/h)",  key=_COST_KEYS["tooling_hour_rate"],
                               min_value=0.0, step=10000.0, value=float(_COST_DEFAULTS["tooling_hour_rate"]))
        ehr  = st.number_input("Energy rate (VND/h)",   key=_COST_KEYS["energy_hour_rate"],
                               min_value=0.0, step=5000.0,  value=float(_COST_DEFAULTS["energy_hour_rate"]))
        ohr  = st.number_input("Overhead rate (VND/h)", key=_COST_KEYS["overhead_hour_rate"],
                               min_value=0.0, step=10000.0, value=float(_COST_DEFAULTS["overhead_hour_rate"]))
        bqty = st.number_input("Batch quantity",        key=_COST_KEYS["batch_quantity"],
                               min_value=1, step=1,         value=int(_COST_DEFAULTS["batch_quantity"]))

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        total_rate = mhr + lhr + thr + ehr + ohr
        callout_box("Total Manufacturing Rate", f"{total_rate:,.0f}", "VND/h")

    # ── Cost calculations (use inputs from right panel) ───────────────────────
    mhr = float(mhr); lhr = float(lhr); thr = float(thr)
    ehr = float(ehr); ohr = float(ohr); bqty = int(bqty)
    total_rate   = mhr + lhr + thr + ehr + ohr
    cycle_h      = total_time / 3600.0 if total_time > 0 else 0.0
    parts_per_hour = 3600.0 / total_time if total_time > 0 else 0.0
    cost_per_part  = cycle_h * total_rate
    cost_per_batch = cost_per_part * bqty

    with col_results:
        # ── KPI cards ─────────────────────────────────────────────────────────
        k1, k2, k3 = st.columns(3)
        with k1:
            kpi_card("Cost / Part", f"{cost_per_part:,.0f}", "VND",
                     delta=f"{time_val} {time_unit} cycle", accent=PRIMARY)
        with k2:
            kpi_card("Total Rate", f"{total_rate:,.0f}", "VND/h", accent=WARNING)
        with k3:
            kpi_card("Batch Total", f"{cost_per_batch:,.0f}", "VND",
                     delta=f"{bqty:,} parts", accent=SUCCESS)

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        section_label("Cost Breakdown per Part", margin_top=0)

        cost_items = [
            ("Machine",  mhr  * cycle_h, "#1a2b4a"),
            ("Labour",   lhr  * cycle_h, "#1a8a50"),
            ("Tooling",  thr  * cycle_h, "#c97b10"),
            ("Energy",   ehr  * cycle_h, "#5b6fa8"),
            ("Overhead", ohr  * cycle_h, "#aab0be"),
        ]
        for name, cost, color in cost_items:
            pct = (cost / cost_per_part * 100.0) if cost_per_part > 0 else 0.0
            progress_bar_row(name, cost, pct, color, right_text=f"{cost:,.0f} VND")

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Pie chart
        labels = [n for n, _, _ in cost_items]
        values = [c for _, c, _ in cost_items]
        colors = [col for _, _, col in cost_items]
        pie = go.Figure(go.Pie(
            labels=labels, values=values,
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            hole=0.45, textinfo="percent",
            textfont=dict(size=11, family="Inter, -apple-system, sans-serif", color="#ffffff"),
            hovertemplate="%{label}: %{value:,.0f} VND (%{percent})<extra></extra>",
        ))
        pie.update_layout(
            height=220, margin=dict(l=8, r=8, t=8, b=8),
            paper_bgcolor=CANVAS,
            font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#333333"),
            legend=dict(
                font=dict(size=11, family="Inter, -apple-system, sans-serif", color="#333333"),
                orientation="h", y=-0.1,
            ),
            showlegend=True,
        )
        st.plotly_chart(pie, use_container_width=True, config={"displayModeBar": False})

        callout_box("Estimated Throughput", f"{parts_per_hour:.2f}", "parts / hour")

    st.divider()
