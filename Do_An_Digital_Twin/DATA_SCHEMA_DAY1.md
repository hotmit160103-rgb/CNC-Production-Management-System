# DATA_SCHEMA_DAY1

## 1. Mục tiêu của file

File này dùng để chốt dữ liệu cốt lõi cần lấy cho 2 máy:

- EMCO_155
- HURCO_VM10I

Mục tiêu là chuẩn hóa dữ liệu để sau này web có thể chọn máy và hiển thị đúng dữ liệu theo từng máy.

---

## 2. MACHINE CONFIG


Bảng này chỉ lưu thông tin cấu hình máy. 
Không lưu cố định T1 là dao gì, T2 là dao gì, H1 dài bao nhiêu.

| machine_id | machine_name | control | x_travel_mm | y_travel_mm | z_travel_mm | rapid_x_mm_min | rapid_y_mm_min | rapid_z_mm_min | spindle_max_rpm | tool_stations | tool_id_policy | tool_setup_required | table_size_mm | max_table_load_kg | note |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| EMCO_155 | EMCO Concept Mill 155 | PC-Control / WinNC | 300 | 200 | 300 | 7500 | 7500 | 7500 | 5000 | 10 | station_mode_for_test | yes | 520 x 180 | 20 | effective Z-stroke = 200 mm |
| HURCO_VM10I | Hurco VM10i | Winmax Control | 660 | 406 | 508 | 28000 | 28000 | 28000 | 10000 | 24 | station_mode_for_test | yes | 762 x 406 | 1500 | max tool length = 250 mm, max tool weight = 7 kg |

Ghi chú:
- `tool_stations` là số vị trí dao tối đa của máy.
- `tool_id_policy = station_mode_for_test` nghĩa là trong chương trình test tuần này, tạm quy ước T1 tương ứng station 1, T2 tương ứng station 2.
- Đây là quy ước cho test đơn giản, không khẳng định mọi chương trình CNC đều dùng T-code theo station.
- Thông tin dao thật phải được đưa vào TOOL SETUP TABLE theo từng run_id.
## 3. NC PROGRAM METADATA

| column_name | required | description | example |
|---|---|---|---|
| program_id | yes | Mã chương trình test | EMCO_TEST_01 |
| machine_id | yes | Mã máy chạy chương trình | EMCO_155 |
| nc_filename | yes | Tên file NC-code | emco_test_01.nc |
| program_type | yes | Loại chương trình test | normal_test / near_limit_test |
| unit_mode | yes | Đơn vị chương trình | G20 / G21 |
| work_offset_system | yes | Hệ tọa độ phôi | G54 |
| test_purpose | yes | Mục đích test | kiểm tra XYZ, RPM, feedrate, cycle time |
| is_safe_to_run | yes | Có an toàn để chạy máy thật không | True / False |
## 4. TOOL SETUP TABLE

Bảng này dùng để mô tả dao thật theo từng lần chạy.
Không được hard-code thư viện dao cố định trong machine config.

| column_name | required | description | example |
|---|---|---|---|
| machine_id | yes | Mã máy | EMCO_155 |
| run_id | yes | Mã lần chạy | EMCO_TEST_01_RUN_01 |
| program_tool_id | yes | Mã T được trích từ NC-code | 1 |
| station_no | no | Vị trí dao trên ổ dao nếu biết | 1 |
| h_offset_id | no | Mã H được trích từ G43 H... | 1 |
| h_length_mm | no | Chiều dài bù dao thực tế | 0.0 |
| d_offset_id | no | Mã D nếu dùng G41/G42 | 1 |
| tool_name | no | Tên dao | End mill D10 |
| tool_type | no | Loại dao | end_mill / drill / face_mill / tap |
| tool_diameter_mm | no | Đường kính dao | 10.0 |
| source | yes | Nguồn dữ liệu dao | nc_code / operator_input / machine_tool_table |
| setup_status | yes | Trạng thái khai báo dao | confirmed / temporary / missing |
| note | no | Ghi chú | H_length cần lấy từ tool register |

Quy tắc:
- NC-code chỉ cho biết chương trình gọi T nào, H nào, D nào.
- Tool setup table cho biết dao đó thật sự là gì.
- Nếu thiếu tool setup table, hệ thống vẫn chạy graph nhưng phải cảnh báo `tool_setup_status = missing`.

---

## 5. SIMULATION TIME-SERIES DATASET

| column_name | required | description |
|---|---|---|
| machine_id | yes | Mã máy |
| run_id | yes | Mã lần chạy |
| data_source | yes | simulation |
| time_s | yes | Thời gian mô phỏng |
| line_number | yes | Số dòng NC-code |
| raw_line | yes | Dòng NC-code gốc |
| motion_mode | yes | G0 / G1 / G2 / G3 |
| axis_x | yes | Tọa độ trục X trong G53 |
| axis_y | yes | Tọa độ trục Y trong G53 |
| axis_z | yes | Tọa độ trục Z trong G53 |
| tip_x | yes | Tọa độ Tool Tip X |
| tip_y | yes | Tọa độ Tool Tip Y |
| tip_z | yes | Tọa độ Tool Tip Z |
| feedrate_mm_min | yes | Feedrate sau khi chuẩn hóa về mm/min |
| rpm | yes | Tốc độ trục chính |
| spindle_on | yes | Trạng thái trục chính |
| program_tool_id | yes | Mã T hiện tại được trích từ NC-code |
| h_offset_id | no | Mã H hiện tại được trích từ G43 H... |
| d_offset_id | no | Mã D hiện tại nếu có G41/G42 |
| tool_change | yes | True nếu block có M6 |
| station_no | no | Vị trí dao sau khi đối chiếu tool setup table |
| h_length_mm | no | Chiều dài bù dao lấy từ tool setup table hoặc tool register |
| tool_name | no | Tên dao nếu có khai báo |
| tool_type | no | Loại dao nếu có khai báo |
| tool_diameter_mm | no | Đường kính dao nếu có khai báo |
| tool_setup_status | yes | found / missing / temporary |
| tool_warning | yes | Cảnh báo nếu thiếu tool setup hoặc H length |
| tool_station_warning | yes | Cảnh báo nếu station_no vượt số vị trí dao của máy |
| unit_mode | yes | G20 hoặc G21 |
| ot_x | yes | Cảnh báo quá hành trình X |
| ot_y | yes | Cảnh báo quá hành trình Y |
| ot_z | yes | Cảnh báo quá hành trình Z |
| ot_amount_x | yes | Lượng vượt giới hạn X |
| ot_amount_y | yes | Lượng vượt giới hạn Y |
| ot_amount_z | yes | Lượng vượt giới hạn Z |
| unsupported_code | yes | Lệnh chưa hỗ trợ nếu có |
| rpm_limit_warning | yes | True nếu RPM vượt giới hạn spindle của máy |
| feed_limit_warning | yes | True nếu feedrate vượt giới hạn working feed của máy |
| capability_warning | yes | True nếu có bất kỳ cảnh báo capability nào |
| capability_message | yes | Nội dung cảnh báo giới hạn máy |
Ghi chú về dao:
- `program_tool_id` lấy trực tiếp từ T-code trong NC-code.
- `h_offset_id` lấy từ G43 H...
- `d_offset_id` lấy từ G41/G42 D...
- `station_no`, `h_length_mm`, `tool_name`, `tool_diameter_mm` không tự suy đoán từ NC-code.
- Các giá trị vật lý của dao phải lấy từ TOOL SETUP TABLE.

---

## 6. MACHINE OBSERVATION DATA

| column_name | required | description |
|---|---|---|
| machine_id | yes | Mã máy |
| run_id | yes | Mã lần chạy |
| data_source | yes | machine_observed |
| time_s | yes | Thời điểm ghi nhận |
| line_number | no | Dòng NC-code tương ứng nếu biết |
| machine_x | yes | Machine Coordinate X trên máy |
| machine_y | yes | Machine Coordinate Y trên máy |
| machine_z | yes | Machine Coordinate Z trên máy |
| work_x | no | Work Coordinate X |
| work_y | no | Work Coordinate Y |
| work_z | no | Work Coordinate Z |
| rpm_actual | no | RPM hiển thị trên máy |
| feed_actual | no | Feed hiển thị trên máy |
| tool_id_actual | no | Dao hiện tại |
| cycle_time_real_s | yes | Thời gian chạy thực / dry-run |
| note | no | Ghi chú |

---

## 7. VALIDATION RESULT

| column_name | required | description |
|---|---|---|
| machine_id | yes | Mã máy |
| run_id | yes | Mã lần chạy |
| line_number | yes | Dòng NC-code được đối chiếu |
| sim_x | yes | X do app tính |
| sim_y | yes | Y do app tính |
| sim_z | yes | Z do app tính |
| real_x | yes | X đọc từ máy |
| real_y | yes | Y đọc từ máy |
| real_z | yes | Z đọc từ máy |
| error_x | yes | Sai lệch X |
| error_y | yes | Sai lệch Y |
| error_z | yes | Sai lệch Z |
| error_pos | yes | Sai lệch tổng |
| cycle_time_sim_s | yes | Thời gian app tính |
| cycle_time_real_s | yes | Thời gian máy / dry-run |
| cycle_time_error_percent | yes | Sai số thời gian |
| validation_status | yes | pass / warning / fail |

---

## 8. Quy ước bắt buộc

Không dùng tên máy tự do.

Chỉ dùng đúng 2 machine_id:

- EMCO_155
- HURCO_VM10I

Tất cả dữ liệu sau này đều phải có machine_id và run_id.
## 9. Phạm vi Machine Capability Check

Hệ thống có kiểm tra giới hạn vận hành cơ bản của từng máy gồm:

- RPM vượt giới hạn spindle.
- Feedrate vượt giới hạn working feed nếu có số liệu chắc chắn.
- Tool station vượt số vị trí dao của máy nếu có station_no trong tool setup table.

Quy tắc kiểm tra tool:
- Nếu đang dùng `station_mode_for_test`, có thể kiểm tra trực tiếp T-code với số vị trí dao.
- Nếu dùng `tool_table_mode`, không được kết luận T-code vượt station chỉ bằng T number.
- Khi có TOOL SETUP TABLE, phải kiểm tra `station_no`, không kiểm tra trực tiếp `program_tool_id`.

Hệ thống không đánh giá:

- công suất cắt,
- lực cắt,
- tải trục chính,
- rung động,
- tối ưu chế độ cắt.

## 10. Kết luận về Tool Data

Trong đề tài này, dữ liệu dao được tách thành 3 lớp:

1. NC-code layer:
   - Trích xuất T-code, H-code, D-code, M6.
   - Không tự suy đoán loại dao, chiều dài dao hoặc đường kính dao.

2. Machine config layer:
   - Chỉ lưu khả năng hệ dao của máy, ví dụ số vị trí dao.
   - EMCO_155 có 10 vị trí dao.
   - HURCO_VM10I có 24 vị trí dao.

3. Tool setup layer:
   - Lưu thông tin dao thật theo từng run_id.
   - Bao gồm station_no, h_length_mm, tool_name, tool_type, tool_diameter_mm.
   - Đây là nguồn dữ liệu chính để xác nhận dao trong từng chương trình test.

Câu chốt:
NC-code cho biết chương trình gọi dao nào.
Tool setup table cho biết dao đó thật sự là gì và nằm ở đâu.
Machine config cho biết máy chứa tối đa bao nhiêu dao.