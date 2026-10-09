"""
tools/risk_params.py — single source of truth for every trading risk parameter.

The Markets dashboard writes here (POST /risk-params), and the ENTIRE trading
pipeline reads from here before acting: trading._guard() on every order,
conviction.auto_hunt() before every autonomous entry, trade_monitor before
scale-ins/re-hunts, opportunity_scan._auto_fill(), auto_trade_daily.py.

v2 — capital limits are PERCENTAGES of live Alpaca buying power / portfolio
value (tools/account_sync.py), not hardcoded dollars. The old $100
TRADING_BUDGET cap and $-denominated max_position_size are retired.

Position sizing formula (Bug-2 spec):
    position_size = available_capital × allocation_pct
    allocation_pct from conviction score (engine 0-100 / UI 1-10):
      50-64 (5-6)  → ~2-3%    base 2.5%
      65-84 (7-8)  → ~4-6%    base 5.0%
      85+   (9-10) → ~7-10%   base 8.5%
    scaled by risk-profile multiplier, capped at max_position_pct.

Persisted via tools/store.py (key 'risk_params') so values survive restarts
and are shared across the server process and the Task Scheduler process.
"""

from datetime import datetime
from tools.store import get, put

_KEY = "risk_params"

DEFAULTS = {
    "risk_profile":        "moderate",
    "max_position_pct":    6.0,      # % of buying power per position (cap)
    "max_daily_loss_pct":  2.0,      # % of portfolio value day loss → pause
    "min_cash_reserve_pct": 10,      # % of buying power kept liquid — the ONLY
                                     # position-count constraint is capital
    "min_conviction":      6,        # 1-10 UI scale → engine needs score >= x*10
    "options_conviction_threshold": 55,  # 0-100 engine scale — options need a
                                     # higher, independently configurable bar
                                     # than stocks (theta decay risk)
    "stop_loss_pct":       7.5,
    "take_profit_pct":     22.0,
    "trading_hours_start": "09:30",  # ET
    "trading_hours_end":   "15:30",
    "live_trading":        False,
    "autonomous_enabled":  True,
    "blocked_tickers":     [],
    "allowed_sectors":     ["Technology", "Healthcare", "Energy", "Financials",
                            "Consumer", "Industrials", "Materials", "Utilities",
                            "Real Estate", "Communication"],
}

# Five profiles. goal_engine.py maps required daily return onto these;
# automatic escalation NEVER goes above "aggressive" (user rule) — high_risk
# and speculative require an explicit user instruction.
PRESETS = {
    "conservative": {"max_position_pct": 3.0,  "max_daily_loss_pct": 1.0,
                     "min_cash_reserve_pct": 25, "min_conviction": 8,
                     "stop_loss_pct": 3.0,  "take_profit_pct": 8.0},
    "moderate":     {"max_position_pct": 6.0,  "max_daily_loss_pct": 2.0,
                     "min_cash_reserve_pct": 10, "min_conviction": 6,
                     "stop_loss_pct": 7.5,  "take_profit_pct": 22.0},
    "aggressive":   {"max_position_pct": 10.0, "max_daily_loss_pct": 3.0,
                     "min_cash_reserve_pct": 5,  "min_conviction": 5,
                     "stop_loss_pct": 12.0, "take_profit_pct": 40.0},
    "high_risk":    {"max_position_pct": 15.0, "max_daily_loss_pct": 4.0,
                     "min_cash_reserve_pct": 0,  "min_conviction": 4,
                     "stop_loss_pct": 15.0, "take_profit_pct": 60.0},
    "speculative":  {"max_position_pct": 20.0, "max_daily_loss_pct": 5.0,
                     "min_cash_reserve_pct": 0,  "min_conviction": 3,
                     "stop_loss_pct": 15.0, "take_profit_pct": 100.0},
}

# Highest profile automatic escalation may select (goal_engine honors this).
MAX_AUTO_PROFILE = "aggressive"
PROFILE_ORDER = ["conservative", "moderate", "aggressive", "high_risk", "speculative"]

# Profile multiplier applied to the conviction-tier base allocation.
_ALLOC_MULT = {"conservative": 0.6, "moderate": 1.0, "aggressive": 1.4,
               "high_risk": 1.8, "speculative": 2.2}

# Scanning behavior per profile (Feature 1 point 3) — consumed by
# conviction._budget_friendly_universe / opportunity_scan.
SCAN_PREFS = {
    "conservative": {"min_dollar_volume": 50_000_000, "include_squeeze": False},
    "moderate":     {"min_dollar_volume": 10_000_000, "include_squeeze": False},
    "aggressive":   {"min_dollar_volume":  5_000_000, "include_squeeze": True},
    "high_risk":    {"min_dollar_volume":  2_000_000, "include_squeeze": True},
    "speculative":  {"min_dollar_volume":  1_000_000, "include_squeeze": True},
}

_SECTORS = DEFAULTS["allowed_sectors"]
_HOURS = [f"{h:02d}:{m:02d}" for h in range(4, 21) for m in (0, 30)]

# key → (validator, error message)
_VALID = {
    "risk_profile":        (lambda v: v in PRESETS,
                            "must be conservative/moderate/aggressive/high_risk/speculative"),
    "max_position_pct":    (lambda v: isinstance(v, (int, float)) and 1 <= v <= 25 and round(v * 2) == v * 2,
                            "must be 1-25% in 0.5% steps"),
    "max_daily_loss_pct":  (lambda v: isinstance(v, (int, float)) and 0.5 <= v <= 10 and round(v * 2) == v * 2,
                            "must be 0.5-10% in 0.5% steps"),
    "min_cash_reserve_pct": (lambda v: isinstance(v, (int, float)) and 0 <= v <= 50 and v % 5 == 0,
                             "must be 0-50% in 5% steps"),
    "min_conviction":      (lambda v: isinstance(v, int) and 1 <= v <= 10, "must be 1-10"),
    "options_conviction_threshold": (lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
                                     "must be 0-100"),
    "stop_loss_pct":       (lambda v: isinstance(v, (int, float)) and 1 <= v <= 15 and round(v * 2) == v * 2,
                            "must be 1-15% in 0.5% steps"),
    "take_profit_pct":     (lambda v: isinstance(v, (int, float)) and 3 <= v <= 100 and v == int(v),
                            "must be 3-100% in 1% steps"),
    "trading_hours_start": (lambda v: v in _HOURS, "must be HH:MM in 30-min steps"),
    "trading_hours_end":   (lambda v: v in _HOURS, "must be HH:MM in 30-min steps"),
    "live_trading":        (lambda v: isinstance(v, bool), "must be true/false"),
    "autonomous_enabled":  (lambda v: isinstance(v, bool), "must be true/false"),
    "blocked_tickers":     (lambda v: isinstance(v, list) and len(v) <= 50 and
                            all(isinstance(t, str) and 1 <= len(t) <= 5 and t.isalpha() for t in v),
                            "must be a list of 1-5 letter tickers"),
    "allowed_sectors":     (lambda v: isinstance(v, list) and all(s in _SECTORS for s in v),
                            f"sectors must be from: {', '.join(_SECTORS)}"),
}


def get_params() -> dict:
    stored = get(_KEY) or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return out


def set_params(updates: dict) -> dict:
    """Validate + persist. Raises ValueError('key: message') on bad values.
    Selecting a risk_profile preset also applies that preset's values."""
    if not isinstance(updates, dict) or not updates:
        raise ValueError("no parameters given")
    clean = {}
    for k, v in updates.items():
        if k not in _VALID:
            raise ValueError(f"{k}: unknown parameter")
        # JSON numbers arrive as int/float; normalize int-like floats
        if isinstance(v, float) and v == int(v) and k in ("min_conviction", "options_conviction_threshold"):
            v = int(v)
        check, msg = _VALID[k]
        if not check(v):
            raise ValueError(f"{k}: {msg}")
        clean[k] = v
    if clean.get("risk_profile"):
        clean.update(PRESETS[clean["risk_profile"]])
    params = get_params()
    params.update(clean)
    put(_KEY, params)
    return params


def reset_params() -> dict:
    put(_KEY, dict(DEFAULTS))
    return dict(DEFAULTS)


# ── Capital-aware sizing (live Alpaca buying power via account_sync) ───────────

def _buying_power() -> float:
    try:
        import tools.account_sync as SYNC
        return SYNC.buying_power()
    except Exception:
        return 0.0


def _portfolio_value() -> float:
    try:
        import tools.account_sync as SYNC
        return SYNC.portfolio_value()
    except Exception:
        return 0.0


def available_capital() -> float:
    """Buying power minus the cash-reserve holdback — the sizing base."""
    p = get_params()
    bp = _buying_power()
    return max(0.0, bp * (1 - p["min_cash_reserve_pct"] / 100.0))


def position_dollar_cap() -> float:
    """Hard per-position cap in dollars: max_position_pct of buying power."""
    return _buying_power() * get_params()["max_position_pct"] / 100.0


def daily_loss_dollars() -> float:
    """Dollar pause threshold: max_daily_loss_pct of portfolio value."""
    pv = _portfolio_value()
    return pv * get_params()["max_daily_loss_pct"] / 100.0 if pv else 0.0


def alloc_pct(conviction100: int) -> float:
    """Allocation % of available capital for a given engine conviction score,
    per the tiered spec, scaled by profile and capped at max_position_pct."""
    p = get_params()
    if conviction100 >= 85:
        base = 8.5
    elif conviction100 >= 65:
        base = 5.0
    else:
        base = 2.5
    pct = base * _ALLOC_MULT.get(p["risk_profile"], 1.0)
    return max(1.0, min(pct, float(p["max_position_pct"])))


def position_size_dollars(conviction100: int) -> float:
    """Dollars to deploy on a new entry: available capital × allocation %,
    never above the per-position cap. With $100k buying power on moderate,
    a 75/100 conviction ≈ $5,000 — not $25. Shrunk further by the market
    outlook mode (CAUTIOUS → -50%, per the Markets outlook spec)."""
    dollars = available_capital() * alloc_pct(conviction100) / 100.0
    cap = position_dollar_cap()
    dollars = min(dollars, cap) if cap > 0 else dollars
    try:
        import tools.market_outlook as MO
        dollars *= MO.size_multiplier()
    except Exception:
        pass
    return dollars


def options_conviction_threshold() -> int:
    """Configurable options-entry bar (0-100 engine scale) — replaces the old
    hardcoded 45/70 cutoff in options_engine.py. 'set options conviction
    threshold to 50' updates this."""
    return int(get_params()["options_conviction_threshold"])


def set_options_threshold(value) -> str:
    """'set options conviction threshold to 50' — plain-English setter."""
    try:
        v = float(value)
        v = int(v) if v == int(v) else v
    except (TypeError, ValueError):
        return f"'{value}' isn't a number — try 'set options conviction threshold to 50'."
    try:
        set_params({"options_conviction_threshold": v})
    except ValueError as e:
        return f"Rejected: {e}"
    return f"Options conviction threshold set to {v}/100."


def min_conviction_engine() -> int:
    """Effective stock-entry conviction bar (0-100), folding in the current
    market outlook mode: SELECTIVE raises the bar +10, CAUTIOUS forces it to
    at least 85 (per the market outlook spec). STANDBY is handled upstream by
    autonomy_gate() blocking all new entries outright."""
    base = int(get_params()["min_conviction"]) * 10
    try:
        import tools.market_outlook as MO
        return MO.adjust_min_conviction(base)
    except Exception:
        return base


def scan_prefs() -> dict:
    """Scanning behavior for the active profile (Feature 1 point 3)."""
    return dict(SCAN_PREFS.get(get_params()["risk_profile"], SCAN_PREFS["moderate"]))


# ── Enforcement helpers (called by the trading pipeline) ───────────────────────

def _day_loss() -> float:
    """Today's total day P&L from Alpaca (equity vs last close) — negative = loss."""
    try:
        import tools.trading as TRD
        acct = TRD._api("GET", "/v2/account")
        return float(acct.get("equity", 0)) - float(acct.get("last_equity", 0))
    except Exception:
        return 0.0


def order_gate(symbol: str = "") -> tuple:
    """Checks that apply to EVERY order (manual or autonomous):
    blocked tickers, daily loss pause. Returns (ok, reason)."""
    p = get_params()
    sym = (symbol or "").upper()
    if sym and sym in [t.upper() for t in p["blocked_tickers"]]:
        return False, f"{sym} is on your blocked-tickers list (Markets dashboard)."
    loss = _day_loss()
    limit = daily_loss_dollars()
    if limit > 0 and loss <= -limit:
        return False, (f"DAILY LIMIT REACHED — down ${abs(loss):,.2f} today "
                       f"(limit {p['max_daily_loss_pct']:.1f}% = ${limit:,.0f}). "
                       f"Trading paused until tomorrow.")
    return True, "OK"


def autonomy_gate(symbol: str = "") -> tuple:
    """Extra checks for AUTONOMOUS entries only (auto_hunt, scale-ins,
    re-hunts, queue fills): master switch, trading-hours window, allowed
    sector. Manual explicit orders are not subject to these."""
    p = get_params()
    if not p["autonomous_enabled"]:
        return False, "Autonomous trading is OFF (master switch, Markets dashboard) — analysis only."
    ok, reason = order_gate(symbol)
    if not ok:
        return False, reason
    # Geopolitical risk CRITICAL (81+) halts all new autonomous positions
    try:
        import tools.political_intel as PI
        if PI.geo_size_factor() <= 0:
            return False, (f"Geopolitical risk CRITICAL ({PI.geo_risk_score()}/100) — "
                           "new positions halted, managing existing only.")
    except Exception:
        pass
    # Market outlook STANDBY halts all new autonomous positions (0-9/100 score
    # — extreme fear/breadth/volume conditions). User can override with
    # "force aggressive mode" / "ignore market outlook today".
    try:
        import tools.market_outlook as MO
        ok_o, why_o = MO.outlook_gate()
        if not ok_o:
            return False, why_o
    except Exception:
        pass
    # Trading-hours window (ET via Alpaca clock; naive local fallback)
    now_hm = None
    try:
        import tools.trading as TRD
        clk = TRD._api("GET", "/v2/clock")
        ts = clk.get("timestamp", "")
        if ts:
            now_hm = ts[11:16]
    except Exception:
        pass
    if not now_hm:
        now_hm = datetime.now().strftime("%H:%M")
    if not (p["trading_hours_start"] <= now_hm <= p["trading_hours_end"]):
        return False, (f"Outside your trading window {p['trading_hours_start']}-"
                       f"{p['trading_hours_end']} ET (now {now_hm} ET) — no autonomous entries.")
    return True, "OK"


def sector_allowed(symbol: str) -> tuple:
    """One yfinance lookup for the single candidate about to be traded."""
    p = get_params()
    if len(p["allowed_sectors"]) >= len(_SECTORS):
        return True, ""   # everything allowed — skip the lookup
    try:
        import yfinance as yf
        sector = (yf.Ticker(symbol).info or {}).get("sector", "") or ""
    except Exception:
        return True, ""   # can't verify — don't block on a data hiccup
    # Map yfinance's sector names onto the dashboard's 10 checkboxes
    alias = {"Consumer Cyclical": "Consumer", "Consumer Defensive": "Consumer",
             "Financial Services": "Financials", "Communication Services": "Communication",
             "Basic Materials": "Materials"}
    mapped = alias.get(sector, sector)
    if mapped and mapped not in p["allowed_sectors"]:
        return False, f"{symbol} is {sector} — excluded by your allowed-sectors settings."
    return True, ""


def params_report() -> str:
    """Human-readable settings summary (chat tool)."""
    p = get_params()
    loss = _day_loss()
    bp = _buying_power()
    pos_cap = position_dollar_cap()
    loss_cap = daily_loss_dollars()
    return "\n".join([
        "⚙️ RISK PARAMETERS", "━" * 30,
        f"  profile: {p['risk_profile'].upper().replace('_', ' ')}",
        f"  autonomous trading: {'ON 🟢' if p['autonomous_enabled'] else 'OFF ⚪ (analysis only)'}",
        f"  mode: {'LIVE 🔴' if p['live_trading'] else 'PAPER 🔵'}",
        f"  buying power: ${bp:,.2f} (live Alpaca — the only capital constraint)",
        f"  max position: {p['max_position_pct']:.1f}% of buying power"
        + (f" (= ${pos_cap:,.0f})" if pos_cap else "")
        + " | positions: unlimited (capital-constrained)",
        f"  cash reserve: {p['min_cash_reserve_pct']:.0f}% of buying power kept liquid",
        f"  daily loss limit: {p['max_daily_loss_pct']:.1f}% of portfolio"
        + (f" (= ${loss_cap:,.0f})" if loss_cap else "") + f" (today: ${loss:+,.2f})",
        f"  min conviction: {p['min_conviction']}/10 (engine ≥{p['min_conviction'] * 10}/100)",
        f"  sizing tiers: 5-6 conviction → {alloc_pct(55):.1f}% | 7-8 → {alloc_pct(75):.1f}% "
        f"| 9-10 → {alloc_pct(90):.1f}% of available capital",
        f"  stop {p['stop_loss_pct']:.1f}% | target +{p['take_profit_pct']:.0f}%",
        f"  hours: {p['trading_hours_start']}-{p['trading_hours_end']} ET",
        f"  blocked: {', '.join(p['blocked_tickers']) or 'none'}",
        f"  sectors: {'all' if len(p['allowed_sectors']) >= 10 else ', '.join(p['allowed_sectors'])}",
        "  Adjust in the 📈 Markets tab.",
    ])
