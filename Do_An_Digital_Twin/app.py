import html
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.engine import GCodeEngine
from transformation import DigitalTwinTransformer
from analytics import (
    build_production_summary,
    build_time_breakdown,
    build_event_diagnostics,
    build_overtravel_table,
    build_top_time_blocks,
    build_microblock_report,
    build_cost_summary,
    build_saving_recommendations,
)


st.set_page_config(
    layout="wide",
    page_title="CNC Production Management System",
    page_icon="⚙️"
)


@st.cache_data
def load_config():
    try:
        from pathlib import Path

        BASE_DIR = Path(__file__).parent
        CONFIG_PATH = BASE_DIR / "config.json"

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Configuration file loading error: {e}")
        return None


config = load_config()

if config is None:
    st.stop()

def _display_value_to_text(value):
    """
    Convert mixed object values to text before rendering with Streamlit.
    This avoids PyArrow serialization errors caused by mixed int/float/str columns.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value)


def make_arrow_safe_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare DataFrame for Streamlit display.

    Numeric columns remain numeric.
    Mixed object columns are converted to string dtype.
    """
    if df is None:
        return pd.DataFrame()

    safe_df = df.copy()

    for col in safe_df.columns:
        if safe_df[col].dtype == "object":
            safe_df[col] = safe_df[col].map(_display_value_to_text).astype("string")

    return safe_df


@st.cache_data(show_spinner=False)
def process_nc_data(content: str, config_snapshot: dict, machine_id: str):
    """
    Parse and simulate an NC program into a point-level time-series log.

    Scope of this step:
    - Keep the existing motion timing model unchanged.
    - Preserve M-code event information for analytics tables.
    - Do not apply measured cycle-time correction.
    """
    config_snapshot["active_machine_id"] = machine_id

    engine = GCodeEngine(config_snapshot)
    transformer = DigitalTwinTransformer(config_snapshot)

    source_lines = []
    flat_logs = []

    for i, line in enumerate(content.splitlines(), start=1):
        source_lines.append({"line_number": i, "raw_line": line})
        cmd = engine.parse_line(line)
        block_dict = {
            "tokens": cmd if isinstance(cmd, dict) else {},
            "line_number": i,
            "raw_line": line
        }

        block_start_time = float(transformer.state.get("current_time", 0.0))
        segments = transformer.apply_block(block_dict)
        block_end_time = float(transformer.state.get("current_time", 0.0))

        for seg in segments:
            seg_start_time = float(seg.get("start_time", block_start_time))
            seg_end_time = float(seg.get("end_time", block_end_time))

            if seg.get("type") == "motion" and "trajectory_slide" in seg:
                points = seg["trajectory_slide"]

                for pt in points:
                    point_time = pt.get("t", seg_end_time)

                    flat_logs.append({
                        "time": float(point_time),

                        "axis_x": pt.get("X"),
                        "axis_y": pt.get("Y"),
                        "axis_z": pt.get("Z"),

                        "tip_x": pt.get("tip_x"),
                        "tip_y": pt.get("tip_y"),
                        "tip_z": pt.get("tip_z"),

                        "line_number": pt.get("line_number", i),
                        "raw_line": pt.get("raw_line", line),

                        "motion_mode": pt.get("motion_mode", seg.get("motion_mode")),
                        "is_air_time": pt.get("is_air_time", seg.get("is_air_time", False)),

                        "event_type": "",
                        "event_duration_s": 0.0,
                        "event_duration_source": "",

                        "previous_tool_id": None,
                        "next_tool_id": None,
                        "station_count": None,
                        "tool_station_steps": None,

                        "spindle_rpm_before": None,
                        "spindle_rpm_target": None,

                        "feedrate": float(pt.get("feedrate", transformer.state.get("feedrate", 0))),
                        "rpm": float(pt.get("rpm", transformer.state.get("rpm", 0))),
                        "tool_id": str(pt.get("tool_id", transformer.state.get("active_tool_id", "None"))),

                        "H_length": float(transformer.state.get("H_length", 0.0)),
                        "H_status": pt.get("H_status", transformer.state.get("H_status", "")),
                        "tool_length_warning": pt.get(
                            "tool_length_warning",
                            transformer.state.get("tool_length_warning", "")
                        ),

                        "ot_x": bool(pt.get("ot_x", False)),
                        "ot_y": bool(pt.get("ot_y", False)),
                        "ot_z": bool(pt.get("ot_z", False)),

                        "ot_amount_x": float(pt.get("ot_amount_x", 0.0)),
                        "ot_amount_y": float(pt.get("ot_amount_y", 0.0)),
                        "ot_amount_z": float(pt.get("ot_amount_z", 0.0)),
                    })

            else:
                event_type = seg.get("event_type", "UNKNOWN")
                event_duration = float(seg.get("duration", max(seg_end_time - seg_start_time, 0.0)))
                event_times = [seg_start_time, seg_end_time] if seg_end_time > seg_start_time else [seg_start_time]

                slide_pos = transformer.compute_slide_g53()
                tip_pos = transformer.compute_tip_g53()

                for idx_event, event_time in enumerate(event_times):
                    is_event_end = idx_event == len(event_times) - 1

                    flat_logs.append({
                        "time": float(event_time),

                        "axis_x": slide_pos["X"],
                        "axis_y": slide_pos["Y"],
                        "axis_z": slide_pos["Z"],

                        "tip_x": tip_pos["X"],
                        "tip_y": tip_pos["Y"],
                        "tip_z": tip_pos["Z"],

                        "line_number": i,
                        "raw_line": line,

                        "motion_mode": "event",
                        "is_air_time": True,

                        "event_type": event_type,
                        "event_duration_s": event_duration if is_event_end else 0.0,
                        "event_duration_source": seg.get("event_duration_source", ""),

                        "previous_tool_id": seg.get("previous_tool_id"),
                        "next_tool_id": seg.get("next_tool_id"),
                        "station_count": seg.get("station_count"),
                        "tool_station_steps": seg.get("tool_station_steps"),

                        "spindle_rpm_before": seg.get("spindle_rpm_before"),
                        "spindle_rpm_target": seg.get("spindle_rpm_target"),

                        "feedrate": float(transformer.state.get("feedrate", 0)),
                        "rpm": float(
                            transformer.state.get(
                                "actual_spindle_rpm",
                                transformer.state.get("rpm", 0)
                            )
                        ),
                        "tool_id": str(transformer.state.get("active_tool_id", "None")),

                        "H_length": float(transformer.state.get("H_length", 0.0)),
                        "H_status": transformer.state.get("H_status", ""),
                        "tool_length_warning": transformer.state.get("tool_length_warning", ""),

                        "ot_x": False,
                        "ot_y": False,
                        "ot_z": False,
                        "ot_amount_x": 0.0,
                        "ot_amount_y": 0.0,
                        "ot_amount_z": 0.0,
                    })

    df_source_nc = pd.DataFrame(source_lines)
    df = pd.DataFrame(flat_logs)

    if not df.empty:
        df = df.sort_values(by=["time", "line_number"]).reset_index(drop=True)

        for col in ["axis_x", "axis_y", "axis_z"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df[["axis_x", "axis_y", "axis_z"]] = df[["axis_x", "axis_y", "axis_z"]].ffill().bfill()
        df[["feedrate", "rpm"]] = df[["feedrate", "rpm"]].fillna(0)

        event_cols_default = {
            "event_type": "",
            "event_duration_s": 0.0,
            "event_duration_source": "",
            "previous_tool_id": "",
            "next_tool_id": "",
            "station_count": "",
            "tool_station_steps": "",
            "spindle_rpm_before": "",
            "spindle_rpm_target": ""
        }

        for col, default_value in event_cols_default.items():
            if col not in df.columns:
                df[col] = default_value
            else:
                df[col] = df[col].fillna(default_value)

    return df_source_nc, df


# =============================================================================
# Sidebar
# =============================================================================
st.sidebar.markdown("## CNC Production Management System")
st.sidebar.info("NC program analysis, cycle time prediction and physical overtravel validation")

if "machines" not in config:
    st.sidebar.error("config.json does not contain the required 'machines' key.")
    st.stop()

machine_ids = list(config["machines"].keys())

default_machine = config.get("active_machine_id", machine_ids[0])
if default_machine not in machine_ids:
    default_machine = machine_ids[0]

selected_machine = st.sidebar.selectbox(
    "CNC Machine",
    machine_ids,
    index=machine_ids.index(default_machine)
)

config["active_machine_id"] = selected_machine
active_machine_cfg = config["machines"][selected_machine]

machine_control = active_machine_cfg.get("control", "N/A")
limits = active_machine_cfg["machine_g53"]["limits"]
limit_status = active_machine_cfg["machine_g53"].get("limit_status", "unknown")

st.sidebar.markdown("### Machine Information")
st.sidebar.write(f"Machine ID: {selected_machine}")
st.sidebar.write(f"Machine Name: {active_machine_cfg.get('machine_name', 'N/A')}")
st.sidebar.write(f"Controller: {machine_control}")

st.sidebar.markdown("### Machine Travel Limits")
st.sidebar.write(f"X: {limits['x'][0]} → {limits['x'][1]} mm")
st.sidebar.write(f"Y: {limits['y'][0]} → {limits['y'][1]} mm")
st.sidebar.write(f"Z: {limits['z'][0]} → {limits['z'][1]} mm")
st.sidebar.write(f"MCS Limit Source: {limit_status}")

nc_files = st.sidebar.file_uploader(
    "Import NC Program",
    accept_multiple_files=True
)

st.sidebar.markdown("### Industrial Cost Parameters")

machine_hour_rate = st.sidebar.number_input(
    "Machine hourly rate (VND/h)",
    min_value=0.0,
    value=150000.0,
    step=10000.0
)

labor_hour_rate = st.sidebar.number_input(
    "Labor hourly rate (VND/h)",
    min_value=0.0,
    value=50000.0,
    step=10000.0
)

tooling_hour_rate = st.sidebar.number_input(
    "Tooling hourly rate (VND/h)",
    min_value=0.0,
    value=30000.0,
    step=10000.0
)

energy_hour_rate = st.sidebar.number_input(
    "Energy hourly rate (VND/h)",
    min_value=0.0,
    value=10000.0,
    step=5000.0
)

overhead_hour_rate = st.sidebar.number_input(
    "Factory overhead rate (VND/h)",
    min_value=0.0,
    value=20000.0,
    step=10000.0
)

batch_quantity = st.sidebar.number_input(
    "Batch quantity",
    min_value=1,
    value=100,
    step=1
)

cost_cfg = {
    "machine_hour_rate": machine_hour_rate,
    "labor_hour_rate": labor_hour_rate,
    "tooling_hour_rate": tooling_hour_rate,
    "energy_hour_rate": energy_hour_rate,
    "overhead_hour_rate": overhead_hour_rate,
    "batch_quantity": batch_quantity
}

if not nc_files:
    st.title("Digital Twin Dashboard")
    st.info("Import an NC program to start the production analysis.")
    st.stop()


# =============================================================================
# Main rendering
# =============================================================================
for uploaded in nc_files:
    content = uploaded.getvalue().decode("utf-8", errors="ignore")

    with st.spinner("Analyzing NC program..."):
        df_source_nc, df = process_nc_data(content, config, selected_machine)

    if df.empty:
        st.warning(f"File {uploaded.name} does not contain valid trajectory data.")
        continue

    st.markdown(f"### NC Program Analysis: `{uploaded.name}`")

    timeline_total_time = float(df["time"].max())
    df_time_breakdown = build_time_breakdown(df)

    total_row = df_time_breakdown[
        df_time_breakdown["Category"].astype(str).str.strip() == "Total Machining Cycle Time"
    ]

    if not total_row.empty:
        total_time = float(total_row["Time (s)"].iloc[0])
    else:
        total_time = timeline_total_time

    total_pts = len(df)
    df_errors = df[(df["ot_x"]) | (df["ot_y"]) | (df["ot_z"])]
    error_lines_count = len(df_errors["line_number"].unique())
    ot_x_count = int(df["ot_x"].sum()) if "ot_x" in df.columns else 0
    ot_y_count = int(df["ot_y"].sum()) if "ot_y" in df.columns else 0
    ot_z_count = int(df["ot_z"].sum()) if "ot_z" in df.columns else 0

    st.caption(
        f"Overtravel points in MCS — X: {ot_x_count}, Y: {ot_y_count}, Z: {ot_z_count}"
    )

    if "tool_length_warning" in df.columns:
        tool_warnings = sorted(
            set(
                str(x) for x in df["tool_length_warning"].dropna().unique()
                if str(x).strip()
            )
        )
        if tool_warnings:
            st.warning("Tool data warning: " + "; ".join(tool_warnings))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Machining Cycle Time", f"{total_time:.2f} s")
    m2.metric("Interpolated Trajectory Points", f"{total_pts} pts")

    if error_lines_count > 0:
        m3.metric(
            "NC Blocks with Faults",
            f"{error_lines_count} blocks",
            delta="Overtravel",
            delta_color="inverse"
        )
        m4.metric(
            "MCS Safety Status",
            "FAULT",
            delta="Stop required",
            delta_color="inverse"
        )
    else:
        m3.metric("NC Blocks with Faults", "0 blocks")
        m4.metric("MCS Safety Status", "SAFE", delta="No overtravel fault", delta_color="normal")

    st.markdown("### Production Analytics")

    df_production_summary = build_production_summary(
        df=df,
        file_name=uploaded.name,
        machine_id=selected_machine,
        machine_cfg=active_machine_cfg
    )

    df_event_diagnostics = build_event_diagnostics(df)

    df_overtravel_table = build_overtravel_table(
        df=df,
        limits=active_machine_cfg["machine_g53"]["limits"]
    )

    df_top_blocks = build_top_time_blocks(df, top_n=10)
    df_microblock = build_microblock_report(df)

    df_cost_summary = build_cost_summary(
        total_time_s=float(total_time),
        cost_cfg=cost_cfg
    )

    df_saving_recommendations = build_saving_recommendations(
        df_time_breakdown=df_time_breakdown,
        df_top_blocks=df_top_blocks,
        df_microblock=df_microblock,
        cost_cfg=cost_cfg
    )

    tab_sum, tab_time, tab_event, tab_ot, tab_top, tab_micro, tab_cost, tab_saving = st.tabs([
        "Overview",
        "Cycle Time",
        "M-code Events",
        "MCS Limits",
        "Critical Blocks",
        "CAM Quality",
        "Costing",
        "Optimization"
    ])

    with tab_sum:
        st.dataframe(
            make_arrow_safe_display_df(df_production_summary),
            width="stretch",
            hide_index=True
        )

    with tab_time:
        st.caption(
            "Detailed cycle time breakdown by cutting interpolation, rapid positioning and non-productive machine events."
        )
        st.dataframe(
            make_arrow_safe_display_df(df_time_breakdown),
            width="stretch",
            hide_index=True,
            height=300,
            column_config={
                "Category": st.column_config.TextColumn("Category", width="large"),
                "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                "Time (s)": st.column_config.NumberColumn("Time", format="%.3f s", width="small"),
                "Share (%)": st.column_config.NumberColumn("Share", format="%.2f %%", width="small"),
                "Technical Meaning": st.column_config.TextColumn("Technical Meaning", width="large")
            }
        )

    with tab_event:
        st.caption(
            "Non-productive M-code event diagnostics for spindle events, program stops and automatic tool change cycles."
        )
        st.dataframe(
            make_arrow_safe_display_df(df_event_diagnostics),
            width="stretch",
            hide_index=True,
            height=360,
            column_config={
                "Line": st.column_config.NumberColumn("Line", width="small"),
                "NC Block": st.column_config.TextColumn("NC Block", width="medium"),
                "M-code": st.column_config.TextColumn("M-code", width="small"),
                "Initial State": st.column_config.TextColumn("Initial State", width="medium"),
                "Target State": st.column_config.TextColumn("Target State", width="medium"),
                "Model Basis": st.column_config.TextColumn("Model Basis", width="large"),
                "Event Time (s)": st.column_config.NumberColumn("Event Time", format="%.3f s", width="small"),
                "Data Confidence": st.column_config.TextColumn("Data Confidence", width="medium"),
                "Required Calibration": st.column_config.TextColumn("Required Calibration", width="large")
            }
        )

    with tab_ot:
        st.dataframe(make_arrow_safe_display_df(df_overtravel_table), width="stretch", hide_index=True)

    with tab_top:
        st.dataframe(make_arrow_safe_display_df(df_top_blocks), width="stretch", hide_index=True)

    with tab_micro:
        st.dataframe(make_arrow_safe_display_df(df_microblock), width="stretch", hide_index=True)

    with tab_cost:
        st.dataframe(make_arrow_safe_display_df(df_cost_summary), width="stretch", hide_index=True)

    with tab_saving:
        st.dataframe(make_arrow_safe_display_df(df_saving_recommendations), width="stretch", hide_index=True)

    st.divider()

    st.markdown("#### Graph 1: MCS Axis Travel Monitoring")
    limits = active_machine_cfg["machine_g53"]["limits"]
    colors = {"X": "#EF553B", "Y": "#00CC96", "Z": "#636EFA"}

    g1_c1, g1_c2, g1_c3 = st.columns(3)
    g1_cols = [g1_c1, g1_c2, g1_c3]

    for idx, ax in enumerate(["X", "Y", "Z"]):
        with g1_cols[idx]:
            fig = go.Figure()
            col_name = f"axis_{ax.lower()}"

            if col_name in df.columns:
                plot_df = df.copy()
                plot_df[col_name] = pd.to_numeric(plot_df[col_name], errors="coerce")
                plot_df = plot_df.dropna(subset=[col_name, "time"])

                fig.add_trace(go.Scatter(
                    x=plot_df["time"],
                    y=plot_df[col_name],
                    mode="lines",
                    name=f"{ax}-axis travel",
                    line=dict(color=colors[ax], width=2.5),
                    connectgaps=True,
                    customdata=plot_df[["line_number", "raw_line"]],
                    hovertemplate=(
                        "Time: %{x:.2f} s<br>"
                        "Position: %{y:.3f} mm<br>"
                        "Line %{customdata[0]}: %{customdata[1]}"
                        "<extra></extra>"
                    )
                ))

                l_min, l_max = limits[ax.lower()]
                fig.add_hline(
                    y=l_max,
                    line_dash="dash",
                    line_color="rgba(255,0,0,0.6)",
                    annotation_text=f"Maximum {ax}: {l_max}"
                )
                fig.add_hline(
                    y=l_min,
                    line_dash="dash",
                    line_color="rgba(255,0,0,0.6)",
                    annotation_text=f"Minimum {ax}: {l_min}"
                )

                ot_col = f"ot_{ax.lower()}"
                if ot_col in plot_df.columns:
                    df_error = plot_df[plot_df[ot_col] == True]
                    if not df_error.empty:
                        fig.add_trace(go.Scatter(
                            x=df_error["time"],
                            y=df_error[col_name],
                            mode="markers",
                            name=f"{ax}-axis overtravel",
                            marker=dict(color="red", symbol="x", size=8),
                            hoverinfo="skip"
                        ))

                fig.update_layout(
                    title=f"{ax}-axis MCS Position",
                    xaxis_title="Time (s)",
                    yaxis_title="Position (mm)",
                    height=280,
                    margin=dict(l=10, r=10, t=35, b=10),
                    hovermode="x unified",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, width="stretch")

    st.divider()

    g2_c1, g2_c2 = st.columns(2)
    with g2_c1:
        st.markdown("#### Graph 2: Commanded Feedrate")
        fig_feed = px.area(
            df,
            x="time",
            y="feedrate",
            template="plotly_dark",
            height=280
        )
        fig_feed.update_layout(xaxis_title="Time (s)", yaxis_title="Feedrate (mm/min)")
        st.plotly_chart(fig_feed, width="stretch")

    with g2_c2:
        st.markdown("#### Graph 3: Spindle Speed")
        fig_rpm = px.line(
            df,
            x="time",
            y="rpm",
            template="plotly_dark",
            height=280
        )
        fig_rpm.update_layout(xaxis_title="Time (s)", yaxis_title="Spindle speed (rpm)")
        st.plotly_chart(fig_rpm, width="stretch")

    st.divider()

    bot_c1, bot_c2, bot_c3 = st.columns([3, 4, 3])

    with bot_c1:
        st.markdown("#### Tool Sequence & Process Routing")
        df["tool_str"] = "T" + df["tool_id"].astype(str)
        fig_tool = px.scatter(
            df,
            x="time",
            y="tool_str",
            color="tool_str",
            template="plotly_dark",
            height=400
        )
        fig_tool.update_traces(marker=dict(size=8, opacity=0.7))
        fig_tool.update_layout(
            yaxis_title="Tool Identifier / Turret Station",
            xaxis_title="Time (s)",
            showlegend=False
        )
        st.plotly_chart(fig_tool, width="stretch")

    with bot_c2:
        st.markdown("#### Interpolation Time-Series Log")

        log_cols = [
            "time",
            "axis_x",
            "axis_y",
            "axis_z",
            "feedrate",
            "rpm",
            "tool_id"
        ]

        for extra_col in [
            "event_type",
            "event_duration_s",
            "previous_tool_id",
            "next_tool_id",
            "tool_station_steps",
            "spindle_rpm_before",
            "spindle_rpm_target",
            "H_length",
            "H_status",
            "tool_length_warning"
        ]:
            if extra_col in df.columns:
                log_cols.append(extra_col)

        log_display = df[log_cols].copy()
        log_display = log_display.rename(columns={
            "time": "Time (s)",
            "axis_x": "X-axis MCS Position (mm)",
            "axis_y": "Y-axis MCS Position (mm)",
            "axis_z": "Z-axis MCS Position (mm)",
            "feedrate": "Feedrate (mm/min)",
            "rpm": "Spindle Speed (rpm)",
            "tool_id": "Tool ID",
            "event_type": "M-code Event",
            "event_duration_s": "Event Time (s)",
            "previous_tool_id": "Previous Tool",
            "next_tool_id": "Target Tool",
            "tool_station_steps": "Turret Station Steps",
            "spindle_rpm_before": "Initial Spindle Speed (rpm)",
            "spindle_rpm_target": "Target Spindle Speed (rpm)",
            "H_length": "Tool Length Compensation (mm)",
            "H_status": "Tool Length Data Status",
            "tool_length_warning": "Tool Length Warning"
        })

        st.dataframe(
            make_arrow_safe_display_df(log_display),
            height=400,
            width="stretch",
            hide_index=True
        )

    with bot_c3:
        st.markdown("#### NC Program")
        error_lines = set(df_errors["line_number"].unique()) if not df_errors.empty else set()
        html_lines = []
        clicked_ln = st.session_state.get("clicked_line", -1)

        for _, row in df_source_nc.iterrows():
            ln = int(row["line_number"])
            code_text = html.escape(str(row["raw_line"]))

            bg_style = ""
            if ln == clicked_ln:
                bg_style = "background-color: #ffd700; color: black; font-weight: bold;"
            elif ln in error_lines:
                bg_style = "background-color: rgba(255, 0, 0, 0.4);"

            line_html = (
                f"<div id='line_{ln}' "
                f"style='padding:2px 8px; font-family:monospace; "
                f"{bg_style} border-bottom:1px solid #444;'>"
                f"{code_text}</div>"
            )
            html_lines.append(line_html)

        st.markdown(
            "<div style='height:400px; overflow-y:auto; border:1px solid #555; "
            "border-radius:5px; background-color:#0e1117;'>"
            f"{''.join(html_lines)}</div>",
            unsafe_allow_html=True
        )
