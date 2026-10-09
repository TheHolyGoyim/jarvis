"""
trading.py  —  JARVIS Live Trading Engine v2.0
Full Alpaca Markets integration: paper and live trading, real-time market data,
advanced order types, position management, risk controls, and automated strategies.

Configure in .env:
  ALPACA_API_KEY     = your-api-key-id
  ALPACA_API_SECRET  = your-secret-key
  ALPACA_BASE_URL    = https://paper-api.alpaca.markets   (paper — default & safe)
                     = https://api.alpaca.markets          (LIVE — real money)
  TRADING_MODE       = paper                               (paper | live)

Capital constraints come from LIVE Alpaca buying power (tools/account_sync.py)
plus the Markets-dashboard risk parameters (tools/risk_params.py, % based).
The old TRADING_BUDGET / DAILY_LOSS_LIMIT / MAX_POSITIONS env caps are retired.
"""

import os, json, math, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Storage ────────────────────────────────────────────────────────────────────
_DATA_DIR = Path.home() / "Documents" / "JARVIS" / "trading"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

def _load(f: Path, default=None):
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}

def _save(f: Path, data):
    try:
        f.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

# ── Config ─────────────────────────────────────────────────────────────────────
def _cfg(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def _is_live() -> bool:
    return "paper" not in _cfg("ALPACA_BASE_URL", "paper").lower()

def _mode() -> str:
    return "LIVE" if _is_live() else "PAPER"

def _configured() -> bool:
    return bool(_cfg("ALPACA_API_KEY") and _cfg("ALPACA_API_SECRET"))

# ── API helpers ────────────────────────────────────────────────────────────────
def _api(method: str, path: str, body: dict = None) -> dict:
    """Alpaca broker API (trading operations)."""
    key    = _cfg("ALPACA_API_KEY")
    secret = _cfg("ALPACA_API_SECRET")
    base   = _cfg("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key or not secret:
        raise ValueError(
            "Alpaca not configured.\n"
            "Add to your .env:\n"
            "  ALPACA_API_KEY=your-key\n"
            "  ALPACA_API_SECRET=your-secret\n"
            "  ALPACA_BASE_URL=https://paper-api.alpaca.markets\n"
            "Get free keys at https://alpaca.markets (paper trading is free)"
        )
    import requests
    hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
            "Content-Type": "application/json"}
    url  = base.rstrip("/") + path
    r    = requests.request(method, url, headers=hdrs, json=body, timeout=12)
    if not r.ok:
        try:
            msg = r.json().get("message", r.text[:300])
        except Exception:
            msg = r.text[:300]
        raise ValueError(f"Alpaca {method} {path} → {r.status_code}: {msg}")
    return r.json() if r.content else {}

def _data(path: str, params: dict = None) -> dict:
    """Alpaca market data API (real-time and historical quotes/bars)."""
    key    = _cfg("ALPACA_API_KEY")
    secret = _cfg("ALPACA_API_SECRET")
    if not key or not secret:
        raise ValueError("Alpaca not configured. See ALPACA_API_KEY in .env")
    import requests
    hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    r    = requests.get(f"https://data.alpaca.markets{path}",
                        headers=hdrs, params=params, timeout=12)
    if not r.ok:
        raise ValueError(f"Data API {path} → {r.status_code}: {r.text[:200]}")
    return r.json()

# ── Risk guard (called before every order) ─────────────────────────────────────
def _guard(symbol: str = "") -> tuple:
    """Returns (ok: bool, reason: str). Blocks trades when limits are hit.
    Reads the Markets-dashboard risk params (tools/risk_params.py) on EVERY
    order: blocked tickers + daily-loss pause. Capital is constrained ONLY by
    live Alpaca buying power (tools/account_sync.py) — the old $100
    TRADING_BUDGET hard cap is retired. No hardcoded figure blocks trades."""
    if not _configured():
        return False, "Alpaca not configured. Add API keys to .env"
    try:
        import tools.risk_params as RP
        ok, reason = RP.order_gate(symbol)
        if not ok:
            return False, reason
    except Exception:
        pass
    # No position-count limit — the only constraint is CAPITAL: live buying
    # power minus the min-cash-reserve, respected by _budget_remaining() when
    # sizing. Every position is monitored for exit.
    try:
        import tools.account_sync as SYNC
        if SYNC.buying_power() <= 0:
            return False, "No buying power available (live Alpaca account)."
    except Exception:
        pass   # never block on a data hiccup — Alpaca itself rejects if truly out
    return True, "OK"


def _budget_remaining() -> float:
    """Capital available to deploy RIGHT NOW: live Alpaca buying_power
    (GET /v2/account) minus the Markets-dashboard cash-reserve holdback.
    When the API is unreachable this falls back to the LAST KNOWN synced
    buying power from store.py — never to a hardcoded budget figure.
    (Name kept from the retired $100-budget era: every sizing path in the
    pipeline calls this.)"""
    bp = 0.0
    try:
        import tools.account_sync as SYNC
        bp = SYNC.buying_power()          # live, with store.py fallback inside
    except Exception:
        pass
    if bp <= 0:
        try:
            acct = _api("GET", "/v2/account")
            bp = float(acct.get("buying_power", 0) or 0)
        except Exception:
            return 0.0
    reserve_pct = 0.0
    try:
        import tools.risk_params as RP
        reserve_pct = float(RP.get_params().get("min_cash_reserve_pct", 0))
    except Exception:
        pass
    return max(0.0, bp * (1 - reserve_pct / 100.0))

# ══════════════════════════════════════════════════════════════════════════════
# MARKET STATUS
# ══════════════════════════════════════════════════════════════════════════════

def market_clock() -> str:
    """Is the NYSE/NASDAQ market open right now? Next open/close times."""
    try:
        clk      = _api("GET", "/v2/clock")
        is_open  = clk.get("is_open", False)
        nxt_open = clk.get("next_open",  "")
        nxt_close = clk.get("next_close", "")
        status   = "OPEN" if is_open else "CLOSED"
        lines    = [f"Market Status: {status}  ({datetime.now().strftime('%I:%M %p')})"]
        if is_open and nxt_close:
            ts   = datetime.fromisoformat(nxt_close[:19])
            diff = ts - datetime.utcnow()
            h, r = divmod(int(diff.total_seconds()), 3600)
            lines.append(f"  Closes in:  {h}h {r//60}m  ({nxt_close[11:16]} ET)")
        elif not is_open and nxt_open:
            lines.append(f"  Opens at:   {nxt_open[11:16]} ET  ({nxt_open[:10]})")
        lines.append(f"  Mode: [{_mode()}]")
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Clock error: {e}"

def _is_open() -> bool:
    try:
        return _api("GET", "/v2/clock").get("is_open", False)
    except Exception:
        return False

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT & PORTFOLIO
# ══════════════════════════════════════════════════════════════════════════════

def trading_account() -> str:
    """Full account summary: equity, cash, buying power, day P/L, PDT status."""
    try:
        a      = _api("GET", "/v2/account")
        eq     = float(a.get("equity",        0))
        cash   = float(a.get("cash",           0))
        bpow   = float(a.get("buying_power",   0))
        last   = float(a.get("last_equity",    0))
        day_pl = eq - last
        day_pct = (day_pl / last * 100) if last else 0
        dt_cnt = a.get("daytrade_count", 0)
        pdt    = a.get("pattern_day_trader", False)
        arrow  = "▲" if day_pl >= 0 else "▼"
        return "\n".join([
            f"Trading Account  [{_mode()}]",
            f"  Portfolio Value: ${eq:>12,.2f}",
            f"  Cash:            ${cash:>12,.2f}",
            f"  Buying Power:    ${bpow:>12,.2f}",
            f"  Day P/L:         {arrow}${abs(day_pl):>11,.2f}  ({day_pct:+.2f}%)",
            f"  Day Trades Used: {dt_cnt}/3",
            f"  PDT Restricted:  {'YES ⚠' if pdt else 'No'}",
            f"  Account Status:  {a.get('status','N/A').upper()}",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Account error: {e}"

def trading_positions() -> str:
    """All open positions with current price, P/L, and portfolio weight."""
    try:
        positions = _api("GET", "/v2/positions")
        if not positions:
            return f"No open positions  [{_mode()}]."
        try:
            acct = _api("GET", "/v2/account")
            port = float(acct.get("portfolio_value", 1)) or 1
        except Exception:
            port = 1
        lines     = [f"Open Positions  [{_mode()}]  —  {len(positions)} position(s)", ""]
        total_pl  = 0
        for p in sorted(positions, key=lambda x: -abs(float(x.get("unrealized_pl", 0)))):
            sym   = p["symbol"]
            qty   = float(p["qty"])
            entry = float(p["avg_entry_price"])
            curr  = float(p["current_price"])
            pl    = float(p.get("unrealized_pl",   0))
            plp   = float(p.get("unrealized_plpc", 0)) * 100
            mval  = float(p.get("market_value",    0))
            side  = p.get("side", "long").upper()
            wt    = mval / port * 100
            total_pl += pl
            arrow = "▲" if pl >= 0 else "▼"
            lines.append(
                f"  {sym:<6}  {side:<5}  {qty:>7.0f}sh"
                f"  Entry:${entry:,.2f} → ${curr:,.2f}"
                f"  {arrow}${abs(pl):,.2f} ({plp:+.1f}%)"
                f"  Wt:{wt:.1f}%"
            )
        lines += ["", f"  Total Unrealized P/L: ${total_pl:+,.2f}"]
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Positions error: {e}"

def trading_pnl_today() -> str:
    """Today's realized and unrealized P/L breakdown."""
    try:
        a      = _api("GET", "/v2/account")
        eq     = float(a.get("equity",      0))
        last   = float(a.get("last_equity", 0))
        day_pl = eq - last
        day_pct = (day_pl / last * 100) if last else 0
        try:
            positions = _api("GET", "/v2/positions")
            unreal    = sum(float(p.get("unrealized_pl", 0)) for p in positions)
        except Exception:
            unreal = 0
        realized = day_pl - unreal
        arrow    = "▲" if day_pl >= 0 else "▼"
        return "\n".join([
            f"Today's P/L  [{_mode()}]  {datetime.now().strftime('%b %d, %Y')}",
            f"  Total Day P/L:  {arrow}${abs(day_pl):>10,.2f}  ({day_pct:+.2f}%)",
            f"  Unrealized:      ${unreal:>+10,.2f}",
            f"  Realized:        ${realized:>+10,.2f}",
            f"  Start of Day:   ${last:>10,.2f}",
            f"  Current Equity: ${eq:>10,.2f}",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"P/L error: {e}"

def trading_orders(status: str = "open") -> str:
    """List orders by status: open | closed | all."""
    try:
        orders = _api("GET", f"/v2/orders?status={status}&limit=25")
        if not orders:
            return f"No {status} orders  [{_mode()}]."
        lines = [f"Orders [{status.upper()}]  [{_mode()}]", ""]
        for o in orders[:20]:
            sym   = o.get("symbol", "?")
            side  = o.get("side",   "?").upper()
            qty   = o.get("qty",    "?")
            otype = o.get("type",   "?")
            stat  = o.get("status", "?")
            lp    = f" @${float(o['limit_price']):,.2f}"  if o.get("limit_price") else ""
            sp    = f" stop:${float(o['stop_price']):,.2f}" if o.get("stop_price") else ""
            oid   = o.get("id", "")[:8]
            lines.append(f"  [{oid}] {side} {qty} {sym}  {otype}{lp}{sp}  → {stat.upper()}")
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Orders error: {e}"

def trading_history(days: int = 7) -> str:
    """Recent filled orders."""
    try:
        after  = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        orders = _api("GET", f"/v2/orders?status=closed&limit=100&after={after}")
        filled = [o for o in orders if o.get("status") == "filled"]
        if not filled:
            return f"No filled orders in last {days} days  [{_mode()}]."
        lines = [f"Trade History — Last {days} Days  [{_mode()}]", ""]
        for o in filled[-25:]:
            sym  = o.get("symbol", "?")
            side = o.get("side",   "?").upper()
            qty  = float(o.get("filled_qty",       0))
            fp   = float(o.get("filled_avg_price", 0))
            val  = qty * fp
            ts   = o.get("filled_at", "")[:16].replace("T", " ")
            lines.append(
                f"  {ts}  {side:<4}  {qty:>5.0f} {sym:<6}"
                f"  @${fp:>9,.2f}  = ${val:>10,.2f}"
            )
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"History error: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

def trading_buy(symbol: str, qty: float = None, notional: float = None,
                order_type: str = "market", limit_price: float = None,
                stop_price: float = None, tif: str = "day",
                extended_hours: bool = False) -> str:
    """
    Buy shares or a dollar amount.
    order_type: market | limit | stop | stop_limit
    """
    symbol = symbol.upper().strip()
    ok, reason = _guard(symbol)
    if not ok:
        return f"Trade blocked: {reason}"
    if qty is None and notional is None:
        return "Specify qty (number of shares) or notional (dollar amount)."
    body: dict = {"symbol": symbol, "side": "buy", "type": order_type,
                  "time_in_force": tif}
    if qty is not None:
        body["qty"] = str(int(qty)) if qty == int(qty) else str(qty)
    else:
        body["notional"] = f"{float(notional):.2f}"
    if order_type in ("limit", "stop_limit") and limit_price:
        body["limit_price"] = f"{float(limit_price):.2f}"
    if order_type in ("stop", "stop_limit") and stop_price:
        body["stop_price"] = f"{float(stop_price):.2f}"
    if extended_hours:
        body["extended_hours"] = True
        body["time_in_force"]  = "day"
    try:
        r       = _api("POST", "/v2/orders", body)
        qty_str = f"{qty} shares" if qty is not None else f"${notional:,.2f}"
        lp_str  = f" @${float(limit_price):,.2f}" if limit_price else ""
        return (f"✅ [{_mode()}] BUY ORDER PLACED\n"
                f"  Symbol: {symbol}   Qty: {qty_str}{lp_str}\n"
                f"  Type:   {order_type.upper()}   TIF: {tif.upper()}\n"
                f"  ID:     {r.get('id','?')[:8]}   Status: {r.get('status','?').upper()}")
    except ValueError as e:
        return f"Order failed: {e}"
    except Exception as e:
        return f"Order error: {e}"

def trading_sell(symbol: str, qty: float = None, notional: float = None,
                 order_type: str = "market", limit_price: float = None,
                 stop_price: float = None, tif: str = "day",
                 extended_hours: bool = False) -> str:
    """
    Sell shares or a dollar amount.
    order_type: market | limit | stop | stop_limit
    """
    symbol = symbol.upper().strip()
    ok, reason = _guard(symbol)
    if not ok:
        return f"Trade blocked: {reason}"
    if qty is None and notional is None:
        return "Specify qty (number of shares) or notional (dollar amount)."
    body: dict = {"symbol": symbol, "side": "sell", "type": order_type,
                  "time_in_force": tif}
    if qty is not None:
        body["qty"] = str(int(qty)) if qty == int(qty) else str(qty)
    else:
        body["notional"] = f"{float(notional):.2f}"
    if order_type in ("limit", "stop_limit") and limit_price:
        body["limit_price"] = f"{float(limit_price):.2f}"
    if order_type in ("stop", "stop_limit") and stop_price:
        body["stop_price"] = f"{float(stop_price):.2f}"
    if extended_hours:
        body["extended_hours"] = True
    try:
        r       = _api("POST", "/v2/orders", body)
        qty_str = f"{qty} shares" if qty is not None else f"${notional:,.2f}"
        lp_str  = f" @${float(limit_price):,.2f}" if limit_price else ""
        return (f"✅ [{_mode()}] SELL ORDER PLACED\n"
                f"  Symbol: {symbol}   Qty: {qty_str}{lp_str}\n"
                f"  Type:   {order_type.upper()}   TIF: {tif.upper()}\n"
                f"  ID:     {r.get('id','?')[:8]}   Status: {r.get('status','?').upper()}")
    except ValueError as e:
        return f"Order failed: {e}"
    except Exception as e:
        return f"Order error: {e}"

def trading_bracket(symbol: str, qty: float, stop_loss_pct: float = 2.0,
                    take_profit_pct: float = 4.0, entry_type: str = "market",
                    limit_price: float = None) -> str:
    """
    Bracket order: entry + automatic stop-loss + take-profit in one shot.
    stop_loss_pct:   % below entry (default 2%)
    take_profit_pct: % above entry (default 4%)  → R/R = 2:1
    """
    symbol = symbol.upper().strip()
    ok, reason = _guard(symbol)
    if not ok:
        return f"Trade blocked: {reason}"
    # Fetch live price to calculate exact levels
    try:
        snap   = _data(f"/v2/stocks/{symbol}/quotes/latest")
        ask    = float(snap.get("quote", {}).get("ap", 0))
        if ask == 0:
            bar = _data(f"/v2/stocks/{symbol}/bars/latest")
            ask = float(bar.get("bar", {}).get("c", 0))
        entry_p = float(limit_price) if limit_price else ask
        if entry_p == 0:
            return f"Could not get current price for {symbol}."
    except Exception as e:
        return f"Price fetch failed: {e}"
    stop_p   = round(entry_p * (1 - stop_loss_pct   / 100), 2)
    target_p = round(entry_p * (1 + take_profit_pct / 100), 2)
    rr       = round(take_profit_pct / stop_loss_pct, 2)
    body: dict = {
        "symbol":        symbol,
        "qty":           str(int(qty)),
        "side":          "buy",
        "type":          entry_type,
        "time_in_force": "day",
        "order_class":   "bracket",
        "take_profit":   {"limit_price": f"{target_p:.2f}"},
        "stop_loss":     {"stop_price":  f"{stop_p:.2f}"},
    }
    if entry_type == "limit" and limit_price:
        body["limit_price"] = f"{float(limit_price):.2f}"
    try:
        r = _api("POST", "/v2/orders", body)
        return (f"✅ [{_mode()}] BRACKET ORDER\n"
                f"  Symbol:  {symbol}  ×  {int(qty)} shares\n"
                f"  Entry:   ${entry_p:,.2f}  ({entry_type.upper()})\n"
                f"  Stop:    ${stop_p:,.2f}  (-{stop_loss_pct}%)  risk: ${(entry_p-stop_p)*qty:,.2f}\n"
                f"  Target:  ${target_p:,.2f}  (+{take_profit_pct}%)  reward: ${(target_p-entry_p)*qty:,.2f}\n"
                f"  R/R:     {rr}:1\n"
                f"  ID:      {r.get('id','?')[:8]}   Status: {r.get('status','?').upper()}")
    except ValueError as e:
        return f"Bracket order failed: {e}"
    except Exception as e:
        return f"Error: {e}"

def trading_trail_stop(symbol: str, qty: float, trail_pct: float = 1.5,
                       side: str = "sell") -> str:
    """
    Trailing stop order — locks in profits as price moves in your favour.
    trail_pct: gap (%) between current high and stop (default 1.5%)
    side:      sell (exit long) | buy (cover short)
    """
    symbol = symbol.upper().strip()
    ok, reason = _guard(symbol)
    if not ok:
        return f"Trade blocked: {reason}"
    body: dict = {
        "symbol":        symbol,
        "qty":           str(int(qty)),
        "side":          side,
        "type":          "trailing_stop",
        "time_in_force": "gtc",
        "trail_percent": str(trail_pct),
    }
    try:
        r = _api("POST", "/v2/orders", body)
        return (f"✅ [{_mode()}] TRAILING STOP\n"
                f"  {symbol}  ×  {int(qty)} shares  ({side.upper()})\n"
                f"  Trail:  {trail_pct}% from price peak\n"
                f"  GTC — stays active until triggered or cancelled\n"
                f"  ID: {r.get('id','?')[:8]}")
    except ValueError as e:
        return f"Trail stop failed: {e}"
    except Exception as e:
        return f"Error: {e}"

def trading_cancel(order_id: str = "all") -> str:
    """Cancel a single order by ID, or all open orders (order_id='all')."""
    ok, reason = _guard()
    if not ok:
        return f"Error: {reason}"
    try:
        if order_id.lower() == "all":
            _api("DELETE", "/v2/orders")
            return f"✅ [{_mode()}] All open orders cancelled."
        _api("DELETE", f"/v2/orders/{order_id}")
        return f"✅ [{_mode()}] Order {order_id[:8]} cancelled."
    except ValueError as e:
        return f"Cancel failed: {e}"
    except Exception as e:
        return f"Error: {e}"

def trading_close_position(symbol: str) -> str:
    """Close an entire position at market price (flatten to zero)."""
    symbol = symbol.upper().strip()
    ok, reason = _guard()
    if not ok:
        return f"Error: {reason}"
    try:
        r   = _api("DELETE", f"/v2/positions/{symbol}")
        qty = r.get("qty", "?")
        return (f"✅ [{_mode()}] Closing {symbol}: {qty} shares at market.\n"
                f"  Order ID: {r.get('id','?')[:8]}  Status: {r.get('status','?').upper()}")
    except ValueError as e:
        return f"Close failed: {e}"
    except Exception as e:
        return f"Error: {e}"

def trading_close_all() -> str:
    """Liquidate ALL open positions at market price."""
    ok, reason = _guard()
    if not ok:
        return f"Error: {reason}"
    try:
        result = _api("DELETE", "/v2/positions")
        n = len(result) if isinstance(result, list) else 0
        return (f"✅ [{_mode()}] Close-all sent — {n} market orders placed.\n"
                f"  All positions will be flat once orders fill.")
    except ValueError as e:
        return f"Close-all failed: {e}"
    except Exception as e:
        return f"Error: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# LIVE MARKET DATA
# ══════════════════════════════════════════════════════════════════════════════

def trading_quote(symbol: str) -> str:
    """Live NBBO bid/ask spread and last trade."""
    symbol = symbol.upper().strip()
    try:
        q    = _data(f"/v2/stocks/{symbol}/quotes/latest")
        qt   = q.get("quote", {})
        bid  = float(qt.get("bp", 0))
        ask  = float(qt.get("ap", 0))
        bsz  = qt.get("bs", 0)
        asz  = qt.get("as", 0)
        sprd = ask - bid
        t    = _data(f"/v2/stocks/{symbol}/trades/latest")
        tr   = t.get("trade", {})
        lp   = float(tr.get("p", 0))
        lv   = tr.get("s", 0)
        mid  = (bid + ask) / 2 if bid and ask else lp
        return "\n".join([
            f"Live Quote: {symbol}  [{datetime.now().strftime('%H:%M:%S')}]",
            f"  Bid:    ${bid:,.4f}  (size: {bsz})",
            f"  Ask:    ${ask:,.4f}  (size: {asz})",
            f"  Mid:    ${mid:,.4f}",
            f"  Spread: ${sprd:.4f}  ({sprd/ask*100:.3f}%)" if ask else "  Spread: N/A",
            f"  Last:   ${lp:,.4f}  × {lv} shares",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Quote error: {e}"

def trading_snapshot(symbols: str = "AAPL,NVDA,TSLA,SPY,QQQ") -> str:
    """Multi-symbol live snapshot: price, day change, bid/ask."""
    sym_list = [s.strip().upper() for s in symbols.replace(",", " ").split() if s.strip()][:25]
    if not sym_list:
        return "No symbols provided."
    try:
        snap  = _data("/v2/stocks/snapshots", {"symbols": ",".join(sym_list)})
        lines = [f"Live Snapshot  [{datetime.now().strftime('%H:%M:%S')}]", ""]
        for sym in sym_list:
            s    = snap.get(sym, {})
            bar  = s.get("latestBar",   {})
            tr   = s.get("latestTrade", {})
            qt   = s.get("latestQuote", {})
            dp   = s.get("dailyBar",    {})
            c    = float(bar.get("c", tr.get("p", 0)))
            o    = float(dp.get("o", c))
            chg  = ((c - o) / o * 100) if o else 0
            bid  = float(qt.get("bp", 0))
            ask  = float(qt.get("ap", 0))
            vol  = int(dp.get("v", 0))
            arrow = "▲" if chg >= 0 else "▼"
            bid_ask = f"  b:{bid:.2f}/a:{ask:.2f}" if bid and ask else ""
            lines.append(
                f"  {sym:<6}  ${c:>9,.2f}  {arrow}{chg:+.2f}%"
                f"  vol:{vol:>9,}{bid_ask}"
            )
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Snapshot error: {e}"

def trading_bars(symbol: str, timeframe: str = "5Min", limit: int = 50) -> str:
    """Recent intraday OHLCV bars with VWAP. timeframe: 1Min|5Min|15Min|1Hour"""
    symbol = symbol.upper().strip()
    tf_map = {"1m":"1Min","5m":"5Min","15m":"15Min","1h":"1Hour",
              "1min":"1Min","5min":"5Min","15min":"15Min","1hour":"1Hour"}
    tf     = tf_map.get(timeframe.lower(), timeframe)
    try:
        raw  = _data(f"/v2/stocks/{symbol}/bars", {"timeframe": tf, "limit": limit})
        bars = raw.get("bars", [])
        if not bars:
            return f"No {tf} bars for {symbol}. Market may be closed."
        vwap = _vwap(bars)
        last = bars[-1]
        prev = bars[-2] if len(bars) > 1 else last
        chg  = (last["c"] - prev["c"]) / prev["c"] * 100 if prev["c"] else 0
        curr_vs_vwap = (last["c"] - vwap) / vwap * 100 if vwap else 0
        return "\n".join([
            f"Intraday: {symbol}  ({tf})  [{len(bars)} bars]",
            f"  Bar Time: {last['t'][:16].replace('T',' ')}",
            f"  O:{last['o']:.2f}  H:{last['h']:.2f}  L:{last['l']:.2f}  C:{last['c']:.2f}",
            f"  Volume:   {last['v']:,}",
            f"  VWAP:     ${vwap:.2f}  (price {curr_vs_vwap:+.2f}% from VWAP)",
            f"  vs prev:  {chg:+.2f}%",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Bars error: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# INTRADAY CALCULATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _vwap(bars: list) -> float:
    """Volume Weighted Average Price from a list of Alpaca bar dicts."""
    total_vol = sum(b.get("v", 0) for b in bars)
    if not total_vol:
        return 0
    return round(
        sum((b["h"] + b["l"] + b["c"]) / 3 * b.get("v", 0) for b in bars) / total_vol, 2
    )

def _orb(bars: list, minutes: int = 15) -> dict:
    """Opening Range from first N 1-min bars."""
    orb = bars[:minutes]
    if not orb:
        return {}
    return {
        "high":  round(max(b["h"] for b in orb), 2),
        "low":   round(min(b["l"] for b in orb), 2),
        "range": round(max(b["h"] for b in orb) - min(b["l"] for b in orb), 2),
    }

def _fetch_intraday(symbol: str, timeframe: str = "5Min", limit: int = 100) -> list:
    """Return list of Alpaca bar dicts for intraday analysis."""
    try:
        raw = _data(f"/v2/stocks/{symbol}/bars",
                    {"timeframe": timeframe, "limit": limit})
        return raw.get("bars", [])
    except Exception:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def trading_position_size(symbol: str, risk_pct: float = 0.5,
                          max_alloc_pct: float = 5.0) -> str:
    """
    ATR-based position sizing.
    risk_pct:      % of portfolio to risk on the trade (default 0.5%)
    max_alloc_pct: max % of portfolio to allocate to this position (default 5%)
    """
    symbol = symbol.upper().strip()
    if not _configured():
        return "Alpaca not configured. Position sizing needs live account equity."
    try:
        acct   = _api("GET", "/v2/account")
        equity = float(acct.get("equity", 0))
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Account error: {e}"
    if equity == 0:
        return "Account equity is $0."
    # Fetch ATR via market module
    try:
        import tools.market as MKT
        bars  = MKT._fetch_history(symbol, 30)
        ta    = MKT._compute_ta(bars) if bars else {}
        price = ta.get("price", 0)
        atr   = ta.get("atr", 0)
    except Exception:
        price, atr = 0, 0
    if not price:
        try:
            bar   = _data(f"/v2/stocks/{symbol}/bars/latest")
            price = float(bar.get("bar", {}).get("c", 0))
        except Exception:
            return f"Cannot get price for {symbol}."
    if not atr:
        atr = price * 0.02
    stop_dist    = atr * 1.5
    stop_price   = round(price - stop_dist, 2)
    dollar_risk  = equity * (risk_pct    / 100)
    max_alloc    = equity * (max_alloc_pct / 100)
    shares_risk  = math.floor(dollar_risk / stop_dist) if stop_dist > 0 else 0
    shares_alloc = math.floor(max_alloc   / price)     if price     > 0 else 0
    shares       = min(shares_risk, shares_alloc)
    # ── Capital clamp: never exceed available buying power ─────────
    budget_rem    = _budget_remaining()
    budget_capped = False
    if budget_rem > 0 and price > 0:
        shares_budget = math.floor(budget_rem / price)
        if shares_budget < shares:
            shares        = shares_budget
            budget_capped = True
    pos_val      = round(shares * price, 2)
    budget_note  = (f"  ** Capital cap: ${budget_rem:,.2f} buying power available **" if budget_capped
                    else f"  Available capital: ${budget_rem:,.2f} (live buying power)")
    return "\n".join(filter(None, [
        f"Position Sizing: {symbol}  [{_mode()}]",
        f"  Account Equity:  ${equity:>12,.2f}",
        f"  Entry Price:     ${price:>12,.2f}",
        f"  ATR(14):         ${atr:>12.2f}",
        f"  Stop Loss:       ${stop_price:>12,.2f}  (entry − 1.5×ATR)",
        f"  Risk per Share:  ${stop_dist:>12.2f}",
        "",
        f"  Risk Budget:     ${dollar_risk:>12,.2f}  ({risk_pct}% of equity)",
        f"  Max Alloc:       ${max_alloc:>12,.2f}  ({max_alloc_pct}% of equity)",
        budget_note,
        "",
        f"  → Optimal Shares: {shares}",
        f"  → Position Value: ${pos_val:>10,.2f}  ({pos_val/equity*100:.1f}% of equity)",
        f"  → Max $ at Risk:  ${shares*stop_dist:>10,.2f}",
    ]))

def trading_risk_status() -> str:
    """Overall risk dashboard: day P/L vs limit, positions, gross exposure."""
    if not _configured():
        return "Alpaca not configured."
    try:
        acct      = _api("GET", "/v2/account")
        equity    = float(acct.get("equity",      0))
        last      = float(acct.get("last_equity", 0))
        day_pl    = equity - last
        try:
            import tools.risk_params as RP
            limit     = RP.daily_loss_dollars()
            limit_pct = RP.get_params()["max_daily_loss_pct"]
        except Exception:
            limit, limit_pct = 0.0, 0.0
        positions = _api("GET", "/v2/positions")
        n_pos     = len(positions)
        gross_exp = sum(abs(float(p.get("market_value", 0))) for p in positions)
        exp_pct   = gross_exp / equity * 100 if equity else 0
        halted    = limit > 0 and day_pl < -limit
        return "\n".join([
            f"Trading Risk Status  [{_mode()}]",
            f"  Day P/L:      ${day_pl:>+10,.2f}",
            f"  Loss Limit:   ${limit:>10,.0f}  ({limit_pct:.1f}% of portfolio)  →  "
            f"{'⚠ EXCEEDED — AUTO-TRADING HALTED' if halted else '✓ OK'}",
            f"  Positions:    {n_pos}  (unlimited — capital-constrained)",
            f"  Gross Exp:    ${gross_exp:>10,.2f}  ({exp_pct:.1f}% of equity)",
            f"  Auto-Trade:   {'HALTED ⚠' if halted else 'ACTIVE ✓'}",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Risk status error: {e}"

def trading_performance(days: int = 30) -> str:
    """Trade performance stats from Alpaca portfolio history."""
    if not _configured():
        return "Alpaca not configured."
    try:
        hist   = _api("GET", f"/v2/portfolio/history?period={days}D&timeframe=1D")
        pl_pct = hist.get("profit_loss_pct", [])
        pl_abs = hist.get("profit_loss",     [])
        eq_arr = hist.get("equity",          [])
        if not pl_pct:
            return f"No portfolio history for last {days} days  [{_mode()}]."
        total_return = (eq_arr[-1] - eq_arr[0]) / eq_arr[0] * 100 if eq_arr and eq_arr[0] else 0
        best_day     = max(pl_pct)
        worst_day    = min(pl_pct)
        pos_days     = sum(1 for x in pl_pct if x > 0)
        neg_days     = sum(1 for x in pl_pct if x < 0)
        daily_mean   = sum(pl_pct) / len(pl_pct)
        variance     = sum((x - daily_mean)**2 for x in pl_pct) / len(pl_pct)
        std_dev      = variance**0.5 or 0.0001
        sharpe       = round((daily_mean / std_dev) * (252**0.5), 2)
        total_pnl    = sum(pl_abs) if pl_abs else 0
        return "\n".join([
            f"Performance — Last {days} Days  [{_mode()}]",
            f"  Total Return:   {total_return:+.2f}%",
            f"  Total P/L:      ${total_pnl:+,.2f}",
            f"  Best Day:       {best_day:+.2f}%",
            f"  Worst Day:      {worst_day:+.2f}%",
            f"  Up Days:        {pos_days} / {len(pl_pct)} trading days",
            f"  Down Days:      {neg_days} / {len(pl_pct)} trading days",
            f"  Sharpe (ann.):  {sharpe:.2f}  ({'Strong' if sharpe > 1.5 else 'Good' if sharpe > 1 else 'Weak' if sharpe < 0 else 'Moderate'})",
        ])
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Performance error: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# TRADING STRATEGIES
# ══════════════════════════════════════════════════════════════════════════════

def strategy_momentum_scan(symbols: str = "watchlist", min_score: int = 3,
                           auto_trade: bool = False, risk_pct: float = 0.5) -> str:
    """
    Momentum scanner: ranks symbols by TA score, highlights STRONG BUY setups.
    auto_trade=True: places bracket orders on scores >= 5 (use with caution).
    """
    try:
        import tools.market as MKT
    except ImportError:
        return "Market module unavailable."
    presets = {
        "watchlist": list(MKT._load(MKT._WATCHLIST_FILE, {}).keys()),
        "sp500":     ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","V","UNH","XOM","AVGO"],
        "tech":      ["NVDA","AMD","AAPL","MSFT","META","GOOGL","AMZN","TSM","AVGO","ORCL","PLTR","SMCI"],
        "momentum":  ["NVDA","SMCI","PLTR","CRWD","MELI","PANW","SNOW","DDOG","MDB","ZS","NET","CELH"],
    }
    sym_list = (presets.get(symbols.lower())
                if symbols.lower() in presets
                else [s.strip().upper() for s in symbols.replace(",", " ").split() if s.strip()])
    if not sym_list:
        return "No symbols. Add tickers to watchlist or specify comma-separated list."
    results  = []
    executed = []
    for sym in sym_list[:25]:
        bars = MKT._fetch_history(sym, 90)
        if not bars or len(bars) < 21:
            continue
        ta = MKT._compute_ta(bars)
        if not ta:
            continue
        verdict, score, reasons = MKT._score_signal(ta)
        price = ta.get("price", 0)
        atr   = ta.get("atr") or price * 0.02
        results.append({
            "symbol": sym, "verdict": verdict, "score": score,
            "price": price, "rsi": ta.get("rsi"), "atr": atr,
            "reasons": reasons[:2],
        })
        if auto_trade and score >= 5 and _configured():
            ok, why = _guard(sym)
            if ok:
                try:
                    acct   = _api("GET", "/v2/account")
                    eq     = float(acct.get("equity", 0))
                    dr     = eq * (risk_pct / 100)
                    stop_d = atr * 1.5
                    qty    = max(1, math.floor(dr / stop_d)) if stop_d > 0 else 1
                    r = _api("POST", "/v2/orders", {
                        "symbol": sym, "qty": str(qty), "side": "buy",
                        "type": "market", "time_in_force": "day",
                        "order_class": "bracket",
                        "take_profit": {"limit_price": f"{round(price + atr*3, 2):.2f}"},
                        "stop_loss":   {"stop_price":  f"{round(price - atr*1.5, 2):.2f}"},
                    })
                    executed.append(f"{sym}×{qty}sh (ID:{r.get('id','?')[:6]})")
                except Exception as ex:
                    executed.append(f"{sym} failed:{ex}")
        time.sleep(0.2)
    results.sort(key=lambda x: -x["score"])
    strong_buy  = [r for r in results if r["score"] >= 5]
    buy_sigs    = [r for r in results if 2 <= r["score"] < 5]
    sell_sigs   = [r for r in results if r["score"] <= -2]
    lines = [f"Momentum Scan — {len(results)} symbols — {datetime.now().strftime('%H:%M')}  [{_mode()}]", ""]
    if strong_buy:
        lines.append("  STRONG BUY:")
        for r in strong_buy:
            lines.append(f"    {r['symbol']:<7} ${r['price']:>9,.2f}  RSI:{str(r['rsi'] or '?'):<5}  [{r['score']:+2d}]")
            for rsn in r["reasons"]:
                lines.append(f"           {rsn}")
    if buy_sigs:
        lines.append("\n  BUY signals:")
        for r in buy_sigs:
            lines.append(f"    {r['symbol']:<7} ${r['price']:>9,.2f}  RSI:{str(r['rsi'] or '?'):<5}  [{r['score']:+2d}]")
    if sell_sigs:
        lines.append("\n  SELL / avoid:")
        for r in sell_sigs:
            lines.append(f"    {r['symbol']:<7} ${r['price']:>9,.2f}  [{r['score']:+2d}]")
    if not results:
        lines.append("  No data returned. Check watchlist or symbol list.")
    if executed:
        lines += ["", f"  Auto-executed: {', '.join(executed)}"]
    return "\n".join(lines)

def strategy_orb(symbol: str, range_minutes: int = 15,
                 auto_trade: bool = False, qty: int = 0) -> str:
    """
    Opening Range Breakout: levels from the first N minutes (9:30–9:45 ET).
    Breakout above the high = buy. Breakdown below low = avoid / short.
    """
    symbol = symbol.upper().strip()
    bars   = _fetch_intraday(symbol, "1Min", range_minutes + 45)
    if not bars:
        return f"No intraday bars for {symbol}. Is the market open?"
    orb_lvl = _orb(bars, range_minutes)
    vwap_v  = _vwap(bars)
    curr    = float(bars[-1]["c"])
    high    = orb_lvl.get("high", 0)
    low     = orb_lvl.get("low",  0)
    rng     = orb_lvl.get("range",0)
    if curr > high:
        signal  = "BREAKOUT UP  — bullish"
        action  = "BUY"
        stop_p  = low
        target_p = round(high + rng, 2)
    elif curr < low:
        signal  = "BREAKDOWN — bearish"
        action  = "WAIT/AVOID"
        stop_p  = high
        target_p = round(low - rng, 2)
    else:
        signal  = "INSIDE RANGE — wait"
        action  = "WAIT"
        stop_p  = low
        target_p = high
    rr = round(rng / max(abs(curr - stop_p), 0.01), 2)
    lines = [
        f"ORB Strategy: {symbol}  ({range_minutes}-min range)  [{_mode()}]",
        f"  Current:  ${curr:,.2f}  |  VWAP: ${vwap_v:.2f}",
        f"  ORB High: ${high:,.2f}",
        f"  ORB Low:  ${low:,.2f}  (range: ${rng:.2f})",
        f"  Signal:   {signal}",
        f"  Action:   {action}",
    ]
    if action == "BUY":
        lines += [
            f"  Entry:    above ${high:,.2f}",
            f"  Stop:     ${stop_p:,.2f}  (below ORB low)",
            f"  Target:   ${target_p:,.2f}  (1× range projection)",
            f"  R/R:      {rr}:1",
        ]
    if auto_trade and action == "BUY" and qty > 0 and curr > high:
        ok, reason = _guard(symbol)
        if ok:
            try:
                r = _api("POST", "/v2/orders", {
                    "symbol": symbol, "qty": str(qty), "side": "buy",
                    "type": "market", "time_in_force": "day",
                    "order_class": "bracket",
                    "take_profit": {"limit_price": f"{target_p:.2f}"},
                    "stop_loss":   {"stop_price":  f"{stop_p:.2f}"},
                })
                lines.append(f"\n  ✅ AUTO-TRADE: BUY {qty} {symbol} | ID:{r.get('id','?')[:8]}")
            except Exception as ex:
                lines.append(f"\n  Auto-trade failed: {ex}")
    return "\n".join(lines)

def strategy_vwap(symbol: str, deviation_pct: float = 0.5) -> str:
    """
    VWAP deviation trade: price far below VWAP = mean-reversion buy setup.
    Also flags extended moves above VWAP for profit-taking.
    """
    symbol = symbol.upper().strip()
    bars   = _fetch_intraday(symbol, "5Min", 80)
    if not bars:
        return f"No intraday bars for {symbol}."
    vwap_v = _vwap(bars)
    curr   = float(bars[-1]["c"])
    high_d = float(bars[-1]["h"])
    vol    = bars[-1].get("v", 0)
    avg_v  = sum(b.get("v", 0) for b in bars) / len(bars) if bars else 1
    vr     = vol / avg_v if avg_v else 0
    diff   = (curr - vwap_v) / vwap_v * 100 if vwap_v else 0
    if diff < -deviation_pct:
        signal = f"BUY SETUP — price {abs(diff):.1f}% below VWAP (mean reversion)"
        detail = f"  Entry near ${curr:.2f}  |  Stop: ${round(curr - (vwap_v - curr)*0.5, 2):.2f}  |  Target: VWAP ${vwap_v:.2f}"
    elif diff > deviation_pct * 3:
        signal = f"TAKE PROFIT — price {diff:.1f}% above VWAP (extended / overbought)"
        detail = f"  Consider trailing stop or partial exit"
    elif diff > deviation_pct:
        signal = f"BULLISH BIAS — {diff:.1f}% above VWAP"
        detail = f"  Pullbacks to VWAP ${vwap_v:.2f} = potential buy zone"
    else:
        signal = f"NEUTRAL — price {diff:.2f}% from VWAP"
        detail = f"  Wait for directional confirmation"
    return "\n".join([
        f"VWAP Strategy: {symbol}  [{_mode()}]",
        f"  Price:  ${curr:,.2f}",
        f"  VWAP:   ${vwap_v:.2f}  ({diff:+.2f}% deviation)",
        f"  Volume: {vr:.1f}x average  ({vol:,} shares last bar)",
        f"  Signal: {signal}",
        detail,
    ])

def strategy_gap_scanner(gap_pct: float = 2.0, symbols: str = "") -> str:
    """
    Pre/post-market gap scanner. Finds stocks gapping up or down >= gap_pct%.
    These are prime Opening Range Breakout candidates.
    """
    default_syms = [
        "AAPL","MSFT","NVDA","AMD","TSLA","META","GOOGL","AMZN",
        "SPY","QQQ","COIN","PLTR","MSTR","SMCI","ARM","AVGO",
        "GME","RIVN","NIO","XPEV","LCID","SOFI","HOOD","BBAI",
        "PTON","BYND","OPEN","RDFN","AI","SOUN","LUNR","RKLB",
    ]
    sym_list = ([s.strip().upper() for s in symbols.replace(",", " ").split() if s.strip()]
                if symbols else default_syms)[:40]
    if not _configured():
        return "Alpaca not configured — gap scanner needs live data."
    try:
        snap     = _data("/v2/stocks/snapshots", {"symbols": ",".join(sym_list)})
        gappers  = []
        for sym in sym_list:
            s = snap.get(sym, {})
            prev = float(s.get("prevDailyBar", {}).get("c", 0))
            curr = float(s.get("latestTrade",  {}).get("p", 0) or
                         s.get("latestBar",    {}).get("c", 0))
            opn  = float(s.get("dailyBar",     {}).get("o", 0))
            if not prev or not curr:
                continue
            gap  = (opn - prev) / prev * 100 if opn else 0
            chg  = (curr - prev) / prev * 100
            vol  = int(s.get("dailyBar", {}).get("v", 0))
            if abs(gap) >= gap_pct:
                gappers.append({"symbol": sym, "prev": prev, "open": opn,
                                 "curr": curr, "gap": gap, "chg": chg, "vol": vol})
        if not gappers:
            return f"No gappers >= {gap_pct}% in {len(sym_list)} scanned symbols."
        gappers.sort(key=lambda x: -abs(x["gap"]))
        up   = [g for g in gappers if g["gap"] > 0]
        down = [g for g in gappers if g["gap"] < 0]
        lines = [f"Gap Scanner (≥{gap_pct}%) — {datetime.now().strftime('%H:%M:%S')}  [{_mode()}]",
                 f"  Scanned: {len(sym_list)} symbols  |  Found: {len(gappers)} gappers", ""]
        if up:
            lines.append("  GAP UP (bullish — ORB buy candidates):")
            for g in up[:10]:
                lines.append(
                    f"    {g['symbol']:<6}  prev:${g['prev']:.2f} → open:${g['open']:.2f}"
                    f"  gap:{g['gap']:+.1f}%  now:{g['chg']:+.1f}%  vol:{g['vol']:,}"
                )
        if down:
            lines.append("\n  GAP DOWN (bearish — watch for fill or continuation):")
            for g in down[:6]:
                lines.append(
                    f"    {g['symbol']:<6}  prev:${g['prev']:.2f} → open:${g['open']:.2f}"
                    f"  gap:{g['gap']:+.1f}%  now:{g['chg']:+.1f}%"
                )
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Gap scanner error: {e}"

def strategy_auto_execute(symbol: str, strategy: str = "momentum",
                          risk_pct: float = 0.5) -> str:
    """
    Execute a named strategy on a symbol automatically.
    strategy: momentum | orb | vwap
    ATR-based bracket orders placed automatically.
    """
    symbol = symbol.upper().strip()
    ok, reason = _guard(symbol)
    if not ok:
        return f"Trade blocked: {reason}"
    if not _is_open():
        return "Market is closed. Auto-execute is only available during market hours (9:30–16:00 ET)."
    try:
        acct   = _api("GET", "/v2/account")
        equity = float(acct.get("equity", 0))
    except ValueError as e:
        return str(e)
    # Get TA for sizing
    try:
        import tools.market as MKT
        bars  = MKT._fetch_history(symbol, 30)
        ta    = MKT._compute_ta(bars) if bars else {}
        price = ta.get("price", 0)
        atr   = ta.get("atr", 0) or (price * 0.02 if price else 0)
        _, score, _ = MKT._score_signal(ta) if ta else ("", 0, [])
    except Exception:
        price, atr, score = 0, 0, 0
    if not price:
        try:
            bar   = _data(f"/v2/stocks/{symbol}/bars/latest")
            price = float(bar.get("bar", {}).get("c", 0))
            atr   = price * 0.02
        except Exception:
            return f"Cannot get price for {symbol}."
    if strategy == "momentum" and score < 3:
        return (f"{symbol} TA score {score:+d}/10 — too weak for auto-trade "
                f"(need ≥ +3). Check 'signal {symbol}' first.")
    dr       = equity * (risk_pct / 100)
    stop_d   = atr * 1.5
    qty      = max(1, math.floor(dr / stop_d)) if stop_d > 0 else 1
    stop_p   = round(price - stop_d, 2)
    target_p = round(price + atr * 3.0, 2)
    rr       = round(atr * 3.0 / stop_d, 2) if stop_d else 0
    try:
        r = _api("POST", "/v2/orders", {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          "buy",
            "type":          "market",
            "time_in_force": "day",
            "order_class":   "bracket",
            "take_profit":   {"limit_price": f"{target_p:.2f}"},
            "stop_loss":     {"stop_price":  f"{stop_p:.2f}"},
        })
        return (f"✅ [{_mode()}] AUTO-TRADE EXECUTED: {symbol}  ({strategy})\n"
                f"  Shares:  {qty}\n"
                f"  Entry:   ${price:,.2f}  (market)\n"
                f"  Stop:    ${stop_p:,.2f}  (−{stop_d/price*100:.1f}%)\n"
                f"  Target:  ${target_p:,.2f}  (+{(target_p-price)/price*100:.1f}%)\n"
                f"  R/R:     {rr}:1\n"
                f"  $ Risk:  ${qty*stop_d:,.2f}  ({risk_pct}% of equity)\n"
                f"  ID:      {r.get('id','?')[:8]}   Status: {r.get('status','?').upper()}")
    except ValueError as e:
        return f"Auto-trade failed: {e}"
    except Exception as e:
        return f"Error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# CAPITAL STATUS  (live Alpaca buying power — the $100 budget cap is retired)
# ══════════════════════════════════════════════════════════════════════════════

def trading_budget_status() -> str:
    """
    Live capital status: equity, buying power, deployment, P&L — straight from
    the Alpaca account. If a trading goal is set (goal_engine), its progress
    is appended. (Tool name kept from the retired $100-mission era.)
    """
    if not _configured():
        return "Alpaca not configured. Add API keys to .env"
    try:
        acct      = _api("GET", "/v2/account")
        positions = _api("GET", "/v2/positions")
        equity    = float(acct.get("equity",          0))
        last_eq   = float(acct.get("last_equity",     0))
        cash      = float(acct.get("cash",            0))
        bpow      = float(acct.get("buying_power",    0))
        day_pl    = equity - last_eq
        mkt_value = sum(abs(float(p.get("market_value", 0))) for p in positions)
        unreal_pl = sum(float(p.get("unrealized_pl", 0)) for p in positions)
        deploy_pct = mkt_value / equity * 100 if equity else 0
        avail      = _budget_remaining()
        lines = [
            f"JARVIS CAPITAL STATUS  [{_mode()}]",
            f"",
            f"  Portfolio Value: ${equity:>12,.2f}",
            f"  Cash:            ${cash:>12,.2f}",
            f"  Buying Power:    ${bpow:>12,.2f}   (live Alpaca — the only capital limit)",
            f"  Deployable Now:  ${avail:>12,.2f}   (after cash-reserve holdback)",
            f"",
            f"  Deployed:        ${mkt_value:>12,.2f}   ({deploy_pct:.1f}% of portfolio)",
            f"  Unrealized P&L:  ${unreal_pl:>+12,.2f}",
            f"  Day P&L:         ${day_pl:>+12,.2f}",
        ]
        try:
            import tools.goal_engine as GOAL
            g = GOAL.goal_progress_lines()
            if g:
                lines += [""] + g
        except Exception:
            pass
        if positions:
            lines += ["", "  Open Positions:"]
            for p in positions:
                sym = p["symbol"]
                pl  = float(p.get("unrealized_pl", 0))
                mv  = float(p.get("market_value",  0))
                plp = float(p.get("unrealized_plpc", 0)) * 100
                arrow = "▲" if pl >= 0 else "▼"
                lines.append(f"    {sym:<6}  ${mv:>10,.2f}  {arrow}${abs(pl):,.2f} ({plp:+.1f}%)")
        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Capital status error: {e}"
