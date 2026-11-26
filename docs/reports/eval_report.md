# Bao cao danh gia qc.py

- Du lieu: 18538 cuboid; 3 lan chen ngau nhien (seed), 50 box loi moi muc moi lan
- Recall = ty le box chen loi bi gan co ERROR/WARNING (cot 'ERROR' chi tinh ERROR)
- Precision can duoi: moi box bi co khong nam trong so box chen deu tinh la FP, ke ca co tren GT goc (co the la loi that cua nuScenes)

## LOW_LIDAR_PTS

Co tren GT goc (chua chen): **273** box. Precision can duoi: **27%** (TP=283, FP=767)

| Muc | So box | Recall (>=WARNING) | Recall (ERROR) |
|---|---|---|---|
| giu 50% diem | 150 | 1% | 1% |
| giu 25% diem | 150 | 19% | 19% |
| giu 10% diem | 150 | 69% | 69% |
| 0 diem | 150 | 100% | 100% |

## BAD_SIZE

Co tren GT goc (chua chen): **109** box. Precision can duoi: **85%** (TP=535, FP=92)

| Muc | So box | Recall (>=WARNING) | Recall (ERROR) |
|---|---|---|---|
| x1.15 | 150 | 0% | 0% |
| x1.3 | 150 | 19% | 0% |
| x1.6 | 150 | 97% | 0% |
| x2.0 | 150 | 100% | 32% |
| x0.7 | 150 | 41% | 0% |
| x0.5 | 150 | 100% | 17% |

## OVERLAP

Co tren GT goc (chua chen): **48** box. Precision can duoi: **88%** (TP=1200, FP=165)

| Muc | So box | Recall (>=WARNING) | Recall (ERROR) |
|---|---|---|---|
| dich 0.1 chieu dai | 150 | 100% | 100% |
| dich 0.3 | 150 | 100% | 100% |
| dich 0.5 | 150 | 100% | 100% |
| dich 0.8 | 150 | 100% | 1% |

## HEADING_REVERSED

Co tren GT goc (chua chen): **1** box. Precision can duoi: **100%** (TP=656, FP=3)

| Muc | So box | Recall (>=WARNING) | Recall (ERROR) |
|---|---|---|---|
| lat 180 do | 150 | 100% | 100% |
| lech 165 | 150 | 100% | 100% |
| lech 150 | 150 | 100% | 100% |
| lech 135 | 150 | 100% | 100% |
| lech 120 | 150 | 37% | 37% |
| lech 90 | 150 | 0% | 0% |

## BOX_OFFSET

Co tren GT goc (chua chen): **277** box. Precision can duoi: **31%** (TP=388, FP=883)

| Muc | So box | Recall (>=WARNING) | Recall (ERROR) | Recall (BOX_OFFSET hoac LOW_LIDAR_PTS) |
|---|---|---|---|---|
| dich 0.5 m | 150 | 50% | 8% | 52% |
| dich 0.8 m | 150 | 67% | 14% | 67% |
| dich 1.2 m | 150 | 75% | 57% | 77% |
| dich 1.8 m | 150 | 67% | 59% | 74% |
