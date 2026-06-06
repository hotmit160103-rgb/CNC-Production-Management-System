import re
import json
import os
import pandas as pd
from transformation import DigitalTwinTransformer

class NCCodeChecker:
    def __init__(self, nc_file_path, config_path):
        self.nc_file_path = nc_file_path
        with open(config_path, "r") as f:
            self.config = json.load(f)
        self.transformer = DigitalTwinTransformer(self.config)

    def parse_block(self, line, line_num):
        """Bóc tách 1 dòng NC thành Dictionary chuẩn."""
        clean_line = re.sub(r"\(.*?\)", "", line)
        clean_line = re.sub(r";.*", "", clean_line).strip().upper()
        
        if not clean_line or clean_line == "%":
            return None

        tokens = {}
        n_match = re.search(r"N(\d+)", clean_line)
        if n_match: tokens["N"] = int(n_match.group(1))

        for g in re.findall(r"G(\d+)", clean_line): tokens.setdefault("G", []).append(int(g))
        for m in re.findall(r"M(\d+)", clean_line): tokens.setdefault("M", []).append(int(m))

        for letter in ["T", "H", "D", "S"]:
            match = re.search(f"{letter}(\\d+)", clean_line)
            if match: tokens[letter] = int(match.group(1))

        for param in ["X", "Y", "Z", "I", "J", "K", "R", "F"]:
            match = re.search(f"{param}([-+]?\\d*\\.?\\d+)", clean_line)
            if match: tokens[param] = float(match.group(1))

        if not tokens: return None

        return {
            "line_number": line_num,
            "raw_line": line.rstrip('\n'),
            "tokens": tokens
        }

    def run_inspection(self):
        """Hàm chạy quét toàn bộ file và xuất ra Schema Dataset chuẩn (Pandas DataFrame)"""
        if not os.path.exists(self.nc_file_path):
            print(f"Lỗi: Không tìm thấy file {self.nc_file_path}")
            return None

        # 1. KHỞI TẠO DANH SÁCH RỖNG ĐỂ CHỨA CÁC ĐIỂM (SCHEMA)
        dataset = []

        print("Đang phân tích và nội suy quỹ đạo...")
        with open(self.nc_file_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                raw = line.strip()
                if not raw: continue

                block = self.parse_block(raw, line_num)
                if not block: continue

                # 2. Đưa qua Transformer để lấy Segments (đã nội suy toán học và thời gian)
                segments = self.transformer.apply_block(block)

                # 3. ÉP PHẲNG DỮ LIỆU (FLATTEN TO SCHEMA)
                for seg in segments:
                    if seg.get("type") == "motion" and "trajectory_slide" in seg:
                        # Lấy metadata chung của cả đoạn
                        line_nc = seg.get("line_number", block["line_number"])
                        raw_nc = seg.get("raw_line", block["raw_line"])
                        is_air = seg.get("is_air_time", False)
                        tool_id = self.transformer.state.get("active_tool_id", "None")

                        # Quét qua từng điểm nhỏ (Sample point)
                        for pt in seg["trajectory_slide"]:
                            # 4. TẠO 1 HÀNG (ROW) CHUẨN
                            row = {
                                "t_sec": pt.get("t", 0.0),
                                "X": pt.get("X", 0.0),
                                "Y": pt.get("Y", 0.0),
                                "Z": pt.get("Z", 0.0),
                                "line_number": line_nc,
                                "raw_line": raw_nc,
                                "tool_id": tool_id,
                                "status": "Air Move (G0)" if is_air else "Cutting (G1/2/3)"
                            }
                            dataset.append(row)

        # 5. CHUYỂN ĐỔI THÀNH PANDAS DATAFRAME ĐỂ DỄ VẼ ĐỒ THỊ VÀ XUẤT CSV
        df = pd.DataFrame(dataset)
        
        print(f"✅ Hoàn thành! Đã băm được tổng cộng {len(df)} điểm quỹ đạo.")
        return df


def main():
    checker = NCCodeChecker(
        nc_file_path="input_post1.nc", # Thay bằng file NC thực tế của bạn
        config_path="config.json"
    )
    
    # Lấy DataFrame chứa toàn bộ dataset
    df_trajectory = checker.run_inspection()
    
    if df_trajectory is not None and not df_trajectory.empty:
        # In ra 10 điểm đầu tiên để xem Schema đã đẹp chưa
        print("\n=== XEM TRƯỚC 10 DÒNG CỦA DATASET CHUẨN ===")
        print(df_trajectory.head(10).to_string(index=False))
        
        # Bạn có thể xuất ra file CSV để kiểm tra bằng Excel:
        # df_trajectory.to_csv("trajectory_log.csv", index=False)

if __name__ == "__main__":
    main()

import pandas as pd

class SimulationLogger:
    def __init__(self):
        self.dataset = [] # Cái rổ chứa toàn bộ các hàng (rows)

    def log_segments(self, segments, current_state):
        """Hàm này nhận kết quả từ transformer và nén thành từng Hàng (Row)"""
        for seg in segments:
            base_row = {
                "line_number": seg.get("line_number"),
                "raw_line": seg.get("raw_line"),
                "tool_id": current_state.get("active_tool_id"),
                "feedrate": current_state.get("feedrate"),
                "is_air_time": seg.get("is_air_time", False)
            }

            if seg["type"] == "motion":
                base_row["motion_mode"] = f"G{seg.get('motion_mode')}"
                base_row["event_type"] = "None"
                
                # Quét qua từng điểm (point) trong quỹ đạo
                for pt in seg.get("trajectory_slide", []):
                    row = base_row.copy()
                    row.update({
                        "timestamp_sec": pt.get("t"),
                        "axis_x": pt.get("X"),
                        "axis_y": pt.get("Y"),
                        "axis_z": pt.get("Z"),
                        "ot_x": pt.get("ot_x", False),
                        "ot_y": pt.get("ot_y", False),
                        "ot_z": pt.get("ot_z", False),
                        "ot_amount_x": pt.get("ot_amount_x", 0.0),
                        # ... (Thêm Y, Z tương tự)
                    })
                    self.dataset.append(row)

            elif seg["type"] == "event":
                base_row["motion_mode"] = "Event"
                base_row["event_type"] = seg.get("event_type")
                
                # Event đứng im: Cần 2 điểm (Start và End) để vẽ đường đi ngang
                pos = current_state["programmed_wcs_pos"] # Giả sử đang đứng ở đây (Cần lấy G53 thật)
                
                # Điểm 1 (Bắt đầu)
                row_start = base_row.copy()
                row_start.update({"timestamp_sec": seg["start_time"], "axis_x": pos["X"], "axis_y": pos["Y"], "axis_z": pos["Z"]})
                
                # Điểm 2 (Kết thúc)
                row_end = base_row.copy()
                row_end.update({"timestamp_sec": seg["end_time"], "axis_x": pos["X"], "axis_y": pos["Y"], "axis_z": pos["Z"]})
                
                self.dataset.append(row_start)
                self.dataset.append(row_end)

    def export_dataframe(self):
        df = pd.DataFrame(self.dataset)
        # Sắp xếp lại một lần nữa để đảm bảo thời gian không bị ngược
        if not df.empty:
            df = df.sort_values(by="timestamp_sec").reset_index(drop=True)
        return df

import pandas as pd
from transformation import DigitalTwinTransformer
# Giả sử class SimulationLogger đã được đặt ở trên trong file này
# =========================================================
# HÀM NGHIỆM THU DATASET (DÁN VÀO NGAY TRÊN DEF MAIN)
# =========================================================
def run_checkpoint_tests(df):
    print("\n" + "="*50)
    print("🔬 BẮT ĐẦU NGHIỆM THU DATASET (CHECKPOINT TESTS)")
    print("="*50)

    if df is None or df.empty:
        print("❌ THẤT BẠI: Bảng dữ liệu trống trơn!")
        return

    # TEST 1: SỨC KHỎE CHUNG CỦA BẢNG
    print("\n👉 TEST 1: Kiểm tra 5 dòng đầu tiên (Data Sanity)")
    cols_to_show = ['timestamp_sec', 'line_number', 'raw_line', 'motion_mode', 'axis_x', 'ot_x']
    # Dùng try-except để tránh lỗi nếu các cột chưa được logger tạo ra đúng tên
    try:
        print(df[cols_to_show].head(5).to_string(index=False))
    except KeyError as e:
        print(f"⚠️ Cảnh báo: Thiếu cột {e} trong Dataset. Hãy kiểm tra lại Logger.")

    # TEST 2: KIỂM TRA M6
    print("\n👉 TEST 2: Kiểm tra Event M6")
    if 'event_type' in df.columns:
        df_m6 = df[df['event_type'] == 'M6']
        if len(df_m6) >= 2:
            print(f"✅ THÀNH CÔNG: Đã ghi nhận điểm dừng thay dao M6.")
        elif len(df_m6) > 0:
            print(f"❌ THẤT BẠI: M6 tạo ra số lượng điểm không đúng: {len(df_m6)}")
        else:
            print("⚠️ Bỏ qua: Không tìm thấy sự kiện M6 nào trong kịch bản test này.")
    else:
         print("⚠️ Cảnh báo: Thiếu cột 'event_type'.")

    # TEST 3: KIỂM TRA BẮT LỖI OVERTRAVEL
    print("\n👉 TEST 3: Kiểm tra bắt lỗi Overtravel")
    if 'ot_x' in df.columns:
        df_loi = df[df['ot_x'] == True]
        if not df_loi.empty:
            print(f"✅ THÀNH CÔNG: Phát hiện được {len(df_loi)} điểm vượt giới hạn trục X!")
            diem_loi = df_loi.iloc[0]
            print(f"   Lỗi bắt đầu tại giây : {diem_loi['timestamp_sec']:.2f}s")
            print(f"   Thuộc dòng lệnh      : {diem_loi['raw_line']}")
            print(f"   Tọa độ lúc lỗi       : X = {diem_loi['axis_x']}")
        else:
            print("⚠️ Bỏ qua: Không có lỗi trục X nào (hoặc hệ thống chưa bắt được).")
    else:
        print("⚠️ Cảnh báo: Thiếu cột cờ lỗi 'ot_x'.")

    print("\n" + "="*50)

def main():
    print("🚀 KHỞI ĐỘNG HỆ THỐNG DIGITAL TWIN...")

    # 1. Cấu hình hệ thống (Ví dụ giới hạn X từ -50 đến 50)
    config = {
        "machine_g53": {
            "limits": {"x": [-50, 50], "y": [-50, 50], "z": [-50, 0]},
            "rapid_speed": 1000.0,
            "tool_change_time": 4.0 # Thời gian thay dao mất 4 giây
        },
        "work_offset_g54": {"offset_vector": {"x": 0, "y": 0, "z": 0}},
        "tool_library": {"1": {"h_length": 0.0}, "6": {"h_length": 0.0}}
    }
    
    # 2. KHỞI TẠO "MÁY GIA CÔNG" VÀ "NGƯỜI GHI CHÉP" (Để ngoài vòng lặp)
    transformer = DigitalTwinTransformer(config)
    logger = SimulationLogger()

    # 3. Kịch bản test (Thay thế cho việc đọc file input.nc)
    test_blocks = [
        {"line_number": 1, "raw_line": "N10 G0 X10. Y0. Z-10.", "tokens": {"G": [0], "X": 10.0, "Y": 0.0, "Z": -10.0}},
        {"line_number": 2, "raw_line": "N20 M6 T6", "tokens": {"M": [6], "T": 6}}, # Đổi dao M6
        {"line_number": 3, "raw_line": "N30 G1 X60. F100.", "tokens": {"G": [1], "X": 60.0, "F": 100.0}}, # Cố tình chạy lố X = 60
    ]

    # 4. VÒNG LẶP DÂY CHUYỀN
    for block in test_blocks:
        # Máy gia công tính toán ra các segments
        segments = transformer.apply_block(block)
        
        # Người ghi chép chép ngay các segments đó vào sổ (Cần đưa thêm current_state để biết dao và feedrate)
        logger.log_segments(segments, transformer.state)

    # 5. KẾT THÚC DÂY CHUYỀN: Xuất sổ ghi chép ra thành Bảng (DataFrame)
    df_final = logger.export_dataframe()
    
    print(f"✅ Đã tạo xong Dataset với {len(df_final)} điểm.")
    
    # GỌI HÀM TEST NGHIỆM THU Ở ĐÂY (Sẽ hướng dẫn ở Phần 2)
    run_checkpoint_tests(df_final)

if __name__ == "__main__":
    main()    

def run_checkpoint_tests(df):
    print("\n" + "="*50)
    print("🔬 BẮT ĐẦU NGHIỆM THU DATASET (CHECKPOINT TESTS)")
    print("="*50)

    # Nếu bảng rỗng thì báo lỗi ngay
    if df is None or df.empty:
        print("❌ THẤT BẠI: Bảng dữ liệu trống trơn!")
        return

    # ---------------------------------------------------------
    # TEST 1: SỨC KHỎE CHUNG CỦA BẢNG (In 5 dòng đầu)
    # ---------------------------------------------------------
    print("\n👉 TEST 1: Kiểm tra 5 dòng đầu tiên (Data Sanity)")
    # Chỉ chọn vài cột quan trọng để in cho đỡ rối mắt
    cols_to_show = ['timestamp_sec', 'line_number', 'raw_line', 'motion_mode', 'axis_x', 'ot_x']
    print(df[cols_to_show].head(5).to_string(index=False))
    # -> Kiểm tra bằng mắt: timestamp_sec có bắt đầu từ 0 không? raw_line có đúng không?

    # ---------------------------------------------------------
    # TEST 2: KIỂM TRA SỰ KIỆN ĐỔI DAO (M6)
    # ---------------------------------------------------------
    print("\n👉 TEST 2: Kiểm tra Event M6 (Dòng số 2)")
    df_m6 = df[df['event_type'] == 'M6']
    
    if len(df_m6) == 2:
        start_time = df_m6.iloc[0]['timestamp_sec']
        end_time = df_m6.iloc[1]['timestamp_sec']
        duration = end_time - start_time
        print(f"✅ THÀNH CÔNG: M6 tạo ra đúng 2 điểm. Bắt đầu: {start_time}s, Kết thúc: {end_time}s.")
        print(f"   Thời gian thay dao mất đúng: {duration} giây.")
    else:
        print(f"❌ THẤT BẠI: M6 đang tạo ra {len(df_m6)} điểm (Bắt buộc phải là 2 điểm).")

    # ---------------------------------------------------------
    # TEST 3: KIỂM TRA BẮT LỖI OVERTRAVEL (Dòng số 3)
    # ---------------------------------------------------------
    print("\n👉 TEST 3: Kiểm tra bắt lỗi Overtravel (Chạy lố X=60)")
    # Lọc ra những hàng có cờ ot_x = True
    df_loi = df[df['ot_x'] == True]
    
    if not df_loi.empty:
        print(f"✅ THÀNH CÔNG: Phát hiện được {len(df_loi)} điểm vượt giới hạn trục X!")
        # Lấy điểm đầu tiên bị lỗi ra xem thử
        diem_loi = df_loi.iloc[0]
        print(f"   Lỗi bắt đầu tại giây : {diem_loi['timestamp_sec']:.2f}s")
        print(f"   Thuộc dòng lệnh      : {diem_loi['raw_line']}")
        print(f"   Tọa độ lúc lỗi       : X = {diem_loi['axis_x']}")
        print(f"   Lượng vượt quá (Max 50): {diem_loi['ot_amount_x']} mm")
    else:
        print("❌ THẤT BẠI: Dòng số 3 chạy tới X=60 nhưng hệ thống không bắt được lỗi!")

    print("\n" + "="*50)