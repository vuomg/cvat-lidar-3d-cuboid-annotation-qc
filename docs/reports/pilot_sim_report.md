# MO PHONG pilot QC cuboid 3D (KHONG phai thuc nghiem voi nguoi that)

Ghep cap: cung bo annotation co loi, hai quy trinh (baseline vs co tool). 3 lan mo phong, 404 task (frame) moi lan, 18577 box moi lan.

## Gia dinh chua do duoc

- Ty le loi cua annotator / box: {'size': 0.02, 'flip': 0.02, 'dup': 0.005, 'shift': 0.02}
- Xac suat reviewer thay 1 loi moi vong: {'size': 0.5, 'flip': 0.4, 'dup': 0.8, 'shift': 0.5}
- Annotator sua dung sau khi bi tra lai: 90%; lam theo tool: 90%; co 'kiem tra thu cong' -> tu sua dung: 60%
- Box duoc coi la dung neu IoU 3D co huong >= 0.7

## Phan do that: tool tren loi mo phong

| Loai loi | So loi | Tool bao co |
|---|---|---|
| size | 764 | 541 (71%) |
| flip | 88 | 88 (100%) |
| dup | 126 | 126 (100%) |
| shift | 147 | 111 (76%) |

IoU 3D co huong cua cac box loi: **0.23** (luc nop) -> **0.54** (sau khi annotator dung tool, TRUOC review)

Trung binh moi lan: 946 box bi co (5.1% tong box), 61.3% loi con sot sau buoc tu kiem tra

## Ket qua theo gia dinh do nhay cua reviewer (nhan voi he so)

| He so reviewer | So vong tra lai / task: baseline | co tool | Giam | 95% CI cua chenh lech | Loi sot / task: baseline -> co tool | IoU cuoi: baseline -> co tool |
|---|---|---|---|---|---|---|
| x0.6 | 0.31 | 0.21 | 32% | [0.06, 0.13] | 0.61 -> 0.37 | 0.48 -> 0.69 |
| x1.0 | 0.51 | 0.29 | 43% | [0.18, 0.26] | 0.36 -> 0.26 | 0.68 -> 0.77 |
| x1.4 | 0.62 | 0.38 | 39% | [0.20, 0.28] | 0.17 -> 0.15 | 0.83 -> 0.84 |

## Dien giai

- Day la uoc luong *neu* cac gia dinh dung. No cho biet tool co kha nang giam bao nhieu vong tra lai khi biet do phu loi cua tool, KHONG thay the pilot voi annotator that (xem PILOT.md).
- Cac loi tool khong bat duoc (vi du lech vi tri nhe vi con du diem) van nam trong quy trinh review nhu cu.
- Tool khong lam reviewer 'thay' them loi: so loi sot khi duoc nhan phan anh viec box da duoc tool sua truoc khi den reviewer.
