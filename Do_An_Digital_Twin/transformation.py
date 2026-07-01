from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import math
import numpy as np


@dataclass
class MotionBlock:
    line_number: int
    raw_block: str
    motion_type: str
    start_position_mcs: np.ndarray
    end_position_mcs: np.ndarray
    path_length_mm: float
    unit_direction_vector: np.ndarray
    geometry_source: str
    commanded_feed_mm_min: float
    is_rapid_positioning: bool
    is_cutting_interpolation: bool
    pre_motion_events: List[Dict[str, Any]] = field(default_factory=list)
    post_motion_events: List[Dict[str, Any]] = field(default_factory=list)
class DigitalTwinTransformer:
    def __init__(self, config):
        """
        Khởi tạo Digital Twin Transformer.

        Mục tiêu:
        - Ưu tiên đọc dữ liệu theo máy đang chọn trong config["machines"].
        - Không dùng legacy machine_g53/work_offset_g54 nếu đã có dữ liệu machine-specific.
        - Giữ tên biến cũ như T_world_from_G54 để không phá các hàm phía dưới.
        """

        self.config = config

        # ---------------------------------------------------------
        # 1. Chọn máy đang active
        # ---------------------------------------------------------
        self.machine_id = config.get("active_machine_id", "EMCO_155")

        if "machines" not in config:
            raise KeyError("config.json thiếu khóa 'machines'.")

        if self.machine_id not in config["machines"]:
            raise KeyError(
                f"Không tìm thấy machine_id '{self.machine_id}' trong config['machines']."
            )

        self.machine_cfg = config["machines"][self.machine_id]

        # ---------------------------------------------------------
        # 2. Đọc giới hạn G53 và G54 theo máy đang chọn
        # ---------------------------------------------------------
        self.limits = self.machine_cfg["machine_g53"]["limits"]
        self.work_offset = self.machine_cfg["work_offset_g54"]["offset_vector"]

        # Tool library hiện tại vẫn dùng legacy.
        # Sau này có thể thay bằng tool_setup.csv.
        self.tools = config.get("tool_library", {})

        # ---------------------------------------------------------
        # 3. Gom thông số máy về dạng phẳng để các hàm cũ vẫn chạy
        #    Ưu tiên schema mới feed_system, vẫn hỗ trợ schema cũ feed.
        # ---------------------------------------------------------
        feed_cfg = (
            self.machine_cfg.get("feed_system")
            or self.machine_cfg.get("feed")
            or {}
        )

        spindle_cfg = self.machine_cfg.get("spindle", {})
        tool_system_cfg = self.machine_cfg.get("tool_system", {})

        # Rapid có thể là dict từng trục hoặc một số chung.
        rapid_cfg = feed_cfg.get("rapid_traverse_mm_min", None)

        if isinstance(rapid_cfg, dict):
            rapid_x = float(rapid_cfg.get("x") or 7500.0)
            rapid_y = float(rapid_cfg.get("y") or 7500.0)
            rapid_z = float(rapid_cfg.get("z") or 7500.0)
            rapid_speed_default = max(rapid_x, rapid_y, rapid_z)
        elif rapid_cfg is not None:
            rapid_x = rapid_y = rapid_z = float(rapid_cfg)
            rapid_speed_default = float(rapid_cfg)
        else:
            rapid_speed_default = float(feed_cfg.get("rapid_speed_mm_min") or 7500.0)
            rapid_x = rapid_y = rapid_z = rapid_speed_default

        max_working_feed = float(
            feed_cfg.get("working_feed_max_mm_min")
            or feed_cfg.get("max_working_feed_mm_min")
            or 4000.0
        )

        max_spindle_rpm_val = (
            spindle_cfg.get("speed_max_rpm_machine_actual")
            or spindle_cfg.get("speed_max_rpm")
            or spindle_cfg.get("speed_max_rpm_manual_standard")
            or 5000.0
        )
        max_spindle_rpm = float(max_spindle_rpm_val)

        tool_change_time_default = float(
            tool_system_cfg.get("tool_change_time_s")
            or tool_system_cfg.get("tool_change_time_36deg_s")
            or 4.0
        )

        self.machine_params = {
            "rapid_speed": rapid_speed_default,
            "rapid_speed_x": rapid_x,
            "rapid_speed_y": rapid_y,
            "rapid_speed_z": rapid_z,

            "max_working_feed_mm_min": max_working_feed,
            "max_spindle_rpm": max_spindle_rpm,

            # Giá trị fallback. Bước sau M3/M6 sẽ đọc từ cycle_time_model nếu có.
            "tool_change_time": tool_change_time_default,
            "spindle_start_time": float(
                config.get("machine_g53", {}).get("spindle_start_time") or 4.0
            ),
            "program_stop_time": 0.0,

            "linear_sample_step": 0.5
        }

        # ---------------------------------------------------------
        # 6. Ma trận đồng nhất G54 -> G53
        # ---------------------------------------------------------
        # Dùng để quy đổi:
        # ToolTip_G53 = Programmed_G54 + G54_offset
        #
        # Tạo cả 2 tên biến để tránh lỗi lệch tên giữa các bản code cũ/mới.
        self.T_G53_from_G54 = np.array([
            [1, 0, 0, self.work_offset["x"]],
            [0, 1, 0, self.work_offset["y"]],
            [0, 0, 1, self.work_offset["z"]],
            [0, 0, 0, 1]
        ], dtype=float)

        # Alias tương thích với code cũ
        self.T_world_from_G54 = self.T_G53_from_G54

        # ---------------------------------------------------------
        # 5. Vị trí ban đầu trong WCS/G54
        # ---------------------------------------------------------
        init_wcs = self.machine_cfg.get("simulation_initial_wcs_pos", {})

        initial_programmed_wcs_pos = {
            "X": float(init_wcs.get("x", init_wcs.get("X", 0.0))),
            "Y": float(init_wcs.get("y", init_wcs.get("Y", 0.0))),
            "Z": float(init_wcs.get("z", init_wcs.get("Z", 0.0)))
        }

        # ---------------------------------------------------------
        # 6. Modal State
        # ---------------------------------------------------------
        self.state = {
            "abs_mode": True,
            "work_system": 54,
            "motion_mode": 0,
            "plane_mode": 17,

            "feedrate": 0.0,
            "rpm": 0.0,
            "actual_spindle_rpm": 0.0,
            "spindle_on": False,

            "pending_tool_id": None,
            "active_tool_id": None,

            "g43_on": False,
            "H_length": 0.0,
            "H_id": None,
            "H_status": "not_active",
            "tool_length_warning": "",

            "current_time": 0.0,

            # Mặc định bắt đầu tại G54 X0 Y0 Z0,
            # không tự ép về G53 X0 Y0 Z0.
            "programmed_wcs_pos": initial_programmed_wcs_pos
        }
        

    # =====================================================================
    # STEP 1: CẬP NHẬT MODAL STATE
    # =====================================================================
    def apply_tokens(self, tokens):
        """Cập nhật Modal State dựa trên tokens từ parser."""
        g_list = tokens.get("G", [])
        m_list = tokens.get("M", [])

        # G90/G91
        if 90 in g_list:
            self.state["abs_mode"] = True

        if 91 in g_list:
            self.state["abs_mode"] = False

        # Work Coordinate System: hiện tại chỉ dùng offset G54 trong config
        for wcs in [54, 55, 56, 57, 58, 59]:
            if wcs in g_list:
                self.state["work_system"] = wcs

        # Motion Mode
        for mode in [0, 1, 2, 3]:
            if mode in g_list:
                self.state["motion_mode"] = mode

        # Plane Mode
        if 17 in g_list:
            self.state["plane_mode"] = 17

        if 18 in g_list:
            self.state["plane_mode"] = 18

        if 19 in g_list:
            self.state["plane_mode"] = 19

        # Tool Management
        if "T" in tokens:
            self.state["pending_tool_id"] = int(tokens["T"])

        
        # Không cập nhật active_tool_id tại đây.
        # M6 sẽ được xử lý trong _update_time() để còn biết previous_tool và next_tool.
        # if 6 in m_list and self.state["pending_tool_id"] is not None:
        #     self.state["active_tool_id"] = int(self.state["pending_tool_id"])
        

        # Feedrate & RPM
        if "F" in tokens:
            self.state["feedrate"] = float(tokens["F"])

        if "S" in tokens:
            self.state["rpm"] = float(tokens["S"])

        # Spindle state
        # Không bật spindle_on tại M3/M4 ở đây.
        # M3/M4 phải được xử lý trong _update_time()
        # để còn biết trước event spindle đang tắt hay đang chạy.

        # Không tắt spindle_on tại apply_tokens.
        # M5 sẽ được xử lý trong _update_time() để còn ghi được event log.
        # if 5 in m_list:
        #     self.state["spindle_on"] = False
        #     self.state["actual_spindle_rpm"] = 0.0

        # G43/G49 & H_length
        if 43 in g_list:
            self.state["g43_on"] = True

        if 49 in g_list:
            self.state["g43_on"] = False
            self.state["H_length"] = 0.0
            self.state["H_id"] = None
            self.state["H_status"] = "not_active"
            self.state["tool_length_warning"] = ""

        # H register: lấy đúng theo H, không lấy theo active_tool_id
        if "H" in tokens:
            h_id = str(int(tokens["H"]))
            self.state["H_id"] = h_id

            tool_data = self.tools.get(h_id)

            if tool_data is None or tool_data.get("h_length") is None:
                # Không biết H thì vẫn dùng 0 để vẽ tạm,
                # nhưng phải đánh dấu dữ liệu Z là chưa xác thực.
                self.state["H_length"] = 0.0
                self.state["H_status"] = "missing"
                self.state["tool_length_warning"] = f"UNVERIFIED_TOOL_LENGTH_H{h_id}"
            else:
                self.state["H_length"] = float(tool_data.get("h_length"))
                self.state["H_status"] = tool_data.get("status", "available")
                self.state["tool_length_warning"] = ""

        # Cập nhật tọa độ lập trình WCS/G54
        for axis in ("X", "Y", "Z"):
            if axis in tokens:
                val = float(tokens[axis])

                if self.state["abs_mode"]:
                    self.state["programmed_wcs_pos"][axis] = val
                else:
                    self.state["programmed_wcs_pos"][axis] += val

    # =====================================================================
    # STEP 2: TẠO SEGMENT EVENT / MOTION
    # =====================================================================
    def build_segments(self, tokens):
        """
        Xác định block hiện tại tạo ra:
        - Event segment: M6, M3/M4, M00/M01
        - Motion segment: G0/G1/G2/G3 có X/Y/Z/I/J/K/R
        """
        segments = []

        g_list = tokens.get("G", [])
        m_list = tokens.get("M", [])

        # ---------------------------------------------------------
        # G28: return to machine reference
        # ---------------------------------------------------------
        if 28 in g_list:
            active_axes = [
                axis for axis in ("X", "Y", "Z")
                if axis in tokens
            ]

            # Nếu G28 không chỉ rõ trục, tạm mặc định chỉ rút Z
            if not active_axes:
                active_axes = ["Z"]

            # Đưa các trục được gọi về machine zero:
            # Muốn ToolTip_G53 = 0 thì Programmed_G54 = -Offset_G54
            for axis in active_axes:
                self.state["programmed_wcs_pos"][axis] = (
                    -self.work_offset[axis.lower()]
                )

            segments.append({
                "type": "motion",
                "motion_mode": 0,
                "is_g28": True
            })

            return segments

        # ---------------------------------------------------------
        # Event: thay dao M6
        # ---------------------------------------------------------
        if 6 in m_list:
            segments.append({
                "type": "event",
                "event_type": "M6"
            })

        # ---------------------------------------------------------
        # Event: khởi động trục chính M3/M4
        # ---------------------------------------------------------
        if 3 in m_list or 4 in m_list:
            segments.append({
                "type": "event",
                "event_type": "M3"
            })

        # ---------------------------------------------------------
        # Event: dừng trục chính M5
        # ---------------------------------------------------------
        if 5 in m_list:
            segments.append({
                "type": "event",
                "event_type": "M5"
            })
            
        # ---------------------------------------------------------
        # Event: dừng chương trình M00/M01
        # ---------------------------------------------------------
        if 0 in m_list:
            segments.append({
                "type": "event",
                "event_type": "M00"
            })

        if 1 in m_list:
            segments.append({
                "type": "event",
                "event_type": "M01"
            })

        # ---------------------------------------------------------
        # Motion segment
        # ---------------------------------------------------------
        has_motion = any(
            key in tokens
            for key in ["X", "Y", "Z", "I", "J", "K", "R"]
        )

        if has_motion:
            segments.append({
                "type": "motion",
                "motion_mode": self.state["motion_mode"]
            })

        return segments

    # =====================================================================
    # STEP 3: CHUYỂN ĐỔI TỌA ĐỘ
    # =====================================================================
    def compute_tip_g53(self, wcs_pos=None):
        """ToolTip_G53 = Programmed_G54 + G54_offset."""
        pos = wcs_pos if wcs_pos is not None else self.state["programmed_wcs_pos"]

        p_wcs = np.array([
            pos["X"],
            pos["Y"],
            pos["Z"],
            1.0
        ])

        p_g53_tip = self.T_G53_from_G54 @ p_wcs

        return {
            "X": float(p_g53_tip[0]),
            "Y": float(p_g53_tip[1]),
            "Z": float(p_g53_tip[2])
        }

    def compute_slide_g53(self, wcs_pos=None):
        """
        ToolTip_G53 = Programmed_G54 + G54_offset.
        Slide_G53 = ToolTip_G53 + H_length khi G43 bật.
        """
        tip = self.compute_tip_g53(wcs_pos)

        z_slide = tip["Z"]

        if self.state["g43_on"]:
            z_slide += self.state["H_length"]

        return {
            "X": tip["X"],
            "Y": tip["Y"],
            "Z": float(z_slide)
        }

    def compute_slide_g53_with_comp(self, wcs_pos=None, g43_on=None, h_length=None):
        """
        Tính vị trí slide G53 với trạng thái G43/H truyền vào.
        Dùng để xử lý trường hợp G43/H thay đổi ngay trong block có chuyển động.
        """
        tip = self.compute_tip_g53(wcs_pos)

        use_g43 = self.state["g43_on"] if g43_on is None else g43_on
        use_h = self.state["H_length"] if h_length is None else h_length

        z_slide = tip["Z"]

        if use_g43:
            z_slide += use_h

        return {
            "X": tip["X"],
            "Y": tip["Y"],
            "Z": float(z_slide)
        }

    # =====================================================================
    # STEP 4: NỘI SUY TUYẾN TÍNH G0/G1
    # =====================================================================
    def _generate_linear_points(self, start, end):
        """Băm nhỏ quỹ đạo G0/G1 thành nhiều điểm."""
        dist = np.sqrt(
            sum(
                (end[axis] - start[axis]) ** 2
                for axis in "XYZ"
            )
        )

        if dist < 1e-5:
            return [dict(start), dict(end)]

        step_size = float(self.machine_params.get("linear_sample_step", 0.5))
        num = max(2, int(dist / step_size) + 1)

        return [
            {
                axis: start[axis] + (end[axis] - start[axis]) * (i / (num - 1))
                for axis in "XYZ"
            }
            for i in range(num)
        ]

    # =====================================================================
    # STEP 5: NỘI SUY CUNG TRÒN G2/G3
    # =====================================================================
    def _generate_arc_points(self, start_wcs, tokens, mode):
        """
        Sinh điểm nội suy cho cung tròn G2/G3.

        Hiện tại ưu tiên xử lý cung bằng I/J/K.
        Nếu gặp cung dùng R mà chưa có I/J/K,
        hệ thống sẽ cảnh báo và tạm xấp xỉ bằng đoạn thẳng.
        """
        # apply_tokens() đã chạy trước đó, state hiện tại là điểm đích đúng
        # kể cả khi đang ở G90 hay G91.
        target_wcs = dict(self.state["programmed_wcs_pos"])

        plane = self.state.get("plane_mode", 17)

        # Chọn cặp trục nội suy theo mặt phẳng gia công
        if plane == 17:
            ax_h, ax_v, ax_d = "X", "Y", "Z"
            off_h, off_v = "I", "J"
        elif plane == 18:
            ax_h, ax_v, ax_d = "Z", "X", "Y"
            off_h, off_v = "K", "I"
        elif plane == 19:
            ax_h, ax_v, ax_d = "Y", "Z", "X"
            off_h, off_v = "J", "K"
        else:
            return self._generate_linear_points(start_wcs, target_wcs)

        has_center_offset = (
            (off_h in tokens) or
            (off_v in tokens)
        )

        # Nếu G2/G3 dùng R mà không có I/J/K thì hiện tại chưa xử lý tâm cung R.
        # Trả về nội suy tuyến tính để tránh tạo cung sai âm thầm.
        if "R" in tokens and not has_center_offset:
            print("⚠️ [CẢNH BÁO ARC-R]")
            print("   G2/G3 dùng R nhưng thuật toán hiện chưa nội suy cung R.")
            print("   Tạm xấp xỉ đoạn này bằng đường thẳng.")
            print("-" * 60)

            return self._generate_linear_points(start_wcs, target_wcs)

        if not has_center_offset:
            print("⚠️ [CẢNH BÁO ARC THIẾU TÂM]")
            print("   G2/G3 không có I/J/K hoặc R.")
            print("   Tạm xấp xỉ đoạn này bằng đường thẳng.")
            print("-" * 60)

            return self._generate_linear_points(start_wcs, target_wcs)

        cx = start_wcs[ax_h] + float(tokens.get(off_h, 0.0))
        cy = start_wcs[ax_v] + float(tokens.get(off_v, 0.0))

        radius = np.sqrt(
            (start_wcs[ax_h] - cx) ** 2 +
            (start_wcs[ax_v] - cy) ** 2
        )

        if radius < 1e-5:
            return self._generate_linear_points(start_wcs, target_wcs)

        start_angle = np.arctan2(
            start_wcs[ax_v] - cy,
            start_wcs[ax_h] - cx
        )

        end_angle = np.arctan2(
            target_wcs[ax_v] - cy,
            target_wcs[ax_h] - cx
        )

        # G2: clockwise, G3: counter-clockwise
        if mode == 2 and end_angle >= start_angle:
            end_angle -= 2 * np.pi
        elif mode == 3 and end_angle <= start_angle:
            end_angle += 2 * np.pi

        angle_span_deg = abs(np.degrees(end_angle - start_angle))
        num = max(15, int(angle_span_deg / 5))

        points = []

        for i, angle in enumerate(np.linspace(start_angle, end_angle, num + 1)):
            ratio = i / num

            point = {}

            point[ax_h] = cx + radius * np.cos(angle)
            point[ax_v] = cy + radius * np.sin(angle)

            # Trục còn lại nội suy tuyến tính để hỗ trợ helix đơn giản
            point[ax_d] = (
                start_wcs[ax_d] +
                (target_wcs[ax_d] - start_wcs[ax_d]) * ratio
            )

            points.append(point)

        return points

    def _to_xyz_array(self, position: Dict[str, float]) -> np.ndarray:
        """
        Convert a CNC position dictionary into a 3-axis NumPy vector.
        """
        return np.array(
            [
                float(position.get("X", 0.0)),
                float(position.get("Y", 0.0)),
                float(position.get("Z", 0.0)),
            ],
            dtype=float,
        )

    def _vector_length_mm(self, start_position_mcs: np.ndarray, end_position_mcs: np.ndarray) -> float:
        """
        Compute the geometric 3D path length in machine coordinate space.
        This is a pure geometry value and is not a cycle-time calculation.
        """
        displacement_vector = np.array(end_position_mcs, dtype=float) - np.array(start_position_mcs, dtype=float)
        return float(np.linalg.norm(displacement_vector))

    def _unit_direction_vector(
        self,
        start_position_mcs: np.ndarray,
        end_position_mcs: np.ndarray,
    ) -> np.ndarray:
        """
        Compute the unit toolpath direction vector in machine coordinate space.
        """
        displacement_vector = np.array(end_position_mcs, dtype=float) - np.array(start_position_mcs, dtype=float)
        vector_length = float(np.linalg.norm(displacement_vector))

        if vector_length <= 1e-9:
            return np.zeros(3, dtype=float)

        return displacement_vector / vector_length

    def _format_motion_type(self, motion_mode: int) -> str:
        """
        Convert the active CNC modal motion code into an industrial G-code label.
        """
        motion_map = {
            0: "G00",
            1: "G01",
            2: "G02",
            3: "G03",
        }
        return motion_map.get(int(motion_mode), "UNKNOWN")

    def _extract_motion_events(self, tokens: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract non-motion state-changing commands attached to the NC block.
        These events are stored for later planning stages without assigning any duration.
        """
        events: List[Dict[str, Any]] = []

        g_list = tokens.get("G", []) or []
        m_list = tokens.get("M", []) or []

        for g_code in g_list:
            g_code_int = int(g_code)

            if g_code_int in [43, 49, 54, 55, 56, 57, 58, 59, 90, 91, 17, 18, 19]:
                event_payload: Dict[str, Any] = {
                    "event_type": f"G{g_code_int:02d}",
                    "event_group": "modal_state",
                }

                if g_code_int == 43:
                    event_payload["event_group"] = "tool_length_compensation"
                    event_payload["h_register"] = int(tokens["H"]) if "H" in tokens else None

                if g_code_int == 49:
                    event_payload["event_group"] = "tool_length_compensation_cancel"

                events.append(event_payload)

        if "H" in tokens and 43 not in [int(g) for g in g_list]:
            events.append(
                {
                    "event_type": "H_REGISTER",
                    "event_group": "tool_length_offset_selection",
                    "h_register": int(tokens["H"]),
                }
            )

        if "T" in tokens:
            events.append(
                {
                    "event_type": "T_CODE",
                    "event_group": "tool_preselection",
                    "tool_id": int(tokens["T"]),
                }
            )

        if "S" in tokens:
            events.append(
                {
                    "event_type": "S_CODE",
                    "event_group": "spindle_speed_command",
                    "spindle_speed_rpm": float(tokens["S"]),
                }
            )

        if "F" in tokens:
            events.append(
                {
                    "event_type": "F_CODE",
                    "event_group": "feedrate_command",
                    "feedrate_mm_min": float(tokens["F"]),
                }
            )

        for m_code in m_list:
            m_code_int = int(m_code)

            if m_code_int == 6:
                events.append(
                    {
                        "event_type": "M06",
                        "event_group": "automatic_tool_change",
                        "previous_tool_id": self.state.get("active_tool_id"),
                        "next_tool_id": self.state.get("pending_tool_id"),
                    }
                )

            elif m_code_int in [3, 4]:
                events.append(
                    {
                        "event_type": f"M{m_code_int:02d}",
                        "event_group": "spindle_start",
                        "spindle_direction": "clockwise" if m_code_int == 3 else "counter_clockwise",
                        "spindle_speed_rpm": float(tokens.get("S", self.state.get("rpm", 0.0))),
                    }
                )

            elif m_code_int == 5:
                events.append(
                    {
                        "event_type": "M05",
                        "event_group": "spindle_stop",
                    }
                )

            elif m_code_int in [0, 1]:
                events.append(
                    {
                        "event_type": f"M{m_code_int:02d}",
                        "event_group": "program_stop",
                    }
                )

            elif m_code_int == 30:
                events.append(
                    {
                        "event_type": "M30",
                        "event_group": "program_end",
                    }
                )

        return events

    def _update_non_time_modal_effects(self, tokens: Dict[str, Any]) -> None:
        """
        Apply modal effects that change machine state but do not require time planning.
        """
        m_list = tokens.get("M", []) or []

        if 6 in [int(m) for m in m_list]:
            if self.state.get("pending_tool_id") is not None:
                self.state["active_tool_id"] = int(self.state["pending_tool_id"])

        if 3 in [int(m) for m in m_list] or 4 in [int(m) for m in m_list]:
            self.state["spindle_on"] = True
            self.state["actual_spindle_rpm"] = float(self.state.get("rpm", 0.0))

        if 5 in [int(m) for m in m_list]:
            self.state["spindle_on"] = False
            self.state["actual_spindle_rpm"] = 0.0

    def _linearize_motion_to_mcs_points(
        self,
        start_wcs_position: Dict[str, float],
        end_wcs_position: Dict[str, float],
        tokens: Dict[str, Any],
        motion_mode: int,
    ) -> List[np.ndarray]:
        """
        Convert the programmed motion geometry into a list of machine-coordinate points.
        No temporal sampling or feedrate scheduling is performed here.
        """
        if motion_mode in [2, 3]:
            wcs_points = self._generate_arc_points(
                start_wcs=start_wcs_position,
                tokens=tokens,
                mode=motion_mode,
            )
        else:
            wcs_points = [
                dict(start_wcs_position),
                dict(end_wcs_position),
            ]

        mcs_points: List[np.ndarray] = []

        for wcs_point in wcs_points:
            slide_position_mcs = self.compute_slide_g53(wcs_point)
            mcs_points.append(self._to_xyz_array(slide_position_mcs))

        return mcs_points

    def _create_motion_block(
        self,
        line_number: int,
        raw_block: str,
        motion_type: str,
        start_position_mcs: np.ndarray,
        end_position_mcs: np.ndarray,
        geometry_source: str,
        commanded_feed_mm_min: float,
        pre_motion_events: Optional[List[Dict[str, Any]]] = None,
        post_motion_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[MotionBlock]:
        """
        Create one geometry-only MotionBlock from two consecutive machine-coordinate points.
        """
        path_length_mm = self._vector_length_mm(start_position_mcs, end_position_mcs)

        if path_length_mm <= 1e-9:
            return None

        is_rapid_positioning = motion_type == "G00"
        is_cutting_interpolation = motion_type in ["G01", "G02", "G03"]

        return MotionBlock(
            line_number=int(line_number),
            raw_block=str(raw_block),
            motion_type=str(motion_type),
            start_position_mcs=np.array(start_position_mcs, dtype=float),
            end_position_mcs=np.array(end_position_mcs, dtype=float),
            path_length_mm=float(path_length_mm),
            unit_direction_vector=self._unit_direction_vector(start_position_mcs, end_position_mcs),
            geometry_source=str(geometry_source),
            commanded_feed_mm_min=float(commanded_feed_mm_min),
            is_rapid_positioning=bool(is_rapid_positioning),
            is_cutting_interpolation=bool(is_cutting_interpolation),
            pre_motion_events=list(pre_motion_events or []),
            post_motion_events=list(post_motion_events or []),
        )

    def _apply_g28_geometry_target(self, tokens: Dict[str, Any]) -> None:
        """
        Update the programmed WCS position so that the requested machine axes return to G53 zero.
        """
        active_axes = [axis for axis in ("X", "Y", "Z") if axis in tokens]

        if not active_axes:
            active_axes = ["Z"]

        for axis in active_axes:
            self.state["programmed_wcs_pos"][axis] = -float(self.work_offset[axis.lower()])

    def build_geometry_chain(self, nc_program_text: str, gcode_engine: Optional[Any] = None) -> List[MotionBlock]:
        """
        Build the first-pass CNC geometry chain.

        This pass performs only:
        - NC parsing
        - modal state tracking
        - WCS-to-MCS coordinate transformation
        - tool length compensation propagation
        - linear and arc geometry decomposition

        This pass does not perform:
        - feed scheduling
        - distance-over-feed timing
        - FIR filter modeling
        - corner blending
        - micro-block peak feed calculation
        - cycle-time accumulation
        """
        if gcode_engine is None:
            from src.engine import GCodeEngine
            gcode_engine = GCodeEngine(self.config)

        geometry_chain: List[MotionBlock] = []
        pending_pre_motion_events: List[Dict[str, Any]] = []

        for line_number, raw_line in enumerate(str(nc_program_text).splitlines(), start=1):
            raw_block = str(raw_line).strip()

            if not raw_block:
                continue

            parsed_tokens = gcode_engine.parse_line(raw_block)
            tokens: Dict[str, Any] = parsed_tokens if isinstance(parsed_tokens, dict) else {}

            if not tokens:
                continue

            pre_update_wcs_position = dict(self.state["programmed_wcs_pos"])
            pre_update_motion_mode = int(self.state.get("motion_mode", 0))
            block_events = self._extract_motion_events(tokens)

            g_list = [int(g_code) for g_code in (tokens.get("G", []) or [])]
            has_g28_return = 28 in g_list

            has_axis_or_arc_address = any(address in tokens for address in ["X", "Y", "Z", "I", "J", "K", "R"])
            has_motion_command = any(g_code in [0, 1, 2, 3] for g_code in g_list)
            has_motion_geometry = bool(has_axis_or_arc_address or has_g28_return)

            if not has_motion_geometry:
                self.apply_tokens(tokens)
                self._update_non_time_modal_effects(tokens)
                pending_pre_motion_events.extend(block_events)
                continue

            if has_g28_return:
                self._apply_g28_geometry_target(tokens)
                post_update_wcs_position = dict(self.state["programmed_wcs_pos"])
                motion_mode = 0
            else:
                self.apply_tokens(tokens)
                post_update_wcs_position = dict(self.state["programmed_wcs_pos"])
                motion_mode = int(self.state.get("motion_mode", pre_update_motion_mode))

            if has_motion_command:
                motion_mode = next(g_code for g_code in g_list if g_code in [0, 1, 2, 3])

            motion_type = self._format_motion_type(motion_mode)

            if motion_type == "UNKNOWN":
                self._update_non_time_modal_effects(tokens)
                pending_pre_motion_events.extend(block_events)
                continue

            block_pre_motion_events = list(pending_pre_motion_events)
            block_pre_motion_events.extend(block_events)
            pending_pre_motion_events = []

            commanded_feed_mm_min = float(self.state.get("feedrate", 0.0))

            if motion_mode == 0:
                rapid_feed_candidates = [
                    float(self.machine_params.get("rapid_speed_x", 0.0)),
                    float(self.machine_params.get("rapid_speed_y", 0.0)),
                    float(self.machine_params.get("rapid_speed_z", 0.0)),
                    float(self.machine_params.get("rapid_speed", 0.0)),
                ]
                commanded_feed_mm_min = max(rapid_feed_candidates)

            mcs_points = self._linearize_motion_to_mcs_points(
                start_wcs_position=pre_update_wcs_position,
                end_wcs_position=post_update_wcs_position,
                tokens=tokens,
                motion_mode=motion_mode,
            )

            geometry_source = "arc_linearized" if motion_mode in [2, 3] else "linear"

            for point_index in range(len(mcs_points) - 1):
                segment_pre_events = block_pre_motion_events if point_index == 0 else []

                motion_block = self._create_motion_block(
                    line_number=line_number,
                    raw_block=raw_block,
                    motion_type=motion_type,
                    start_position_mcs=mcs_points[point_index],
                    end_position_mcs=mcs_points[point_index + 1],
                    geometry_source=geometry_source,
                    commanded_feed_mm_min=commanded_feed_mm_min,
                    pre_motion_events=segment_pre_events,
                    post_motion_events=[],
                )

                if motion_block is not None:
                    geometry_chain.append(motion_block)

            self._update_non_time_modal_effects(tokens)

        if pending_pre_motion_events and geometry_chain:
            geometry_chain[-1].post_motion_events.extend(pending_pre_motion_events)

        return geometry_chain
    # =====================================================================
    # =====================================================================
    # STEP 6: ĐỘNG CƠ TÍNH THỜI GIAN
    # =====================================================================
    def _rapid_segment_time_sec(self, p0, p1):
        """
        Tính thời gian G0 theo rapid từng trục.
        Các trục X/Y/Z chạy đồng thời, nên thời gian lấy theo trục lâu nhất.
        """

        dx = abs(float(p1["X"]) - float(p0["X"]))
        dy = abs(float(p1["Y"]) - float(p0["Y"]))
        dz = abs(float(p1["Z"]) - float(p0["Z"]))

        vx = max(float(self.machine_params.get("rapid_speed_x", 7500.0)), 1e-6)
        vy = max(float(self.machine_params.get("rapid_speed_y", 7500.0)), 1e-6)
        vz = max(float(self.machine_params.get("rapid_speed_z", 7500.0)), 1e-6)

        tx = dx / vx * 60.0
        ty = dy / vy * 60.0
        tz = dz / vz * 60.0

        return max(tx, ty, tz)

    def _get_cycle_time_model(self):
        """
        Đọc mô hình cycle time của máy đang active.
        measured_cycle_time_s chỉ dùng để đối chứng, không dùng để ép tổng thời gian.
        """
        return self.machine_cfg.get("cycle_time_model", {})
    
    def _get_interpolator_cfg(self):
        """
        Read controller interpolator model parameters.

        This configuration is intentionally disabled until machine specific
        identification is available. No arbitrary correction factor is allowed.
        """
        return self._get_cycle_time_model().get("interpolator_model", {})


    def _is_interpolator_model_enabled(self) -> bool:
        cfg = self._get_interpolator_cfg()
        return bool(cfg.get("enabled", False))


    def _safe_axis_min(self, unit_vec, limits):
        """
        Quy đổi giới hạn theo từng trục thành giới hạn theo phương chạy dao.

        Ví dụ:
            v_path <= Vx_max / |ux|
            a_path <= Ax_max / |ux|
            j_path <= Jx_max / |ux|
        """
        values = []

        for axis, u in unit_vec.items():
            u_abs = abs(float(u))
            lim = float(limits.get(axis, 0.0) or 0.0)

            if u_abs > 1e-9 and lim > 0:
                values.append(lim / u_abs)

        return min(values) if values else float("inf")


    def _dominant_axis_by_direction(self, unit_vec):
        """Chọn trục có thành phần chuyển động lớn nhất."""
        return max(unit_vec.keys(), key=lambda axis: abs(float(unit_vec[axis])))


    def _dominant_axis_by_time(self, axis_times):
        """Chọn trục có thời gian chuyển động lâu nhất."""
        return max(axis_times.keys(), key=lambda axis: float(axis_times[axis]))


    def _get_axis_interpolator_params(self):
        """
        Đọc thông số Ward/FIR theo từng trục từ config.json.

        Đường dẫn config:
            cycle_time_model -> interpolator_model -> axis_parameters
        """
        cfg = self._get_interpolator_cfg()
        raw_axis_params = cfg.get("axis_parameters", {}) or {}

        axis_params = {}

        for axis in ["x", "y", "z"]:
            p = raw_axis_params.get(axis, {}) or {}
            axis_params[axis] = {
                "T1_s": float(p.get("T1_s", 0.0) or 0.0),
                "Td_s": float(p.get("Td_s", 0.0) or 0.0),
                "Jmax_mm_s3": float(p.get("Jmax_mm_s3", 0.0) or 0.0),
                "Amax_mm_s2": float(p.get("Amax_mm_s2", 0.0) or 0.0),
            }

        return axis_params


    def _path_metrics_from_trajectory(self, points):
        """
        Tính L, vectơ hướng tuyệt đối và lượng chạy từng trục từ trajectory_slide.

        Với line thẳng: unit_abs gần tương đương |ux|, |uy|, |uz|.
        Với cung đã nội suy: unit_abs là tỷ lệ đóng góp trục trên toàn cung.
        """
        if not points or len(points) < 2:
            return (
                0.0,
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 0.0, "y": 0.0, "z": 0.0},
            )

        total_length = 0.0
        axis_abs_motion = {"x": 0.0, "y": 0.0, "z": 0.0}

        for i in range(len(points) - 1):
            dx = float(points[i + 1]["X"]) - float(points[i]["X"])
            dy = float(points[i + 1]["Y"]) - float(points[i]["Y"])
            dz = float(points[i + 1]["Z"]) - float(points[i]["Z"])

            segment_length = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
            total_length += segment_length

            axis_abs_motion["x"] += abs(dx)
            axis_abs_motion["y"] += abs(dy)
            axis_abs_motion["z"] += abs(dz)

        if total_length <= 1e-9:
            unit_abs = {"x": 0.0, "y": 0.0, "z": 0.0}
        else:
            unit_abs = {
                axis: axis_abs_motion[axis] / total_length
                for axis in ["x", "y", "z"]
            }

        return float(total_length), unit_abs, axis_abs_motion


    def _get_working_feed_limit_by_axis_mm_min(self):
        """
        Lấy giới hạn feed làm việc theo trục.
        Nếu config chỉ có một số chung thì dùng chung cho X/Y/Z.
        """
        feed_cfg = (
            self.machine_cfg.get("feed_system")
            or self.machine_cfg.get("feed")
            or {}
        )

        raw_limit = (
            feed_cfg.get("working_feed_max_mm_min")
            or feed_cfg.get("max_working_feed_mm_min")
            or self.machine_params.get("max_working_feed_mm_min")
            or 4000.0
        )

        if isinstance(raw_limit, dict):
            return {
                "x": float(raw_limit.get("x", 4000.0) or 4000.0),
                "y": float(raw_limit.get("y", 4000.0) or 4000.0),
                "z": float(raw_limit.get("z", 4000.0) or 4000.0),
            }

        limit = float(raw_limit)
        return {"x": limit, "y": limit, "z": limit}


    def _compute_ward_fir_duration_for_motion(self, points, commanded_feed_mm_min, is_air):
        """
        Tính thời gian motion theo mô hình Ward/FIR tối thiểu.

        G01/G02/G03:
            T = L / v_target + Td_eff
            T1_eff = sqrt(v_target / J_path)
            Td_eff = 3 * T1_eff

        G00:
            T = max(Tx, Ty, Tz) + Td_axis
        """
        path_length_mm, unit_vec_abs, axis_abs_motion = self._path_metrics_from_trajectory(points)

        if path_length_mm <= 1e-9:
            return {
                "duration_s": 0.0,
                "basic_time_s": 0.0,
                "fir_delay_s": 0.0,
                "path_length_mm": 0.0,
                "scheduled_feed_mm_min": 0.0,
                "dominant_axis": None,
                "A_path_mm_s2": None,
                "J_path_mm_s3": None,
                "T1_eff_s": None,
                "model_status": "zero_length_motion",
            }

        axis_params = self._get_axis_interpolator_params()
        interpolator_enabled = self._is_interpolator_model_enabled()

        # -----------------------------------------------------
        # G00 rapid: các trục chạy đồng thời, lấy trục lâu nhất
        # -----------------------------------------------------
        if is_air:
            rapid_mm_min = {
                "x": max(float(self.machine_params.get("rapid_speed_x", 7500.0)), 1e-6),
                "y": max(float(self.machine_params.get("rapid_speed_y", 7500.0)), 1e-6),
                "z": max(float(self.machine_params.get("rapid_speed_z", 7500.0)), 1e-6),
            }

            axis_times = {
                "x": axis_abs_motion["x"] / rapid_mm_min["x"] * 60.0,
                "y": axis_abs_motion["y"] / rapid_mm_min["y"] * 60.0,
                "z": axis_abs_motion["z"] / rapid_mm_min["z"] * 60.0,
            }

            dominant_axis = self._dominant_axis_by_time(axis_times)
            basic_time_s = float(axis_times[dominant_axis])

            fir_delay_s = 0.0
            t1_eff_s = None

            if interpolator_enabled and dominant_axis in axis_params:
                fir_delay_s = float(axis_params[dominant_axis].get("Td_s", 0.0) or 0.0)
                t1_eff_s = float(axis_params[dominant_axis].get("T1_s", 0.0) or 0.0)

            return {
                "duration_s": float(basic_time_s + fir_delay_s),
                "basic_time_s": basic_time_s,
                "fir_delay_s": fir_delay_s,
                "path_length_mm": float(path_length_mm),
                "scheduled_feed_mm_min": float(max(rapid_mm_min.values())),
                "dominant_axis": dominant_axis.upper(),
                "A_path_mm_s2": None,
                "J_path_mm_s3": None,
                "T1_eff_s": t1_eff_s,
                "model_status": "G00 rapid with Ward/FIR delay" if fir_delay_s > 0 else "G00 rapid axis-synchronised",
            }

        # -----------------------------------------------------
        # G01/G02/G03: feed motion
        # -----------------------------------------------------
        commanded_feed_mm_min = max(float(commanded_feed_mm_min), 1e-6)
        v_cmd_mm_s = commanded_feed_mm_min / 60.0

        axis_feed_limits_mm_min = self._get_working_feed_limit_by_axis_mm_min()
        axis_feed_limits_mm_s = {
            axis: float(value) / 60.0
            for axis, value in axis_feed_limits_mm_min.items()
        }

        axis_A_limits = {
            axis: axis_params.get(axis, {}).get("Amax_mm_s2", 0.0)
            for axis in ["x", "y", "z"]
        }
        axis_J_limits = {
            axis: axis_params.get(axis, {}).get("Jmax_mm_s3", 0.0)
            for axis in ["x", "y", "z"]
        }

        v_axis_limit_mm_s = self._safe_axis_min(unit_vec_abs, axis_feed_limits_mm_s)
        A_path_mm_s2 = self._safe_axis_min(unit_vec_abs, axis_A_limits)
        J_path_mm_s3 = self._safe_axis_min(unit_vec_abs, axis_J_limits)

        v_target_mm_s = min(v_cmd_mm_s, v_axis_limit_mm_s)
        v_target_mm_s = max(float(v_target_mm_s), 1e-9)

        basic_time_s = path_length_mm / v_target_mm_s

        dominant_axis = self._dominant_axis_by_direction(unit_vec_abs)
        fir_delay_s = 0.0
        t1_eff_s = None

        if interpolator_enabled and axis_params:
            t1_values = [
                float(p.get("T1_s", 0.0) or 0.0)
                for p in axis_params.values()
                if float(p.get("T1_s", 0.0) or 0.0) > 0
            ]

            if math.isfinite(J_path_mm_s3) and J_path_mm_s3 > 0 and t1_values:
                t1_eff_s = math.sqrt(v_target_mm_s / J_path_mm_s3)
                t1_eff_s = max(t1_eff_s, min(t1_values))
                t1_eff_s = min(t1_eff_s, max(t1_values))
                fir_delay_s = 3.0 * t1_eff_s
            elif dominant_axis in axis_params:
                t1_eff_s = float(axis_params[dominant_axis].get("T1_s", 0.0) or 0.0)
                fir_delay_s = float(axis_params[dominant_axis].get("Td_s", 0.0) or 0.0)

        return {
            "duration_s": float(basic_time_s + fir_delay_s),
            "basic_time_s": float(basic_time_s),
            "fir_delay_s": float(fir_delay_s),
            "path_length_mm": float(path_length_mm),
            "scheduled_feed_mm_min": float(v_target_mm_s * 60.0),
            "dominant_axis": dominant_axis.upper(),
            "A_path_mm_s2": None if not math.isfinite(A_path_mm_s2) else float(A_path_mm_s2),
            "J_path_mm_s3": None if not math.isfinite(J_path_mm_s3) else float(J_path_mm_s3),
            "T1_eff_s": t1_eff_s,
            "model_status": "G01/G02/G03 with Ward/FIR dynamic T1" if fir_delay_s > 0 else "Basic distance over feed",
        }


    def _compute_corner_angle_rad(self, previous_vector, next_vector):
        """
        Compute the geometric transition angle between two consecutive motion vectors.
        """
        if previous_vector is None or next_vector is None:
            return 0.0

        v1 = np.array(previous_vector, dtype=float)
        v2 = np.array(next_vector, dtype=float)

        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)

        if n1 <= 1e-9 or n2 <= 1e-9:
            return 0.0

        cos_value = np.dot(v1, v2) / (n1 * n2)
        cos_value = np.clip(cos_value, -1.0, 1.0)

        return float(np.arccos(cos_value))


    def _corner_blending_weight(self, angle_rad: float) -> float:
        """
        Geometry based blending weight.

        This is not a tuning factor. It only determines whether a corner is
        geometrically eligible for blending. The actual time constant must come
        from machine identification.
        """
        cfg = self._get_interpolator_cfg()

        min_angle_deg = float(cfg.get("minimum_blending_angle_deg", 5.0))
        min_angle_rad = np.deg2rad(min_angle_deg)

        if angle_rad <= min_angle_rad:
            return 0.0

        return float(min(angle_rad / np.pi, 1.0))


    def _ward_effective_block_time(
        self,
        basic_time_s: float,
        entry_angle_rad: float,
        exit_angle_rad: float
    ) -> dict:
        """
        Ward compatible block time correction.

        UI note:
        - Do not display internal variable names on Streamlit.
        - Display names must be readable, for example:
        "Effective Block Time", "Corner Blending Candidate",
        "Micro Block Candidate".
        """

        cfg = self._get_interpolator_cfg()

        if not self._is_interpolator_model_enabled():
            return {
                "effective_time_s": basic_time_s,
                "blending_deduction_s": 0.0,
                "is_blending_active": False,
                "is_micro_block": False,
                "actual_peak_feed_mm_min": None,
                "model_status": "Basic distance over feed model"
            }

        blend_time = cfg.get("corner_blending_time_s", None)
        time_constant = cfg.get("interpolator_time_constant_s", None)

        if blend_time is None or time_constant is None:
            return {
                "effective_time_s": basic_time_s,
                "blending_deduction_s": 0.0,
                "is_blending_active": False,
                "is_micro_block": False,
                "actual_peak_feed_mm_min": None,
                "model_status": "Ward model disabled because controller parameters are missing"
            }

        blend_time = float(blend_time)
        time_constant = float(time_constant)

        entry_weight = self._corner_blending_weight(entry_angle_rad)
        exit_weight = self._corner_blending_weight(exit_angle_rad)

        blending_deduction = (entry_weight + exit_weight) * blend_time
        effective_time = basic_time_s - blending_deduction

        if effective_time <= 0:
            return {
                "effective_time_s": 0.0,
                "blending_deduction_s": round(blending_deduction, 6),
                "is_blending_active": True,
                "is_micro_block": True,
                "actual_peak_feed_mm_min": 0.0,
                "model_status": "Block fully absorbed by continuous blending window"
            }

        is_micro_block = effective_time < time_constant

        return {
            "effective_time_s": float(effective_time),
            "blending_deduction_s": round(blending_deduction, 6),
            "is_blending_active": blending_deduction > 0,
            "is_micro_block": is_micro_block,
            "actual_peak_feed_mm_min": None,
            "model_status": "Ward compatible interpolation model"
        }


    def _get_spindle_event_cfg(self):
        return self._get_cycle_time_model().get("spindle_event_model", {})


    def _get_toolchange_event_cfg(self):
        return self._get_cycle_time_model().get("tool_change_event_model", {})

    def get_m3_time_s(self):
        """
        Tính thời gian M3/M4.

        Ưu tiên mô hình tham số máy:
            T_M3 = base_start_time_s + |S_target - S_current| / accel_rpm_per_s

        Nếu config hiện tại vẫn dùng m3_by_rpm_s thì vẫn hỗ trợ để không làm vỡ app.
        """

        cycle_cfg = self._get_cycle_time_model()

        target_rpm = float(self.state.get("rpm", 0.0))
        current_rpm = float(self.state.get("actual_spindle_rpm", 0.0))

        if target_rpm <= 0:
            return 0.0

        # -----------------------------------------------------
        # 1. Schema mới: spindle_event_model
        # -----------------------------------------------------
        spindle_cfg = cycle_cfg.get("spindle_event_model", {})

        if spindle_cfg:
            accel = spindle_cfg.get("accel_rpm_per_s", None)

            default_start_time = float(
                spindle_cfg.get(
                    "default_start_time_s",
                    self.machine_params.get("spindle_start_time", 4.0)
                )
            )

            base_start_time = float(spindle_cfg.get("base_start_time_s", 0.0))
            min_event_time = float(spindle_cfg.get("min_event_time_s", 0.0))

            if accel is None or float(accel) <= 0:
                dt = default_start_time
            else:
                accel = float(accel)

                # Nếu spindle đang tắt thì cộng base.
                # Nếu spindle đang chạy thì chỉ tính phần đổi tốc.
                base = base_start_time if not self.state.get("spindle_on", False) else 0.0
                dt = base + abs(target_rpm - current_rpm) / max(accel, 1e-6)

            return max(float(dt), min_event_time)

        # -----------------------------------------------------
        # 2. Schema cũ: event_time_model / m3_by_rpm_s
        # -----------------------------------------------------
        event_cfg = cycle_cfg.get("event_time_model", {})
        m3_map = event_cfg.get("m3_by_rpm_s", {})

        rpm_key = str(int(round(target_rpm)))

        if rpm_key in m3_map:
            return float(m3_map[rpm_key])

        return float(
            m3_map.get(
                "default",
                self.machine_params.get("spindle_start_time", 4.0)
            )
        )

    def _shortest_station_distance(self, previous_station, next_station, station_count):
        """
        Tính số bước quay ngắn nhất trên đài dao tròn.

        Ví dụ đài 10 dao:
        T3 -> T10:
        direct = |10 - 3| = 7
        reverse = 10 - 7 = 3
        n = 3
        """
        if previous_station is None or next_station is None:
            return None

        prev_station = int(previous_station)
        next_station = int(next_station)
        station_count = int(station_count)

        direct = abs(next_station - prev_station)
        reverse = station_count - direct

        return min(direct, reverse)

    def get_m6_time_s(self, previous_tool, next_tool):
        """
        Tính thời gian thay dao M6.

        Ưu tiên mô hình tổng quát:
            T_M6 = base_time_s + n_station * step_time_s

        Nếu config hiện tại vẫn dùng m6_by_transition_s thì vẫn hỗ trợ để không làm vỡ app.
        """

        cycle_cfg = self._get_cycle_time_model()

        # -----------------------------------------------------
        # 1. Schema mới: tool_change_event_model
        # -----------------------------------------------------
        tool_cfg = cycle_cfg.get("tool_change_event_model", {})

        if tool_cfg:
            if next_tool is None:
                return 0.0

            if previous_tool is not None and int(previous_tool) == int(next_tool):
                return float(tool_cfg.get("same_tool_time_s", 0.0))

            station_count = int(
                tool_cfg.get(
                    "stations",
                    self.machine_cfg.get("tool_system", {}).get("tool_stations", 10)
                )
            )

            n_station = self._shortest_station_distance(
                previous_station=previous_tool,
                next_station=next_tool,
                station_count=station_count
            )

            if n_station is None:
                return float(
                    tool_cfg.get(
                        "unknown_previous_tool_time_s",
                        self.machine_params.get("tool_change_time", 4.0)
                    )
                )

            base_time = float(
                tool_cfg.get(
                    "base_time_s",
                    self.machine_params.get("tool_change_time", 4.0)
                )
            )

            step_time = float(tool_cfg.get("step_time_s", 0.0))

            return float(base_time + n_station * step_time)

        # -----------------------------------------------------
        # 2. Schema cũ: event_time_model / m6_by_transition_s
        # -----------------------------------------------------
        event_cfg = cycle_cfg.get("event_time_model", {})
        m6_map = event_cfg.get("m6_by_transition_s", {})

        prev_key = "None" if previous_tool is None else str(previous_tool)
        next_key = "None" if next_tool is None else str(next_tool)

        transition_key = f"{prev_key}->{next_key}"

        if transition_key in m6_map:
            return float(m6_map[transition_key])

        return float(
            m6_map.get(
                "default",
                self.machine_params.get("tool_change_time", 4.0)
            )
        ) 
    def _update_time(self, seg):
        start_time = self.state["current_time"]

        line_num = seg.get("line_number")
        raw_line = seg.get("raw_line")
        motion_mode = seg.get("motion_mode")
        tool_id = self.state.get("active_tool_id", "None")

        if seg["type"] == "event":
            event_type = seg.get("event_type")

            dt = 0.0

            if event_type == "M6":
                previous_tool = seg.get("previous_tool_id")
                next_tool = seg.get("next_tool_id")

                station_count = int(
                    self._get_toolchange_event_cfg().get(
                        "stations",
                        self.machine_cfg.get("tool_system", {}).get("tool_stations", 10)
                    )
                )

                n_station = self._shortest_station_distance(
                    previous_tool,
                    next_tool,
                    station_count
                )

                dt = self.get_m6_time_s(previous_tool, next_tool)

                seg["previous_tool_id"] = previous_tool
                seg["next_tool_id"] = next_tool
                seg["station_count"] = station_count
                seg["tool_station_steps"] = n_station

            elif event_type == "M3":
                target_rpm = float(self.state.get("rpm", 0.0))
                current_rpm = float(self.state.get("actual_spindle_rpm", 0.0))

                dt = self.get_m3_time_s()

                seg["spindle_rpm_before"] = current_rpm
                seg["spindle_rpm_target"] = target_rpm

            elif event_type == "M5":
                dt = 0.0
                seg["spindle_rpm_before"] = float(self.state.get("actual_spindle_rpm", 0.0))
                seg["spindle_rpm_target"] = 0.0

            elif event_type in ["M00", "M01"]:
                dt = self.machine_params.get("program_stop_time", 0.0)

            seg["is_air_time"] = True
            seg["start_time"] = round(start_time, 4)

            self.state["current_time"] += dt

            # Sau khi M6 hoàn tất mới cập nhật dao active.
            if event_type == "M6":
                next_tool = seg.get("next_tool_id")
                if next_tool is not None:
                    self.state["active_tool_id"] = int(next_tool)

            # Sau khi M3 hoàn tất mới cập nhật trạng thái spindle.
            if event_type == "M3":
                self.state["spindle_on"] = True
                self.state["actual_spindle_rpm"] = float(self.state.get("rpm", 0.0))
            if event_type == "M5":
                self.state["spindle_on"] = False
                self.state["actual_spindle_rpm"] = 0.0                

            seg["end_time"] = round(self.state["current_time"], 4)
            seg["duration"] = round(dt, 4)
            if event_type in ["M3", "M5", "M6"]:
                seg["event_duration_source"] = (
                    "cycle_time_model" if self._get_cycle_time_model() else "machine_params_fallback"
                )            

        elif seg["type"] == "motion":
            is_air = (motion_mode == 0)
            seg["is_air_time"] = is_air

            points = seg["trajectory_slide"]
            current_t = start_time

            if is_air:
                commanded_feed_for_time = self.machine_params.get("rapid_speed", 100.0)
            else:
                commanded_feed_for_time = self.state["feedrate"]

            time_info = self._compute_ward_fir_duration_for_motion(
                points=points,
                commanded_feed_mm_min=commanded_feed_for_time,
                is_air=is_air
            )

            total_duration_s = float(time_info.get("duration_s", 0.0))
            path_length_mm = float(time_info.get("path_length_mm", 0.0))
            display_feed_mm_min = float(
                time_info.get(
                    "scheduled_feed_mm_min",
                    self.state.get("feedrate", 0.0)
                )
            )

            # Ghi metadata cho segment để app/analytics có thể đọc
            seg["cycle_time_model_status"] = time_info.get("model_status")
            seg["path_length_mm"] = round(path_length_mm, 6)
            seg["basic_time_s"] = round(float(time_info.get("basic_time_s", 0.0)), 6)
            seg["ward_fir_delay_s"] = round(float(time_info.get("fir_delay_s", 0.0)), 6)
            seg["dominant_axis"] = time_info.get("dominant_axis")
            seg["scheduled_feed_mm_min"] = round(display_feed_mm_min, 4)
            seg["A_path_mm_s2"] = time_info.get("A_path_mm_s2")
            seg["J_path_mm_s3"] = time_info.get("J_path_mm_s3")
            seg["T1_eff_s"] = time_info.get("T1_eff_s")

            if len(points) > 0:
                points[0].update({
                    "t": round(current_t, 4),
                    "line_number": line_num,
                    "raw_line": raw_line,
                    "motion_mode": motion_mode,
                    "tool_id": tool_id,
                    "is_air_time": is_air,
                    "feedrate": display_feed_mm_min,
                    "rpm": self.state["actual_spindle_rpm"] if self.state["spindle_on"] else 0.0,
                    "cycle_time_model_status": seg["cycle_time_model_status"],
                    "ward_fir_delay_s": seg["ward_fir_delay_s"],
                    "dominant_axis": seg["dominant_axis"]
                })

            # Phân bố tổng thời gian của block xuống các điểm nội suy
            # theo tỷ lệ chiều dài hình học từng đoạn nhỏ.
            for i in range(len(points) - 1):
                dx = points[i + 1]["X"] - points[i]["X"]
                dy = points[i + 1]["Y"] - points[i]["Y"]
                dz = points[i + 1]["Z"] - points[i]["Z"]

                dist = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

                if path_length_mm > 1e-9:
                    dt_point = total_duration_s * (dist / path_length_mm)
                else:
                    dt_point = 0.0

                current_t += dt_point

                points[i + 1].update({
                    "t": round(current_t, 4),
                    "line_number": line_num,
                    "raw_line": raw_line,
                    "motion_mode": motion_mode,
                    "tool_id": tool_id,
                    "is_air_time": is_air,
                    "feedrate": display_feed_mm_min,
                    "rpm": self.state["actual_spindle_rpm"] if self.state["spindle_on"] else 0.0,
                    "cycle_time_model_status": seg["cycle_time_model_status"],
                    "ward_fir_delay_s": seg["ward_fir_delay_s"],
                    "dominant_axis": seg["dominant_axis"]
                })

            seg["start_time"] = round(start_time, 4)
            self.state["current_time"] = start_time + total_duration_s
            seg["end_time"] = round(self.state["current_time"], 4)
            seg["duration"] = round(total_duration_s, 4)

    # =====================================================================
    # STEP 7: KIỂM TRA QUÁ HÀNH TRÌNH
    # =====================================================================
    def _check_overtravel(self, seg):
        if seg.get("type") != "motion" or not seg.get("trajectory_slide"):
            seg["ot_summary"] = {"seg_ot": False}
            return

        points = seg["trajectory_slide"]

        summary = {
            "seg_ot": False,
            "seg_ot_axis": set(),
            "max_violation": {
                "X": 0.0,
                "Y": 0.0,
                "Z": 0.0
            },
            "first_violation": None
        }

        for i, point in enumerate(points):
            point_ot = False

            for axis in ["X", "Y", "Z"]:
                key_ot = f"ot_{axis.lower()}"
                key_amount = f"ot_amount_{axis.lower()}"

                point[key_ot] = False
                point[key_amount] = 0.0

                value = point.get(axis)

                if value is None or math.isnan(value):
                    continue

                limit_min, limit_max = self.limits[axis.lower()]

                amount = 0.0

                if value > limit_max:
                    point[key_ot] = True
                    amount = value - limit_max
                    point_ot = True
                elif value < limit_min:
                    point[key_ot] = True
                    amount = value - limit_min
                    point_ot = True

                point[key_amount] = round(amount, 4)

                if abs(amount) > abs(summary["max_violation"][axis]):
                    summary["max_violation"][axis] = round(amount, 4)

            if point_ot:
                summary["seg_ot"] = True

                for axis in ["X", "Y", "Z"]:
                    if point[f"ot_{axis.lower()}"]:
                        summary["seg_ot_axis"].add(axis)

                if summary["first_violation"] is None:
                    summary["first_violation"] = {
                        "index": i,
                        "t": point.get("t"),
                        "line_number": point.get("line_number"),
                        "raw_line": point.get("raw_line")
                    }

        summary["seg_ot_axis"] = list(summary["seg_ot_axis"])
        seg["ot_summary"] = summary

    # =====================================================================
    # STEP 8: TRẠM ĐIỀU PHỐI CHÍNH
    # =====================================================================
    def apply_block(self, block_dict):
        tokens = block_dict.get("tokens", block_dict)

        if not tokens:
            return []

        line_num = block_dict.get("line_number", 0)
        raw_line = block_dict.get("raw_line", "")

        start_wcs = dict(self.state["programmed_wcs_pos"])
        previous_tool_before_block = self.state.get("active_tool_id")
        start_g43_on = self.state["g43_on"]
        start_H_length = self.state["H_length"]
        start_H_status = self.state.get("H_status", "not_active")
        start_tool_warning = self.state.get("tool_length_warning", "")

        self.apply_tokens(tokens)
        next_tool_after_tokens = self.state.get("pending_tool_id")

        end_g43_on = self.state["g43_on"]
        end_H_length = self.state["H_length"]
        end_H_status = self.state.get("H_status", "not_active")
        end_tool_warning = self.state.get("tool_length_warning", "")

        segments = self.build_segments(tokens)

        for seg in segments:
            seg["line_number"] = line_num
            seg["raw_line"] = raw_line
            
            if seg.get("type") == "event" and seg.get("event_type") == "M6":
                seg["previous_tool_id"] = previous_tool_before_block
                seg["next_tool_id"] = next_tool_after_tokens

            if seg["type"] == "motion":
                if seg["motion_mode"] in [2, 3]:
                    path_wcs = self._generate_arc_points(
                        start_wcs,
                        tokens,
                        seg["motion_mode"]
                    )
                else:
                    path_wcs = self._generate_linear_points(
                        start_wcs,
                        dict(self.state["programmed_wcs_pos"])
                    )

                # Slide_G53 dùng cho Graph 1 và Overtravel
                trajectory_slide = []

                n_path = len(path_wcs)

                for idx, point_wcs in enumerate(path_wcs):
                    if n_path <= 1:
                        ratio = 1.0
                    else:
                        ratio = idx / (n_path - 1)

                    # Nếu H/G43 thay đổi trong cùng block, nội suy H từ trạng thái đầu đến cuối.
                    # Nếu không thay đổi, giá trị này sẽ giữ nguyên.
                    h_interp = start_H_length + (end_H_length - start_H_length) * ratio

                    # G43 bật/tắt trong cùng block: lấy trạng thái cuối cho các điểm sau khi block thực thi.
                    # Với trường hợp phổ biến G0 G43 Z... Hn, cách này tránh nhảy sai toàn bộ đoạn.
                    if start_g43_on == end_g43_on:
                        g43_interp = end_g43_on
                    else:
                        g43_interp = end_g43_on

                    slide = self.compute_slide_g53_with_comp(
                        point_wcs,
                        g43_on=g43_interp,
                        h_length=h_interp
                    )

                    slide["H_status"] = end_H_status
                    slide["tool_length_warning"] = end_tool_warning

                    trajectory_slide.append(slide)

                seg["trajectory_slide"] = trajectory_slide

                # ToolTip_G53 dùng để mở rộng toolpath / debug
                for i, point_wcs in enumerate(path_wcs):
                    tip = self.compute_tip_g53(point_wcs)

                    seg["trajectory_slide"][i].update({
                        "tip_x": tip["X"],
                        "tip_y": tip["Y"],
                        "tip_z": tip["Z"]
                    })

                seg["end_tip"] = self.compute_tip_g53()

            self._update_time(seg)
            self._check_overtravel(seg)

            ot_sum = seg.get("ot_summary", {})

            if ot_sum.get("seg_ot"):
                first = ot_sum["first_violation"]
                axes = ", ".join(ot_sum["seg_ot_axis"])
                max_v = ot_sum["max_violation"]

                print(f"🛑 [CẢNH BÁO VA CHẠM MÁY] Overtravel tại trục {axes}")
                print(f"   ► Thời điểm : {first['t']:.3f} giây")
                print(f"   ► Nguồn gốc : Dòng {first['line_number']} -> '{first['raw_line']}'")
                print(f"   ► Lượng vượt: X: {max_v['X']} | Y: {max_v['Y']} | Z: {max_v['Z']}")
                print("-" * 60)

        return segments
