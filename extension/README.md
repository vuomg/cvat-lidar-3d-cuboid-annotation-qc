# Extension "Cuboid QC cho CVAT"

Nút **QC** ngay trong trang job CVAT 3D: kiểm tra chất lượng cuboid, xem danh sách lỗi, nhảy tới đối tượng, ghi cờ và
gợi ý sửa vào job. Gồm hai phần:

```
Trang CVAT (extension)  ──nhãn + point cloud──►  server QC (máy bạn, 127.0.0.1)
   đọc/ghi bằng phiên đăng nhập của bạn  ◄── lỗi + kế hoạch ghi ──  chạy 5 checker
```

- **Extension** đọc nhãn và point cloud của job bằng **phiên đăng nhập sẵn có trong trình duyệt** (không cần mật khẩu hay
  token CVAT), gửi sang server local, và tự ghi kết quả ngược vào CVAT.
- **Server** (`cuboidqc/server/app.py`, chạy bằng `scripts/run_server.py`) chỉ tính toán. Không có thông tin đăng nhập CVAT.

## Cài đặt
1. Chạy server (trong thư mục dự án):
   ```powershell
   python scripts
un_server.py --meta data\demo_data\meta.json
   ```
   Server in ra **token**. `--meta` là tùy chọn (ego pose để kiểm tra hướng ngược; xem "Giới hạn").
2. Mở `chrome://extensions` (hoặc `edge://extensions`), bật **Developer mode**, bấm **Load unpacked**, chọn thư mục `extension`.
3. Mở **Tùy chọn** của extension, dán token, bấm **Kiểm tra kết nối**.
4. Mở một job CVAT 3D: góc dưới trái có nút tròn **QC**.

Extension chạy trên `http://localhost/*`, `http://127.0.0.1/*`, `https://cvat.edufun.ai/*`, `https://app.cvat.ai/*`
(giống `cvat-pointcloud-tweaker`). Muốn thêm domain, sửa `content_scripts.matches` trong `manifest.json`.

## Sử dụng
| Nút | Việc làm |
|---|---|
| **Chạy QC** | Đọc job, nạp point cloud (lần đầu; sau đó dùng cache của server), chạy kiểm tra, hiện danh sách lỗi. Chỉ đọc, không ghi gì. |
| Danh sách lỗi | **Nhóm theo frame** ("Frame 2 — 2 lỗi"); mỗi lỗi có huy hiệu **#23** là **ID đối tượng hiển thị ở danh sách bên phải của CVAT**, kèm vị trí `x, y` và khoảng cách tới xe |
| Bấm vào một lỗi | Nhảy tới **frame** đó, rồi **cuộn danh sách bên phải của CVAT tới đúng đối tượng và chọn nó** (khung Top/Side/Front hiện box đó). Không tải lại trang, kết quả QC còn nguyên. Bấm tiêu đề "Frame N" để chỉ nhảy frame |
| **Ghi cờ & gợi ý vào job** | Đặt thuộc tính `qc_issue` / `qc_note` lên cuboid bị cờ và tạo cuboid xanh `QC_SUGGESTION` tại vị trí gợi ý. Có hộp xác nhận. Tải lại trang sau khi ghi. |
| **Tự sửa (xem trước)** | Tính trước những gì sẽ tự sửa (chính sách `conservative`: lật hướng khi ERROR, sửa kích thước theo track). Sau đó nút ghi đổi thành "Ghi thay đổi tự sửa vào job". |

**Hãy lưu (Ctrl+S) mọi thay đổi chưa lưu trước khi ghi**: extension đọc nhãn từ server CVAT, không thấy phần chưa lưu, và trang tải lại sau khi ghi.

## Yêu cầu về project CVAT
Để **ghi** được, project cần có:
- label `QC_SUGGESTION` (loại cuboid) với attribute dạng text: `issue`, `target`, `note`;
- mỗi label đối tượng có attribute dạng text `qc_issue`, `qc_note`.

Thiếu thì extension vẫn **hiện lỗi** nhưng tắt nút ghi và nêu rõ còn thiếu gì. Project demo (`cuboid-qc-demo`) đã có sẵn (do `cvat_setup.py` tạo).
Extension **không** tự sửa cấu hình label của project.

## Bảo mật
- Server chỉ lắng nghe `127.0.0.1` và **yêu cầu token** (`X-QC-Token`). Không bật CORS nên trang web khác không đọc được phản hồi.
- Service worker chỉ cho phép gọi `/health`, `/frames`, `/qc` của server QC; content script không gọi được URL tùy ý.
- Extension không lưu hay gửi mật khẩu/token CVAT. Token của server QC lưu trong `chrome.storage.local`.
- `--allow-origin` của server chỉ dành cho thử nghiệm; extension không cần.

## Giới hạn đã biết
- **Kiểm tra hướng ngược cần ego pose.** Dữ liệu thô trong CVAT không có. Cách có: `--meta <meta.json>` (theo tên frame; demo có sẵn),
  hoặc `--coords global` nếu nhãn và point cloud đã ở hệ tọa độ global (kèm `--frame-dt` giây giữa hai frame).
  Không có thì bỏ qua checker này và hiện cảnh báo.
- **Profile tham chiếu lấy từ nuScenes** (`profile.json`): kích thước và số điểm kỳ vọng theo class. Với dữ liệu của nhóm
  nên tính lại từ nhãn đã duyệt, nếu không có thể lệch (ví dụ barrier).
- **Job bắt đầu từ frame > 0** được xử lý bằng cách đệm tên frame, nhưng **chưa thử trên CVAT thật** (job demo bắt đầu từ 0).
- **ID #N** là số CVAT tự đánh khi tải job: `1 + vị trí` trong danh sách [tags, shapes, tracks] theo thứ tự API trả về (đã kiểm chứng
  CVAT 2.81.1: khớp 36/36 mục). Vì shapes đứng trước tracks, **thêm/xóa cuboid gợi ý làm đổi ID của các track**; extension tính lại ID từ
  annotation hiện tại mỗi lần tải trang hoặc chạy QC, nên chỉ lệch nếu bạn thêm/xóa đối tượng *sau khi tải trang* (khi đó tải lại trang).
- **Nhảy frame** đặt giá trị vào ô chọn frame của CVAT (`.cvat-player-frame-selector`); **chọn đối tượng** cuộn danh sách ảo bên phải
  (tìm nhị phân theo ID) rồi mô phỏng rê chuột lên mục đó. Cả hai dựa vào cấu trúc giao diện CVAT 2.81.1; nếu bản CVAT khác đổi cấu trúc,
  nhảy frame tự chuyển sang liên kết `?frame=…` (tải lại trang), còn chọn đối tượng sẽ không có tác dụng (huy hiệu ID vẫn dùng được để tìm tay).
- Kết quả QC lưu trong `sessionStorage` của tab (chỉ danh sách lỗi, khoảng vài KB, **không** gồm kế hoạch ghi). Sau khi tải lại trang,
  bấm "Ghi…" sẽ tự chạy lại QC để tính kế hoạch rồi mới hỏi xác nhận.
- Sau khi **nạp lại hoặc cập nhật extension**, trang CVAT đang mở phải tải lại (F5); nếu không bảng sẽ báo "Extension vừa được nạp lại".
- Mỗi lần nạp lần đầu phải chuyển toàn bộ point cloud (demo: 41 frame, 22 MB) qua máy; các lần sau dùng cache.
- Số điểm LiDAR được tính lại từ point cloud, nên **không phụ thuộc** `num_lidar_pts` của nuScenes.

## Kiểm thử
```powershell
node --test extension/test/lib.test.js           # 26 test cho logic thuần (URL, thứ tự PATCH, base64, nạp frame, lỗi giữa chừng)
python -W error::ResourceWarning -m unittest discover -s tests   # gồm 20 test cho server QC
python tests\mutation_check.py                   # 33 đột biến (cả Python và JS), test phải bắt hết
```

### Đã kiểm chứng đầu-cuối (trong trang CVAT thật, ở chế độ thử nghiệm: không qua service worker)
Nạp `lib.js` + `content.js` vào trang job 38 của CVAT 2.81.1, gọi server thật: đọc 1.142 cuboid, **tự lấy 41 frame `.pcd` từ CVAT**
(`/api/jobs/{id}/data?type=frame&quality=original&number=N`), server trả 22 cờ (đúng với kết quả CLI trên cùng job), 5,5 giây, không cảnh báo.

### Chưa kiểm chứng: cần bạn thử thủ công khi đã nạp extension thật
Các phần dưới đây phụ thuộc môi trường trình duyệt mà tôi không điều khiển được (nạp extension vào Chrome/Edge của bạn):
- [ ] Nạp extension (Load unpacked) không báo lỗi; nút **QC** xuất hiện ở trang job, **không** xuất hiện ở trang danh sách task.
- [ ] Trang Tùy chọn: **Kiểm tra kết nối** báo "Kết nối tốt"; nhập sai token thì báo "TOKEN SAI".
- [ ] **Chạy QC** qua service worker (không phải chế độ thử nghiệm) cho cùng kết quả như CLI.
- [ ] **Ghi cờ & gợi ý vào job**: ghi thành công với phiên đăng nhập của bạn (kiểm tra header `X-CSRFToken` được CVAT chấp nhận); sau khi tải lại có cuboid xanh `QC_SUGGESTION`.
- [ ] Chạy QC lần hai sau khi ghi: số cờ không đổi, không nhân đôi cuboid gợi ý.
- [ ] Trên CVAT dùng HTTPS (ví dụ `cvat.edufun.ai`): service worker gọi được `http://127.0.0.1:8766` (không bị chặn).
- [x] Bấm một lỗi trong danh sách: nhảy đúng frame và chọn đúng đối tượng (đã thử trong Chrome với 3 lỗi: #23, #46, #32).
