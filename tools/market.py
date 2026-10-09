"""
market.py — JARVIS Market Intelligence Engine
Real technical analysis, trading signals, crypto, watchlists, web fetch,
automated scanning, and retirement planning tools.

Dependencies (all optional — graceful fallbacks):
  pip install yfinance requests beautifulsoup4 numpy
"""

import os, json, re, math, time, threading, subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ── Shared helpers ─────────────────────────────────────────────────────────────

_DATA_DIR = Path.home() / "Documents" / "JARVIS" / "market"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_WATCHLIST_FILE  = _DATA_DIR / "watchlist.json"
_TRADES_FILE     = _DATA_DIR / "paper_trades.json"
_SIGNALS_FILE    = _DATA_DIR / "signals_log.json"
_STRATEGY_FILE   = _DATA_DIR / "strategies.json"

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

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

def _ai(prompt: str, system: str = "") -> str:
    try:
        import requests
        payload = {"model": _OLLAMA_MODEL, "prompt": prompt,
                   "system": system or "You are a sharp financial analyst. Be direct, specific, and concise.",
                   "stream": False}
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=20)
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return "(AI unavailable)"

def _alpaca_get(path: str):
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_API_SECRET", "")
    base   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key:
        return None
    try:
        import requests
        hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        data_base = "https://data.alpaca.markets"
        url = (data_base if path.startswith("/data") else base) + path.replace("/data", "", 1)
        r = requests.get(url, headers=hdrs, timeout=8)
        return r.json() if r.ok else None
    except Exception:
        return None

# ── Price data ─────────────────────────────────────────────────────────────────

def _fetch_history(symbol: str, days: int = 90) -> list[dict]:
    """
    Fetch OHLCV bars for a stock symbol.
    Tries yfinance first, falls back to Alpaca, then Yahoo Finance scrape.
    Returns list of dicts: {date, open, high, low, close, volume}
    """
    symbol = symbol.upper()

    # yfinance (most reliable free source)
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        hist = tk.history(period=f"{days}d", interval="1d", auto_adjust=True)
        if not hist.empty:
            rows = []
            for dt, row in hist.iterrows():
                rows.append({
                    "date":   str(dt.date()),
                    "open":   float(row["Open"]),
                    "high":   float(row["High"]),
                    "low":    float(row["Low"]),
                    "close":  float(row["Close"]),
                    "volume": int(row["Volume"]),
                })
            return rows
    except Exception:
        pass

    # Alpaca market data
    try:
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        data  = _alpaca_get(f"/data/v2/stocks/{symbol}/bars?timeframe=1Day&start={start}&limit=200")
        if data and "bars" in data:
            return [{
                "date":   b["t"][:10],
                "open":   b["o"], "high": b["h"],
                "low":    b["l"], "close": b["c"],
                "volume": b["v"],
            } for b in data["bars"]]
    except Exception:
        pass

    return []


def _fetch_quote(symbol: str) -> dict:
    """Get the current price and basic info for a symbol."""
    symbol = symbol.upper()
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).fast_info
        return {
            "symbol": symbol,
            "price":  round(float(info.last_price or 0), 2),
            "prev":   round(float(info.previous_close or 0), 2),
            "high52": round(float(info.year_high or 0), 2),
            "low52":  round(float(info.year_low or 0), 2),
            "mktcap": int(info.market_cap or 0),
        }
    except Exception:
        pass

    # Alpaca latest bar
    try:
        data = _alpaca_get(f"/data/v2/stocks/{symbol}/bars/latest")
        if data and "bar" in data:
            b = data["bar"]
            return {"symbol": symbol, "price": b["c"], "prev": b["o"],
                    "high52": 0, "low52": 0, "mktcap": 0}
    except Exception:
        pass

    return {"symbol": symbol, "price": 0, "prev": 0, "high52": 0, "low52": 0, "mktcap": 0}


# ── Technical Analysis ─────────────────────────────────────────────────────────

def _compute_ta(bars: list[dict]) -> dict:
    """
    Compute technical indicators from OHLCV bars.
    Returns dict of indicator values.
    """
    if len(bars) < 20:
        return {}

    closes  = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    highs   = [b["high"]  for b in bars]
    lows    = [b["low"]   for b in bars]

    def sma(data, n):
        if len(data) < n:
            return None
        return sum(data[-n:]) / n

    def ema(data, n):
        if len(data) < n:
            return None
        k = 2 / (n + 1)
        e = data[0]
        for v in data[1:]:
            e = v * k + e * (1 - k)
        return round(e, 4)

    def rsi(data, n=14):
        if len(data) < n + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(data)):
            d = data[i] - data[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        ag = sum(gains[-n:]) / n
        al = sum(losses[-n:]) / n
        if al == 0:
            return 100.0
        rs = ag / al
        return round(100 - (100 / (1 + rs)), 2)

    def bollinger(data, n=20, k=2):
        if len(data) < n:
            return None, None, None
        window = data[-n:]
        mid = sum(window) / n
        std = math.sqrt(sum((x - mid) ** 2 for x in window) / n)
        return round(mid - k * std, 2), round(mid, 2), round(mid + k * std, 2)

    def macd(data):
        if len(data) < 26:
            return None, None, None
        e12 = ema(data, 12)
        e26 = ema(data, 26)
        if e12 is None or e26 is None:
            return None, None, None
        line = round(e12 - e26, 4)
        # Approximate signal (9-period EMA of MACD — simplified)
        macd_series = []
        for i in range(9, len(data) + 1):
            e12i = ema(data[:i], 12)
            e26i = ema(data[:i], 26)
            if e12i and e26i:
                macd_series.append(e12i - e26i)
        sig = ema(macd_series, 9) if len(macd_series) >= 9 else line
        hist_val = round(line - (sig or line), 4)
        return line, round(sig, 4) if sig else None, hist_val

    price   = closes[-1]
    sma20   = sma(closes, 20)
    sma50   = sma(closes, 50)
    sma200  = sma(closes, 200)
    rsi14   = rsi(closes)
    bb_low, bb_mid, bb_high = bollinger(closes)
    macd_line, macd_sig, macd_hist = macd(closes)
    avg_vol = sma(volumes, 20)
    cur_vol = volumes[-1]

    # ATR (Average True Range — volatility)
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = highs[i], lows[i], closes[i-1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sma(trs, 14) if len(trs) >= 14 else None

    return {
        "price":      round(price, 2),
        "sma20":      round(sma20, 2)  if sma20  else None,
        "sma50":      round(sma50, 2)  if sma50  else None,
        "sma200":     round(sma200, 2) if sma200 else None,
        "rsi":        rsi14,
        "bb_low":     bb_low,
        "bb_mid":     bb_mid,
        "bb_high":    bb_high,
        "macd":       macd_line,
        "macd_sig":   macd_sig,
        "macd_hist":  macd_hist,
        "atr":        round(atr, 2) if atr else None,
        "vol":        cur_vol,
        "avg_vol":    int(avg_vol) if avg_vol else None,
        "vol_ratio":  round(cur_vol / avg_vol, 2) if avg_vol else None,
        "pct_change": round((price - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else 0,
        "chg_5d":     round((price - closes[-6]) / closes[-6] * 100, 2) if len(closes) > 5 else None,
        "chg_30d":    round((price - closes[-31]) / closes[-31] * 100, 2) if len(closes) > 30 else None,
    }


def _score_signal(ta: dict) -> tuple[str, int, list[str]]:
    """
    Score technical signals. Returns (verdict, score -10 to +10, reasons).
    Positive score = bullish, negative = bearish.
    """
    score   = 0
    reasons = []
    price   = ta.get("price", 0)

    # RSI
    rsi = ta.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 3
            reasons.append(f"RSI {rsi} — oversold (bullish)")
        elif rsi < 40:
            score += 1
            reasons.append(f"RSI {rsi} — approaching oversold")
        elif rsi > 70:
            score -= 3
            reasons.append(f"RSI {rsi} — overbought (bearish)")
        elif rsi > 60:
            score -= 1
            reasons.append(f"RSI {rsi} — elevated")

    # Moving averages
    sma50  = ta.get("sma50")
    sma200 = ta.get("sma200")
    sma20  = ta.get("sma20")
    if sma50 and sma200:
        if sma50 > sma200:
            score += 2
            reasons.append("Golden cross (50MA > 200MA) — long-term bullish")
        else:
            score -= 2
            reasons.append("Death cross (50MA < 200MA) — long-term bearish")
    if sma20 and price > sma20:
        score += 1
        reasons.append(f"Price ${price} above 20MA ${sma20}")
    elif sma20 and price < sma20:
        score -= 1
        reasons.append(f"Price ${price} below 20MA ${sma20}")
    if sma50 and price > sma50:
        score += 1
        reasons.append(f"Above 50MA ${sma50}")
    elif sma50 and price < sma50:
        score -= 1
        reasons.append(f"Below 50MA ${sma50}")

    # MACD
    macd_line = ta.get("macd")
    macd_sig  = ta.get("macd_sig")
    macd_hist = ta.get("macd_hist")
    if macd_line is not None and macd_sig is not None:
        if macd_line > macd_sig:
            score += 2
            reasons.append(f"MACD {macd_line:.3f} above signal — bullish momentum")
        else:
            score -= 2
            reasons.append(f"MACD {macd_line:.3f} below signal — bearish momentum")

    # Bollinger Bands
    bb_low  = ta.get("bb_low")
    bb_high = ta.get("bb_high")
    if bb_low and bb_high and price:
        if price <= bb_low:
            score += 2
            reasons.append(f"Price at/below lower Bollinger Band ${bb_low} — mean reversion likely")
        elif price >= bb_high:
            score -= 2
            reasons.append(f"Price at/above upper Bollinger Band ${bb_high} — extended")

    # Volume confirmation
    vol_ratio = ta.get("vol_ratio")
    if vol_ratio and vol_ratio > 1.5:
        reasons.append(f"Volume {vol_ratio:.1f}x average — strong conviction in move")
    elif vol_ratio and vol_ratio < 0.6:
        reasons.append(f"Low volume {vol_ratio:.1f}x average — weak conviction")

    score = max(-10, min(10, score))
    if score >= 4:
        verdict = "STRONG BUY"
    elif score >= 2:
        verdict = "BUY"
    elif score <= -4:
        verdict = "STRONG SELL"
    elif score <= -2:
        verdict = "SELL"
    else:
        verdict = "HOLD / NEUTRAL"

    return verdict, score, reasons


# ── Public API: Technical Analysis ────────────────────────────────────────────

def market_technicals(symbol: str, days: int = 90) -> str:
    """
    Full technical analysis for a stock symbol.
    Computes RSI, MACD, Bollinger Bands, Moving Averages, ATR, volume.
    """
    symbol = symbol.upper().strip()
    bars = _fetch_history(symbol, days)
    if not bars:
        return f"Could not fetch price data for {symbol}. Check symbol or install: pip install yfinance"

    ta = _compute_ta(bars)
    if not ta:
        return f"Not enough data for {symbol} (need at least 20 bars)."

    price = ta["price"]
    lines = [
        f"Technical Analysis: {symbol}",
        f"  Price:     ${price:,.2f}  ({ta.get('pct_change', 0):+.2f}% today)",
        f"  5d:        {ta.get('chg_5d', 'N/A'):+.2f}%   30d: {ta.get('chg_30d', 'N/A'):+.2f}%",
        "",
        f"  RSI(14):   {ta.get('rsi', 'N/A')}   {'🔴 Overbought' if (ta.get('rsi') or 50) > 70 else '🟢 Oversold' if (ta.get('rsi') or 50) < 30 else '⚪ Neutral'}",
        f"  SMA 20:    ${ta.get('sma20', 'N/A')}",
        f"  SMA 50:    ${ta.get('sma50', 'N/A')}",
        f"  SMA 200:   ${ta.get('sma200', 'N/A')}",
        f"  MACD:      {ta.get('macd', 'N/A')}  Signal: {ta.get('macd_sig', 'N/A')}",
        f"  BB:        ${ta.get('bb_low', 'N/A')} / ${ta.get('bb_mid', 'N/A')} / ${ta.get('bb_high', 'N/A')}",
        f"  ATR(14):   ${ta.get('atr', 'N/A')}",
        f"  Volume:    {ta.get('vol', 0):,}  ({ta.get('vol_ratio', 1.0):.1f}x avg)",
    ]

    verdict, score, reasons = _score_signal(ta)
    lines += [
        "",
        f"  Signal:    {verdict} (score {score:+d}/10)",
        "  Reasons:",
    ] + [f"    • {r}" for r in reasons]

    try:
        import tools.charts as CHARTS
        chart_path = CHARTS.price_chart(symbol, bars, ta)
        if chart_path:
            lines += ["", f"Chart saved: {chart_path}"]
    except Exception:
        pass

    return "\n".join(lines)


def chart_price(symbol: str, days: int = 90) -> str:
    """
    Draw a price chart for any symbol — line chart with SMA20/50/200 overlays
    and an RSI sub-panel. Use for 'chart AAPL', 'graph NVDA', 'plot TSLA'.
    """
    symbol = symbol.upper().strip()
    bars = _fetch_history(symbol, days)
    if not bars:
        return f"Could not fetch price data for {symbol}."
    ta = _compute_ta(bars) or {}
    try:
        import tools.charts as CHARTS
        chart_path = CHARTS.price_chart(symbol, bars, ta)
        if not chart_path:
            return f"Could not render a chart for {symbol}."
        return f"{symbol} price chart ({days}d, SMA20/50/200 + RSI).\nChart saved: {chart_path}"
    except Exception as e:
        return f"Chart error: {e}"


def trade_signal(symbol: str) -> str:
    """
    Generate a BUY / SELL / HOLD signal with full reasoning.
    Combines technical analysis with AI interpretation.
    """
    symbol = symbol.upper().strip()
    bars = _fetch_history(symbol, 120)
    if not bars:
        return f"No data for {symbol}."

    ta = _compute_ta(bars)
    if not ta:
        return f"Insufficient history for {symbol}."

    verdict, score, reasons = _score_signal(ta)

    # ATR-based stop and target
    price = ta["price"]
    atr   = ta.get("atr") or price * 0.02
    stop  = round(price - atr * 1.5, 2)
    tgt1  = round(price + atr * 2.0, 2)
    tgt2  = round(price + atr * 4.0, 2)
    risk_reward = round(atr * 2.0 / (atr * 1.5), 2)

    ai_take = _ai(
        f"Stock {symbol} at ${price}. TA signal: {verdict} (score {score}/10). "
        f"RSI {ta.get('rsi')}, MACD {'bullish' if (ta.get('macd') or 0) > (ta.get('macd_sig') or 0) else 'bearish'}, "
        f"price {'above' if price > (ta.get('sma50') or price) else 'below'} 50MA. "
        f"Give your 2-sentence view on this trade and whether you agree with the signal.",
        system="You are a seasoned day trader and technical analyst. Be direct and opinionated."
    )

    # Log to signals file
    log = _load(_SIGNALS_FILE, [])
    log.append({
        "symbol": symbol, "verdict": verdict, "score": score,
        "price": price, "timestamp": datetime.now().isoformat(),
    })
    _save(_SIGNALS_FILE, log[-500:])

    lines = [
        f"Signal: {symbol} — {verdict}",
        f"  Price:    ${price:,.2f}",
        f"  Score:    {score:+d}/10",
        "",
        "  Trade Setup:",
        f"    Entry:      ${price:,.2f}",
        f"    Stop Loss:  ${stop:,.2f}  (1.5x ATR = ${atr:.2f})",
        f"    Target 1:   ${tgt1:,.2f}  (+{((tgt1-price)/price*100):.1f}%)",
        f"    Target 2:   ${tgt2:,.2f}  (+{((tgt2-price)/price*100):.1f}%)",
        f"    Risk/Reward: {risk_reward:.2f}:1",
        "",
        "  Why:",
    ] + [f"    • {r}" for r in reasons] + [
        "",
        f"  AI Take: {ai_take}",
    ]
    return "\n".join(lines)


def market_scan(symbols: str = "") -> str:
    """
    Scan multiple symbols for trade signals.
    symbols: comma-separated list, or 'sp500' / 'tech' / 'watchlist'
    """
    presets = {
        "sp500":     ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"],
        "tech":      ["NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "AMZN", "TSM", "AVGO", "ORCL"],
        "finance":   ["JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B", "C", "WFC", "AXP"],
        "energy":    ["XOM", "CVX", "COP", "SLB", "EOG", "PXD", "OXY", "MPC", "PSX", "VLO"],
        "watchlist": list(_load(_WATCHLIST_FILE, {}).keys()),
        "crypto_stocks": ["COIN", "MSTR", "MARA", "RIOT", "HUT", "CLSK"],
    }

    if not symbols or symbols.lower() in presets:
        syms = presets.get(symbols.lower() if symbols else "sp500", presets["sp500"])
    else:
        syms = [s.strip().upper() for s in symbols.replace(",", " ").split() if s.strip()]

    if not syms:
        return "No symbols to scan. Add to watchlist or specify symbols."

    results = []
    for sym in syms[:15]:  # cap at 15 to avoid long waits
        bars = _fetch_history(sym, 90)
        if not bars:
            results.append({"symbol": sym, "verdict": "NO DATA", "score": 0, "price": 0})
            continue
        ta = _compute_ta(bars)
        if not ta:
            continue
        verdict, score, _ = _score_signal(ta)
        results.append({
            "symbol": sym, "verdict": verdict, "score": score,
            "price": ta["price"], "rsi": ta.get("rsi"), "pct": ta.get("pct_change", 0)
        })
        time.sleep(0.3)  # rate limit

    results.sort(key=lambda x: -x["score"])

    lines = [f"Market Scan — {len(results)} symbols — {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for r in results:
        bar   = "+" * max(0, r["score"]) if r["score"] > 0 else "-" * max(0, -r["score"])
        lines.append(
            f"  {r['symbol']:<8} ${r['price']:<9,.2f} "
            f"RSI:{r.get('rsi') or '?':<6} {r['pct']:+.1f}%   "
            f"[{r['score']:+2d}] {r['verdict']:<15}  {bar}"
        )

    buys  = [r for r in results if "BUY" in r["verdict"]]
    sells = [r for r in results if "SELL" in r["verdict"]]

    lines += [
        "",
        f"  Top Buys:  {', '.join(r['symbol'] for r in buys[:3]) or 'none'}",
        f"  Top Sells: {', '.join(r['symbol'] for r in sells[:3]) or 'none'}",
    ]
    try:
        import tools.charts as CHARTS
        chart_path = CHARTS.market_scan_chart(results)
        if chart_path:
            lines += ["", f"Chart saved: {chart_path}"]
    except Exception:
        pass
    return "\n".join(lines)


# ── Watchlist ──────────────────────────────────────────────────────────────────

def watchlist_add(symbol: str, note: str = "") -> str:
    """Add a symbol to the watchlist."""
    wl = _load(_WATCHLIST_FILE, {})
    symbol = symbol.upper().strip()
    wl[symbol] = {"added": datetime.now().isoformat(), "note": note}
    _save(_WATCHLIST_FILE, wl)
    return f"Added {symbol} to watchlist. ({len(wl)} total)"


def watchlist_remove(symbol: str) -> str:
    """Remove a symbol from the watchlist."""
    wl = _load(_WATCHLIST_FILE, {})
    symbol = symbol.upper().strip()
    if symbol in wl:
        del wl[symbol]
        _save(_WATCHLIST_FILE, wl)
        return f"Removed {symbol} from watchlist."
    return f"{symbol} not in watchlist."


def watchlist_view() -> str:
    """Show the current watchlist with live prices and signals."""
    wl = _load(_WATCHLIST_FILE, {})
    if not wl:
        return "Watchlist is empty. Say 'watchlist add AAPL' to start."

    lines = [f"Watchlist ({len(wl)} symbols):", ""]
    for sym, info in wl.items():
        bars = _fetch_history(sym, 60)
        if bars:
            ta = _compute_ta(bars)
            verdict, score, _ = _score_signal(ta)
            p   = ta.get("price", 0)
            rsi = ta.get("rsi", "?")
            pct = ta.get("pct_change", 0)
            lines.append(f"  {sym:<8} ${p:<9,.2f} RSI:{rsi:<5} {pct:+.2f}%  [{score:+d}] {verdict}"
                         + (f"  — {info['note']}" if info.get("note") else ""))
        else:
            lines.append(f"  {sym:<8} (no data)")
        time.sleep(0.2)

    return "\n".join(lines)


def watchlist_alert(price_target: float = 0, symbol: str = "") -> str:
    """Set a price alert for a symbol. Checks in background."""
    wl = _load(_WATCHLIST_FILE, {})
    symbol = symbol.upper().strip()
    if symbol not in wl:
        wl[symbol] = {"added": datetime.now().isoformat(), "note": ""}
    wl[symbol]["alert_price"] = float(price_target)
    _save(_WATCHLIST_FILE, wl)
    return f"Alert set: notify when {symbol} reaches ${price_target:,.2f}"


# ── Crypto ─────────────────────────────────────────────────────────────────────

_CRYPTO_IDS = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "xrp": "ripple", "ada": "cardano", "doge": "dogecoin",
    "bnb": "binancecoin", "avax": "avalanche-2", "link": "chainlink",
    "dot": "polkadot", "matic": "matic-network", "uni": "uniswap",
    "atom": "cosmos", "ltc": "litecoin", "shib": "shiba-inu",
    "pepe": "pepe", "arb": "arbitrum", "op": "optimism",
}

def crypto_price(coins: str = "btc,eth,sol") -> str:
    """Get current crypto prices. coins: comma-separated list (btc, eth, sol, etc.)"""
    coin_list = [c.strip().lower() for c in coins.replace(",", " ").split() if c.strip()]
    ids = [_CRYPTO_IDS.get(c, c) for c in coin_list]

    try:
        import requests
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
        r = requests.get(url, timeout=8)
        if not r.ok:
            return f"CoinGecko API error: {r.status_code}"
        data = r.json()

        lines = [f"Crypto Prices — {datetime.now().strftime('%H:%M:%S')}", ""]
        for coin_sym, coin_id in zip(coin_list, ids):
            d = data.get(coin_id, {})
            price  = d.get("usd", 0)
            change = d.get("usd_24h_change", 0) or 0
            mcap   = d.get("usd_market_cap", 0) or 0
            arrow  = "▲" if change >= 0 else "▼"
            lines.append(
                f"  {coin_sym.upper():<6}  ${price:>12,.4f}  {arrow}{change:+.2f}%"
                + (f"  MCap: ${mcap/1e9:.1f}B" if mcap > 0 else "")
            )
        return "\n".join(lines)

    except ImportError:
        return "Install requests: pip install requests"
    except Exception as e:
        return f"Crypto price error: {e}"


def crypto_dominance() -> str:
    """Get BTC dominance and overall crypto market cap."""
    try:
        import requests
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=8)
        if not r.ok:
            return f"API error: {r.status_code}"
        d = r.json().get("data", {})
        mcap   = d.get("total_market_cap", {}).get("usd", 0)
        vol    = d.get("total_volume", {}).get("usd", 0)
        btc_d  = d.get("market_cap_percentage", {}).get("btc", 0)
        eth_d  = d.get("market_cap_percentage", {}).get("eth", 0)
        trend  = d.get("market_cap_change_percentage_24h_usd", 0)

        return "\n".join([
            f"Crypto Market Overview",
            f"  Total Market Cap: ${mcap/1e12:.2f}T  ({trend:+.2f}% 24h)",
            f"  24h Volume:       ${vol/1e9:.1f}B",
            f"  BTC Dominance:    {btc_d:.1f}%",
            f"  ETH Dominance:    {eth_d:.1f}%",
            f"  Alt Season:       {'Yes — alts outperforming' if btc_d < 45 else 'No — BTC dominant' if btc_d > 55 else 'Neutral'}",
        ])
    except Exception as e:
        return f"Error: {e}"


def crypto_analyze(coin: str = "bitcoin") -> str:
    """Technical analysis on a top crypto using CoinGecko OHLCV data."""
    coin_id = _CRYPTO_IDS.get(coin.lower().strip(), coin.lower().strip())
    try:
        import requests
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc?vs_currency=usd&days=90",
            timeout=10
        )
        if not r.ok:
            return f"No OHLCV data for {coin}."
        raw = r.json()  # [[timestamp, o, h, l, c], ...]
        bars = [{"date": str(datetime.fromtimestamp(x[0]/1000).date()),
                 "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": 0}
                for x in raw]
        if not bars:
            return f"No data for {coin}."
        ta = _compute_ta(bars)
        if not ta:
            return "Insufficient data."
        verdict, score, reasons = _score_signal(ta)
        lines = [
            f"Crypto TA: {coin.upper()} (CoinGecko)",
            f"  Price:  ${ta['price']:,.4f}  ({ta.get('pct_change', 0):+.2f}%)",
            f"  RSI:    {ta.get('rsi', 'N/A')}",
            f"  MACD:   {ta.get('macd', 'N/A')}",
            f"  BB:     ${ta.get('bb_low', 'N/A')} / ${ta.get('bb_high', 'N/A')}",
            f"  Signal: {verdict} ({score:+d}/10)",
            "",
            "  Reasons:",
        ] + [f"    • {r}" for r in reasons]
        return "\n".join(lines)
    except Exception as e:
        return f"Crypto analysis error: {e}"


# ── Paper Trading Tracker ──────────────────────────────────────────────────────

def paper_trade(symbol: str, action: str, shares: float, price: float = 0) -> str:
    """
    Log a paper trade for strategy tracking and P/L calculation.
    action: buy / sell
    """
    symbol = symbol.upper().strip()
    if price == 0:
        bars = _fetch_history(symbol, 5)
        price = bars[-1]["close"] if bars else 0
    if price == 0:
        return f"Could not get price for {symbol}. Specify price manually."

    trades = _load(_TRADES_FILE, [])
    trades.append({
        "symbol":    symbol,
        "action":    action.lower(),
        "shares":    float(shares),
        "price":     float(price),
        "value":     round(float(shares) * float(price), 2),
        "timestamp": datetime.now().isoformat(),
        "open":      True,
    })
    _save(_TRADES_FILE, trades)
    total = round(float(shares) * float(price), 2)
    return f"Paper {action.upper()}: {shares} {symbol} @ ${price:,.2f} = ${total:,.2f}"


def paper_portfolio() -> str:
    """Show all open paper positions with current P/L."""
    trades = _load(_TRADES_FILE, [])
    buys   = {}
    sells  = {}

    for t in trades:
        sym = t["symbol"]
        if t["action"] == "buy":
            buys.setdefault(sym, []).append(t)
        else:
            sells.setdefault(sym, []).append(t)

    if not buys:
        return "No paper positions. Say 'paper buy AAPL 10' to start."

    lines = [f"Paper Trading Portfolio — {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    total_cost = 0
    total_val  = 0

    for sym, buy_trades in buys.items():
        total_shares = sum(t["shares"] for t in buy_trades)
        avg_price    = sum(t["shares"] * t["price"] for t in buy_trades) / total_shares

        # Current price
        bars  = _fetch_history(sym, 5)
        cur   = bars[-1]["close"] if bars else avg_price
        cost  = total_shares * avg_price
        value = total_shares * cur
        pl    = value - cost
        plp   = (pl / cost * 100) if cost else 0

        total_cost += cost
        total_val  += value

        lines.append(
            f"  {sym:<8} {total_shares}sh @ ${avg_price:,.2f} → ${cur:,.2f}  "
            f"P/L: ${pl:+,.2f} ({plp:+.1f}%)"
        )
        time.sleep(0.2)

    total_pl = total_val - total_cost
    lines += [
        "",
        f"  Total Cost:  ${total_cost:,.2f}",
        f"  Total Value: ${total_val:,.2f}",
        f"  Total P/L:   ${total_pl:+,.2f} ({(total_pl/total_cost*100 if total_cost else 0):+.1f}%)",
    ]
    return "\n".join(lines)


# ── Web Intelligence ───────────────────────────────────────────────────────────

def web_fetch(url: str, max_chars: int = 3000) -> str:
    """
    Fetch and read the text content of any web page.
    Strips HTML tags, returns readable text.
    """
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url.strip(), headers=headers, timeout=10)
        if not r.ok:
            return f"HTTP {r.status_code}: {url}"

        # Strip HTML
        text = r.text
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>',  ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'\s{3,}', '\n', text)
        text = text.strip()

        return text[:max_chars] + (f"\n\n[...truncated, {len(text)-max_chars} chars remaining]" if len(text) > max_chars else "")
    except ImportError:
        return "Install requests: pip install requests"
    except Exception as e:
        return f"Fetch error: {e}"


def news_fetch(query: str = "stock market", num: int = 5) -> str:
    """
    Fetch real news headlines for a topic.
    Uses Hacker News API for tech, Google News RSS for everything else.
    """
    query_l = query.lower()

    # Hacker News for tech topics
    if any(w in query_l for w in ["tech", "ai", "software", "startup", "developer", "nvidia", "openai"]):
        try:
            import requests
            r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=5)
            ids = r.json()[:20] if r.ok else []
            articles = []
            for aid in ids[:num + 3]:
                ar = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{aid}.json", timeout=3)
                if ar.ok:
                    d = ar.json()
                    if d.get("title") and query_l.split()[0] in d.get("title", "").lower() or True:
                        articles.append({"title": d.get("title", ""), "url": d.get("url", ""), "score": d.get("score", 0)})
                        if len(articles) >= num:
                            break

            if articles:
                lines = [f"Hacker News — Top Stories (filtered: {query})", ""]
                for a in articles:
                    lines.append(f"  [{a['score']}pts] {a['title']}")
                    if a.get("url"):
                        lines.append(f"         {a['url']}")
                return "\n".join(lines)
        except Exception:
            pass

    # Google News RSS for market/finance/general
    try:
        import requests
        rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(rss_url, timeout=8)
        if r.ok:
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            titles = [t for t in titles if t != "Google News"][1:num+1]  # skip feed title
            links  = re.findall(r'<link>(https?://[^<]+)</link>', r.text)[:num]
            if titles:
                lines = [f"News: {query}", ""]
                for i, title in enumerate(titles):
                    lines.append(f"  {i+1}. {title}")
                    if i < len(links):
                        lines.append(f"     {links[i]}")
                return "\n".join(lines)
    except Exception:
        pass

    return f"Could not fetch news for '{query}'. Install requests: pip install requests"


def news_sentiment(ticker: str) -> str:
    """
    Fetch recent news for a stock ticker and have AI analyze market sentiment.
    """
    ticker = ticker.upper().strip()
    news_text = news_fetch(f"{ticker} stock earnings revenue", num=6)
    if "Could not" in news_text:
        return news_text

    analysis = _ai(
        f"Here are recent news headlines for {ticker}:\n\n{news_text}\n\n"
        f"Rate the overall sentiment: BULLISH / BEARISH / NEUTRAL. "
        f"List 3 key themes. 1 sentence each. Be direct.",
        system="You are a financial news analyst. Extract actionable signal from news."
    )
    return f"News Sentiment: {ticker}\n\n{news_text}\n\nSentiment Analysis:\n{analysis}"


def company_research(company: str) -> str:
    """
    Comprehensive live research on any company — public or private.
    Automatically finds the stock ticker, gets live price and technicals if
    publicly traded, checks IPO/private status, and pulls current news.
    Works for SpaceX, Stripe, Nvidia, any company name.
    """
    company = company.strip()
    # A PERSON is never a stock lookup: political figures/CEOs route to
    # role-based market-impact analysis instead of a yfinance ticker search.
    try:
        import tools.political_intel as PI
        if PI.is_person(company):
            return PI.person_impact(company)
    except Exception:
        pass
    lines   = [f"Company Research: {company}", "=" * 42, ""]
    ticker  = None
    is_public = False

    # ── 1. Find ticker via Yahoo Finance search API ─────────────────────────────
    try:
        import requests
        qs  = requests.utils.quote(company)
        url = (f"https://query1.finance.yahoo.com/v1/finance/search"
               f"?q={qs}&quotesCount=5&newsCount=0&enableFuzzyQuery=false")
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=8)
        if r.ok:
            quotes = r.json().get("quotes", [])
            # Prefer EQUITY type; skip indices / futures
            for q in quotes:
                if q.get("quoteType", "") in ("EQUITY", "ETF"):
                    ticker    = q.get("symbol", "").upper()
                    long_name = q.get("longname") or q.get("shortname", ticker)
                    exchange  = q.get("exchange", "?")
                    is_public = True
                    lines.append(f"Public Ticker:  {ticker}")
                    lines.append(f"Name:           {long_name}")
                    lines.append(f"Exchange:       {exchange}")
                    break
    except Exception:
        pass

    # ── 2. Live price + key stats ───────────────────────────────────────────────
    if ticker and is_public:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            price  = getattr(info, "last_price",  None)
            mktcap = getattr(info, "market_cap",  None)
            prev   = getattr(info, "previous_close", None)
            chg    = ((price - prev) / prev * 100) if price and prev else None
            lines.append(f"Last Price:     ${price:,.2f}" if price else "")
            if mktcap:
                cap_str = (f"${mktcap/1e12:.2f}T" if mktcap >= 1e12
                           else f"${mktcap/1e9:.1f}B" if mktcap >= 1e9
                           else f"${mktcap/1e6:.0f}M")
                lines.append(f"Market Cap:     {cap_str}")
            if chg is not None:
                arrow = "▲" if chg >= 0 else "▼"
                lines.append(f"Day Change:     {arrow} {chg:+.2f}%")
        except Exception:
            pass

        # ── 3. Technical Analysis ───────────────────────────────────────────────
        try:
            bars = _fetch_history(ticker, days=60)
            if bars:
                ta   = _compute_ta(bars)
                verdict, score, reasons = _score_signal(ta)
                lines += [
                    "",
                    "Technical Analysis:",
                    f"  Signal:  {verdict} (score {score:+d})",
                    f"  RSI(14): {ta.get('rsi', 0):.1f}",
                    f"  MACD:    {'bullish cross' if ta.get('macd_cross') == 'bull' else 'bearish cross' if ta.get('macd_cross') == 'bear' else 'neutral'}",
                    f"  vs SMA200: {'above' if ta.get('above_200ma') else 'below'}",
                ]
                if reasons:
                    lines.append(f"  Reasons: {', '.join(reasons[:3])}")
        except Exception:
            pass
    else:
        # ── Private company ─────────────────────────────────────────────────────
        lines.append(f"Status:         Private — not listed on major public exchanges")
        lines.append(f"                (No ticker found via Yahoo Finance search)")

    # ── 4. Live news — always, regardless of public/private status ──────────────
    try:
        news = news_fetch(f"{company} stock IPO valuation funding acquisition 2025 2026", num=7)
        lines += ["", "Current News & Developments:", news]
    except Exception:
        pass

    # ── 5. AI summary ───────────────────────────────────────────────────────────
    context = "\n".join(lines)
    summary = _ai(
        f"Based on this data about {company}:\n\n{context}\n\n"
        f"Give a 3-sentence investment/trade summary: "
        f"1) What is this company's current status (public/private/IPO pending)? "
        f"2) Is it worth watching or trading right now? "
        f"3) What is the single biggest catalyst or risk? Be direct.",
        system="You are a sharp financial analyst. Answer strictly from the data provided, not training memory."
    )
    lines += ["", "Investment Summary:", summary]

    return "\n".join(l for l in lines if l is not None)


def reddit_sentiment(ticker: str) -> str:
    """
    Fetch WSB / stocks subreddit mentions for a ticker via Reddit RSS.
    """
    ticker = ticker.upper().strip()
    try:
        import requests
        headers = {"User-Agent": "JARVIS/4.0 market-tool"}
        urls = [
            f"https://www.reddit.com/r/wallstreetbets/search.json?q={ticker}&sort=new&limit=10",
            f"https://www.reddit.com/r/stocks/search.json?q={ticker}&sort=new&limit=5",
        ]
        posts = []
        for url in urls:
            r = requests.get(url, headers=headers, timeout=8)
            if r.ok:
                data = r.json()
                for p in data.get("data", {}).get("children", []):
                    d = p.get("data", {})
                    posts.append({
                        "title":  d.get("title", ""),
                        "score":  d.get("score", 0),
                        "sub":    d.get("subreddit", ""),
                        "upvotes": d.get("ups", 0),
                    })

        if not posts:
            return f"No Reddit posts found for {ticker}."

        lines = [f"Reddit Sentiment: {ticker} ({len(posts)} posts)", ""]
        bull = sum(1 for p in posts if any(w in p["title"].lower()
                   for w in ["buy", "bull", "moon", "calls", "long", "up", "gain"]))
        bear = sum(1 for p in posts if any(w in p["title"].lower()
                   for w in ["sell", "bear", "puts", "short", "down", "loss", "crash"]))

        for p in sorted(posts, key=lambda x: -x["score"])[:6]:
            lines.append(f"  [{p['score']}] r/{p['sub']}: {p['title'][:80]}")

        overall = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "MIXED"
        lines += ["", f"  Sentiment: {overall} ({bull} bullish / {bear} bearish mentions)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Reddit fetch error: {e}"


# ── Risk & Position Sizing ─────────────────────────────────────────────────────

def risk_check(symbol: str, account_size: float = 10000,
               risk_pct: float = 1.0, stop_pct: float = 2.0) -> str:
    """
    Calculate proper position size based on account risk rules.
    risk_pct: max % of account to risk per trade (default 1%)
    stop_pct: stop loss distance as % of entry (default 2%)
    """
    symbol  = symbol.upper().strip()
    bars    = _fetch_history(symbol, 30)
    price   = bars[-1]["close"] if bars else 0
    if not price:
        return f"Could not get price for {symbol}."

    ta  = _compute_ta(bars) if bars else {}
    atr = ta.get("atr") or price * (stop_pct / 100)

    dollar_risk   = account_size * (risk_pct / 100)
    stop_price    = round(price - atr * 1.5, 2)
    risk_per_share = price - stop_price
    shares        = math.floor(dollar_risk / risk_per_share) if risk_per_share > 0 else 0
    position_val  = round(shares * price, 2)
    position_pct  = round(position_val / account_size * 100, 2)

    return "\n".join([
        f"Position Sizing: {symbol}",
        f"  Entry Price:     ${price:,.2f}",
        f"  Stop Loss:       ${stop_price:,.2f}  (1.5x ATR ${atr:.2f})",
        f"  Risk Per Share:  ${risk_per_share:.2f}",
        "",
        f"  Account:         ${account_size:,.2f}",
        f"  Max Risk:        ${dollar_risk:,.2f} ({risk_pct}%)",
        f"  Position Size:   {shares} shares",
        f"  Position Value:  ${position_val:,.2f} ({position_pct}% of account)",
        "",
        f"  Rule: Never risk more than {risk_pct}% per trade.",
        f"  With ${account_size:,.0f}, max {shares} shares of {symbol}.",
    ])


def strategy_define(name: str, symbol: str = "", rule: str = "",
                    action: str = "buy", shares: int = 10) -> str:
    """
    Define an automated trade rule. Example:
    strategy_define('rsi_dip', 'AAPL', 'rsi < 35 and above_200ma', 'buy', 5)
    """
    strategies = _load(_STRATEGY_FILE, {})
    strategies[name] = {
        "symbol":  symbol.upper(),
        "rule":    rule,
        "action":  action.lower(),
        "shares":  int(shares),
        "active":  True,
        "created": datetime.now().isoformat(),
        "trades":  0,
    }
    _save(_STRATEGY_FILE, strategies)
    return (f"Strategy '{name}' saved.\n"
            f"  Symbol: {symbol.upper()}\n"
            f"  Rule:   {rule}\n"
            f"  Action: {action} {shares} shares\n"
            f"  Status: Active (will trigger on next scan)\n\n"
            f"Say 'strategy run' to evaluate all strategies now.")


def strategy_run() -> str:
    """Evaluate all defined strategies against current market data."""
    strategies = _load(_STRATEGY_FILE, {})
    if not strategies:
        return "No strategies defined. Say 'strategy define [name] [symbol] [rule]'."

    results = []
    for name, s in strategies.items():
        if not s.get("active"):
            continue
        sym  = s.get("symbol", "")
        rule = s.get("rule", "").lower()
        if not sym:
            continue

        bars = _fetch_history(sym, 90)
        if not bars:
            results.append(f"  {name}: NO DATA for {sym}")
            continue

        ta = _compute_ta(bars)
        if not ta:
            results.append(f"  {name}: insufficient history")
            continue

        # Evaluate rule conditions
        rsi    = ta.get("rsi", 50)
        price  = ta.get("price", 0)
        sma50  = ta.get("sma50") or 0
        sma200 = ta.get("sma200") or 0
        macd   = ta.get("macd") or 0
        sig    = ta.get("macd_sig") or 0

        triggered = False
        if "rsi < 35" in rule and rsi < 35:      triggered = True
        if "rsi < 30" in rule and rsi < 30:      triggered = True
        if "rsi > 70" in rule and rsi > 70:      triggered = True
        if "above_200ma" in rule and price > sma200: triggered = triggered  # AND condition
        if "above_50ma"  in rule and price > sma50:  triggered = triggered
        if "macd_cross"  in rule and macd > sig:  triggered = True
        if "rsi < 35"    in rule and "above_200ma" in rule:
            triggered = (rsi < 35 and price > sma200)

        if triggered:
            results.append(
                f"  TRIGGERED: {name} — {s['action'].upper()} {s['shares']} {sym} "
                f"@ ${price:,.2f}  (RSI:{rsi} SMA200:{sma200:.0f})"
            )
        else:
            results.append(f"  Waiting:  {name} — {sym}  RSI:{rsi}  Price:${price:,.2f}")

        time.sleep(0.3)

    return "Strategy Evaluation:\n" + "\n".join(results)


# ── Retirement Planning ────────────────────────────────────────────────────────

def retirement_plan(current_savings: float = 0, monthly_contrib: float = 500,
                    years: float = 30, annual_return: float = 8.0,
                    target: float = 0) -> str:
    """
    Retirement projection calculator.
    Shows multiple scenarios and what it takes to retire on investment income.
    """
    r  = annual_return / 100 / 12  # monthly rate
    n  = int(years * 12)           # total months

    # Future value with monthly contributions
    if r > 0:
        fv = current_savings * (1 + r)**n + monthly_contrib * (((1 + r)**n - 1) / r)
    else:
        fv = current_savings + monthly_contrib * n

    # Monthly income at 4% safe withdrawal rate
    monthly_income = fv * 0.04 / 12

    # Scenarios
    scenarios = []
    for ret, label in [(6, "Conservative"), (8, "Moderate"), (10, "Aggressive"), (12, "Optimistic")]:
        mr = ret / 100 / 12
        if mr > 0:
            sv = current_savings * (1 + mr)**n + monthly_contrib * (((1 + mr)**n - 1) / mr)
        else:
            sv = current_savings + monthly_contrib * n
        scenarios.append((label, ret, sv, sv * 0.04 / 12))

    # What contribution is needed to hit target?
    target_contrib = None
    if target > 0 and r > 0:
        remaining = target - current_savings * (1 + r)**n
        if remaining > 0:
            target_contrib = remaining / (((1 + r)**n - 1) / r)

    lines = [
        f"Retirement Projection",
        f"  Current savings:  ${current_savings:,.2f}",
        f"  Monthly contrib:  ${monthly_contrib:,.2f}",
        f"  Time horizon:     {years:.0f} years",
        f"  Assumed return:   {annual_return}% annually",
        "",
        f"  Projected value:  ${fv:,.2f}",
        f"  Monthly income:   ${monthly_income:,.2f}  (4% withdrawal rule)",
        "",
        "  Scenarios:",
    ]
    for label, ret, sv, inc in scenarios:
        lines.append(f"    {label:<14} ({ret}%/yr): ${sv:>14,.2f}  → ${inc:,.2f}/mo")

    if target > 0:
        lines += [
            "",
            f"  Target:           ${target:,.2f}",
        ]
        if target_contrib:
            lines.append(f"  Required contrib: ${target_contrib:,.2f}/month")
        lines.append(f"  {'On track!' if fv >= target else 'Need more contributions or higher returns.'}")

    ai_note = _ai(
        f"Someone saving ${monthly_contrib}/month for {years} years at {annual_return}% "
        f"will have ${fv:,.0f}. Give 2 specific strategies they can use to accelerate this goal, "
        f"especially using stock market investing. Be direct.",
        system="You are a financial planner focused on building wealth through disciplined investing."
    )
    lines += ["", "AI Wealth Advice:", ai_note]
    return "\n".join(lines)


def manual_trade_log(symbol: str = "", result: str = "", pnl: float = 0,
                     notes: str = "") -> str:
    """
    Manually log a trade result note (for trades made outside JARVIS, e.g. a
    manual brokerage fill you want tracked here too). This is NOT the query
    tool for JARVIS's own autonomous trades — those are auto-logged with full
    reasoning by tools/trade_monitor.py and answered via trade_why(symbol) /
    trades_by_date() / trades_by_result() / trades_by_reason(). Deliberately
    left off the LLM's tool menu (server.py) so "check the journal for X" /
    "explain why you bought X" can't misfire here instead of trade_why.
    """
    journal_file = _DATA_DIR / "journal.json"
    entries = _load(journal_file, [])
    entry = {
        "date":   datetime.now().isoformat(),
        "symbol": symbol.upper(),
        "result": result.upper(),   # WIN / LOSS / BE
        "pnl":    float(pnl),
        "notes":  notes,
    }
    entries.append(entry)
    _save(journal_file, entries)

    # Running stats
    wins   = sum(1 for e in entries if e.get("result") == "WIN")
    losses = sum(1 for e in entries if e.get("result") == "LOSS")
    total_pnl = sum(e.get("pnl", 0) for e in entries)
    win_rate  = wins / max(wins + losses, 1) * 100

    return (f"Trade logged: {symbol.upper()} — {result.upper()} ${pnl:+.2f}\n"
            f"Journal: {len(entries)} trades | Win rate: {win_rate:.1f}% | Total P/L: ${total_pnl:+,.2f}")


def market_calendar() -> str:
    """Fetch upcoming economic events, Fed dates, and earnings."""
    ai_view = _ai(
        f"Today is {datetime.now().strftime('%B %d, %Y')}. List the most important "
        f"upcoming market events in the next 2 weeks: Fed meetings, CPI/PPI/PCE dates, "
        f"major earnings (NVDA, AAPL, MSFT, AMZN, etc.), and key economic data releases. "
        f"Format as a clean dated list. Be specific.",
        system="You are a market strategist. List only confirmed or highly anticipated events."
    )
    return f"Market Calendar\n\n{ai_view}"


# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED TECHNICAL ANALYSIS — Stochastic, Williams %R, VWAP, MTF
# ══════════════════════════════════════════════════════════════════════════════

def _stochastic(bars: list, k: int = 14, d: int = 3) -> tuple:
    """Stochastic Oscillator %K and %D."""
    if len(bars) < k:
        return None, None
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]
    closes = [b["close"] for b in bars]
    k_vals = []
    for i in range(k - 1, len(bars)):
        hh = max(highs[i - k + 1 : i + 1])
        ll = min(lows[ i - k + 1 : i + 1])
        kv = ((closes[i] - ll) / (hh - ll) * 100) if (hh - ll) else 50
        k_vals.append(round(kv, 2))
    if len(k_vals) < d:
        return k_vals[-1], None
    d_val = round(sum(k_vals[-d:]) / d, 2)
    return k_vals[-1], d_val


def _williams_r(bars: list, period: int = 14) -> float | None:
    """Williams %R — momentum oscillator (-100 to 0; below -80 oversold, above -20 overbought)."""
    if len(bars) < period:
        return None
    window = bars[-period:]
    hh     = max(b["high"]  for b in window)
    ll     = min(b["low"]   for b in window)
    close  = bars[-1]["close"]
    if hh == ll:
        return -50.0
    return round((hh - close) / (hh - ll) * -100, 2)


def _support_resistance(bars: list, lookback: int = 20) -> dict:
    """Simple pivot-based support and resistance levels."""
    if len(bars) < lookback:
        return {}
    window = bars[-lookback:]
    highs  = sorted(set(round(b["high"],  2) for b in window), reverse=True)
    lows   = sorted(set(round(b["low"],   2) for b in window))
    price  = bars[-1]["close"]
    res    = [h for h in highs[:10] if h > price]
    sup    = [l for l in lows[:10]  if l < price]
    return {
        "resistance1": res[0] if res else None,
        "resistance2": res[1] if len(res) > 1 else None,
        "support1":    sup[0] if sup else None,
        "support2":    sup[1] if len(sup) > 1 else None,
    }


def _fetch_intraday(symbol: str, timeframe: str = "5Min", limit: int = 100) -> list:
    """Fetch intraday bars via Alpaca (requires API keys)."""
    try:
        key    = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_API_SECRET", "")
        if not key or not secret:
            return []
        import requests
        hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        r    = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/bars",
            headers=hdrs, params={"timeframe": timeframe, "limit": limit}, timeout=10
        )
        if not r.ok:
            return []
        raw = r.json().get("bars", [])
        return [{"date": b["t"][:10], "open": b["o"], "high": b["h"],
                 "low": b["l"], "close": b["c"], "volume": b["v"]} for b in raw]
    except Exception:
        return []


def _vwap_from_bars(bars: list) -> float:
    """VWAP from daily or intraday bars."""
    total_vol = sum(b.get("volume", 0) for b in bars)
    if not total_vol:
        return 0
    return round(
        sum((b["high"] + b["low"] + b["close"]) / 3 * b.get("volume", 0) for b in bars) / total_vol, 2
    )


def intraday_analysis(symbol: str, timeframe: str = "5Min") -> str:
    """
    Intraday technical analysis using Alpaca real-time bars.
    Computes VWAP, Stochastic, Williams %R from intraday data.
    Requires ALPACA_API_KEY in .env
    """
    symbol = symbol.upper().strip()
    bars   = _fetch_intraday(symbol, timeframe, 100)
    if not bars:
        return (f"No intraday data for {symbol}. "
                f"Ensure ALPACA_API_KEY is set in .env, and market is open.")
    ta      = _compute_ta(bars)
    stoch_k, stoch_d = _stochastic(bars)
    wr      = _williams_r(bars)
    vwap    = _vwap_from_bars(bars)
    sr      = _support_resistance(bars, 30)
    price   = ta.get("price", bars[-1]["close"])
    diff_vw = (price - vwap) / vwap * 100 if vwap else 0
    verdict, score, reasons = _score_signal(ta)
    lines = [
        f"Intraday Analysis: {symbol}  ({timeframe}  —  {len(bars)} bars)",
        f"  Price:      ${price:,.2f}",
        f"  VWAP:       ${vwap:.2f}  ({diff_vw:+.2f}% from VWAP)",
        f"  Stoch %K:   {stoch_k}  %D: {stoch_d}",
        f"  Williams %R:{wr}",
        f"  RSI(14):    {ta.get('rsi', 'N/A')}",
        f"  MACD:       {ta.get('macd', 'N/A')}  sig:{ta.get('macd_sig','N/A')}",
    ]
    if sr.get("resistance1"):
        lines.append(f"  Resistance: ${sr['resistance1']:.2f}"
                     + (f"  /  ${sr['resistance2']:.2f}" if sr.get("resistance2") else ""))
    if sr.get("support1"):
        lines.append(f"  Support:    ${sr['support1']:.2f}"
                     + (f"  /  ${sr['support2']:.2f}" if sr.get("support2") else ""))
    lines += [
        "",
        f"  Signal:     {verdict}  (score {score:+d}/10)",
        "  Reasons:",
    ] + [f"    • {r}" for r in reasons]
    # Stochastic signals
    if stoch_k is not None:
        if stoch_k < 20:
            lines.append("    • Stochastic < 20 — oversold (bullish)")
        elif stoch_k > 80:
            lines.append("    • Stochastic > 80 — overbought (bearish)")
    if wr is not None:
        if wr < -80:
            lines.append("    • Williams %R < -80 — oversold (bullish)")
        elif wr > -20:
            lines.append("    • Williams %R > -20 — overbought (bearish)")
    return "\n".join(lines)


def multi_timeframe_analysis(symbol: str) -> str:
    """
    Multi-timeframe confluence: daily TA + 4h + 1h.
    All three aligned = high-conviction signal.
    Requires ALPACA_API_KEY for intraday data.
    """
    symbol = symbol.upper().strip()
    results = {}
    # Daily (90 bars from yfinance)
    daily_bars = _fetch_history(symbol, 90)
    if daily_bars:
        ta = _compute_ta(daily_bars)
        v, s, _ = _score_signal(ta)
        results["Daily"] = (v, s, ta.get("price", 0), ta.get("rsi"))
    # 1-hour bars (via Alpaca)
    h1_bars = _fetch_intraday(symbol, "1Hour", 60)
    if h1_bars:
        ta = _compute_ta(h1_bars)
        if ta:
            v, s, _ = _score_signal(ta)
            results["1H"] = (v, s, ta.get("price", 0), ta.get("rsi"))
    # 15-min bars
    m15_bars = _fetch_intraday(symbol, "15Min", 60)
    if m15_bars:
        ta = _compute_ta(m15_bars)
        if ta:
            v, s, _ = _score_signal(ta)
            results["15M"] = (v, s, ta.get("price", 0), ta.get("rsi"))
    if not results:
        return f"No data for {symbol}."
    lines = [f"Multi-Timeframe Analysis: {symbol}", ""]
    bulls = 0
    bears = 0
    for tf, (verdict, score, price, rsi) in results.items():
        arrow = "▲" if score >= 2 else "▼" if score <= -2 else "—"
        lines.append(f"  {tf:<6}  {arrow}  {verdict:<16}  score:{score:+2d}  RSI:{rsi or '?'}")
        if score >= 2:
            bulls += 1
        elif score <= -2:
            bears += 1
    n = len(results)
    if bulls == n:
        confluence = "ALL TIMEFRAMES BULLISH — high-conviction BUY"
    elif bears == n:
        confluence = "ALL TIMEFRAMES BEARISH — avoid / short setup"
    elif bulls > bears:
        confluence = "BULLISH BIAS — majority of timeframes green"
    elif bears > bulls:
        confluence = "BEARISH BIAS — majority of timeframes red"
    else:
        confluence = "MIXED — no clear confluence, wait for alignment"
    lines += ["", f"  Confluence: {confluence}"]
    return "\n".join(lines)
