"""
tools/chart_patterns.py — classical chart-pattern recognition (Feature 2).

Detects, on daily (60d) and intraday (15-min) OHLCV data:
  CONTINUATION: bull/bear flag, ascending/descending triangle, pennant,
                cup & handle, rising/falling wedge
  REVERSAL:     head & shoulders (+inverse), double/triple top & bottom,
                rounding bottom, hammer / shooting star
  CANDLESTICK:  doji, bullish/bearish engulfing, morning/evening star,
                harami, marubozu

Every detected pattern carries:
  score 1-10         clarity + trend context
  volume_confirmed   breakout/expansion on ≥1.5× average volume
  direction          LONG / SHORT
  entry / target / stop   measured-move price objectives

Conviction integration (used by auto_hunt at ranking time):
  clear pattern (score ≥7)              ×1.3
  + volume confirmation                 ×1.5
  + same-direction pattern on BOTH
    daily and intraday timeframes       ×1.7

Alerts: opportunity_scan's narrow loop calls scan_watchlist_alerts() so a
high-scoring fresh pattern on a watched ticker pops into the chat with
pattern name, entry trigger, target, and stop.
"""

import time
from datetime import datetime

_alert_throttle = {}   # (symbol, pattern) → last alert ts


# ── Small geometry helpers ───────────────────────────────────────────────────────

def _closes(bars):  return [b["close"]  for b in bars]
def _highs(bars):   return [b["high"]   for b in bars]
def _lows(bars):    return [b["low"]    for b in bars]
def _vols(bars):    return [b["volume"] for b in bars]


def _avg_vol(bars, n=20):
    v = _vols(bars)
    n = min(n, len(v))
    return sum(v[-n:]) / n if n else 0


def _vol_confirmed(bars) -> bool:
    """Last bar's volume ≥1.5× the 20-bar average = confirmed."""
    av = _avg_vol(bars[:-1]) or _avg_vol(bars)
    return bool(av and bars[-1]["volume"] >= 1.5 * av)


def _pivots(bars, w=2):
    """Local swing highs/lows: bar i is a pivot if it is the extreme of the
    surrounding ±w bars. Returns (high_pivots, low_pivots) as (idx, price)."""
    his, los = [], []
    for i in range(w, len(bars) - w):
        seg = bars[i - w:i + w + 1]
        if bars[i]["high"] >= max(b["high"] for b in seg):
            his.append((i, bars[i]["high"]))
        if bars[i]["low"] <= min(b["low"] for b in seg):
            los.append((i, bars[i]["low"]))
    return his, los


def _slope(points):
    """Least-squares slope of (idx, price) points, normalized per bar."""
    n = len(points)
    if n < 2:
        return 0.0
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points); sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    return (n * sxy - sx * sy) / denom if denom else 0.0


def _near(a, b, tol=0.02):
    return b and abs(a - b) / b <= tol


def _mk(name, direction, score, entry, target, stop, detail, bars):
    return {
        "pattern":  name,
        "direction": direction,                    # LONG | SHORT
        "score":    max(1, min(10, int(round(score)))),
        "entry":    round(entry, 2),
        "target":   round(target, 2),
        "stop":     round(stop, 2),
        "volume_confirmed": _vol_confirmed(bars),
        "detail":   detail,
    }


# ── Multi-bar patterns ───────────────────────────────────────────────────────────

def _detect_flag(bars):
    """Bull/bear flag: strong pole (≥6% in ≤10 bars), then tight consolidation
    (range < 40% of pole) on declining volume."""
    if len(bars) < 15:
        return None
    pole, flag = bars[-15:-5], bars[-5:]
    p_start, p_end = pole[0]["close"], pole[-1]["close"]
    if not p_start:
        return None
    move = (p_end - p_start) / p_start
    f_hi, f_lo = max(_highs(flag)), min(_lows(flag))
    f_range = f_hi - f_lo
    pole_range = abs(p_end - p_start)
    if pole_range <= 0 or f_range > 0.4 * pole_range:
        return None
    vol_declining = _avg_vol(flag, 5) < _avg_vol(pole, 10)
    price = bars[-1]["close"]
    base = 6 + (1 if vol_declining else 0)
    if move >= 0.06:
        score = base + (1 if price > f_hi * 0.995 else 0)
        return _mk("Bull Flag", "LONG", score, f_hi,
                   f_hi + pole_range, f_lo,
                   f"pole +{move * 100:.1f}%, flag range ${f_range:.2f}"
                   + (", volume contracting (healthy)" if vol_declining else ""), bars)
    if move <= -0.06:
        score = base + (1 if price < f_lo * 1.005 else 0)
        return _mk("Bear Flag", "SHORT", score, f_lo,
                   f_lo - pole_range, f_hi,
                   f"pole {move * 100:.1f}%, flag range ${f_range:.2f}", bars)
    return None


def _detect_triangles(bars):
    """Ascending (flat top, rising lows) / descending (flat bottom, falling
    highs) triangles and pennants/wedges from pivot trendlines."""
    if len(bars) < 25:
        return None
    win = bars[-25:]
    his, los = _pivots(win)
    if len(his) < 2 or len(los) < 2:
        return None
    hi_slope, lo_slope = _slope(his[-3:]), _slope(los[-3:])
    price = win[-1]["close"]
    top = sum(p for _, p in his[-3:]) / len(his[-3:])
    bot = sum(p for _, p in los[-3:]) / len(los[-3:])
    height = top - bot
    if height <= 0 or not price:
        return None
    rel = lambda s: s / price          # slope as % of price per bar

    flat_top   = abs(rel(hi_slope)) < 0.0015
    flat_bot   = abs(rel(lo_slope)) < 0.0015
    rising_lo  = rel(lo_slope) > 0.0015
    falling_hi = rel(hi_slope) < -0.0015

    if flat_top and rising_lo:
        score = 7 + (1 if price > top * 0.99 else 0)
        return _mk("Ascending Triangle", "LONG", score, top, top + height, bot,
                   f"flat resistance ${top:.2f}, rising support", bars)
    if flat_bot and falling_hi:
        score = 7 + (1 if price < bot * 1.01 else 0)
        return _mk("Descending Triangle", "SHORT", score, bot, bot - height, top,
                   f"flat support ${bot:.2f}, falling resistance", bars)
    if rising_lo and falling_hi:
        # Converging — pennant continues the preceding move
        pre = bars[-35:-25] if len(bars) >= 35 else []
        pre_move = ((win[0]["close"] - pre[0]["close"]) / pre[0]["close"]
                    if pre and pre[0]["close"] else 0)
        if abs(pre_move) >= 0.05:
            d = "LONG" if pre_move > 0 else "SHORT"
            return _mk("Pennant", d, 6,
                       top if d == "LONG" else bot,
                       (top + height) if d == "LONG" else (bot - height),
                       bot if d == "LONG" else top,
                       f"converging after {pre_move * 100:+.1f}% move", bars)
        return None
    # Wedges break OPPOSITE to the wedge's own direction
    if rel(lo_slope) > 0.002 and rel(hi_slope) > 0.002 and rel(lo_slope) > rel(hi_slope):
        return _mk("Rising Wedge", "SHORT", 6, bot, bot - height, top,
                   "both trendlines rising and converging — bearish break expected", bars)
    if rel(lo_slope) < -0.002 and rel(hi_slope) < -0.002 and rel(hi_slope) < rel(lo_slope):
        return _mk("Falling Wedge", "LONG", 6, top, top + height, bot,
                   "both trendlines falling and converging — bullish break expected", bars)
    return None


def _detect_double_triple(bars):
    """Double/triple tops (equal highs) and bottoms (equal lows), 2% tolerance,
    with the neckline as trigger and a measured move equal to the depth."""
    if len(bars) < 30:
        return None
    win = bars[-40:] if len(bars) >= 40 else bars
    his, los = _pivots(win, w=3)
    price = win[-1]["close"]

    def _equal_run(pivs, tol=0.02):
        if len(pivs) < 2:
            return []
        last = pivs[-1][1]
        return [p for p in pivs[-4:] if _near(p[1], last, tol)]

    eq_his = _equal_run(his)
    eq_los = _equal_run(los)

    if len(eq_his) >= 2:
        top = sum(p for _, p in eq_his) / len(eq_his)
        lows_between = [p for i, p in los if i > eq_his[0][0]]
        neck = min(lows_between) if lows_between else min(_lows(win[-15:]))
        depth = top - neck
        if depth > 0 and price < top * 0.99:
            n = "Triple Top" if len(eq_his) >= 3 else "Double Top"
            score = 7 + (1 if price < neck else 0) + (1 if len(eq_his) >= 3 else 0)
            return _mk(n, "SHORT", score, neck, neck - depth, top,
                       f"{len(eq_his)} equal highs ~${top:.2f}, neckline ${neck:.2f}", bars)
    if len(eq_los) >= 2:
        bot = sum(p for _, p in eq_los) / len(eq_los)
        his_between = [p for i, p in his if i > eq_los[0][0]]
        neck = max(his_between) if his_between else max(_highs(win[-15:]))
        depth = neck - bot
        if depth > 0 and price > bot * 1.01:
            n = "Triple Bottom" if len(eq_los) >= 3 else "Double Bottom"
            score = 7 + (1 if price > neck else 0) + (1 if len(eq_los) >= 3 else 0)
            return _mk(n, "LONG", score, neck, neck + depth, bot,
                       f"{len(eq_los)} equal lows ~${bot:.2f}, neckline ${neck:.2f}", bars)
    return None


def _detect_head_shoulders(bars):
    """H&S: three peaks, middle highest; inverse: three troughs, middle lowest.
    Trigger = neckline break; measured move = head-to-neckline distance."""
    if len(bars) < 35:
        return None
    win = bars[-45:] if len(bars) >= 45 else bars
    his, los = _pivots(win, w=3)
    price = win[-1]["close"]

    if len(his) >= 3:
        l, h, r = his[-3], his[-2], his[-1]
        if h[1] > l[1] and h[1] > r[1] and _near(l[1], r[1], 0.04):
            troughs = [p for i, p in los if l[0] < i < r[0]]
            if troughs:
                neck = sum(troughs) / len(troughs)
                depth = h[1] - neck
                if depth > 0:
                    score = 7 + (2 if price < neck else 0)
                    return _mk("Head & Shoulders", "SHORT", score, neck,
                               neck - depth, h[1],
                               f"head ${h[1]:.2f}, shoulders ~${(l[1] + r[1]) / 2:.2f}, "
                               f"neckline ${neck:.2f}", bars)
    if len(los) >= 3:
        l, h, r = los[-3], los[-2], los[-1]
        if h[1] < l[1] and h[1] < r[1] and _near(l[1], r[1], 0.04):
            peaks = [p for i, p in his if l[0] < i < r[0]]
            if peaks:
                neck = sum(peaks) / len(peaks)
                depth = neck - h[1]
                if depth > 0:
                    score = 7 + (2 if price > neck else 0)
                    return _mk("Inverse Head & Shoulders", "LONG", score, neck,
                               neck + depth, h[1],
                               f"head ${h[1]:.2f}, neckline ${neck:.2f}", bars)
    return None


def _detect_cup_handle(bars):
    """Cup & handle: U-shaped base (rim ≈ rim, floor 12-35% below), then a
    small handle pullback near the right rim. Breakout above rim → LONG."""
    if len(bars) < 40:
        return None
    win = bars[-45:]
    cup, handle = win[:-6], win[-6:]
    rim_l = max(_highs(cup[:8])); rim_r = max(_highs(cup[-8:]))
    floor = min(_lows(cup))
    if not _near(rim_l, rim_r, 0.04):
        return None
    rim = (rim_l + rim_r) / 2
    depth = (rim - floor) / rim if rim else 0
    if not (0.10 <= depth <= 0.40):
        return None
    # Floor should sit in the middle third (a U, not a V at the edge)
    floor_idx = _lows(cup).index(min(_lows(cup)))
    if not (len(cup) * 0.25 <= floor_idx <= len(cup) * 0.75):
        return None
    h_lo = min(_lows(handle))
    if h_lo < rim * 0.85:                       # handle too deep
        return None
    price = win[-1]["close"]
    score = 7 + (1 if price > rim * 0.99 else 0)
    return _mk("Cup & Handle", "LONG", score, rim, rim + (rim - floor), h_lo,
               f"rim ${rim:.2f}, cup depth {depth * 100:.0f}%, handle low ${h_lo:.2f}", bars)


def _detect_rounding_bottom(bars):
    """Saucer: long gradual down-then-up curve — falling first-third slope,
    rising last-third slope, floor in the middle."""
    if len(bars) < 40:
        return None
    win = bars[-50:] if len(bars) >= 50 else bars
    c = _closes(win)
    third = len(c) // 3
    s1 = _slope(list(enumerate(c[:third])))
    s3 = _slope(list(enumerate(c[-third:])))
    price = c[-1]
    if not price:
        return None
    if s1 / price < -0.001 and s3 / price > 0.001:
        floor_idx = c.index(min(c))
        if third <= floor_idx <= 2 * third:
            rim = max(c[:5])
            depth = rim - min(c)
            if depth / rim >= 0.08:
                return _mk("Rounding Bottom", "LONG", 6, rim, rim + depth, min(c),
                           f"gradual saucer, floor ${min(c):.2f}, rim ${rim:.2f}", bars)
    return None


# ── Candlestick patterns (last 1-3 bars) ─────────────────────────────────────────

def _detect_candles(bars):
    """Single/multi-candle signals on the most recent bars."""
    if len(bars) < 3:
        return []
    out = []
    a, b, c = bars[-3], bars[-2], bars[-1]
    price = c["close"]

    def body(x):  return abs(x["close"] - x["open"]) if "open" in x else abs(x["close"] - x["high"])
    def rng(x):   return x["high"] - x["low"]
    def bull(x):  return x.get("open") is not None and x["close"] > x["open"]
    def bear(x):  return x.get("open") is not None and x["close"] < x["open"]

    if "open" not in c:
        return []
    atr_proxy = sum(rng(x) for x in bars[-14:]) / min(14, len(bars))
    stop_l = price - atr_proxy
    stop_s = price + atr_proxy

    # Doji — indecision
    if rng(c) > 0 and body(c) <= 0.1 * rng(c):
        out.append(_mk("Doji", "LONG" if bear(b) else "SHORT", 4,
                       price, price + atr_proxy, stop_l,
                       "indecision candle — potential reversal", bars))
    # Engulfing
    if bear(b) and bull(c) and c["close"] >= b["open"] and c["open"] <= b["close"]:
        out.append(_mk("Bullish Engulfing", "LONG", 7, price,
                       price + 2 * atr_proxy, min(c["low"], b["low"]),
                       "full-body engulf of prior red candle", bars))
    if bull(b) and bear(c) and c["close"] <= b["open"] and c["open"] >= b["close"]:
        out.append(_mk("Bearish Engulfing", "SHORT", 7, price,
                       price - 2 * atr_proxy, max(c["high"], b["high"]),
                       "full-body engulf of prior green candle", bars))
    # Morning / Evening star
    if bear(a) and body(b) <= 0.3 * body(a) and bull(c) and c["close"] > (a["open"] + a["close"]) / 2:
        out.append(_mk("Morning Star", "LONG", 8, price,
                       price + 2 * atr_proxy, min(b["low"], c["low"]),
                       "3-candle bullish reversal", bars))
    if bull(a) and body(b) <= 0.3 * body(a) and bear(c) and c["close"] < (a["open"] + a["close"]) / 2:
        out.append(_mk("Evening Star", "SHORT", 8, price,
                       price - 2 * atr_proxy, max(b["high"], c["high"]),
                       "3-candle bearish reversal", bars))
    # Harami — inside bar, momentum slowing
    if body(b) > 0 and max(c["open"], c["close"]) <= max(b["open"], b["close"]) \
            and min(c["open"], c["close"]) >= min(b["open"], b["close"]):
        out.append(_mk("Harami", "LONG" if bear(b) else "SHORT", 4,
                       price, price + (atr_proxy if bear(b) else -atr_proxy),
                       stop_l if bear(b) else stop_s,
                       "inside bar — momentum slowing", bars))
    # Marubozu — full-body conviction candle
    if rng(c) > 0 and body(c) >= 0.9 * rng(c):
        d = "LONG" if bull(c) else "SHORT"
        out.append(_mk("Marubozu", d, 6, price,
                       price + (2 * atr_proxy if d == "LONG" else -2 * atr_proxy),
                       c["low"] if d == "LONG" else c["high"],
                       "full-body candle — strong momentum", bars))
    # Hammer / Shooting star
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    if rng(c) > 0 and lower_wick >= 2 * body(c) and upper_wick <= 0.3 * rng(c):
        out.append(_mk("Hammer", "LONG", 6, c["high"],
                       c["high"] + 2 * atr_proxy, c["low"],
                       "long lower wick rejection — bullish reversal candle", bars))
    if rng(c) > 0 and upper_wick >= 2 * body(c) and lower_wick <= 0.3 * rng(c):
        out.append(_mk("Shooting Star", "SHORT", 6, c["low"],
                       c["low"] - 2 * atr_proxy, c["high"],
                       "long upper wick rejection — bearish reversal candle", bars))
    return out


# ── Public API ───────────────────────────────────────────────────────────────────

_DETECTORS = [_detect_flag, _detect_triangles, _detect_double_triple,
              _detect_head_shoulders, _detect_cup_handle, _detect_rounding_bottom]


def _with_open(bars):
    """Daily bars from market._fetch_history carry 'open'; normalize intraday
    Alpaca bars ({o,h,l,c,v,t}) to the same shape."""
    out = []
    for b in bars:
        if "close" in b:
            out.append(b)
        else:
            out.append({"open": b.get("o", 0), "high": b.get("h", 0),
                        "low": b.get("l", 0), "close": b.get("c", 0),
                        "volume": b.get("v", 0)})
    return out


def detect_patterns(symbol: str, daily_bars: list = None,
                    intraday_bars: list = None) -> dict:
    """Run every detector on daily (60d) + intraday (15-min) data.
    Returns {"daily": [patterns], "intraday": [patterns], "multiplier": float}.
    """
    import tools.market as MKT
    symbol = symbol.upper().strip()
    if daily_bars is None:
        daily_bars = MKT._fetch_history(symbol, 60)
    if intraday_bars is None:
        try:
            import tools.trading as TRD
            intraday_bars = TRD._fetch_intraday(symbol, "15Min", 40)
        except Exception:
            intraday_bars = []
    daily_bars = _with_open(daily_bars or [])
    intraday_bars = _with_open(intraday_bars or [])

    def _run(bars):
        found = []
        if len(bars) >= 15:
            for det in _DETECTORS:
                try:
                    p = det(bars)
                    if p:
                        found.append(p)
                except Exception:
                    pass
            try:
                found += _detect_candles(bars)
            except Exception:
                pass
        found.sort(key=lambda p: -p["score"])
        return found

    daily = _run(daily_bars)
    intra = _run(intraday_bars)
    return {"symbol": symbol, "daily": daily, "intraday": intra,
            "multiplier": conviction_multiplier_from(daily, intra)}


def conviction_multiplier_from(daily: list, intraday: list) -> float:
    """Pattern → conviction multiplier per the spec:
    clear pattern (7+) ×1.3 · +volume confirmation ×1.5 · +multi-timeframe ×1.7.
    Bearish patterns invert (divide) so a SHORT setup drags a long-bias
    conviction score DOWN instead of up. No pattern → 1.0."""
    best = (daily or [None])[0]
    if not best or best["score"] < 7:
        return 1.0
    mult = 1.3
    if best["volume_confirmed"]:
        mult = 1.5
    same_dir_intra = any(p["direction"] == best["direction"] and p["score"] >= 6
                         for p in (intraday or []))
    if same_dir_intra:
        mult = 1.7
    return round(mult if best["direction"] == "LONG" else 1.0 / mult, 3)


def pattern_multiplier(symbol: str, daily_bars: list = None) -> tuple:
    """(multiplier, note) for the ranking pipeline. Cheap wrapper."""
    try:
        res = detect_patterns(symbol, daily_bars=daily_bars)
        best = (res["daily"] or [None])[0]
        if not best or res["multiplier"] == 1.0:
            return 1.0, ""
        note = (f"{best['pattern']} ({best['direction']}, {best['score']}/10"
                + (", vol-confirmed" if best["volume_confirmed"] else "") + ")")
        return res["multiplier"], note
    except Exception:
        return 1.0, ""


def pattern_report(symbol: str) -> str:
    """Chat tool: 'chart patterns NVDA' — every pattern with entry/target/stop."""
    res = detect_patterns(symbol)
    sym = res["symbol"]
    lines = [f"CHART PATTERNS — {sym}  [{datetime.now().strftime('%H:%M')}]"]
    for tf, key in (("DAILY (60d)", "daily"), ("INTRADAY (15-min)", "intraday")):
        pats = res[key]
        lines.append(f"  ── {tf} ──")
        if not pats:
            lines.append("    none detected")
            continue
        for p in pats[:5]:
            vc = "volume CONFIRMED ✓" if p["volume_confirmed"] else "volume unconfirmed — wait"
            lines.append(f"    {p['pattern']:<24} {p['direction']:<5} score {p['score']}/10  ({vc})")
            lines.append(f"      entry ${p['entry']:,.2f} → target ${p['target']:,.2f} "
                         f"| stop ${p['stop']:,.2f}")
            lines.append(f"      {p['detail']}")
    m = res["multiplier"]
    if m != 1.0:
        lines.append(f"  Conviction multiplier: ×{m}")
    lines.append("  Say 'predict " + sym + "' for the full prediction block.")
    return "\n".join(lines)


# ── Watchlist alerts (called from opportunity_scan's narrow loop) ───────────────

def scan_watchlist_alerts(symbols: list = None) -> int:
    """Check watched tickers for fresh high-scoring patterns; alert the user
    with pattern name, entry trigger, target, and stop. Throttled 4h per
    (symbol, pattern). Returns number of alerts pushed."""
    import tools.market as MKT
    if symbols is None:
        try:
            symbols = list(MKT._load(MKT._WATCHLIST_FILE, {}).keys())
        except Exception:
            symbols = []
    pushed = 0
    for sym in (symbols or [])[:25]:
        try:
            res = detect_patterns(sym)
            best = (res["daily"] or [None])[0]
            if not best or best["score"] < 7:
                continue
            key = (sym, best["pattern"])
            if time.time() - _alert_throttle.get(key, 0) < 14400:
                continue
            _alert_throttle[key] = time.time()
            vc = "volume confirmed" if best["volume_confirmed"] else "volume NOT yet confirmed"
            msg = (f"📐 {best['pattern']} forming on {sym} — "
                   f"{'breakout above' if best['direction'] == 'LONG' else 'breakdown below'} "
                   f"${best['entry']:,.2f} targets ${best['target']:,.2f}, "
                   f"stop at ${best['stop']:,.2f}, {vc}")
            try:
                import tools.trade_monitor as MON
                MON._push_user_alert(msg)
            except Exception:
                pass
            pushed += 1
            time.sleep(0.2)
        except Exception:
            continue
    return pushed
