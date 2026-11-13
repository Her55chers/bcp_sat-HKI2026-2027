#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exact_models.py -- cac mo hinh ILP va CP dung de so sanh voi SAT (Thanh vien 2).

  Gurobi, CPLEX MIP : mo hinh ILP (3)-(7) trong bao cao
  CPLEX CP, CP-SAT  : mo hinh CP tren bien nguyen

Moi ham nhan (g, T) va tra ve (coloring|None, da_chung_minh_toi_uu, t_build, t_solve, info).
Cac mo hinh dung chung voi SAT: can duoi LB (clique), can tren H va phep to heuristic
(duoc dua vao solver lam nghiem khoi dau), va cung bo dinh bac thap S.peel. Neu het gio ma solver chua co nghiem thi
tra ve phep to heuristic (trang thai FEAS), giong nhu cach SAT.
"""
import time
import bcp_sat as S

def bounds(g):
    """(phep to heuristic, H, LB), cung cach tinh voi S.search."""
    lb = S.lower_bound(g); col = S.heuristic_coloring(g, lb)
    return col, max(col, default=0), lb

def _info(g, H, lb, nvars, ncons):
    return dict(vars=nvars, clauses=ncons, H=H, LB=lb)

def _trivial(g, col0, H, lb, t0):
    """Heuristic da dat LB: toi uu, khong can goi solver."""
    return col0, True, time.perf_counter() - t0, 0.0, _info(g, H, lb, 0, 0)

def _prepare(g):
    """Can, heuristic va bo dinh bac thap (S.peel), giong het S.search.
    Tra ve (ket_qua_neu_xong_ngay | None, ngu_canh)."""
    t0 = time.perf_counter(); col0, H, lb = bounds(g)
    if H <= lb: return _trivial(g, col0, H, lb, t0), None
    gr, keep, removed = S.peel(g, lb)
    if gr.n == 0:
        c = S.unpeel(g, [], keep, removed)
        return (c, True, time.perf_counter() - t0, 0.0, _info(g, H, lb, 0, 0)), None
    return None, (t0, gr, [col0[v] for v in keep], H, lb, keep, removed)

def _finish(g, ctx, colr, opt, t1, t2, nvars, ncons):
    t0, gr, _, H, lb, keep, removed = ctx
    return S.unpeel(g, colr, keep, removed), opt, t1 - t0, t2 - t1, _info(g, H, lb, nvars, ncons)

def solve_cpsat(G, T):
    """Mo hinh CP: bien nguyen c[v], moi canh mot bien thu tu; cuc tieu k. 1 luong."""
    from ortools.sat.python import cp_model
    done, ctx = _prepare(G)
    if done: return done
    t0, g, col0, H, lb = ctx[:5]
    m = cp_model.CpModel()
    new_int = getattr(m, "new_int_var", None) or m.NewIntVar
    new_bool = getattr(m, "new_bool_var", None) or m.NewBoolVar
    add = getattr(m, "add", None) or m.Add
    hint = getattr(m, "add_hint", None) or m.AddHint
    c = [new_int(1, H, f"c{v}") for v in range(g.n)]; k = new_int(lb, H, "k")
    for v in range(g.n): add(c[v] <= k); hint(c[v], col0[v])
    hint(k, H)
    for u, v, d in g.edges:
        b = new_bool(f"b{u}_{v}"); hint(b, col0[u] > col0[v])
        r = add(c[u] - c[v] >= d); (getattr(r, "only_enforce_if", None) or r.OnlyEnforceIf)(b)
        r = add(c[v] - c[u] >= d); (getattr(r, "only_enforce_if", None) or r.OnlyEnforceIf)(b.Not() if hasattr(b, "Not") else b.negated())
    (getattr(m, "minimize", None) or m.Minimize)(k)
    sv = cp_model.CpSolver(); t1 = time.perf_counter()
    sv.parameters.max_time_in_seconds = max(1.0, T - (t1 - t0))
    try: sv.parameters.num_workers = 1
    except Exception: sv.parameters.num_search_workers = 1
    st = (getattr(sv, "solve", None) or sv.Solve)(m); t2 = time.perf_counter()
    val = getattr(sv, "value", None) or sv.Value
    col = [int(val(x)) for x in c] if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else col0
    return _finish(G, ctx, col, st == cp_model.OPTIMAL, t1, t2, g.n + len(g.edges) + 1, g.n + 2 * len(g.edges))

def solve_gurobi(G, T):
    """Mo hinh ILP (3)-(8), 1 luong."""
    import gurobipy as gp
    done, ctx = _prepare(G)
    if done: return done
    t0, g, col0, H, lb = ctx[:5]
    m = gp.Model(); m.Params.OutputFlag = 0; m.Params.Threads = 1
    c = [m.addVar(lb=1, ub=H, vtype=gp.GRB.INTEGER) for _ in range(g.n)]
    k = m.addVar(lb=lb, ub=H, vtype=gp.GRB.INTEGER)
    for v in range(g.n): m.addConstr(c[v] <= k); c[v].Start = col0[v]
    k.Start = H
    for u, v, d in g.edges:
        M = H - 1 + d; y = m.addVar(vtype=gp.GRB.BINARY); y.Start = int(col0[u] < col0[v])
        m.addConstr(c[u] - c[v] + M * y >= d); m.addConstr(c[v] - c[u] + M * (1 - y) >= d)
    m.setObjective(k, gp.GRB.MINIMIZE); t1 = time.perf_counter()
    m.Params.TimeLimit = max(1.0, T - (t1 - t0)); m.optimize(); t2 = time.perf_counter()
    col = [int(round(x.X)) for x in c] if m.SolCount > 0 else col0
    return _finish(G, ctx, col, m.Status == gp.GRB.OPTIMAL, t1, t2, g.n + len(g.edges) + 1, g.n + 2 * len(g.edges))

def solve_cplex_mip(G, T):
    """Mo hinh ILP (3)-(8) qua docplex.mp, 1 luong."""
    from docplex.mp.model import Model
    done, ctx = _prepare(G)
    if done: return done
    t0, g, col0, H, lb = ctx[:5]
    m = Model(); m.parameters.threads = 1
    c = [m.integer_var(1, H) for _ in range(g.n)]; k = m.integer_var(lb, H)
    start = {k: H}
    for v in range(g.n): m.add_constraint(c[v] <= k); start[c[v]] = col0[v]
    for u, v, d in g.edges:
        M = H - 1 + d; y = m.binary_var(); start[y] = int(col0[u] < col0[v])
        m.add_constraint(c[u] - c[v] + M * y >= d); m.add_constraint(c[v] - c[u] + M * (1 - y) >= d)
    m.minimize(k)
    try:
        ws = m.new_solution()
        for var, val in start.items(): ws.add_var_value(var, val)
        m.add_mip_start(ws)
    except Exception:
        pass
    t1 = time.perf_counter()
    m.parameters.timelimit = max(1.0, T - (t1 - t0)); sol = m.solve(log_output=False); t2 = time.perf_counter()
    col = [int(round(sol.get_value(x))) for x in c] if sol else col0
    opt = bool(sol) and "optimal" in str(m.solve_details.status).lower()
    return _finish(G, ctx, col, opt, t1, t2, g.n + len(g.edges) + 1, g.n + 2 * len(g.edges))

def solve_cplex_cp(G, T):
    """Mo hinh CP qua docplex.cp (can CP Optimizer), 1 luong."""
    from docplex.cp.model import CpoModel
    done, ctx = _prepare(G)
    if done: return done
    t0, g, col0, H, lb = ctx[:5]
    m = CpoModel(); c = [m.integer_var(1, H) for _ in range(g.n)]; k = m.integer_var(lb, H)
    for v in range(g.n): m.add(c[v] <= k)
    for u, v, d in g.edges: m.add(abs(c[u] - c[v]) >= d)
    m.add(m.minimize(k))
    try:
        from docplex.cp.solution import CpoModelSolution
        sp = CpoModelSolution()
        for x, val in zip(c, col0): sp.add_integer_var_solution(x, val)
        sp.add_integer_var_solution(k, H); m.set_starting_point(sp)
    except Exception:
        pass
    t1 = time.perf_counter()
    sol = m.solve(TimeLimit=max(1.0, T - (t1 - t0)), Workers=1, LogVerbosity="Quiet"); t2 = time.perf_counter()
    col = [int(sol[x]) for x in c] if sol and sol.is_solution() else col0
    opt = bool(sol) and sol.is_solution() and str(sol.get_solve_status()).lower() == "optimal"
    return _finish(G, ctx, col, opt, t1, t2, g.n + 1, g.n + len(g.edges))

EXACT_FN = {"cpsat": solve_cpsat, "gurobi": solve_gurobi, "cplex-mip": solve_cplex_mip, "cplex-cp": solve_cplex_cp}
