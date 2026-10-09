"""
flow_intel.py — JARVIS Free Market Flow Intelligence
Homegrown replacements for paid Unusual Whales signals, built entirely from
data Jarvis already has free access to (Alpaca + free Yahoo tickers) or from
genuinely free public disclosures. No paid API key, no subscription.

Honesty about fidelity — real data vs. best-effort approximation:
  congress_trades()    — REAL data. Same STOCK Act disclosures a paid feed
                         resells, pulled straight from the public Senate
                         filings via the open-source Senate Stock Watcher
                         project (github.com/timothycarambat/senate-stock-watcher-data).
  gamma_exposure()     — REAL computation from Alpaca's own live options chain
                         (open interest + Greeks), using the standard public
                         GEX approximation formula. Covers 1-45 day expiries
                         (near-term, where dealer hedging pressure matters
                         most) — not the full LEAPS-inclusive chain.
  vix_term_structure() — REAL data from free Yahoo Finance tickers
                         (^VIX9D/^VIX/^VIX3M) — a macro options-market read,
                         analogous to a market-wide flow "tide".
  block_trade_scan()   — APPROXIMATION, not true dark pool data. Alpaca's free
                         IEX trade feed does not carry off-exchange TRF/dark-
                         pool prints, so there is no free way to see them in
                         real time through this account. This flags unusually
                         large individual prints on the LIT tape instead, as a
                         rough proxy for size/institutional activity. Genuine
                         FINRA ATS dark pool volume is published free (weekly,
                         aggregated) via a developer.finra.org account — that
                         requires the user's own manual signup; say the word
                         and it can be wired in once credentials exist.
"""

import os, json, re
from datetime import datetime
from pathlib import Path

_DATA_DIR = Path.home() / "Documents" / "JARVIS" / "flow_intel"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_SSW_URL = (
    "https://raw.githubusercontent.com/timothycarambat/"
    "senate-stock-watcher-data/master/aggregate/all_transactions.json"
)


def _cache_get(key: str, ttl_minutes: int):
    f = _DATA_DIR / f"{re.sub(r'[^a-zA-Z0-9_]', '_', key)}.json"
    if f.exists():
        age = (datetime.now().timestamp() - f.stat().st_mtime) / 60
        if age < ttl_minutes:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def _cache_set(key: str, data) -> None:
    try:
        f = _DATA_DIR / f"{re.sub(r'[^a-zA-Z0-9_]', '_', key)}.json"
        f.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CONGRESSIONAL TRADING (real data, free, no key)
# ══════════════════════════════════════════════════════════════════════════════

def _load_congress_data() -> list:
    cached = _cache_get("congress_all", ttl_minutes=720)  # 12h — filings aren't real-time
    if cached is not None:
        return cached
    try:
        import requests
        r = requests.get(_SSW_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if not r.ok:
            return []
        data = r.json()
    except Exception:
        return []
    _cache_set("congress_all", data)
    return data


def congress_trades(ticker: str = "", limit: int = 15) -> str:
    """
    Recent Senate stock trades disclosed under the STOCK Act — free, public,
    same underlying filings a paid feed resells. Source updates on whatever
    cadence the open-source Senate Stock Watcher project scrapes at (not
    guaranteed real-time; filings themselves lag the actual trade by 30-45 days
    under the law regardless of source).
    """
    data = _load_congress_data()
    if not data:
        return "Could not load congressional trading data (Senate Stock Watcher feed unavailable right now)."

    sym  = ticker.upper().strip()
    rows = [d for d in data if not sym or (d.get("ticker", "") or "").upper() == sym]
    if not rows:
        return f"No congressional trades found{f' for {sym}' if sym else ''}."

    def _key(d):
        try:
            return datetime.strptime(d.get("transaction_date", ""), "%m/%d/%Y")
        except Exception:
            return datetime.min

    rows.sort(key=_key, reverse=True)

    title = f"Congressional Trading{f' — {sym}' if sym else ' (Recent, Senate)'}"
    lines = [title, "Source: public STOCK Act disclosures (Senate Stock Watcher, free)"]
    newest = _key(rows[0])
    if newest != datetime.min and (datetime.now() - newest).days > 90:
        lines.append(
            f"  WARNING: feed's newest record is {newest.strftime('%Y-%m-%d')} — "
            f"the open-source scraper behind this may have gone stale. Treat as historical, not live."
        )
    lines.append("")
    for d in rows[:limit]:
        lines.append(
            f"  {d.get('transaction_date','?'):<12} {d.get('senator','?'):<24} "
            f"{d.get('ticker','?'):<6} {d.get('type','?'):<16} {d.get('amount','?')}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GAMMA / GREEK EXPOSURE — Black-Scholes computed from real market prices
# ══════════════════════════════════════════════════════════════════════════════
# Alpaca's options contracts endpoint returns `greeks: null` on this account
# tier (verified directly — pre-computed Greeks are a premium-feed feature).
# Rather than silently report zero, this solves implied volatility from the
# actual quoted option price (standard bisection on Black-Scholes) and derives
# gamma from that — genuinely homegrown, no dependency on a broker computing
# it for us. Falls back to Alpaca's own `greeks` field first if it's ever
# populated for a given account/symbol.

_RISK_FREE_RATE = 0.045  # rough constant approximation, doesn't move gamma much


def _bs_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    import math
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    import math
    from scipy.stats import norm
    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _implied_vol(price: float, S: float, K: float, T: float, r: float, is_call: bool):
    """Bisection solve for IV — simple and numerically stable for this use case."""
    if price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None
    lo, hi = 0.01, 4.0
    for _ in range(60):
        mid = (lo + hi) / 2
        model_price = _bs_price(S, K, T, r, mid, is_call)
        if model_price > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-4:
            break
    return (lo + hi) / 2


def _bs_gamma_full(S: float, K: float, T: float, r: float, sigma: float) -> float:
    import math
    from scipy.stats import norm
    if sigma <= 0 or T <= 0 or S <= 0:
        return 0.0
    d1 = _bs_d1(S, K, T, r, sigma)
    return norm.pdf(d1) / (S * sigma * math.sqrt(T))


def _fetch_snapshots(ticker: str) -> dict:
    """Bulk options snapshots (bid/ask/last) for the whole chain in one call —
    this lives on Alpaca's market-data host, not the trading-API host."""
    try:
        import requests
        hdrs = {"APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
                "APCA-API-SECRET-KEY": os.getenv("ALPACA_API_SECRET", "")}
        r = requests.get(f"https://data.alpaca.markets/v1beta1/options/snapshots/{ticker}",
                         headers=hdrs, params={"limit": 200}, timeout=15)
        data = r.json() if r.ok else {}
    except Exception:
        data = {}
    return (data or {}).get("snapshots", {})


def gamma_exposure(ticker: str) -> str:
    """
    Homegrown dealer gamma exposure (GEX) for a symbol. Uses Alpaca's own
    Greeks when present; otherwise solves implied volatility from the real
    quoted option price and computes gamma via Black-Scholes. Near-term
    expiries (1-45 days) only — that's where dealer hedging pressure matters most.
    """
    sym = ticker.upper().strip()
    try:
        import tools.options_engine as OPT
    except Exception as e:
        return f"Options engine unavailable: {e}"

    try:
        calls = OPT._raw_contracts(sym, 1, 45, "call", limit=250)
        puts  = OPT._raw_contracts(sym, 1, 45, "put",  limit=250)
    except Exception as e:
        return f"Gamma exposure error: {e}"

    if not calls and not puts:
        return f"No options chain data for {sym}."

    spot = 0.0
    try:
        import tools.market as MKT
        spot = float(MKT._fetch_quote(sym).get("price", 0) or 0)
    except Exception:
        pass
    if not spot:
        for c in (calls + puts):
            up = c.get("underlying_price")
            if up:
                spot = float(up)
                break
    if not spot:
        return f"Could not determine {sym}'s spot price — can't compute GEX without it."

    snapshots = _fetch_snapshots(sym)
    used_bs = False

    def _gamma_for(c, is_call: bool) -> float:
        nonlocal used_bs
        real_gamma = float((c.get("greeks") or {}).get("gamma", 0) or 0)
        if real_gamma:
            return real_gamma
        # Fall back to our own Black-Scholes gamma from the quoted price
        snap = snapshots.get(c.get("symbol", ""), {})
        quote = snap.get("latestQuote", {})
        bid, ask = quote.get("bp", 0) or 0, quote.get("ap", 0) or 0
        mid = (bid + ask) / 2 if (bid and ask) else (snap.get("latestTrade", {}) or {}).get("p", 0)
        if not mid:
            return 0.0
        try:
            expiry = datetime.strptime(c.get("expiration_date", ""), "%Y-%m-%d")
            T = max((expiry - datetime.now()).days, 1) / 365.0
        except Exception:
            return 0.0
        strike = float(c.get("strike_price", 0) or 0)
        if not strike:
            return 0.0
        iv = _implied_vol(mid, spot, strike, T, _RISK_FREE_RATE, is_call)
        if not iv:
            return 0.0
        used_bs = True
        return _bs_gamma_full(spot, strike, T, _RISK_FREE_RATE, iv)

    def _gex_side(contracts, is_call: bool):
        total, by_strike = 0.0, {}
        for c in contracts:
            gamma  = _gamma_for(c, is_call)
            oi     = int(c.get("open_interest", 0) or 0)
            strike = float(c.get("strike_price", 0) or 0)
            val = gamma * oi * 100 * (spot ** 2) * 0.01
            total += val
            by_strike[strike] = by_strike.get(strike, 0.0) + val
        return total, by_strike

    call_gex, call_by_strike = _gex_side(calls, True)
    put_gex,  put_by_strike  = _gex_side(puts, False)
    net_gex = call_gex - put_gex

    all_strikes = set(call_by_strike) | set(put_by_strike)
    wall = max(
        all_strikes,
        key=lambda k: abs(call_by_strike.get(k, 0.0) - put_by_strike.get(k, 0.0)),
        default=None,
    ) if all_strikes else None

    lines = [
        f"Gamma Exposure (homegrown GEX): {sym}   spot ${spot:,.2f}",
        "Computed from Alpaca's live options chain, 1-45 day expiries (near-term only)"
        + ("  [gamma solved via Black-Scholes from real quotes — Alpaca doesn't provide "
           "pre-computed Greeks on this account tier]" if used_bs else ""),
        "",
        f"  Call GEX: {call_gex:>+18,.0f}",
        f"  Put GEX:  {put_gex:>+18,.0f}",
        f"  Net GEX:  {net_gex:>+18,.0f}",
    ]
    if wall is not None and (call_by_strike.get(wall, 0) or put_by_strike.get(wall, 0)):
        lines.append(f"  Largest strike exposure: ${wall:.2f}  (a likely 'gamma wall' / pin level)")
    lines += [
        "",
        "  Read: " + (
            "dealers net LONG gamma — hedging dampens moves, price tends to pin near the wall"
            if net_gex > 0 else
            "dealers net SHORT gamma — hedging amplifies moves, expect more volatility"
        ),
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# VIX TERM STRUCTURE (real data, free Yahoo tickers)
# ══════════════════════════════════════════════════════════════════════════════

def vix_term_structure() -> str:
    """
    Free VIX curve (9-day / 30-day / 3-month) — a macro options-market read on
    fear vs. complacency, the closest free analog to a market-wide flow tide.
    Contango (VIX9D < VIX < VIX3M) = calm. Backwardation = near-term stress.
    """
    try:
        import yfinance as yf
        vals = {}
        for label, sym in (("VIX9D", "^VIX9D"), ("VIX", "^VIX"), ("VIX3M", "^VIX3M")):
            info = yf.Ticker(sym).fast_info
            vals[label] = float(info.last_price or 0)
    except Exception as e:
        return f"VIX term structure error: {e}"

    if not all(vals.values()):
        return "Could not fetch the full VIX term structure (one or more tickers unavailable)."

    lines = [
        f"VIX Term Structure — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"  VIX9D:  {vals['VIX9D']:.2f}",
        f"  VIX:    {vals['VIX']:.2f}",
        f"  VIX3M:  {vals['VIX3M']:.2f}",
        "",
    ]
    if vals["VIX9D"] < vals["VIX"] < vals["VIX3M"]:
        read = "CONTANGO — calm/complacent market, options pricing in low near-term risk"
    elif vals["VIX9D"] > vals["VIX"] > vals["VIX3M"]:
        read = "BACKWARDATION — near-term stress priced above longer-term, often a risk-off signal"
    else:
        read = "MIXED — no clean curve shape, regime may be transitioning"
    lines.append(f"  Read: {read}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK TRADE SCAN (honest dark-pool proxy — see module docstring)
# ══════════════════════════════════════════════════════════════════════════════

def block_trade_scan(ticker: str, min_shares: int = 500) -> str:
    """
    Flags unusually large individual prints on the public LIT tape as a rough
    proxy for institutional/block activity. This is NOT true dark pool data —
    see the module docstring for why, and how to get the real free FINRA feed.
    """
    sym = ticker.upper().strip()
    try:
        import tools.social_intel as SOC
    except Exception as e:
        return f"Trade tape unavailable: {e}"

    data   = SOC._alpaca_data_get(f"/v2/stocks/{sym}/trades", params={"limit": 300, "feed": "iex"})
    trades = (data or {}).get("trades", [])
    if not trades:
        return f"No trade tape available for {sym}."

    blocks = [t for t in trades if (t.get("s", 0) or 0) >= min_shares]
    blocks.sort(key=lambda t: t.get("s", 0) or 0, reverse=True)

    lines = [
        f"Block Trade Scan (dark-pool proxy): {sym}",
        f"Flagging prints >= {min_shares:,} shares from the last {len(trades)} lit-tape trades",
        "NOTE: approximation, not real dark pool/ATS data — Alpaca's free feed "
        "doesn't carry off-exchange prints. Real FINRA dark pool volume is free "
        "via a developer.finra.org account if you want it wired in.",
        "",
    ]
    if not blocks:
        lines.append(f"  No prints >= {min_shares:,} shares in the recent tape.")
    else:
        for t in blocks[:10]:
            price = t.get("p", 0)
            size  = t.get("s", 0)
            ts    = (t.get("t", "") or "")[:19].replace("T", " ")
            lines.append(f"  {size:>7,}sh @ ${price:.2f}   {ts}")
    return "\n".join(lines)
