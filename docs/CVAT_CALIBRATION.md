# Hiệu chỉnh quy ước cuboid CVAT 3D (kiểm chứng trên CVAT 2.81.1 local)

Mục tiêu: biết chắc `points` của cuboid trong CVAT ánh xạ thế nào sang (vị trí, kích thước, hướng) để
công cụ QC và `cvat-prelabel` ghi/đọc đúng, không bị lệch 90° hay ngược 180°.

## Cách làm
`python -m cuboidqc.cvat.calibrate` tạo task `calibration` gồm **một frame** có:
- cụm điểm đặc ở `(+25, 0)` đánh dấu chiều **+x**; ba cụm nhỏ ở `(0, +20/+23/+26)` đánh dấu chiều **+y**;
- hộp `Car` tại `(0, 0)`, `rz = 0`, scale `(sx, sy, sz) = (8, 2, 2)`, kèm một dải điểm dày ở **đầu +x** của hộp;
- hộp `Truck` tại `(0, -14)`, `rz = +45°`, cùng scale.

Mở job trong CVAT, nhìn khung 3D từ trên xuống (CVAT vẽ gizmo trục: cam = x, xanh lá = y, xanh dương = z).

## Kết quả
| Câu hỏi | Quan sát | Kết luận |
|---|---|---|
| `sx` là chiều nào? | Hộp 8×2 ở `rz=0` nằm dọc theo trục +x (đường cam của gizmo chạy dọc chiều dài hộp, về phía cụm điểm đánh dấu +x) | `sx` = **chiều dài, dọc +x cục bộ** |
| Thứ tự scale | Thanh bên CVAT hiển thị `L / W / H` = 4,75 / 2,02 / 1,49 cho hộp ghi với `points[6:9]` = `(4.75, 2.02, 1.49)` | `sx = L`, `sy = W`, `sz = H` |
| Chiều quay của `rz` | Hộp `Truck` ghi `rz = +45°` hiện xoay **ngược chiều kim đồng hồ** 45° so với hộp `Car` khi nhìn từ trên | `rz > 0` là CCW nhìn từ +z |
| Hệ trục | +x → +y là CCW nhìn từ trên; trục +z hướng lên | Hệ tay phải, z lên |
| Gốc yaw | `rz = 0` thì chiều dài hộp nằm dọc +x | `yaw_offset = 0` |

Vậy `CONVENTION` mặc định trong `cvat_adapter.py` (`scale_order="lwh"`, `yaw_offset=0`, `yaw_sign=+1`) là
**đúng** và trùng với giả định trong `cvat-prelabel/server/prelabel/exporter.py`.

## Chưa kiểm chứng được
- **Đầu nào của hộp là "phía trước"**: CVAT không vẽ mũi tên hướng lên cuboid, và hộp đối xứng nên không đọc ra
  được. Ta giả định phía trước = **+x cục bộ** (giống nuScenes và exporter của `cvat-prelabel`). Điều này phụ thuộc
  vào việc annotator đặt hướng đúng theo guideline; kiểm tra bằng chính checker `HEADING_REVERSED`
  (so hướng hộp với hướng di chuyển).
- Khung nhìn **Top** của CVAT xoay theo vật đang chọn (hộp luôn nằm ngang), nên không dùng nó để đọc yaw; hãy dùng khung 3D chính.
- Chỉ thử trên CVAT 2.81.1. Phiên bản khác có thể khác quy ước.
