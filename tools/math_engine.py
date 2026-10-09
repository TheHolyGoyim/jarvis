"""
tools/math_engine.py — Jarvis math + quant pattern engine.

Two halves, both fully local (sympy/numpy/scipy, no API, no LLM needed):

  compute(expression)          — arithmetic, percentages, algebra, equation
                                 systems, calculus (derivatives / integrals /
                                 limits / series), matrices, ODEs, primes/
                                 gcd/lcm, quick stats on a list of numbers.
                                 Auto-detects intent from natural phrasing.
  pattern_scan(symbol, days)   — statistical pattern hunt on REAL price bars:
                                 trend/Hurst regime, return autocorrelation,
                                 FFT cycle candidates, vol clustering, weekday
                                 bias, fat tails — plus a deterministic
                                 trading synthesis (momentum vs mean-reversion
                                 vs "no edge in price history alone").
  pair_correlation(a, b, days) — correlation / beta / lead-lag between two
                                 tickers.

The local LLM is bad at arithmetic — the system prompt tells it to route ALL
math here rather than computing in its head.
"""

import re
import math
from datetime import datetime

_RULE = "━" * 30

# Reject anything that could smuggle code through the sympy parser.
_BLOCKED = re.compile(
    r'__|\bimport\b|\bopen\b|\bexec\b|\beval\b|\blambda\b|\bos\b|\bsys\b'
    r'|\bgetattr\b|\bsetattr\b|\bglobals\b|\blocals\b')


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _num(x) -> str:
    """Trim a numeric value to a clean human string."""
    try:
        f = float(x)
    except Exception:
        return str(x)
    if f == int(f) and abs(f) < 1e15:
        return f"{int(f):,}"
    s = f"{f:,.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _report(kind: str, echo: str, lines: list) -> str:
    echo = echo if len(echo) <= 80 else echo[:77] + "..."
    return "\n".join([f"🧮 MATH — {kind}", _RULE, f"Input: {echo}", ""] + lines)


# ══════════════════════════════════════════════════════════════════════════════
# SYMBOLIC / NUMERIC SOLVER
# ══════════════════════════════════════════════════════════════════════════════

def _sp():
    import sympy
    return sympy


def _parse(txt: str):
    """Parse a math expression leniently: ^ → **, implicit multiplication."""
    from sympy.parsing.sympy_parser import (
        parse_expr, standard_transformations,
        implicit_multiplication_application, convert_xor)
    txt = txt.strip().strip(".").strip()
    return parse_expr(
        txt,
        transformations=standard_transformations +
        (implicit_multiplication_application, convert_xor))


def _pick_var(expr, name: str = ""):
    """Choose the working variable: named one, else x, else first free symbol."""
    sp = _sp()
    if name:
        return sp.Symbol(name)
    free = sorted(expr.free_symbols, key=lambda s: s.name)
    for s in free:
        if s.name == "x":
            return s
    return free[0] if free else sp.Symbol("x")


def _exact_and_decimal(res) -> list:
    sp = _sp()
    lines = [f"Exact:   {sp.nsimplify(res) if not res.free_symbols else res}"]
    try:
        if not res.free_symbols:
            dec = sp.N(res, 12)
            if str(dec) != str(res):
                lines.append(f"Decimal: {_num(dec)}")
    except Exception:
        pass
    return lines


def _clean_query(q: str) -> str:
    s = q.lower().strip().rstrip("?").strip()
    s = re.sub(r'^(?:hey\s+)?jarvis[,!\s]+', '', s)
    s = re.sub(r'^(?:please\s+)?(?:can\s+you\s+)?'
               r'(?:calculate|calc|compute|evaluate|work\s+out'
               r'|what\s+is|what[\'’]?s|whats|how\s+much\s+is|tell\s+me)\s+',
               '', s)
    s = re.sub(r'\s+please$', '', s)
    s = (s.replace('×', '*').replace('÷', '/').replace('−', '-')
          .replace('π', 'pi').replace('√', 'sqrt').replace('∞', 'oo')
          .replace('→', '->').replace('’', "'"))
    s = re.sub(r'(\d),(?=\d{3}\b)', r'\1', s)   # 1,000,000 → 1000000
    return s.strip()


def _solve_equations(s: str) -> str:
    sp = _sp()
    body = re.sub(r'^solve\s+(?:the\s+)?(?:equations?\s+)?(?:for\s+[a-z]\s*[: ]\s*)?', '', s)
    m_for = re.search(r'\bfor\s+([a-z])\b\s*$', body)
    if m_for:
        body = body[:m_for.start()].strip()
    parts = [p.strip() for p in re.split(r'\band\b|;|,', body) if "=" in p]
    if not parts:
        parts = [body]
    eqs = []
    for p in parts:
        if "=" in p and "<" not in p and ">" not in p:
            l, r = p.split("=", 1)
            eqs.append(sp.Eq(_parse(l), _parse(r)))
        else:
            # Inequality or bare expression (= 0 implied)
            eqs.append(_parse(p.replace("=", "==")) if ("<" in p or ">" in p)
                       else sp.Eq(_parse(p), 0))
    syms = set()
    for e in eqs:
        syms |= e.free_symbols
    if m_for:
        target = [sp.Symbol(m_for.group(1))]
    else:
        target = sorted(syms, key=lambda x: x.name)
    if not target:
        return _report("solve", s, ["No variable found — nothing to solve for."])
    sols = sp.solve(eqs if len(eqs) > 1 else eqs[0], target if len(target) > 1 else target[0])
    lines = []
    if isinstance(sols, dict):
        sols = [sols]
    if isinstance(sols, (list, tuple)) and sols:
        for sol in sols:
            if isinstance(sol, dict):
                lines.append("  " + ",  ".join(f"{k} = {v}" for k, v in sol.items()))
            elif isinstance(sol, (list, tuple)):
                lines.append("  " + ",  ".join(
                    f"{t} = {v}" for t, v in zip(target, sol)))
            else:
                extra = ""
                try:
                    if not sol.free_symbols and sp.im(sp.N(sol)) == 0:
                        d = _num(sp.N(sol, 10))
                        if d != str(sol):
                            extra = f"   (≈ {d})"
                except Exception:
                    pass
                lines.append(f"  {target[0]} = {sol}{extra}")
        lines.insert(0, f"Solutions ({len(sols)}):")
    elif sols not in (None, [], ()):
        lines = [f"Solution set: {sols}"]
    else:
        lines = ["No solution found (or empty solution set)."]
    return _report("solve", s, lines)


def _do_ode(s: str) -> str:
    sp = _sp()
    x = sp.Symbol("x")
    y = sp.Function("y")
    t = re.sub(r'^solve\s+', '', s)
    t = t.replace("dy/dx", "y'")
    t = t.replace("y''", "Derivative(y(x),x,2)").replace("y'", "Derivative(y(x),x)")
    t = re.sub(r'\by\b(?!\()', 'y(x)', t)
    t = t.replace("^", "**")
    # Plain sympify here — the implicit-multiplication transformations in
    # _parse mangle Derivative(y(x),x,2) internals.
    loc = {"y": y, "x": x, "Derivative": sp.Derivative}
    if "=" in t:
        l, r = t.split("=", 1)
        eq = sp.Eq(sp.sympify(l, locals=loc), sp.sympify(r, locals=loc))
    else:
        eq = sp.Eq(sp.sympify(t, locals=loc), 0)
    sol = sp.dsolve(eq, y(x))
    return _report("differential equation", s,
                   [f"  {sol}", "", "C1, C2 = free constants (set by initial conditions)."])


def _do_limit(s: str) -> str:
    sp = _sp()
    m = re.search(r'(?:limit\s+(?:of\s+)?)?(.+?)\s+as\s+([a-z])\s*'
                  r'(?:->|approaches|goes\s+to|tends\s+to)\s*(\S+)', s)
    if not m:
        return _report("limit", s,
                       ["Couldn't read the limit — try: limit of sin(x)/x as x -> 0"])
    body, var, to = m.group(1), m.group(2), m.group(3)
    body = re.sub(r'^limit\s+(?:of\s+)?', '', body)
    side = "+"
    if to.endswith("+") or to.endswith("-"):
        side, to = to[-1], to[:-1]
    to_expr = sp.oo if to in ("infinity", "inf", "oo") else \
        (-sp.oo if to in ("-infinity", "-inf", "-oo") else _parse(to))
    res = sp.limit(_parse(body), sp.Symbol(var), to_expr, side)
    return _report("limit", s, [f"  lim {var}→{to}{side if to == '0' else ''}  =  {res}"]
                   + ([f"  ≈ {_num(sp.N(res, 10))}"] if not res.free_symbols and res.is_finite else []))


def _do_sum(s: str) -> str:
    sp = _sp()
    m = re.search(r'^(?:the\s+)?(?:sum|series)\s+(?:of\s+)?(.+?)\s+'
                  r'(?:from|for)\s+([a-z])\s*=?\s*(\S+)\s+to\s+(\S+)', s)
    if not m:
        return _report("sum", s,
                       ["Couldn't read it — try: sum of 1/n^2 from n=1 to infinity"])
    body, var, a, b = m.groups()
    lo = sp.oo if a in ("infinity", "inf", "oo") else _parse(a)
    hi = sp.oo if b in ("infinity", "inf", "oo") else _parse(b)
    res = sp.summation(_parse(body), (sp.Symbol(var), lo, hi))
    return _report("sum/series", s, ["  Σ = " + str(res)] +
                   ([f"  ≈ {_num(sp.N(res, 12))}"] if not res.free_symbols and res.is_finite else []))


def _do_derivative(s: str) -> str:
    sp = _sp()
    order = 1
    mo = re.search(r'\b(second|2nd|third|3rd|(\d+)(?:st|nd|rd|th))\s+derivative', s)
    if mo:
        order = {"second": 2, "2nd": 2, "third": 3, "3rd": 3}.get(
            mo.group(1), int(mo.group(2) or 1))
    var_name = ""
    mv = re.search(r'\bwith\s+respect\s+to\s+([a-z])\b|\bd/d([a-z])\b', s)
    if mv:
        var_name = mv.group(1) or mv.group(2)
    body = re.sub(r'^(?:the\s+)?(?:\w+\s+)?(?:derivative|differentiate|diff)\s*(?:of\s+)?', '', s)
    body = re.sub(r'\bwith\s+respect\s+to\s+[a-z]\b|\bd/d[a-z]\b', '', body).strip()
    expr = _parse(body)
    var = _pick_var(expr, var_name)
    res = sp.diff(expr, var, order)
    try:
        shown = sp.expand(res)   # conventional textbook form
    except Exception:
        shown = sp.simplify(res)
    tag = "d" if order == 1 else f"d^{order}"
    return _report("derivative", s,
                   [f"  {tag}/d{var}{'' if order == 1 else f'^{order}'} [{expr}]",
                    f"  = {shown}"])


def _do_integral(s: str) -> str:
    sp = _sp()
    var_name = ""
    mv = re.search(r'\bwith\s+respect\s+to\s+([a-z])\b', s)
    if mv:
        var_name = mv.group(1)
    mb = re.search(r'\b(?:from|between)\s+(\S+)\s+(?:to|and)\s+(\S+)', s)
    body = re.sub(r'^(?:the\s+)?(?:integrate|integral|antiderivative)\s*(?:of\s+)?', '', s)
    body = re.sub(r'\b(?:from|between)\s+\S+\s+(?:to|and)\s+\S+', '', body)
    body = re.sub(r'\bwith\s+respect\s+to\s+[a-z]\b', '', body)
    body = re.sub(r'\bd([a-z])\s*$', '', body).strip()
    expr = _parse(body)
    var = _pick_var(expr, var_name)
    if mb:
        bound = lambda t: sp.oo if t in ("infinity", "inf", "oo") else \
            (-sp.oo if t in ("-infinity", "-inf", "-oo") else _parse(t))
        a, b = bound(mb.group(1)), bound(mb.group(2))
        res = sp.integrate(expr, (var, a, b))
        lines = [f"  ∫[{a} → {b}] {expr} d{var}", f"  = {sp.simplify(res)}"]
        try:
            if not res.free_symbols and res.is_finite:
                lines.append(f"  ≈ {_num(sp.N(res, 12))}")
        except Exception:
            pass
        return _report("definite integral", s, lines)
    res = sp.integrate(expr, var)
    return _report("integral", s, [f"  ∫ {expr} d{var}", f"  = {res} + C"])


def _do_matrix(s: str) -> str:
    sp = _sp()
    blocks = []
    i = 0
    while True:
        start = s.find("[[", i)
        if start < 0:
            break
        depth = 0
        for j in range(start, len(s)):
            if s[j] == "[":
                depth += 1
            elif s[j] == "]":
                depth -= 1
                if depth == 0:
                    blocks.append(s[start:j + 1])
                    i = j + 1
                    break
        else:
            break
    if not blocks:
        return _report("matrix", s, ["Couldn't find a [[...]] matrix literal."])
    mats = [sp.Matrix(sp.sympify(b)) for b in blocks]
    A = mats[0]
    if len(mats) == 2 and re.search(r'\]\s*\*\s*\[|multipl|times|product', s):
        P = mats[0] * mats[1]
        return _report("matrix product", s, [f"  {P.tolist()}"])
    lines = []
    if re.search(r'\bdet(?:erminant)?\b', s):
        lines.append(f"  det = {A.det()}")
    elif re.search(r'\binv(?:erse|ert)?\b', s):
        lines.append(f"  inverse = {A.inv().tolist()}")
    elif re.search(r'\beigen', s):
        for val, mult, _v in A.eigenvects():
            lines.append(f"  λ = {val}  (×{mult})")
    elif re.search(r'\brank\b', s):
        lines.append(f"  rank = {A.rank()}")
    elif re.search(r'\brref\b|\brow\s+reduce', s):
        lines.append(f"  rref = {A.rref()[0].tolist()}")
    elif re.search(r'\btranspose\b', s):
        lines.append(f"  transpose = {A.T.tolist()}")
    else:
        lines = [f"  matrix {A.shape[0]}×{A.shape[1]}: {A.tolist()}"]
        if A.is_square:
            lines.append(f"  det = {A.det()}   rank = {A.rank()}")
    return _report("matrix", s, lines)


def _do_stats(nums: list) -> str:
    import numpy as np
    a = np.array(nums, dtype=float)
    lines = [
        f"  n:      {len(a)}",
        f"  sum:    {_num(a.sum())}",
        f"  mean:   {_num(a.mean())}",
        f"  median: {_num(float(np.median(a)))}",
        f"  stdev:  {_num(float(a.std(ddof=1))) if len(a) > 1 else 'n/a'}",
        f"  min:    {_num(a.min())}   max: {_num(a.max())}",
    ]
    return _report("stats", ", ".join(_num(x) for x in nums[:12]) +
                   ("..." if len(nums) > 12 else ""), lines)


def compute(expression: str = "", **_) -> str:
    """Universal math entry point — detects intent and dispatches."""
    q = str(expression or "").strip()
    if not q:
        return ("Give me something to compute — e.g. '15% of 240', "
                "'solve x^2-5x+6=0', 'integrate x^2 sin(x)', "
                "'limit of sin(x)/x as x->0'.")
    if _BLOCKED.search(q.lower()):
        return "That expression contains disallowed tokens — plain math only."
    s = _clean_query(q)
    try:
        sp = _sp()
    except Exception as e:
        return f"Math engine unavailable (sympy failed to load: {e}). Run: pip install sympy"

    try:
        # ── Percent phrasings ────────────────────────────────────────
        m = re.match(r'^([\d.]+)\s*%\s*of\s+([\d.]+)$', s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            return _report("percent", s, [f"  {_num(a)}% of {_num(b)} = {_num(a / 100 * b)}"])
        m = re.match(r'^([\d.]+)\s+(?:increased|up)\s+by\s+([\d.]+)\s*%$', s)
        if m:
            b, a = float(m.group(1)), float(m.group(2))
            return _report("percent", s, [f"  {_num(b)} + {_num(a)}% = {_num(b * (1 + a / 100))}"])
        m = re.match(r'^([\d.]+)\s+(?:decreased|down|reduced)\s+by\s+([\d.]+)\s*%$', s)
        if m:
            b, a = float(m.group(1)), float(m.group(2))
            return _report("percent", s, [f"  {_num(b)} − {_num(a)}% = {_num(b * (1 - a / 100))}"])
        m = re.match(r'^([\d.]+)\s+is\s+what\s+(?:percent|%)\s+of\s+([\d.]+)$', s) or \
            re.match(r'^what\s+(?:percent|%)\s+of\s+([\d.]+)\s+is\s+([\d.]+)$', s)
        if m:
            g = [float(m.group(1)), float(m.group(2))]
            part, whole = (g[0], g[1]) if "is what" in s else (g[1], g[0])
            return _report("percent", s,
                           [f"  {_num(part)} / {_num(whole)} = {_num(part / whole * 100)}%"])
        m = re.match(r'^(?:%\s*change|percent\s+change)\s+(?:from\s+)?([\d.-]+)\s+to\s+([\d.-]+)$', s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            return _report("percent", s,
                           [f"  {_num(a)} → {_num(b)} = {_num((b - a) / abs(a) * 100)}%"])

        # ── Stats on a plain list of numbers ─────────────────────────
        body = re.sub(r'^(?:stats|statistics|describe)\s+(?:of|on|for)?\s*', '', s)
        toks = re.split(r'[,\s]+', body.strip())
        if len(toks) >= 3 and all(re.fullmatch(r'-?[\d.]+', t) for t in toks if t):
            return _do_stats([float(t) for t in toks if t])

        # ── Number theory ────────────────────────────────────────────
        m = re.match(r'^is\s+(\d+)\s+(?:a\s+)?prime', s)
        if m:
            n = int(m.group(1))
            return _report("prime check", s,
                           [f"  {n:,} is {'PRIME' if sp.isprime(n) else 'NOT prime'}"])
        m = re.match(r'^(?:prime\s+)?factor(?:s|ize|ise)?\s+(?:of\s+)?(\d+)$', s)
        if m:
            f = sp.factorint(int(m.group(1)))
            return _report("prime factorization", s,
                           ["  " + " · ".join(f"{p}^{e}" if e > 1 else f"{p}"
                                              for p, e in sorted(f.items()))])
        m = re.match(r'^(gcd|lcm)\s+(?:of\s+)?([\d,\s]+)$', s)
        if m:
            ns = [int(t) for t in re.split(r'[,\s]+', m.group(2)) if t]
            fn = math.gcd if m.group(1) == "gcd" else math.lcm
            r = ns[0]
            for n in ns[1:]:
                r = fn(r, n)
            return _report(m.group(1), s, [f"  {m.group(1)}({', '.join(map(str, ns))}) = {r:,}"])

        # ── Structured branches ──────────────────────────────────────
        if "[[" in s:
            return _do_matrix(s)
        if "y'" in s or "dy/dx" in s:
            return _do_ode(s)
        if re.search(r'\bas\s+[a-z]\s*(?:->|approaches|goes\s+to|tends\s+to)', s) or \
                re.match(r'^limit\b', s):
            return _do_limit(s)
        if re.match(r'^(?:the\s+)?(?:sum|series)\b', s) and re.search(r'\b(?:from|for)\b', s):
            return _do_sum(s)
        if re.search(r'^(?:the\s+)?(?:\w+\s+)?(?:derivative|differentiate)\b|\bd/d[a-z]\b', s):
            return _do_derivative(s)
        if re.match(r'^(?:the\s+)?(?:integrate|integral|antiderivative)\b', s):
            return _do_integral(s)
        m = re.match(r'^(simplify|expand|factor)\s+(.+)$', s)
        if m and not re.fullmatch(r'\d+', m.group(2).strip()):
            expr = _parse(m.group(2))
            res = getattr(sp, m.group(1))(expr)
            return _report(m.group(1), s, [f"  {res}"])
        if "=" in s or re.match(r'^solve\b', s):
            return _solve_equations(s)

        # ── Default: evaluate ────────────────────────────────────────
        expr = _parse(s)
        if expr.free_symbols:
            res = sp.simplify(expr)
            return _report("simplify", s, [f"  {res}"])
        return _report("evaluate", s, _exact_and_decimal(expr))

    except Exception as e:
        return (f"🧮 Couldn't compute that ({type(e).__name__}: {str(e)[:80]}).\n"
                "Try plainer phrasing — e.g. 'solve x^2=4', 'integrate x^2 from 0 to 1', "
                "'derivative of sin(x)*x', '15% of 240'.")


# ══════════════════════════════════════════════════════════════════════════════
# QUANT PATTERN LAB — statistical pattern hunt on real price history
# ══════════════════════════════════════════════════════════════════════════════

def _returns(bars):
    import numpy as np
    closes = np.array([b["close"] for b in bars], dtype=float)
    logp = np.log(closes)
    return closes, logp, np.diff(logp)


def _autocorr(x, k):
    import numpy as np
    x = x - x.mean()
    d = float(np.sum(x * x))
    return float(np.sum(x[k:] * x[:-k]) / d) if d else 0.0


def _hurst(logp):
    """Variance-of-lags Hurst estimate. >0.55 trending, <0.45 mean-reverting."""
    import numpy as np
    n = len(logp)
    lags = range(2, min(21, n // 4))
    tau = [float(np.std(logp[l:] - logp[:-l])) for l in lags]
    if not tau or any(t <= 0 for t in tau):
        return 0.5
    return float(np.polyfit(np.log(list(lags)), np.log(tau), 1)[0])


def pattern_scan(symbol: str = "", days: int = 180, **_) -> str:
    """Hunt for statistically real (and honestly caveated) patterns in a ticker."""
    import numpy as np
    from scipy import stats as sst
    symbol = str(symbol).upper().strip()
    if not symbol:
        return "Which ticker? e.g. 'find patterns in SOFI'"
    days = max(60, min(int(days or 180), 730))
    import tools.market as MKT
    bars = MKT._fetch_history(symbol, days)
    if len(bars) < 60:
        return (f"Not enough history for {symbol} ({len(bars)} bars) — "
                "need ≥60 daily bars for the pattern tests to mean anything.")
    closes, logp, rets = _returns(bars)
    n = len(rets)
    t = np.arange(len(logp))
    sig = 1.96 / math.sqrt(n)          # 95% significance band for autocorr

    # Trend + Hurst
    slope, intercept = np.polyfit(t, logp, 1)
    fitted = np.polyval((slope, intercept), t)
    ss_res = float(np.sum((logp - fitted) ** 2))
    ss_tot = float(np.sum((logp - logp.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    drift = (math.exp(slope * 252) - 1) * 100
    H = _hurst(logp)
    regime = ("trending" if H > 0.55 else
              "mean-reverting" if H < 0.45 else "≈ random walk")

    # Serial correlation
    acs = [_autocorr(rets, k) for k in range(1, 11)]
    sig_lags = [k + 1 for k, a in enumerate(acs) if abs(a) > sig]
    # OU half-life of mean reversion
    b = float(np.polyfit(logp[:-1], np.diff(logp), 1)[0])
    half_life = (-math.log(2) / b) if b < 0 else None

    # FFT cycle candidates on detrended log price
    detr = logp - fitted
    power = np.abs(np.fft.rfft(detr - detr.mean())) ** 2
    freqs = np.fft.rfftfreq(len(detr), 1.0)
    cyc = []
    if len(power) > 2:
        periods = 1.0 / freqs[1:]
        pw = power[1:]
        mask = (periods >= 5) & (periods <= len(detr) / 2)
        if mask.any():
            tot = float(pw[mask].sum())
            order = np.argsort(pw[mask])[::-1][:2]
            pd_m, pw_m = periods[mask], pw[mask]
            cyc = [(float(pd_m[i]), float(pw_m[i]) / tot * 100) for i in order]

    # Volatility
    ann_vol = float(rets.std(ddof=1)) * math.sqrt(252) * 100
    vol_cluster = _autocorr(np.abs(rets), 1)
    roll = np.array([rets[i - 20:i].std(ddof=1) for i in range(20, n + 1)])
    vol_pctile = float((roll <= roll[-1]).mean() * 100) if len(roll) > 5 else 50.0

    # Weekday bias
    wd_rets = {}
    for i in range(1, len(bars)):
        try:
            wd = datetime.strptime(bars[i]["date"], "%Y-%m-%d").weekday()
            wd_rets.setdefault(wd, []).append(rets[i - 1])
        except Exception:
            pass
    wd_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    wd_mean = {wd_names[k]: float(np.mean(v)) * 100
               for k, v in wd_rets.items() if k < 5 and len(v) >= 5}

    # Distribution
    skew = float(sst.skew(rets))
    kurt = float(sst.kurtosis(rets))     # excess
    best_i, worst_i = int(np.argmax(rets)), int(np.argmin(rets))

    out = [f"🔬 PATTERN LAB — {symbol} ({len(bars)} bars)", _RULE]
    out += ["📈 TREND",
            f"  drift {drift:+.0f}%/yr | trend fit R² {r2:.2f}",
            f"  Hurst {H:.2f} → {regime}"]
    out += ["🔁 SERIAL CORRELATION (daily)",
            f"  lag-1 {acs[0]:+.3f} (95% band ±{sig:.3f})"
            + (" → momentum" if acs[0] > sig else
               " → reversal" if acs[0] < -sig else " → noise")]
    if sig_lags:
        out.append(f"  significant lags: {', '.join(map(str, sig_lags))}")
    if half_life and 1 <= half_life <= n:
        out.append(f"  mean-reversion half-life ≈ {half_life:.0f}d")
    if cyc:
        out += ["🌊 CYCLE CANDIDATES (FFT — suggestive, not gospel)"]
        out += [f"  ~{p:.0f} trading days ({sh:.0f}% of detrended var)"
                for p, sh in cyc]
    out += ["📊 VOLATILITY",
            f"  annualized {ann_vol:.0f}% | clustering {vol_cluster:+.2f}",
            f"  20d vol now: {vol_pctile:.0f}th percentile of its history"]
    if wd_mean:
        bd = max(wd_mean, key=wd_mean.get)
        wd = min(wd_mean, key=wd_mean.get)
        out += ["📅 WEEKDAY BIAS (small sample — weak evidence)",
                f"  best {bd} {wd_mean[bd]:+.2f}%/d | worst {wd} {wd_mean[wd]:+.2f}%/d"]
    out += ["🎲 DISTRIBUTION",
            f"  skew {skew:+.2f} | excess kurtosis {kurt:+.1f}"
            + (" (FAT TAILS)" if kurt > 3 else ""),
            f"  best day {rets[best_i] * 100:+.1f}% ({bars[best_i + 1]['date']})",
            f"  worst day {rets[worst_i] * 100:+.1f}% ({bars[worst_i + 1]['date']})"]

    # Deterministic trading synthesis — rules, not vibes
    syn = []
    if H > 0.55 and acs[0] > 0:
        syn.append("Momentum regime: trend entries + trailing stops favored; "
                   "let winners run.")
    elif H < 0.45 or acs[0] < -sig:
        syn.append("Mean-reversion regime: fade extremes, take profits quickly, "
                   "avoid chasing breakouts.")
    else:
        syn.append("No exploitable serial pattern at daily scale — any edge must "
                   "come from catalysts/flow/sentiment, not price history alone.")
    if kurt > 3:
        syn.append("Fat tails: size positions smaller than average vol suggests; "
                   "hard stops matter more than usual.")
    if vol_pctile >= 80:
        syn.append(f"Vol at {vol_pctile:.0f}th percentile: expect wider swings — "
                   "widen stops or cut size, not both.")
    elif vol_pctile <= 20:
        syn.append("Vol compressed: breakout potential building; cheap options "
                   "premium if a catalyst is queued.")
    if cyc and cyc[0][1] >= 20:
        syn.append(f"~{cyc[0][0]:.0f}d cycle carries {cyc[0][1]:.0f}% of variance — "
                   "worth timing entries against, but re-verify weekly.")
    out += ["🧠 SYNTHESIS"] + [f"  • {x}" for x in syn]

    try:
        import tools.charts as CHT
        path = CHT.bar_chart(f"{symbol} return autocorrelation (lags 1-10)",
                             [f"lag {k}" for k in range(1, 11)], acs,
                             xlabel=f"autocorrelation (95% band ±{sig:.3f})")
        if path:
            out.append(f"Chart saved: {path}")
    except Exception:
        pass
    return "\n".join(out)


def pair_correlation(symbol_a: str = "", symbol_b: str = "", days: int = 120, **_) -> str:
    """Correlation / beta / lead-lag between two tickers' daily returns."""
    import numpy as np
    a, b = str(symbol_a).upper().strip(), str(symbol_b).upper().strip()
    if not a or not b:
        return "Give me two tickers — e.g. 'correlate SOFI and HOOD'"
    days = max(45, min(int(days or 120), 730))
    import tools.market as MKT
    bars_a = {x["date"]: x["close"] for x in MKT._fetch_history(a, days)}
    bars_b = {x["date"]: x["close"] for x in MKT._fetch_history(b, days)}
    common = sorted(set(bars_a) & set(bars_b))
    if len(common) < 30:
        return f"Not enough overlapping history for {a}/{b} ({len(common)} shared days)."
    pa = np.log([bars_a[d] for d in common])
    pb = np.log([bars_b[d] for d in common])
    ra, rb = np.diff(pa), np.diff(pb)
    corr = float(np.corrcoef(ra, rb)[0, 1])
    beta = float(np.cov(ra, rb)[0, 1] / np.var(rb, ddof=1))
    a_leads = float(np.corrcoef(ra[:-1], rb[1:])[0, 1])   # a today → b tomorrow
    b_leads = float(np.corrcoef(rb[:-1], ra[1:])[0, 1])   # b today → a tomorrow
    sig = 1.96 / math.sqrt(len(ra))
    out = [f"🔗 PAIR — {a} vs {b} ({len(common)} shared days)", _RULE,
           f"  correlation: {corr:+.2f}  (R² {corr * corr:.2f})",
           f"  beta ({a} per 1% {b} move): {beta:+.2f}",
           f"  lead-lag: {a}→{b} {a_leads:+.2f} | {b}→{a} {b_leads:+.2f} "
           f"(band ±{sig:.2f})"]
    syn = []
    if abs(corr) >= 0.7:
        syn.append(f"Tightly coupled — don't hold both as if they diversify; "
                   f"treat as one {'{:+.0f}%'.format(corr * 100)} correlated bet.")
    elif abs(corr) <= 0.2:
        syn.append("Effectively independent — genuine diversification pair.")
    if max(abs(a_leads), abs(b_leads)) > sig:
        lead = a if abs(a_leads) > abs(b_leads) else b
        lagr = b if lead == a else a
        syn.append(f"{lead} tends to lead {lagr} by ~1 day — watch {lead} for "
                   f"early signal on {lagr}.")
    else:
        syn.append("No significant lead-lag — neither predicts the other day-ahead.")
    return "\n".join(out + ["🧠 SYNTHESIS"] + [f"  • {x}" for x in syn])
