"""
src/geometry_logic.py
=====================
Self-contained symbolic computation module for the ETC pipeline.

Implements solve_expression(expr_str) which takes a cleaned colon-separated
barycentric string and returns a SolveResult with x_t, y_t, weierstrass_n, etc.

This module is imported by scripts/02_run_computation.py (_pebble_entry calls
solve_expression). All functions are defined at module level so pebble/loky can
pickle them by reference.
"""
from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from typing import Optional

import sympy as sp
from sympy.core.cache import clear_cache
from sympy.functions.elementary.trigonometric import TrigonometricFunction
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════
# EMBEDDED MATH — cells 6, 7, 8, 9, 10 of ETC_Center_Table_Thales
# ═══════════════════════════════════════════════════════════════════
import re
import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations, implicit_multiplication_application, convert_xor
)

# ── String-cleaning helpers ───────────────────────────────────────────────────
# (These are defined here as module-level functions; clean_bary is called
#  inside _compute_one so the pipeline is robust to cell execution order.)

_UNICODE_MAP = {
    '²': '**2', '³': '**3', '⁴': '**4', '⁵': '**5',
    '·': '*', '−': '-', '–': '-', ' ': ' ',
    'π': 'pi', 'α': 'alpha', 'β': 'beta', 'γ': 'gamma'
}
_TRIG        = r'(sin|cos|tan|cot|sec|csc)'
_KNOWN_FUNCS = frozenset(['sin','cos','tan','cot','sec','csc','sqrt','Abs','pi','exp','log'])
_ABSTRACT_FN = re.compile(r'\b[fghFGH]\s*\(')


def _insert_impl_mul(s):
    """Insert * before ( when preceded by a non-function identifier."""
    def rep(m):
        return m.group(1) + ('(' if m.group(1) in _KNOWN_FUNCS else '*(')
    return re.sub(r'\b([A-Za-z_][A-Za-z0-9_]*)\(', rep, s)


def string_expand_func(expr, fname, v1, v2, v3, body):
    """
    Expand all occurrences of  fname(arg1, arg2, arg3)  by substituting
    the formal parameters (v1, v2, v3) with the actual arguments.

    Sentinel characters \x01\x02\x03 prevent cascade substitution when the
    arguments themselves contain the parameter names.
    """
    if not expr: return expr
    pattern = rf'\b{re.escape(fname)}\s*\(([^,)]+),\s*([^,)]+),\s*([^)]+)\)'
    def repl(m):
        a1, a2, a3 = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        res = body
        S1, S2, S3 = '\x01', '\x02', '\x03'
        res = re.sub(rf'\b{re.escape(v1)}\b', S1, res)
        res = re.sub(rf'\b{re.escape(v2)}\b', S2, res)
        res = re.sub(rf'\b{re.escape(v3)}\b', S3, res)
        return f'({res.replace(S1, f"({a1})").replace(S2, f"({a2})").replace(S3, f"({a3})")})'
    return re.sub(pattern, repl, expr)


def clean_bary(text):
    if not isinstance(text, str): return ""
    
    # Unicode and common replacements
    for k, v in _UNICODE_MAP.items():
        text = text.replace(k, v)
    text = text.replace('^', '**')
    
    # Conway and Sw (Conway symbols are handled first to avoid 's' conflicts)
    text = text.replace('S_A', 'SA').replace('S_B', 'SB').replace('S_C', 'SC')
    text = re.sub(r'S_\\omega|S_w|Somega', 'Sw', text)
    
    # Trig regex: sin 2A -> sin(2*A), sin^2 A -> sin(A)**2
    # These use \b (word boundaries) to protect variables like 's' or 'r'
    text = re.sub(r'(sin|cos|tan|cot|sec|csc)\*\*2\s*([A-C])', r'\1(\2)**2', text)
    text = re.sub(r'\b(sin|cos|tan|cot|sec|csc)\s+([A-C])\b', r'\1(\2)', text)
    text = re.sub(r'\b(sin|cos|tan|cot|sec|csc)\s+([A-C])/(\d+)\b', r'\1(\2/\3)', text)
    
    return text.strip()


import sympy as sp
import math

# ── Symbols ───────────────────────────────────────────────────────────────────
theta, t = sp.symbols('theta t', real=True)
C_ang     = sp.Symbol('C', real=True, positive=True)  # kept symbolic for limits
w_sym     = sp.Symbol('w', positive=True)              # Brocard angle

S, SA, SB, SC = sp.symbols('S SA SB SC', real=True)
Sw, s          = sp.symbols('Sw s',       real=True)
sa, sb, sc     = sp.symbols('sa sb sc',   real=True)
r, R           = sp.symbols('r R',        positive=True)

# ── Vertex angles ─────────────────────────────────────────────────────────────
#   A=(1,0), B=(-1,0), C=(cos theta, sin theta) on the unit circumcircle
#   By the inscribed-angle theorem:
#     angle A = (pi - theta)/2,  angle B = theta/2,  angle C = pi/2
#
#   C is placed directly in geom_sub as pi/2.
#   Expressions like  sin(C)=1, cos(C)=0, tan(C)=zoo  are evaluated immediately.
#   A zoo (complex infinity) result means the center has a pole at C=pi/2
#   for our right-triangle setup -- caught in _compute_one as "degen:C_pole".
#   This is faster and more robust than calling sp.limit for every center.
A_angle = (sp.pi - theta) / 2
B_angle = theta / 2
C_angle = sp.pi / 2   # placed in geom_sub

# ── Side lengths ──────────────────────────────────────────────────────────────
a_side = 2 * sp.cos(theta / 2)   # BC (opposite A)
b_side = 2 * sp.sin(theta / 2)   # CA (opposite B)
c_side = sp.Integer(2)           # AB = 2R = 2  (hypotenuse / diameter)

# ── Conway symbols ────────────────────────────────────────────────────────────
a2, b2, c2 = a_side**2, b_side**2, c_side**2
SA_val = (b2 + c2 - a2) / 2     # = 2(1 - cos theta)
SB_val = (c2 + a2 - b2) / 2     # = 2(1 + cos theta)
SC_val = sp.Integer(0)           # right-angle at C -> a^2+b^2 = c^2

# S = 2*Area.
#   Area = (1/2)*a*b*sin(C) = (1/2)*a*b   so  S = a*b = 2*sin(theta)
S_val  = a_side * b_side

s_val  = (a_side + b_side + c_side) / 2
r_val  = S_val / (2 * s_val)     # inradius = Area/s = S/(2s)
R_val  = sp.Integer(1)           # circumradius = 1
Sw_val = SA_val + SB_val         # S_omega = SA+SB+SC = SA+SB  (SC=0)

# Brocard angle w:
#   General formula:  cot(w) = (a^2+b^2+c^2) / (2S)
#   For our right triangle: (a^2+b^2+c^2)/(2S) = 8/(2*2sin(theta)) = 2/sin(theta)
#   Also: cot(w) = cot(A)+cot(B)+cot(C)  with cot(pi/2)=0
#   => cot(w) = tan(theta/2) + cot(theta/2)  [via double-angle identities]
cotw_val = (a2 + b2 + c2) / (2 * S_val)   # = 2/sin(theta)
w_val    = sp.acot(cotw_val)               # atan(sin(theta)/2)

# ── Substitution dictionary ───────────────────────────────────────────────────
# C_ang -> pi/2 is included directly.
#   - sin(C)=1, cos(C)=0 substitute cleanly.
#   - tan(C)=zoo, sec(C)=zoo: these produce zoo in the output, which is
#     caught by the "degen:C_pole" check in _compute_one.
#   - This replaces the former sp.limit(expr, C_ang, pi/2) slow path,
#     which was the primary cause of 3-5 hour runtimes on complex inputs.
geom_sub = {
    sp.Symbol('a'): a_side,
    sp.Symbol('b'): b_side,
    sp.Symbol('c'): c_side,
    sp.Symbol('A'): A_angle,
    sp.Symbol('B'): B_angle,
    C_ang:          sp.pi / 2,   # direct substitution; zoo caught downstream
    S: S_val, SA: SA_val, SB: SB_val, SC: SC_val, Sw: Sw_val,
    s: s_val,
    sa: s_val - a_side, sb: s_val - b_side, sc: s_val - c_side,
    r: r_val, R: R_val,
    # Brocard angle: cot and tan substituted directly; sin/cos handled via w_val
    sp.cot(w_sym): cotw_val,
    sp.tan(w_sym): sp.Integer(1) / cotw_val,
    w_sym: w_val,
}

# ── Rational parametrisation  t = tan(theta/4) ───────────────────────────────
THETA_T = 4 * sp.atan(t)

_s2  = 2*t / (1 + t**2)
_c2  = (1 - t**2) / (1 + t**2)
_sth = sp.cancel(2 * _s2 * _c2)
_cth = sp.cancel(_c2**2 - _s2**2)

rat_sub_dict = {
    sp.sin(theta/2):  _s2,
    sp.cos(theta/2):  _c2,
    sp.tan(theta/2):  sp.cancel(_s2 / _c2),
    sp.cot(theta/2):  sp.cancel(_c2 / _s2),
    sp.sin(theta):    _sth,
    sp.cos(theta):    _cth,
    sp.tan(theta):    sp.cancel(_sth / _cth),
    sp.cot(theta):    sp.cancel(_cth / _sth),
}

print("Geometry setup complete.")
print(f"  a  = {a_side}")
print(f"  b  = {b_side}")
print(f"  S  = {sp.simplify(S_val)}   (Conway S = 2*Area)")
print(f"  SA = {sp.simplify(SA_val)}")
print(f"  SB = {sp.simplify(SB_val)}")
print(f"  SC = {SC_val}              (right angle at C)")
print(f"  cot(w) = {sp.simplify(cotw_val)}")
print(f"  Note: C=pi/2 in geom_sub; tan(C)/sec(C) poles caught as degen:C_pole")

import numpy as np

import math
from sympy.functions.elementary.trigonometric import TrigonometricFunction


def detect_denominators(expr):
    """
    Return list of all denominators d found in theta/d trig arguments.

    Used to determine the optimal Weierstrass substitution parameter.
    The LCD of the returned list = n  gives  t = tan(theta/(2n)).

    Design: uses as_coefficient(theta) which is O(n) and exact, unlike
    sp.simplify(arg/theta) which is slow and can fail on multi-term args.
    """
    denoms = []
    for node in expr.find(TrigonometricFunction):
        arg = node.args[0]
        for term in sp.Add.make_args(sp.expand(arg)):
            c = term.as_coefficient(theta)
            if c is not None and c.is_Rational and c != 0:
                denoms.append(int(abs(c).q))
    return denoms if denoms else [1]


def _is_power_of_two(m: int) -> bool:
    return m > 0 and (m & (m - 1)) == 0


def choose_weierstrass_n(denoms):
    """
    Choose n in  t = tan(theta/(2n)) using the deepest-angle policy.

    - Power-of-2-only denominators: n = max(denoms) = 2^k
      (deepest angle theta/2^k -> tangent half-angle uses theta/2^(k+1)).
      Example: sin(theta/2), tan(theta) -> n=2 -> t=tan(theta/4).

    - Mixed prime factors: n = lcd/lcm(denoms).
      Example: sin(theta/2)*sin(theta/3) -> n=6 -> t=tan(theta/12).

    Keeping the explicit LCD/LCD-path is required for project traceability.
    """
    clean = [abs(int(d)) for d in denoms if int(d) != 0]
    if not clean:
        return 1

    if all(_is_power_of_two(d) for d in clean):
        return max(clean)

    # Explicit LCD (LCM) branch for mixed-prime denominators.
    return math.lcm(*clean)


def build_weierstrass_sub(n):
    """
    Build a fast-path substitution dict for  t = tan(theta/(2n)).

    Covers sin/cos/tan/cot of theta/n (base) and theta/(n/2) (double base)
    directly; compound multiples are handled by the general rewrite(tan) path.

    Returns (THETA_T, rat_sub_dict) where THETA_T = 2n*atan(t).
    """
    THETA_T_n = sp.Integer(2) * n * sp.atan(t)
    u   = theta / n                        # base angle
    su  = 2*t      / (1 + t**2)            # sin(u) = sin(theta/n)
    cu  = (1-t**2) / (1 + t**2)            # cos(u)
    s2u = sp.cancel(2 * su * cu)           # sin(2u)
    c2u = sp.cancel(cu**2 - su**2)         # cos(2u)
    rsd = {
        sp.sin(u): su,   sp.cos(u): cu,
        sp.tan(u): sp.cancel(su/cu),   sp.cot(u): sp.cancel(cu/su),
        sp.sin(2*u): s2u, sp.cos(2*u): c2u,
        sp.tan(2*u): sp.cancel(s2u/c2u), sp.cot(2*u): sp.cancel(c2u/s2u),
    }
    return THETA_T_n, rsd




def is_degenerate_denom(u_th, v_th, w_th):
    """
    Return True if u + v + w is identically zero after geometry substitution.

    A zero sum means the three weights define a point at projective infinity --
    no finite Cartesian coordinates exist.  Detecting this early prevents a
    ZeroDivisionError (or zoo result) deep inside the pipeline.
    """
    return sp.cancel(u_th + v_th + w_th) == 0


def make_numpy_func(expr_t):
    """
    Wrap sp.lambdify so that the returned callable always produces a
    1-D numpy array, even when expr_t is a numeric constant.

    sp.lambdify of a constant (e.g. X(3) Circumcenter x = 0) returns a
    Python int/float, not an array.  Broadcasting is needed before
    downstream code can treat all x_func / y_func uniformly.
    """
    raw = sp.lambdify(t, expr_t, modules='numpy')

    def f(t_vals):
        t_arr = np.asarray(t_vals, dtype=float)
        result = raw(t_arr)
        if np.ndim(result) == 0:              # constant expression
            return np.full(t_arr.shape, float(result))
        return np.asarray(result, dtype=float)

    return f


from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations, implicit_multiplication_application, convert_xor
)

# Enable implicit multiplication: a(b+c) -> a*(b+c), 2SA -> 2*SA
_TRANSF = standard_transformations + (implicit_multiplication_application, convert_xor)

# Canonical symbols reused across all parse calls for stability + speed
_PARSE_LOCALS = {
    'a': sp.Symbol('a', real=True, positive=True),
    'b': sp.Symbol('b', real=True, positive=True),
    'c': sp.Symbol('c', real=True, positive=True),
    'A': sp.Symbol('A', real=True),
    'B': sp.Symbol('B', real=True),
    'C': C_ang,
    'SA': SA, 'SB': SB, 'SC': SC,
    'S': S, 'Sw': Sw, 'SW': Sw,
    's': s, 'sa': sa, 'sb': sb, 'sc': sc,
    'r': r, 'R': R, 'w': w_sym,
    'sin': sp.sin, 'cos': sp.cos, 'tan': sp.tan,
    'cot': sp.cot, 'sec': sp.sec, 'csc': sp.csc,
    'sqrt': sp.sqrt, 'Abs': sp.Abs, 'exp': sp.exp, 'log': sp.log,
    'pi': sp.pi,
}


def _expand_custom_functions(expr_text, custom_funcs):
    out = expr_text
    if not custom_funcs:
        return out
    for fname, defn in custom_funcs.items():
        if not (isinstance(defn, (tuple, list)) and len(defn) == 4):
            continue
        v1, v2, v3, body = defn
        out = string_expand_func(out, fname, v1, v2, v3, body)
    return out


def parse_bary(bary_str, custom_funcs=None):
    """Parse a barycentric triple string into a SymPy tuple (u, v, w)."""
    if not isinstance(bary_str, str) or ':' not in bary_str:
        return None

    expanded = _expand_custom_functions(bary_str, custom_funcs)
    parts = [p.strip() for p in expanded.split(':')]
    if len(parts) < 3:
        return None
    parts = parts[:3]
    if any(not p for p in parts):
        return None

    try:
        parsed = tuple(
            parse_expr(piece, local_dict=_PARSE_LOCALS, transformations=_TRANSF, evaluate=False)
            for piece in parts
        )
    except Exception:
        return None

    return parsed if len(parsed) == 3 else None


# ── Fast-path substitution dict for n=2  (t = tan(θ/4)) ─────────────────────
_t_sq   = t**2
_denom  = 1 + _t_sq
_denom2 = _denom**2

_FAST_SUB_N2 = {
    sp.sin(theta/2):  2*t / _denom,
    sp.cos(theta/2):  (1 - _t_sq) / _denom,
    sp.tan(theta/2):  2*t / (1 - _t_sq),
    sp.cot(theta/2):  (1 - _t_sq) / (2*t),
    sp.sin(theta):    4*t*(1 - _t_sq) / _denom2,
    sp.cos(theta):    ((1 - _t_sq)**2 - 4*_t_sq) / _denom2,
    sp.tan(theta):    4*t*(1 - _t_sq) / ((1 - _t_sq)**2 - 4*_t_sq),
    sp.cot(theta):    ((1 - _t_sq)**2 - 4*_t_sq) / (4*t*(1 - _t_sq)),
}

# ── Pre-computed Cx(t), Cy(t) ────────────────────────────────────────────────
_CX_T = {}; _CY_T = {}

def _get_CxCy(n):
    if n not in _CX_T:
        if n == 2:
            _CX_T[2] = sp.cancel(sp.cos(theta).subs(_FAST_SUB_N2))
            _CY_T[2] = sp.cancel(sp.sin(theta).subs(_FAST_SUB_N2))
        else:
            THETA_T = sp.Integer(2)*n*sp.atan(t)
            cx = sp.expand_trig(sp.cos(theta).subs(theta, THETA_T))
            cy = sp.expand_trig(sp.sin(theta).subs(theta, THETA_T))
            _CX_T[n] = sp.cancel(cx.rewrite(sp.tan).subs(sp.tan(sp.atan(t)), t))
            _CY_T[n] = sp.cancel(cy.rewrite(sp.tan).subs(sp.tan(sp.atan(t)), t))
    return _CX_T[n], _CY_T[n]

_get_CxCy(2)   # warm up at import time


# ── Plain dict caches (picklable by loky/cloudpickle, unlike @lru_cache) ────
# @lru_cache decorated functions cannot be pickled in interactive Jupyter contexts.
# Plain dict caches are always picklable and persist within each worker process
# for its 500-task lifetime (max_tasks_per_child=500).
# maxsize enforced by pruning the oldest half when the limit is reached.

_GEOM_CACHE = {}
_RAT_CACHE  = {}
_CACHE_MAX  = 8192

def _cached_geom_expand(expr):
    """Dict-cached sp.expand_trig(expr.subs(geom_sub)) — picklable."""
    if expr not in _GEOM_CACHE:
        if len(_GEOM_CACHE) >= _CACHE_MAX:
            for k in list(_GEOM_CACHE)[:_CACHE_MAX // 2]:
                del _GEOM_CACHE[k]
        _GEOM_CACHE[expr] = sp.expand_trig(expr.subs(geom_sub))
    return _GEOM_CACHE[expr]

def _cached_rationalize(expr, n):
    """Dict-cached _rationalize_one — picklable."""
    key = (expr, n)
    if key not in _RAT_CACHE:
        if len(_RAT_CACHE) >= _CACHE_MAX:
            for k in list(_RAT_CACHE)[:_CACHE_MAX // 2]:
                del _RAT_CACHE[k]
        _RAT_CACHE[key] = _rationalize_one(expr, n)
    return _RAT_CACHE[key]


# ── AST Complexity Scorer ────────────────────────────────────────────────────

def _count_ast_nodes(expr):
    """Count the number of nodes in a SymPy expression tree (fast traversal)."""
    if not isinstance(expr, sp.Basic):
        return 0
    return sum(1 for _ in sp.preorder_traversal(expr))

def _score_coords(coords):
    """
    Heuristic cost of a barycentric triple (u, v, w).

    Lower score = cheaper to process through geom_sub + GCD pipeline.

    Scoring rules (applied to parsed SymPy, before geom_sub):
      base  = total AST nodes (reflects expression size)
      × 10  if any component contains a TrigonometricFunction
             (trig → polynomial conversion via rewrite(tan) is expensive)
      × 1.5 if any component contains Pow (rational exponents, sqrt)

    Why score BEFORE geom_sub?
    The raw parsed symbols (SA, SB, a, b, ...) reveal structure cheaply.
    After geom_sub everything becomes sin/cos of theta anyway.
    """
    base     = sum(_count_ast_nodes(c) for c in coords)
    has_trig = any(c.has(TrigonometricFunction) for c in coords)
    has_pow  = any(c.has(sp.Pow) for c in coords)
    return base * (10 if has_trig else 1) * (1.5 if has_pow else 1)

def _choose_simplest(parsed_list):
    """
    Given a list of parsed (u, v, w) triples, return the one with the
    lowest AST complexity score.
    """
    best, best_score = None, float('inf')
    for coords in parsed_list:
        if coords is None:
            continue
        s = _score_coords(coords)
        if s < best_score:
            best_score = s
            best = coords
    return best


# ── Core rationalize helpers ─────────────────────────────────────────────────

def _rationalize_one(expr, n):
    """Rationalize without cancel (caller decides when to cancel)."""
    if expr is None or not isinstance(expr, sp.Basic):
        return None
    if n == 2:
        r = expr.subs(_FAST_SUB_N2)
        if not r.has(TrigonometricFunction):
            return r
    THETA_T_n = sp.Integer(2)*n*sp.atan(t)
    sub = sp.expand_trig(expr.subs(theta, THETA_T_n))
    a2r = sub.rewrite(sp.tan).subs(sp.tan(sp.atan(t)), t)
    return a2r if not a2r.has(theta) else None

def rationalize_expr(expr_theta, n_override=None):
    """Public API: rationalize and cancel."""
    n = n_override if n_override is not None else 2
    r = _rationalize_one(expr_theta, n)
    return sp.cancel(r) if r is not None else None


def _safe_poly_lcm(a, b, syms):
    """
    Compute LCM of two expressions via Poly objects.
    Poly.lcm().as_expr() always returns a clean SymPy Expr, never a Tuple.
    """
    try:
        return sp.lcm(sp.Poly(a, *syms), sp.Poly(b, *syms)).as_expr()
    except Exception:
        # Integer-GCD fallback -- also stays in Expr-land
        g = sp.gcd(a, b)
        return a * (b // g) if g != 0 else a * b


def clear_denominators(expr):
    """Lighter-weight denominator clearing using cancel() only."""
    if expr is None: return None
    try:
        # cancel() is significantly faster than simplify() for barycentrics
        n, d = sp.fraction(sp.cancel(expr))
        return n if d != 0 else expr
    except:
        return expr

def resolve_C(x_expr, y_expr):
    """
    [LEGACY - now a no-op]

    C_ang -> pi/2 is handled directly in geom_sub (Cell 7).
    After geom_sub, C_ang never appears in the Cartesian expressions.
    Centers where tan(C) or sec(C) produce zoo are caught earlier
    in _compute_one by the "degen:C_pole" check.

    sp.limit was removed as the slow path here was the primary cause
    of worker threads blocking for 3-5 hours on complex inputs.
    """
    return x_expr, y_expr


# Patch: _PARSE_LOCALS uses positive=True symbols for a,b,c,r.
# Add them to geom_sub so substitution works regardless of assumptions.
_a_pos = sp.Symbol('a', real=True, positive=True)
_b_pos = sp.Symbol('b', real=True, positive=True)
_c_pos = sp.Symbol('c', real=True, positive=True)
_r_pos = sp.Symbol('r', real=True, positive=True)
_R_pos = sp.Symbol('R', real=True, positive=True)
geom_sub.update({
    _a_pos: a_side, _b_pos: b_side, _c_pos: c_side,
    _r_pos: r_val,  _R_pos: R_val,
})

# ═══════════════════════════════════════════════════════════════════
# PIPELINE HELPERS — from notebook cell 23
# ═══════════════════════════════════════════════════════════════════
import time
import warnings
import pandas as pd
import sympy as sp
import pickle
from pathlib import Path
from joblib import Parallel, delayed
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, convert_xor
from sympy.functions.elementary.trigonometric import TrigonometricFunction

warnings.filterwarnings("ignore")

# ── 1) Complexity routing + helpers ───────────────────────────────────────────
_TRIG_WORDS = ('sin', 'cos', 'tan', 'cot', 'sec', 'csc')


def bary_complexity_score(raw):
    """Lower score means algebraically cheaper candidate."""
    if not isinstance(raw, str):
        return 10**9
    s = raw.replace(' ', '')
    trig_penalty = 40 * sum(s.count(w) for w in _TRIG_WORDS)
    len_penalty = len(s)
    op_penalty = s.count('/') * 5 + s.count('**') * 3
    return trig_penalty + len_penalty + op_penalty


def _normalize_bary_list(bary_list):
    """Drop empty/duplicate strings while preserving order."""
    out, seen = [], set()
    if not isinstance(bary_list, list):
        return out
    for b in bary_list:
        if not isinstance(b, str):
            continue
        key = " ".join(b.split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _normalize_funcs(funcs):
    """Canonicalize function dictionary for stable task keys."""
    if not isinstance(funcs, dict):
        return {}
    norm = {}
    for name, defn in funcs.items():
        if not (isinstance(name, str) and isinstance(defn, (tuple, list)) and len(defn) == 4):
            continue
        v1, v2, v3, body = defn
        norm[name.lower().strip()] = (str(v1).strip(), str(v2).strip(), str(v3).strip(), " ".join(str(body).split()))
    return norm


def _geom_eval_triplet(uvw):
    # Light symbolic simplification first improves robustness before Weierstrass.
    return tuple(sp.cancel(sp.expand_trig(sp.trigsimp(comp.subs(geom_sub)))) for comp in uvw)


def _contains_pole(uvw):
    return any(comp.has(sp.zoo, sp.oo, -sp.oo, sp.nan) for comp in uvw)


def _weierstrass_profile(denoms):
    """Return n and deepest angle denominator K for t = tan(theta/K), K=2n."""
    n = choose_weierstrass_n(denoms if denoms else [1])
    return n, 2 * n


def _expr_signature(x_expr, y_expr):
    """Cache key by algebraic x(t), y(t), independent of Weierstrass angle metadata."""
    return f"{sp.srepr(sp.cancel(x_expr))}||{sp.srepr(sp.cancel(y_expr))}"


def bary_to_cartesian(uvw_t, n_val):
    """Convert barycentric weights (u,v,w) to Cartesian x(t), y(t)."""
    u, v, w = uvw_t
    denom = sp.cancel(u + v + w)
    if denom == 0:
        return None, None

    Cx, Cy = _get_CxCy(n_val)
    x_expr = sp.cancel((u - v + w*Cx) / denom)
    y_expr = sp.cancel((w*Cy) / denom)
    return x_expr, y_expr


def _compute_one(bary_list, funcs_dict, algebra_cache=None):
    """
    Evaluate barycentrics in listed order and choose by:
      1) shallowest successful Weierstrass denominator (min 2*n => fewer terms),
      2) cleanest structure via complexity,
      3) expression size.

    Returns: (chosen_tuple, candidate_cache_rows)
    chosen_tuple = (x, y, weierstrass_n, deepest_factor, deepest_angle_den,
                    bary_checked, bary_valid, eval_status)
    """
    ranked = _normalize_bary_list(bary_list)  # preserve extraction order
    funcs_dict = _normalize_funcs(funcs_dict)
    if not ranked:
        return (None, None, None, None, None, 0, 0, "no_bary"), []

    checked, valid = 0, 0
    candidates = []
    algebra_cache = algebra_cache if isinstance(algebra_cache, dict) else {}

    for raw_idx, raw_str in enumerate(ranked, 1):
        checked += 1
        cleaned = clean_bary(raw_str)
        parsed = parse_bary(cleaned, funcs_dict)
        if parsed is None:
            continue

        parsed = tuple(clear_denominators(p) for p in parsed)

        try:
            theta_triplet = _geom_eval_triplet(parsed)
        except Exception:
            continue

        if _contains_pole(theta_triplet):
            continue

        denoms = []
        for comp in theta_triplet:
            denoms.extend(detect_denominators(comp))

        auto_n, _ = _weierstrass_profile(denoms)
        n_candidates = []
        for n_val in [auto_n, 2, 4, 1]:
            if n_val not in n_candidates:
                n_candidates.append(n_val)

        complexity = bary_complexity_score(raw_str)

        for n_val in n_candidates:
            try:
                rat_triplet = tuple(rationalize_expr(comp, n_override=n_val) for comp in theta_triplet)
                if any(val is None for val in rat_triplet):
                    continue

                x_t, y_t = bary_to_cartesian(rat_triplet, n_val)
                if x_t is None or y_t is None:
                    continue
                if theta in x_t.free_symbols or theta in y_t.free_symbols:
                    continue

                valid += 1
                deep_den = 2 * int(n_val)
                expr_size = len(str(x_t)) + len(str(y_t))
                sig = _expr_signature(x_t, y_t)

                # If algebra already known in previous caches, prefer cached canonical row.
                cached = algebra_cache.get(sig)
                if cached:
                    x_t, y_t = cached['x'], cached['y']

                candidates.append({
                    'raw_idx': raw_idx,
                    'complexity': complexity,
                    'expr_size': expr_size,
                    'x': x_t,
                    'y': y_t,
                    'n': int(n_val),
                    'deepest_factor': int(n_val),
                    'deep_den': deep_den,
                    'sig': sig,
                    'raw': raw_str,
                })
            except Exception:
                continue

    if not candidates:
        return (None, None, None, None, None, checked, valid, "no_valid_route"), []

    # Least Weierstrass terms first => minimum denominator among valid candidates.
    best_deep_den = min(c['deep_den'] for c in candidates)
    top = [c for c in candidates if c['deep_den'] == best_deep_den]
    top.sort(key=lambda c: (c['complexity'], c['expr_size'], c['raw_idx']))
    chosen = top[0]

    chosen_tuple = (
        chosen['x'], chosen['y'], chosen['n'], chosen['deepest_factor'], chosen['deep_den'],
        checked, valid, "ok"
    )

    # Store all unchosen expressions in cache rows (NOT dataframe)
    cache_rows = []
    for c in candidates:
        cache_rows.append({
            'sig': c['sig'],
            'x': c['x'],
            'y': c['y'],
            'n': c['n'],
            'deepest_factor': c['deepest_factor'],
            'deep_den': c['deep_den'],
            'complexity': c['complexity'],
            'expr_size': c['expr_size'],
            'raw': c['raw'],
            'chosen': c is chosen,
        })

    return chosen_tuple, cache_rows


def _make_task_key(bl, fn):
    bl_key = tuple(_normalize_bary_list(bl))
    fn_norm = _normalize_funcs(fn)
    fn_key = tuple(sorted((k, tuple(v)) for k, v in fn_norm.items()))
    return bl_key, fn_key


def _run_task(task, algebra_cache):
    key, bl, fn = task
    chosen, cache_rows = _compute_one(bl, fn, algebra_cache=algebra_cache)
    return key, chosen, cache_rows


def _run_task_pebble(packed):
    """Pebble-compatible wrapper: takes a single packed tuple (key, bl, fn).
    Must be defined at module level for pebble to pickle by reference."""
    key, bl, fn = packed
    chosen, cache_rows = _compute_one(bl, fn, algebra_cache={})
    return key, chosen, cache_rows


def _parallel_run(task_list, backend_name, algebra_cache, n_jobs=-1, chunk_size=1500):
    """
    Chunked parallel execution.

    On Windows, joblib loky causes PicklingError because _run_task closes over
    SymPy globals (geom_sub, theta, t, …) which hit internal lru_cache wrappers.
    Pebble solves this by spawning fresh worker processes and importing the module
    cleanly — no serialization of SymPy objects needed.

    Priority: pebble (if installed) → loky → sequential.
    Install pebble:  pip install pebble
    """
    out = []
    n_total = len(task_list)
    if n_total == 0:
        return out

    # ── Try pebble first (OS-level kills, no PicklingError on Windows) ────────
    try:
        from pebble import ProcessPool
        from concurrent.futures import TimeoutError as _PebbleTimeout
        import os as _os

        _workers = max(1, (_os.cpu_count() or 4) - 1) if n_jobs < 0 else n_jobs
        _PEBBLE_TIMEOUT = 20.0   # seconds per task
        _MAX_TASKS = 500         # recycle worker after this many tasks (memory reset)

        print(f"[pebble] {n_total} tasks  workers={_workers}  timeout={_PEBBLE_TIMEOUT}s")
        t0_run = time.time()

        with ProcessPool(max_workers=_workers, max_tasks=_MAX_TASKS) as pool:
            futures = [(task, pool.schedule(_run_task_pebble, args=(task,),
                                             timeout=_PEBBLE_TIMEOUT))
                       for task in task_list]

            for done, (task, fut) in enumerate(futures, 1):
                key = task[0]
                try:
                    result = fut.result()
                    out.append(result)
                except _PebbleTimeout:
                    out.append((key, (None,None,None,None,None,1,0,"timeout"), []))
                except Exception as exc:
                    out.append((key, (None,None,None,None,None,1,0,f"exc:{exc!s:.60}"), []))

                if done % 500 == 0 or done == n_total:
                    ok = sum(1 for _,c,_ in out if c[7]=="ok")
                    to = sum(1 for _,c,_ in out if "timeout" in str(c[7]))
                    print(f"  {done}/{n_total}  ok={ok}  timeouts={to}"
                          f"  {(time.time()-t0_run)/60:.1f}min", flush=True)

        return out

    except ImportError:
        print("pebble not installed — falling back to loky.")
        print("Install with:  pip install pebble  (strongly recommended on Windows)")

    # ── Fallback: loky/multiprocessing ────────────────────────────────────────
    n_chunks = (n_total + chunk_size - 1) // chunk_size
    for chunk_id, start in enumerate(range(0, n_total, chunk_size), 1):
        chunk = task_list[start:start + chunk_size]
        print(f"[{backend_name}] chunk {chunk_id}/{n_chunks}  size={len(chunk)}")
        chunk_out = Parallel(n_jobs=n_jobs, backend=backend_name, verbose=0)(
            delayed(_run_task)(task, algebra_cache) for task in chunk
        )
        out.extend(chunk_out)
    return out


def _precomputed_task_cache(df):
    """Reuse previously computed symbolic outputs if they already exist in df."""
    required = {"x(t)", "y(t)", "weierstrass_n"}
    if not required.issubset(set(df.columns)):
        return {}

    cache = {}
    for _, row in df.iterrows():
        x_val, y_val = row.get("x(t)"), row.get("y(t)")
        n_val = row.get("weierstrass_n")
        if pd.isna(x_val) or pd.isna(y_val) or pd.isna(n_val):
            continue

        key = _make_task_key(row.get("bary_list", []), row.get("funcs", {}))
        cache[key] = (
            x_val,
            y_val,
            n_val,
            row.get("deepest_factor", n_val),
            row.get("deepest_angle_den", (2 * int(n_val)) if pd.notna(n_val) else None),
            row.get("bary_checked", 0),
            row.get("bary_valid", 0),
            row.get("eval_status", "precomputed"),
        )
    return cache


def _load_disk_cache(path):
    if not path.exists():
        return {'task_cache': {}, 'algebra_cache': {}, 'candidate_cache': {}}
    try:
        with path.open('rb') as f:
            data = pickle.load(f)
        # Backward compatibility: old format was plain task-cache dict
        if isinstance(data, dict) and 'task_cache' in data:
            return {
                'task_cache': data.get('task_cache', {}),
                'algebra_cache': data.get('algebra_cache', {}),
                'candidate_cache': data.get('candidate_cache', {}),
            }
        if isinstance(data, dict):
            return {'task_cache': data, 'algebra_cache': {}, 'candidate_cache': {}}
    except Exception:
        pass
    return {'task_cache': {}, 'algebra_cache': {}, 'candidate_cache': {}}


def _save_disk_cache(path, payload):
    try:
        with path.open('wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass




# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SolveResult:
    x_t:                    Optional[str]  = None
    y_t:                    Optional[str]  = None
    weierstrass_n:          Optional[int]  = None
    chosen_weierstrass_angle: Optional[str] = None
    eval_status:            str            = "not_computed"
    seconds:                float          = 0.0


def solve_expression(expr_str: str) -> SolveResult:
    """
    Convert a cleaned colon-separated barycentric string to Cartesian x(t), y(t).

    Parameters
    ----------
    expr_str : str
        A cleaned barycentric triple, e.g. ``"a : b : c"`` or ``"SA : SB : SC"``.

    Returns
    -------
    SolveResult
        Contains x_t, y_t as strings, weierstrass_n, chosen_weierstrass_angle,
        and eval_status in {"ok", "no_valid_route", "no_bary", …}.
    """
    import time as _time
    t0 = _time.perf_counter()
    try:
        chosen, _ = _compute_one(
            bary_list=[expr_str],
            funcs_dict={},
            algebra_cache={},
        )
        x_t, y_t, n_val, deepest_factor, deep_den, checked, valid, status = chosen
        angle_str = f"theta/{int(deep_den)}" if deep_den else None
        return SolveResult(
            x_t=str(x_t) if x_t is not None else None,
            y_t=str(y_t) if y_t is not None else None,
            weierstrass_n=int(n_val) if n_val is not None else None,
            chosen_weierstrass_angle=angle_str,
            eval_status=status,
            seconds=round(_time.perf_counter() - t0, 6),
        )
    except Exception as exc:
        return SolveResult(eval_status=f"error:{exc!s:.120}", seconds=round(_time.perf_counter() - t0, 6))
    finally:
        clear_cache()


def bary_complexity(expr_str: str) -> int:
    """Heuristic complexity for ordering tasks (lower = simpler)."""
    s = expr_str.replace(' ', '')
    trig_penalty = 40 * sum(s.count(w) for w in ('sin','cos','tan','cot','sec','csc'))
    return trig_penalty + len(s) + s.count('/') * 5 + s.count('**') * 3


def _pebble_entry(expr: str) -> dict:
    """Top-level pebble worker entry point (must be module-level for pickling)."""
    r = solve_expression(expr)
    return {
        "x_t":                    r.x_t,
        "y_t":                    r.y_t,
        "weierstrass_n":          r.weierstrass_n,
        "chosen_weierstrass_angle": r.chosen_weierstrass_angle,
        "eval_status":            r.eval_status,
        "seconds":                r.seconds,
    }
