#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bcp_sat.py -- SAT encodings for the Bandwidth Coloring Problem (BCP).

Given G = (V, E) with positive integer edge weights d(u,v), find c: V -> {1,2,...}
with |c(u) - c(v)| >= d(u,v) for every edge, minimising the largest colour (span).

Contents
  * Five AMO (at-most-one) encoders: pairwise, sequential counter, binary,
    commander, product (all implemented here, no external dependency).
  * Encoding configurations: full, no-sym, pair, non-inc and direct-<amo>.
  * Descending threshold search that certifies optimality (SAT at B, UNSAT at B-1).
  * Closed-form size formulas, checked against the generator.
  * Independent colouring checker, greedy upper bound, DIMACS writer, .col reader.
  * A tiny reference DPLL solver used ONLY for validation/testing.
    Real experiments should use CDCL solvers (PySAT: cadical195, glucose4, ...).

CLI
  python bcp_sat.py verify --out ../report                 # correctness tests
  python bcp_sat.py sizes  --out ../report                 # size tables + figure
  python bcp_sat.py solve  --instance ../instances/GEOM/GEOM20.col --solver cadical195
  python bcp_sat.py dimacs --instance ../instances/GEOM/GEOM20.col --k 21 --out g.cnf
  python bcp_sat.py gen    --n 30 --dist 2000000 --max-weight 10 --seed 1 --out g.col
"""
import argparse, collections, itertools, json, math, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
INST = os.path.join(HERE, "..", "instances")

# ----------------------------------------------------------------------------
# 1. Clause sinks and variable pool
# ----------------------------------------------------------------------------
class Pool:
    """Allocates fresh auxiliary variables above the primary ones."""
    def __init__(self, top): self.top = top
    def new(self):
        self.top += 1
        return self.top

class ListSink:
    def __init__(self): self.clauses = []
    def add(self, c): self.clauses.append(c)
    @property
    def n(self): return len(self.clauses)

class CountSink:
    """Only counts clauses (streaming, O(1) memory)."""
    def __init__(self): self.n = 0
    def add(self, c): self.n += 1

# ----------------------------------------------------------------------------
# 2. AMO encoders:  f(lits, pool, sink)
# ----------------------------------------------------------------------------
def amo_pairwise(lits, pool, sink):
    for a, b in itertools.combinations(lits, 2):
        sink.add([-a, -b])

def amo_seqcounter(lits, pool, sink):
    """Sinz (2005), k = 1: m-1 aux variables, 3m-4 clauses."""
    m = len(lits)
    if m < 2: return
    s = [pool.new() for _ in range(m - 1)]
    sink.add([-lits[0], s[0]])
    for i in range(1, m - 1):
        sink.add([-lits[i], s[i]])
        sink.add([-s[i - 1], s[i]])
        sink.add([-lits[i], -s[i - 1]])
    sink.add([-lits[m - 1], -s[m - 2]])

def amo_binary(lits, pool, sink):
    """Binary: ceil(log2 m) aux variables, m*ceil(log2 m) clauses."""
    m = len(lits)
    if m < 2: return
    k = (m - 1).bit_length()
    y = [pool.new() for _ in range(k)]
    for i, x in enumerate(lits):
        for j in range(k):
            sink.add([-x, y[j] if (i >> j) & 1 else -y[j]])

def group_sizes(m, g):
    base, rem = divmod(m, g)
    return [base + 1] * rem + [base] * (g - rem)

def amo_commander(lits, pool, sink, s=3):
    """Commander (Klieber & Kwon), one level, groups of about s literals."""
    m = len(lits)
    if m < 2: return
    g = -(-m // s)
    groups, pos = [], 0
    for z in group_sizes(m, g):
        groups.append(lits[pos:pos + z]); pos += z
    c = [pool.new() for _ in groups]
    amo_pairwise(c, pool, sink)
    for ci, G in zip(c, groups):
        sink.add([-ci] + list(G))
        amo_pairwise(G, pool, sink)
        for x in G: sink.add([-x, ci])

def ceil_sqrt(m):
    p = math.isqrt(m)
    return p if p * p >= m else p + 1

def amo_product(lits, pool, sink):
    """Product (Chen 2010), one level on a p x q grid."""
    m = len(lits)
    if m < 2: return
    p = ceil_sqrt(m); q = -(-m // p)
    r = [pool.new() for _ in range(p)]
    c = [pool.new() for _ in range(q)]
    amo_pairwise(r, pool, sink); amo_pairwise(c, pool, sink)
    for i, x in enumerate(lits):
        sink.add([-x, r[i // q]]); sink.add([-x, c[i % q]])

AMO = {"pairwise": amo_pairwise, "seq": amo_seqcounter, "binary": amo_binary,
       "commander": amo_commander, "product": amo_product}
AMO_LABEL = {"pairwise": "Pairwise", "seq": "Sequential", "binary": "Binary",
             "commander": "Commander", "product": "Product"}

def amo_cost(kind, m, s=3):
    """Closed form (aux variables, clauses) of AMO over m literals."""
    if m < 2: return 0, 0
    if kind == "pairwise": return 0, m * (m - 1) // 2
    if kind == "seq": return m - 1, 3 * m - 4
    if kind == "binary":
        k = (m - 1).bit_length(); return k, m * k
    if kind == "commander":
        g = -(-m // s)
        return g, g * (g - 1) // 2 + g + m + sum(z * (z - 1) // 2 for z in group_sizes(m, g))
    if kind == "product":
        p = ceil_sqrt(m); q = -(-m // p)
        return p + q, 2 * m + p * (p - 1) // 2 + q * (q - 1) // 2
    raise ValueError(kind)

# ----------------------------------------------------------------------------
# 3. Graphs
# ----------------------------------------------------------------------------
class Graph:
    """Vertices 0..n-1; edges: list of (u, v, d) with u < v, d >= 1."""
    def __init__(self, n, edges, name=""):
        self.n, self.name = n, name
        w = {}
        for u, v, d in edges:
            if u == v: continue
            k = (min(u, v), max(u, v))
            w[k] = max(w.get(k, 0), d)
        self.edges = [(u, v, d) for (u, v), d in sorted(w.items())]
        self.adj = [[] for _ in range(n)]
        for u, v, d in self.edges:
            self.adj[u].append((v, d)); self.adj[v].append((u, d))

def read_col(path):
    """Read a .col file: `p <kind> n m`, `e u v [w]`. Vertices are 1-based.
    GEOM and MS-CAP files also hold multicolouring data: `n v w` lines (colour
    demands) and self-loops `e v v w` (same-vertex distance). Both are outside
    BCP and are ignored here."""
    n, edges = 0, []
    with open(path) as f:
        for line in f:
            t = line.split()
            if not t: continue
            if t[0] == "p": n = int(t[2])
            elif t[0] == "e":
                edges.append((int(t[1]) - 1, int(t[2]) - 1, int(t[3]) if len(t) > 3 else 1))
    return Graph(n, edges, os.path.splitext(os.path.basename(path))[0])

def write_col(path, g):
    with open(path, "w") as f:
        f.write(f"p band {g.n} {len(g.edges)}\n")
        for u, v, d in g.edges: f.write(f"e {u+1} {v+1} {d}\n")

def random_geometric(n, max_sq_dist, max_weight, seed):
    """Trick-style geometric graph: points in a 10000 x 10000 square, an edge when
    close enough, weight larger for closer points."""
    rng = random.Random(seed)
    pts = [(rng.randrange(10000), rng.randrange(10000)) for _ in range(n)]
    E = []
    for u, v in itertools.combinations(range(n), 2):
        sq = (pts[u][0] - pts[v][0]) ** 2 + (pts[u][1] - pts[v][1]) ** 2
        if sq <= max_sq_dist:
            E.append((u, v, 1 + int((max_weight - 1) * (1 - sq / max_sq_dist))))
    return Graph(n, E, f"gen{n}_s{seed}")

def is_valid_coloring(g, c):
    """Independent checker: shares no code with the encoder."""
    return (len(c) == g.n and all(x >= 1 for x in c) and
            all(abs(c[u] - c[v]) >= d for u, v, d in g.edges))

def first_fit(g):
    """Greedy colouring by decreasing degree; its span is the upper bound H."""
    c = {}
    for v in sorted(range(g.n), key=lambda v: (-len(g.adj[v]), v)):
        k = 1
        while any(w in c and abs(c[w] - k) < d for w, d in g.adj[v]): k += 1
        c[v] = k
    return [c[v] for v in range(g.n)]

def lower_bound(g):
    return max((d for _, _, d in g.edges), default=0) + 1

def anchor_vertex(g):
    """Largest degree, then largest neighbour-degree sum, then smallest index."""
    deg = [len(a) for a in g.adj]
    return max(range(g.n), key=lambda v: (deg[v], sum(deg[w] for w, _ in g.adj[v]), -v))

# ----------------------------------------------------------------------------
# 4. Encodings
# ----------------------------------------------------------------------------
Config = collections.namedtuple("Config", "name vars dist amo sym inc")
CONFIGS = {
    "full":    Config("full", "order", "interval", None, True, True),
    "no-sym":  Config("no-sym", "order", "interval", None, False, True),
    "pair":    Config("pair", "order", "pairwise", None, True, True),
    "non-inc": Config("non-inc", "order", "interval", None, True, False),
}
for _k in AMO:
    CONFIGS[f"direct-{_k}"] = Config(f"direct-{_k}", "direct", "pairwise", _k, True, True)
CONFIG_LABEL = {k: k for k in CONFIGS}

class Encoding:
    """x(v,j): c(v) = j, 1 <= j <= H.   g(v,j): c(v) >= j, 2 <= j <= H."""
    def __init__(self, g, H, cfg):
        self.G, self.H, self.cfg = g, H, cfg
        self.anchor = anchor_vertex(g) if cfg.sym else None
        top = g.n * H + (g.n * (H - 1) if cfg.vars == "order" else 0)
        self.pool = Pool(top)

    def x(self, v, j): return v * self.H + j
    def g(self, v, j): return self.G.n * self.H + v * (self.H - 1) + j - 1

    def _ge(self, v, t):
        """Literal for c(v) >= t, or True/False when t is outside [2, H]."""
        if t <= 1: return True
        if t > self.H: return False
        return self.g(v, t)

    @staticmethod
    def _add(sink, *items):
        """Each item is (literal or constant, sign). Simplifies constants away."""
        out = []
        for lit, sign in items:
            if lit is True or lit is False:
                if lit == sign: return
                continue
            out.append(lit if sign else -lit)
        sink.add(out)

    def fixed(self, sink):
        """Everything that does not depend on K."""
        n, H, x = self.G.n, self.H, self.x
        if self.cfg.vars == "order":
            for v in range(n):
                for j in range(2, H):                                # (chain)
                    sink.add([-self.g(v, j + 1), self.g(v, j)])
                for j in range(1, H + 1):                            # (channel)
                    a, b = self._ge(v, j), self._ge(v, j + 1)
                    self._add(sink, (x(v, j), False), (a, True))
                    self._add(sink, (x(v, j), False), (b, False))
                    self._add(sink, (x(v, j), True), (a, False), (b, True))
        else:
            f = AMO[self.cfg.amo]
            for v in range(n):
                lits = [x(v, j) for j in range(1, H + 1)]
                sink.add(lits)                                       # ALO
                f(lits, self.pool, sink)                             # AMO
        for u, v, d in self.G.edges:
            if self.cfg.dist == "pairwise":
                for a in range(1, H + 1):
                    for b in range(max(1, a - d + 1), min(H, a + d - 1) + 1):
                        sink.add([-x(u, a), -x(v, b)])
            else:
                for p, q in ((u, v), (v, u)):
                    for a in range(1, H + 1):
                        self._add(sink, (x(p, a), False),
                                  (self._ge(q, a - d + 1), False), (self._ge(q, a + d), True))

    def delta(self, K, sink):
        """Span <= K, plus the anchor in the lower half of [1, K] (reflection)."""
        half = math.ceil(K / 2)
        if self.cfg.vars == "order":
            if K + 1 <= self.H:
                for v in range(self.G.n): sink.add([-self.g(v, K + 1)])
            if self.anchor is not None and half + 1 <= self.H:
                sink.add([-self.g(self.anchor, half + 1)])
        else:
            for v in range(self.G.n):
                for j in range(K + 1, self.H + 1): sink.add([-self.x(v, j)])
            if self.anchor is not None:
                for j in range(half + 1, self.H + 1): sink.add([-self.x(self.anchor, j)])

    def decode(self, true_lits):
        c = [0] * self.G.n
        limit = self.G.n * self.H
        for l in true_lits:
            if 1 <= l <= limit:
                v, j = divmod(l - 1, self.H)
                if c[v]: raise ValueError("vertex has two colours")
                c[v] = j + 1
        return c

def formula_size(g, H, cfg):
    """Closed-form (variables, clauses) before Delta_K, for H >= 2."""
    n = g.n
    pair = sum((2 * d - 1) * H - d * (d - 1) for _, _, d in g.edges)
    if cfg.vars == "order":
        dist = pair if cfg.dist == "pairwise" else 2 * H * len(g.edges)
        return n * (2 * H - 1), n * (H - 2) + n * (3 * H - 2) + dist
    a, l = amo_cost(cfg.amo, H)
    return n * H + n * a, n * (1 + l) + pair

# ----------------------------------------------------------------------------
# 5. Back-ends and the threshold search
# ----------------------------------------------------------------------------
class Backend:
    """add(clause), solve() -> list of true literals or None, close()."""
    def close(self): pass

class DPLLBackend(Backend):
    def __init__(self, nvars): self.nvars, self.cl = nvars, []
    def add(self, c): self.cl.append(list(c))
    def solve(self):
        m = dpll_solve(self.cl, self.nvars)
        return None if m is None else [v for v in range(1, self.nvars + 1) if m[v] > 0]

class PySATBackend(Backend):
    def __init__(self, name):
        from pysat.solvers import Solver
        self.s = Solver(name=name)
    def add(self, c): self.s.add_clause(c)
    def solve(self): return [l for l in self.s.get_model() if l > 0] if self.s.solve() else None
    def close(self): self.s.delete()

def search(g, cfg, make_backend, on_incumbent=None, on_built=None):
    """Descending search. Returns dict(status, span, coloring, H, LB, calls, ...).
    status OPTIMAL means: a colouring of span B plus UNSAT at B-1, or B = LB."""
    t0 = time.perf_counter()
    H, lb = max(first_fit(g)), lower_bound(g)
    enc = Encoding(g, H, cfg)
    sink = ListSink(); enc.fixed(sink)
    res = dict(H=H, LB=lb, vars=enc.pool.top, clauses=sink.n, calls=0, span=None, coloring=None, status="UNKNOWN")
    backend, K = None, H
    def load(b):
        for c in sink.clauses: b.add(c)
        return b
    if cfg.inc: backend = load(make_backend(enc.pool.top))
    res["t_build"] = time.perf_counter() - t0
    if on_built: on_built(res)
    while K >= lb:
        if not cfg.inc:
            if backend: backend.close()
            backend = load(make_backend(enc.pool.top))
        d = ListSink(); enc.delta(K, d)
        for c in d.clauses: backend.add(c)
        res["calls"] += 1
        true = backend.solve()
        if true is None:
            if res["span"] is None: raise RuntimeError("UNSAT at the feasible upper bound: encoder bug")
            res["status"] = "OPTIMAL"; break
        c = enc.decode(true)
        if not is_valid_coloring(g, c) or max(c) > K:
            res["status"] = "WRONG"; break
        res["span"], res["coloring"] = max(c), c
        if on_incumbent: on_incumbent(max(c))
        if max(c) <= lb:
            res["status"] = "OPTIMAL"; break
        K = max(c) - 1
    if backend: backend.close()
    return res

def write_dimacs(path, clauses, nvars):
    with open(path, "w") as f:
        f.write(f"p cnf {nvars} {len(clauses)}\n")
        for c in clauses: f.write(" ".join(map(str, c)) + " 0\n")

# ----------------------------------------------------------------------------
# 6. Reference solver (testing only): DPLL with two watched literals
# ----------------------------------------------------------------------------
def dpll_solve(clauses, nvars, assumptions=()):
    """Return assignment list (index 1..nvars, +1/-1) or None if UNSAT."""
    val = [0] * (nvars + 1); trail = []; head = 0
    idx = lambda l: 2 * l if l > 0 else -2 * l + 1
    watch = [[] for _ in range(2 * nvars + 2)]
    cls, units = [], []
    for c in clauses:
        c = list(dict.fromkeys(c))
        if not c: return None
        if any(-l in c for l in c): continue
        if len(c) == 1: units.append(c[0]); continue
        watch[idx(c[0])].append(len(cls)); watch[idx(c[1])].append(len(cls)); cls.append(c)
    def set_lit(l):
        want = 1 if l > 0 else -1
        if val[abs(l)] == 0: val[abs(l)] = want; trail.append(l); return True
        return val[abs(l)] == want
    def propagate():
        nonlocal head
        while head < len(trail):
            false_lit = -trail[head]; head += 1
            ws, keep = watch[idx(false_lit)], []
            for pos, ci in enumerate(ws):
                c = cls[ci]
                if c[0] == false_lit: c[0], c[1] = c[1], c[0]
                first = c[0]; fv = val[abs(first)]
                if fv == (1 if first > 0 else -1): keep.append(ci); continue
                for k in range(2, len(c)):
                    if val[abs(c[k])] != (-1 if c[k] > 0 else 1):
                        c[1], c[k] = c[k], c[1]; watch[idx(c[1])].append(ci); break
                else:
                    keep.append(ci)
                    if fv != 0:                                     # conflict
                        keep.extend(ws[pos + 1:]); watch[idx(false_lit)] = keep
                        return False
                    set_lit(first)
            watch[idx(false_lit)] = keep
        return True
    for u in list(units) + list(assumptions):
        if not set_lit(u): return None
    if not propagate(): return None
    stack = []
    next_var = 1
    while True:
        while next_var <= nvars and val[next_var] != 0: next_var += 1
        if next_var > nvars: return val
        stack.append((len(trail), next_var, next_var, False)); set_lit(next_var)
        ok = propagate()
        while not ok:
            if not stack: return None
            size, v, nv, flipped = stack.pop()
            for l in trail[size:]: val[abs(l)] = 0
            del trail[size:]; head = size; next_var = nv
            if flipped: continue
            stack.append((size, v, nv, True)); set_lit(-v); ok = propagate()

def unit_propagate(clauses, assumptions):
    """Naive UP fix-point. Returns (conflict?, {var: bool})."""
    val = {abs(a): a > 0 for a in assumptions}
    changed = True
    while changed:
        changed = False
        for c in clauses:
            free, sat = [], False
            for l in c:
                v = val.get(abs(l))
                if v is None: free.append(l)
                elif v == (l > 0): sat = True; break
            if sat: continue
            if not free: return True, val
            if len(free) == 1:
                val[abs(free[0])] = free[0] > 0; changed = True
    return False, val

# ----------------------------------------------------------------------------
# 7. Validation suite
# ----------------------------------------------------------------------------
EXAMPLE = Graph(4, [(0, 1, 3), (0, 2, 2), (1, 2, 2), (1, 3, 1), (2, 3, 3)], "example")

def amo_instance(kind, m):
    pool = Pool(m); sink = ListSink()
    AMO[kind](list(range(1, m + 1)), pool, sink)
    return sink.clauses, pool.top

def test_amo_exhaustive(kind, m):
    cl, nv = amo_instance(kind, m); cases = 0
    for bits in itertools.product([False, True], repeat=m):
        ass = [(i + 1) if b else -(i + 1) for i, b in enumerate(bits)]
        if (dpll_solve(cl, nv, ass) is not None) != (sum(bits) <= 1): return cases, False
        cases += 1
    return cases, True

def test_amo_low_weight(kind, m):
    cl, nv = amo_instance(kind, m); cases = 0
    for w in (0, 1, 2):
        for T in itertools.combinations(range(m), w):
            ass = [(i + 1) if i in T else -(i + 1) for i in range(m)]
            if (dpll_solve(cl, nv, ass) is not None) != (w <= 1): return cases, False
            cases += 1
    return cases, True

def test_up(kind, m):
    cl, nv = amo_instance(kind, m); cases = 0
    for i in range(1, m + 1):
        conflict, val = unit_propagate(cl, [i])
        if conflict or any(val.get(j) is not False for j in range(1, m + 1) if j != i): return cases, False
        cases += 1
    return cases, True

def brute_force_opt(g, H):
    best = None
    for c in itertools.product(range(1, H + 1), repeat=g.n):
        if (best is None or max(c) < best) and is_valid_coloring(g, c): best = max(c)
    return best

def random_graph(rng, nmax=6, wmax=4, p=0.6):
    n = rng.randint(2, nmax)
    E = [(u, v, rng.randint(1, wmax)) for u, v in itertools.combinations(range(n), 2) if rng.random() < p]
    return Graph(n, E) if E else random_graph(rng, nmax, wmax, p)

def cmd_verify(a):
    out = {"amo": {}, "bcp": {}}
    t0 = time.time(); ok_all = True
    for k in AMO:
        ex, lw, up, form = 0, 0, 0, True; ok = True
        for m in range(1, 11):
            c, o = test_amo_exhaustive(k, m); ex += c; ok &= o
        for m in range(11, 25):
            c, o = test_amo_low_weight(k, m); lw += c; ok &= o
        for m in range(2, 65):
            c, o = test_up(k, m); up += c; ok &= o
        for m in range(2, 201):
            cl, nv = amo_instance(k, m); av, ac = amo_cost(k, m)
            form &= (nv - m == av and len(cl) == ac)
        out["amo"][k] = dict(exhaustive=ex, low_weight=lw, up=up, formula_m2_200=form, ok=ok)
        ok_all &= ok and form
    print("AMO tests done in %.1fs" % (time.time() - t0))
    rng = random.Random(2026); graphs = checks = 0; bad = []
    for _ in range(a.graphs):
        g = random_graph(rng)
        H = max(first_fit(g)); opt = brute_force_opt(g, H); graphs += 1
        if not (lower_bound(g) <= opt <= H): bad.append(("bounds", g.edges))
        for name, cfg in CONFIGS.items():
            r = search(g, cfg, DPLLBackend); checks += 1
            if r["status"] != "OPTIMAL" or r["span"] != opt or not is_valid_coloring(g, r["coloring"]):
                bad.append((name, g.edges, opt, r["span"]))
    out["bcp"]["random_graphs"] = graphs; out["bcp"]["search_runs"] = checks; out["bcp"]["search_ok"] = not bad
    # F(K) is SAT exactly when a colouring of span <= K exists, at every K, without the search
    thr = 0; thr_ok = True
    for _ in range(a.graphs // 2):
        g = random_graph(rng, nmax=5); H = max(first_fit(g)); opt = brute_force_opt(g, H)
        for name in ("full", "pair", "direct-seq"):
            enc = Encoding(g, H, CONFIGS[name]); s = ListSink(); enc.fixed(s); base = s.clauses
            for K in range(1, H + 1):
                d = ListSink(); enc.delta(K, d); thr += 1
                thr_ok &= (dpll_solve(base + d.clauses, enc.pool.top) is not None) == (opt <= K)
    out["bcp"]["threshold_cases"] = thr; out["bcp"]["threshold_ok"] = thr_ok
    # size formulas against the generator
    siz = 0; siz_ok = True
    for _ in range(100):
        g = random_graph(rng, nmax=12, wmax=6); H = max(first_fit(g))
        if H < 2: continue
        for cfg in CONFIGS.values():
            enc = Encoding(g, H, cfg); s = CountSink(); enc.fixed(s); fv, fc = formula_size(g, H, cfg); siz += 1
            siz_ok &= (enc.pool.top == fv and s.n == fc)
    out["bcp"]["size_cases"] = siz; out["bcp"]["size_ok"] = siz_ok
    # worked example: span 6 is optimal, span 5 is UNSAT
    res = {}
    for name, cfg in CONFIGS.items(): res[name] = search(EXAMPLE, cfg, DPLLBackend)["span"]
    enc = Encoding(EXAMPLE, 8, CONFIGS["full"]); s = ListSink(); enc.fixed(s); d = ListSink(); enc.delta(5, d)
    out["bcp"]["example_spans"] = res
    out["bcp"]["example_ok"] = (set(res.values()) == {6} and brute_force_opt(EXAMPLE, 8) == 6 and
                                dpll_solve(s.clauses + d.clauses, enc.pool.top) is None)
    # unweighted graph: BCP = graph colouring, K4 needs 4 colours, C5 needs 3
    k4 = Graph(4, [(u, v, 1) for u, v in itertools.combinations(range(4), 2)])
    c5 = Graph(5, [(i, (i + 1) % 5, 1) for i in range(5)])
    out["bcp"]["unit_weight_ok"] = (search(k4, CONFIGS["full"], DPLLBackend)["span"] == 4 and
                                    search(c5, CONFIGS["full"], DPLLBackend)["span"] == 3)
    # reader ignores node lines and self-loops, keeps the larger duplicate weight
    tmp = os.path.join(a.out, "results", "_t.col"); os.makedirs(os.path.dirname(tmp), exist_ok=True)
    open(tmp, "w").write("c x\np band 3 3\nn 1 5\ne 1 1 10\ne 1 2 6\ne 2 1 7\ne 2 3 1\n")
    g = read_col(tmp); os.remove(tmp)
    out["bcp"]["reader_ok"] = (g.n == 3 and g.edges == [(0, 1, 7), (1, 2, 1)])
    # every benchmark file: n and |E| agree with the published reference data
    ref_path = os.path.join(INST, "reference_values.csv"); chk = 0; chk_ok = True
    if os.path.exists(ref_path):
        import csv, glob
        refs = {r["instance"]: r for r in csv.DictReader(open(ref_path))}
        for p in glob.glob(os.path.join(INST, "*", "*.col")):
            g = read_col(p); r = refs.get(g.name)
            if r: chk += 1; chk_ok &= (str(g.n) == r["n"] and str(len(g.edges)) == r["E"])
    out["bcp"]["instances_checked"] = chk; out["bcp"]["instances_ok"] = chk_ok
    out["seconds"] = round(time.time() - t0, 1)
    ok_all &= all(out["bcp"][k] for k in ("search_ok", "threshold_ok", "size_ok", "example_ok", "unit_weight_ok", "reader_ok", "instances_ok"))
    path = os.path.join(a.out, "results", "validation.json")
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out, indent=1))
    if bad: print("FAILURES:", bad[:5])
    print("ALL TESTS PASSED" if ok_all else "SOME TESTS FAILED")
    return 0 if ok_all else 1

# ----------------------------------------------------------------------------
# 8. Size tables / figure for the report
# ----------------------------------------------------------------------------
SIZE_INSTANCES = ["GEOM20", "GEOM40", "GEOM60", "GEOM80", "GEOM100", "GEOM120", "GEOM60a", "GEOM120a", "GEOM60b", "GEOM120b"]
SIZE_CONFIGS = ["full", "pair", "direct-pairwise", "direct-seq", "direct-binary", "direct-commander", "direct-product"]

def thin(x): return f"{x:,}".replace(",", "\\,")

def cmd_sizes(a):
    tdir = os.path.join(a.out, "tables"); os.makedirs(tdir, exist_ok=True)
    os.makedirs(os.path.join(a.out, "results"), exist_ok=True)
    rows = []
    for name in SIZE_INSTANCES:
        g = read_col(os.path.join(INST, "GEOM", name + ".col")); H = max(first_fit(g))
        for c in SIZE_CONFIGS:
            nv, nc = formula_size(g, H, CONFIGS[c])
            rows.append(dict(instance=name, n=g.n, E=len(g.edges), H=H, config=c, vars=nv, clauses=nc))
    with open(os.path.join(a.out, "results", "encoding_sizes.csv"), "w") as f:
        f.write("instance,n,E,H,config,vars,clauses\n")
        for r in rows: f.write(",".join(str(r[k]) for k in ("instance", "n", "E", "H", "config", "vars", "clauses")) + "\n")
    short = {"full": "full", "pair": "pair", "direct-pairwise": "Pairwise", "direct-seq": "Sequential",
             "direct-binary": "Binary", "direct-commander": "Commander", "direct-product": "Product"}
    def table(fname, key):
        L = [r"\begin{tabular}{lrrr" + "r" * len(SIZE_CONFIGS) + "}", r"\toprule",
             r"Đề & $n$ & $|E|$ & $H$ & " + " & ".join(short[c] for c in SIZE_CONFIGS) + r" \\", r"\midrule"]
        for name in SIZE_INSTANCES:
            rs = {r["config"]: r for r in rows if r["instance"] == name}
            best = min(r[key] for r in rs.values()); r0 = rs["full"]
            cells = [(r"\textbf{%s}" % thin(rs[c][key])) if rs[c][key] == best else thin(rs[c][key]) for c in SIZE_CONFIGS]
            L.append(f"{name} & {r0['n']} & {r0['E']} & {r0['H']} & " + " & ".join(cells) + r" \\")
        L += [r"\bottomrule", r"\end{tabular}"]
        open(os.path.join(tdir, fname), "w", encoding="utf-8").write("\n".join(L) + "\n")
    table("size_vars.tex", "vars"); table("size_cls.tex", "clauses")
    ms = [25, 50, 100, 200]
    form = {"pairwise": ("$0$", "$m(m-1)/2$"), "seq": ("$m-1$", "$3m-4$"),
            "binary": (r"$\lceil\log_2 m\rceil$", r"$m\lceil\log_2 m\rceil$"),
            "commander": (r"$g=\lceil m/3\rceil$", r"$\binom{g}{2}+g+m+\sum_i\binom{s_i}{2}$"),
            "product": ("$p+q$", r"$2m+\binom{p}{2}+\binom{q}{2}$")}
    L = [r"\begin{tabular}{lll" + "c" * len(ms) + "}", r"\toprule",
         "Mã hóa AMO & Số biến phụ & Số mệnh đề & " + " & ".join(f"$m={m}$" for m in ms) + r" \\", r"\midrule"]
    for k in AMO:
        cells = [f"{amo_cost(k, m)[0]}\\,/\\,{amo_cost(k, m)[1]}" for m in ms]
        L.append(f"{AMO_LABEL[k]} & {form[k][0]} & {form[k][1]} & " + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(tdir, "amo_group_sizes.tex"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "serif"})
    fam = ["GEOM20", "GEOM40", "GEOM60", "GEOM80", "GEOM100", "GEOM120"]
    fig, axs = plt.subplots(1, 2, figsize=(6.6, 2.7))
    mk = dict(zip(SIZE_CONFIGS, "osv^D<>"))
    for ax, key, ttl in ((axs[0], "vars", "(a) số biến"), (axs[1], "clauses", "(b) số mệnh đề")):
        for c in SIZE_CONFIGS:
            ys = [r[key] for n in fam for r in rows if r["instance"] == n and r["config"] == c]
            ax.plot(range(len(fam)), ys, marker=mk[c], ms=3.5, lw=1, label=short[c])
        ax.set_yscale("log"); ax.set_xticks(range(len(fam))); ax.set_xticklabels(fam, rotation=45); ax.set_title(ttl, fontsize=8); ax.grid(alpha=.3)
    axs[0].legend(fontsize=6.5, frameon=False)
    plt.tight_layout(); os.makedirs(os.path.join(a.out, "figures"), exist_ok=True)
    plt.savefig(os.path.join(a.out, "figures", "encoding_size.pdf")); plt.close()
    print("wrote tables/size_vars.tex, size_cls.tex, amo_group_sizes.tex, figures/encoding_size.pdf, results/encoding_sizes.csv")

# ----------------------------------------------------------------------------
# 9. CLI
# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("sizes"); p.add_argument("--out", default="../report")
    p = sp.add_parser("verify"); p.add_argument("--out", default="../report"); p.add_argument("--graphs", type=int, default=200)
    p = sp.add_parser("solve"); p.add_argument("--instance", required=True); p.add_argument("--config", default="full", choices=list(CONFIGS))
    p.add_argument("--solver", default="cadical195", help="dpll (reference) or a PySAT name, e.g. glucose4")
    p = sp.add_parser("dimacs"); p.add_argument("--instance", required=True); p.add_argument("--config", default="full", choices=list(CONFIGS))
    p.add_argument("--k", type=int, required=True); p.add_argument("--out", required=True)
    p = sp.add_parser("gen"); p.add_argument("--n", type=int, default=30); p.add_argument("--dist", type=int, default=2000000)
    p.add_argument("--max-weight", type=int, default=10); p.add_argument("--seed", type=int, default=0); p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "sizes": return cmd_sizes(a)
    if a.cmd == "verify": return cmd_verify(a)
    if a.cmd == "gen":
        g = random_geometric(a.n, a.dist, a.max_weight, a.seed); write_col(a.out, g)
        print(f"wrote {a.out}: n={g.n}, |E|={len(g.edges)}"); return 0
    g = read_col(a.instance)
    if a.cmd == "dimacs":
        H = max(first_fit(g)); enc = Encoding(g, H, CONFIGS[a.config]); s = ListSink()
        enc.fixed(s); enc.delta(a.k, s); write_dimacs(a.out, s.clauses, enc.pool.top)
        print(f"wrote {a.out}: {enc.pool.top} vars, {s.n} clauses"); return 0
    t = time.time()
    make = DPLLBackend if a.solver == "dpll" else (lambda nv: PySATBackend(a.solver))
    r = search(g, CONFIGS[a.config], make, on_incumbent=lambda b: print(f"  span {b}  ({time.time()-t:.2f}s)"))
    print(f"{r['status']} span={r['span']} H={r['H']} LB={r['LB']} calls={r['calls']} vars={r['vars']} clauses={r['clauses']} {time.time()-t:.2f}s")
    if r["coloring"]: print(" ".join(map(str, r["coloring"])))
    return 0

if __name__ == "__main__":
    sys.exit(main())
