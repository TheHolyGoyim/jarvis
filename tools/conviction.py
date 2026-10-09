"""
conviction.py — JARVIS High-Conviction Trading Engine
Every signal in one score, every angle covered. Position sizing comes from
live Alpaca buying power × conviction-tier allocation (tools/risk_params.py).

Signal stack (100 pts total):
  Technical Analysis (multi-timeframe) .... 25 pts
  Social Media Sentiment (ST+Reddit) ...... 15 pts
  News Sentiment ..........................  10 pts
  Geopolitical / Macro fit ................  15 pts
  Options Flow (put/call ratio) ...........  10 pts
  Fear & Greed (market context) ...........  10 pts
  Insider Activity (SEC Form 4) ...........  15 pts

Score thresholds:
  80-100  MAXIMUM CONVICTION — trade now
  65-79   HIGH CONVICTION — strong entry
  50-64   MODERATE — watch and wait
  35-49   LOW — skip
   0-34   AVOID
"""

import os, re, json, math, time
from datetime import datetime, timedelta
from pathlib import Path

_DATA_DIR = Path.home() / "Documents" / "JARVIS" / "trading"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_UNIVERSE_CACHE_FILE = _DATA_DIR / "exchange_universe_cache.json"
_BUDGET_UNIV_CACHE_FILE = _DATA_DIR / "budget_universe_cache.json"


def _cache_read(path: Path, ttl_hours: float):
    try:
        if path.exists():
            age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
            if age_h < ttl_hours:
                return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _cache_write(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

def _cfg(k: str, d: str = "") -> str:
    return os.getenv(k, d)


_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

# ── Local AI (Ollama) ────────────────────────────────────────────────────────────
def _ai(prompt: str, system: str = "You are a sharp quant analyst. Be direct, specific, and brief.",
        timeout: int = 30) -> str:
    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": _OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False},
            timeout=timeout,
        )
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return ""


# ── News fetcher ────────────────────────────────────────────────────────────────
def _fetch_news(query: str, max_items: int = 8) -> list[str]:
    """Fetch headlines from Google News RSS for a given query."""
    try:
        import requests
        url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        r   = requests.get(url, timeout=8,
                           headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        titles = re.findall(r"<title>(.*?)</title>", r.text)
        # Skip the first (feed title)
        return [t for t in titles[1:max_items + 1] if t and "Google News" not in t]
    except Exception:
        return []


# ── Signal helpers ──────────────────────────────────────────────────────────────
def _ta_signal(symbol: str) -> tuple[int, str, list[str]]:
    """
    Returns (points: 0-30, verdict, reasons).
    Blends the classic multi-timeframe score 50/50 with the full
    technical-suite composite (tools/technical_suite: trend 30% /
    momentum 25% / volume 25% / volatility 10% / S-R 10%).
    """
    try:
        import tools.market as MKT
        bars = MKT._fetch_history(symbol, 90)
        if not bars or len(bars) < 21:
            return 10, "NO DATA", []
        ta      = MKT._compute_ta(bars)
        verdict, score, reasons = MKT._score_signal(ta)
        # score ranges roughly -10 to +10; map to 0-30
        pts = min(30, max(0, int((score + 10) / 20 * 30)))
        try:
            import tools.technical_suite as TS
            comp = TS.composite_score(symbol, bars=bars)   # 0-100
            pts = min(30, max(0, int(round((pts + comp * 30 / 100) / 2))))
            reasons = ([f"composite technical score {comp}/100"] + reasons)[:4]
        except Exception:
            pass
        return pts, verdict, reasons[:3]
    except Exception:
        return 10, "ERROR", []


def _news_signal(symbol: str) -> tuple[int, str]:
    """Returns (points: 0-20, summary). Fetches and scores recent headlines."""
    try:
        headlines = _fetch_news(f"{symbol} stock", max_items=6)
        if not headlines:
            return 10, "No news found"
        joined = " | ".join(headlines)
        # Fast keyword scoring before calling LLM
        bull_words = ["surge", "soar", "jump", "rally", "beat", "upgrade", "buy",
                      "record", "growth", "profit", "deal", "win", "launch", "partnership"]
        bear_words = ["fall", "drop", "plunge", "miss", "cut", "sell", "loss",
                      "downgrade", "sue", "recall", "fraud", "warn", "fine", "crash"]
        text_lower = joined.lower()
        bull_hits  = sum(1 for w in bull_words if w in text_lower)
        bear_hits  = sum(1 for w in bear_words if w in text_lower)
        net        = bull_hits - bear_hits
        if net >= 3:
            pts, label = 20, "BULLISH"
        elif net >= 1:
            pts, label = 15, "LEANING BULLISH"
        elif net == 0:
            pts, label = 10, "NEUTRAL"
        elif net == -1:
            pts, label = 5, "LEANING BEARISH"
        else:
            pts, label = 0, "BEARISH"
        snippet = headlines[0][:80] if headlines else ""
        return pts, f"{label} — {snippet}"
    except Exception:
        return 10, "News error"


def _options_signal(symbol: str) -> tuple[int, str]:
    """Returns (points: 0-15, detail). Scores options flow via put/call ratio."""
    try:
        import requests
        r    = requests.get(
            f"https://query1.finance.yahoo.com/v7/finance/options/{symbol}",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return 7, "Options data unavailable"
        data    = r.json()["optionChain"]["result"][0]
        calls   = data["options"][0].get("calls", [])
        puts    = data["options"][0].get("puts",  [])
        call_oi = sum(c.get("openInterest", 0) for c in calls)
        put_oi  = sum(p.get("openInterest", 0) for p in puts)
        ratio   = put_oi / call_oi if call_oi > 0 else 1.0
        # High call OI vs put OI = bullish options positioning
        if ratio < 0.5:
            return 15, f"VERY BULLISH — P/C Ratio: {ratio:.2f} (heavy call buying)"
        elif ratio < 0.8:
            return 12, f"BULLISH — P/C Ratio: {ratio:.2f}"
        elif ratio < 1.2:
            return 8,  f"NEUTRAL — P/C Ratio: {ratio:.2f}"
        elif ratio < 1.8:
            return 4,  f"BEARISH — P/C Ratio: {ratio:.2f} (put buying elevated)"
        else:
            return 0,  f"VERY BEARISH — P/C Ratio: {ratio:.2f} (heavy put buying)"
    except Exception:
        return 7, "Options unavailable"


def _fear_greed_signal() -> tuple[int, str]:
    """Returns (points: 0-10, detail). Extreme fear = contrarian buy."""
    try:
        import requests
        r = requests.get("https://api.alternative.me/fng/?limit=1&format=json", timeout=6)
        if r.ok:
            d     = r.json().get("data", [{}])[0]
            score = int(d.get("value", 50))
            label = d.get("value_classification", "Neutral")
            # Extreme fear: best buying opportunity
            if score <= 20:
                return 10, f"EXTREME FEAR {score}/100 — Contrarian BUY zone"
            elif score <= 40:
                return 8,  f"FEAR {score}/100 — Oversold conditions building"
            elif score <= 60:
                return 5,  f"NEUTRAL {score}/100 — No strong directional edge"
            elif score <= 80:
                return 3,  f"GREED {score}/100 — Elevated; watch for pullbacks"
            else:
                return 1,  f"EXTREME GREED {score}/100 — Caution: overbought market"
    except Exception:
        pass
    return 5, "Fear/Greed unavailable"


def _insider_signal(symbol: str) -> tuple[int, str]:
    """Returns (points: 0-10, detail). Insider buying = strong bullish signal."""
    try:
        since  = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        import requests
        params = {"q": f'"{symbol}"', "forms": "4",
                  "dateRange": "custom", "startdt": since}
        r = requests.get("https://efts.sec.gov/LATEST/search-index",
                         params=params, timeout=8,
                         headers={"User-Agent": "JARVIS/1.0"})
        if not r.ok:
            return 5, "SEC unavailable"
        hits = r.json().get("hits", {}).get("hits", [])
        if not hits:
            return 5, "No insider filings (neutral)"
        count = len(hits)
        if count >= 5:
            return 10, f"{count} insider filings — elevated activity (bullish)"
        elif count >= 2:
            return 7,  f"{count} insider filings — some activity"
        else:
            return 5,  f"{count} insider filing"
    except Exception:
        return 5, "Insider data unavailable"


def _geo_signal(symbol: str, geo_themes: list[str]) -> tuple[int, str]:
    """
    Returns (points: 0-15, detail).
    Scores how well the symbol aligns with current geopolitical/macro themes.
    """
    # Sector → list of theme tags that give this stock a tailwind
    sector_map = {
        # Defense / geopolitical tension
        "LMT":  ["defense", "war", "geopolitical", "nato"],
        "RTX":  ["defense", "war", "geopolitical"],
        "NOC":  ["defense", "war", "space"],
        "GD":   ["defense", "war"],
        "AXON": ["defense", "law"],
        "KTOS": ["defense", "drone", "ai"],
        "CACI": ["defense", "data"],
        "LDOS": ["defense", "government"],
        # Semiconductors / AI / tech war
        "NVDA": ["chips", "ai", "semiconductor", "tech", "nvidia"],
        "AMD":  ["chips", "semiconductor", "tech", "ai"],
        "SMCI": ["chips", "ai", "server", "tech"],
        "TSM":  ["chips", "semiconductor", "china", "taiwan"],
        "AVGO": ["chips", "semiconductor", "networking"],
        "ARM":  ["chips", "semiconductor", "tech"],
        "INTC": ["chips", "semiconductor"],
        # Energy / commodity
        "XOM":  ["oil", "energy", "commodity"],
        "CVX":  ["oil", "energy"],
        "OXY":  ["oil", "energy"],
        "DVN":  ["oil", "energy"],
        "HAL":  ["oil", "drilling"],
        # Gold / safe haven
        "GLD":  ["gold", "safe haven", "inflation", "fear"],
        "SLV":  ["silver", "commodity"],
        "GDX":  ["gold", "mining"],
        # China / trade war
        "BABA": ["china", "trade", "ecommerce"],
        "JD":   ["china", "ecommerce"],
        "PDD":  ["china", "retail"],
        "KWEB": ["china", "tech"],
        # Finance / rates
        "JPM":  ["banking", "rates", "finance"],
        "GS":   ["banking", "rates"],
        "BAC":  ["banking", "rates"],
        # AI / tech
        "PLTR": ["ai", "defense", "data", "government"],
        "MSFT": ["ai", "cloud", "tech"],
        "GOOGL":["ai", "tech", "search"],
        "META": ["ai", "social", "tech"],
        "TSLA": ["ev", "energy", "battery", "tech"],
        "MSTR": ["bitcoin", "crypto"],
        "COIN": ["bitcoin", "crypto"],
        "CRWD": ["security", "cybersecurity", "ai", "defense"],
        "NET":  ["cloud", "security", "tech"],
    }
    sym_tags  = sector_map.get(symbol.upper(), ["general"])
    # Normalize geo_themes — split multi-word themes too
    all_theme_words = set()
    for t in geo_themes:
        for w in t.lower().split():
            all_theme_words.add(w)
    # Count how many of the symbol's tags match active themes
    hits = [tag for tag in sym_tags if any(tag in tw or tw in tag for tw in all_theme_words)]
    if len(hits) >= 2:
        return 15, f"Strong tailwind: {', '.join(hits[:3])} aligns with active themes"
    elif len(hits) == 1:
        return 10, f"Geopolitical tailwind: {hits[0]}"
    else:
        return 5,  "Neutral geopolitical fit"


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def conviction_score(symbol: str) -> str:
    """
    Full 0-100 conviction score for a symbol.
    Combines: TA, social media, news, options flow, geo/macro, Fear/Greed, insider.
    """
    symbol = symbol.upper().strip()
    ts     = datetime.now().strftime("%H:%M:%S")

    # Pull geo themes first (needed for geo signal)
    geo_raw    = _geo_brief_themes()
    geo_themes = geo_raw.get("themes", [])

    # Run all signals (raw values, then scaled to new allocation)
    ta_raw,  ta_v,   ta_rsns = _ta_signal(symbol)       # raw 0-30
    news_raw, news_v          = _news_signal(symbol)     # raw 0-20
    opt_raw,  opt_v           = _options_signal(symbol)  # raw 0-15
    fg_pts,   fg_v            = _fear_greed_signal()     # 0-10 (unchanged)
    ins_raw,  ins_v           = _insider_signal(symbol)  # raw 0-10
    geo_pts,  geo_v           = _geo_signal(symbol, geo_themes)  # 0-15 (unchanged)

    # Social media sentiment (NEW — 0-15 pts)
    try:
        import tools.social_intel as SOC
        soc_pts, soc_v = SOC.social_signal(symbol)
    except Exception:
        soc_pts, soc_v = 7, "Social unavailable (neutral)"

    # Rescale to new allocation
    ta_pts   = int(ta_raw  * 25 / 30)   # 0-25 (was 0-30)
    news_pts = int(news_raw * 10 / 20)  # 0-10 (was 0-20)
    opt_pts  = int(opt_raw  * 10 / 15)  # 0-10 (was 0-15)
    ins_pts  = int(ins_raw  * 15 / 10)  # 0-15 (was 0-10) — insiders matter more

    total = ta_pts + soc_pts + news_pts + opt_pts + geo_pts + fg_pts + ins_pts
    total = min(100, max(0, total))

    if total >= 80:
        verdict = "MAXIMUM CONVICTION — TRADE NOW"
        action  = "Execute bracket order sized by conviction tier (risk params)"
    elif total >= 65:
        verdict = "HIGH CONVICTION — STRONG BUY"
        action  = "Strong entry with ATR-based stop and 2:1 R/R target"
    elif total >= 50:
        verdict = "MODERATE — WATCH"
        action  = "Monitor for confirmation; do not force entry"
    elif total >= 35:
        verdict = "LOW — SKIP"
        action  = "Better opportunities elsewhere"
    else:
        verdict = "AVOID"
        action  = "Multiple signals negative; do not trade"

    bar_fill = int(total / 5)
    bar      = "█" * bar_fill + "░" * (20 - bar_fill)

    lines = [
        f"Conviction Score: {symbol}  [{ts}]",
        f"",
        f"  SCORE:  {total}/100  [{bar}]",
        f"  SIGNAL: {verdict}",
        f"  ACTION: {action}",
        f"",
        f"  ── Signal Breakdown ──────────────────────────",
        f"  Technical Analysis:   {ta_pts:>2}/25  {ta_v}",
    ]
    for r in ta_rsns:
        lines.append(f"                         → {r}")
    lines += [
        f"  Social Media (ST+WSB): {soc_pts:>2}/15  {soc_v}",
        f"  News Sentiment:        {news_pts:>2}/10  {news_v}",
        f"  Geopolitical Fit:      {geo_pts:>2}/15  {geo_v}",
        f"  Options Flow:          {opt_pts:>2}/10  {opt_v}",
        f"  Fear & Greed:          {fg_pts:>2}/10  {fg_v}",
        f"  Insider Activity:      {ins_pts:>2}/15  {ins_v}",
    ]
    if geo_themes:
        lines += ["", f"  Active Macro Themes: {', '.join(geo_themes[:4])}"]
    try:
        import tools.charts as CHARTS
        breakdown = {
            "TA": ta_pts, "Social": soc_pts, "News": news_pts,
            "Geo": geo_pts, "Options": opt_pts, "F&G": fg_pts, "Insider": ins_pts,
        }
        chart_path = CHARTS.conviction_breakdown_chart(symbol, total, breakdown)
        if chart_path:
            lines += ["", f"Chart saved: {chart_path}"]
    except Exception:
        pass
    return "\n".join(lines)


def _geo_brief_themes() -> dict:
    """
    Returns dict with keys: themes (list[str]), headline_context (str).
    Fetches market-moving news and extracts dominant macro/geo themes via LLM.
    Fast-path: keyword extraction before LLM if LLM unavailable.
    """
    headlines = (
        _fetch_news("geopolitical markets financial", 5) +
        _fetch_news("US economy federal reserve", 4) +
        _fetch_news("tech stocks earnings", 3)
    )
    if not headlines:
        return {"themes": ["general", "tech", "rates"], "headline_context": "No news fetched"}

    headline_block = "\n".join(f"- {h}" for h in headlines[:12])

    # Fast keyword extraction
    text = headline_block.lower()
    theme_keywords = {
        "defense":    ["war", "military", "nato", "ukraine", "taiwan", "missile", "pentagon", "defense"],
        "oil":        ["oil", "opec", "crude", "energy", "pipeline", "gas price"],
        "chips ai":   ["semiconductor", "chips", "nvidia", "ai chip", "artificial intelligence", "tsmc"],
        "china":      ["china", "beijing", "tariff", "trade war", "hong kong", "xi"],
        "rates":      ["federal reserve", "fed rate", "interest rate", "inflation", "cpi", "pce"],
        "gold":       ["gold", "safe haven", "recession", "dollar weak"],
        "crypto":     ["bitcoin", "crypto", "eth", "btc", "coinbase"],
        "biotech":    ["fda", "drug", "clinical trial", "pharma", "vaccine"],
        "tech":       ["apple", "microsoft", "google", "meta", "amazon", "earnings"],
    }
    found = []
    for theme, kws in theme_keywords.items():
        if any(k in text for k in kws):
            found.append(theme)
    if not found:
        found = ["general", "tech"]

    # LLM enrichment (non-blocking — if it fails we use keyword themes)
    ai_themes = found
    ai_prompt = (
        f"Current financial headlines:\n{headline_block}\n\n"
        f"List the 4 most important macro/geopolitical trading themes right now "
        f"as single keywords separated by commas (e.g. 'defense, chips, rates, china'). "
        f"No explanation, just the keywords."
    )
    ai_resp = _ai(ai_prompt, timeout=15)
    if ai_resp:
        extracted = [t.strip().lower() for t in re.split(r"[,\n]", ai_resp) if t.strip()]
        if extracted:
            ai_themes = extracted[:6]

    return {"themes": ai_themes, "headline_context": headline_block}


def geopolitical_brief() -> str:
    """
    Full macro and geopolitical intelligence brief with specific stock picks.
    Uses real news headlines + LLM analysis to identify the top trading opportunities
    based on: geopolitical events, sector rotation, macro economics, policy shifts.
    """
    geo_data   = _geo_brief_themes()
    themes     = geo_data["themes"]
    headlines  = geo_data["headline_context"]

    try:
        import tools.intel as INTEL
        fg_text = INTEL.fear_greed()
        fg_match = re.search(r"(\d+)/100", fg_text)
        fg_val   = int(fg_match.group(1)) if fg_match else 50
        fg_line  = fg_text.split("\n")[2] if len(fg_text.split("\n")) > 2 else ""
    except Exception:
        fg_val, fg_line = 50, ""

    try:
        import tools.intel as INTEL
        eco_text = INTEL.economic_events()
    except Exception:
        eco_text = "Economic calendar unavailable"

    system_prompt = (
        "You are a top-tier quant fund manager with deep expertise in geopolitics, "
        "macro economics, sector rotation, and technical analysis. "
        "You turn macro events into specific, actionable trade ideas with clear rationale. "
        "Be direct, specific, and actionable. Mention real ticker symbols."
    )
    user_prompt = (
        f"Today is {datetime.now().strftime('%Y-%m-%d')}.\n"
        f"Fear & Greed Index: {fg_val}/100 — {fg_line}\n\n"
        f"Current financial/geopolitical headlines:\n{headlines}\n\n"
        f"Macro themes detected: {', '.join(themes)}\n\n"
        f"Task: Provide a structured trading brief covering:\n"
        f"1. MACRO REGIME: bull/bear/volatile? Why?\n"
        f"2. TOP 3 GEOPOLITICAL TRADES: specific ticker + 1-sentence entry logic + catalyst\n"
        f"3. SECTORS TO BUY NOW: 2 sectors with momentum + example tickers\n"
        f"4. SECTORS TO AVOID: 1-2 sectors and brief reason\n"
        f"5. KEY RISK TO WATCH: 1 event that could reverse the thesis\n\n"
        f"Format clearly. Be concise. Focus on trades actionable within 1-5 days."
    )
    brief = _ai(user_prompt, system=system_prompt, timeout=40)
    if not brief:
        brief = (
            f"[AI engine offline — keyword analysis only]\n"
            f"Active themes: {', '.join(themes)}\n"
            f"Fear & Greed: {fg_val}/100\n"
            f"Suggested focus: defense ({', '.join(['LMT','RTX','NOC'])}), "
            f"chips ({', '.join(['NVDA','AMD','SMCI'])}), "
            f"energy ({', '.join(['OXY','DVN'])})"
        )

    lines = [
        f"GEOPOLITICAL & MACRO INTELLIGENCE BRIEF  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
        f"",
        f"ACTIVE THEMES: {', '.join(themes).upper()}",
        f"FEAR & GREED:  {fg_val}/100",
        f"",
        "─" * 60,
        brief,
        "─" * 60,
        f"",
        f"Run 'conviction score [TICKER]' for full signal analysis on any of these picks.",
        f"Run 'auto hunt' to scan the full universe and find the highest-conviction setup.",
    ]
    return "\n".join(lines)


def market_regime() -> str:
    """
    Classify the current market regime: BULL / BEAR / VOLATILE / SIDEWAYS.
    Uses SPY + QQQ trend analysis + Fear & Greed + VIX proxy.
    """
    try:
        import tools.market as MKT
        spy_bars = MKT._fetch_history("SPY", 220)
        qqq_bars = MKT._fetch_history("QQQ", 60)
        spy_ta   = MKT._compute_ta(spy_bars) if spy_bars else {}
        qqq_ta   = MKT._compute_ta(qqq_bars) if qqq_bars else {}
        spy_v, spy_s, _ = MKT._score_signal(spy_ta) if spy_ta else ("N/A", 0, [])
        qqq_v, qqq_s, _ = MKT._score_signal(qqq_ta) if qqq_ta else ("N/A", 0, [])
        spy_price = float(spy_ta.get("price")  or 0)
        qqq_price = float(qqq_ta.get("price")  or 0)
        spy_sma50 = float(spy_ta.get("sma50")  or 0)
        spy_sma200= float(spy_ta.get("sma200") or 0)
        spy_rsi   = float(spy_ta.get("rsi")    or 50)
        avg_score = (spy_s + qqq_s) / 2
        if avg_score >= 4 and spy_price > spy_sma50:
            regime = "BULL MARKET"
            detail = "SPY above SMA50, momentum positive. Favor longs, tech, growth."
            style  = "Momentum plays, breakouts, VWAP entries, high-beta longs"
        elif avg_score <= -3 or (spy_price < spy_sma200 and spy_rsi < 45):
            regime = "BEAR MARKET"
            detail = "Below key MAs, negative momentum. Defensive posture required."
            style  = "Inverse ETFs (SQQQ/SPXU), defensive sectors, tight stops"
        elif abs(avg_score) <= 1:
            regime = "SIDEWAYS / CHOPPY"
            detail = "No clear trend. Mean-reversion plays work best."
            style  = "VWAP deviation trades, range-bound scalps, avoid momentum"
        else:
            regime = "VOLATILE / TRANSITIONING"
            detail = "Mixed signals — use smaller position sizes, tighter stops."
            style  = "ORB setups, gap-and-go, short-duration trades only"
        fg_pts, fg_v = _fear_greed_signal()
        return "\n".join([
            f"Market Regime Analysis  [{datetime.now().strftime('%H:%M')}]",
            f"",
            f"  REGIME:    {regime}",
            f"  Detail:    {detail}",
            f"  Strategy:  {style}",
            f"",
            f"  SPY:   ${spy_price:,.2f}  vs SMA50 ${spy_sma50:,.2f}  vs SMA200 ${spy_sma200:,.2f}",
            f"  SPY Score: {spy_s:+d}  ({spy_v})",
            f"  QQQ Score: {qqq_s:+d}  ({qqq_v})",
            f"  RSI(SPY):  {spy_rsi:.1f}",
            f"",
            f"  {fg_v}",
        ])
    except Exception as e:
        return f"Market regime error: {e}"


# ── Broad NYSE/NASDAQ screener — budget-friendly tickers with live sentiment ──

def _fetch_tradable_universe(exchanges: tuple = ("NYSE", "NASDAQ")) -> list[str]:
    """
    Full roster of tradable common-stock tickers on the given exchanges, via
    Alpaca's asset catalog. Cached 24h locally — the exchange roster barely
    changes intraday, so there's no need to refetch thousands of assets every run.
    """
    cached = _cache_read(_UNIVERSE_CACHE_FILE, ttl_hours=24)
    if cached is not None:
        return cached
    try:
        import tools.trading as TRD
        assets = TRD._api("GET", "/v2/assets?status=active&asset_class=us_equity")
    except Exception:
        return []
    out = []
    for a in assets:
        sym = a.get("symbol", "")
        if not a.get("tradable"):
            continue
        if a.get("exchange") not in exchanges:
            continue
        # Plain common-stock tickers only — skip warrants/units/preferred/rights
        if not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        out.append(sym)
    _cache_write(_UNIVERSE_CACHE_FILE, out)
    return out


def _snapshot_batch(symbols: list[str]) -> dict:
    """Latest price + daily volume for up to hundreds of symbols, batched 100 at a time."""
    import tools.trading as TRD
    out = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        try:
            data = TRD._data("/v2/stocks/snapshots", params={"symbols": ",".join(chunk)})
        except Exception:
            continue
        for sym, snap in (data or {}).items():
            trade = snap.get("latestTrade") or {}
            daily = snap.get("dailyBar") or {}
            price = trade.get("p") or daily.get("c") or 0
            vol   = daily.get("v") or 0
            if price:
                out[sym] = {"price": float(price), "volume": int(vol)}
        time.sleep(0.15)
    return out


def _budget_friendly_universe(max_price: float = 0, min_dollar_volume: float = 0,
                              top_n: int = 60) -> list[str]:
    """
    Screens the full NYSE + NASDAQ tradable roster for LIQUID tickers, ranked
    by dollar volume (a proxy for how much retail/market attention a name is
    getting right now). The liquidity floor comes from the active risk
    profile's scan prefs (risk_params.SCAN_PREFS) — capital no longer caps
    which prices we can even look at (the old ≤$60 ceiling is retired).
    max_price <= 0 means no price ceiling.
    Cached 4h — the expensive full-roster snapshot pass doesn't need to rerun
    every auto-hunt cycle (every ~3min after a trade closes).
    """
    if min_dollar_volume <= 0:
        try:
            import tools.risk_params as RP
            min_dollar_volume = RP.scan_prefs().get("min_dollar_volume", 10_000_000)
        except Exception:
            min_dollar_volume = 10_000_000

    cache_key = f"{max_price:.0f}_{min_dollar_volume:.0f}_{top_n}"
    cached = _cache_read(_BUDGET_UNIV_CACHE_FILE, ttl_hours=4)
    if cached is not None and cached.get("key") == cache_key:
        return cached.get("symbols", [])

    all_syms = _fetch_tradable_universe()
    if not all_syms:
        return []

    # Sample across the full roster rather than truncating alphabetically,
    # so budget-friendly names outside the A-C range aren't systematically missed.
    if len(all_syms) > 3000:
        step = len(all_syms) // 3000
        all_syms = all_syms[::step]

    snaps = _snapshot_batch(all_syms)

    ranked = []
    for sym, s in snaps.items():
        price, vol = s["price"], s["volume"]
        if price <= 0 or (max_price > 0 and price > max_price):
            continue
        dollar_vol = price * vol
        if dollar_vol < min_dollar_volume:
            continue
        ranked.append((sym, dollar_vol))

    ranked.sort(key=lambda x: -x[1])
    result = [sym for sym, _ in ranked[:top_n]]
    _cache_write(_BUDGET_UNIV_CACHE_FILE, {"key": cache_key, "symbols": result})
    return result


def nyse_budget_screener(max_price: float = 0) -> str:
    """
    On-demand report: the broadest liquid NYSE/NASDAQ screen, ranked by dollar
    volume, with live social + retail order-flow sentiment on the top names.
    Pass max_price to filter (e.g. 'find cheap stocks with good sentiment');
    otherwise no price ceiling applies.
    """
    found = _budget_friendly_universe(max_price=max_price, top_n=25)
    if not found:
        return ("No liquid tickers found. This needs ALPACA_API_KEY configured "
                "(for the asset catalog + snapshots) and an internet connection.")

    try:
        import tools.social_intel as SOC
    except Exception:
        SOC = None

    lines = [
        f"NYSE/NASDAQ Budget Screener  [{datetime.now().strftime('%H:%M:%S')}]",
        f"  Scanned full tradable roster → {len(found)} budget-friendly, liquid candidates",
        "",
    ]
    for sym in found[:15]:
        if SOC:
            try:
                soc_pts, soc_v = SOC.social_signal(sym)
            except Exception:
                soc_pts, soc_v = 0, "sentiment unavailable"
        else:
            soc_pts, soc_v = 0, "sentiment unavailable"
        lines.append(f"  {sym:<6}  Sentiment {soc_pts:>2}/15  {soc_v}")
        time.sleep(0.1)

    lines += [
        "",
        "  Say 'conviction [ticker]' or 'auto hunt' for a full scored breakdown "
        "including these names.",
    ]
    return "\n".join(lines)


# ── Known high-short-interest tickers (squeeze watch, shared by the scans) ────
_SQUEEZE_CANDIDATES = [
    "GME", "AMC", "SPCE", "CLOV", "SAVA", "BBBY", "MSTR", "HOOD",
    "SOFI", "RIVN", "BYND", "OPEN", "RDFN", "AI", "SOUN", "LUNR",
    "RKLB", "NIO", "LCID", "XPEV", "NKLA", "GOEV", "WKHS",
]

# ── Universe of candidates for auto-hunt ───────────────────────────────────────
_UNIVERSE = [
    # High-beta momentum
    "NVDA", "AMD", "SMCI", "PLTR", "CRWD", "ARM", "AVGO",
    # Volatile / high-move candidates
    "TSLA", "MSTR", "COIN", "HOOD", "SOFI", "RKLB", "SOUN", "BBAI", "AI",
    # Defense / geopolitical
    "LMT", "RTX", "NOC", "AXON", "KTOS",
    # Energy
    "OXY", "DVN", "HAL",
    # Biotech
    "MRNA", "BNTX",
    # Leveraged ETFs (3x) — fastest compounders when direction right
    "TQQQ", "SOXL", "UPRO", "TNA", "LABU",
    # Emerging tech / cloud
    "NET", "DDOG", "SNOW",
    # Squeeze / meme potential
    "GME", "AMC", "SPCE",
    # China
    "BABA", "PDD",
    # Gold
    "GDX", "GDXJ",
]


def auto_hunt(auto_trade: bool = False) -> str:
    """
    Autonomous best-setup hunter: scans the full universe, scores every candidate,
    returns the top 5 highest-conviction plays with full signal breakdown.

    auto_trade=True: executes the best affordable pick as a bracket order,
    sized by conviction tier × live Alpaca buying power (risk_params).

    Strategy: finds the single best asymmetric setup right now using every signal
    (TA + news + options + geopolitical + insider + Fear/Greed).
    """
    start_ts = datetime.now().strftime("%H:%M:%S")

    # Step 1: Get global context (cached for session)
    geo_data   = _geo_brief_themes()
    geo_themes = geo_data["themes"]
    fg_pts, fg_v = _fear_greed_signal()

    # Step 2: Fast-scan universe with TA only
    try:
        import tools.market as MKT
        import tools.trading as TRD
    except ImportError as e:
        return f"Modules unavailable: {e}"

    budget_rem = TRD._budget_remaining()   # live buying power minus cash reserve

    # Merge the curated watchlist with a live broad NYSE/NASDAQ screen of
    # liquid tickers — widens the net beyond the fixed list so names with
    # real volume/sentiment right now aren't missed. No price ceiling.
    try:
        wide_pool = _budget_friendly_universe()
    except Exception:
        wide_pool = []
    # Cross-sector bridge companies always join the hunt — multiple tailwinds
    try:
        import tools.bridge_map as BRG
        bridge_pool = BRG.bridge_tickers()
    except Exception:
        BRG, bridge_pool = None, []
    scan_pool = list(dict.fromkeys(_UNIVERSE + bridge_pool + wide_pool))  # dedupe, preserve order
    # Profile-driven scanning behavior (goal engine / Markets dashboard):
    # aggressive and above also sweep squeeze/momentum candidates.
    try:
        import tools.risk_params as _RPP
        if _RPP.scan_prefs().get("include_squeeze"):
            scan_pool = list(dict.fromkeys(scan_pool + _SQUEEZE_CANDIDATES))
    except Exception:
        pass

    # Feed the live real-time trade tape (Alpaca IEX WebSocket) with everything
    # this hunt is about to consider, so live_tape_signal() has real data by the
    # time we're ready to execute — not just a REST snapshot at decision time.
    try:
        import tools.trade_stream as TAPE
        TAPE.update_watchlist(scan_pool)
    except Exception:
        TAPE = None

    fast_scores = []
    for sym in scan_pool:
        try:
            bars = MKT._fetch_history(sym, 60)
            if not bars or len(bars) < 20:
                continue
            ta = MKT._compute_ta(bars)
            if not ta:
                continue
            verdict, score, reasons = MKT._score_signal(ta)
            price = ta.get("price", 0)
            if price <= 0:
                continue
            fast_scores.append({
                "symbol":  sym,
                "ta_score": score,
                "verdict": verdict,
                "price":   price,
                "rsi":     ta.get("rsi", 0),
                "atr":     ta.get("atr") or price * 0.02,
                "reasons": reasons[:2],
            })
            time.sleep(0.1)
        except Exception:
            continue

    if not fast_scores:
        return "No data returned from universe scan. Check internet connection."

    # Step 3: Rank by TA score, take top 8 for deep analysis
    fast_scores.sort(key=lambda x: -x["ta_score"])
    candidates = fast_scores[:8]

    # Step 4: Full conviction score on top 8 — SAME allocation as
    # conviction_score() (TA25 + Social15 + News10 + Geo15 + Opts10 + F&G10 +
    # Insider15 = 100), so the entry score and the monitor's Rule-5 re-eval
    # are directly comparable instead of drifting apart on allocation alone.
    full_results = []
    for c in candidates:
        sym        = c["symbol"]
        ta_raw     = min(30, max(0, int((c["ta_score"] + 10) / 20 * 30)))
        news_raw,  news_v  = _news_signal(sym)      # raw 0-20
        opt_raw,   opt_v   = _options_signal(sym)   # raw 0-15
        geo_pts,   geo_v   = _geo_signal(sym, geo_themes)   # 0-15
        ins_raw,   ins_v   = _insider_signal(sym)   # raw 0-10
        try:
            import tools.social_intel as SOC
            soc_pts, soc_v = SOC.social_signal(sym)  # 0-15
        except Exception:
            soc_pts, soc_v = 7, "Social unavailable (neutral)"
        ta_pts     = int(ta_raw  * 25 / 30)
        news_pts   = int(news_raw * 10 / 20)
        opt_pts    = int(opt_raw  * 10 / 15)
        ins_pts    = int(ins_raw  * 15 / 10)
        total      = ta_pts + soc_pts + news_pts + opt_pts + fg_pts + ins_pts + geo_pts
        total      = min(100, max(0, total))
        # Can we afford at least 1 share?
        affordable = c["price"] <= budget_rem
        full_results.append({
            "symbol":    sym,
            "total":     total,
            "ta_pts":    ta_pts,
            "soc_pts":   soc_pts,
            "soc_v":     soc_v,
            "news_pts":  news_pts,
            "opt_pts":   opt_pts,
            "geo_pts":   geo_pts,
            "ins_pts":   ins_pts,
            "fg_pts":    fg_pts,
            "price":     c["price"],
            "rsi":       c["rsi"],
            "atr":       c["atr"],
            "verdict":   c["verdict"],
            "reasons":   c["reasons"],
            "news_v":    news_v,
            "opt_v":     opt_v,
            "geo_v":     geo_v,
            "ins_v":     ins_v,
            "affordable": affordable,
        })
        time.sleep(0.1)

    # Rank by conviction + bridge multiplier + political catalyst + geo risk.
    # The calibrated 100-pt base score is untouched; adjustments apply at
    # RANKING/entry time: political catalyst ×1.25/1.40/1.50 (24h window),
    # geo risk HIGH ×0.75 / CRITICAL ×0.50 on everything.
    try:
        import tools.political_intel as PI
        _geo_conv = PI.geo_conviction_multiplier()
    except Exception:
        PI, _geo_conv = None, 1.0
    for x in full_results:
        try:
            x["bridge_bonus"] = BRG.bridge_bonus(x["symbol"]) if BRG else 0
            x["bridge_line"]  = BRG.bridge_line(x["symbol"]) if BRG else ""
        except Exception:
            x["bridge_bonus"], x["bridge_line"] = 0, ""
        try:
            pol_m, pol_note = PI.catalyst_multiplier(x["symbol"]) if PI else (1.0, "")
        except Exception:
            pol_m, pol_note = 1.0, ""
        x["pol_mult"], x["pol_note"] = pol_m, pol_note
        # Chart-pattern multiplier (Feature 2): clear pattern ×1.3, +volume
        # ×1.5, multi-timeframe ×1.7; bearish patterns divide instead.
        try:
            import tools.chart_patterns as CP
            pat_m, pat_note = CP.pattern_multiplier(x["symbol"])
        except Exception:
            pat_m, pat_note = 1.0, ""
        x["pat_mult"], x["pat_note"] = pat_m, pat_note
        x["adj_total"] = round(x["total"] * pol_m * _geo_conv * pat_m, 1)
    full_results.sort(key=lambda x: -(x.get("adj_total", x["total"]) + x.get("bridge_bonus", 0)))
    top         = full_results[:5]
    top1        = full_results[0] if full_results else None
    end_ts      = datetime.now().strftime("%H:%M:%S")

    lines = [
        f"AUTO-HUNT: Universe Scan  [{start_ts} → {end_ts}]",
        f"  Scanned: {len(scan_pool)} symbols ({len(_UNIVERSE)} curated + {len(wide_pool)} broad-screened)  |  Analyzed: {len(candidates)} deep",
        f"  Capital available: ${budget_rem:,.2f} (live Alpaca buying power)",
        f"  Active themes: {', '.join(geo_themes[:4])}",
        f"  {fg_v}",
        f"",
        f"  ── TOP PICKS ─────────────────────────────────────────",
    ]
    for i, r in enumerate(top):
        rank_sym   = "★ #1" if i == 0 else f"   #{i+1}"
        bar_fill   = int(r["total"] / 5)
        mini_bar   = "█" * bar_fill + "░" * (20 - bar_fill)
        affd_note  = "" if r["affordable"] else "  ⚠ price > budget"
        lines.append(
            f"  {rank_sym}  {r['symbol']:<6}  {r['total']:>3}/100  [{mini_bar}]"
            f"  ${r['price']:>8,.2f}{affd_note}"
        )
        lines.append(f"       Signal: {r['verdict']}  RSI:{r['rsi']:.0f}  ATR:${r['atr']:.2f}")
        if r.get("bridge_line"):
            lines.append(f"       {r['bridge_line']}  [+{r.get('bridge_bonus', 0)} rank]")
        if r.get("pol_mult", 1.0) != 1.0:
            lines.append(f"       🏛 political catalyst ×{r['pol_mult']} — {r.get('pol_note','')[:70]}")
        if r.get("pat_mult", 1.0) != 1.0:
            lines.append(f"       📐 chart pattern ×{r['pat_mult']} — {r.get('pat_note','')[:70]}")
        for rsn in r["reasons"][:2]:
            lines.append(f"       → {rsn}")
        lines.append(
            f"       TA:{r['ta_pts']}/25  Social:{r['soc_pts']}/15  News:{r['news_pts']}/10  "
            f"Opts:{r['opt_pts']}/10  Geo:{r['geo_pts']}/15  "
            f"F&G:{r['fg_pts']}/10  Insider:{r['ins_pts']}/15"
        )
        lines.append(f"       {r['news_v'][:70]}")
        lines.append("")

    # Auto-trade: find best affordable pick (not just #1)
    if auto_trade:
        lines.append("  ── AUTO-TRADE EXECUTION ────────────────────────────────")
        # Markets-dashboard risk parameters govern every autonomous entry
        try:
            import tools.risk_params as RP
            _rp = RP.get_params()
            _gate_ok, _gate_why = RP.autonomy_gate()
        except Exception:
            RP, _rp = None, {}
            _gate_ok, _gate_why = True, ""
        try:
            import tools.trade_monitor as MON
        except Exception:
            MON = None
        if not _gate_ok:
            lines.append(f"  ⏸ {_gate_why}")
            lines.append("  Rankings above are analysis only — no order placed.")
            return "\n".join(lines)
        try:
            min_score = RP.min_conviction_engine() if RP else int(_rp.get("min_conviction", 5)) * 10
        except Exception:
            min_score = int(_rp.get("min_conviction", 5)) * 10
        # Walk ranked list — find highest-score pick that fits the budget
        trade_candidate = None
        tape_detail     = ""
        skipped         = []
        for r in full_results:
            if not r["affordable"]:
                # Try fractional if price is close (within 4x budget)
                if r["price"] <= budget_rem * 4:
                    reason = f"${r['price']:.2f} (score {r['total']}) — price above available capital"
                    skipped.append(f"{r['symbol']} ${r['price']:.2f} (score {r['total']})")
                    if MON:
                        try: MON.log_skip(r['symbol'], reason, source="auto_hunt")
                        except Exception: pass
                continue
            if r.get("adj_total", r["total"]) >= min_score:
                # Real-time tape confirmation — a high score can still walk into
                # a live sell-off between when the scan ran and now. Skip to the
                # next-best affordable pick rather than buying into active dumping.
                try:
                    tape_pts, tp_detail = TAPE.live_tape_signal(r["symbol"]) if TAPE else (5, "")
                except Exception:
                    tape_pts, tp_detail = 5, ""
                if tape_pts == 0:
                    reason = f"score {r['total']}/100 but live tape shows active sell pressure — {tp_detail}"
                    skipped.append(f"{r['symbol']} score {r['total']} but live tape shows active sell pressure")
                    if MON:
                        try: MON.log_skip(r['symbol'], reason, source="auto_hunt")
                        except Exception: pass
                    continue
                # Allowed-sectors filter (one yfinance lookup, candidates only)
                if RP:
                    _sec_ok, _sec_why = RP.sector_allowed(r["symbol"])
                    if not _sec_ok:
                        skipped.append(_sec_why)
                        if MON:
                            try: MON.log_skip(r['symbol'], _sec_why, source="auto_hunt")
                            except Exception: pass
                        continue
                trade_candidate = r
                tape_detail     = tp_detail
                break
            else:
                reason = f"conviction score {r['total']}/100 below the {min_score}/100 threshold"
                skipped.append(f"{r['symbol']} score {r['total']} < {min_score}")
                if MON:
                    try: MON.log_skip(r['symbol'], reason, source="auto_hunt")
                    except Exception: pass
        if skipped:
            lines.append(f"  Skipped (unaffordable/low-score): {', '.join(skipped[:4])}")
        if not trade_candidate:
            lines.append(
                f"  No high-conviction setup passed the gates (capital available: ${budget_rem:,.2f}).\n"
                f"  All top picks scored below {min_score} or failed tape/sector checks.\n"
                f"  Recommendation: wait for the next scan cycle or check 'sector heat'."
            )
        else:
            sym   = trade_candidate["symbol"]
            price = trade_candidate["price"]
            atr   = trade_candidate["atr"]
            score = trade_candidate["total"]
            try:
                # Conviction-tier sizing (Bug-2 spec): available capital ×
                # allocation % (5-6 → 2-3%, 7-8 → 4-6%, 9-10 → 7-10%), capped
                # by the profile's max_position_pct — all off LIVE buying power.
                try:
                    spend_cap = min(budget_rem, RP.position_size_dollars(int(score)))
                except Exception:
                    spend_cap = min(budget_rem, budget_rem * 0.05)
                # Geo risk shrinks size: ELEVATED -25%, HIGH -50%, CRITICAL = 0
                # (the autonomy gate also halts at CRITICAL — this is belt+braces)
                try:
                    import tools.political_intel as _PI
                    spend_cap *= _PI.geo_size_factor()
                except Exception:
                    pass
                stop_pct  = float(_rp.get("stop_loss_pct", 7.5))
                tp_pct    = float(_rp.get("take_profit_pct", 22.0))
                stop_d    = price * stop_pct / 100
                qty       = math.floor(spend_cap / price)
                while qty > 0 and qty * price > spend_cap:
                    qty -= 1
                if qty < 1:
                    lines.append(f"  ⚠ Cannot buy even 1 share of {sym} (${price:.2f}) within "
                                 f"the ${spend_cap:,.2f} conviction-tier allocation "
                                 f"(capital ${budget_rem:,.2f}).")
                else:
                    ok, reason = TRD._guard(sym)
                    if ok:
                        # Live account pre-trade check: buying power covers the
                        # spend, PDT status, no doubled-up position (Feature 5).
                        try:
                            import tools.account_sync as _SYNC
                            ok, reason = _SYNC.pre_trade_check(sym, qty * price)
                        except Exception:
                            pass
                    if not ok:
                        lines.append(f"  Trade blocked by guard: {reason}")
                    else:
                        stop_p   = round(price * (1 - stop_pct / 100), 2)
                        target_p = round(price * (1 + tp_pct / 100), 2)
                        body = {
                            "symbol": sym, "qty": str(qty), "side": "buy",
                            "type": "market", "time_in_force": "day",
                            "order_class": "bracket",
                            "take_profit": {"limit_price": f"{target_p:.2f}"},
                            "stop_loss":   {"stop_price":  f"{stop_p:.2f}"},
                        }
                        r = TRD._api("POST", "/v2/orders", body)
                        lines += [
                            f"",
                            f"  ✅ EXECUTED — Best affordable pick at {score}/100",
                            f"     BUY {qty} {sym} @ market  (${qty*price:.2f} deployed)",
                            f"     Stop:   ${stop_p:.2f}  (-{stop_d/price*100:.1f}%)",
                            f"     Target: ${target_p:.2f}  (+{(target_p-price)/price*100:.1f}%)",
                            f"     R/R:    {tp_pct/stop_pct:.1f}:1  |  Max loss: ${qty*stop_d:.2f}",
                            f"     Order ID: {r.get('id','?')[:8]}  Status: {r.get('status','?').upper()}",
                        ]
                        if tape_detail:
                            lines.append(f"     Live tape: {tape_detail}")
                        # Register with monitor for real-time tracking — store the
                        # full signal breakdown so 'why did you buy X' can answer
                        # with what was actually true at decision time, not a fresh recompute.
                        try:
                            import tools.trade_monitor as MON
                            reasoning = "\n".join([
                                f"  Verdict: {trade_candidate.get('verdict','?')}  "
                                f"(RSI {trade_candidate.get('rsi','?')}, ATR ${trade_candidate.get('atr',0):.2f})",
                                f"  TA:       {trade_candidate.get('ta_pts',0)}/25 — "
                                + "; ".join(trade_candidate.get("reasons", [])[:3]),
                                f"  Social:   {trade_candidate.get('soc_pts',0)}/15 — {trade_candidate.get('soc_v','')}",
                                f"  News:     {trade_candidate.get('news_pts',0)}/10 — {trade_candidate.get('news_v','')}",
                                f"  Options:  {trade_candidate.get('opt_pts',0)}/10 — {trade_candidate.get('opt_v','')}",
                                f"  Geo:      {trade_candidate.get('geo_pts',0)}/15 — {trade_candidate.get('geo_v','')}",
                                f"  Insider:  {trade_candidate.get('ins_pts',0)}/15 — {trade_candidate.get('ins_v','')}",
                                f"  F&G:      {trade_candidate.get('fg_pts',0)}/10",
                                trade_candidate.get("bridge_line", ""),
                                f"  Live tape: {tape_detail}" if tape_detail else "",
                            ])
                            MON.register_trade(sym, qty, price, stop_p, target_p, score, reasoning)
                            # Proactive chat notification — the user shouldn't have to
                            # go looking for what JARVIS just did; the headline reason
                            # plus a pointer to the full stored breakdown.
                            headline = (trade_candidate.get("pat_note") or
                                       trade_candidate.get("bridge_line") or
                                       (trade_candidate.get("reasons") or ["high-conviction setup"])[0])
                            MON._push_user_alert(
                                f"✅ Bought {sym} ${qty*price:,.0f} — {headline}, "
                                f"conviction {score}/100, target +{tp_pct:.0f}% in ~5-7 days. "
                                f"Say 'explain {sym}' for full analysis."
                            )
                        except Exception:
                            pass
                        # Feature-3 prediction block for the executed pick
                        try:
                            import tools.prediction as PRED
                            lines += [""] + PRED.predict(sym).split("\n")[:10]
                        except Exception:
                            pass
            except Exception as ex:
                lines.append(f"  Auto-trade error: {ex}")
    elif not auto_trade and top1:
        lines.append(
            f"  To execute: say 'auto hunt and trade' or "
            f"'conviction trade {top1['symbol']}'"
        )

    return "\n".join(lines)


def short_squeeze_scan() -> str:
    """
    Scans for short squeeze candidates: high short interest + positive catalyst + TA momentum.
    These are the highest-velocity plays for rapid compounding.
    """
    # Known high-short-interest tickers (updated periodically by user)
    squeeze_candidates = _SQUEEZE_CANDIDATES
    try:
        import tools.market as MKT
        results = []
        for sym in squeeze_candidates:
            try:
                bars = MKT._fetch_history(sym, 30)
                if not bars or len(bars) < 10:
                    continue
                ta    = MKT._compute_ta(bars)
                if not ta:
                    continue
                price = ta.get("price", 0)
                rsi   = ta.get("rsi",   50)
                atr   = ta.get("atr") or price * 0.02
                vol_chg = ta.get("volume", 0) / max(ta.get("avg_volume", 1), 1)
                _, score, reasons = MKT._score_signal(ta)
                headlines = _fetch_news(f"{sym} short squeeze", max_items=3)
                has_catalyst = bool(headlines)
                squeeze_score = (
                    (5 if rsi < 40 else 2 if rsi < 55 else 0) +
                    (5 if vol_chg > 2 else 2 if vol_chg > 1.3 else 0) +
                    (3 if has_catalyst else 0) +
                    max(0, score)
                )
                results.append({
                    "symbol": sym, "score": squeeze_score, "price": price,
                    "rsi": rsi, "vol_chg": vol_chg, "reasons": reasons[:1],
                    "headline": headlines[0][:60] if headlines else "",
                })
                time.sleep(0.15)
            except Exception:
                continue
        results.sort(key=lambda x: -x["score"])
        top = results[:8]
        lines = [
            f"Short Squeeze Scanner  [{datetime.now().strftime('%H:%M')}]",
            f"  Scanned: {len(squeeze_candidates)} known high-SI tickers",
            f"",
            f"  RANK  SYMBOL   PRICE     RSI    VOL-CHNG  SCORE",
            f"  " + "─" * 55,
        ]
        for i, r in enumerate(top):
            lines.append(
                f"  #{i+1:<3}  {r['symbol']:<7}  ${r['price']:>8,.2f}"
                f"  RSI:{r['rsi']:>4.0f}  vol:{r['vol_chg']:>4.1f}x  [{r['score']:>2}/13]"
            )
            if r["headline"]:
                lines.append(f"          Catalyst: {r['headline']}")
            if r["reasons"]:
                lines.append(f"          TA: {r['reasons'][0]}")
        if not top:
            lines.append("  No squeeze candidates identified with current data.")
        lines += [
            "",
            "  Tip: Short squeezes are violent and fast. Use tight stops (1.5-2% max loss).",
            "  Run 'conviction score [SYMBOL]' on top picks before trading.",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Squeeze scan error: {e}"


def sector_heat() -> str:
    """
    Which sectors are running hot right now? Scores 9 major sectors using ETF performance.
    Routes capital to the strongest sector tailwind.
    """
    # proxy ETF → (sector name, stock pick for the sector)
    sector_map = [
        ("XLK",  "Technology",     "NVDA"),
        ("SMH",  "Semiconductors", "AMD"),
        ("XLE",  "Energy",         "OXY"),
        ("ITA",  "Defense",        "LMT"),
        ("XLF",  "Financials",     "GS"),
        ("XLV",  "Healthcare",     "UNH"),
        ("XLY",  "Consumer",       "AMZN"),
        ("GLD",  "Gold/Metals",    "GDX"),
        ("KWEB", "China/EM",       "PDD"),
    ]
    try:
        import tools.trading as TRD
        all_syms = [s[0] for s in sector_map]
        snap     = TRD._data("/v2/stocks/snapshots", {"symbols": ",".join(all_syms)})
        results  = []
        for proxy, sector, pick in sector_map:
            s    = snap.get(proxy, {})
            bar  = s.get("dailyBar",    {})
            prev = s.get("prevDailyBar", {})
            curr = float(bar.get("c") or bar.get("o") or 0)
            opn  = float(bar.get("o") or curr)
            pc   = float(prev.get("c") or opn)
            if not curr or not pc:
                continue
            day_chg = (curr - pc) / pc * 100 if pc else 0
            # Use week-ago approximation from prevDailyBar as 1-day proxy, day chg as heat
            score   = day_chg
            results.append({
                "sector": sector, "proxy": proxy, "pick": pick,
                "price": curr, "day_chg": day_chg, "score": score,
            })
        results.sort(key=lambda x: -x["score"])
        lines = [
            f"Sector Heat Map  [{datetime.now().strftime('%H:%M')}]",
            f"  Today's sector rotation — sorted by strength",
            f"",
            f"  {'SECTOR':<16}  {'PROXY':<6}  {'DAY%':>6}  TRADE",
            f"  " + "─" * 55,
        ]
        for i, r in enumerate(results):
            arrow = "▲" if r["score"] >= 0 else "▼"
            hot   = " ← FOCUS HERE" if i == 0 else ""
            lines.append(
                f"  {r['sector']:<16}  {r['proxy']:<6}  {r['day_chg']:>+5.2f}%  "
                f"{arrow} {r['pick']}{hot}"
            )
        if results:
            top = results[0]
            lines += [
                f"",
                f"  HOTTEST: {top['sector']} ({top['proxy']} {top['day_chg']:+.2f}% today)",
                f"  Best equity play: {top['pick']}",
                f"  Run 'conviction score {top['pick']}' or 'auto hunt' to enter.",
            ]
        if not results:
            return "Sector heat: No snapshot data returned. Market may be closed."
        try:
            import tools.charts as CHARTS
            chart_path = CHARTS.sector_heat_chart(results)
            if chart_path:
                lines += ["", f"Chart saved: {chart_path}"]
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        return f"Sector heat error: {e}"
