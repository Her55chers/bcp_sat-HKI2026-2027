# Báo cáo BTL 1 — Bandwidth Coloring solver dùng SAT

Bộ giải bài toán tô màu băng thông (BCP) bằng SAT, so sánh các cách mã hóa, các SAT solver (CaDiCaL, Glucose, CryptoMiniSat, Kissat) và các solver ILP, CP (Gurobi, CPLEX MIP, CPLEX CP, OR-Tools CP-SAT).

## Phân công hai thành viên

| | Thành viên 1 | Thành viên 2 |
|---|---|---|
| Code | `code/bcp_sat.py`, `code/make_example_figure.py` | `code/exact_models.py`, `code/run_experiments.py` |
| Thực nghiệm | cấu hình mã hóa, AMO, SAT solver | Gurobi, CPLEX MIP, CPLEX CP, CP-SAT |
| Báo cáo | `report/parts/member1/` | `report/parts/member2/` |

`report/bcp_sat_report.tex` chỉ ghép hai thư mục trên, mỗi người chỉ sửa thư mục của mình. PDF luôn biên dịch được, nhưng mọi trang có dòng đỏ **BẢN CHƯA HOÀN THÀNH** cho đến khi đủ cả ba điều kiện: có đủ file của hai người, Thành viên 1 đã chạy xong, Thành viên 2 đã chạy xong. Nếu thiếu file, tại vị trí đó có khung đỏ ghi rõ file nào của ai.

## Cấu trúc
- `report/bcp_sat_report.tex`, `report/parts/` — báo cáo theo template Elsevier `cas-sc`.
- `report/tables/`, `report/figures/`, `report/results/` — bảng, hình, số liệu sinh tự động.
- `code/bcp_sat.py` — encoder BCP (9 cấu hình), 5 cách mã hóa AMO, công thức kích thước, bộ kiểm thử, ghi DIMACS, wrapper PySAT.
- `code/exact_models.py` — các mô hình ILP và CP.
- `code/make_example_figure.py` — sinh Hình 1.
- `code/run_experiments.py` — chạy thực nghiệm và tự điền báo cáo.
- `instances/GEOM/`, `instances/MS-CAP/` — dữ liệu. `instances/reference_values.csv` — giá trị tối ưu tham khảo.

## Chạy
Cả hai cùng làm:
```
cd code
pip install -r requirements.txt
python bcp_sat.py verify --out ../report
python run_experiments.py check
python run_experiments.py info --member 1 --name "Nguyen Van A" --student-id 2402xxxx --email 2402xxxx@vnu.edu.vn --github https://github.com/<ban>/bcp-sat
python run_experiments.py info --member 2 --name "Tran Thi B" --student-id 2402yyyy --email 2402yyyy@vnu.edu.vn
```
Thành viên 1 chạy trước, rồi đẩy `report/results/runs_member1.csv` và `meta_member1.json` lên repo:
```
python run_experiments.py run --member 1 --profile quick --jobs 4
```
Thành viên 2 lấy hai file đó về rồi chạy. Lệnh này tự dùng đúng bộ đề và giới hạn thời gian của Thành viên 1, và báo lỗi nếu chưa có các file đó:
```
python run_experiments.py run --member 2 --jobs 4
```
- Thông số máy trong báo cáo lấy từ máy của Thành viên 1. So sánh thời gian chỉ công bằng khi hai người dùng cùng một máy; nếu khác máy, hãy nêu rõ trong mục Hạn chế.
- `check` cho biết solver nào dùng được. Solver thiếu sẽ được bỏ qua và ghi "không chạy" trong báo cáo. Thành viên 2 cần ít nhất một solver ILP hoặc CP.
- `quick`: 60 giây mỗi lần, toàn bộ GEOM. `full`: 3600 giây mỗi lần, GEOM và MS-CAP, rất lâu. `smoke`: chạy thử. Có thể chọn bộ bằng `--sets GEOM-L`, đổi giới hạn bằng `--time-limit`.
- Chạy thử xong, hãy xóa các file `report/results/runs_member*.csv` và `meta_member*.json` trước khi chạy thật, rồi chạy `python run_experiments.py reset`.
- Dừng giữa chừng rồi chạy lại lệnh cũ, các lần đã xong sẽ được bỏ qua.
- Kissat cần file chạy riêng: thêm `--kissat ĐƯỜNG_DẪN`. Gurobi và CPLEX cần giấy phép: bản miễn phí giới hạn kích thước mô hình, nên đề lớn sẽ báo lỗi trong cột `msg`.

## Biên dịch trên Overleaf
1. Tải toàn bộ thư mục `report/` lên (gồm cả `parts/`), chọn `bcp_sat_report.tex` làm file chính.
2. Menu → Settings → Compiler: chọn **XeLaTeX**.
3. Recompile (Overleaf tự chạy BibTeX).

Chữ đỏ trong PDF là chỗ chưa có dữ liệu. Sau khi chạy thực nghiệm, hãy đọc lại các đoạn văn tự sinh trong `report/results/auto_text.tex` và sửa cho tự nhiên.

