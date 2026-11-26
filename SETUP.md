# Cài đặt và chạy

Hướng dẫn từ đầu đến khi dùng được nút **QC** trong CVAT. Các lệnh dùng PowerShell trên Windows; trên Linux/macOS thay
`\` bằng `/` và bỏ phần `.ps1`.

## 1. Yêu cầu

| Thành phần | Bắt buộc? | Ghi chú |
|---|---|---|
| Python 3.10+ (đã thử 3.11) | Có | |
| `numpy` | Có | `pip install -r requirements.txt` |
| Chrome hoặc Edge (Manifest V3) | Để dùng extension | Đã thử: Chrome (đầy đủ), Edge (nạp và kết nối) |
| CVAT chạy local (Docker) | Để dùng trong CVAT | Đã thử bản **2.81.1** tại `http://localhost:8080` |
| Node.js 18+ | Chỉ để chạy test JS | `node --test` |
| nuScenes Mini | Tùy chọn | Để tạo demo và đánh giá; xem mục 5 |

```powershell
git clone https://github.com/vuomg/cvat-lidar-3d-cuboid-annotation-qc.git
cd cvat-lidar-3d-cuboid-annotation-qc
pip install -r requirements.txt
python -W error::ResourceWarning -m unittest discover -s tests     # kỳ vọng: OK (bỏ qua test cần dữ liệu demo nếu chưa tạo)
```

## 2. Chỉ chạy QC (không cần CVAT)

```powershell
python -m cuboidqc.core.qc --dataroot <thư mục nuScenes> --version v1.0-mini --out data\report.csv
```
In tóm tắt số cờ theo loại và ghi `data\report.csv`. Cần cả point cloud (`samples\LIDAR_TOP`) để chạy checker `BOX_OFFSET`;
thêm `--no-points` để bỏ checker này. Viewer HTML để xem từng lỗi:
```powershell
python -m cuboidqc.viewer.build --dataroot <thư mục nuScenes> --report data\report.csv
```
rồi mở `data\viewer.html` bằng trình duyệt.

## 3. Dùng trong CVAT bằng extension

### 3.1 Chạy server QC
```powershell
python scripts\run_server.py
```
Server lắng nghe `127.0.0.1:8766` và in **token**. Token được lưu trong `.qc_token` (cùng thư mục repo) nên các lần chạy sau
**giữ nguyên**, bạn chỉ phải dán một lần. Giữ cửa sổ này mở khi dùng extension.

Tùy chọn hữu ích (mọi tham số xem `python scripts\run_server.py --help`):

| Tham số | Việc làm |
|---|---|
| `--meta <meta.json>` | Cho ego pose theo tên frame để kiểm tra hướng ngược (demo có sẵn `data\demo_data\meta.json`) |
| `--coords global` | Nếu nhãn và point cloud đã ở tọa độ global (kèm `--frame-dt` giây giữa hai frame) |
| `--profile <file>` | Dùng profile riêng thay cho `configs\profile.json` |
| `--port` | Đổi cổng (khi đó nhớ sửa địa chỉ trong Tùy chọn của extension) |

### 3.2 Nạp extension
1. Mở `chrome://extensions` (Chrome) hoặc `edge://extensions` (Edge).
2. Bật **Developer mode**.
3. Bấm **Load unpacked** và chọn thư mục **`extension`** của repo (thư mục chứa `manifest.json`, không phải thư mục gốc repo).
4. Ở thẻ extension chọn **Details → Extension options**, điền:
   - **Địa chỉ server:** `http://127.0.0.1:8766`
   - **Token:** nội dung file `.qc_token` (hoặc token server đã in)
5. Bấm **Kiểm tra kết nối**: phải thấy "Kết nối tốt". "TOKEN SAI" nghĩa là token chưa khớp.

Khi sửa mã extension: bấm **Reload** ở thẻ extension rồi **F5** trang CVAT.

### 3.3 Chuẩn bị project CVAT
Để **ghi** cờ và gợi ý vào job, project cần:
- label `QC_SUGGESTION` (loại cuboid) có ba attribute dạng text: `issue`, `target`, `note`;
- mỗi label đối tượng có hai attribute dạng text: `qc_issue`, `qc_note`.

Thiếu thì extension vẫn **hiện lỗi** nhưng tắt nút ghi và nêu rõ còn thiếu gì. Extension không tự sửa cấu hình project.
Muốn có project mẫu đã đủ, làm mục 5.

### 3.4 Dùng
Mở một job 3D (ví dụ `http://localhost:8080/tasks/<task>/jobs/<job>`). Góc dưới trái có nút tròn **QC**.
- **Chạy QC**: đọc job, nạp point cloud lần đầu (vài giây), hiện danh sách lỗi. Chỉ đọc, không ghi gì.
- Bấm một lỗi: nhảy tới frame đó trong trang. Nút **chọn** mở đúng đối tượng (trang tải lại, CVAT lọc chỉ còn đối tượng đó).
- **Ghi cờ & gợi ý vào job**: có hộp xác nhận. **Lưu (Ctrl+S) mọi thay đổi trong CVAT trước**.
- **Tự sửa (xem trước)**: tính trước phần tự sửa theo chính sách `conservative`.

## 4. Kiểm tra cài đặt thành công
| Việc | Kết quả đúng |
|---|---|
| Trang Tùy chọn → Kiểm tra kết nối | "Kết nối tốt. Server QC phiên bản …" |
| Mở job CVAT | Có nút tròn **QC** (không có chữ "null") |
| Chạy QC trên job demo | "1142 cuboid, 22 bị cờ" (hoặc 27 nếu chưa chạy `apply`), không có cảnh báo |
| Cửa sổ server | Có dòng `PUT /frames/…` và `POST /qc … 200` |

## 5. Demo đầy đủ trên CVAT với nuScenes

Cần nuScenes Mini (tải từ trang nuScenes, giải nén, xem điều khoản phi thương mại của họ) và CVAT local.

```powershell
# thống kê tham chiếu (đã có sẵn configs\profile.json; chỉ cần chạy lại nếu muốn tính lại)
python -m cuboidqc.core.qcprofile --dataroot <nuScenes> --out configs\profile.json
# dựng dữ liệu demo: 41 frame .pcd + nhãn + 9 lỗi chèn có sổ ghi
python -m cuboidqc.cvat.demo --dataroot <nuScenes> --scene scene-0553
# lưu đăng nhập CVAT (mã hóa bằng Windows DPAPI, một lần; bỏ qua thì script sẽ hỏi mỗi lần)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\save_login.ps1
# tạo project / task / job demo trên CVAT, rồi chạy QC
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1 -Step setup -Recreate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1 -Step qc
```
Các bước của `demo.ps1`: `setup`, `calib` (task hiệu chỉnh trục), `dryrun`, `qc`, `apply`; gộp được: `-Step qc,apply,qc`.
Log ở `data\logs\`. Thông tin đăng nhập chỉ qua biến môi trường hoặc ô nhập ẩn, **không ghi ra file** (trừ file mã hóa
`.cvat_login.xml` nếu bạn chạy `save_login.ps1`; file này nằm trong `.gitignore`).

`-Recreate` **xóa project `cuboid-qc-demo` rồi tạo lại**; project nào khác của bạn không bị đụng.

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp và cách xử lý |
|---|---|
| Không thấy nút **QC** | Chưa **Reload** extension / chưa **F5** trang; hoặc không ở trang job (`/tasks/N/jobs/M`). CVAT là ứng dụng một trang nên đợi khoảng một giây |
| Nút hiện chữ `QCnull`, bảng có "nullnull" | Đang dùng bản extension cũ: **Reload** extension rồi **Ctrl+F5** |
| "Không kết nối được server QC" | Chưa chạy `scripts\run_server.py`, hoặc sai cổng trong Tùy chọn |
| "TOKEN SAI" | Token trong Tùy chọn khác nội dung `.qc_token` |
| "Extension vừa được nạp lại…" | Sau khi Reload extension, trang đang mở phải tải lại (F5) |
| Cảnh báo "Khong co ego pose…" | Dữ liệu thô không có ego pose: chạy server với `--meta` hoặc `--coords global`; không thì bỏ qua kiểm tra hướng |
| Cảnh báo thiếu label / attribute | Project chưa có `QC_SUGGESTION` và `qc_issue`/`qc_note`: xem 3.3 |
| Bấm "Ghi…" báo lỗi 403 | CVAT từ chối CSRF hoặc phiên đã hết hạn: đăng nhập lại CVAT, tải lại trang |
| Test báo thiếu `data\demo_data` | Test đó cần dữ liệu demo (mục 5); các test khác vẫn chạy |

## 7. Gỡ cài đặt
- Extension: **Remove** ở trang quản lý extension.
- Dữ liệu sinh ra: xóa thư mục `data\`. File `.qc_token` và `.cvat_login.xml` chứa thông tin riêng của máy bạn, xóa khi không dùng.
- Project demo trên CVAT: xóa `cuboid-qc-demo` trong giao diện CVAT.
