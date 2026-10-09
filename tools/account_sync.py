"""
tools/account_sync.py — live Alpaca account state as the ONLY capital truth.

Replaces the retired TRADING_BUDGET hard cap. Every capital decision in the
trading pipeline reads buying power / portfolio value from here:

  • On startup and every 5 minutes (background thread):
      GET /v2/account   → buying_power, portfolio_value, cash,
                          daytrade_count, pattern_day_trader
      GET /v2/positions → open positions with live P&L
      GET /v2/orders    → pending orders
    ...synced into tools/store.py (keys 'alpaca_account', 'alpaca_positions',
    'alpaca_orders') so the Task Scheduler process and the server share one
    ground truth that survives restarts.

  • If a live API call fails, the LAST KNOWN synced values from store.py are
    used as fallback — trades are never blocked by a hardcoded budget figure.

  • pre_trade_check(symbol, notional) runs before every autonomous entry:
    buying power sufficient, PDT status (irrelevant above $25k equity — the
    check confirms rather than assumes), and existing-position awareness.
"""

import os, time, threading
from datetime import datetime
from tools.store import get, put

_ACCT_KEY = "alpaca_account"
_POS_KEY  = "alpaca_positions"
_ORD_KEY  = "alpaca_orders"

_SYNC_INTERVAL = 300          # 5 minutes
_state = {"running": False, "last_sync": 0.0, "last_error": "", "syncs": 0}
_cache = {"account": None, "positions": None, "orders": None, "ts": 0.0}
_lock = threading.Lock()


def _configured() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"))


def _api(method: str, path: str):
    import tools.trading as TRD
    return TRD._api(method, path)


# ── Sync ───────────────────────────────────────────────────────────────────────

def sync_now() -> dict:
    """Pull account + positions + orders from Alpaca and persist to store.py.
    Returns the account dict (live on success, last-known on failure)."""
    if not _configured():
        return get(_ACCT_KEY) or {}
    try:
        acct = _api("GET", "/v2/account")
        snapshot = {
            "equity":             float(acct.get("equity", 0)),
            "portfolio_value":    float(acct.get("portfolio_value", 0)),
            "cash":               float(acct.get("cash", 0)),
            "buying_power":       float(acct.get("buying_power", 0)),
            "last_equity":        float(acct.get("last_equity", 0)),
            "daytrade_count":     int(acct.get("daytrade_count", 0)),
            "pattern_day_trader": bool(acct.get("pattern_day_trader", False)),
            "status":             acct.get("status", ""),
            "synced_at":          datetime.now().isoformat(),
        }
        put(_ACCT_KEY, snapshot)
        with _lock:
            _cache["account"] = snapshot
            _cache["ts"] = time.time()
        try:
            positions = _api("GET", "/v2/positions")
            put(_POS_KEY, [{
                "symbol":        p.get("symbol", ""),
                "qty":           float(p.get("qty", 0)),
                "avg_entry":     float(p.get("avg_entry_price", 0)),
                "market_value":  float(p.get("market_value", 0) or 0),
                "unrealized_pl": float(p.get("unrealized_pl", 0) or 0),
            } for p in positions])
            with _lock:
                _cache["positions"] = positions
        except Exception:
            pass
        try:
            orders = _api("GET", "/v2/orders?status=open&limit=100")
            put(_ORD_KEY, [{
                "id": o.get("id", ""), "symbol": o.get("symbol", ""),
                "side": o.get("side", ""), "type": o.get("type", ""),
                "qty": o.get("qty", ""), "status": o.get("status", ""),
            } for o in orders])
            with _lock:
                _cache["orders"] = orders
        except Exception:
            pass
        _state["last_sync"] = time.time()
        _state["last_error"] = ""
        _state["syncs"] += 1
        return snapshot
    except Exception as e:
        _state["last_error"] = str(e)
        return get(_ACCT_KEY) or {}


def account(max_age_s: int = 60) -> dict:
    """Current account snapshot. Live if the cache is older than max_age_s;
    on API failure, last known synced values (never a hardcoded figure)."""
    with _lock:
        fresh = _cache["account"] and (time.time() - _cache["ts"] <= max_age_s)
        if fresh:
            return dict(_cache["account"])
    return sync_now()


def buying_power() -> float:
    """THE capital figure for position sizing. Live Alpaca buying_power,
    falling back to the last synced value from store.py."""
    return float(account().get("buying_power", 0) or 0)


def portfolio_value() -> float:
    return float(account().get("portfolio_value", 0) or 0)


def cash() -> float:
    return float(account().get("cash", 0) or 0)


def equity() -> float:
    return float(account().get("equity", 0) or 0)


def open_position_symbols() -> set:
    try:
        positions = _api("GET", "/v2/positions")
        return {p.get("symbol", "") for p in positions}
    except Exception:
        return {p.get("symbol", "") for p in (get(_POS_KEY) or [])}


# ── Pre-trade checks (Feature 5) ───────────────────────────────────────────────

def pre_trade_check(symbol: str, notional: float = 0.0,
                    allow_add: bool = False) -> tuple:
    """Run before every autonomous entry. Returns (ok, reason).
      1. buying power must cover the intended notional
      2. PDT: only restrictive under $25k equity (paper acct at $100k → free)
      3. position must not already exist (unless allow_add for scale-ins)
    """
    a = account()
    if not a:
        return False, "Alpaca account unavailable (no live data and no synced fallback)."
    bp = float(a.get("buying_power", 0) or 0)
    if notional > 0 and bp < notional:
        return False, f"Buying power ${bp:,.2f} < intended ${notional:,.2f}."
    if bp <= 0:
        return False, "No buying power available."
    eq = float(a.get("equity", 0) or 0)
    if eq < 25_000 and int(a.get("daytrade_count", 0)) >= 3:
        return False, (f"PDT guard: {a.get('daytrade_count')} day trades used and "
                       f"equity ${eq:,.0f} < $25k — day trading restricted.")
    if not allow_add and symbol and symbol.upper() in open_position_symbols():
        return False, f"{symbol.upper()} position already open — not doubling in."
    return True, "OK"


# ── Background loop ────────────────────────────────────────────────────────────

def _loop():
    while _state["running"]:
        try:
            sync_now()
        except Exception as e:
            _state["last_error"] = str(e)
        time.sleep(_SYNC_INTERVAL)


def start_account_sync() -> str:
    if _state["running"]:
        return "Account sync already running."
    if not _configured():
        return "Alpaca not configured — account sync not started."
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-account-sync").start()
    return f"Account sync started (Alpaca ground truth every {_SYNC_INTERVAL // 60} min)."


def account_status() -> str:
    """Human-readable snapshot of the synced account state (chat tool)."""
    a = account()
    if not a:
        return "No Alpaca account data (not configured or never synced)."
    age = ""
    try:
        secs = (datetime.now() - datetime.fromisoformat(a["synced_at"])).total_seconds()
        age = f"{int(secs // 60)}m ago" if secs >= 60 else "just now"
    except Exception:
        pass
    eq = float(a.get("equity", 0) or 0)
    pdt_line = ("unlimited day trades (equity ≥ $25k)" if eq >= 25_000 else
                f"{a.get('daytrade_count', 0)}/3 day trades used (equity < $25k — PDT applies)")
    return "\n".join([
        "🏦 ALPACA ACCOUNT SYNC", "━" * 30,
        f"  equity:          ${eq:>12,.2f}",
        f"  portfolio value: ${float(a.get('portfolio_value', 0) or 0):>12,.2f}",
        f"  cash:            ${float(a.get('cash', 0) or 0):>12,.2f}",
        f"  buying power:    ${float(a.get('buying_power', 0) or 0):>12,.2f}  ← sizing basis",
        f"  PDT:             {pdt_line}",
        f"  last sync:       {a.get('synced_at', '?')[:19].replace('T', ' ')} ({age})",
        f"  sync loop:       {'running' if _state['running'] else 'NOT running'}"
        + (f"  |  last error: {_state['last_error'][:60]}" if _state['last_error'] else ""),
    ])
