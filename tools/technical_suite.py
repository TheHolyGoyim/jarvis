"""
tools/technical_suite.py — full technical indicator suite + composite score
(Feature 4). Computed on every scanned ticker from daily OHLCV bars
(tools/market._fetch_history) and intraday bars where relevant.

TREND:       SMA 20/50/200, EMA 9/21, price vs each MA, golden/death cross
MOMENTUM:    RSI 14, MACD (12/26/9) + crossover, Stochastic (14,3,3), ROC 10
VOLUME:      OBV trend, volume vs 20-day SMA, VWAP (intraday), A/D line trend
VOLATILITY:  Bollinger (20,2) + squeeze, ATR 14, Keltner channels (20, 1.5×ATR)
S/R:         previous day/week high-low, round numbers, 52-week high/low,
             volume-profile POC (price bin with most traded volume)

COMPOSITE SCORE (0-100): each indicator votes bullish (+1) / bearish (-1) /
neutral (0); votes are averaged inside their group, then weighted:
  trend 30% · momentum 25% · volume 25% · volatility 10% · S/R 10%
  70+ strong buy · 60-69 moderate buy · 40-59 neutral · 30-39 moderate sell
  <30 strong sell/avoid
"""

import math
from datetime import datetime


# ── Primitive indicator helpers (pure functions on OHLCV bar lists) ────────────

def _closes(bars):  return [b["close"]  for b in bars]
def _highs(bars):   return [b["high"]   for b in bars]
def _lows(bars):    return [b["low"]    for b in bars]
def _volumes(bars): return [b["volume"] for b in bars]


def sma(data, n):
    return sum(data[-n:]) / n if len(data) >= n else None


def ema(data, n):
    if len(data) < n:
        return None
    k = 2 / (n + 1)
    e = data[0]
    for v in data[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(data, n=14):
    if len(data) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(data)):
        d = data[i] - data[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag, al = sum(gains[-n:]) / n, sum(losses[-n:]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd(data):
    """Returns (macd_line, signal, histogram) or (None,)*3."""
    if len(data) < 35:
        return None, None, None
    series = []
    for i in range(26, len(data) + 1):
        e12, e26 = ema(data[:i], 12), ema(data[:i], 26)
        if e12 is not None and e26 is not None:
            series.append(e12 - e26)
    if not series:
        return None, None, None
    line = series[-1]
    sig = ema(series, 9) if len(series) >= 9 else line
    return line, sig, line - (sig or line)


def stochastic(bars, k=14, d=3):
    """Returns (%K, %D) — the (14,3,3) slow stochastic."""
    if len(bars) < k + d:
        return None, None
    ks = []
    for i in range(len(bars) - d + 1 - 2, len(bars) + 1):
        window = bars[max(0, i - k):i]
        if len(window) < k:
            continue
        hh = max(_highs(window)); ll = min(_lows(window))
        c = window[-1]["close"]
        ks.append((c - ll) / (hh - ll) * 100 if hh > ll else 50.0)
    if not ks:
        return None, None
    return ks[-1], sum(ks[-d:]) / min(d, len(ks))


def roc(data, n=10):
    if len(data) < n + 1:
        return None
    return (data[-1] - data[-n - 1]) / data[-n - 1] * 100 if data[-n - 1] else None


def obv(bars):
    """On Balance Volume series (last 2 points enough for trend)."""
    if len(bars) < 2:
        return []
    series = [0]
    for i in range(1, len(bars)):
        v = bars[i]["volume"]
        if bars[i]["close"] > bars[i - 1]["close"]:
            series.append(series[-1] + v)
        elif bars[i]["close"] < bars[i - 1]["close"]:
            series.append(series[-1] - v)
        else:
            series.append(series[-1])
    return series


def ad_line(bars):
    """Accumulation/Distribution line series."""
    series, total = [], 0.0
    for b in bars:
        h, l, c, v = b["high"], b["low"], b["close"], b["volume"]
        mfm = ((c - l) - (h - c)) / (h - l) if h > l else 0.0
        total += mfm * v
        series.append(total)
    return series


def atr(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-n:]) / n


def bollinger(data, n=20, k=2):
    if len(data) < n:
        return None, None, None
    w = data[-n:]
    mid = sum(w) / n
    std = math.sqrt(sum((x - mid) ** 2 for x in w) / n)
    return mid - k * std, mid, mid + k * std


def keltner(bars, n=20, mult=1.5):
    closes = _closes(bars)
    mid = ema(closes, n)
    a = atr(bars, 14)
    if mid is None or a is None:
        return None, None, None
    return mid - mult * a, mid, mid + mult * a


def round_levels(price):
    """Nearest round-number magnets below/above ($5 steps under $100,
    $10 to $500, $50 beyond)."""
    step = 5 if price < 100 else 10 if price < 500 else 50
    below = math.floor(price / step) * step
    above = below + step
    return below, above


def volume_profile_poc(bars, bins=24):
    """Price level with the most traded volume (POC) over the window."""
    if not bars:
        return None
    lo = min(_lows(bars)); hi = max(_highs(bars))
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    buckets = [0.0] * bins
    for b in bars:
        mid = (b["high"] + b["low"] + b["close"]) / 3
        idx = min(bins - 1, max(0, int((mid - lo) / width)))
        buckets[idx] += b["volume"]
    best = buckets.index(max(buckets))
    return lo + (best + 0.5) * width


# ── Composite score ─────────────────────────────────────────────────────────────

_WEIGHTS = {"trend": 0.30, "momentum": 0.25, "volume": 0.25,
            "volatility": 0.10, "sr": 0.10}


def compute_suite(symbol: str, bars: list = None, intraday: list = None) -> dict:
    """All indicators + votes + weighted composite 0-100 for one ticker.
    Pass pre-fetched bars to avoid duplicate downloads inside scans."""
    import tools.market as MKT
    symbol = symbol.upper().strip()
    if bars is None:
        bars = MKT._fetch_history(symbol, 300)     # enough for SMA200 + 52wk
    if not bars or len(bars) < 30:
        return {}
    closes, vols = _closes(bars), _volumes(bars)
    price = closes[-1]

    out = {"symbol": symbol, "price": round(price, 2)}
    votes = {"trend": [], "momentum": [], "volume": [], "volatility": [], "sr": []}
    notes = []

    # ── TREND ──────────────────────────────────────────────────────────────
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    e9, e21 = ema(closes, 9), ema(closes, 21)
    out.update({"sma20": s20, "sma50": s50, "sma200": s200, "ema9": e9, "ema21": e21})
    for ma, name in ((s20, "SMA20"), (s50, "SMA50"), (s200, "SMA200"),
                     (e9, "EMA9"), (e21, "EMA21")):
        if ma:
            votes["trend"].append(1 if price > ma else -1)
    if s50 and s200:
        prev_c = _closes(bars[:-5])
        p50, p200 = sma(prev_c, 50), sma(prev_c, 200)
        if p50 and p200:
            if p50 <= p200 and s50 > s200:
                votes["trend"] += [1, 1]           # golden cross = strong buy
                notes.append("GOLDEN CROSS — 50MA crossed above 200MA (strong buy)")
                out["cross"] = "golden"
            elif p50 >= p200 and s50 < s200:
                votes["trend"] += [-1, -1]
                notes.append("DEATH CROSS — 50MA crossed below 200MA (strong sell)")
                out["cross"] = "death"
        if "cross" not in out:
            out["cross"] = "golden_held" if s50 > s200 else "death_held"
            votes["trend"].append(1 if s50 > s200 else -1)

    # ── MOMENTUM ───────────────────────────────────────────────────────────
    r = rsi(closes)
    out["rsi"] = round(r, 1) if r is not None else None
    if r is not None:
        if r < 30:
            votes["momentum"].append(1); notes.append(f"RSI {r:.0f} oversold — bullish reversal zone")
        elif r > 70:
            votes["momentum"].append(-1); notes.append(f"RSI {r:.0f} overbought")
        else:
            votes["momentum"].append(1 if r >= 55 else -1 if r <= 45 else 0)
    m_line, m_sig, m_hist = macd(closes)
    out.update({"macd": m_line, "macd_signal": m_sig, "macd_hist": m_hist})
    if m_line is not None and m_sig is not None:
        votes["momentum"].append(1 if m_line > m_sig else -1)
        notes.append(f"MACD {'above' if m_line > m_sig else 'below'} signal")
    st_k, st_d = stochastic(bars)
    out.update({"stoch_k": st_k, "stoch_d": st_d})
    if st_k is not None:
        votes["momentum"].append(1 if st_k < 20 else -1 if st_k > 80 else
                                 (1 if st_d is not None and st_k > st_d else 0))
    rc = roc(closes)
    out["roc10"] = round(rc, 2) if rc is not None else None
    if rc is not None:
        votes["momentum"].append(1 if rc > 2 else -1 if rc < -2 else 0)

    # ── VOLUME ─────────────────────────────────────────────────────────────
    obv_s = obv(bars)
    if len(obv_s) >= 10:
        votes["volume"].append(1 if obv_s[-1] > obv_s[-10] else -1)
        out["obv_trend"] = "up" if obv_s[-1] > obv_s[-10] else "down"
    vol_sma20 = sma(vols, 20)
    out["vol_ratio"] = round(vols[-1] / vol_sma20, 2) if vol_sma20 else None
    if vol_sma20:
        up_day = closes[-1] >= closes[-2] if len(closes) > 1 else True
        if vols[-1] >= 1.5 * vol_sma20:
            votes["volume"].append(1 if up_day else -1)
            notes.append(f"Unusual volume {out['vol_ratio']}x avg on "
                         f"{'up' if up_day else 'down'} day")
        else:
            votes["volume"].append(0)
    ad_s = ad_line(bars)
    if len(ad_s) >= 10:
        votes["volume"].append(1 if ad_s[-1] > ad_s[-10] else -1)
    if intraday:
        tot_v = sum(b.get("v", b.get("volume", 0)) for b in intraday)
        if tot_v:
            vwap = sum(((b.get("h", b.get("high", 0)) + b.get("l", b.get("low", 0)) +
                         b.get("c", b.get("close", 0))) / 3) *
                       b.get("v", b.get("volume", 0)) for b in intraday) / tot_v
            out["vwap"] = round(vwap, 2)
            votes["volume"].append(1 if price > vwap else -1)

    # ── VOLATILITY ─────────────────────────────────────────────────────────
    bb_lo, bb_mid, bb_hi = bollinger(closes)
    out.update({"bb_low": bb_lo, "bb_mid": bb_mid, "bb_high": bb_hi})
    a = atr(bars)
    out["atr"] = round(a, 2) if a else None
    k_lo, k_mid, k_hi = keltner(bars)
    if bb_lo and bb_hi:
        if price <= bb_lo:
            votes["volatility"].append(1)
        elif price >= bb_hi:
            votes["volatility"].append(-1)
        else:
            votes["volatility"].append(0)
        if k_lo and k_hi and bb_lo > k_lo and bb_hi < k_hi:
            out["squeeze"] = True                  # BB inside Keltner = squeeze
            notes.append("Bollinger squeeze inside Keltner — breakout loading")
            votes["volatility"].append(1 if (m_hist or 0) >= 0 else -1)
        else:
            out["squeeze"] = False

    # ── SUPPORT / RESISTANCE ───────────────────────────────────────────────
    prev_day = bars[-2] if len(bars) >= 2 else None
    week = bars[-6:-1] if len(bars) >= 6 else []
    hi52 = max(_highs(bars)); lo52 = min(_lows(bars))
    out.update({
        "prev_day_high": prev_day["high"] if prev_day else None,
        "prev_day_low":  prev_day["low"]  if prev_day else None,
        "week_high": max(_highs(week)) if week else None,
        "week_low":  min(_lows(week))  if week else None,
        "high_52w": round(hi52, 2), "low_52w": round(lo52, 2),
    })
    rnd_below, rnd_above = round_levels(price)
    out.update({"round_below": rnd_below, "round_above": rnd_above})
    poc = volume_profile_poc(bars[-60:])
    out["poc"] = round(poc, 2) if poc else None
    if prev_day:
        votes["sr"].append(1 if price > prev_day["high"] else
                           -1 if price < prev_day["low"] else 0)
    if hi52 and price >= hi52 * 0.995:
        votes["sr"].append(1); notes.append("At/near 52-week high — breakout territory")
    elif lo52 and price <= lo52 * 1.02:
        votes["sr"].append(-1); notes.append("Near 52-week low")
    if poc:
        votes["sr"].append(1 if price > poc else -1)

    # ── Weighted composite ─────────────────────────────────────────────────
    score = 50.0
    for group, w in _WEIGHTS.items():
        vs = votes[group]
        if vs:
            score += (sum(vs) / len(vs)) * w * 50   # each group swings ±w×50
    score = max(0.0, min(100.0, score))
    out["score"] = round(score, 1)
    out["signal"] = ("STRONG BUY" if score >= 70 else
                     "MODERATE BUY" if score >= 60 else
                     "NEUTRAL / HOLD" if score >= 40 else
                     "MODERATE SELL" if score >= 30 else
                     "STRONG SELL / AVOID")
    out["votes"] = {g: sum(v) for g, v in votes.items()}
    out["notes"] = notes
    return out


def technical_report(symbol: str) -> str:
    """Human-readable full-suite report (chat tool: 'tech score NVDA')."""
    import tools.market as MKT
    symbol = symbol.upper().strip()
    intraday = []
    try:
        import tools.trading as TRD
        intraday = TRD._fetch_intraday(symbol, "15Min", 30)
    except Exception:
        pass
    s = compute_suite(symbol, intraday=intraday)
    if not s:
        return f"Not enough data to compute the technical suite for {symbol}."
    fmt = lambda v: f"${v:,.2f}" if isinstance(v, (int, float)) else "—"
    num = lambda v, spec="+.3f": format(v, spec) if isinstance(v, (int, float)) else "—"
    bar_fill = int(s["score"] / 5)
    lines = [
        f"TECHNICAL SUITE — {symbol}  [{datetime.now().strftime('%H:%M')}]",
        f"  COMPOSITE: {s['score']}/100  [{'█' * bar_fill}{'░' * (20 - bar_fill)}]  {s['signal']}",
        f"  votes — trend:{s['votes']['trend']:+d}  momentum:{s['votes']['momentum']:+d}  "
        f"volume:{s['votes']['volume']:+d}  volatility:{s['votes']['volatility']:+d}  "
        f"S/R:{s['votes']['sr']:+d}",
        "",
        f"  TREND      price {fmt(s['price'])} | SMA20 {fmt(s.get('sma20'))} "
        f"SMA50 {fmt(s.get('sma50'))} SMA200 {fmt(s.get('sma200'))}",
        f"             EMA9 {fmt(s.get('ema9'))} EMA21 {fmt(s.get('ema21'))} | "
        f"cross: {s.get('cross', '—').replace('_', ' ')}",
        f"  MOMENTUM   RSI {s.get('rsi', '—')} | MACD {num(s.get('macd'))} vs sig "
        f"{num(s.get('macd_signal'))} | Stoch %K {num(s.get('stoch_k'), '.0f')} | "
        f"ROC10 {s.get('roc10', '—')}%",
        f"  VOLUME     {s.get('vol_ratio', '—')}x 20d avg | OBV {s.get('obv_trend', '—')}"
        + (f" | VWAP {fmt(s.get('vwap'))}" if s.get('vwap') else ""),
        f"  VOLATILITY ATR {fmt(s.get('atr'))} | BB {fmt(s.get('bb_low'))} / "
        f"{fmt(s.get('bb_mid'))} / {fmt(s.get('bb_high'))} | "
        f"squeeze: {'YES' if s.get('squeeze') else 'no'}",
        f"  S/R        prev-day {fmt(s.get('prev_day_low'))}-{fmt(s.get('prev_day_high'))} | "
        f"52wk {fmt(s.get('low_52w'))}-{fmt(s.get('high_52w'))} | "
        f"round {fmt(s.get('round_below'))}/{fmt(s.get('round_above'))} | "
        f"POC {fmt(s.get('poc'))}",
    ]
    if s["notes"]:
        lines += ["", "  Signals:"] + [f"    • {n}" for n in s["notes"][:6]]
    return "\n".join(lines)


def composite_score(symbol: str, bars: list = None) -> int:
    """0-100 composite for pipeline callers (conviction engine)."""
    s = compute_suite(symbol, bars=bars)
    return int(s.get("score", 50)) if s else 50
