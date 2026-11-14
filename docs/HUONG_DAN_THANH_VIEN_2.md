# Hướng dẫn cài đặt và chạy — Thành viên 2

Thành viên 2 phụ trách hai thí nghiệm:

- **Thí nghiệm B**: so sánh các SAT solver (CaDiCaL, Glucose, CryptoMiniSat, Kissat) với cấu hình tốt nhất do Thành viên 1 tìm ra và với `direct-pairwise`.
- **Thí nghiệm C**: so sánh SAT với các solver ILP và CP (Gurobi, CPLEX MIP, CPLEX CP, OR-Tools CP-SAT).

Thành viên 2 **chạy sau** Thành viên 1, vì chương trình dùng lại bộ đề, giới hạn thời gian và cấu hình tốt nhất của Thành viên 1.

Khối lượng: B = 4 solver × 2 cấu hình × N đề, trừ 2N lần đã có từ thí nghiệm A, còn 6N; C = 4 solver × N = 4N. Tổng **10N lần chạy**, bằng Thành viên 1.

| Profile (do Thành viên 1 chọn) | Số lần chạy | Thời gian tối đa (mọi lần đều hết giờ) |
|---|---|---|
| `quick` (60 giây/lần, 33 đề GEOM) | 330 | 5,5 giờ; khoảng 1,4 giờ với `--jobs 4` |
| `full` (900 giây/lần, 53 đề GEOM + MS-CAP) | 530 | khoảng 5,5 ngày; khoảng 1,4 ngày với `--jobs 4` |

Solver nào không cài được sẽ được bỏ qua và ghi "không chạy" trong báo cáo, nên số lần chạy thực tế có thể ít hơn.

---

## 1. Chuẩn bị

- **Python 3.10 trở lên** (đã thử với 3.12). Kiểm tra:
  ```bash
  python --version
  ```
- **Git**, và đã clone repo về máy.

Yêu cầu tối thiểu để chạy được phần của bạn:

| Cần | Để làm gì | Bắt buộc? |
|---|---|---|
| `python-sat` (có CaDiCaL, Glucose) | Thí nghiệm B. CaDiCaL thường là solver cố định của Thành viên 1, nên máy bạn phải chạy được nó. | **Có** |
| `ortools` (CP-SAT) | Thí nghiệm C. Miễn phí, không cần giấy phép. | **Có** (hoặc một solver ILP/CP khác) |
| `pycryptosat` | CryptoMiniSat trong thí nghiệm B | Nên có |
| Kissat (file chạy) | Kissat trong thí nghiệm B | Tùy chọn |
| `gurobipy` | Gurobi trong thí nghiệm C | Tùy chọn, cần giấy phép |
| `docplex`, `cplex` | CPLEX MIP và CPLEX CP trong thí nghiệm C | Tùy chọn, cần giấy phép |

## 2. Tạo môi trường và cài thư viện cơ bản

Mở terminal ở thư mục gốc của repo.

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

Cài thư viện (gồm `python-sat`, `pycryptosat`, `ortools`, `matplotlib`, `psutil`):
```bash
cd code
```
```bash
pip install -r requirements.txt
```

> Nếu PowerShell báo không cho chạy script khi kích hoạt môi trường ảo, chạy một lần lệnh
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` rồi kích hoạt lại.

## 3. Cài các solver tùy chọn

### Kissat
Kissat không có gói Python; chương trình gọi file chạy `kissat` và truyền đường dẫn bằng `--kissat`.

- **Linux**: tự build từ mã nguồn.
  ```bash
  git clone https://github.com/arminbiere/kissat.git
  ```
  ```bash
  cd kissat && ./configure && make
  ```
  File chạy nằm ở `kissat/build/kissat`.
- **macOS**: có thể cài qua Homebrew (`brew install kissat`) hoặc build như trên.
- **Windows**: Kissat không hỗ trợ Windows trực tiếp. Hoặc chạy toàn bộ dự án trong WSL (Ubuntu) rồi build như Linux, hoặc bỏ qua Kissat (báo cáo sẽ ghi "không chạy").

### CryptoMiniSat
`pycryptosat` đã có trong `requirements.txt`. Nếu không cài được, có thể dùng file chạy `cryptominisat5` và truyền đường dẫn bằng `--cms ĐƯỜNG_DẪN`.

### Gurobi
```bash
pip install gurobipy
```
Không có giấy phép thì `gurobipy` chạy ở chế độ giới hạn kích thước mô hình (khoảng 2000 biến và 2000 ràng buộc). Mô hình ILP có khoảng n + |E| biến và n + 2|E| ràng buộc, nên các đề GEOM lớn sẽ vượt giới hạn và báo lỗi ở cột `msg`. Sinh viên có thể xin giấy phép học thuật miễn phí trên trang của Gurobi rồi kích hoạt theo hướng dẫn ở đó.

### CPLEX (MIP và CP)
```bash
pip install docplex cplex
```
Gói `cplex` trên pip là bản Community Edition, giới hạn khoảng 1000 biến và 1000 ràng buộc. Muốn chạy đề lớn, hoặc nếu `check` báo CPLEX CP không chạy, hãy cài **IBM ILOG CPLEX Optimization Studio** bản đầy đủ (miễn phí cho sinh viên qua IBM Academic Initiative).

## 4. Kiểm tra cài đặt

Các lệnh dưới đây chạy trong thư mục `code/`.

Kiểm tra tính đúng của encoder (khoảng 30 giây, phải in ra `ALL TESTS PASSED`):
```bash
python bcp_sat.py verify --out ../report
```

Xem solver nào dùng được (thêm `--kissat`, `--cms` nếu có):
```bash
python run_experiments.py check --kissat /duong/dan/toi/kissat
```
Phải có ít nhất:
- **CaDiCaL** `OK` ở phần SAT solver;
- **một** solver `OK` ở phần "ILP và CP" (thường là OR-Tools CP-SAT).

## 5. Ghi thông tin tác giả

```bash
python run_experiments.py info --member 2 --name "Tran Thi B" --student-id 2402yyyy --email 2402yyyy@vnu.edu.vn
```

## 6. Lấy kết quả của Thành viên 1

Đợi Thành viên 1 chạy xong và push, rồi lấy về:
```bash
git pull origin main
```
Phải có hai file `report/results/runs_member1.csv` và `report/results/meta_member1.json`. Nếu thiếu, bước sau sẽ báo lỗi.

> Muốn chạy thử trước khi Thành viên 1 xong: chạy `python run_experiments.py run --member 1 --profile smoke --jobs 4`, rồi `python run_experiments.py run --member 2 --jobs 4`. Chạy thử xong thì **xóa** `report/results/runs_member*.csv` và `meta_member*.json`, chạy `python run_experiments.py reset`, và **không commit** các file đó.

## 7. Chạy thật

```bash
python run_experiments.py run --member 2 --jobs 4 --kissat /duong/dan/toi/kissat
```
Bỏ `--kissat ...` nếu không dùng Kissat. Chương trình sẽ:
1. đọc bộ đề, giới hạn thời gian và cấu hình tốt nhất từ `meta_member1.json`;
2. chạy **thí nghiệm B** (bỏ qua các lần đã có từ thí nghiệm A) và chọn SAT solver tốt nhất;
3. chạy **thí nghiệm C** với các solver ILP/CP dùng được;
4. sinh lại bảng, hình và đoạn văn trong `report/`.

Lưu ý:
- `--jobs 4` chạy song song 4 tiến trình. Nên **dùng cùng số `--jobs` với Thành viên 1** và đừng dùng máy cho việc nặng khác, để thời gian so sánh được.
- **Nếu máy bạn khác máy Thành viên 1**, báo cáo tự ghi thêm thông số máy của bạn. Khi đó thời gian của solver cố định trong bảng SAT solver (lấy từ thí nghiệm A) không so sánh trực tiếp được với các solver bạn chạy. Tốt nhất hai người chạy trên cùng một máy.
- **Bị dừng giữa chừng**: chạy lại đúng lệnh cũ, các lần đã xong sẽ được bỏ qua.
- Máy tính phải **không ngủ** trong lúc chạy.

## 8. Đẩy kết quả lên

```bash
cd ..
```
```bash
git add report/results report/tables report/figures
```
```bash
git commit -m "Add member 2 results (experiments B and C)"
```
```bash
git push origin main
```

Khi có đủ kết quả của cả hai người, dòng đỏ **BẢN CHƯA HOÀN THÀNH** trong PDF sẽ biến mất (nếu đủ các file báo cáo).

## 9. Viết báo cáo

Bạn chỉ sửa các file trong `report/parts/member2/`. Mục "So sánh các SAT solver" và "So sánh với ILP và CP" nằm trong `exp_compare.tex`. Sau khi chạy, đọc lại `report/results/auto_text.tex` (đoạn văn tự sinh) và sửa nhận xét cho tự nhiên. Biên dịch PDF theo hướng dẫn trong [README](../README.md#biên-dịch-trên-overleaf).

---

## Lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| `Chưa có kết quả của Thành viên 1 (report/results/meta_member1.json)` | Chưa `git pull`, hoặc Thành viên 1 chưa push. |
| `Máy này không chạy được CaDiCaL (solver cố định của Thành viên 1)` | Cài `python-sat`: `pip install python-sat`. |
| `Không có solver ILP hay CP nào chạy được` | Cài `ortools`: `pip install ortools`. |
| `Kết quả của Thành viên 2 không khớp ...` khi sinh báo cáo | Thành viên 1 đã chạy lại với giới hạn thời gian khác: chạy lại `run --member 2`. |
| Cột `msg` báo lỗi kích thước mô hình (Gurobi/CPLEX) | Bản không có giấy phép bị giới hạn kích thước; xin giấy phép học thuật, hoặc chấp nhận "lỗi" trên đề lớn và nêu trong mục Hạn chế. |
| `không tìm thấy kissat (thêm --kissat ĐƯỜNG_DẪN)` | Truyền đúng đường dẫn tới file chạy `kissat`, hoặc bỏ qua Kissat. |
| `UnicodeEncodeError: 'charmap' codec ...` khi in tiếng Việt (Windows) | Chạy `$env:PYTHONIOENCODING="utf-8"` trong PowerShell (hoặc `set PYTHONIOENCODING=utf-8` trong cmd) rồi chạy lại lệnh. |
