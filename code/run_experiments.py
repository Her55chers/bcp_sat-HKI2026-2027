#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_experiments.py -- chay toan bo thuc nghiem va TU DIEN vao bao cao.

Lenh:
  python run_experiments.py check                       # xem solver nao dung duoc
  python run_experiments.py info --member 1 --name "Nguyen Van A" --student-id 2402xxxx --email x@vnu.edu.vn --github https://github.com/u/bcp-sat
  python run_experiments.py info --member 2 --name "Tran Thi B" --student-id 2402yyyy --email y@vnu.edu.vn

  Thanh vien 1 (ma hoa va SAT solver), chay truoc:
  python run_experiments.py run --member 1 --profile smoke   # chay thu rat nhanh
  python run_experiments.py run --member 1 --profile quick   # 60 giay/lan, toan bo GEOM
  python run_experiments.py run --member 1 --profile full    # 3600 giay/lan, GEOM + MS-CAP
  python run_experiments.py run --member 1 --profile quick --sets GEOM-L --jobs 4

  Thanh vien 2 (ILP va CP), dung cung bo de va gioi han thoi gian cua Thanh vien 1:
  python run_experiments.py run --member 2 --jobs 4

  python run_experiments.py report      # chi tao lai bang/hinh/doan van tu ket qua da co
  python run_experiments.py reset       # tra bao cao ve trang thai chu do

Ket qua duoc luu dan vao report/results/runs_member1.csv va runs_member2.csv, chay lai
se BO QUA cac lan da xong. Bao cao chi het nhan "chua hoan thanh" khi ca hai phan da xong.
"""
import argparse, csv, glob, json, os, platform, re, shutil, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bcp_sat as S
from exact_models import EXACT_FN, bounds

ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPORT = os.path.join(ROOT, "report")
INST = os.path.join(ROOT, "instances")
RUNS = {1: os.path.join(REPORT, "results", "runs_member1.csv"), 2: os.path.join(REPORT, "results", "runs_member2.csv")}
META = {1: os.path.join(REPORT, "results", "meta_member1.json"), 2: os.path.join(REPORT, "results", "meta_member2.json")}
MEMBERS = os.path.join(REPORT, "results", "members.tex")
REFS = os.path.join(INST, "reference_values.csv")

ORDER_CFG = ["full", "no-sym", "pair", "non-inc"]
DIRECT_CFG = [f"direct-{k}" for k in S.AMO]
CFGS = ORDER_CFG + DIRECT_CFG
SIMPLE_CFG = "direct-pairwise"
SAT_SOLVERS = ["cadical195", "glucose4", "cms", "kissat"]
SAT_LABEL = {"cadical195": "CaDiCaL", "glucose4": "Glucose", "cms": "CryptoMiniSat", "kissat": "Kissat"}
EXACT = ["gurobi", "cplex-mip", "cplex-cp", "cpsat"]
EXACT_LABEL = {"gurobi": "Gurobi", "cplex-mip": "CPLEX MIP", "cplex-cp": "CPLEX CP", "cpsat": "OR-Tools CP-SAT"}
SET_ORDER = ["GEOM-S", "GEOM-M", "GEOM-L", "MS-CAP"]

PROFILES = {
    "smoke": dict(time_limit=5, sets=["GEOM-S"]),
    "quick": dict(time_limit=60, sets=["GEOM-S", "GEOM-M", "GEOM-L"]),
    "full":  dict(time_limit=3600, sets=SET_ORDER),
}

# =============================================================================
# 1. Instances
# =============================================================================
def instance_sets():
    sets = {k: [] for k in SET_ORDER}
    for p in sorted(glob.glob(os.path.join(INST, "GEOM", "*.col"))):
        size = int(re.match(r"GEOM(\d+)", os.path.basename(p)).group(1))
        sets["GEOM-S" if size <= 50 else "GEOM-M" if size <= 90 else "GEOM-L"].append(p)
    sets["MS-CAP"] = sorted(glob.glob(os.path.join(INST, "MS-CAP", "*.col")))
    return sets

def load_refs():
    if not os.path.exists(REFS): return {}
    return {r["instance"]: r for r in csv.DictReader(open(REFS))}

# =============================================================================
# 2. Worker: solve ONE instance with ONE method, print a JSON line
# =============================================================================
class TimeUp(Exception): pass

class CMSBackend(S.Backend):
    def __init__(self):
        from pycryptosat import Solver
        self.s = Solver(threads=1)
    def add(self, c): self.s.add_clause(c)
    def solve(self):
        ok, sol = self.s.solve()
        return [i for i, v in enumerate(sol) if v is True] if ok else None

class ExternalBackend(S.Backend):
    """Ghi DIMACS roi goi solver ngoai; exit 10 = SAT, 20 = UNSAT.
    Moi nguong la mot lan chay moi, nen khong giu menh de hoc duoc."""
    def __init__(self, exe, extra, nvars, deadline):
        self.exe, self.extra, self.nvars, self.deadline, self.cl = exe, extra, nvars, deadline, []
    def add(self, c): self.cl.append(c)
    def solve(self):
        fd, path = tempfile.mkstemp(suffix=".cnf"); os.close(fd)
        try:
            S.write_dimacs(path, self.cl, self.nvars)
            left = self.deadline - time.perf_counter()
            if left <= 0: raise TimeUp()
            try:
                p = subprocess.run([self.exe] + self.extra + [path], capture_output=True, text=True, timeout=left)
            except subprocess.TimeoutExpired:
                raise TimeUp()
            if p.returncode == 20: return None
            if p.returncode != 10:
                raise RuntimeError(f"{os.path.basename(self.exe)} exit {p.returncode}: {(p.stderr or p.stdout)[-200:]}")
            return [int(t) for line in p.stdout.splitlines() if line.startswith("v ")
                    for t in line[2:].split() if int(t) > 0]
        finally:
            os.remove(path)

def make_backend_factory(solver, a, deadline):
    if solver == "cms":
        if a.cms: return lambda nv: ExternalBackend(a.cms, ["--verb", "0", "--threads", "1"], nv, deadline)
        try:
            import pycryptosat  # noqa
            return lambda nv: CMSBackend()
        except ImportError:
            exe = shutil.which("cryptominisat5")
            if exe: return lambda nv: ExternalBackend(exe, ["--verb", "0", "--threads", "1"], nv, deadline)
            raise RuntimeError("không có pycryptosat và không tìm thấy cryptominisat5 (thêm --cms ĐƯỜNG_DẪN)")
    if solver == "kissat":
        exe = a.kissat or shutil.which("kissat")
        if not exe: raise RuntimeError("không tìm thấy kissat (thêm --kissat ĐƯỜNG_DẪN)")
        return lambda nv: ExternalBackend(exe, ["-q"], nv, deadline)
    return lambda nv: S.PySATBackend(solver)

def worker(a):
    g = S.read_col(a.instance); t0 = time.perf_counter(); deadline = t0 + a.time_limit
    H, lb = bounds(g)
    out = dict(status="ERR", span="", H=H, LB=lb, t_build=0, t_solve=0, t_total=0)
    def log(**kw):
        if a.progress:
            with open(a.progress, "a") as f: f.write(json.dumps(kw) + "\n")
    try:
        if a.method in EXACT_FN:
            col, opt, tb, ts, info = EXACT_FN[a.method](g, a.time_limit)
            out.update(info, t_build=tb, t_solve=ts, t_total=tb + ts)
            if col is None: out["status"] = "TO"
            elif not S.is_valid_coloring(g, col): out["status"] = "WRONG"
            else: out.update(status="OPT" if opt else "FEAS", span=max(col))
        else:
            _, solver, config = a.method.split(":")
            cfg = S.CONFIGS[config]; state = {}
            def built(r):
                state.update(vars=r["vars"], clauses=r["clauses"], t_build=r["t_build"]); log(vars=r["vars"], clauses=r["clauses"], t_build=r["t_build"])
            def inc(b):
                state["span"] = b; log(span=b, t=time.perf_counter() - t0)
            try:
                r = S.search(g, cfg, make_backend_factory(solver, a, deadline), on_incumbent=inc, on_built=built)
                total = time.perf_counter() - t0
                out.update(vars=r["vars"], clauses=r["clauses"], t_build=r["t_build"], t_solve=total - r["t_build"], t_total=total,
                           span=r["span"] if r["span"] else "", calls=r["calls"])
                out["status"] = {"OPTIMAL": "OPT", "WRONG": "WRONG"}.get(r["status"], "ERR")
            except TimeUp:
                out.update(vars=state.get("vars", ""), clauses=state.get("clauses", ""), t_build=state.get("t_build", 0),
                           span=state.get("span", ""), t_total=a.time_limit, status="FEAS" if state.get("span") else "TO")
        if out["t_total"] > a.time_limit and out["status"] == "OPT":
            out["status"] = "FEAS" if out["span"] else "TO"
    except MemoryError:
        out.update(status="MO", msg="hết bộ nhớ")
    except Exception as e:
        out.update(status="ERR", msg=f"{type(e).__name__}: {e}"[:300])
    print(json.dumps(out))

# =============================================================================
# 3. Running
# =============================================================================
FIELDS = ["set", "instance", "method", "time_limit", "status", "span", "H", "LB", "t_build", "t_solve", "t_total", "vars", "clauses", "msg"]
_lock = threading.Lock()

def load_runs():
    rows = []
    for path in RUNS.values():
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                rows += list(csv.DictReader(f))
    for r in rows:
        for k in ("t_build", "t_solve", "t_total", "time_limit"): r[k] = float(r[k] or 0)
        r["span"] = int(r["span"]) if r["span"] else None
    return rows

def append_run(row):
    path = RUNS[1 if row["method"].startswith("sat:") else 2]
    with _lock:
        new = not os.path.exists(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new: w.writeheader()
            w.writerow({k: row.get(k, "") for k in FIELDS})

def run_one(method, inst, T, paths):
    """Moi lan chay la mot tien trinh rieng; qua gio thi bi dung va doc nghiem tot nhat tu file tien do."""
    fd, prog = tempfile.mkstemp(suffix=".jsonl"); os.close(fd)
    cmd = [sys.executable, os.path.abspath(__file__), "worker", "--method", method, "--instance", inst,
           "--time-limit", str(T), "--progress", prog]
    for k in ("cms", "kissat"):
        if paths.get(k): cmd += [f"--{k}", paths[k]]
    grace = 2 if method.startswith("sat:") else 30
    try:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=T + grace)
            line = [l for l in p.stdout.splitlines() if l.startswith("{")]
            if line: return json.loads(line[-1])
            err = (p.stderr or "").strip().splitlines()
            return dict(status="MO" if any("MemoryError" in l for l in err) else "ERR", t_total=0, msg=(err[-1] if err else f"exit {p.returncode}")[:300])
        except subprocess.TimeoutExpired:
            out = dict(status="TO", t_total=T, t_solve=T, span="")
            for l in open(prog):
                d = json.loads(l)
                if "span" in d: out.update(status="FEAS", span=d["span"])
                else: out.update(d)
            g = S.read_col(inst); out.update(H=max(S.first_fit(g)), LB=S.lower_bound(g))
            return out
    finally:
        try: os.remove(prog)
        except OSError: pass

def tiny_path():
    os.makedirs(INST, exist_ok=True); p = os.path.join(INST, "_tiny.col")
    if not os.path.exists(p): S.write_col(p, S.EXAMPLE)
    return p

def _available(methods, labels, paths, verbose):
    ok_list = []
    for key, method in methods:
        r = run_one(method, tiny_path(), 30, paths); ok = r["status"] == "OPT" and r.get("span") == 6
        if ok: ok_list.append(key)
        if verbose: print(f"  {'OK ' if ok else '-- '} {labels[key]:16s} {'' if ok else str(r.get('msg', r['status']))[:100]}")
    return ok_list

def available_sat(paths, verbose=True):
    return _available([(s, f"sat:{s}:full") for s in SAT_SOLVERS], SAT_LABEL, paths, verbose)

def available_exact(paths, verbose=True):
    return _available([(m, m) for m in EXACT], EXACT_LABEL, paths, verbose)

def run_batch(jobs, T, njobs, paths, done):
    rel = lambda i: os.path.relpath(i, ROOT).replace("\\", "/")
    todo = [(s, i, m) for (s, i, m) in jobs if (rel(i), m, float(T)) not in done]
    print(f"  {len(jobs)} lần chạy, {len(jobs)-len(todo)} đã có kết quả, còn {len(todo)}")
    cnt = [0]
    def go(job):
        s, i, m = job
        r = run_one(m, i, T, paths)
        r.update(set=s, instance=os.path.relpath(i, ROOT).replace("\\", "/"), method=m, time_limit=T)
        append_run(r); done.add((r["instance"], m, float(T)))
        with _lock:
            cnt[0] += 1
            print(f"  [{cnt[0]}/{len(todo)}] {s:7s} {os.path.basename(i):16s} {m:30s} {r['status']:5s} span={str(r.get('span','')):>4s} {r.get('t_total',0):8.2f}s")
    with ThreadPoolExecutor(max_workers=njobs) as ex:
        list(ex.map(go, todo))

def stats(rows, method, set_, T):
    rs = [r for r in rows if r["method"] == method and r["set"] == set_ and r["time_limit"] == T]
    if not rs: return None
    opt = [r for r in rs if r["status"] == "OPT"]
    return dict(opt=len(opt), feas=sum(r["status"] == "FEAS" for r in rs), to=sum(r["status"] in ("TO", "MO", "ERR") for r in rs),
                total=len(rs), wrong=sum(r["status"] == "WRONG" for r in rs),
                par2=sum(r["t_total"] if r["status"] == "OPT" else 2 * T for r in rs) / len(rs),
                build=sum(r["t_build"] for r in opt), solve=sum(r["t_solve"] for r in opt))

def better(a, b):
    """True neu a tot hon b: chung nhan toi uu nhieu hon, roi PAR-2 nho hon."""
    if b is None: return a is not None
    if a is None: return False
    return (a["opt"], -a["par2"]) > (b["opt"], -b["par2"])

def total(rows, method, sets, T):
    agg = dict(opt=0, feas=0, to=0, total=0, par2=0.0)
    for s in sets:
        st = stats(rows, method, s, T)
        if st:
            for k in agg: agg[k] += st[k]
    return agg

def key_total(rows, method, sets, T):
    t = total(rows, method, sets, T)
    return (t["opt"], -t["par2"]) if t["total"] else (-1, 0)

def cmd_run(a):
    return run_member1(a) if a.member == 1 else run_member2(a)

def run_member1(a):
    """Thanh vien 1: cac cau hinh ma hoa va cac SAT solver."""
    prof = PROFILES[a.profile]; T = float(a.time_limit or prof["time_limit"])
    all_sets = instance_sets()
    names = a.sets or prof["sets"]
    unknown = [s for s in names if s not in all_sets]
    if unknown: sys.exit(f"--sets {unknown}: không có bộ này. Các bộ hợp lệ: {SET_ORDER}")
    sets = {s: all_sets[s] for s in SET_ORDER if s in names and all_sets[s]}
    paths = {"cms": a.cms, "kissat": a.kissat}
    print("1) Bộ dữ liệu:"); [print(f"  {k}: {len(v)} đề") for k, v in sets.items()]
    print("2) Kiểm tra SAT solver ...")
    sat_ok = available_sat(paths)
    if not sat_ok: sys.exit("Không có SAT solver nào chạy được. Hãy cài python-sat.")
    done = {(r["instance"], r["method"], r["time_limit"]) for r in load_runs()}
    fixed = sat_ok[0]
    print(f"3) Thí nghiệm A: {len(CFGS)} cấu hình mã hóa với {SAT_LABEL[fixed]}")
    run_batch([(s, i, f"sat:{fixed}:{c}") for s in sets for c in CFGS for i in sets[s]], T, a.jobs, paths, done)
    rows = load_runs()
    best_cfg = max(CFGS, key=lambda c: key_total(rows, f"sat:{fixed}:{c}", list(sets), T))
    print(f"   -> cấu hình tốt nhất: {best_cfg}")
    print(f"4) Thí nghiệm B: các SAT solver {sat_ok} với {best_cfg} và {SIMPLE_CFG}")
    cfgs = [best_cfg] + ([SIMPLE_CFG] if best_cfg != SIMPLE_CFG else [])
    run_batch([(s, i, f"sat:{x}:{c}") for c in cfgs for x in sat_ok for s in sets for i in sets[s]], T, a.jobs, paths, done)
    rows = load_runs()
    best_sat = max(sat_ok, key=lambda x: key_total(rows, f"sat:{x}:{best_cfg}", list(sets), T))
    print(f"   -> SAT solver tốt nhất: {best_sat}")
    meta = dict(profile=a.profile, time_limit=T, sets={k: len(v) for k, v in sets.items()}, fixed=fixed, best_cfg=best_cfg,
                best_sat=best_sat, sat_ok=sat_ok, jobs=a.jobs, cms=a.cms, kissat=a.kissat, machine=machine_info())
    os.makedirs(os.path.dirname(META[1]), exist_ok=True)
    json.dump(meta, open(META[1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("5) Tạo bảng, hình và đoạn văn cho báo cáo ...")
    cmd_report(a)
    print("Xong phần Thành viên 1. Gửi report/results/runs_member1.csv và meta_member1.json cho Thành viên 2.")

def run_member2(a):
    """Thanh vien 2: ILP va CP, cung bo de va gioi han thoi gian voi Thanh vien 1."""
    if not os.path.exists(META[1]):
        sys.exit("Chưa có kết quả của Thành viên 1 (report/results/meta_member1.json). Thành viên 2 cần file này để dùng đúng bộ đề và giới hạn thời gian.")
    m1 = json.load(open(META[1], encoding="utf-8")); T = float(m1["time_limit"])
    all_sets = instance_sets(); sets = {s: all_sets[s] for s in m1["sets"]}
    print(f"1) Dùng cấu hình của Thành viên 1: các bộ {list(sets)}, giới hạn {T:g} giây")
    print("2) Kiểm tra solver ILP và CP ...")
    exact_ok = available_exact({})
    if not exact_ok: sys.exit("Không có solver ILP hay CP nào chạy được, chưa thể hoàn thành phần Thành viên 2. Hãy cài ortools, gurobipy hoặc docplex.")
    done = {(r["instance"], r["method"], r["time_limit"]) for r in load_runs()}
    print(f"3) Thí nghiệm C: {[EXACT_LABEL[m] for m in exact_ok]}")
    run_batch([(s, i, m) for m in exact_ok for s in sets for i in sets[s]], T, a.jobs, {}, done)
    json.dump(dict(time_limit=T, exact_ok=exact_ok, jobs=a.jobs, machine=machine_info()), open(META[2], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("4) Tạo bảng, hình và đoạn văn cho báo cáo ...")
    cmd_report(a)
    print("Xong phần Thành viên 2.")

# =============================================================================
# 4. Report generation
# =============================================================================
def tex_escape(s):
    s = str(s)
    for k, v in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")):
        s = s.replace(k, v)
    return s

def vn(x, d=2):
    """So kieu Viet Nam: 1.234,56"""
    s = f"{x:,.{d}f}" if d else f"{int(round(x)):,}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def cell(st, best=False):
    if st is None: return "--"
    t = f"{st['opt']}/{st['total']} ({vn(st['par2'], 2 if st['par2'] < 100 else 1)})"
    if st["wrong"]: t += r"$^{!}$"
    return r"\textbf{" + t + "}" if best else t

def machine_info():
    cpu = platform.processor() or ""
    try:
        if sys.platform.startswith("linux"):
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"): cpu = line.split(":", 1)[1].strip(); break
        elif sys.platform == "darwin":
            cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip() or cpu
    except Exception: pass
    ram = None
    try:
        import psutil; ram = psutil.virtual_memory().total
    except Exception:
        try:
            for line in open("/proc/meminfo"):
                if line.startswith("MemTotal"): ram = int(line.split()[1]) * 1024; break
        except Exception: pass
    return dict(cpu=cpu or "không xác định", cores=os.cpu_count(), ram=f"{ram/2**30:.0f} GB" if ram else "không xác định",
                os=f"{platform.system()} {platform.release()}", python=platform.python_version())

def solver_versions(meta):
    v = {}
    def tryv(key, fn):
        try: v[key] = str(fn()).strip().splitlines()[0]
        except Exception: v[key] = None
    tryv("pysat", lambda: __import__("pysat").__version__)
    v["cadical195"] = "1.9.5" + (f" (PySAT {v['pysat']})" if v.get("pysat") else "")
    v["glucose4"] = "4.1" + (f" (PySAT {v['pysat']})" if v.get("pysat") else "")
    if meta.get("cms"):
        tryv("cms", lambda: subprocess.run([meta["cms"], "--version"], capture_output=True, text=True).stdout)
    else:
        tryv("cms", lambda: "pycryptosat " + __import__("pycryptosat").__version__)
    exe = meta.get("kissat") or shutil.which("kissat")
    tryv("kissat", lambda: subprocess.run([exe, "--version"], capture_output=True, text=True).stdout)
    tryv("cpsat", lambda: "OR-Tools " + __import__("ortools").__version__)
    tryv("gurobi", lambda: ".".join(map(str, __import__("gurobipy").gurobi.version())))
    tryv("cplex-mip", lambda: "docplex " + __import__("docplex").__version__)
    v["cplex-cp"] = v["cplex-mip"]
    return v

def solvers_table(ver=None, sat_ok=(), exact_ok=()):
    td = r"\TODO{\,}"
    def vc(k, ok): return (tex_escape(ver.get(k) or "--") if ok else "không chạy") if ver is not None else td
    def vx(k): return td if exact_ok is None else vc(k, k in exact_ok)
    cms_how = r"\texttt{pycryptosat} hoặc file chạy \texttt{cryptominisat5}"
    return "\n".join([
        r"\begin{tabular}{lll}", r"\toprule", r"Solver & Cách gọi & Phiên bản\\", r"\midrule",
        r"CaDiCaL & PySAT~\citep{ignatiev2018} (\texttt{cadical195}), tăng dần & " + vc("cadical195", "cadical195" in sat_ok) + r"\\",
        r"Glucose & PySAT~\citep{ignatiev2018} (\texttt{glucose4}), tăng dần & " + vc("glucose4", "glucose4" in sat_ok) + r"\\",
        r"CryptoMiniSat & " + cms_how + " & " + vc("cms", "cms" in sat_ok) + r"\\",
        r"Kissat & file chạy, DIMACS, không tăng dần & " + vc("kissat", "kissat" in sat_ok) + r"\\",
        r"\midrule",
        r"Gurobi~\citep{gurobi} & \texttt{gurobipy}, mô hình ILP & " + vx("gurobi") + r"\\",
        r"CPLEX MIP~\citep{cplex} & \texttt{docplex.mp}, mô hình ILP & " + vx("cplex-mip") + r"\\",
        r"CPLEX CP~\citep{cplex} & \texttt{docplex.cp}, mô hình CP & " + vx("cplex-cp") + r"\\",
        r"OR-Tools CP-SAT~\citep{cpsat} & \texttt{ortools}, mô hình CP & " + vx("cpsat") + r"\\",
        r"\bottomrule", r"\end{tabular}"]) + "\n"

def bench_table(sets):
    all_sets = instance_sets()
    src = {k: r"\citet{nguyen2026bcp}" for k in SET_ORDER}
    B = [r"\begin{tabular}{llcccc}", r"\toprule", r"Bộ & Nguồn & Số đề & $n$ & $|E|$ & $d_{\max}$\\", r"\midrule"]
    for s in sets:
        gs = [S.read_col(p) for p in all_sets[s]]
        ns, es = [g.n for g in gs], [len(g.edges) for g in gs]
        dm = max(d for g in gs for _, _, d in g.edges)
        B.append(f"{s} & {src[s]} & {len(gs)} & {min(ns)}--{max(ns)} & {min(es)}--{max(es)} & {dm}" + r"\\")
    B += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(B) + "\n"

def cmd_report(a=None):
    rows = load_runs()
    if not rows or not os.path.exists(META[1]):
        sys.exit("Chưa có kết quả của Thành viên 1. Hãy chạy: python run_experiments.py run --member 1 --profile quick")
    meta = json.load(open(META[1], encoding="utf-8")); T = float(meta["time_limit"])
    has_m2 = False
    if os.path.exists(META[2]):
        m2 = json.load(open(META[2], encoding="utf-8"))
        if float(m2["time_limit"]) == T: has_m2 = True; meta["exact_ok"] = m2["exact_ok"]
        else: print("  ! Kết quả của Thành viên 2 dùng giới hạn thời gian khác, cần chạy lại --member 2.")
    if not has_m2: meta["exact_ok"] = []
    write_members(True, has_m2)
    sets = list(meta["sets"]); fixed = meta["fixed"]; bc = meta["best_cfg"]; bs = meta["best_sat"]
    tdir = os.path.join(REPORT, "tables"); os.makedirs(tdir, exist_ok=True)
    W = lambda name, txt: open(os.path.join(tdir, name), "w", encoding="utf-8").write(txt)
    refs = load_refs()

    # ---- Bang A: cac cau hinh ma hoa voi solver co dinh
    best = {}
    for s in sets:
        b = None
        for c in CFGS:
            if better(stats(rows, f"sat:{fixed}:{c}", s, T), stats(rows, f"sat:{fixed}:{b}", s, T) if b else None): b = c
        best[s] = b
    L = [r"\begin{tabular}{l" + "c" * len(sets) + "}", r"\toprule", "Cấu hình & " + " & ".join(sets) + r" \\", r"\midrule"]
    for i, c in enumerate(CFGS):
        if i == len(ORDER_CFG): L.append(r"\midrule")
        L.append(r"\texttt{" + c + "} & " + " & ".join(cell(stats(rows, f"sat:{fixed}:{c}", s, T), best[s] == c) for s in sets) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_cfg.tex", "\n".join(L) + "\n")

    # ---- Bang B: cac SAT solver
    solvers = [x for x in SAT_SOLVERS if any(r["method"] == f"sat:{x}:{bc}" for r in rows)]
    cfgs = [bc] + ([SIMPLE_CFG] if bc != SIMPLE_CFG else [])
    L = [r"\begin{tabular}{ll" + "c" * len(sets) + "}", r"\toprule", "Cấu hình & Solver & " + " & ".join(sets) + r" \\", r"\midrule"]
    for ci, c in enumerate(cfgs):
        bb = {}
        for s in sets:
            b = None
            for x in solvers:
                if better(stats(rows, f"sat:{x}:{c}", s, T), stats(rows, f"sat:{b}:{c}", s, T) if b else None): b = x
            bb[s] = b
        for j, x in enumerate(solvers):
            first = (r"\multirow{" + str(len(solvers)) + r"}{*}{\texttt{" + c + "}}") if j == 0 else ""
            L.append(f"{first} & {SAT_LABEL[x]} & " + " & ".join(cell(stats(rows, f"sat:{x}:{c}", s, T), bb[s] == x) for s in sets) + r" \\")
        if ci < len(cfgs) - 1: L.append(r"\midrule")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_solvers.tex", "\n".join(L) + "\n")

    ver = solver_versions(meta)
    W("solvers.tex", solvers_table(ver, meta["sat_ok"], meta["exact_ok"] if has_m2 else None))
    W("bench.tex", bench_table(sets))

    # ---- Bang C: SAT tot nhat so voi ILP, CP
    sat_m = f"sat:{bs}:{bc}"; sat_lab = f"SAT ({SAT_LABEL[bs]}, {bc})"
    methods = [sat_m] + meta["exact_ok"]; labels = [sat_lab] + [EXACT_LABEL[m] for m in meta["exact_ok"]]
    bestC = {}
    for s in sets:
        b = None
        for m in methods:
            if better(stats(rows, m, s, T), stats(rows, b, s, T) if b else None): b = m
        bestC[s] = b
    L = [r"\begin{tabular}{l" + "c" * len(sets) + "}", r"\toprule", "Phương pháp & " + " & ".join(sets) + r" \\", r"\midrule"]
    for m, l in zip(methods, labels):
        L.append(tex_escape(l) + " & " + " & ".join(cell(stats(rows, m, s, T), bestC[s] == m) for s in sets) + r" \\")
    for m in EXACT:
        if m not in meta["exact_ok"]:
            L.append(EXACT_LABEL[m] + " & " + " & ".join(["không chạy" if has_m2 else r"\textcolor{red}{\textbf{--}}"] * len(sets)) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_base.tex", "\n".join(L) + "\n")

    # ---- Bang chi tiet tung de + doi chieu voi gia tri tham chieu
    by = {(r["instance"], r["method"]): r for r in rows if r["time_limit"] == T}
    all_sets = instance_sets(); mismatch = []
    D = [r"\begin{longtable}{lrrc" + "c" * len(methods) + "}",
         r"\caption{Kết quả từng đề. Dấu $^{*}$: đã chứng nhận tối ưu, kèm thời gian (giây); FEAS: hết giờ khi đang có nghiệm; TO: hết giờ, chưa có nghiệm. Cột ``TK'' là giá trị tham khảo từ dữ liệu của~\citet{nguyen2026bcp}.}\label{tab:detail}\\",
         r"\toprule"]
    head = r"Đề & $n$ & $|E|$ & TK & " + " & ".join(("SAT" if m == sat_m else EXACT_LABEL[m].replace("OR-Tools ", "")) for m in methods) + r" \\"
    D += [head, r"\midrule", r"\endfirsthead", r"\toprule", head, r"\midrule", r"\endhead", r"\bottomrule", r"\endlastfoot"]
    for s in sets:
        for p in all_sets[s]:
            rel = os.path.relpath(p, ROOT).replace("\\", "/"); g = S.read_col(p); ref = refs.get(g.name, {})
            cs = []
            for m in methods:
                r = by.get((rel, m))
                if not r: cs.append("--")
                elif r["status"] == "OPT":
                    cs.append(f"{r['span']}$^{{*}}$ ({vn(r['t_total'], 1)})")
                    if ref.get("proved_optimal") == "1" and str(r["span"]) != ref["reference_span"]: mismatch.append((g.name, m, r["span"], ref["reference_span"]))
                elif r["status"] == "FEAS": cs.append(f"{r['span']} (FEAS)")
                else: cs.append(r["status"])
            D.append(f"{tex_escape(g.name)} & {g.n} & {len(g.edges)} & {ref.get('reference_span', '--')} & " + " & ".join(cs) + r" \\")
    D.append(r"\end{longtable}"); W("res_detail.tex", "\n".join(D) + "\n")

    # ---- cactus
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        plt.rcParams.update({"font.size": 8, "font.family": "serif"})
        fig, ax = plt.subplots(figsize=(5.2, 3.0))
        for x in solvers:
            ts = sorted(r["t_total"] for r in rows if r["method"] == f"sat:{x}:{bc}" and r["time_limit"] == T and r["status"] == "OPT")
            if ts: ax.plot(range(1, len(ts) + 1), ts, marker=".", ms=3, lw=1, label=f"{SAT_LABEL[x]} ({bc})")
        for m in meta["exact_ok"]:
            ts = sorted(r["t_total"] for r in rows if r["method"] == m and r["time_limit"] == T and r["status"] == "OPT")
            if ts: ax.plot(range(1, len(ts) + 1), ts, marker="x", ms=3, lw=1, ls="--", label=EXACT_LABEL[m])
        ax.set_yscale("log"); ax.set_xlabel("Số đề chứng nhận tối ưu"); ax.set_ylabel("Thời gian (giây)")
        ax.axhline(T, color="gray", ls="--", lw=0.8); ax.grid(alpha=.3); ax.legend(fontsize=7, frameon=False)
        plt.tight_layout(); os.makedirs(os.path.join(REPORT, "figures"), exist_ok=True)
        plt.savefig(os.path.join(REPORT, "figures", "cactus.pdf")); plt.close()
    except Exception as e:
        print("  ! không vẽ được cactus:", e)

    # ---- doan van tu dong
    mi = meta.get("machine") or machine_info(); tot = lambda m, ss=sets: total(rows, m, ss, T)
    ranked = sorted(CFGS, key=lambda c: (-tot(f"sat:{fixed}:{c}")["opt"], tot(f"sat:{fixed}:{c}")["par2"]))
    cb, cw = ranked[0], ranked[-1]; tb, tw = tot(f"sat:{fixed}:{cb}"), tot(f"sat:{fixed}:{cw}")
    def diff(x, y):
        a_, b_ = tot(f"sat:{fixed}:{x}"), tot(f"sat:{fixed}:{y}")
        return f"\\texttt{{{y}}} đạt {b_['opt']}/{b_['total']} đề, tổng PAR-2 {vn(b_['par2'])} giây"
    amos = sorted(DIRECT_CFG, key=lambda c: (-tot(f"sat:{fixed}:{c}")["opt"], tot(f"sat:{fixed}:{c}")["par2"]))
    cfg_txt = (f"Với {SAT_LABEL[fixed]}, cấu hình tốt nhất là \\texttt{{{cb}}}: chứng nhận tối ưu {tb['opt']}/{tb['total']} đề, tổng PAR-2 trên các bộ là {vn(tb['par2'])} giây. "
               f"Cấu hình kém nhất là \\texttt{{{cw}}} ({tw['opt']}/{tw['total']} đề, tổng PAR-2 {vn(tw['par2'])} giây). "
               f"So với \\texttt{{full}} ({tot(f'sat:{fixed}:full')['opt']}/{tot(f'sat:{fixed}:full')['total']} đề): " + "; ".join(diff("full", c) for c in ("no-sym", "pair", "non-inc")) + ". "
               f"Trong năm cấu hình \\texttt{{direct}}, thứ tự từ tốt đến kém là " + ", ".join(S.AMO_LABEL[c.split('-')[1]] for c in amos) + ".")
    rank = sorted(solvers, key=lambda x: (-tot(f"sat:{x}:{bc}")["opt"], tot(f"sat:{x}:{bc}")["par2"]))
    solver_txt = (f"Với cấu hình \\texttt{{{bc}}}, xếp theo số đề chứng nhận tối ưu rồi đến PAR-2, thứ tự các solver là "
                  + ", ".join(f"{SAT_LABEL[x]} ({tot(f'sat:{x}:{bc}')['opt']}/{tot(f'sat:{x}:{bc}')['total']})" for x in rank) + ".")
    miss = [SAT_LABEL[x] for x in SAT_SOLVERS if x not in meta["sat_ok"]]
    if miss: solver_txt += f" Không chạy được trên máy thử nghiệm: {', '.join(miss)}."
    def share(m):
        st = [stats(rows, m, s, T) for s in sets]; b_ = sum(x["build"] for x in st if x); s_ = sum(x["solve"] for x in st if x)
        return 100 * b_ / (b_ + s_) if b_ + s_ > 0 else 0
    largest = sets[-1] if sets[-1] != "MS-CAP" or len(sets) == 1 else sets[-2]
    sc = stats(rows, sat_m, largest, T)
    scale_txt = (f"Trên bộ lớn nhất ({largest}), {sat_lab} chứng nhận tối ưu {sc['opt']}/{sc['total']} đề trong giới hạn {vn(T, 0)} giây. "
                 f"Thời gian sinh công thức chiếm {vn(share(sat_m), 0)}\\% tổng thời gian của các đề đã chứng nhận. ")
    bad = [r for r in rows if r["status"] in ("MO", "ERR", "WRONG") and r["time_limit"] == T]
    if bad: scale_txt += f"Có {len(bad)} lần chạy lỗi hoặc hết bộ nhớ (xem cột msg trong \\texttt{{results/runs.csv}}). "
    if any(r["status"] == "WRONG" for r in bad): scale_txt += r"\textcolor{red}{Có lời giải sai (đánh dấu $^{!}$ trong bảng), cần kiểm tra lại code.} "
    if mismatch:
        scale_txt += r"\textcolor{red}{" + f"Có {len(mismatch)} giá trị tối ưu khác giá trị tham khảo: {tex_escape(str(mismatch[:3]))}; cần kiểm tra lại." + "} "
    else:
        n_chk = sum(1 for (i, m), r in by.items() if r["status"] == "OPT" and refs.get(os.path.splitext(os.path.basename(i))[0], {}).get("proved_optimal") == "1")
        scale_txt += f"Cả {n_chk} giá trị được chứng nhận tối ưu trong bài đều trùng với giá trị tham khảo của~\\citet{{nguyen2026bcp}}. "
    bt = tot(sat_m)
    if not has_m2:
        cmp_txt = PLACEHOLDER_TEXT["AutoCompare"]; sent = ""
    elif meta["exact_ok"]:
        parts = [f"{EXACT_LABEL[m]} {tot(m)['opt']}/{tot(m)['total']} đề (tổng PAR-2 {vn(tot(m)['par2'])} giây)" for m in meta["exact_ok"]]
        win = [m for m in meta["exact_ok"] if (tot(m)["opt"], -tot(m)["par2"]) > (bt["opt"], -bt["par2"])]
        cmp_txt = (f"Trên toàn bộ dữ liệu, {sat_lab} chứng nhận tối ưu {bt['opt']}/{bt['total']} đề (tổng PAR-2 {vn(bt['par2'])} giây); " + "; ".join(parts) + ". "
                   + (f"Tốt hơn cách SAT theo tiêu chí này: {', '.join(EXACT_LABEL[m] for m in win)}." if win else "Cách SAT đứng đầu theo tiêu chí này."))
        notrun = [EXACT_LABEL[m] for m in EXACT if m not in meta["exact_ok"]]
        if notrun: cmp_txt += f" Không chạy được trên máy thử nghiệm: {', '.join(notrun)}."
        sent = " So với các solver ILP và CP: " + "; ".join(parts) + "."
    else:
        cmp_txt = "Gurobi, CPLEX và CP-SAT không chạy được trên máy thử nghiệm, nên chưa có số liệu so sánh."; sent = ""
    n_all = sum(meta["sets"].values())
    abs_txt = (f"Trên {n_all} đề với giới hạn {vn(T, 0)} giây, cấu hình tốt nhất là \\texttt{{{bc}}} và {SAT_LABEL[bs]} là SAT solver tốt nhất, "
               f"chứng nhận tối ưu {bt['opt']}/{bt['total']} đề." + sent)
    scope = "trên các bộ " + ", ".join(sets)
    def M(name, val): return f"\\renewcommand{{\\{name}}}{{{val}}}\n"
    txt = ("% TU DONG SINH boi run_experiments.py -- hay doc lai va sua cho tu nhien.\n"
           + M("MachineCPU", tex_escape(mi["cpu"])) + M("MachineCores", mi["cores"]) + M("MachineRAM", tex_escape(mi["ram"]))
           + M("MachineOS", tex_escape(mi["os"])) + M("PythonVersion", mi["python"]) + M("TimeLimit", vn(T, 0))
           + M("RepeatText", "Mỗi đề chạy một lần với mỗi cấu hình" + (f", chạy song song {meta['jobs']} tiến trình" if meta["jobs"] > 1 else "") + ".")
           + M("FixedSolver", SAT_LABEL[fixed]) + M("BestConfig", r"\texttt{" + bc + "}") + M("BestSolver", SAT_LABEL[bs]) + M("DataScope", scope)
           + M("AutoAbstract", abs_txt) + M("AutoCfg", cfg_txt) + M("AutoSolvers", solver_txt) + M("AutoScale", scale_txt)
           + M("AutoCompare", cmp_txt) + M("AutoConclusion", abs_txt))
    open(os.path.join(REPORT, "results", "auto_text.tex"), "w", encoding="utf-8").write(txt)
    print("  đã ghi tables/res_*.tex, tables/solvers.tex, tables/bench.tex, figures/cactus.pdf, results/auto_text.tex")

# =============================================================================
# 5. Placeholders (reset) and author info
# =============================================================================
PLACEHOLDER_TEXT = {
    "MachineCPU": r"\TODO{CPU}", "MachineCores": r"\TODO{số luồng}", "MachineRAM": r"\TODO{RAM}",
    "MachineOS": r"\TODO{hệ điều hành}", "PythonVersion": r"\TODO{phiên bản}", "TimeLimit": r"\TODO{giới hạn}",
    "RepeatText": r"\TODO{Ghi số lần chạy lặp.}", "FixedSolver": r"\TODO{solver cố định}",
    "BestConfig": r"\TODO{cấu hình tốt nhất}", "BestSolver": r"\TODO{solver tốt nhất}",
    "DataScope": r"trên \TODO{các bộ đã chạy}",
    "AutoAbstract": r"\TODO{Viết 1--2 câu về kết quả thực nghiệm chính.}",
    "AutoCfg": r"\TODO{Nhận xét: cấu hình nào chứng nhận được nhiều đề nhất; ảnh hưởng của phá đối xứng, mã hóa khoảng và giải tăng dần; thứ tự các AMO.}",
    "AutoSolvers": r"\TODO{Nhận xét thứ hạng các SAT solver.}",
    "AutoScale": r"\TODO{Ghi kết quả trên bộ lớn nhất; tỉ lệ thời gian sinh công thức; các lần chạy lỗi; đối chiếu với giá trị tham khảo.}",
    "AutoCompare": r"\TODO{Nhận xét SAT so với Gurobi, CPLEX MIP, CPLEX CP và CP-SAT.}",
    "AutoConclusion": r"\TODO{Tóm tắt kết quả thực nghiệm.}",
}

def write_members(one, two):
    os.makedirs(os.path.dirname(MEMBERS), exist_ok=True)
    open(MEMBERS, "w", encoding="utf-8").write("% TU DONG SINH: phan thuc nghiem cua moi thanh vien da xong chua\n"
        + ("\\MemberOneDonetrue\n" if one else "\\MemberOneDonefalse\n") + ("\\MemberTwoDonetrue\n" if two else "\\MemberTwoDonefalse\n"))

def cmd_reset(a=None):
    tdir = os.path.join(REPORT, "tables"); os.makedirs(tdir, exist_ok=True)
    os.makedirs(os.path.join(REPORT, "results"), exist_ok=True)
    txt = "% CHO TRONG -- se bi ghi de khi chay run_experiments.py run\n" + "".join(
        f"\\renewcommand{{\\{k}}}{{{v}}}\n" for k, v in PLACEHOLDER_TEXT.items())
    open(os.path.join(REPORT, "results", "auto_text.tex"), "w", encoding="utf-8").write(txt)
    t = r"\textcolor{red}{\textbf{--}}"
    W = lambda name, s: open(os.path.join(tdir, name), "w", encoding="utf-8").write(s)
    sets = SET_ORDER
    L = [r"\begin{tabular}{l" + "c" * len(sets) + "}", r"\toprule", "Cấu hình & " + " & ".join(sets) + r" \\", r"\midrule"]
    for i, c in enumerate(CFGS):
        if i == len(ORDER_CFG): L.append(r"\midrule")
        L.append(r"\texttt{" + c + "} & " + " & ".join([t] * len(sets)) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_cfg.tex", "\n".join(L) + "\n")
    L = [r"\begin{tabular}{ll" + "c" * len(sets) + "}", r"\toprule", "Cấu hình & Solver & " + " & ".join(sets) + r" \\", r"\midrule"]
    for ci, cname in enumerate([r"\TODO{tốt nhất}", r"\texttt{" + SIMPLE_CFG + "}"]):
        for j, x in enumerate(SAT_SOLVERS):
            L.append(((r"\multirow{" + str(len(SAT_SOLVERS)) + r"}{*}{" + cname + "}") if j == 0 else "") + f" & {SAT_LABEL[x]} & " + " & ".join([t] * len(sets)) + r" \\")
        if ci == 0: L.append(r"\midrule")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_solvers.tex", "\n".join(L) + "\n")
    W("solvers.tex", solvers_table())
    W("bench.tex", bench_table(SET_ORDER))
    L = [r"\begin{tabular}{l" + "c" * len(sets) + "}", r"\toprule", "Phương pháp & " + " & ".join(sets) + r" \\", r"\midrule",
         r"SAT (\TODO{solver + cấu hình tốt nhất}) & " + " & ".join([t] * len(sets)) + r" \\"]
    for m in EXACT: L.append(EXACT_LABEL[m] + " & " + " & ".join([t] * len(sets)) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]; W("res_base.tex", "\n".join(L) + "\n")
    refs = load_refs(); all_sets = instance_sets()
    D = [r"\begin{longtable}{lrrcccccc}",
         r"\caption{Kết quả từng đề. Dấu $^{*}$: đã chứng nhận tối ưu, kèm thời gian (giây); FEAS: hết giờ khi đang có nghiệm; TO: hết giờ, chưa có nghiệm. Cột ``TK'' là giá trị tham khảo từ dữ liệu của~\citet{nguyen2026bcp}.}\label{tab:detail}\\",
         r"\toprule"]
    head = r"Đề & $n$ & $|E|$ & TK & SAT & Gurobi & CPLEX MIP & CPLEX CP & CP-SAT \\"
    D += [head, r"\midrule", r"\endfirsthead", r"\toprule", head, r"\midrule", r"\endhead", r"\bottomrule", r"\endlastfoot"]
    for s in sets:
        for p in all_sets[s]:
            g = S.read_col(p)
            D.append(f"{tex_escape(g.name)} & {g.n} & {len(g.edges)} & {refs.get(g.name, {}).get('reference_span', '--')} & " + " & ".join([t] * 5) + r" \\")
    D.append(r"\end{longtable}"); W("res_detail.tex", "\n".join(D) + "\n")
    cp = os.path.join(REPORT, "figures", "cactus.pdf")
    if os.path.exists(cp): os.remove(cp)
    write_members(False, False)
    print("Đã đưa báo cáo về trạng thái chữ đỏ (các file results/runs_member*.csv vẫn được giữ).")

def cmd_info(a):
    p = os.path.join(REPORT, "results", "author.tex"); old = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            m = re.match(r"\\renewcommand\{\\(\w+)\}\{(.*)\}$", line.strip())
            if m: old[m.group(1)] = m.group(2)
    new = dict(old); n = {1: "One", 2: "Two"}[a.member]
    if a.name: new[f"Author{n}"] = tex_escape(a.name)
    if a.student_id: new[f"ID{n}"] = tex_escape(a.student_id)
    if a.email: new[f"Email{n}"] = tex_escape(a.email)
    if a.github: new["GithubURL"] = r"\url{" + a.github + "}"
    open(p, "w", encoding="utf-8").write("".join(f"\\renewcommand{{\\{k}}}{{{v}}}\n" for k, v in new.items()))
    print("Đã ghi", p)

# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    def paths(p):
        p.add_argument("--cms", help="đường dẫn file chạy cryptominisat5 (nếu không dùng pycryptosat)")
        p.add_argument("--kissat", help="đường dẫn file chạy kissat")
    p = sp.add_parser("check"); paths(p)
    p = sp.add_parser("run"); p.add_argument("--member", type=int, required=True, choices=[1, 2]); p.add_argument("--profile", default="quick", choices=list(PROFILES))
    p.add_argument("--time-limit", type=float); p.add_argument("--jobs", type=int, default=1); paths(p)
    p.add_argument("--sets", nargs="+", help="chỉ chạy các bộ này, vd --sets GEOM-S GEOM-L")
    sp.add_parser("report"); sp.add_parser("reset")
    p = sp.add_parser("info"); p.add_argument("--member", type=int, required=True, choices=[1, 2]); p.add_argument("--name"); p.add_argument("--student-id"); p.add_argument("--email"); p.add_argument("--github")
    p = sp.add_parser("worker"); p.add_argument("--method"); p.add_argument("--instance")
    p.add_argument("--time-limit", type=float); p.add_argument("--progress"); paths(p)
    a = ap.parse_args()
    if a.cmd == "worker": return worker(a)
    if a.cmd == "check":
        print("Thành viên 1, SAT solver (OK = chạy được):"); available_sat({"cms": a.cms, "kissat": a.kissat})
        print("Thành viên 2, ILP và CP:"); available_exact({}); return
    if a.cmd == "run": return cmd_run(a)
    if a.cmd == "report": return cmd_report(a)
    if a.cmd == "reset": return cmd_reset(a)
    if a.cmd == "info": return cmd_info(a)

if __name__ == "__main__":
    main()
