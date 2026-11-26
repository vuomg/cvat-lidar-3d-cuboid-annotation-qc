# Quy trinh pilot: QC cuboid 3D (N2-04C)

Muc tieu: chung minh bang so lieu that rang cong cu giam **so vong bi tra lai** va tang **IoU 3D** cua nhan cuoi.
`pilot_sim.py` chi la uoc luong theo gia dinh; tai lieu nay la cach do that.

## 1. Thiet ke
- **Don vi task:** 1 clip lien tiep (de xuat 10 keyframe = 1 scene nuScenes 20 s) de co du box va tracking.
- **Hai nhom:** `baseline` (lam nhu cu) va `tool` (chay `qc.py`, xu ly co trong `viewer.html`, roi moi nop).
- **Phan nhom (de xuat):** ghep cap. Moi task duoc lam hai lan (bat dau tu cung bo nhan nguon / cung scene tho),
  mot lan moi nhom, boi hai annotator tuong duong; hoac crossover: moi annotator lam mot nua task moi nhom
  (cach 1-2 ngay giua hai lan de giam hieu ung nho lai).
- **Chia ngau nhien** task giua hai nhom, can bang theo mat do doi tuong va dieu kien (ngay/dem/mua).
- **Reviewer mu nhom:** reviewer khong duoc biet task thuoc nhom nao. Nen co >= 2 reviewer, xoay vong.
- **So mau:** de phat hien giam 0.5 vong tra lai voi SD ~ 1.0 (alpha = .05, power = .8) can ~63 task moi nhom
  (`pilot_metrics.py` tinh lai theo SD thuc). So annotator toi thieu 3 moi nhom de khong phu thuoc mot nguoi.

## 2. Chi so
| Chi so | Dinh nghia | Cach do |
|---|---|---|
| **So vong bi tra lai** | so lan reviewer tra task truoc khi duoc nhan (0 = nhan ngay) | log cua he thong review (cot `rounds_returned`) |
| **IoU 3D truoc / sau** | IoU 3D cua tung box so voi **gold**; "truoc" = ban nop dau tien cua baseline, "sau" = ban nop co dung tool; do them IoU 3D co huong (0 neu yaw lech > 90 do) | `iou3d_mean` trung binh theo task |
| Thoi gian / task | tu luc mo task den luc nop | cot `minutes` |
| Chat luong cua tool | precision that = ty le co duoc review la "loi that" | `decisions.csv` xuat tu viewer |

**Gold:** 2 chuyen gia gan nhan doc lap tren mot mau con (de xuat >= 30% task), thong nhat khac biet; box chi duoc dung
de tinh IoU khi gold da duoc chot. IoU thuan khong thay loi lat 180 do nen luon ghi kem IoU co huong hoac sai so goc.

## 3. Cach chay
1. Chuan bi du lieu: `python -m cuboidqc.core.qc --dataroot <nuScenes> --out report.csv`; ban pilot nen dung bo nhan tho cua annotator, khong phai GT.
2. Nhom `tool`: sinh viewer `python -m cuboidqc.viewer.build --dataroot <...> --report report.csv --out viewer.html`, annotator xu ly tung co,
   bam *Loi that / Bao nham / Bo qua*, chinh box trong cong cu gan nhan cua ho (viewer chi goi y, khong sua nhan).
3. Ghi log moi task theo [`pilot_log_template.csv`](pilot_log_template.csv), roi: `python -m cuboidqc.evaluation.pilot_metrics pilot_log.csv`.
4. So `decisions.csv` voi tung loai loi de chinh nguong (`sweep.py`, `config.json`) **truoc** pilot chinh, khong chinh giua chung.

## 4. Tieu chi thanh cong (de xuat, thong nhat truoc khi bat dau)
- So vong tra lai giam >= 30% va 95% CI cua chenh lech khong chua 0.
- IoU 3D cua nhan cuoi tang >= 0.05 va CI khong chua 0.
- Precision cua co ERROR >= 60% (annotator khong bi lam phien boi bao nham); thoi gian / task khong tang qua 10%.

## 5. Rui ro
- **Hieu ung nho lai / hoc:** crossover can tach thoi gian; dao thu tu nhom giua cac annotator.
- **Hawthorne:** annotator lam ky hon khi biet dang duoc do; de baseline cung biet la pilot.
- **Reviewer thien vi:** mu nhom, hoac it nhat khong cho reviewer thay file co cua tool.
- **Tool chua bat het:** lech vi tri nhe / kich thuoc sat nguong van den reviewer nhu cu (xem [`reports/eval_report.md`](reports/eval_report.md)).
- **Gold chua chuan:** neu gold tu nuScenes thi chi dung de kiem tra tool, khong dung de tuyen bo ve IoU cua annotator that.
