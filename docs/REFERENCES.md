# Tài liệu tham khảo

Tài liệu này liệt kê các bài báo và tài liệu liên quan tới công cụ QC cuboid 3D, **bài nào ảnh hưởng tới phần nào của tool**,
và **đã áp dụng đến đâu**. Mục đích là để người đọc phân biệt rõ: *tool này lấy ý tưởng từ đâu* và *tool này tự làm gì*.

## Mức độ kiểm chứng (đọc trước)
- Phần mô tả bài báo dưới đây dựa trên **tóm tắt và trích đoạn từ kết quả tìm kiếm** (tháng 11/2026), **không phải toàn văn**.
  Các con số do bài báo tự báo cáo, chưa được kiểm chứng độc lập trong dự án này.
- Một số mã arXiv có tiền tố 26xx lấy nguyên từ kết quả tìm kiếm; hãy mở liên kết để xác nhận trước khi trích dẫn chính thức.
- Khảo sát chỉ gồm vài lượt tìm kiếm, **không phải tổng quan có hệ thống**, nên có thể bỏ sót bài.
- Không tìm thấy bài nào làm đúng bài toán *"kiểm tra chất lượng cuboid 3D bằng luật hình học trên point cloud"* như tool này.
  Việc so sánh với các bài dưới đây là **tương đồng về ý tưởng**, không phải so sánh số liệu.

## Bảng tổng hợp

| # | Tài liệu | Ý chính (theo tóm tắt) | Ảnh hưởng tới tool | Trạng thái |
|---|---|---|---|---|
| 1 | **nuScenes**, Caesar et al., 2019. [arXiv:1903.11027](https://arxiv.org/abs/1903.11027) | Bộ dữ liệu lái xe tự hành đa cảm biến, 1,4 triệu box 3D | Nguồn dữ liệu và nhãn tham chiếu (`profile.json`, đánh giá, demo) | **Đã dùng** |
| 2 | **LMD / MetaDetect3D**, [arXiv:2306.07835](https://ar5iv.labs.arxiv.org/html/2306.07835) | Ước lượng chất lượng dự đoán của detector LiDAR để gắn cờ nhãn sai trên KITTI/nuScenes; báo cáo 43/100 đề xuất đầu trên nuScenes test là nhãn sai thật | Ý tưởng "xếp hạng theo điểm nghi ngờ" thay vì ngưỡng cứng | **Chưa làm** (tool dùng luật + ngưỡng, không dùng detector) |
| 3 | **REC✓D**, [arXiv:2508.06556](https://arxiv.org/html/2508.06556v2) | Quy trình phát hiện lỗi nhãn → sửa → người duyệt; bản cho box 2D (KITTI) | Kiến trúc tổng thể: cờ → gợi ý → người quyết định (viewer HTML, cuboid `QC_SUGGESTION` trong CVAT, `decisions.csv`) | **Lấy cảm hứng** (kiến trúc, không phải thuật toán) |
| 4 | **CLOD**, [arXiv:2211.13993](https://arxiv.org/pdf/2211.13993) | Phát hiện nhãn nhiễu cho box 2D (COCO, Waymo ảnh) | Bối cảnh bài toán nhãn nhiễu | Chỉ tham khảo |
| 5 | **AutoVDC**, [arXiv:2507.12414](https://arxiv.org/pdf/2507.12414v1) | Dùng mô hình ngôn ngữ-thị giác xác minh cờ lỗi (đánh giá trên ảnh 2D) | Hướng mở rộng: kiểm chứng cờ tự động | **Chưa làm** |
| 6 | **Lỗi hệ thống của box 3D do quét không đồng thời**, [arXiv:2601.14038](https://arxiv.org/html/2601.14038v1) | LiDAR quét quay nên vật chuyển động bị lệch box tới ~2,5 m (Argoverse 2); đề xuất sửa bằng mô hình chuyển động | Giải thích một phần cờ `BOX_OFFSET` trên xe chạy nhanh | **Chưa làm** (chưa có dung sai theo vận tốc) |
| 7 | **AmodalBox**, [arXiv:2611.10821](https://arxiv.org/pdf/2611.10821) | Chỉ dùng điểm LiDAR một phần dễ cho box sai kích thước khi vật bị che | Cơ sở để **giữ nguyên kích thước khi dịch box** (`boxfit`) và dùng kích thước theo track | **Áp dụng một phần** |
| 8 | **Chan et al.**, *The inconvenient truth of ground truth errors in automotive datasets and DNN-based detection*, Data-Centric Engineering. [Cambridge](https://www.cambridge.org/core/journals/data-centric-engineering/article/inconvenient-truth-of-ground-truth-errors-in-automotive-datasets-and-dnnbased-detection/E6DD1635FACE3CF49C67019E9A10BB5E) | Phân loại lỗi nhãn trong KITTI và nuScenes; hướng dẫn gắn nhãn của nuScenes "mở cho nhiều cách hiểu"; báo cáo sửa nhãn tăng tới 9% hiệu năng | Khung bài toán; lý do cờ trên nhãn gốc nuScenes **chưa chắc là báo nhầm** | **Lấy cảm hứng** |
| 9 | **3D Auto Labeling (3DAL)**, Qi et al., CVPR 2021. [arXiv:2103.05073](https://arxiv.org/abs/2103.05073v1) | Detect từng frame → tracking → tinh chỉnh theo vật; báo cáo ngang nhãn người trên Waymo | Ý tưởng "xử lý theo **track**" cho sửa kích thước (`fixes.fix_size_by_track`) | **Áp dụng bản đơn giản** (trung vị theo track, không học) |
| 10 | **CTRL**, [arXiv:2304.12315](https://arxiv.org/pdf/2304.12315v1.pdf) | Coi track là đơn vị chính của auto-label, thêm bước tinh chỉnh | Như trên | **Áp dụng bản đơn giản** |
| 11 | **LabelFormer**, [arXiv:2311.01444](https://arxiv.org/pdf/2311.01444v1.pdf) | Mô hình học để tinh chỉnh quỹ đạo vật thể | Hướng mở rộng cho sửa theo track | **Chưa làm** |
| 12 | **Kiểm tra chất lượng annotation cảm biến bằng luật**, [arXiv:2603.00114](https://arxiv.org/html/2603.00114v1) | Các kiểm tra tự động theo luật trên nhãn LiDAR (bộ dữ liệu đường sắt) | Gần nhất về tinh thần với hướng "luật, giải thích được" của tool | **Lấy cảm hứng** |
| 13 | ePose, [arXiv:2111.15114](https://arxiv.org/pdf/2111.15114) | (Nguồn yếu) một lưu ý về box bị che hoàn toàn trong nuScenes | Cân nhắc khi đọc cờ `LOW_LIDAR_PTS` | Nguồn yếu, chỉ tham khảo |
| 14 | *Rethink 3D Object Detection from Physical World*, [arXiv:2507.00190](https://arxiv.org/pdf/2507.00190) | (Nguồn yếu) nuScenes gắn nhãn 2 Hz; sai vị trí 0,5 m có thể gây sai vận tốc ~1 m/s | Cân nhắc khi đọc cờ hướng / vận tốc | Nguồn yếu, chỉ tham khảo |

## Công cụ và thuật toán nền
| Tài liệu | Dùng ở đâu |
|---|---|
| **CVAT** và REST API (`/api/docs`, schema OpenAPI của bản 2.81.1 đang chạy) | `cvat_client.py`, `cvat_qc.py`, extension |
| Sutherland & Hodgman, *Reentrant polygon clipping*, CACM 1974 *(thuật toán kinh điển, trích theo hiểu biết, chưa mở lại trong phiên này)* | `qc.clip_poly`: giao hai đa giác lồi để tính IoU 3D |
| Quy ước quaternion (w, x, y, z) và ego pose của nuScenes (xem tài liệu nuScenes devkit) | `qc.yaw_of`, `cvat_adapter.to_global` |

## Mỗi tính năng của tool dựa vào đâu

| Tính năng | Cơ sở | Ghi chú trung thực |
|---|---|---|
| 5 checker (ít điểm, kích thước, chồng, hướng, lệch) | Luật hình học tự thiết kế; tinh thần như #12 | Ngưỡng chọn bằng dữ liệu nuScenes và quét tham số, **chưa kiểm chứng với nhãn người thật** |
| Ngưỡng LiDAR theo khoảng cách | Quan sát trên nuScenes (nhiều box 0 điểm hợp lệ vì ở xa/bị che) | Tự đo, không từ bài báo |
| Gợi ý sửa theo **track** | #9, #10 (ý tưởng), #7 | Bản đơn giản, không có mô hình học như #11 |
| Quy trình cờ → gợi ý → người duyệt | #3 | Không dùng thuật toán của #3 |
| Chính sách `apply` **bảo thủ** | Phát hiện của chính dự án: tự áp dụng dịch box làm hỏng nhãn đúng (118 mẫu, chỉ 5% còn gần nhãn gốc) | Đo trên 7 scene nuScenes bằng `evaluate_cvat.py`; không có trong các bài trên |
| Hiệu chỉnh quy ước cuboid CVAT | Thực nghiệm trên CVAT 2.81.1 ([`docs/CVAT_CALIBRATION.md`](CVAT_CALIBRATION.md)) | Không từ bài báo |

## Hướng đã khảo sát nhưng chưa tích hợp
Bộ xếp hạng học được kiểu #2, dung sai theo vận tốc theo #6, mô hình tinh chỉnh track kiểu #11, và kiểm chứng cờ bằng VLM kiểu #5.
Các hướng này cần mô hình đã huấn luyện hoặc dữ liệu có nhãn người, nên được để lại như phần phát triển tiếp theo.
