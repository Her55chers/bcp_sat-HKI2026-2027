#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exact_models.py -- cac mo hinh ILP va CP dung de so sanh voi SAT (Thanh vien 2).

  Gurobi, CPLEX MIP : mo hinh ILP (3)-(7) trong bao cao
  CPLEX CP, CP-SAT  : mo hinh CP tren bien nguyen

Moi ham nhan (g, T) va tra ve (coloring|None, da_chung_minh_toi_uu, t_build, t_solve, info).
"""
import time
import bcp_sat as S

def bounds(g):
    return max(S.first_fit(g)), S.lower_bound(g)

def solve_cpsat(g, T):
    """Mo hinh CP: bien nguyen c[v], moi canh mot bien thu tu; cuc tieu k. 1 luong."""
    from ortools.sat.python import cp_model
    t0 = time.perf_counter(); H, lb = bounds(g)
    m = cp_model.CpModel()
    new_int = getattr(m, "new_int_var", None) or m.NewIntVar
    new_bool = getattr(m, "new_bool_var", None) or m.NewBoolVar
    add = getattr(m, "add", None) or m.Add
    c = [new_int(1, H, f"c{v}") for v in range(g.n)]; k = new_int(lb, H, "k")
    for v in range(g.n): add(c[v] <= k)
    for u, v, d in g.edges:
        b = new_bool(f"b{u}_{v}")
        r = add(c[u] - c[v] >= d); (getattr(r, "only_enforce_if", None) or r.OnlyEnforceIf)(b)
        r = add(c[v] - c[u] >= d); (getattr(r, "only_enforce_if", None) or r.OnlyEnforceIf)(b.Not() if hasattr(b, "Not") else b.negated())
    (getattr(m, "minimize", None) or m.Minimize)(k)
    sv = cp_model.CpSolver(); t1 = time.perf_counter()
    sv.parameters.max_time_in_seconds = max(1.0, T - (t1 - t0))
    try: sv.parameters.num_workers = 1
    except Exception: sv.parameters.num_search_workers = 1
    st = (getattr(sv, "solve", None) or sv.Solve)(m); t2 = time.perf_counter()
    val = getattr(sv, "value", None) or sv.Value
    col = [int(val(x)) for x in c] if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    return col, st == cp_model.OPTIMAL, t1 - t0, t2 - t1, dict(vars=g.n + len(g.edges) + 1, clauses=g.n + 2 * len(g.edges))

def solve_gurobi(g, T):
    """Mo hinh ILP (3)-(8), 1 luong."""
    import gurobipy as gp
    t0 = time.perf_counter(); H, lb = bounds(g)
    m = gp.Model(); m.Params.OutputFlag = 0; m.Params.Threads = 1
    c = [m.addVar(lb=1, ub=H, vtype=gp.GRB.INTEGER) for _ in range(g.n)]
    k = m.addVar(lb=lb, ub=H, vtype=gp.GRB.INTEGER)
    for v in range(g.n): m.addConstr(c[v] <= k)
    for u, v, d in g.edges:
        M = H - 1 + d; y = m.addVar(vtype=gp.GRB.BINARY)
        m.addConstr(c[u] - c[v] + M * y >= d); m.addConstr(c[v] - c[u] + M * (1 - y) >= d)
    m.setObjective(k, gp.GRB.MINIMIZE); t1 = time.perf_counter()
    m.Params.TimeLimit = max(1.0, T - (t1 - t0)); m.optimize(); t2 = time.perf_counter()
    col = [int(round(x.X)) for x in c] if m.SolCount > 0 else None
    return col, m.Status == gp.GRB.OPTIMAL, t1 - t0, t2 - t1, dict(vars=g.n + len(g.edges) + 1, clauses=g.n + 2 * len(g.edges))

def solve_cplex_mip(g, T):
    """Mo hinh ILP (3)-(8) qua docplex.mp, 1 luong."""
    from docplex.mp.model import Model
    t0 = time.perf_counter(); H, lb = bounds(g)
    m = Model(); m.parameters.threads = 1
    c = [m.integer_var(1, H) for _ in range(g.n)]; k = m.integer_var(lb, H)
    for v in range(g.n): m.add_constraint(c[v] <= k)
    for u, v, d in g.edges:
        M = H - 1 + d; y = m.binary_var()
        m.add_constraint(c[u] - c[v] + M * y >= d); m.add_constraint(c[v] - c[u] + M * (1 - y) >= d)
    m.minimize(k); t1 = time.perf_counter()
    m.parameters.timelimit = max(1.0, T - (t1 - t0)); sol = m.solve(log_output=False); t2 = time.perf_counter()
    col = [int(round(sol.get_value(x))) for x in c] if sol else None
    opt = bool(sol) and "optimal" in str(m.solve_details.status).lower()
    return col, opt, t1 - t0, t2 - t1, dict(vars=g.n + len(g.edges) + 1, clauses=g.n + 2 * len(g.edges))

def solve_cplex_cp(g, T):
    """Mo hinh CP qua docplex.cp (can CP Optimizer), 1 luong."""
    from docplex.cp.model import CpoModel
    t0 = time.perf_counter(); H, lb = bounds(g)
    m = CpoModel(); c = [m.integer_var(1, H) for _ in range(g.n)]; k = m.integer_var(lb, H)
    for v in range(g.n): m.add(c[v] <= k)
    for u, v, d in g.edges: m.add(abs(c[u] - c[v]) >= d)
    m.add(m.minimize(k)); t1 = time.perf_counter()
    sol = m.solve(TimeLimit=max(1.0, T - (t1 - t0)), Workers=1, LogVerbosity="Quiet"); t2 = time.perf_counter()
    col = [int(sol[x]) for x in c] if sol and sol.is_solution() else None
    opt = bool(col) and str(sol.get_solve_status()).lower() == "optimal"
    return col, opt, t1 - t0, t2 - t1, dict(vars=g.n + 1, clauses=g.n + len(g.edges))

EXACT_FN = {"cpsat": solve_cpsat, "gurobi": solve_gurobi, "cplex-mip": solve_cplex_mip, "cplex-cp": solve_cplex_cp}
