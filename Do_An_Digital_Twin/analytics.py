import re
import pandas as pd
import numpy as np


TIME_CATEGORY_TOTAL = "Total Machining Cycle Time"
TIME_CATEGORY_CUTTING = "Effective Cutting Interpolation Time"
TIME_CATEGORY_RAPID = "Non-cutting Rapid Positioning Time"
TIME_CATEGORY_SPINDLE = "Spindle Start or Speed Change Time"
TIME_CATEGORY_TOOL_CHANGE = "Automatic Tool Change Time"


def _has_code(raw_line: str, letter: str, number: int) -> bool:
    """
    Detect G/M codes without false matches.

    Examples:
    - M3 must not be detected inside M30.
    - M06 and M6 are treated as the same command.
    """
    raw = str(raw_line).upper()
    pattern = rf"(?<![A-Z0-9]){letter}0*{number}(?!\d)"
    return re.search(pattern, raw) is not None


def add_duration_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a non-negative duration column to a point-level time-series log.

    duration_s is the time increment from the previous log row to the
    current log row. For M-code events represented by start/end rows,
    the positive duration is assigned to the end row.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    work_df = df.copy()

    if "time" not in work_df.columns:
        work_df["duration_s"] = 0.0
        return work_df

    work_df["time"] = pd.to_numeric(work_df["time"], errors="coerce").fillna(0.0)

    if "line_number" not in work_df.columns:
        work_df["line_number"] = 0

    work_df = work_df.sort_values(["time", "line_number"]).reset_index(drop=True)
    work_df["duration_s"] = work_df["time"].diff().fillna(0.0).clip(lower=0.0)

    return work_df


def classify_time_group(row) -> str:
    """
    Classify one time-series row into a production time group.

    Internal group names are intentionally kept machine-readable.
    Display labels are generated only inside table-building functions.
    """
    raw = str(row.get("raw_line", "")).upper()
    motion_mode = row.get("motion_mode", "")
    is_air = bool(row.get("is_air_time", False))

    if _has_code(raw, "M", 30) or _has_code(raw, "M", 0) or _has_code(raw, "M", 1):
        return "stop_pause"

    if _has_code(raw, "M", 6):
        return "tool_change"

    if _has_code(raw, "M", 3) or _has_code(raw, "M", 4):
        return "spindle_start"

    try:
        mm = int(float(motion_mode))
    except Exception:
        mm = None

    if mm == 0 or is_air:
        return "rapid"

    if mm in [1, 2, 3]:
        return "cutting"

    return "other"


def build_time_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detailed Cycle Time Breakdown Table.

    This function does not change the core L/F motion timing. It only
    aggregates the point-level timeline into CNC production time categories.
    """
    columns = [
        "Category",
        "Symbol",
        "Time (s)",
        "Share (%)",
        "Technical Meaning"
    ]

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    work_df = df.copy()

    if "time" not in work_df.columns:
        return pd.DataFrame(columns=columns)

    if "line_number" not in work_df.columns:
        work_df["line_number"] = 0

    work_df["time"] = pd.to_numeric(work_df["time"], errors="coerce")
    work_df = work_df.dropna(subset=["time"])
    work_df = work_df.sort_values(["time", "line_number"]).reset_index(drop=True)

    work_df["time increment"] = work_df["time"].diff().fillna(0.0).clip(lower=0.0)

    if "event_type" not in work_df.columns:
        work_df["event_type"] = ""

    work_df["event_type"] = work_df["event_type"].fillna("").astype(str).str.strip()

    if "event_duration_s" not in work_df.columns:
        work_df["event_duration_s"] = 0.0

    work_df["event_duration_s"] = pd.to_numeric(
        work_df["event_duration_s"],
        errors="coerce"
    ).fillna(0.0)

    event_df = work_df[work_df["event_type"] != ""].copy()

    spindle_time = event_df.loc[
        event_df["event_type"].str.upper().isin(["M3", "M4"]),
        "event_duration_s"
    ].sum()

    tool_change_time = event_df.loc[
        event_df["event_type"].str.upper() == "M6",
        "event_duration_s"
    ].sum()

    other_event_time = event_df.loc[
        ~event_df["event_type"].str.upper().isin(["M3", "M4", "M6"]),
        "event_duration_s"
    ].sum()

    motion_df = work_df[work_df["event_type"] == ""].copy()

    if "motion_mode" not in motion_df.columns:
        motion_df["motion_mode"] = ""

    motion_mode = motion_df["motion_mode"].fillna("").astype(str).str.upper()

    if "raw_line" in motion_df.columns:
        raw_line = motion_df["raw_line"].fillna("").astype(str).str.upper()
    else:
        raw_line = pd.Series("", index=motion_df.index)

    is_rapid = (
        motion_mode.isin(["0", "G0", "G00"])
        | raw_line.str.contains(r"\bG00\b|\bG0\b", regex=True)
    )

    is_cutting = (
        motion_mode.isin(["1", "2", "3", "G1", "G01", "G2", "G02", "G3", "G03"])
        | raw_line.str.contains(r"\bG01\b|\bG1\b|\bG02\b|\bG2\b|\bG03\b|\bG3\b", regex=True)
    )

    cutting_time = motion_df.loc[is_cutting, "time increment"].sum()
    rapid_time = motion_df.loc[is_rapid, "time increment"].sum()

    total_motion_time = motion_df["time increment"].sum()
    known_motion_time = cutting_time + rapid_time
    other_motion_time = max(total_motion_time - known_motion_time, 0.0)

    total_time = cutting_time + rapid_time + other_motion_time + spindle_time + tool_change_time + other_event_time

    def ratio(value: float) -> float:
        if total_time <= 0:
            return 0.0
        return round(float(value) / float(total_time) * 100.0, 2)

    rows = [
        {
            "Category": TIME_CATEGORY_CUTTING,
            "Symbol": "T cutting",
            "Time (s)": round(float(cutting_time), 3),
            "Share (%)": ratio(cutting_time),
            "Technical Meaning": "G01/G02/G03 material removal interpolation"
        },
        {
            "Category": TIME_CATEGORY_RAPID,
            "Symbol": "T rapid",
            "Time (s)": round(float(rapid_time), 3),
            "Share (%)": ratio(rapid_time),
            "Technical Meaning": "G00 positioning motion without chip generation"
        },
        {
            "Category": TIME_CATEGORY_SPINDLE,
            "Symbol": "T spindle",
            "Time (s)": round(float(spindle_time), 3),
            "Share (%)": ratio(spindle_time),
            "Technical Meaning": "M03/M04 spindle acceleration or speed transition"
        },
        {
            "Category": TIME_CATEGORY_TOOL_CHANGE,
            "Symbol": "T tool change",
            "Time (s)": round(float(tool_change_time), 3),
            "Share (%)": ratio(tool_change_time),
            "Technical Meaning": "M06 automatic tool change and turret indexing"
        }
    ]

    if other_motion_time > 1e-6:
        rows.append({
            "Category": "Unclassified Motion Time",
            "Symbol": "T other motion",
            "Time (s)": round(float(other_motion_time), 3),
            "Share (%)": ratio(other_motion_time),
            "Technical Meaning": "Motion blocks not classified by the parser"
        })

    if other_event_time > 1e-6:
        rows.append({
            "Category": "Other Non-productive Event Time",
            "Symbol": "T other event",
            "Time (s)": round(float(other_event_time), 3),
            "Share (%)": ratio(other_event_time),
            "Technical Meaning": "M00/M01/M05 or dwell events if configured"
        })

    rows.append({
        "Category": TIME_CATEGORY_TOTAL,
        "Symbol": "T total",
        "Time (s)": round(float(total_time), 3),
        "Share (%)": 100.0 if total_time > 0 else 0.0,
        "Technical Meaning": "Total motion time and non-productive event time"
    })

    return pd.DataFrame(rows, columns=columns)


def build_event_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Non-productive M-code Event Diagnostics.
    """
    columns = [
        "Line",
        "NC Block",
        "M-code",
        "Initial State",
        "Target State",
        "Model Basis",
        "Event Time (s)",
        "Data Confidence",
        "Required Calibration"
    ]

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    work_df = df.copy()

    if "event_type" not in work_df.columns:
        return pd.DataFrame(columns=columns)

    event_df = work_df[
        work_df["event_type"].astype(str).str.strip() != ""
    ].copy()

    if event_df.empty:
        return pd.DataFrame(columns=columns)

    event_df["event_duration_s"] = pd.to_numeric(
        event_df.get("event_duration_s", 0.0),
        errors="coerce"
    ).fillna(0.0)

    def clean_value(value):
        if pd.isna(value) or str(value).strip() == "":
            return ""
        try:
            numeric_value = float(value)
            if numeric_value.is_integer():
                return str(int(numeric_value))
            return f"{numeric_value:.3f}".rstrip("0").rstrip(".")
        except Exception:
            return str(value)

    def get_nc_block(raw_line):
        raw = str(raw_line).strip()
        parts = raw.split()
        if parts and parts[0].upper().startswith("N"):
            return parts[0].upper()
        return "-"

    rows = []
    grouped = event_df.groupby(["line_number", "event_type"], dropna=False)

    for (line_no, event_type), group in grouped:
        group = group.sort_values("time")
        positive_duration = group[group["event_duration_s"] > 0]

        if not positive_duration.empty:
            row = positive_duration.iloc[-1]
            duration = float(row.get("event_duration_s", 0.0))
        else:
            row = group.iloc[-1]
            duration = 0.0

        raw_line = str(row.get("raw_line", "")).strip()
        nc_block = get_nc_block(raw_line)
        event_type = str(event_type).strip().upper()

        previous_tool = clean_value(row.get("previous_tool_id", ""))
        next_tool = clean_value(row.get("next_tool_id", ""))
        station_steps = clean_value(row.get("tool_station_steps", ""))
        rpm_before = clean_value(row.get("spindle_rpm_before", ""))
        rpm_target = clean_value(row.get("spindle_rpm_target", ""))

        initial_state = "-"
        target_state = "-"
        model_basis = "-"
        confidence = "Requires validation"
        required_calibration = "Measure event time on the real machine"

        if event_type == "M6":
            initial_state = f"T{previous_tool}" if previous_tool else "Unknown previous tool"
            target_state = f"T{next_tool}" if next_tool else "Unknown target tool"

            if station_steps:
                model_basis = f"Turret indexing by shortest path, {station_steps} station steps"
            else:
                model_basis = "Initial tool change with unknown previous station"

            confidence = "Machine parameter model"
            required_calibration = "Measure ATC time for multiple turret station transitions"

        elif event_type in ["M3", "M4"]:
            initial_state = f"{rpm_before} rpm" if rpm_before else "0 rpm or unknown"
            target_state = f"{rpm_target} rpm" if rpm_target else "Unknown spindle speed"
            model_basis = "Spindle start or speed transition model"
            confidence = "Temporary default time"
            required_calibration = "Measure spindle ramp time for each commanded speed range"

        elif event_type == "M5":
            initial_state = f"{rpm_before} rpm" if rpm_before else "Spindle running"
            target_state = "0 rpm"
            model_basis = "Spindle stop event"
            confidence = "Not included in automatic cycle time"
            required_calibration = "Add M05 deceleration time only if required by the costing model"

        elif event_type in ["M00", "M01"]:
            initial_state = "Automatic cycle"
            target_state = "Program stop"
            model_basis = "Operator-dependent stop"
            confidence = "Operator-dependent"
            required_calibration = "Exclude from automatic cycle time unless the process requires it"

        rows.append({
            "Line": int(line_no) if pd.notna(line_no) else "-",
            "NC Block": nc_block,
            "M-code": event_type,
            "Initial State": initial_state,
            "Target State": target_state,
            "Model Basis": model_basis,
            "Event Time (s)": round(float(duration), 3),
            "Data Confidence": confidence,
            "Required Calibration": required_calibration
        })

    result = pd.DataFrame(rows, columns=columns)

    event_order = {
        "M6": 1,
        "M3": 2,
        "M4": 3,
        "M5": 4,
        "M00": 5,
        "M01": 6
    }

    result["_order"] = result["M-code"].map(event_order).fillna(99)
    result = result.sort_values(["Line", "_order"]).drop(columns=["_order"])

    return result.reset_index(drop=True)


def _get_breakdown_value(df_time_breakdown: pd.DataFrame, category_name: str) -> float:
    """
    Read a numeric time value from the Detailed Cycle Time Breakdown Table.
    """
    if df_time_breakdown is None or df_time_breakdown.empty:
        return 0.0

    if "Category" not in df_time_breakdown.columns:
        return 0.0

    row = df_time_breakdown[
        df_time_breakdown["Category"].astype(str).str.strip() == category_name
    ]

    if row.empty:
        return 0.0

    return float(row.iloc[0]["Time (s)"])


def build_production_summary(
    df: pd.DataFrame,
    file_name: str,
    machine_id: str,
    machine_cfg: dict
) -> pd.DataFrame:
    """
    Production Overview KPI table.
    """
    columns = ["Metric", "Value"]

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    time_breakdown = build_time_breakdown(df)

    total_time = _get_breakdown_value(time_breakdown, TIME_CATEGORY_TOTAL)
    cutting_time = _get_breakdown_value(time_breakdown, TIME_CATEGORY_CUTTING)
    rapid_time = _get_breakdown_value(time_breakdown, TIME_CATEGORY_RAPID)
    spindle_time = _get_breakdown_value(time_breakdown, TIME_CATEGORY_SPINDLE)
    tool_change_time = _get_breakdown_value(time_breakdown, TIME_CATEGORY_TOOL_CHANGE)

    total_points = len(df)
    total_nc_blocks = int(df["line_number"].nunique()) if "line_number" in df.columns else 0

    ot_mask = (
        df.get("ot_x", False).astype(bool)
        | df.get("ot_y", False).astype(bool)
        | df.get("ot_z", False).astype(bool)
    )

    overtravel_blocks = (
        int(df.loc[ot_mask, "line_number"].nunique())
        if "line_number" in df.columns
        else 0
    )

    if total_time > 0:
        cutting_efficiency = cutting_time / total_time * 100.0
        non_productive_ratio = (rapid_time + spindle_time + tool_change_time) / total_time * 100.0
        parts_per_hour = 3600.0 / total_time
    else:
        cutting_efficiency = 0.0
        non_productive_ratio = 0.0
        parts_per_hour = 0.0

    safety_status = "No overtravel fault" if overtravel_blocks == 0 else "Physical overtravel fault detected"

    return pd.DataFrame([
        {"Metric": "NC Program", "Value": file_name},
        {"Metric": "CNC Machine", "Value": machine_cfg.get("machine_name", machine_id)},
        {"Metric": "Controller", "Value": machine_cfg.get("control", "N/A")},
        {"Metric": "Total Machining Cycle Time", "Value": f"{total_time:.3f} s"},
        {"Metric": "Estimated Throughput", "Value": f"{parts_per_hour:.2f} parts/hour"},
        {"Metric": "Cutting Efficiency Index", "Value": f"{cutting_efficiency:.2f} %"},
        {"Metric": "Non-productive Time Ratio", "Value": f"{non_productive_ratio:.2f} %"},
        {"Metric": "Interpolated Trajectory Points", "Value": f"{total_points} points"},
        {"Metric": "NC Blocks with Motion Data", "Value": total_nc_blocks},
        {"Metric": "NC Blocks with Overtravel Faults", "Value": overtravel_blocks},
        {"Metric": "MCS Overtravel Status", "Value": safety_status},
        {"Metric": "MCS Limit Source", "Value": machine_cfg.get("machine_g53", {}).get("limit_status", "unknown")}
    ], columns=columns)


def build_overtravel_table(df: pd.DataFrame, limits: dict) -> pd.DataFrame:
    """
    Physical Overtravel Safety Log in MCS.
    """
    columns = [
        "Line",
        "NC Block",
        "Axis",
        "Checked MCS Position (mm)",
        "Minimum Travel Limit (mm)",
        "Maximum Travel Limit (mm)",
        "Overtravel Amount (mm)",
        "Safety Status",
        "Corrective Action"
    ]

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    axis_map = {
        "X": ("axis_x", "ot_x", "ot_amount_x"),
        "Y": ("axis_y", "ot_y", "ot_amount_y"),
        "Z": ("axis_z", "ot_z", "ot_amount_z"),
    }

    for axis, (pos_col, ot_col, amount_col) in axis_map.items():
        if ot_col not in df.columns:
            continue

        err_df = df[df[ot_col].astype(bool)].copy()
        l_min, l_max = limits[axis.lower()]

        if err_df.empty:
            rows.append({
                "Line": "-",
                "NC Block": "-",
                "Axis": axis,
                "Checked MCS Position (mm)": "-",
                "Minimum Travel Limit (mm)": l_min,
                "Maximum Travel Limit (mm)": l_max,
                "Overtravel Amount (mm)": 0.0,
                "Safety Status": "OK",
                "Corrective Action": "No physical overtravel point detected"
            })
            continue

        for line_no, group in err_df.groupby("line_number"):
            idx = group[amount_col].abs().idxmax()
            row = group.loc[idx]

            rows.append({
                "Line": int(line_no),
                "NC Block": row.get("raw_line", ""),
                "Axis": axis,
                "Checked MCS Position (mm)": round(float(row.get(pos_col, 0.0)), 4),
                "Minimum Travel Limit (mm)": l_min,
                "Maximum Travel Limit (mm)": l_max,
                "Overtravel Amount (mm)": round(float(row.get(amount_col, 0.0)), 4),
                "Safety Status": "FAULT",
                "Corrective Action": "Check work offset, tool length compensation or NC toolpath"
            })

    return pd.DataFrame(rows, columns=columns)


def _build_block_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate point-level logs into NC block-level statistics.
    """
    columns = [
        "Line",
        "NC Block",
        "Time Group",
        "Time (s)",
        "Approximate Path Length (mm)",
        "Feedrate (mm/min)",
        "Spindle Speed (rpm)"
    ]

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    work_df = add_duration_column(df)

    if work_df.empty:
        return pd.DataFrame(columns=columns)

    if "line_number" not in work_df.columns:
        return pd.DataFrame(columns=columns)

    work_df["time_group"] = work_df.apply(classify_time_group, axis=1)

    rows = []

    for line_no, group in work_df.groupby("line_number"):
        group = group.sort_values("time")

        duration = float(group["duration_s"].sum())
        raw_line = str(group["raw_line"].iloc[-1]) if "raw_line" in group.columns else ""
        time_group = str(group["time_group"].iloc[-1])

        length = 0.0

        if all(col in group.columns for col in ["axis_x", "axis_y", "axis_z"]):
            coords = group[["axis_x", "axis_y", "axis_z"]].apply(
                pd.to_numeric,
                errors="coerce"
            ).dropna()

            if len(coords) >= 2:
                diff = coords.diff().dropna()
                dist = np.sqrt(
                    diff["axis_x"] ** 2
                    + diff["axis_y"] ** 2
                    + diff["axis_z"] ** 2
                )
                length = float(dist.sum())

        rows.append({
            "Line": int(line_no),
            "NC Block": raw_line,
            "Time Group": time_group,
            "Time (s)": round(duration, 4),
            "Approximate Path Length (mm)": round(length, 4),
            "Feedrate (mm/min)": float(group["feedrate"].max()) if "feedrate" in group.columns else 0.0,
            "Spindle Speed (rpm)": float(group["rpm"].max()) if "rpm" in group.columns else 0.0
        })

    return pd.DataFrame(rows, columns=columns)


def build_top_time_blocks(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """
    Critical NC Blocks ranked by block time.
    """
    columns = [
        "Line",
        "NC Block",
        "Time Group",
        "Time (s)",
        "Approximate Path Length (mm)",
        "Feedrate (mm/min)",
        "Spindle Speed (rpm)",
        "Recommended Action"
    ]

    stats = _build_block_stats(df)

    if stats.empty:
        return pd.DataFrame(columns=columns)

    stats = stats[stats["Time (s)"] > 0].copy()
    stats = stats.sort_values("Time (s)", ascending=False).head(top_n)

    def suggestion(row):
        group = row["Time Group"]
        if group == "cutting":
            return "Review feedrate, axial depth of cut, step-over or CAM strategy"
        if group == "rapid":
            return "Review retract height, linking move and non-cutting rapid path"
        if group == "tool_change":
            return "Non-productive event; optimize only for repeated batch production"
        if group == "spindle_start":
            return "Validate spindle start or speed transition time by rpm range"
        return "Review the corresponding NC block"

    stats["Recommended Action"] = stats.apply(suggestion, axis=1)

    return stats[columns].reset_index(drop=True)


def build_microblock_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    CAM Trajectory Quality Metric based on micro-block density.
    """
    columns = ["Metric", "Value"]

    stats = _build_block_stats(df)

    if stats.empty:
        return pd.DataFrame(columns=columns)

    motion_stats = stats[
        (stats["Approximate Path Length (mm)"] > 0)
        & (stats["Time Group"].isin(["cutting", "rapid"]))
    ].copy()

    if motion_stats.empty:
        return pd.DataFrame([{
            "Metric": "Valid Motion Blocks",
            "Value": "No valid motion block"
        }], columns=columns)

    total_motion_blocks = len(motion_stats)
    short_05 = int((motion_stats["Approximate Path Length (mm)"] < 0.5).sum())
    short_01 = int((motion_stats["Approximate Path Length (mm)"] < 0.1).sum())

    avg_len = float(motion_stats["Approximate Path Length (mm)"].mean())
    min_len = float(motion_stats["Approximate Path Length (mm)"].min())

    micro_ratio = short_05 / total_motion_blocks * 100.0 if total_motion_blocks > 0 else 0.0

    if micro_ratio > 30:
        assessment = "High micro-block density; review CAM tolerance, smoothing and postprocessor settings"
    elif micro_ratio > 10:
        assessment = "Moderate micro-block density; monitor during high-feed contouring"
    else:
        assessment = "Toolpath is acceptable under the current short-block criterion"

    return pd.DataFrame([
        {"Metric": "Total Motion Blocks", "Value": total_motion_blocks},
        {"Metric": "Blocks Shorter than 0.5 mm", "Value": short_05},
        {"Metric": "Blocks Shorter than 0.1 mm", "Value": short_01},
        {"Metric": "Average Block Length", "Value": f"{avg_len:.4f} mm"},
        {"Metric": "Minimum Block Length", "Value": f"{min_len:.4f} mm"},
        {"Metric": "Micro-block Ratio below 0.5 mm", "Value": f"{micro_ratio:.2f} %"},
        {"Metric": "CAM Trajectory Assessment", "Value": assessment}
    ], columns=columns)


def build_cost_summary(total_time_s: float, cost_cfg: dict) -> pd.DataFrame:
    """
    Industrial Machining Cost Estimator.
    """
    columns = ["Cost Item", "Value", "Technical Meaning"]

    total_time_s = float(total_time_s)

    machine_hour_rate = float(cost_cfg.get("machine_hour_rate", 0.0))
    labor_hour_rate = float(cost_cfg.get("labor_hour_rate", 0.0))
    tooling_hour_rate = float(cost_cfg.get("tooling_hour_rate", 0.0))
    energy_hour_rate = float(cost_cfg.get("energy_hour_rate", 0.0))
    overhead_hour_rate = float(cost_cfg.get("overhead_hour_rate", 0.0))
    batch_quantity = int(cost_cfg.get("batch_quantity", 1))

    total_hour_rate = (
        machine_hour_rate
        + labor_hour_rate
        + tooling_hour_rate
        + energy_hour_rate
        + overhead_hour_rate
    )

    cycle_time_hour = total_time_s / 3600.0 if total_time_s > 0 else 0.0
    parts_per_hour = 3600.0 / total_time_s if total_time_s > 0 else 0.0

    cost_per_part = cycle_time_hour * total_hour_rate
    cost_per_batch = cost_per_part * batch_quantity

    return pd.DataFrame([
        {
            "Cost Item": "Cycle Time per Part",
            "Value": f"{total_time_s:.3f} s",
            "Technical Meaning": "Predicted machining cycle time for one part"
        },
        {
            "Cost Item": "Cycle Time in Hours",
            "Value": f"{cycle_time_hour:.6f} h",
            "Technical Meaning": "Cycle time converted to hours for cost accounting"
        },
        {
            "Cost Item": "Estimated Throughput",
            "Value": f"{parts_per_hour:.2f} parts/hour",
            "Technical Meaning": "Estimated output rate under continuous production"
        },
        {
            "Cost Item": "Machine Hourly Rate",
            "Value": f"{machine_hour_rate:,.0f} VND/h",
            "Technical Meaning": "CNC machine operating cost rate"
        },
        {
            "Cost Item": "Labor Hourly Rate",
            "Value": f"{labor_hour_rate:,.0f} VND/h",
            "Technical Meaning": "Machine operator labor cost rate"
        },
        {
            "Cost Item": "Tooling Hourly Rate",
            "Value": f"{tooling_hour_rate:,.0f} VND/h",
            "Technical Meaning": "Estimated cutting tool consumption rate"
        },
        {
            "Cost Item": "Energy Hourly Rate",
            "Value": f"{energy_hour_rate:,.0f} VND/h",
            "Technical Meaning": "Estimated energy consumption cost rate"
        },
        {
            "Cost Item": "Factory Overhead Rate",
            "Value": f"{overhead_hour_rate:,.0f} VND/h",
            "Technical Meaning": "Allocated factory overhead cost rate"
        },
        {
            "Cost Item": "Total Hourly Manufacturing Rate",
            "Value": f"{total_hour_rate:,.0f} VND/h",
            "Technical Meaning": "Total machining cost rate used for cost estimation"
        },
        {
            "Cost Item": "Machining Cost per Part",
            "Value": f"{cost_per_part:,.0f} VND",
            "Technical Meaning": "Estimated machining cost for one part"
        },
        {
            "Cost Item": "Batch Quantity",
            "Value": f"{batch_quantity} parts",
            "Technical Meaning": "Production batch quantity used for batch cost estimation"
        },
        {
            "Cost Item": "Machining Cost per Batch",
            "Value": f"{cost_per_batch:,.0f} VND",
            "Technical Meaning": "Estimated machining cost for the full production batch"
        }
    ], columns=columns)


def _parse_percent(value) -> float:
    """
    Convert a displayed percent value such as '12.35 %' to 12.35.
    """
    try:
        return float(str(value).replace("%", "").strip())
    except Exception:
        return 0.0


def build_saving_recommendations(
    df_time_breakdown: pd.DataFrame,
    df_top_blocks: pd.DataFrame,
    df_microblock: pd.DataFrame,
    cost_cfg: dict
) -> pd.DataFrame:
    """
    Toolpath / Trajectory Optimization Recommendations.

    The function reports practical opportunities for review. It does not
    modify NC code and does not apply any measured-time correction factor.
    """
    columns = [
        "Optimization Item",
        "Current State",
        "Estimated Time Saving",
        "Saving per Part",
        "Saving per Batch",
        "Priority",
        "Recommended Action"
    ]

    machine_hour_rate = float(cost_cfg.get("machine_hour_rate", 0.0))
    labor_hour_rate = float(cost_cfg.get("labor_hour_rate", 0.0))
    tooling_hour_rate = float(cost_cfg.get("tooling_hour_rate", 0.0))
    energy_hour_rate = float(cost_cfg.get("energy_hour_rate", 0.0))
    overhead_hour_rate = float(cost_cfg.get("overhead_hour_rate", 0.0))
    batch_quantity = int(cost_cfg.get("batch_quantity", 1))

    total_hour_rate = (
        machine_hour_rate
        + labor_hour_rate
        + tooling_hour_rate
        + energy_hour_rate
        + overhead_hour_rate
    )

    total_time = _get_breakdown_value(df_time_breakdown, TIME_CATEGORY_TOTAL)
    cutting_time = _get_breakdown_value(df_time_breakdown, TIME_CATEGORY_CUTTING)
    rapid_time = _get_breakdown_value(df_time_breakdown, TIME_CATEGORY_RAPID)
    spindle_time = _get_breakdown_value(df_time_breakdown, TIME_CATEGORY_SPINDLE)
    tool_change_time = _get_breakdown_value(df_time_breakdown, TIME_CATEGORY_TOOL_CHANGE)

    rows = []

    def add_row(item, current, saving_s, priority, suggestion):
        saving_s = max(float(saving_s), 0.0)
        saving_per_part = saving_s / 3600.0 * total_hour_rate
        saving_per_batch = saving_per_part * batch_quantity

        rows.append({
            "Optimization Item": item,
            "Current State": current,
            "Estimated Time Saving": f"{saving_s:.3f} s/part",
            "Saving per Part": f"{saving_per_part:,.0f} VND",
            "Saving per Batch": f"{saving_per_batch:,.0f} VND",
            "Priority": priority,
            "Recommended Action": suggestion
        })

    if total_time > 0 and rapid_time / total_time >= 0.10:
        estimated_save = rapid_time * 0.10
        add_row(
            item="Reduce Non-cutting Rapid Positioning Time",
            current=f"Rapid positioning time = {rapid_time:.3f} s",
            saving_s=estimated_save,
            priority="High",
            suggestion="Review retract height, linking moves and non-cutting toolpath travel"
        )
    elif rapid_time > 0:
        estimated_save = rapid_time * 0.05
        add_row(
            item="Review Non-cutting Rapid Positioning",
            current=f"Rapid positioning time = {rapid_time:.3f} s",
            saving_s=estimated_save,
            priority="Medium",
            suggestion="Minor optimization may be possible in retract and linking movements"
        )

    if total_time > 0 and cutting_time / total_time >= 0.60:
        estimated_save = cutting_time * 0.03
        add_row(
            item="Optimize Effective Cutting Interpolation Time",
            current=f"Cutting interpolation time = {cutting_time:.3f} s",
            saving_s=estimated_save,
            priority="High",
            suggestion="Review feedrate, axial depth of cut, radial step-over, cutter condition and CAM strategy"
        )

    if spindle_time > 0:
        estimated_save = spindle_time * 0.10
        add_row(
            item="Validate Spindle Start or Speed Change Model",
            current=f"Spindle event time = {spindle_time:.3f} s",
            saving_s=estimated_save,
            priority="Medium",
            suggestion="Measure M03/M04 event time by rpm range to improve cycle time prediction accuracy"
        )

    if tool_change_time > 0:
        estimated_save = tool_change_time * 0.05
        add_row(
            item="Review Automatic Tool Change Time",
            current=f"ATC time = {tool_change_time:.3f} s",
            saving_s=estimated_save,
            priority="Low/Medium",
            suggestion="Optimize only when the program has many tool changes or the batch quantity is high"
        )

    micro_ratio = 0.0
    if df_microblock is not None and not df_microblock.empty:
        if "Metric" in df_microblock.columns and "Value" in df_microblock.columns:
            micro_row = df_microblock[
                df_microblock["Metric"].astype(str).str.strip() == "Micro-block Ratio below 0.5 mm"
            ]
            if not micro_row.empty:
                micro_ratio = _parse_percent(micro_row.iloc[0]["Value"])

    if total_time > 0 and micro_ratio >= 10:
        estimated_save = total_time * 0.02
        add_row(
            item="Reduce Micro-block Density",
            current=f"Micro-block ratio below 0.5 mm = {micro_ratio:.2f} %",
            saving_s=estimated_save,
            priority="High" if micro_ratio >= 30 else "Medium",
            suggestion="Review CAM tolerance, smoothing, postprocessor and contouring strategy"
        )

    if df_top_blocks is not None and not df_top_blocks.empty:
        top = df_top_blocks.iloc[0]
        top_time = float(top.get("Time (s)", 0.0))
        add_row(
            item="Inspect the Most Time-consuming NC Block",
            current=f"Line {top.get('Line')}: {top_time:.4f} s",
            saving_s=0.0,
            priority="Monitoring",
            suggestion="Use the Critical Blocks table to identify the NC block that should be reviewed first"
        )

    if not rows:
        rows.append({
            "Optimization Item": "No Major Optimization Opportunity Detected",
            "Current State": "Current production analytics does not indicate a dominant time loss",
            "Estimated Time Saving": "0.000 s/part",
            "Saving per Part": "0 VND",
            "Saving per Batch": "0 VND",
            "Priority": "Low",
            "Recommended Action": "Continue monitoring cycle time breakdown, CAM quality and MCS overtravel safety log"
        })

    return pd.DataFrame(rows, columns=columns)

# ── Tool life monitoring ─────────────────────────────────────────────────────

def _normalize_tool_id(value) -> str:
    """Return a compact tool id string suitable for UI keys and grouping."""
    if value is None:
        return ""

    text = str(value).strip()

    if text == "" or text.lower() in {"none", "nan", "nat"}:
        return ""

    if text.upper().startswith("T"):
        text = text[1:].strip()

    try:
        numeric = float(text)
        if numeric.is_integer():
            return str(int(numeric))
    except Exception:
        pass

    return text


def _is_truthy_bool(value) -> bool:
    """Robust conversion for bool-like values that may come from Pandas/CSV/UI."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def _is_cutting_motion_row(row) -> bool:
    """
    Identify rows that should accumulate tool life.

    Current scope:
    - G01/G02/G03 interpolation rows only
    - not rapid / air-time
    - not M-code event rows
    """
    if str(row.get("event_type", "")).strip() != "":
        return False

    if _is_truthy_bool(row.get("is_air_time", False)):
        return False

    motion_mode = str(row.get("motion_mode", "")).strip().upper()
    raw_line = str(row.get("raw_line", "")).upper()

    try:
        mm = int(float(motion_mode))
    except Exception:
        mm = None

    if mm in [1, 2, 3]:
        return True

    return bool(re.search(r"\bG0?1\b|\bG0?2\b|\bG0?3\b", raw_line))




def _extract_t_code_from_raw_line(raw_line) -> str:
    """
    Extract T-code from one NC block.

    Used only as a fallback when the simulation log does not carry a valid
    active tool_id on cutting rows. Preference is still given to the simulated
    active tool state and M6 next_tool_id.
    """
    raw = str(raw_line or "").upper()
    match = re.search(r"(?<![A-Z0-9])T\s*0*(\d+)(?!\d)", raw)
    if not match:
        return ""
    return _normalize_tool_id(match.group(1))

def _tool_life_cutting_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return point-level rows that contribute to tool-life usage."""
    if df is None or df.empty:
        return pd.DataFrame()

    required = {"time", "tool_id"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    work_df = add_duration_column(df)

    if work_df.empty:
        return pd.DataFrame()

    if "event_type" not in work_df.columns:
        work_df["event_type"] = ""

    if "is_air_time" not in work_df.columns:
        work_df["is_air_time"] = False

    if "motion_mode" not in work_df.columns:
        work_df["motion_mode"] = ""

    # Prefer the active tool_id produced by the transformer.
    explicit_tool_id = work_df["tool_id"].map(_normalize_tool_id)

    # Fallback: derive active tool from M6 / T-code sequence when old logs
    # have tool_id = None on motion rows. This keeps the UI usable without
    # changing transformation.py.
    if "next_tool_id" in work_df.columns:
        next_tool_from_m6 = work_df["next_tool_id"].map(_normalize_tool_id)
    else:
        next_tool_from_m6 = pd.Series("", index=work_df.index)

    if "event_type" in work_df.columns:
        is_m6_event = work_df["event_type"].astype(str).str.upper().str.strip().isin(["M6", "M06"])
    else:
        is_m6_event = pd.Series(False, index=work_df.index)

    if "raw_line" in work_df.columns:
        t_from_raw = work_df["raw_line"].map(_extract_t_code_from_raw_line)
        raw_has_m6 = work_df["raw_line"].astype(str).str.upper().str.contains(
            r"(?<![A-Z0-9])M0*6(?!\d)",
            regex=True
        )
    else:
        t_from_raw = pd.Series("", index=work_df.index)
        raw_has_m6 = pd.Series(False, index=work_df.index)

    tool_marker = pd.Series("", index=work_df.index, dtype="object")

    # M6 is the safest fallback marker because the tool becomes active after M6.
    tool_marker.loc[is_m6_event & (next_tool_from_m6 != "")] = next_tool_from_m6.loc[
        is_m6_event & (next_tool_from_m6 != "")
    ]
    tool_marker.loc[(tool_marker == "") & raw_has_m6 & (t_from_raw != "")] = t_from_raw.loc[
        (tool_marker == "") & raw_has_m6 & (t_from_raw != "")
    ]

    # Single-tool NC programs sometimes contain only T-code without M6.
    # Use this only when no M6 marker exists in the program.
    if not (tool_marker != "").any():
        tool_marker.loc[t_from_raw != ""] = t_from_raw.loc[t_from_raw != ""]

    work_df["tool_id_normalized"] = explicit_tool_id
    missing_tool = work_df["tool_id_normalized"] == ""
    work_df.loc[missing_tool, "tool_id_normalized"] = tool_marker.loc[missing_tool]

    # Carry the active tool forward to later motion rows.
    work_df["tool_id_normalized"] = (
        work_df["tool_id_normalized"]
        .replace("", pd.NA)
        .ffill()
        .fillna("")
    )

    work_df = work_df[work_df["tool_id_normalized"] != ""].copy()

    if work_df.empty:
        return pd.DataFrame()

    cutting_mask = work_df.apply(_is_cutting_motion_row, axis=1)
    cutting_df = work_df[cutting_mask].copy()

    if cutting_df.empty:
        return pd.DataFrame()

    cutting_df["duration_s"] = pd.to_numeric(
        cutting_df.get("duration_s", 0.0),
        errors="coerce"
    ).fillna(0.0).clip(lower=0.0)

    cutting_df = cutting_df[cutting_df["duration_s"] > 0].copy()

    if cutting_df.empty:
        return pd.DataFrame()

    return cutting_df.sort_values(["time", "line_number"]).reset_index(drop=True)


def extract_cutting_tool_ids(df: pd.DataFrame) -> list:
    """List tools that actually cut in the current NC program."""
    cutting_df = _tool_life_cutting_rows(df)

    if cutting_df.empty:
        return []

    tool_ids = sorted(
        cutting_df["tool_id_normalized"].dropna().astype(str).unique().tolist(),
        key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)
    )

    return tool_ids


def build_tool_life_summary(
    df: pd.DataFrame,
    remaining_life_hours_by_tool: dict,
    warning_ratio: float = 0.20,
    critical_ratio: float = 0.10,
) -> pd.DataFrame:
    """
    Summarize whether each tool has enough remaining life for this NC program.

    The model consumes a manually entered remaining-life balance. It does not
    estimate physical wear from tool material, workpiece material, coolant,
    engagement or cutting-condition physics.
    """
    columns = [
        "Tool",
        "Remaining Before (h)",
        "Cutting Time in Program (h)",
        "Remaining After (h)",
        "Life Used (%)",
        "Remaining (%)",
        "Status",
        "Message",
    ]

    if not remaining_life_hours_by_tool:
        return pd.DataFrame(columns=columns)

    cutting_df = _tool_life_cutting_rows(df)

    if cutting_df.empty:
        rows = []
        for tool_id, remaining_h in remaining_life_hours_by_tool.items():
            tool = _normalize_tool_id(tool_id)
            before_h = max(float(remaining_h or 0.0), 0.0)
            rows.append({
                "Tool": f"T{tool}" if tool else "Unknown",
                "Remaining Before (h)": round(before_h, 4),
                "Cutting Time in Program (h)": 0.0,
                "Remaining After (h)": round(before_h, 4),
                "Life Used (%)": 0.0,
                "Remaining (%)": 100.0 if before_h > 0 else 0.0,
                "Status": "SAFE" if before_h > 0 else "NOT SET",
                "Message": "No cutting time detected for this tool",
            })
        return pd.DataFrame(rows, columns=columns)

    used_s_by_tool = cutting_df.groupby("tool_id_normalized")["duration_s"].sum().to_dict()

    rows = []
    for tool_id, remaining_h in remaining_life_hours_by_tool.items():
        tool = _normalize_tool_id(tool_id)
        before_h = max(float(remaining_h or 0.0), 0.0)
        before_s = before_h * 3600.0
        used_s = float(used_s_by_tool.get(tool, 0.0))
        used_h = used_s / 3600.0
        after_s = before_s - used_s
        after_h = after_s / 3600.0

        if before_s <= 0:
            used_pct = 0.0
            remaining_pct = 0.0
            status = "NOT SET"
            message = "Enter remaining tool life before running the check"
        else:
            used_pct = used_s / before_s * 100.0
            remaining_pct = after_s / before_s * 100.0

            if after_s <= 0:
                status = "FAIL"
                message = "Tool life is not enough to complete this program"
            elif after_s <= critical_ratio * before_s:
                status = "CRITICAL"
                message = f"Remaining life is below {critical_ratio:.0%} of entered life"
            elif after_s <= warning_ratio * before_s:
                status = "WARNING"
                message = f"Remaining life is below {warning_ratio:.0%} of entered life"
            else:
                status = "SAFE"
                message = "Tool can complete this program based on entered remaining life"

        rows.append({
            "Tool": f"T{tool}" if tool else "Unknown",
            "Remaining Before (h)": round(before_h, 4),
            "Cutting Time in Program (h)": round(used_h, 4),
            "Remaining After (h)": round(after_h, 4),
            "Life Used (%)": round(used_pct, 2),
            "Remaining (%)": round(remaining_pct, 2),
            "Status": status,
            "Message": message,
        })

    status_order = {"FAIL": 0, "CRITICAL": 1, "WARNING": 2, "NOT SET": 3, "SAFE": 4}
    result = pd.DataFrame(rows, columns=columns)
    result["_order"] = result["Status"].map(status_order).fillna(9)
    result = result.sort_values(["_order", "Tool"]).drop(columns=["_order"])
    return result.reset_index(drop=True)


def build_tool_life_warning_blocks(
    df: pd.DataFrame,
    remaining_life_hours_by_tool: dict,
    warning_ratio: float = 0.20,
    critical_ratio: float = 0.10,
) -> pd.DataFrame:
    """Find the first NC block where each tool crosses 20%, 10%, and 0% life."""
    columns = [
        "Tool",
        "Level",
        "Line",
        "NC Block",
        "Time (s)",
        "Cumulative Cutting Time (h)",
        "Remaining Life (h)",
        "Threshold",
    ]

    if not remaining_life_hours_by_tool:
        return pd.DataFrame(columns=columns)

    cutting_df = _tool_life_cutting_rows(df)

    if cutting_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    for tool_id, remaining_h in remaining_life_hours_by_tool.items():
        tool = _normalize_tool_id(tool_id)
        before_h = max(float(remaining_h or 0.0), 0.0)
        before_s = before_h * 3600.0

        if tool == "" or before_s <= 0:
            continue

        tool_df = cutting_df[cutting_df["tool_id_normalized"] == tool].copy()

        if tool_df.empty:
            continue

        tool_df = tool_df.sort_values(["time", "line_number"]).reset_index(drop=True)
        tool_df["cumulative_cutting_s"] = tool_df["duration_s"].cumsum()
        tool_df["remaining_s"] = before_s - tool_df["cumulative_cutting_s"]

        threshold_specs = [
            ("WARNING", warning_ratio * before_s, f"≤ {warning_ratio:.0%} remaining"),
            ("CRITICAL", critical_ratio * before_s, f"≤ {critical_ratio:.0%} remaining"),
            ("FAIL", 0.0, "≤ 0 remaining"),
        ]

        for level, threshold_s, threshold_label in threshold_specs:
            crossed = tool_df[tool_df["remaining_s"] <= threshold_s]

            if crossed.empty:
                continue

            row = crossed.iloc[0]
            raw_line = str(row.get("raw_line", ""))
            line_no = row.get("line_number", "")

            try:
                line_no = int(line_no)
            except Exception:
                pass

            rows.append({
                "Tool": f"T{tool}",
                "Level": level,
                "Line": line_no,
                "NC Block": raw_line,
                "Time (s)": round(float(row.get("time", 0.0)), 4),
                "Cumulative Cutting Time (h)": round(float(row["cumulative_cutting_s"]) / 3600.0, 4),
                "Remaining Life (h)": round(float(row["remaining_s"]) / 3600.0, 4),
                "Threshold": threshold_label,
            })

    result = pd.DataFrame(rows, columns=columns)

    if result.empty:
        return result

    level_order = {"FAIL": 0, "CRITICAL": 1, "WARNING": 2}
    result["_order"] = result["Level"].map(level_order).fillna(9)
    result = result.sort_values(["Tool", "_order", "Time (s)"]).drop(columns=["_order"])
    return result.reset_index(drop=True)

