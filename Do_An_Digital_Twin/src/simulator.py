import numpy as np

class Simulator:
    def __init__(self, engine, config):
        self.engine = engine
        self.config = config
        self.current_time = 0.0
        self.logs = []

    def calculate_step(self, cmd, raw_line, line_num):
        prev_axis = self.engine.state["axis_pos"].copy()
        new_axis = prev_axis.copy()
        
        # 1. Update Axis Position (Machine Slide)
        moved = False
        for axis in ['X', 'Y', 'Z']:
            if axis in cmd:
                if self.engine.state["dist_mode"] == "G90":
                    new_axis[axis] = cmd[axis]
                else:
                    new_axis[axis] += cmd[axis]
                moved = True

        # 2. Machining Time Calculation (Linear Model)
        dt = 0.0
        if moved:
            dist = np.sqrt(sum((new_axis[k] - prev_axis[k])**2 for k in 'XYZ'))
            if self.engine.state["motion_mode"] == "G0":
                speed = self.config['machine_g53']['rapid_speed']
            else:
                speed = self.engine.state["feedrate"]
            
            if speed > 0:
                dt = (dist / speed) * 60 # Chuyển inch/min hoặc mm/min sang giây
        
        # 3. Add Constant Times (M6, M3)
        if 'M' in cmd:
            if cmd['M'] == 6: dt += self.config['machine_g53']['tool_change_time']
            if cmd['M'] == 3: dt += self.config['machine_g53']['spindle_start_time']

        self.current_time += dt
        self.engine.state["axis_pos"] = new_axis

        # 4. Logic Tọa độ & Kiểm tra Overtravel chi tiết
        limits = self.config['machine_g53']['limits']
        ot_status = {}
        ot_amounts = {}

        for ax in ['X', 'Y', 'Z']:
            val = new_axis[ax]
            l_min, l_max = limits[ax.lower()]
            
            # Kiểm tra trạng thái vi phạm
            is_violated = not (l_min <= val <= l_max)
            ot_status[f'ot_{ax.lower()}'] = is_violated
            
            # Tính lượng vượt hành trình (Amount)
            if val > l_max:
                amount = val - l_max
            elif val < l_min:
                amount = val - l_min
            else:
                amount = 0.0
            ot_amounts[f'ot_amount_{ax.lower()}'] = amount

        # Tính World Tip Position (Dùng offset G54)
        offset = self.config['work_offset_g54']['offset_vector']
        world_tip = {
            'X': new_axis['X'] + offset['x'],
            'Y': new_axis['Y'] + offset['y'],
            'Z': new_axis['Z'] + offset['z'] - self.engine.state["h_length"]
        }

        # 5. Logging (Time-series mở rộng cho Graph 1 mới)
        self.logs.append({
            "time": self.current_time,
            "line_number": line_num,
            "raw_line": raw_line,
            "tool_id": self.engine.state["tool_id"],
            "motion_mode": self.engine.state["motion_mode"],
            
            # Tọa độ Slide máy (Trục Y của Graph 1)
            "axis_x": new_axis['X'], 
            "axis_y": new_axis['Y'], 
            "axis_z": new_axis['Z'],
            
            # Trạng thái lỗi 3 trục (Dùng để highlight màu đỏ trên Graph)
            "ot_x": ot_status['ot_x'],
            "ot_y": ot_status['ot_y'],
            "ot_z": ot_status['ot_z'],
            
            # Lượng vượt (Dùng để hiển thị trong Tooltip)
            "ot_amount_x": ot_amounts['ot_amount_x'],
            "ot_amount_y": ot_amounts['ot_amount_y'],
            "ot_amount_z": ot_amounts['ot_amount_z'],
            
            # Tọa độ đầu dao (Dùng để hiển thị trong Tooltip)
            "tip_x": world_tip['X'], 
            "tip_y": world_tip['Y'], 
            "tip_z": world_tip['Z'],
            
            # Các thông số phụ khác
            "feedrate": self.engine.state["feedrate"],
            "rpm": self.engine.state["spindle_rpm"],
            "spindle_on": self.engine.state["spindle_on"]
        })