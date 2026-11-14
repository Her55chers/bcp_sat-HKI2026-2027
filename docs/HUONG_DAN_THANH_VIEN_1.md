# Hướng dẫn cài đặt và chạy — Thành viên 1

Thành viên 1 phụ trách **thí nghiệm A**: so sánh 10 cấu hình mã hóa SAT (gồm 5 cách mã hóa AMO) với một SAT solver cố định (thường là CaDiCaL). Thành viên 1 **chạy trước**; Thành viên 2 cần kết quả của bạn để chạy phần của họ.

Khối lượng: 10 cấu hình × N đề = **10N lần chạy**.

| Profile | Số lần chạy | Thời gian tối đa (mọi lần đều hết giờ) |
|---|---|---|
| `quick` (60 giây/lần, 33 đề GEOM) | 330 | 5,5 giờ; khoảng 1,4 giờ với `--jobs 4` |
| `full` (900 giây/lần, 53 đề GEOM + MS-CAP) | 530 | khoảng 5,5 ngày; khoảng 1,4 ngày với `--jobs 4` |

Thực tế ngắn hơn nhiều, vì phần lớn các lần chạy SAT kết thúc sớm.

---

## 1. Chuẩn bị

- **Python 3.10 trở lên** (đã thử với 3.12). Kiểm tra:
  ```bash
  python --version
  ```
- **Git**, và đã clone repo về máy.
- Thành viên 1 **không cần** Gurobi, CPLEX hay Kissat.

## 2. Tạo môi trường và cài thư viện

Nên dùng môi trường ảo để không ảnh hưởng tới Python của máy. Mở terminal ở thư mục gốc của repo.

Tạo môi trường ảo:
```bash
python -m venv .venv
```

Kích hoạt môi trường ảo trên Windows (PowerShell):
```powershell
.venv\Scripts\Activate.ps1
```
Kích hoạt môi trường ảo trên Linux/macOS:
```bash
source .venv/bin/activate
```

Cài thư viện:
```bash
cd code
```
```bash
pip install -r requirements.txt
```

File `requirements.txt` cài `python-sat` (CaDiCaL, Glucose), `pycryptosat`, `ortools`, `matplotlib`, `psutil`. Thành viên 1 thực ra chỉ cần `python-sat`, `matplotlib` và `psutil`, nhưng cứ cài đủ để chạy được mọi lệnh kiểm tra.

> Nếu PowerShell báo không cho chạy script khi kích hoạt môi trường ảo, chạy một lần lệnh
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` rồi kích hoạt lại.

## 3. Kiểm tra cài đặt

Các lệnh dưới đây chạy trong thư mục `code/`.

Kiểm tra tính đúng của encoder (khoảng 30 giây, phải in ra `ALL TESTS PASSED`):
```bash
python bcp_sat.py verify --out ../report
```

Xem solver nào dùng được:
```bash
python run_experiments.py check
```
Ở phần "SAT solver", ít nhất **CaDiCaL** phải là `OK`. Kissat báo `--` là bình thường, vì Thành viên 1 không cần Kissat.

Giải thử một đề:
```bash
python bcp_sat.py solve --instance ../instances/GEOM/GEOM40.col
```

## 4. Ghi thông tin tác giả

```bash
python run_experiments.py info --member 1 --name "Nguyen Van A" --student-id 2402xxxx --email 2402xxxx@vnu.edu.vn --github https://github.com/<ban>/bcp-sat
```
Thay bằng thông tin thật của bạn. Lệnh này ghi vào `report/results/author.tex`.

## 5. Chạy thử nhanh (smoke)

```bash
python run_experiments.py run --member 1 --profile smoke --jobs 4
```
Chỉ chạy bộ GEOM-S với 5 giây/lần, mất vài phút. Nếu chạy hết và in ra `Xong phần Thành viên 1` là ổn.

**Xóa kết quả chạy thử** trước khi chạy thật. Trên Windows (PowerShell):
```powershell
Remove-Item ..\report\results\runs_member*.csv, ..\report\results\meta_member*.json
```
Trên Linux/macOS:
```bash
rm -f ../report/results/runs_member*.csv ../report/results/meta_member*.json
```
Rồi đưa báo cáo về trạng thái ban đầu:
```bash
python run_experiments.py reset
```

## 6. Chạy thật

Thống nhất với Thành viên 2 trước là dùng `quick` hay `full`, vì Thành viên 2 sẽ tự dùng đúng profile và giới hạn thời gian của bạn.

```bash
python run_experiments.py run --member 1 --profile quick --jobs 4
```
hoặc:
```bash
python run_experiments.py run --member 1 --profile full --jobs 4
```

- `--jobs 4` chạy song song 4 tiến trình. Nên đặt nhỏ hơn số nhân CPU, và đừng dùng máy cho việc nặng khác trong lúc chạy, vì thời gian đo sẽ bị nhiễu.
- Có thể chỉ chạy một số bộ, ví dụ `--sets GEOM-S GEOM-L`, hoặc đổi giới hạn bằng `--time-limit 300` (tối đa 900 giây).
- **Bị dừng giữa chừng** (tắt máy, Ctrl+C): chạy lại đúng lệnh cũ, các lần đã xong sẽ được bỏ qua.
- Máy tính phải **không ngủ** trong lúc chạy `full`.

Khi xong, chương trình in ra cấu hình tốt nhất và tự sinh bảng, hình, đoạn văn vào `report/`.

## 7. Gửi kết quả cho Thành viên 2

Commit và push kết quả để Thành viên 2 lấy về. Quan trọng nhất là hai file `runs_member1.csv` và `meta_member1.json`.

```bash
cd ..
```
```bash
git add report/results report/tables report/figures
```
```bash
git commit -m "Add member 1 results (experiment A)"
```
```bash
git push origin main
```

Sau đó báo cho Thành viên 2. Cũng cho họ biết bạn chạy trên máy nào: nếu hai người khác máy, báo cáo sẽ tự ghi chú điều đó.

## 8. Viết báo cáo

Bạn chỉ sửa các file trong `report/parts/member1/`. Sau khi chạy, đọc lại `report/results/auto_text.tex` (đoạn văn tự sinh) và sửa phần nhận xét trong `exp_sat.tex` cho tự nhiên. Biên dịch PDF theo hướng dẫn trong [README](../README.md#biên-dịch-trên-overleaf).

---

## Lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| `ModuleNotFoundError: No module named 'pysat'` | Chưa kích hoạt môi trường ảo, hoặc chưa chạy `pip install -r requirements.txt`. |
| `UnicodeEncodeError: 'charmap' codec ...` khi in tiếng Việt (Windows) | Chạy `$env:PYTHONIOENCODING="utf-8"` trong PowerShell (hoặc `set PYTHONIOENCODING=utf-8` trong cmd) rồi chạy lại lệnh. |
| `--time-limit phải trong khoảng (0, 900] giây` | Giới hạn mỗi lần chạy tối đa là 900 giây. |
| `Không có SAT solver nào chạy được` | Cài lại `python-sat`: `pip install --force-reinstall python-sat`. |
| `verify` báo `SOME TESTS FAILED` | Không chạy thực nghiệm; báo lại cho nhóm kèm output của lệnh. |
