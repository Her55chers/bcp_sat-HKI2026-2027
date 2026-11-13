#!/usr/bin/env python3
"""Solve the 4-vertex example with the SAT encoding and write TikZ for the report."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcp_sat as S

POS = [(0, 0), (1.5, 1.25), (1.5, -1.25), (3, 0)]
LABEL_ANCHOR = {(0, 1): "above left", (0, 2): "below left", (1, 2): "right", (1, 3): "above right", (2, 3): "below right"}

def axis(col, title, shift):
    L = [f"\\begin{{scope}}[shift={{(4.6,{shift})}}]", "\\draw (0,0)--(7.6,0);"]
    for k in range(1, 9):
        L.append(f"\\draw ({k-.7:.1f},-0.06)--({k-.7:.1f},0.06); \\node[font=\\scriptsize,below] at ({k-.7:.1f},-0.04) {{{k}}};")
    seen = {}
    top = max(col)
    for v, k in enumerate(col):
        h = seen.get(k, 0); seen[k] = h + 1
        st = "peak" if k == top else "vert"
        L.append(f"\\node[{st}] at ({k-.7:.1f},{0.42+0.68*h:.2f}) {{$v_{v+1}$}};")
    L.append(f"\\node[font=\\footnotesize,anchor=west] at (1,1.1) {{{title}}};")
    L.append("\\end{scope}")
    return L

g = S.EXAMPLE
res = S.search(g, S.CONFIGS["full"], S.DPLLBackend)
assert res["status"] == "OPTIMAL" and S.is_valid_coloring(g, res["coloring"])
opt = res["coloring"]
feas = [1, 4, 8, 1]
assert S.is_valid_coloring(g, feas)
out = ["\\begin{tikzpicture}[vert/.style={circle,draw,minimum size=6.2mm,inner sep=0pt,font=\\footnotesize},",
       "  peak/.style={vert,draw=blue!70!black,fill=blue!10,thick}, wt/.style={font=\\footnotesize}]"]
for v, (x, y) in enumerate(POS):
    out.append(f"\\node[vert] (v{v}) at ({x},{y}) {{$v_{v+1}$}};")
for u, v, d in g.edges:
    out.append(f"\\draw (v{u})--node[wt,{LABEL_ANCHOR[(u, v)]}]{{{d}}}(v{v});")
out.append("\\node[font=\\footnotesize] at (1.5,-2.15) {(a) đồ thị $G$, số trên cạnh là $d_{uv}$};")
out += axis(feas, f"(b) phép tô khả thi, span {max(feas)}", 0.55)
out += axis(opt, f"(c) phép tô đọc từ mô hình SAT, span {max(opt)}", -1.95)
out.append("\\end{tikzpicture}")
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "report", "figures", "bcp_example.tex")
os.makedirs(os.path.dirname(path), exist_ok=True)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("coloring:", opt, "span", max(opt), "-> wrote", path)
