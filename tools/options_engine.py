"""
options_engine.py — JARVIS Options Trading Engine
Alpaca Markets options API.

Strategy: near-money calls/puts sized to ~1% of live capital per contract
  • 7-21 day expiry (sweet spot: Theta decay not yet vicious)
  • Target delta 0.30-0.50 (ATM to slight OTM)
  • Premium ≤ $0.90/share = ≤ $90/contract (leaves buffer in budget)
  • Requires conviction ≥ risk_params.options_conviction_threshold() (default
    55/100, configurable — "set options conviction threshold to 50") — a
    higher, independently-tunable bar than stocks since theta decay punishes
    a weak entry harder than a stock position does.

OCC Symbol: SOFI260718C00018000
  = SOFI | 2026-07-18 | C=Call (P=Put) | $18.00 strike
"""

import os, re, math
from datetime import datetime, timedelta, date
from pathlib import Path
from tools.store import get as _store_get, put as _store_put


# ── API helpers ─────────────────────────────────────────────────────────────────

def _cfg(k: str, d: str = "") -> str:
    return os.getenv(k, d)


def _api(method: str, path: str, params: dict = None, body: dict = None):
    """Alpaca broker API."""
    key    = _cfg("ALPACA_API_KEY")
    secret = _cfg("ALPACA_API_SECRET")
    base   = _cfg("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key or not secret:
        raise ValueError("Alpaca not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")

    import requests
    hdrs = {
        "APCA-API-KEY-ID":     key,
        "APCA-API-SECRET-KEY": secret,
        "accept":              "application/json",
        "content-type":        "application/json",
    }
    url = base.rstrip("/") + path

    if method.upper() == "GET":
        r = requests.get(url, headers=hdrs, params=params, timeout=15)
    elif method.upper() == "POST":
        r = requests.post(url, headers=hdrs, json=body, timeout=15)
    elif method.upper() == "DELETE":
        r = requests.delete(url, headers=hdrs, timeout=15)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    if not r.ok:
        err = r.text[:400]
        if "403" in str(r.status_code) or "not authorized" in err.lower():
            raise RuntimeError(
                "Options trading not enabled on this Alpaca account.\n"
                "Enable at: https://alpaca.markets → Account → Trading Permissions"
            )
        raise RuntimeError(f"Alpaca {method} {path} → {r.status_code}: {err}")

    return r.json() if r.text.strip() else {}


def _budget_remaining() -> float:
    """Capital available for options: live Alpaca buying power minus the
    cash-reserve holdback (delegates to tools/trading — the retired $100
    TRADING_BUDGET cap no longer applies)."""
    try:
        import tools.trading as TRD
        return TRD._budget_remaining()
    except Exception:
        return 0.0


def _max_premium() -> float:
    """Premium ceiling per share, scaled to live capital: one contract
    (100 shares) may risk ~1% of available capital. Floor $0.10/share,
    ceiling $25/share. Replaces the $100-era (budget-5)/100 formula."""
    avail = _budget_remaining()
    return max(0.10, min(avail * 0.01 / 100.0, 25.0))


# ── Options chain ────────────────────────────────────────────────────────────────

def _raw_contracts(symbol: str, expiry_min_days: int = 7, expiry_max_days: int = 21,
                   option_type: str = "call", limit: int = 100) -> list[dict]:
    """Unfiltered options contracts from Alpaca for the given expiry window (no premium/affordability filter)."""
    sym    = symbol.upper().strip()
    today  = date.today()
    d_from = (today + timedelta(days=expiry_min_days)).strftime("%Y-%m-%d")
    d_to   = (today + timedelta(days=expiry_max_days)).strftime("%Y-%m-%d")

    params = {
        "underlying_symbols": sym,
        "expiration_date_gte": d_from,
        "expiration_date_lte": d_to,
        "type": option_type.lower(),
        "limit": limit,
    }

    data = _api("GET", "/v2/options/contracts", params=params)
    return data if isinstance(data, list) else data.get("option_contracts", [])


def get_contracts(symbol: str, expiry_min_days: int = 7, expiry_max_days: int = 21,
                  option_type: str = "call", max_premium: float = 0.90) -> list[dict]:
    """
    Fetch options contracts from Alpaca within the budget-compatible premium range.
    Returns list sorted by liquidity × delta quality (best first).
    """
    contracts = _raw_contracts(symbol, expiry_min_days, expiry_max_days, option_type)

    # Filter: must have a price AND be affordable
    affordable = []
    for c in contracts:
        prem = float(c.get("close_price") or c.get("ask_price") or 0)
        if 0 < prem <= max_premium:
            c["_premium"]  = prem
            c["_cost"]     = round(prem * 100, 2)  # 1 contract = 100 shares
            affordable.append(c)

    # Score by liquidity × delta quality (prefer delta 0.30-0.50)
    def _score(c):
        oi    = int(c.get("open_interest", 0) or 0)
        vol   = int(c.get("volume", 0) or 0)
        delta = abs(float((c.get("greeks") or {}).get("delta", 0) or 0))
        # Gaussian peak at delta=0.40
        d_score = max(0.0, 1.0 - abs(delta - 0.40) * 4.0)
        return (oi + vol * 2) * d_score

    affordable.sort(key=_score, reverse=True)
    return affordable[:15]


def unusual_options_activity(symbol: str) -> str:
    """
    Flags unusual options activity for a symbol — a classic retail/momentum tell.
    Looks at call-vs-put volume skew and contracts where today's volume swamps
    existing open interest (fresh positioning, not stale OI), across the full
    chain (no premium/budget filter — this is a read for signal, not for a fill).
    """
    sym = symbol.upper().strip()
    lines = [f"Unusual Options Activity — {sym}", ""]

    try:
        calls = _raw_contracts(sym, 1, 45, "call", limit=200)
        puts  = _raw_contracts(sym, 1, 45, "put",  limit=200)
    except (RuntimeError, ValueError) as e:
        return f"{lines[0]}\n  {e}"

    if not calls and not puts:
        return f"{lines[0]}\n  No options chain data available for {sym}."

    call_vol = sum(int(c.get("volume", 0) or 0) for c in calls)
    put_vol  = sum(int(p.get("volume", 0) or 0) for p in puts)
    call_oi  = sum(int(c.get("open_interest", 0) or 0) for c in calls)
    put_oi   = sum(int(p.get("open_interest", 0) or 0) for p in puts)

    vol_pc_ratio = (call_vol / put_vol) if put_vol else (float("inf") if call_vol else 1.0)
    oi_pc_ratio  = (call_oi / put_oi) if put_oi else (float("inf") if call_oi else 1.0)

    def _hot(contracts):
        hot = [
            c for c in contracts
            if int(c.get("open_interest", 0) or 0) > 0
            and int(c.get("volume", 0) or 0) / max(1, int(c.get("open_interest", 0) or 0)) >= 2.0
        ]
        return sorted(hot, key=lambda c: -int(c.get("volume", 0) or 0))[:3]

    hot_calls = _hot(calls)
    hot_puts  = _hot(puts)

    lines += [
        f"  Call volume: {call_vol:,}   Put volume: {put_vol:,}   Vol C/P ratio: {vol_pc_ratio:.2f}",
        f"  Call OI:     {call_oi:,}   Put OI:     {put_oi:,}   OI C/P ratio:  {oi_pc_ratio:.2f}",
        "",
    ]
    if hot_calls:
        lines.append("  UNUSUAL CALL BUYING (today's volume >= 2x open interest):")
        for c in hot_calls:
            lines.append(
                f"    {c.get('symbol','?')}  strike ${float(c.get('strike_price',0) or 0):.2f}  "
                f"vol {int(c.get('volume',0) or 0):,}  OI {int(c.get('open_interest',0) or 0):,}"
            )
    if hot_puts:
        lines.append("  UNUSUAL PUT BUYING (today's volume >= 2x open interest):")
        for p in hot_puts:
            lines.append(
                f"    {p.get('symbol','?')}  strike ${float(p.get('strike_price',0) or 0):.2f}  "
                f"vol {int(p.get('volume',0) or 0):,}  OI {int(p.get('open_interest',0) or 0):,}"
            )
    if not hot_calls and not hot_puts:
        lines.append("  No contracts showing volume >= 2x open interest right now — no unusual flow detected.")

    if vol_pc_ratio > 1.5 and hot_calls:
        bias = "BULLISH — fresh call buying dominates"
    elif vol_pc_ratio < 0.67 and hot_puts:
        bias = "BEARISH — fresh put buying dominates"
    else:
        bias = "MIXED / NO CLEAR SKEW"
    lines += ["", f"  Read: {bias}"]

    return "\n".join(lines)


def options_chain(symbol: str, option_type: str = "call", expiry_days: int = 14) -> str:
    """
    Display the best affordable options contracts for a symbol.
    Usage: 'options chain SOFI calls' or 'SOFI put options'
    """
    sym       = symbol.upper().strip()
    budget_rem = _budget_remaining()
    max_prem   = _max_premium()

    lines = [
        f"Options Chain — {sym} {option_type.upper()}S",
        f"Budget: ${budget_rem:.2f} available | Max premium: ${max_prem:.2f}/sh (${max_prem*100:.0f}/contract)",
        f"Expiry window: up to {expiry_days} days out",
        "",
    ]

    try:
        contracts = get_contracts(sym, 5, expiry_days, option_type, max_prem)

        if not contracts:
            lines += [
                f"  No affordable {option_type} contracts within ${max_prem:.2f} premium.",
                "  Try: longer expiry, lower-priced stock, or wait for a volatility dip.",
            ]
            return "\n".join(lines)

        lines.append(
            f"  {'CONTRACT':<26} {'EXPIRY':<12} {'STRIKE':>7} {'PREM':>6} "
            f"{'COST':>6} {'DELTA':>7} {'OI':>7} {'VOL':>6}"
        )
        lines.append("  " + "─" * 82)

        for c in contracts[:8]:
            csym   = c.get("symbol", "?")
            expiry = c.get("expiration_date", "?")
            strike = float(c.get("strike_price", 0))
            prem   = c["_premium"]
            cost   = c["_cost"]
            greeks = c.get("greeks") or {}
            delta  = float(greeks.get("delta", 0) or 0)
            oi     = int(c.get("open_interest", 0) or 0)
            vol    = int(c.get("volume", 0) or 0)

            lines.append(
                f"  {csym:<26} {expiry:<12} ${strike:>6.2f} "
                f"${prem:>5.2f} ${cost:>5.0f} {delta:>+7.3f} {oi:>7,} {vol:>6,}"
            )

        lines += [
            "",
            "  Best pick is #1 (sorted by liquidity × delta quality).",
            f"  To buy: 'buy option [contract_symbol] {sym}'",
        ]

    except RuntimeError as e:
        lines.append(f"  {e}")

    return "\n".join(lines)


# ── Smart options scan ────────────────────────────────────────────────────────────

def options_best_play(symbol: str, conviction: int = 0) -> str:
    """
    Recommend the single best options contract for a symbol based on conviction score.
    Call when conviction ≥ 60 (bullish) or ≤ 40 (bearish).
    Higher bar than stock trades because theta decay punishes indecision.
    """
    sym        = symbol.upper().strip()
    budget_rem = _budget_remaining()

    if budget_rem < 20:
        return f"Options blocked: only ${budget_rem:,.2f} capital available (need ≥$20 for 1 contract)."

    if conviction >= 60:
        direction = "call"
        rationale = f"Bullish bias ({conviction}/100 conviction)"
    elif conviction <= 40 and conviction > 0:
        direction = "put"
        rationale = f"Bearish bias ({conviction}/100 conviction)"
    else:
        return (
            f"Options scan skipped: conviction {conviction}/100 is too neutral.\n"
            f"Need ≥60 for calls, ≤40 for puts. Get a stronger signal first."
        )

    max_prem = _max_premium()

    try:
        contracts = get_contracts(sym, 7, 21, direction, max_prem)

        if not contracts:
            return (
                f"No affordable {direction} options for {sym}.\n"
                f"Budget: ${budget_rem:.2f} | Max premium: ${max_prem:.2f}\n"
                f"Consider: a cheaper underlier, or wait for IV to drop."
            )

        c      = contracts[0]
        csym   = c.get("symbol", "")
        expiry = c.get("expiration_date", "")
        strike = float(c.get("strike_price", 0))
        prem   = c["_premium"]
        cost   = c["_cost"]
        greeks = c.get("greeks") or {}
        delta  = float(greeks.get("delta", 0) or 0)
        gamma  = float(greeks.get("gamma", 0) or 0)
        theta  = float(greeks.get("theta", 0) or 0)
        iv     = float(c.get("implied_volatility", 0) or 0)
        oi     = int(c.get("open_interest", 0) or 0)

        lines = [
            f"Best {direction.upper()} Option for {sym}",
            f"─" * 42,
            f"  Contract: {csym}",
            f"  Expiry:   {expiry}  |  Strike: ${strike:.2f}",
            f"  Premium:  ${prem:.2f}/share  =  ${cost:.0f} per contract",
            f"  Greeks:   Δ{delta:+.3f}  Γ{gamma:.4f}  Θ{theta:+.4f}",
            f"  IV:       {iv:.1%}  |  Open Interest: {oi:,}",
            f"  Rationale:{rationale}",
            f"  Budget:   ${budget_rem:.2f} available → ${budget_rem - cost:.2f} after fill",
            "",
            f"  ✓ To execute: say 'options buy {csym}'",
            f"  ✓ Risk:       max loss = ${cost:.0f} (total premium paid, no margin)",
        ]
        return "\n".join(lines)

    except RuntimeError as e:
        return f"Options scan failed: {e}"


_SCAN_STREAK_KEY = "options_scan_streak"


def _record_scan_streak(passed: bool) -> int:
    """Tracks consecutive scans where 0 candidates cleared the conviction
    threshold, persisted via store.py so it survives across both the server
    process and the Task Scheduler (auto_trade_daily.py) process. Returns the
    current zero-pass streak count."""
    st = _store_get(_SCAN_STREAK_KEY) or {"zero_count": 0}
    st["zero_count"] = 0 if passed else st.get("zero_count", 0) + 1
    _store_put(_SCAN_STREAK_KEY, st)
    return st["zero_count"]


def options_auto_hunt(min_conviction: int = None) -> str:
    """
    Scan universe for the best options play right now.
    Conviction bar comes from risk_params.options_conviction_threshold()
    (default 55/100, independently configurable from the stock-side
    min_conviction) unless min_conviction is explicitly passed in — that
    override is respected exactly, not silently ignored like the old
    hardcoded-45-regardless-of-argument bug.
    """
    budget_rem = _budget_remaining()
    if budget_rem < 25:
        return f"Options hunt skipped: ${budget_rem:.2f} remaining (need ≥$25 for 1 contract)."

    try:
        import tools.risk_params as RP
        threshold = int(min_conviction) if min_conviction is not None else RP.options_conviction_threshold()
    except Exception:
        threshold = int(min_conviction) if min_conviction is not None else 55

    # Volatile, liquid names with active options chains
    candidates = [
        "SOFI", "PLTR", "SOUN", "BBAI", "AI", "RKLB",
        "COIN", "HOOD", "MSTR", "GME", "AMD", "TSLA",
    ]

    _mp = _max_premium()
    lines = [
        f"Options Auto-Hunt — Scanning {len(candidates)} stocks",
        f"Min conviction: {threshold}/100 | Capital: ${budget_rem:,.2f}",
        f"Strategy: 7-21 day expiry | delta 0.30-0.50 | premium ≤ ${_mp:.2f}/share (~1% capital/contract)",
        "",
    ]

    best_sym   = None
    best_score = 0
    best_c     = None
    best_dir   = None

    for sym in candidates:
        try:
            # Quick TA-only score (fast, avoids full conviction pipeline)
            import tools.market as MKT
            bars = MKT._fetch_history(sym, 90)
            if not bars or len(bars) < 21:
                continue
            ta  = MKT._compute_ta(bars)
            _, raw_score, _ = MKT._score_signal(ta)
            rough = int((raw_score + 10) / 20 * 100)  # normalize -10..+10 to 0-100 (same scale as conviction_score)

            if rough < threshold:
                lines.append(f"  SKIP  {sym}: TA score {rough}/100 — too weak (need ≥{threshold})")
                try:
                    import tools.trade_monitor as MON
                    MON.log_skip(sym, f"options TA score {rough}/100 below threshold {threshold}", source="options_auto_hunt")
                except Exception:
                    pass
                continue

            direction  = "call" if rough >= 60 else "put"
            max_prem   = _max_premium()
            contracts  = get_contracts(sym, 7, 21, direction, max_prem)

            if contracts:
                c = contracts[0]
                lines.append(
                    f"  FOUND {sym}: {direction.upper()} | "
                    f"{c.get('symbol','')} | "
                    f"prem ${c['_premium']:.2f} | TA:{rough}/100"
                )
                if rough > best_score:
                    best_score = rough
                    best_sym   = sym
                    best_c     = c
                    best_dir   = direction
            else:
                lines.append(f"  SKIP  {sym}: no affordable {direction} contracts ≤${max_prem:.2f}")

        except Exception as e:
            lines.append(f"  ERR   {sym}: {str(e)[:60]}")

    streak = _record_scan_streak(passed=bool(best_c))
    if best_c:
        prem  = best_c["_premium"]
        cost  = best_c["_cost"]
        lines += [
            "",
            f"━━ BEST PLAY: {best_sym} {best_dir.upper()} ━━",
            f"  Contract: {best_c.get('symbol','')}",
            f"  Expiry:   {best_c.get('expiration_date','')}  |  Strike: ${float(best_c.get('strike_price',0)):.2f}",
            f"  Premium:  ${prem:.2f}/sh  =  ${cost:.0f}/contract",
            f"  Risk:     max loss = ${cost:.0f} (entire premium if expires worthless)",
            f"",
            f"  → To execute: say 'options buy {best_c.get('symbol','')}'",
        ]
    else:
        lines += ["", "No affordable options plays found. Market conditions may not be ideal."]
        if streak >= 3:
            warn = (f"⚠ {streak} consecutive options scans found 0 qualifying plays "
                    f"(threshold {threshold}/100) — market conditions may be too weak for "
                    f"this bar, or the threshold may be miscalibrated. "
                    f"Say 'set options conviction threshold to {max(30, threshold - 10)}' to lower it.")
            lines += ["", warn]
            try:
                import tools.trade_monitor as MON
                MON._push_user_alert(warn)
            except Exception:
                pass

    return "\n".join(lines)


# ── Order execution ──────────────────────────────────────────────────────────────

def options_buy(contract_symbol: str, qty: int = 1, limit_price: float = None) -> str:
    """
    Buy an options contract via Alpaca.
    contract_symbol: OCC format (e.g. SOFI260718C00018000)
    limit_price: per-share premium (e.g. 0.50 = $50 total per contract)
    """
    budget_rem = _budget_remaining()
    est_cost   = (limit_price or 0.50) * 100 * qty

    if budget_rem < est_cost:
        return (
            f"Options buy blocked: ${budget_rem:.2f} remaining, "
            f"order would cost ~${est_cost:.0f}.\n"
            f"Close a position first to free up budget."
        )

    if limit_price:
        body = {
            "symbol": contract_symbol,
            "qty": str(qty),
            "side": "buy",
            "type": "limit",
            "limit_price": str(round(limit_price, 2)),
            "time_in_force": "day",
        }
        order_type = f"LIMIT @ ${limit_price:.2f}/share"
    else:
        body = {
            "symbol": contract_symbol,
            "qty": str(qty),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
        }
        order_type = "MARKET"

    try:
        order = _api("POST", "/v2/orders", body=body)
        oid   = order.get("id", "?")[:8]
        stat  = order.get("status", "?")

        return (
            f"OPTIONS ORDER PLACED\n"
            f"  Contract:  {contract_symbol}\n"
            f"  Qty:       {qty} contract(s)  ({qty * 100} shares)\n"
            f"  Type:      {order_type}\n"
            f"  Max Loss:  ${est_cost:.0f} (premium paid)\n"
            f"  Status:    {stat.upper()}\n"
            f"  Order ID:  {oid}\n"
            f"  Budget after fill: ~${budget_rem - est_cost:.2f}"
        )
    except RuntimeError as e:
        return f"Options buy failed: {e}"


def options_close(contract_symbol: str, qty: int = 1) -> str:
    """Sell to close an options position (market order)."""
    body = {
        "symbol": contract_symbol,
        "qty": str(qty),
        "side": "sell",
        "type": "market",
        "time_in_force": "day",
    }
    try:
        order = _api("POST", "/v2/orders", body=body)
        oid  = order.get("id", "?")[:8]
        stat = order.get("status", "?")
        return f"Options SELL TO CLOSE: {contract_symbol} × {qty}ct | {stat.upper()} | ID:{oid}"
    except RuntimeError as e:
        return f"Options close failed: {e}"


# ── Positions & portfolio ────────────────────────────────────────────────────────

def options_positions() -> str:
    """Show all open options positions with P&L."""
    try:
        positions = _api("GET", "/v2/positions")
        # Options positions have asset_class=us_option or OCC-format symbol
        occ_pattern = re.compile(r"^[A-Z]{1,5}\d{6}[CP]\d{8}$")
        opts = [
            p for p in positions
            if p.get("asset_class") == "us_option" or occ_pattern.match(p.get("symbol", ""))
        ]

        if not opts:
            return "No open options positions."

        lines = ["Open Options Positions", ""]
        total_pnl = 0.0

        for p in opts:
            sym     = p.get("symbol", "")
            qty     = float(p.get("qty", 0))
            entry   = float(p.get("avg_entry_price", 0))
            curr    = float(p.get("current_price", 0))
            pnl     = float(p.get("unrealized_pl", 0))
            pnl_pct = float(p.get("unrealized_plpc", 0)) * 100
            arrow   = "▲" if pnl >= 0 else "▼"
            total_pnl += pnl

            lines.append(
                f"  {sym:<28}  {qty:.0f}ct  "
                f"entry:${entry:.2f}→now:${curr:.2f}  "
                f"{arrow}${abs(pnl):.2f} ({pnl_pct:+.1f}%)"
            )

        lines += ["", f"  Total Options P&L: ${total_pnl:+.2f}"]
        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching options positions: {e}"
