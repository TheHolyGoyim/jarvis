"""
trade_monitor.py — JARVIS Autonomous Trade Monitor
Runs as a background daemon thread inside server.py.

Every 30 seconds:
  • Polls all open positions
  • Applies intelligent adjustment rules (breakeven, trail, partial profit, RSI cut)
  • Every ~5 cycles, re-scores each position's conviction and decides hold/sell/buy-more
  • Detects closed trades → hunts for the next entry (stocks + options)
  • Writes live dashboard to ~/Documents/JARVIS/trading/dashboard.json
  • Logs every event to trade_log.txt

Adjustment rules (applied per position):
  +2.5%  → Move stop to breakeven (no more risk possible)
  +5.0%  → Switch to 4% trailing stop (let winners run)
  +9.0%  → Partial exit: sell 50%, lock gains, free budget for next trade
  -4.0%  → Early exit if RSI on 15-min is turning bearish (cut before stop)
  conviction degraded (<35) → early defensive exit regardless of price
  conviction still strong (>=65) + price up + budget free → scale in (buy more), once
  live tape (real-time trade stream) shows strong sell pressure, no profit lock yet
         → early defensive exit, faster than price/RSI on lagging bars
  target → Full exit fires automatically via Alpaca bracket
  stop   → Full exit fires automatically via Alpaca stop order
"""

import os, re, json, math, time, threading, traceback
from datetime import datetime, timedelta
from pathlib import Path

# ── Storage ─────────────────────────────────────────────────────────────────────
_DATA_DIR      = Path.home() / "Documents" / "JARVIS" / "trading"
_JOURNAL_FILE  = _DATA_DIR / "trade_journal.json"
_DASHBOARD_FILE= _DATA_DIR / "dashboard.json"
_REPORT_FILE   = _DATA_DIR / "trade_report.txt"
_LOG_FILE      = _DATA_DIR / "trade_log.txt"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Monitor state ────────────────────────────────────────────────────────────────
_monitor_thread   = None
_monitor_running  = False
_last_positions   = {}    # symbol → last known position data
_last_check_time  = None
_check_interval   = 30    # seconds between position checks — hawk positions closely
_events_buffer    = []    # recent events (last 50)

def _cfg(k: str, d: str = "") -> str:
    return os.getenv(k, d)

# ── Logging ──────────────────────────────────────────────────────────────────────
def _log(msg: str, level: str = "INFO"):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    _events_buffer.append({"time": ts, "level": level, "msg": msg})
    if len(_events_buffer) > 100:
        _events_buffer.pop(0)

# ── Journal ──────────────────────────────────────────────────────────────────────
def _load_journal() -> dict:
    try:
        if _JOURNAL_FILE.exists():
            return json.loads(_JOURNAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "mission": {
            # Capital comes LIVE from Alpaca (account_sync) — no budget cap.
            # 'goal' is a display fallback; the goal engine is authoritative.
            "goal":     float(_cfg("TRADING_GOAL", "0") or 0),
            "started":  datetime.now().strftime("%Y-%m-%d"),
            "end_date": None,
        },
        "positions":     {},
        "closed_trades": [],
    }

def _save_journal(j: dict):
    try:
        _JOURNAL_FILE.write_text(json.dumps(j, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

def _journal_open_position(symbol: str, qty: float, entry_price: float,
                           stop_price: float, target_price: float,
                           conviction: int = 0, reasoning: str = ""):
    """Record a new open position in the journal."""
    j = _load_journal()
    j["positions"][symbol] = {
        "symbol":          symbol,
        "qty":             qty,
        "entry_price":     entry_price,
        "entry_time":      datetime.now().isoformat(),
        "cost_basis":      round(qty * entry_price, 2),
        "stop_price":      stop_price,
        "target_price":    target_price,
        "conviction_score":conviction,
        "reasoning":       reasoning,
        "be_stop_applied": False,
        "trail_applied":   False,
        "partial_applied": False,
        "adjustments":     [],
    }
    _save_journal(j)

def _journal_close_position(symbol: str, exit_price: float, qty: float,
                            reason: str = ""):
    """Move an open position to closed_trades."""
    j = _load_journal()
    pos = j["positions"].pop(symbol, None)
    if not pos:
        return
    entry = pos.get("entry_price", exit_price)
    entry_time = pos.get("entry_time", datetime.now().isoformat())
    try:
        mins = int((datetime.now() - datetime.fromisoformat(entry_time)).total_seconds() / 60)
    except Exception:
        mins = 0
    pnl     = round((exit_price - entry) * qty, 2)
    pnl_pct = round((exit_price - entry) / entry * 100, 2) if entry else 0
    j["closed_trades"].append({
        "symbol":           symbol,
        "qty":              qty,
        "entry_price":      entry,
        "exit_price":       exit_price,
        "entry_time":       entry_time,
        "exit_time":        datetime.now().isoformat(),
        "duration_minutes": mins,
        "pnl":              pnl,
        "pnl_pct":          pnl_pct,
        "result":           "WIN" if pnl > 0 else "LOSS",
        "reason":           reason,
        "conviction_score": pos.get("conviction_score", 0),
        "reasoning":        pos.get("reasoning", ""),
        "adjustments":      pos.get("adjustments", []),
    })
    _save_journal(j)
    _log(f"Trade closed: {symbol} | exit ${exit_price:.2f} | P&L ${pnl:+.2f} ({pnl_pct:+.1f}%) | {reason}", "TRADE")

def _journal_adjustment(symbol: str, action: str, detail: str):
    j = _load_journal()
    if symbol in j["positions"]:
        j["positions"][symbol].setdefault("adjustments", []).append({
            "time":   datetime.now().isoformat(),
            "action": action,
            "detail": detail,
        })
        _save_journal(j)


# ── Skip log — "why didn't you buy X" ─────────────────────────────────────────
# Every scan (auto_hunt, opportunity_scan queue fills) that considers a symbol
# and decides NOT to trade it logs the reason here, keyed by symbol + date, so
# a skip is just as explainable after the fact as an executed trade.
def log_skip(symbol: str, reason: str, source: str = ""):
    sym = symbol.upper().strip()
    j = _load_journal()
    skips = j.setdefault("skips", [])
    skips.append({
        "symbol": sym,
        "reason": reason,
        "source": source,
        "time":   datetime.now().isoformat(),
    })
    # Keep the log bounded — most-recent 500 skips is plenty for "why didn't
    # you buy X" lookups without the journal file growing unbounded.
    if len(skips) > 500:
        j["skips"] = skips[-500:]
    _save_journal(j)


def skip_reason(symbol: str) -> str:
    """Why did JARVIS pass on this symbol? Looks up the most recent skip
    logged for it (today or otherwise) — never a fresh recompute."""
    sym = symbol.upper().strip()
    j = _load_journal()
    hits = [s for s in j.get("skips", []) if s.get("symbol") == sym]
    if not hits:
        # Not skipped — maybe it was never scanned, or it was actually traded.
        if sym in j.get("positions", {}) or any(
            t.get("symbol") == sym for t in j.get("closed_trades", [])
        ):
            return f"{sym} wasn't skipped — JARVIS actually traded it. Say 'why did you buy {sym}' for the reasoning."
        return f"No record of {sym} being scanned or skipped recently."
    s = hits[-1]
    ts = s.get("time", "?")[:16].replace("T", " ")
    src = f" ({s['source']} scan)" if s.get("source") else ""
    return f"Skipped {sym} at {ts}{src} — {s.get('reason', '?')}"

# ── Alpaca helpers ────────────────────────────────────────────────────────────────
def _api(method: str, path: str, body: dict = None) -> dict:
    key    = _cfg("ALPACA_API_KEY")
    secret = _cfg("ALPACA_API_SECRET")
    base   = _cfg("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    import requests
    hdrs   = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
               "Content-Type": "application/json"}
    url    = base.rstrip("/") + path
    r      = requests.request(method, url, headers=hdrs, json=body, timeout=15)
    if not r.ok:
        try:    msg = r.json().get("message", r.text[:200])
        except: msg = r.text[:200]
        raise ValueError(f"{method} {path} → {r.status_code}: {msg}")
    return r.json() if r.content else {}

def _data(path: str, params: dict = None) -> dict:
    key    = _cfg("ALPACA_API_KEY")
    secret = _cfg("ALPACA_API_SECRET")
    import requests
    hdrs   = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    r      = requests.get(f"https://data.alpaca.markets{path}",
                          headers=hdrs, params=params, timeout=12)
    if not r.ok:
        raise ValueError(f"Data {path} → {r.status_code}: {r.text[:100]}")
    return r.json()

def _is_market_open() -> bool:
    try:
        return _api("GET", "/v2/clock").get("is_open", False)
    except Exception:
        return False

def _get_positions() -> list:
    try:
        return _api("GET", "/v2/positions")
    except Exception:
        return []

def _get_open_orders(symbol: str = "") -> list:
    try:
        path = "/v2/orders?status=open&limit=50"
        if symbol:
            path += f"&symbols={symbol}"
        return _api("GET", path)
    except Exception:
        return []

def _cancel_stop_orders(symbol: str):
    """Cancel all open stop orders for a symbol."""
    orders = _get_open_orders(symbol)
    for o in orders:
        if o.get("type") in ("stop", "stop_limit") and o.get("side") == "sell":
            try:
                _api("DELETE", f"/v2/orders/{o['id']}")
                _log(f"Cancelled stop order {o['id'][:8]} for {symbol}")
            except Exception as e:
                _log(f"Failed to cancel stop {o['id'][:8]}: {e}", "WARN")

def _cancel_limit_orders(symbol: str):
    """Cancel all open limit (take-profit) sell orders for a symbol."""
    orders = _get_open_orders(symbol)
    for o in orders:
        if o.get("type") == "limit" and o.get("side") == "sell":
            try:
                _api("DELETE", f"/v2/orders/{o['id']}")
            except Exception:
                pass

# ── Adjustment actions ────────────────────────────────────────────────────────────
def _move_stop_breakeven(symbol: str, entry_price: float, qty: int) -> bool:
    """
    Moves the stop loss to the entry price (breakeven).
    Cancels existing stop, places new stop at entry_price.
    Returns True if successful.
    """
    try:
        _cancel_stop_orders(symbol)
        time.sleep(0.5)
        r = _api("POST", "/v2/orders", {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          "sell",
            "type":          "stop",
            "time_in_force": "gtc",
            "stop_price":    f"{entry_price:.2f}",
        })
        detail = f"Stop moved to breakeven ${entry_price:.2f} (ID:{r.get('id','?')[:8]})"
        _log(f"{symbol}: {detail}", "ADJUST")
        _journal_adjustment(symbol, "breakeven_stop", detail)
        return True
    except Exception as e:
        _log(f"{symbol}: Breakeven stop failed: {e}", "ERROR")
        return False

def _switch_trailing_stop(symbol: str, qty: int, trail_pct: float = 4.0) -> bool:
    """
    Cancels bracket orders, places a trailing stop to lock profits while letting them run.
    """
    try:
        _cancel_stop_orders(symbol)
        _cancel_limit_orders(symbol)
        time.sleep(0.5)
        r = _api("POST", "/v2/orders", {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          "sell",
            "type":          "trailing_stop",
            "time_in_force": "gtc",
            "trail_percent": f"{trail_pct}",
        })
        detail = f"Switched to {trail_pct}% trailing stop (ID:{r.get('id','?')[:8]})"
        _log(f"{symbol}: {detail}", "ADJUST")
        _journal_adjustment(symbol, "trailing_stop", detail)
        return True
    except Exception as e:
        _log(f"{symbol}: Trail stop switch failed: {e}", "ERROR")
        return False

def _partial_exit(symbol: str, qty_to_sell: int, reason: str = "partial profit") -> bool:
    """Sell a portion of the position at market."""
    try:
        r = _api("POST", "/v2/orders", {
            "symbol":        symbol,
            "qty":           str(qty_to_sell),
            "side":          "sell",
            "type":          "market",
            "time_in_force": "day",
        })
        detail = f"Partial exit: sold {qty_to_sell} shares ({reason}) ID:{r.get('id','?')[:8]}"
        _log(f"{symbol}: {detail}", "TRADE")
        _journal_adjustment(symbol, "partial_exit", detail)
        return True
    except Exception as e:
        _log(f"{symbol}: Partial exit failed: {e}", "ERROR")
        return False

def _emergency_exit(symbol: str, qty: int, reason: str) -> bool:
    """Full market exit for a position."""
    try:
        _api("DELETE", f"/v2/positions/{symbol}")
        _log(f"{symbol}: Emergency exit — {reason}", "TRADE")
        return True
    except Exception as e:
        _log(f"{symbol}: Emergency exit failed: {e}", "ERROR")
        return False

def _get_conviction(symbol: str) -> int:
    """Current conviction score (0-100) for a symbol, or -1 if unavailable."""
    try:
        import tools.conviction as CVN
        report = CVN.conviction_score(symbol)
        m = re.search(r'SCORE:\s*(\d+)/100', report)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


def _scale_in_position(symbol: str, existing_qty: int, price: float, conviction: int) -> int:
    """
    Add to a winning, still-high-conviction position ('buy more'). Sized within
    live buying power (never more than doubles the original position), and
    never bypasses the risk-param guard.
    Returns the number of shares added (0 if none).
    """
    try:
        # Scale-ins are autonomous entries — master switch/hours/sector apply.
        try:
            import tools.risk_params as RP
            g_ok, g_why = RP.autonomy_gate(symbol)
            if not g_ok:
                _log(f"{symbol}: scale-in blocked — {g_why}", "INFO")
                return 0
        except Exception:
            pass
        import tools.trading as TRD
        ok, reason = TRD._guard(symbol)
        if not ok:
            _log(f"{symbol}: scale-in blocked by guard — {reason}", "INFO")
            return 0
        budget_rem = TRD._budget_remaining()
        if budget_rem < price:
            return 0
        add_qty = min(existing_qty, math.floor(budget_rem / price))
        if add_qty < 1:
            return 0
        r = TRD._api("POST", "/v2/orders", {
            "symbol": symbol, "qty": str(add_qty), "side": "buy",
            "type": "market", "time_in_force": "day",
        })
        _log(
            f"{symbol}: Scaled in +{add_qty} shares @ ~${price:.2f} "
            f"(conviction {conviction}/100) ID:{r.get('id','?')[:8]}", "TRADE"
        )
        return add_qty
    except Exception as e:
        _log(f"{symbol}: Scale-in failed: {e}", "ERROR")
        return 0


def _rsi_turning_bearish(symbol: str):
    """
    Checks 15-min RSI trend. Returns (is_bearish, rsi_now, rsi_before).
    'Turning bearish' = RSI has dropped meaningfully and sits below neutral —
    used to cut a losing position before its hard stop, not after.
    """
    try:
        import tools.market as MKT
        bars = MKT._fetch_intraday(symbol, "15Min", 40)
        if len(bars) < 20:
            return False, None, None
        ta_now    = MKT._compute_ta(bars)
        ta_before = MKT._compute_ta(bars[:-3])
        rsi_now    = ta_now.get("rsi")
        rsi_before = ta_before.get("rsi")
        if rsi_now is None or rsi_before is None:
            return False, rsi_now, rsi_before
        declining    = rsi_now < rsi_before - 3
        bearish_zone = rsi_now < 48
        return (declining and bearish_zone), rsi_now, rsi_before
    except Exception:
        return False, None, None


# ── Position adjustment logic ─────────────────────────────────────────────────────
def _check_position(pos: dict, journal_positions: dict) -> list[str]:
    """
    Apply adjustment rules to a single open position.
    Returns list of actions taken.
    """
    symbol  = pos["symbol"]
    curr    = float(pos.get("current_price",    0))
    entry   = float(pos.get("avg_entry_price",  0))
    qty     = int(float(pos.get("qty",          0)))
    pl_pct  = float(pos.get("unrealized_plpc",  0)) * 100
    pl_abs  = float(pos.get("unrealized_pl",    0))

    if not entry or not curr or qty < 1:
        return []

    actions     = []
    jpos        = journal_positions.get(symbol, {})
    be_applied  = jpos.get("be_stop_applied",  False)
    trail_applied = jpos.get("trail_applied",  False)
    partial_applied = jpos.get("partial_applied", False)

    # ── Rule 1: Breakeven stop at +2.5% ─────────────────────────────────────
    if pl_pct >= 2.5 and not be_applied and not trail_applied:
        if _move_stop_breakeven(symbol, entry, qty):
            j = _load_journal()
            if symbol in j["positions"]:
                j["positions"][symbol]["be_stop_applied"] = True
            _save_journal(j)
            actions.append(f"Breakeven stop set at ${entry:.2f} (locked in, risk-free now)")

    # ── Rule 2: Switch to 4% trailing stop at +5% ────────────────────────────
    if pl_pct >= 5.0 and not trail_applied:
        if _switch_trailing_stop(symbol, qty, trail_pct=4.0):
            j = _load_journal()
            if symbol in j["positions"]:
                j["positions"][symbol]["trail_applied"] = True
                j["positions"][symbol]["be_stop_applied"] = True
            _save_journal(j)
            actions.append(f"Trailing stop activated (4% trail, locking +{pl_pct:.1f}% gain)")

    # ── Rule 3: Partial profit at +9% (sell 50%) ─────────────────────────────
    if pl_pct >= 9.0 and not partial_applied and qty >= 2:
        sell_qty = max(1, qty // 2)
        if _partial_exit(symbol, sell_qty, f"+{pl_pct:.1f}% gain"):
            j = _load_journal()
            if symbol in j["positions"]:
                j["positions"][symbol]["partial_applied"] = True
                j["positions"][symbol]["qty"] = qty - sell_qty
            _save_journal(j)
            profit_locked = round(sell_qty * (curr - entry), 2)
            actions.append(
                f"Partial profit: sold {sell_qty} shares @ ${curr:.2f} "
                f"(locked ${profit_locked:+.2f}, {qty-sell_qty} still running)"
            )

    # ── Rule 4: Early exit at -4% if 15-min RSI is turning bearish ──────────
    early_exit_checked = jpos.get("early_exit_checked", False)
    if pl_pct <= -4.0 and not early_exit_checked:
        is_bearish, rsi_now, rsi_before = _rsi_turning_bearish(symbol)
        j = _load_journal()
        if symbol in j["positions"]:
            j["positions"][symbol]["early_exit_checked"] = True
        _save_journal(j)
        if is_bearish:
            detail = (
                f"Early exit at {pl_pct:.1f}% — 15-min RSI turning bearish "
                f"({rsi_before:.0f}→{rsi_now:.0f}), cutting before the hard stop"
            )
            if _emergency_exit(symbol, qty, detail):
                _journal_adjustment(symbol, "early_rsi_exit", detail)
                _push_exit_alert(symbol, curr, qty, pl_pct, pl_abs, detail, jpos)
                actions.append(detail)

    # ── Rule 6: Real-time trade tape shows strong sustained sell pressure ──
    # Before any profit lock is in place (breakeven stop), react to what the
    # live tick stream (trade_stream.py) shows right now instead of waiting
    # for price/RSI to catch up on lagging bars — the whole point of having
    # a real-time feed instead of only 30s-polled REST snapshots.
    if pl_pct < 2.5 and not be_applied:
        try:
            import tools.trade_stream as TAPE
            tape_pts, tape_detail = TAPE.live_tape_signal(symbol)
        except Exception:
            tape_pts, tape_detail = 5, ""
        if tape_pts == 0:
            detail = f"Real-time tape: strong sell pressure at {pl_pct:+.1f}% — {tape_detail}"
            if _emergency_exit(symbol, qty, detail):
                _journal_adjustment(symbol, "tape_exit", detail)
                _push_exit_alert(symbol, curr, qty, pl_pct, pl_abs, detail, jpos)
                actions.append(detail)

    # ── Rule 5: Periodic conviction re-evaluation — hold, cut, or buy more ──
    # Surveys the thesis itself (not just price) every ~5 minutes so a position
    # isn't held on autopilot once the reasoning behind it has changed.
    last_check_str = jpos.get("last_conviction_check", "")
    due_for_check = True
    if last_check_str:
        try:
            due_for_check = (
                datetime.now() - datetime.fromisoformat(last_check_str)
            ).total_seconds() >= 300
        except Exception:
            due_for_check = True

    if due_for_check:
        j = _load_journal()
        if symbol in j["positions"]:
            j["positions"][symbol]["last_conviction_check"] = datetime.now().isoformat()
        _save_journal(j)

        conviction_now = _get_conviction(symbol)
        if conviction_now >= 0:
            entry_conviction = jpos.get("conviction_score", 0)

            # Thesis deteriorated badly — exit on the reasoning, not just price
            # (skip if the RSI rule already has this near its hard stop)
            if conviction_now < 35 and pl_pct > -4.0:
                detail = (
                    f"Conviction collapsed to {conviction_now}/100 (was {entry_conviction}) "
                    f"at {pl_pct:+.1f}% — exiting on deteriorated thesis, not price"
                )
                if _emergency_exit(symbol, qty, detail):
                    _journal_adjustment(symbol, "conviction_exit", detail)
                    _push_exit_alert(symbol, curr, qty, pl_pct, pl_abs, detail, jpos)
                    actions.append(detail)

            # Thesis still strong, price up modestly, budget free, haven't
            # already scaled in — buy more instead of just holding
            elif conviction_now >= 65 and 0 <= pl_pct < 5.0 and not jpos.get("scaled_in", False):
                added = _scale_in_position(symbol, qty, curr, conviction_now)
                if added:
                    j = _load_journal()
                    if symbol in j["positions"]:
                        j["positions"][symbol]["scaled_in"] = True
                        j["positions"][symbol]["qty"] = qty + added
                    _save_journal(j)
                    actions.append(
                        f"Conviction still strong ({conviction_now}/100) at {pl_pct:+.1f}% — "
                        f"scaled in +{added} shares"
                    )

    # ── Rule 7: multi-signal exit framework + dashboard stop/TP params ──────
    try:
        actions += _exit_signal_scan(symbol, pos, jpos, curr, entry, qty, pl_pct)
    except Exception as e:
        _log(f"{symbol}: signal scan error {e}", "WARN")

    return actions


# ── Rule 7: intelligent multi-signal exit monitoring ──────────────────────────────
# Beyond stop/target: every ~5 min each position is scanned for six exit
# signals. 1 signal → warning log. 2 → alert the user (pops into the chat via
# the reminders channel), prepare to exit. 3+ → exit automatically, with the
# full reasoning logged. Also enforces the Markets-dashboard stop_loss_pct /
# take_profit_pct on positions (TP → sell 50% + breakeven the rest).

_sig_state = {}   # symbol → throttles + latches (rsi_was_high, sector cache, ...)
_SECTOR_ETF = {"Technology": "XLK", "Healthcare": "XLV", "Energy": "XLE",
               "Financial Services": "XLF", "Financials": "XLF",
               "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
               "Industrials": "XLI", "Basic Materials": "XLB", "Materials": "XLB",
               "Utilities": "XLU", "Real Estate": "XLRE",
               "Communication Services": "XLC", "Communication": "XLC"}


def _push_user_alert(text: str):
    """Surface an alert in the chat UI via the reminders channel (polled 30s)."""
    try:
        import tools.assistant_tools as AST
        with AST._REM_LOCK:
            items = AST._rem_load()
            rid = max((x["id"] for x in items), default=0) + 1
            items.append({"id": rid, "text": text, "due": time.time(),
                          "created": time.time()})
            AST._rem_save(items)
    except Exception:
        pass


def _push_exit_alert(symbol: str, curr: float, qty: int, pl_pct: float,
                     pl_abs: float, detail: str, jpos: dict):
    """Chat notification the moment JARVIS closes a position — reasoning +
    realized numbers up front, not just a silent log line. Matches the
    execute-side notification pushed by conviction.auto_hunt()/opportunity_scan."""
    try:
        held = ""
        entry_time = (jpos or {}).get("entry_time", "")
        if entry_time:
            mins = int((datetime.now() - datetime.fromisoformat(entry_time)).total_seconds() / 60)
            held = f"{mins//60}h{mins%60:02d}m" if mins >= 60 else f"{mins}m"
        msg = (f"📉 Sold {symbol} ${curr*qty:,.2f} ({pl_pct:+.1f}%) — {detail}."
               + (f" Held {held}." if held else "")
               + f" P&L: {pl_abs:+,.2f}")
        _push_user_alert(msg)
    except Exception:
        pass


def _exit_signal_scan(symbol, pos, jpos, curr, entry, qty, pl_pct):
    import tools.market as MKT
    st = _sig_state.setdefault(symbol, {})
    now = time.time()
    actions = []

    # Dashboard stop/TP params apply on every cycle (cheap, no data fetch)
    try:
        import tools.risk_params as RP
        p = RP.get_params()
    except Exception:
        p = {}
    stop_pct, tp_pct = float(p.get("stop_loss_pct", 7.5)), float(p.get("take_profit_pct", 22.0))
    if pl_pct <= -stop_pct:
        detail = f"Down {pl_pct:.1f}% — beyond your {stop_pct:.1f}% stop-loss setting"
        if _emergency_exit(symbol, qty, detail):
            _journal_adjustment(symbol, "param_stop_exit", detail)
            _push_exit_alert(symbol, curr, qty, pl_pct, float(pos.get("unrealized_pl", 0)), detail, jpos)
            return [detail]
    if pl_pct >= tp_pct and not jpos.get("param_tp_applied") and qty >= 2:
        sell_qty = max(1, qty // 2)
        if _partial_exit(symbol, sell_qty, f"+{pl_pct:.1f}% ≥ take-profit {tp_pct:.0f}%"):
            _move_stop_breakeven(symbol, entry, qty - sell_qty)
            j = _load_journal()
            if symbol in j["positions"]:
                j["positions"][symbol]["param_tp_applied"] = True
                j["positions"][symbol]["qty"] = qty - sell_qty
            _save_journal(j)
            actions.append(f"Take-profit {tp_pct:.0f}% hit: sold {sell_qty}, "
                           f"breakeven stop on the remaining {qty - sell_qty}")

    # The six-signal sweep runs at most every 5 minutes per position
    if now - st.get("last_scan", 0) < 300:
        return actions
    st["last_scan"] = now
    sigs = []

    # 1/2 — 15-min bars: 20MA cross + RSI exhaustion (>60 then <40)
    try:
        bars15 = MKT._fetch_intraday(symbol, "15Min", 40)
        closes = [b["close"] for b in bars15]
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            if curr < ma20:
                sigs.append(f"below 20MA on 15m (${ma20:.2f})")
        ta = MKT._compute_ta(bars15) if len(bars15) >= 15 else {}
        rsi = ta.get("rsi")
        if rsi is not None:
            if rsi > 60:
                st["rsi_was_high"] = True
            elif st.get("rsi_was_high") and rsi < 40:
                sigs.append(f"RSI exhaustion (was >60, now {rsi:.0f})")
    except Exception:
        pass

    # 3 — volume distribution: pace >40% below average while near the high
    try:
        daily = MKT._fetch_history(symbol, 25)
        if len(daily) >= 21:
            avg_vol = sum(b["volume"] for b in daily[-21:-1]) / 20
            today = daily[-1]
            hi = today.get("high") or curr
            near_high = curr >= hi * 0.98
            frac = min(1.0, max(0.15, (datetime.now().hour - 9.5 + datetime.now().minute / 60) / 6.5))
            if near_high and avg_vol and (today.get("volume", 0) / frac) < avg_vol * 0.6:
                sigs.append("volume drying up near highs (distribution)")
    except Exception:
        pass

    # 4 — sector rotation risk: this position's sector ETF down >2% today
    try:
        sector = st.get("sector")
        if sector is None:
            import yfinance as yf
            sector = (yf.Ticker(symbol).info or {}).get("sector", "") or ""
            st["sector"] = sector
        etf = _SECTOR_ETF.get(sector)
        if etf:
            q = MKT._fetch_quote(etf)
            if q.get("prev") and q.get("price"):
                etf_chg = (q["price"] - q["prev"]) / q["prev"] * 100
                if etf_chg <= -2.0:
                    sigs.append(f"sector rotation risk ({etf} {etf_chg:+.1f}%)")
    except Exception:
        pass

    # 5 — up >15% in a single session → partial exit (once per day)
    try:
        day_chg = float(pos.get("change_today", 0) or 0) * 100
        today_key = datetime.now().strftime("%Y-%m-%d")
        if day_chg >= 15 and st.get("partial15") != today_key:
            st["partial15"] = today_key
            sigs.append(f"+{day_chg:.1f}% in one session (blow-off risk)")
            if qty >= 2 and not jpos.get("param_tp_applied"):
                sell_qty = max(1, qty // 2)
                if _partial_exit(symbol, sell_qty, f"+{day_chg:.1f}% single-session spike"):
                    actions.append(f"Single-session +{day_chg:.1f}%: took 50% off ({sell_qty} shares)")
    except Exception:
        pass

    # 6 — news sentiment turned negative (checked at most every 15 min)
    try:
        if now - st.get("last_news", 0) > 900:
            st["last_news"] = now
            news = str(MKT.news_sentiment(symbol)).lower()
            st["news_neg"] = ("negative" in news or "bearish" in news)
        if st.get("news_neg"):
            sigs.append("news sentiment negative")
    except Exception:
        pass

    # ── Count-based action ──
    if len(sigs) == 1:
        _log(f"{symbol}: exit signal (1/3) — {sigs[0]} — holding", "WARN")
    elif len(sigs) == 2:
        msg = f"⚠ {symbol}: 2 exit signals — {' + '.join(sigs)} — prepared to exit on a third"
        _log(msg, "WARN")
        if st.get("alerted") != st["last_scan"]:
            st["alerted"] = st["last_scan"]
            _push_user_alert(msg)
        actions.append(msg)
    elif len(sigs) >= 3:
        detail = f"{len(sigs)} exit signals: {' + '.join(sigs)}"
        if _emergency_exit(symbol, qty, detail):
            _journal_adjustment(symbol, "multi_signal_exit", detail)
            _push_exit_alert(symbol, curr, qty, pl_pct, float(pos.get("unrealized_pl", 0)), detail, jpos)
            actions.append(detail)
    return actions

# ── Closed-position detection ─────────────────────────────────────────────────────
def _detect_closed_positions(current_syms: set, journal: dict):
    """
    Compare current open positions to journal.
    Any position in journal but NOT in current positions has been closed.
    Record the close and trigger a new hunt.
    """
    journal_syms = set(journal.get("positions", {}).keys())
    closed_syms  = journal_syms - current_syms

    for sym in closed_syms:
        jpos = journal["positions"][sym]
        entry = jpos.get("entry_price", 0)
        qty   = jpos.get("qty", 0)
        # Get the close price from recent filled orders
        exit_price = 0
        try:
            orders = _api("GET", f"/v2/orders?status=closed&limit=20&symbols={sym}")
            sells  = [o for o in orders if o.get("side") == "sell" and o.get("status") == "filled"]
            if sells:
                sells.sort(key=lambda o: o.get("filled_at",""), reverse=True)
                exit_price = float(sells[0].get("filled_avg_price", 0))
        except Exception:
            pass
        if not exit_price:
            # No filled sell found — approximate with the latest trade price
            # (jpos never carries pnl_pct, so the old target/stop guess always
            # picked stop_price and mislabeled winners as stop-outs).
            try:
                t = _data(f"/v2/stocks/{sym}/trades/latest")
                exit_price = float(t.get("trade", {}).get("p", 0)) or entry
            except Exception:
                exit_price = entry
        reason = "stop_loss" if exit_price < entry else "take_profit"
        _journal_close_position(sym, exit_price, qty, reason)
        _log(f"Detected closed: {sym} @ ${exit_price:.2f} via {reason}", "TRADE")
        # Trigger new hunt after a brief delay
        threading.Thread(target=_delayed_hunt, daemon=True).start()

def _delayed_hunt():
    """Wait 15s (just enough for the closing fill to settle/price to update)
    then hunt for the next trade — stocks first, then options if budget
    remains, so both instrument types stay in continuous rotation instead of
    options only running once a day via auto_trade_daily.py. Trade frequency
    is governed purely by conviction + capital gates downstream, not by this
    pause — it exists only to let the fill settle, not to throttle trading."""
    time.sleep(15)
    try:
        # Autonomous re-entry — the Markets-dashboard master switch gates it.
        try:
            import tools.risk_params as RP
            g_ok, g_why = RP.autonomy_gate()
            if not g_ok:
                _log(f"Post-close hunt skipped — {g_why}", "INFO")
                return
        except Exception:
            pass
        import tools.conviction as CVN
        import tools.trading as TRD
        budget_rem = TRD._budget_remaining()
        if budget_rem < 10:
            _log("Post-close hunt: insufficient budget remaining. Waiting.", "INFO")
            return
        _log(f"Post-close hunt: ${budget_rem:.2f} available — scanning universe...", "INFO")
        result = CVN.auto_hunt(auto_trade=True)
        _log("Post-close stock hunt complete:", "INFO")
        for line in result.split("\n")[:10]:
            if line.strip():
                _log(f"  {line.strip()}", "INFO")
    except Exception as e:
        _log(f"Post-close hunt error: {e}", "ERROR")
        return

    # Options — only if budget still supports at least one contract
    try:
        import tools.options_engine as OPT
        budget_rem = OPT._budget_remaining()
        if budget_rem >= 25:
            _log(f"Post-close options hunt: ${budget_rem:.2f} available...", "INFO")
            opts_result = OPT.options_auto_hunt()
            for line in opts_result.split("\n")[:10]:
                if line.strip():
                    _log(f"  {line.strip()}", "INFO")
        else:
            _log(f"Post-close options hunt skipped: only ${budget_rem:.2f} remaining (need >=$25)", "INFO")
    except Exception as e:
        _log(f"Post-close options hunt error: {e}", "ERROR")

# ── Dashboard writer ──────────────────────────────────────────────────────────────
def _write_dashboard(positions: list, journal: dict):
    """Write live JSON + human-readable dashboard."""
    now = datetime.now()
    try:
        # Current position values
        pos_data = []
        for p in positions:
            sym   = p["symbol"]
            curr  = float(p.get("current_price",   0))
            entry = float(p.get("avg_entry_price",  0))
            qty   = float(p.get("qty",              0))
            pl    = float(p.get("unrealized_pl",    0))
            plp   = float(p.get("unrealized_plpc",  0)) * 100
            mv    = float(p.get("market_value",     0))
            jpos  = journal.get("positions", {}).get(sym, {})
            pos_data.append({
                "symbol": sym, "qty": qty, "entry": entry, "current": curr,
                "market_value": mv, "pnl": pl, "pnl_pct": plp,
                "stop":   jpos.get("stop_price",   0),
                "target": jpos.get("target_price", 0),
                "conviction": jpos.get("conviction_score", 0),
                "be_stop": jpos.get("be_stop_applied", False),
                "trail":   jpos.get("trail_applied",   False),
                "entry_time": jpos.get("entry_time", ""),
            })

        closed = journal.get("closed_trades", [])
        wins   = [t for t in closed if t.get("result") == "WIN"]
        losses = [t for t in closed if t.get("result") == "LOSS"]
        total_pnl = sum(t.get("pnl", 0) for t in closed)
        open_pnl  = sum(float(p.get("unrealized_pl", 0)) for p in positions)

        # Live account values (the retired $100 mission math is gone)
        try:
            import tools.account_sync as SYNC
            acct = SYNC.account()
        except Exception:
            acct = {}
        equity = float(acct.get("equity", 0) or 0)
        bpow   = float(acct.get("buying_power", 0) or 0)
        goal_target, goal_pct = float(journal.get("mission", {}).get("goal", 0) or 0), 0.0
        try:
            import tools.goal_engine as GOAL
            gs = GOAL.goal_snapshot()
            if gs:
                goal_target = float(gs.get("target_value", 0) or goal_target)
                goal_pct    = float(gs.get("progress_pct", 0) or 0)
        except Exception:
            pass

        data = {
            "updated_at":    now.isoformat(),
            "market_open":   _is_market_open(),
            "positions":     pos_data,
            "closed_trades": closed[-20:],
            "stats": {
                "total_trades":  len(closed),
                "wins":          len(wins),
                "losses":        len(losses),
                "win_rate":      round(len(wins) / len(closed) * 100, 1) if closed else 0,
                "total_realized_pnl": round(total_pnl, 2),
                "open_pnl":     round(open_pnl, 2),
                "est_capital":  round(equity, 2),
                "progress_pct": round(goal_pct, 2),
                "budget":       round(bpow, 2),
                "goal":         goal_target,
                "budget_remaining": round(bpow, 2),
            },
            "recent_events": _events_buffer[-20:],
        }
        _DASHBOARD_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        _write_report(data)
    except Exception as e:
        _log(f"Dashboard write error: {e}", "ERROR")

def _write_report(data: dict):
    """Write a human-readable trade report."""
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s     = data.get("stats", {})
    goal_line = (f"  Goal Progress:   {s.get('progress_pct',0):>+.2f}% toward ${s.get('goal',0):,.0f}"
                 if s.get("goal") else "  Goal:            none set — say e.g. 'turn 100k into 150k by August'")
    lines = [
        "=" * 70,
        f"  JARVIS TRADING REPORT — live Alpaca capital",
        f"  Updated: {now}  |  Market: {'OPEN' if data.get('market_open') else 'CLOSED'}",
        "=" * 70,
        "",
        f"  Portfolio Value: ${s.get('est_capital',0):>12,.2f}",
        f"  Buying Power:    ${s.get('budget_remaining',0):>12,.2f}",
        f"  Realized P&L:    ${s.get('total_realized_pnl',0):>+12,.2f}",
        f"  Open P&L:        ${s.get('open_pnl',0):>+12,.2f}",
        goal_line,
        "",
    ]
    if data.get("positions"):
        lines += ["  ── OPEN POSITIONS ───────────────────────────────────────────────", ""]
        for p in data["positions"]:
            be_tag  = " [BE]"  if p.get("be_stop")  else ""
            tr_tag  = " [TRAIL]" if p.get("trail")  else ""
            dur_min = 0
            try:
                if p.get("entry_time"):
                    dur_min = int((datetime.now() - datetime.fromisoformat(p["entry_time"])).total_seconds() / 60)
            except Exception:
                pass
            dur_str = f"{dur_min//60}h{dur_min%60:02d}m" if dur_min >= 60 else f"{dur_min}m"
            arrow   = "▲" if p["pnl"] >= 0 else "▼"
            lines.append(
                f"  {p['symbol']:<6}  {p['qty']:>4.0f}sh  "
                f"entry:${p['entry']:.2f} → ${p['current']:.2f}  "
                f"{arrow}${abs(p['pnl']):.2f} ({p['pnl_pct']:+.1f}%)"
                f"  held:{dur_str}{be_tag}{tr_tag}"
            )
            if p.get("stop"):
                lines.append(
                    f"         stop:${p['stop']:.2f}  "
                    f"target:${p['target']:.2f}  "
                    f"conviction:{p['conviction']}/100"
                )
        lines.append("")
    closed = data.get("closed_trades", [])
    if closed:
        lines += ["  ── TRADE HISTORY ────────────────────────────────────────────────", ""]
        for t in reversed(closed[-15:]):
            dur  = t.get("duration_minutes", 0)
            dur_str = f"{dur//60}h{dur%60:02d}m" if dur >= 60 else f"{dur}m"
            arrow= "▲" if t.get("pnl", 0) >= 0 else "▼"
            tag  = "WIN " if t.get("result") == "WIN" else "LOSS"
            lines.append(
                f"  [{tag}] {t.get('symbol','?'):<6}  "
                f"${t.get('entry_price',0):.2f}→${t.get('exit_price',0):.2f}  "
                f"{arrow}${abs(t.get('pnl',0)):.2f} ({t.get('pnl_pct',0):+.1f}%)  "
                f"held:{dur_str}  {t.get('reason','')}"
            )
        lines += [
            "",
            f"  Trades: {s.get('total_trades',0)}  "
            f"Wins: {s.get('wins',0)}  "
            f"Losses: {s.get('losses',0)}  "
            f"Win Rate: {s.get('win_rate',0):.0f}%",
        ]
    if data.get("recent_events"):
        lines += ["", "  ── RECENT ACTIVITY ─────────────────────────────────────────────"]
        for e in data["recent_events"][-10:]:
            if e.get("level") in ("TRADE", "ADJUST", "ERROR"):
                lines.append(f"  [{e['time'][11:16]}] {e['msg']}")
    lines += ["", "=" * 70]
    try:
        _REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass

# ── Main monitor loop ─────────────────────────────────────────────────────────────
def _monitor_loop():
    global _last_positions, _last_check_time, _monitor_running
    _log(f"Monitor started — checking positions every {_check_interval} seconds", "INFO")
    consecutive_errors = 0
    while _monitor_running:
        try:
            configured = bool(_cfg("ALPACA_API_KEY") and _cfg("ALPACA_API_SECRET"))
            if not configured:
                time.sleep(60)
                continue

            positions = _get_positions()
            _last_check_time = datetime.now()
            journal   = _load_journal()
            current_syms = {p["symbol"] for p in positions}

            # ── Keep open positions on the live real-time trade tape ──────────
            # Priority = never trimmed from the stream's symbol cap, so a
            # held position always has fresh tick data for Rule 6 below.
            try:
                import tools.trade_stream as TAPE
                TAPE.update_watchlist(list(current_syms), priority=list(current_syms))
            except Exception:
                pass

            # ── Detect closed trades ─────────────────────────────────────────
            _detect_closed_positions(current_syms, journal)
            journal = _load_journal()  # reload after potential mutations

            # ── Sync journal with current positions ──────────────────────────
            for p in positions:
                sym = p["symbol"]
                if sym not in journal["positions"]:
                    # Position opened outside of auto_hunt — register it
                    entry = float(p.get("avg_entry_price", 0))
                    qty   = float(p.get("qty", 0))
                    _journal_open_position(
                        sym, qty, entry,
                        stop_price   = round(entry * 0.925, 2),
                        target_price = round(entry * 1.225, 2),
                        conviction   = 0,
                    )
                    journal = _load_journal()

            # ── Apply adjustment rules (only when market is open) ────────────
            if _is_market_open():
                for pos in positions:
                    sym = pos["symbol"]
                    actions = _check_position(pos, journal.get("positions", {}))
                    for action in actions:
                        _log(f"{sym}: {action}", "ADJUST")
            else:
                # Market closed — just log a heartbeat every 10 cycles
                pass

            # ── Write dashboard ──────────────────────────────────────────────
            _write_dashboard(positions, journal)
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            _log(f"Monitor error ({consecutive_errors}): {e}", "ERROR")
            if consecutive_errors >= 5:
                _log("5 consecutive errors — backing off 5 min", "WARN")
                time.sleep(300)
                consecutive_errors = 0

        # Sleep until next check
        time.sleep(_check_interval)

    _log("Monitor stopped", "INFO")

# ── Public API ────────────────────────────────────────────────────────────────────
def start_monitor() -> str:
    global _monitor_thread, _monitor_running
    if _monitor_running and _monitor_thread and _monitor_thread.is_alive():
        return "Monitor already running."
    _monitor_running = True
    _monitor_thread  = threading.Thread(target=_monitor_loop, daemon=True, name="jarvis-monitor")
    _monitor_thread.start()
    return f"Trade monitor started — watching positions every {_check_interval} seconds."

def stop_monitor() -> str:
    global _monitor_running
    _monitor_running = False
    return "Trade monitor stopping (completes current cycle)."

def monitor_status() -> str:
    """Show monitor status and last 15 events."""
    global _last_check_time, _monitor_running, _monitor_thread
    alive  = bool(_monitor_thread and _monitor_thread.is_alive())
    status = "RUNNING" if alive else "STOPPED"
    last   = _last_check_time.strftime("%H:%M:%S") if _last_check_time else "never"
    lines  = [
        f"Trade Monitor: {status}",
        f"  Last check: {last}",
        f"  Interval:   {_check_interval}s",
        f"  Log:        {_LOG_FILE}",
        f"  Dashboard:  {_DASHBOARD_FILE}",
        f"  Report:     {_REPORT_FILE}",
        "",
        "  Recent events:",
    ]
    for e in _events_buffer[-15:]:
        if e.get("level") in ("TRADE", "ADJUST", "ERROR", "INFO"):
            lines.append(f"    [{e['time'][11:16]}] [{e['level']:<6}] {e['msg']}")
    return "\n".join(lines)

def portfolio_dashboard() -> str:
    """
    Full mission portfolio view — positions, trade history, stats, P&L curve.
    Can be read any time without prompting (also auto-updated every 60s by monitor).
    """
    try:
        if _DASHBOARD_FILE.exists():
            data = json.loads(_DASHBOARD_FILE.read_text(encoding="utf-8"))
            updated = data.get("updated_at", "?")[:19].replace("T", " ")
            stale   = ""
            try:
                age_s = (datetime.now() - datetime.fromisoformat(data["updated_at"])).total_seconds()
                if age_s > 300:
                    stale = f" ⚠ (stale — {int(age_s//60)}m ago, monitor may be off)"
            except Exception:
                pass
        else:
            # No dashboard file yet — generate live
            positions = _get_positions()
            journal   = _load_journal()
            _write_dashboard(positions, journal)
            data    = json.loads(_DASHBOARD_FILE.read_text(encoding="utf-8"))
            updated = "just now"
            stale   = ""

        # Read the pre-rendered report
        if _REPORT_FILE.exists():
            report = _REPORT_FILE.read_text(encoding="utf-8")
            return report + f"\n  [Data as of {updated}{stale}]"

        # Fallback: render from JSON
        s   = data.get("stats", {})
        pos = data.get("positions", [])
        lines = [
            f"JARVIS PORTFOLIO  [{updated}{stale}]",
            f"  Portfolio Value: ${s.get('est_capital',0):,.2f}"
            + (f"  |  Goal: {s.get('progress_pct',0):+.2f}% toward ${s.get('goal',0):,.0f}"
               if s.get("goal") else ""),
        ]
        for p in pos:
            arrow = "▲" if p["pnl"] >= 0 else "▼"
            lines.append(
                f"  {p['symbol']:<6}  {p['qty']:>4.0f}sh @ ${p['entry']:.2f}"
                f"  now:${p['current']:.2f}  {arrow}{abs(p['pnl_pct']):.1f}%"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Portfolio error: {e}"


def portfolio_live_data() -> dict:
    """
    Raw structured dashboard data for the web UI's live portfolio tracker.
    Same underlying data as portfolio_dashboard(), just JSON instead of text.
    Generates on-demand if the 60s monitor hasn't written a dashboard yet.
    """
    try:
        if not _DASHBOARD_FILE.exists():
            _write_dashboard(_get_positions(), _load_journal())
        data = json.loads(_DASHBOARD_FILE.read_text(encoding="utf-8"))
        try:
            age_s = (datetime.now() - datetime.fromisoformat(data["updated_at"])).total_seconds()
            data["stale"] = age_s > 300
            data["age_seconds"] = int(age_s)
        except Exception:
            data["stale"] = False
            data["age_seconds"] = 0
        mode = "LIVE" if "paper" not in _cfg("ALPACA_BASE_URL", "paper").lower() else "PAPER"
        data["account_mode"] = mode
        data["monitor_running"] = bool(_monitor_thread and _monitor_thread.is_alive())
        return data
    except Exception as e:
        return {"error": str(e)}

def register_trade(symbol: str, qty: float, entry_price: float,
                   stop_price: float, target_price: float, conviction: int = 0,
                   reasoning: str = ""):
    """Called by auto_hunt after placing an order to register it in the journal."""
    _journal_open_position(symbol, qty, entry_price, stop_price, target_price,
                          conviction, reasoning)
    _log(
        f"Trade opened: {symbol} × {qty} @ ${entry_price:.2f} "
        f"| stop:${stop_price:.2f} target:${target_price:.2f} conviction:{conviction}/100",
        "TRADE"
    )


def trade_reasoning(symbol: str) -> str:
    """
    Why did Jarvis make this trade? Looks up the stored signal breakdown from
    the moment the trade was placed — not a fresh recompute, which would drift
    from what was actually true when the decision was made.
    """
    sym = symbol.upper().strip()
    j   = _load_journal()

    pos = j.get("positions", {}).get(sym)
    if pos:
        reasoning = pos.get("reasoning", "")
        header = (
            f"Why {sym} — OPEN position\n"
            f"  Entered: {pos.get('entry_time','?')[:16].replace('T',' ')}  "
            f"@ ${pos.get('entry_price',0):.2f}  ×{pos.get('qty',0)}\n"
            f"  Conviction at entry: {pos.get('conviction_score',0)}/100\n"
        )
        if not reasoning:
            return header + "\n  (No stored rationale — this position was opened outside auto_hunt, e.g. a manual buy.)"
        return header + "\n" + reasoning

    closed = [t for t in j.get("closed_trades", []) if t.get("symbol") == sym]
    if closed:
        t = closed[-1]  # most recent
        reasoning = t.get("reasoning", "")
        header = (
            f"Why {sym} — CLOSED trade ({t.get('result','?')})\n"
            f"  {t.get('entry_time','?')[:16].replace('T',' ')} → {t.get('exit_time','?')[:16].replace('T',' ')}\n"
            f"  ${t.get('entry_price',0):.2f} → ${t.get('exit_price',0):.2f}  "
            f"P&L ${t.get('pnl',0):+.2f} ({t.get('pnl_pct',0):+.1f}%)\n"
            f"  Conviction at entry: {t.get('conviction_score',0)}/100  |  Exit reason: {t.get('reason','?')}\n"
        )
        if not reasoning:
            return header + "\n  (No stored rationale — this position was opened outside auto_hunt, e.g. a manual buy.)"
        return header + "\n" + reasoning

    return f"No record of a {sym} trade in the journal (open or closed)."


# ── Journal queries: by result / by date / by reason / full history ──────────
def _parse_date_query(text: str):
    """Best-effort parse of a date phrase ('July 21', '7/21', 'yesterday',
    'today', '2026-07-21') into a date object. Returns None if unparseable."""
    from datetime import date as _date
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in ("today",):
        return datetime.now().date()
    if t in ("yesterday",):
        return (datetime.now() - timedelta(days=1)).date()
    months = {m.lower(): i for i, m in enumerate(
        ["", "january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"]) if m}
    for name, num in months.items():
        if name in t or name[:3] in t:
            nums = re.findall(r'\d+', t)
            if nums:
                day = int(nums[0])
                year = int(nums[1]) if len(nums) > 1 and len(nums[1]) == 4 else datetime.now().year
                try:
                    return _date(year, num, day)
                except Exception:
                    return None
    try:
        return datetime.fromisoformat(t).date()
    except Exception:
        pass
    m = re.match(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$', t)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        year = datetime.now().year if not yr else (2000 + int(yr) if len(yr) == 2 else int(yr))
        try:
            return _date(year, mo, da)
        except Exception:
            return None
    return None


def _all_trades(j: dict) -> list:
    """Closed trades + open positions normalized into one flat list for
    filtering, each tagged with its status."""
    out = []
    for t in j.get("closed_trades", []):
        row = dict(t); row["status"] = "CLOSED"
        out.append(row)
    for sym, p in j.get("positions", {}).items():
        row = dict(p); row["status"] = "OPEN"; row.setdefault("symbol", sym)
        out.append(row)
    return out


def _fmt_trade_row(t: dict) -> str:
    sym = t.get("symbol", "?")
    if t.get("status") == "OPEN":
        return (f"  [OPEN]  {sym:<6}  entry ${t.get('entry_price', 0):.2f}  "
                f"×{t.get('qty', 0)}  conviction {t.get('conviction_score', 0)}/100  "
                f"since {t.get('entry_time', '?')[:10]}")
    arrow = "▲" if t.get("pnl", 0) >= 0 else "▼"
    return (f"  [{t.get('result', '?'):<4}] {sym:<6}  "
            f"${t.get('entry_price', 0):.2f}→${t.get('exit_price', 0):.2f}  "
            f"{arrow}${abs(t.get('pnl', 0)):.2f} ({t.get('pnl_pct', 0):+.1f}%)  "
            f"{t.get('exit_time', '?')[:10]}  {t.get('reason', '')}")


def trades_by_result(result: str) -> str:
    """'show me my losing trades' / 'winning trades' — filters closed trades
    by outcome. Open positions have no result yet, so they're excluded."""
    want = (result or "").strip().upper()
    if want in ("LOSING", "LOSS", "LOSSES", "LOSERS"):
        want = "LOSS"
    elif want in ("WINNING", "WIN", "WINS", "WINNERS"):
        want = "WIN"
    j = _load_journal()
    hits = [t for t in j.get("closed_trades", []) if t.get("result") == want]
    if not hits:
        return f"No {want.lower()} trades in the journal yet."
    lines = [f"{want.title()} Trades ({len(hits)})", ""]
    lines += [_fmt_trade_row({**t, "status": "CLOSED"}) for t in reversed(hits)]
    return "\n".join(lines)


def trades_by_date(date_query: str) -> str:
    """'what did you trade on July 21' — trades entered or exited on that day."""
    d = _parse_date_query(date_query)
    if d is None:
        return f"Couldn't parse a date from '{date_query}' — try 'July 21' or '2026-07-21'."
    j = _load_journal()
    hits = []
    for t in _all_trades(j):
        for key in ("entry_time", "exit_time"):
            ts = t.get(key, "")
            if ts and ts[:10] == d.isoformat():
                hits.append(t)
                break
    if not hits:
        return f"No trades on {d.isoformat()}."
    lines = [f"Trades on {d.isoformat()} ({len(hits)})", ""]
    lines += [_fmt_trade_row(t) for t in hits]
    return "\n".join(lines)


def trades_by_reason(keyword: str) -> str:
    """'show trades based on chart patterns' — searches the stored reasoning
    text (open + closed) for a keyword/phrase."""
    kw = (keyword or "").strip().lower()
    if not kw:
        return "Give me a keyword to search for, e.g. 'trades based on chart patterns'."
    j = _load_journal()
    hits = [t for t in _all_trades(j) if kw in (t.get("reasoning", "") or "").lower()]
    if not hits:
        return f"No trades found with '{keyword}' in the stored reasoning."
    lines = [f"Trades matching '{keyword}' ({len(hits)})", ""]
    lines += [_fmt_trade_row(t) for t in hits]
    return "\n".join(lines)


def trade_history_full() -> str:
    """'show full trading history' — every closed trade + open position, not
    just the dashboard's trailing-15 window."""
    j = _load_journal()
    closed = j.get("closed_trades", [])
    positions = j.get("positions", {})
    wins = sum(1 for t in closed if t.get("result") == "WIN")
    losses = sum(1 for t in closed if t.get("result") == "LOSS")
    total_pnl = sum(t.get("pnl", 0) for t in closed)
    lines = [
        f"Full Trading History — {len(closed)} closed, {len(positions)} open",
        f"  Wins: {wins}  Losses: {losses}  "
        f"Win rate: {wins/max(wins+losses,1)*100:.0f}%  Total realized P&L: ${total_pnl:+,.2f}",
        "",
    ]
    if positions:
        lines.append("  ── OPEN ──")
        lines += [_fmt_trade_row({**p, "status": "OPEN"}) for p in positions.values()]
        lines.append("")
    if closed:
        lines.append("  ── CLOSED (most recent first) ──")
        lines += [_fmt_trade_row({**t, "status": "CLOSED"}) for t in reversed(closed)]
    return "\n".join(lines)
