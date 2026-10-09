"""
tools/prediction.py — chart movement prediction (Feature 3).

Forms a price prediction for a ticker from ten inputs:
  1. pattern measured move          (tools/chart_patterns)
  2. key support / resistance       (tools/technical_suite)
  3. moving-average targets         (SMA 20/50/200)
  4. Fibonacci retracement levels   (from the 60d swing)
  5. volume profile POC             (price level with most volume)
  6. sector momentum                (sector ETF day change)
  7. political / macro catalyst     (tools/political_intel)
  8. options implied move           (yfinance ATM IV)
  9. historical volatility          (ATR-based)
 10. conviction score               (tools/conviction, 7-signal stack)

Output — the exact block from the spec:
  PREDICTION: NVDA
   Pattern: Bull Flag (confirmed)
   Entry:    $X   (trigger)
   Target 1: $Y (+8%)  — measured move
   Target 2: $Z (+15%) — prior high resistance
   Stop:     $W (-3%)  — pattern invalidation
   Confidence: 78% | Timeframe: 3-7 trading days
   Catalysts: ... | Risk/Reward: 1:4.2
"""

import re
from datetime import datetime

_SECTOR_ETF = {"Technology": "XLK", "Healthcare": "XLV", "Energy": "XLE",
               "Financial Services": "XLF", "Financials": "XLF",
               "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
               "Industrials": "XLI", "Basic Materials": "XLB",
               "Utilities": "XLU", "Real Estate": "XLRE",
               "Communication Services": "XLC"}


def _fib_levels(bars):
    """Retracement levels off the 60d swing low→high (or high→low)."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    hi, lo = max(highs), min(lows)
    rng = hi - lo
    if rng <= 0:
        return {}
    return {f"{r:.3f}".rstrip("0").rstrip("."):
            round(hi - rng * r, 2) for r in (0.236, 0.382, 0.5, 0.618, 0.786)}


def _implied_move(symbol, price):
    """ATM implied volatility from yfinance → expected % move over ~2 weeks."""
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        exps = tk.options
        if not exps:
            return None, None
        chain = tk.option_chain(exps[0])
        calls = chain.calls
        if calls.empty:
            return None, None
        calls = calls.assign(dist=(calls["strike"] - price).abs()).sort_values("dist")
        iv = float(calls.iloc[0].get("impliedVolatility", 0) or 0)
        if iv <= 0:
            return None, None
        move_pct = iv * (10 / 252) ** 0.5 * 100        # ~2-week expected move
        return round(iv * 100, 1), round(move_pct, 1)
    except Exception:
        return None, None


def _sector_momentum(symbol):
    """(sector_name, etf, day_change_pct) or Nones."""
    try:
        import yfinance as yf
        sector = (yf.Ticker(symbol).info or {}).get("sector", "") or ""
        etf = _SECTOR_ETF.get(sector)
        if not etf:
            return sector, None, None
        import tools.market as MKT
        q = MKT._fetch_quote(etf)
        if q.get("prev") and q.get("price"):
            chg = (q["price"] - q["prev"]) / q["prev"] * 100
            return sector, etf, round(chg, 2)
        return sector, etf, None
    except Exception:
        return "", None, None


def _conviction_quick(symbol):
    try:
        import tools.conviction as CVN
        report = CVN.conviction_score(symbol)
        m = re.search(r"SCORE:\s*(\d+)/100", report)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def predict(symbol: str) -> str:
    """Full multi-input prediction block (chat tool: 'predict NVDA')."""
    import tools.market as MKT
    import tools.technical_suite as TS
    import tools.chart_patterns as CP

    symbol = symbol.upper().strip()
    bars = MKT._fetch_history(symbol, 60)
    if not bars or len(bars) < 20:
        return f"Not enough price history to form a prediction for {symbol}."
    price = bars[-1]["close"]

    suite = TS.compute_suite(symbol, bars=bars) or {}
    pats = CP.detect_patterns(symbol, daily_bars=bars)
    best = (pats.get("daily") or [None])[0]
    fibs = _fib_levels(bars)
    sector, etf, etf_chg = _sector_momentum(symbol)
    iv, imp_move = _implied_move(symbol, price)
    conv = _conviction_quick(symbol)
    comp = suite.get("score", 50)
    atr = suite.get("atr") or price * 0.02
    hist_vol_pct = atr / price * 100 if price else 2.0

    # ── Direction, entry, targets, stop ────────────────────────────────────
    if best and best["score"] >= 6:
        direction = best["direction"]
        entry = best["entry"]
        t1 = best["target"]
        stop = best["stop"]
        pattern_line = (f"{best['pattern']} "
                        f"({'confirmed' if best['volume_confirmed'] else 'unconfirmed — wait for volume'})")
        t1_label = "measured move"
    else:
        direction = "LONG" if comp >= 55 else "SHORT" if comp <= 45 else "NEUTRAL"
        entry = price
        t1 = price + 2 * atr if direction != "SHORT" else price - 2 * atr
        stop = price - 1.5 * atr if direction != "SHORT" else price + 1.5 * atr
        pattern_line = "no clear pattern — ATR-projected move"
        t1_label = "2×ATR projection"
    # Target 2: next structural level in the trade's direction
    if direction != "SHORT":
        candidates = [v for v in (suite.get("high_52w"), suite.get("week_high"),
                                  suite.get("round_above")) if v and v > t1]
        t2 = min(candidates) if candidates else t1 + 2 * atr
        t2_label = ("prior high resistance" if candidates else "extended ATR projection")
    else:
        candidates = [v for v in (suite.get("low_52w"), suite.get("week_low"),
                                  suite.get("round_below")) if v and v < t1]
        t2 = max(candidates) if candidates else t1 - 2 * atr
        t2_label = ("prior low support" if candidates else "extended ATR projection")

    risk = abs(entry - stop)
    rr = round(abs(t2 - entry) / risk, 1) if risk else 0.0

    # ── Confidence: blended, honestly bounded 20-90 ───────────────────────
    conf = 0.45 * comp + 0.35 * (conv if conv is not None else 50)
    if best and best["score"] >= 7:
        conf += 8
        if best["volume_confirmed"]:
            conf += 6
    if etf_chg is not None:
        aligned = (etf_chg > 0.3 and direction == "LONG") or \
                  (etf_chg < -0.3 and direction == "SHORT")
        conf += 5 if aligned else -5 if abs(etf_chg) > 0.3 else 0
    conf = int(max(20, min(90, conf)))

    # Timeframe from volatility: faster names resolve sooner
    tf = "1-3 trading days" if hist_vol_pct >= 4 else \
         "3-7 trading days" if hist_vol_pct >= 2 else "5-15 trading days"

    catalysts = []
    if etf and etf_chg is not None:
        catalysts.append(f"{sector} sector {etf} {etf_chg:+.1f}% today")
    try:
        import tools.political_intel as PI
        pol_m, pol_note = PI.catalyst_multiplier(symbol)
        if pol_m != 1.0 and pol_note:
            catalysts.append(pol_note[:60])
    except Exception:
        pass
    if suite.get("squeeze"):
        catalysts.append("volatility squeeze — breakout loading")

    pct = lambda x: (x - price) / price * 100 if price else 0
    fib_line = "  ".join(f"{k}: ${v:,.2f}" for k, v in list(fibs.items())[:5])
    lines = [
        f"PREDICTION: {symbol}   [{datetime.now().strftime('%H:%M')}]",
        f" Direction: {direction}   Price now: ${price:,.2f}",
        f" Pattern:   {pattern_line}",
        f" Entry:     ${entry:,.2f}  "
        + ("(breakout trigger)" if best and best["score"] >= 6 else "(current price)"),
        f" Target 1:  ${t1:,.2f} ({pct(t1):+.1f}%) — {t1_label}",
        f" Target 2:  ${t2:,.2f} ({pct(t2):+.1f}%) — {t2_label}",
        f" Stop Loss: ${stop:,.2f} ({pct(stop):+.1f}%) — "
        + ("pattern invalidation" if best and best["score"] >= 6 else "1.5×ATR"),
        f" Confidence: {conf}%   Timeframe: {tf}",
        f" Risk/Reward: 1:{rr}",
        f" Catalysts: {'; '.join(catalysts) if catalysts else 'none identified'}",
        "",
        f" Inputs — composite TA {comp}/100"
        + (f" · conviction {conv}/100" if conv is not None else "")
        + f" · ATR ${atr:,.2f} ({hist_vol_pct:.1f}%/day)"
        + (f" · ATM IV {iv}% (±{imp_move}% ~2wk implied)" if iv else ""),
        f" Key levels — POC ${suite.get('poc') or 0:,.2f} · "
        f"SMA20/50/200 ${suite.get('sma20') or 0:,.2f}/"
        f"${suite.get('sma50') or 0:,.2f}/${suite.get('sma200') or 0:,.2f}",
        f" Fibonacci — {fib_line}" if fibs else "",
    ]
    return "\n".join(l for l in lines if l)
