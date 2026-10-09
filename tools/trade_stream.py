"""
trade_stream.py — JARVIS Live NYSE/NASDAQ Trade Tape (real-time, free)

Continuous WebSocket listener on Alpaca's free IEX real-time feed — actual
tick-by-tick prints crossing the tape as they happen, not a periodic REST
snapshot/poll (which is all the rest of Jarvis's market data used until now).
Reuses the existing ALPACA_API_KEY/SECRET — no new signup, no paid feed.

Endpoint: wss://stream.data.alpaca.markets/v2/iex

Usage:
  update_watchlist(symbols, priority=[...])  — merge symbols into the live
    subscription set. Called by auto_hunt() (scan universe) and
    trade_monitor (open positions, as priority — never trimmed).
  live_tape_signal(symbol) -> (points 0-10, detail) — real-time buy/sell
    imbalance + trade velocity. Used as an execution-time confirmation gate,
    not folded into the 100-pt conviction score (same pattern as
    retail_flow/options_unusual/gamma_exposure — standalone signal only).
  live_movers() -> str — what's showing the strongest real-time buy/sell
    pressure right now, across everything currently streamed.
"""

import os, json, time, threading
from collections import deque
from datetime import datetime

try:
    import websocket  # websocket-client
    _HAS_WEBSOCKET = True
except Exception:
    _HAS_WEBSOCKET = False

_STREAM_URL      = "wss://stream.data.alpaca.markets/v2/iex"
_MAX_SYMBOLS     = 50      # cap so one WS connection isn't asked to track hundreds of tickers
_TICK_WINDOW_SEC = 300     # 5-minute rolling window per symbol

_lock          = threading.Lock()
_ws            = None
_ws_thread     = None
_running       = False
_connected     = False
_authed        = False
_subscribed    = set()
_desired       = set()     # symbols we want subscribed (open positions ∪ hunt pool)
_ticks         = {}        # symbol -> deque[(ts, price, size, side)]
_last_msg_time = None
_reconnect_delay = 2


def _cfg(k: str, d: str = "") -> str:
    return os.getenv(k, d)


# ══════════════════════════════════════════════════════════════════════════════
# Subscription management
# ══════════════════════════════════════════════════════════════════════════════

def update_watchlist(symbols, priority=None) -> None:
    """
    Merge symbols into the desired subscription set. `priority` symbols
    (e.g. currently-open positions) are never dropped when trimming to
    _MAX_SYMBOLS — everything else competes for the remaining slots.
    """
    global _desired
    with _lock:
        pri   = {s.upper().strip() for s in (priority or []) if s}
        want  = {s.upper().strip() for s in (symbols or []) if s}
        merged = pri | _desired | want
        if len(merged) > _MAX_SYMBOLS:
            rest   = list(merged - pri)
            merged = pri | set(rest[: max(0, _MAX_SYMBOLS - len(pri))])
        _desired = merged
    _resync_subscription()


def _send(msg: dict) -> None:
    try:
        if _ws:
            _ws.send(json.dumps(msg))
    except Exception:
        pass


def _resync_subscription() -> None:
    global _subscribed
    if not (_connected and _authed):
        return
    with _lock:
        to_add    = _desired - _subscribed
        to_remove = _subscribed - _desired
    if to_add:
        _send({"action": "subscribe", "trades": sorted(to_add)})
    if to_remove:
        _send({"action": "unsubscribe", "trades": sorted(to_remove)})
    with _lock:
        _subscribed = set(_desired)


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket callbacks
# ══════════════════════════════════════════════════════════════════════════════

def _on_open(ws):
    global _connected
    _connected = True
    _send({"action": "auth", "key": _cfg("ALPACA_API_KEY"), "secret": _cfg("ALPACA_API_SECRET")})


def _on_message(ws, message):
    global _authed, _last_msg_time
    _last_msg_time = datetime.now()
    try:
        msgs = json.loads(message)
    except Exception:
        return
    if isinstance(msgs, dict):
        msgs = [msgs]
    for m in msgs:
        t = m.get("T")
        if t == "success" and m.get("msg") == "authenticated":
            _authed = True
            _resync_subscription()
        elif t == "t":
            _record_trade(m)


def _record_trade(m: dict) -> None:
    sym   = m.get("S")
    price = m.get("p")
    size  = m.get("s")
    if not sym or not price or not size:
        return
    now = time.time()
    with _lock:
        dq = _ticks.setdefault(sym, deque())
        last_price = dq[-1][1] if dq else None
        if last_price is None or price > last_price:
            side = "buy"
        elif price < last_price:
            side = "sell"
        else:
            side = "neutral"
        dq.append((now, price, size, side))
        cutoff = now - _TICK_WINDOW_SEC
        while dq and dq[0][0] < cutoff:
            dq.popleft()


def _on_error(ws, error):
    pass


def _on_close(ws, *a):
    global _connected, _authed
    _connected = False
    _authed    = False


def _run_ws():
    global _ws, _reconnect_delay
    while _running:
        try:
            _ws = websocket.WebSocketApp(
                _STREAM_URL,
                on_open=_on_open, on_message=_on_message,
                on_error=_on_error, on_close=_on_close,
            )
            _reconnect_delay = 2
            _ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception:
            pass
        if _running:
            time.sleep(_reconnect_delay)
            _reconnect_delay = min(60, _reconnect_delay * 2)


# ══════════════════════════════════════════════════════════════════════════════
# Public control
# ══════════════════════════════════════════════════════════════════════════════

def start_trade_stream(symbols=None) -> str:
    global _running, _ws_thread
    if not _HAS_WEBSOCKET:
        return "websocket-client not installed. Run: pip install websocket-client"
    if not (_cfg("ALPACA_API_KEY") and _cfg("ALPACA_API_SECRET")):
        return "Alpaca not configured — live trade stream needs ALPACA_API_KEY/SECRET (same free keys as everything else)."
    if _running and _ws_thread and _ws_thread.is_alive():
        return "Live trade stream already running."
    if symbols:
        update_watchlist(symbols)
    _running   = True
    _ws_thread = threading.Thread(target=_run_ws, daemon=True, name="jarvis-trade-stream")
    _ws_thread.start()
    return "Live NYSE/NASDAQ trade stream starting (Alpaca IEX real-time feed)."


def stop_trade_stream() -> str:
    global _running
    _running = False
    try:
        if _ws:
            _ws.close()
    except Exception:
        pass
    return "Live trade stream stopping."


def stream_status() -> str:
    with _lock:
        n_sub      = len(_subscribed)
        n_ticking  = sum(1 for dq in _ticks.values() if dq)
    age = f"{(datetime.now() - _last_msg_time).total_seconds():.0f}s ago" if _last_msg_time else "never"
    return "\n".join([
        "Live Trade Stream (Alpaca IEX real-time)",
        f"  Installed:   {_HAS_WEBSOCKET}",
        f"  Running:     {_running}",
        f"  Connected:   {_connected}   Authenticated: {_authed}",
        f"  Subscribed:  {n_sub} symbols  ({n_ticking} with prints so far)",
        f"  Last print:  {age}",
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Signals
# ══════════════════════════════════════════════════════════════════════════════

def _symbol_stats(sym: str):
    with _lock:
        dq = list(_ticks.get(sym.upper(), ()))
    if not dq:
        return None
    now      = time.time()
    recent   = [d for d in dq if now - d[0] <= 60]
    buy_vol  = sum(s for _, _, s, side in dq if side == "buy")
    sell_vol = sum(s for _, _, s, side in dq if side == "sell")
    total    = buy_vol + sell_vol
    buy_ratio = buy_vol / total if total else 0.5
    first_p, last_p = dq[0][1], dq[-1][1]
    momentum_pct = (last_p - first_p) / first_p * 100 if first_p else 0
    return {
        "buy_ratio": buy_ratio, "trade_count": len(dq),
        "trades_per_min": len(recent), "momentum_pct": momentum_pct,
        "last_price": last_p,
    }


def live_tape_signal(symbol: str):
    """
    Real-time buy/sell imbalance + momentum for `symbol`, computed from the
    live tick stream (not a REST snapshot). Returns (points 0-10, detail str).
    Auto-subscribes the symbol for next time if it isn't streamed yet.
    """
    sym   = symbol.upper().strip()
    stats = _symbol_stats(sym)
    if stats is None:
        update_watchlist([sym])
        return 5, f"{sym}: not yet streamed (subscribing now — check again shortly)"
    br = stats["buy_ratio"]
    if br >= 0.65 and stats["trades_per_min"] >= 5:
        pts, label = 10, "STRONG LIVE BUY PRESSURE"
    elif br >= 0.56:
        pts, label = 7, "LIVE BUY PRESSURE"
    elif br <= 0.35 and stats["trades_per_min"] >= 5:
        pts, label = 0, "STRONG LIVE SELL PRESSURE"
    elif br <= 0.44:
        pts, label = 3, "LIVE SELL PRESSURE"
    else:
        pts, label = 5, "BALANCED"
    detail = (
        f"{sym}: {label} — buy-side {br:.0%} of {stats['trade_count']} live prints "
        f"({stats['trades_per_min']}/min), momentum {stats['momentum_pct']:+.2f}% over window, "
        f"last ${stats['last_price']:.2f}"
    )
    return pts, detail


def live_movers(top_n: int = 10) -> str:
    """
    What's showing the strongest real-time buy/sell pressure right now,
    across every symbol currently on the live tape (open positions + hunt
    universe). Genuinely live tick data, not a point-in-time poll.
    """
    with _lock:
        syms = list(_ticks.keys())
    rows = []
    for sym in syms:
        stats = _symbol_stats(sym)
        if not stats or stats["trade_count"] < 3:
            continue
        rows.append((sym, stats))
    if not rows:
        return ("No live tape data yet. The stream may just be starting up, or "
                "the market is closed — run 'auto hunt' first to seed the watchlist.")
    rows.sort(key=lambda r: -abs(r[1]["buy_ratio"] - 0.5))
    lines = [
        f"Live Tape — Real-Time Buy/Sell Pressure  [{datetime.now().strftime('%H:%M:%S')}]",
        f"  Streaming {len(syms)} symbols  |  {len(rows)} with recent prints", "",
    ]
    for sym, s in rows[:top_n]:
        arrow = "▲" if s["buy_ratio"] >= 0.5 else "▼"
        lines.append(
            f"  {sym:<6}  buy:{s['buy_ratio']:>5.0%}  {arrow}  "
            f"{s['trades_per_min']:>3}/min  mom:{s['momentum_pct']:+.2f}%  "
            f"${s['last_price']:.2f}  ({s['trade_count']} prints)"
        )
    return "\n".join(lines)
