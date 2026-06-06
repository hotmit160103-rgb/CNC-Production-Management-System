import re

class GCodeEngine:
    def __init__(self, config):
        self.config = config
        # Initial Modal State
        self.state = {
            "motion_mode": "G0",   # G0, G1, G2, G3
            "dist_mode": "G90",    # G90 (Abs), G91 (Inc)
            "feedrate": 0.0,
            "spindle_rpm": 0.0,
            "spindle_on": False,
            "tool_id": "0",
            "h_length": 0.0,
            "g43_active": False,
            "axis_pos": {"X": 0.0, "Y": 0.0, "Z": 0.0}
        }

    def parse_line(self, line):
        """
        Parse 1 dòng NC-code thành tokens chuẩn:
        - G, M là list vì 1 dòng có thể có nhiều G/M.
        - T, H, D, N là int.
        - X, Y, Z, I, J, K, R, F, S là float.
        """
        clean_line = re.sub(r'\(.*?\)', '', line)
        clean_line = clean_line.split(';')[0].strip().upper()

        if not clean_line or clean_line == "%":
            return None

        # Bắt được: 100, 100., .375, -0.1875, -1, +2.5
        number_pattern = r'[-+]?(?:\d+\.\d*|\.\d+|\d+)'
        tokens = re.findall(rf'([A-Z])({number_pattern})', clean_line)

        supported_letters = {
            "N", "G", "M",
            "X", "Y", "Z",
            "I", "J", "K", "R",
            "F", "S", "T", "H", "D"
        }

        cmd = {"G": [], "M": []}

        for letter, value in tokens:
            if letter not in supported_letters:
                continue

            if letter in ["G", "M"]:
                cmd[letter].append(int(float(value)))
            elif letter in ["N", "T", "H", "D"]:
                cmd[letter] = int(float(value))
            else:
                cmd[letter] = float(value)

        if not cmd["G"]:
            del cmd["G"]
        if not cmd["M"]:
            del cmd["M"]

        if not cmd:
            return None

        # Chỉ giữ state parser để debug; transformer mới là nơi xử lý chính.
        if "G" in cmd:
            for g_val in cmd["G"]:
                if g_val in [0, 1, 2, 3]:
                    self.state["motion_mode"] = f"G{g_val}"
                if g_val in [90, 91]:
                    self.state["dist_mode"] = f"G{g_val}"
                if g_val == 43:
                    self.state["g43_active"] = True
                if g_val == 49:
                    self.state["g43_active"] = False

        if "F" in cmd:
            self.state["feedrate"] = cmd["F"]
        if "S" in cmd:
            self.state["spindle_rpm"] = cmd["S"]
        if "T" in cmd:
            self.state["tool_id"] = str(cmd["T"])

        if "M" in cmd:
            for m_val in cmd["M"]:
                if m_val in [3, 4]:
                    self.state["spindle_on"] = True
                if m_val == 5:
                    self.state["spindle_on"] = False

        if self.state["g43_active"] and "H" in cmd:
            h_id = str(cmd["H"])
            self.state["h_length"] = self.config["tool_library"].get(h_id, {}).get("h_length", 0.0)

        return cmd

if __name__ == "__main__":
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    e = GCodeEngine(config)

    tests = [
        "G1 X-1 Y2 Z0. F100.",
        "G0 G17 G90 G94 G20 G40 G49 G80",
        "G0 G90 G54 X-0.1875 Y-0.375 S100 M3",
        "G43 Z1.5 H25 M8",
        "G3 X7.73 Y-1.185 I0. J-0.25"
    ]

    for t in tests:
        print(t, "=>", e.parse_line(t))        