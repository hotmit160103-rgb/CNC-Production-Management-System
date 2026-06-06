import pandas as pd
import plotly.graph_objects as go
from transformation import DigitalTwinTransformer

# ==========================================
# PHẦN 1: HÀM VẼ ĐỒ THỊ MÔ PHỎNG VERICUT
# ==========================================
def plot_graph_1(df, limits):
    fig = go.Figure()
    colors = {"X": "#EF553B", "Y": "#00CC96", "Z": "#636EFA"}

    for axis in ["X", "Y", "Z"]:
        # 1. Vẽ đường di chuyển của dao
        fig.add_trace(go.Scatter(
            x=df["t_sec"], y=df[axis], mode="lines", name=f"Trục {axis}",
            line=dict(color=colors[axis], width=2),
            customdata=df[["line_number", "raw_line"]],
            hovertemplate="<b>Thời gian:</b> %{x:.2f}s<br><b>Tọa độ:</b> %{y:.2f}<br><b>Dòng lệnh:</b> Dòng %{customdata[0]} (%{customdata[1]})<extra></extra>"
        ))

        # 2. Vẽ 2 vạch kẻ đứt giới hạn máy (Limit)
        l_min, l_max = limits[axis.lower()]
        fig.add_hline(y=l_max, line_dash="dash", line_color=colors[axis], opacity=0.4, annotation_text=f"Max {axis}")
        fig.add_hline(y=l_min, line_dash="dash", line_color=colors[axis], opacity=0.4, annotation_text=f"Min {axis}")

        # 3. Đánh dấu chữ X màu đỏ tại chỗ vượt giới hạn
        df_loi = df[df[f"ot_{axis.lower()}"] == True]
        if not df_loi.empty:
            fig.add_trace(go.Scatter(
                x=df_loi["t_sec"], y=df_loi[axis], mode="markers", name=f"LỖI {axis}",
                marker=dict(color="red", size=10, symbol="x"),
                customdata=df_loi[["line_number", "raw_line", f"ot_amount_{axis.lower()}"]],
                hovertemplate="<b>🚨 VƯỢT GIỚI HẠN!</b><br>Tại: %{x:.2f}s<br>Lố: %{customdata[2]:.2f} mm<br>Lệnh gốc: Dòng %{customdata[0]} (%{customdata[1]})<extra></extra>"
            ))

    fig.update_layout(title="Graph 1: Digital Twin CNC Simulation", xaxis_title="Thời gian (Giây)", yaxis_title="Tọa độ Máy (mm)", template="plotly_dark")
    fig.show()

# ==========================================
# PHẦN 2: CHẠY BÀI TEST ÉP MÁY VÀ VẼ ĐỒ THỊ
# ==========================================
def run_test():
    print("🚀 ĐANG CHẠY BÀI TEST NGHIỆM THU DIGITAL TWIN...\n")

    # 1. Cấu hình giới hạn máy cực nhỏ để test (-50 đến 50)
    config = {
        "machine_g53": {"limits": {"x": [-50, 50], "y": [-50, 50], "z": [-50, 0]}, "rapid_speed": 1000.0},
        "work_offset_g54": {"offset_vector": {"x": 0, "y": 0, "z": 0}},
        "tool_library": {"1": {"h_length": 0.0}}
    }
    
    # Kéo Cỗ máy Transformation của bạn vào
    engine = DigitalTwinTransformer(config)

    # 2. Tạo 4 dòng mã NC giả lập để "Phá máy"
    test_blocks = [
        {"line_number": 1, "raw_line": "N10 G0 X40. Y0. Z-10.", "tokens": {"G": [0], "X": 40.0, "Y": 0.0, "Z": -10.0}}, # Dòng 1: An toàn
        {"line_number": 2, "raw_line": "N20 G1 X60. F100.", "tokens": {"G": [1], "X": 60.0, "F": 100.0}},               # Dòng 2: Lỗi X
        {"line_number": 3, "raw_line": "N30 G0 X0. Y0.", "tokens": {"G": [0], "X": 0.0, "Y": 0.0}},                     # Dòng 3: Về tâm
        {"line_number": 4, "raw_line": "N40 G2 X0. Y0. I0. J40. F100.", "tokens": {"G": [2], "X": 0.0, "Y": 0.0, "I": 0.0, "J": 40.0, "F": 100.0}} # Dòng 4: Lỗi cung tròn Y
    ]

    # 3. Lọc lấy điểm và tạo Bảng dữ liệu (Schema)
    dataset = []
    for block in test_blocks:
        segments = engine.apply_block(block)
        for seg in segments:
            if seg.get("type") == "motion" and "trajectory_slide" in seg:
                for pt in seg["trajectory_slide"]:
                    dataset.append({
                        "t_sec": pt.get("t", 0.0),
                        "X": pt.get("X", 0.0), "Y": pt.get("Y", 0.0), "Z": pt.get("Z", 0.0),
                        "line_number": pt.get("line_number"), "raw_line": pt.get("raw_line"),
                        "ot_x": pt.get("ot_x", False), "ot_y": pt.get("ot_y", False), "ot_z": pt.get("ot_z", False),
                        "ot_amount_x": pt.get("ot_amount_x", 0.0), "ot_amount_y": pt.get("ot_amount_y", 0.0)
                    })

    # 4. Biến thành bảng Pandas và gọi hàm vẽ đồ thị
    df = pd.DataFrame(dataset)
    print(f"✅ Đã tạo xong bảng dữ liệu với {len(df)} điểm.")
    print("✅ Đang mở trình duyệt để xem đồ thị...")
    plot_graph_1(df, config["machine_g53"]["limits"])

if __name__ == "__main__":
    run_test()