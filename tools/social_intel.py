"""
social_intel.py — JARVIS Social & Geopolitical Intelligence Engine
Taps public APIs — no paid keys required.

Sources:
  StockTwits   — real-time crowd sentiment (free API, no auth)
  Reddit WSB   — r/wallstreetbets + r/stocks + r/investing
  Finviz       — headline scraper
  Google News  — multi-source geopolitical feeds
"""

import os, re, json, time
from datetime import datetime
from pathlib import Path

_CACHE_DIR = Path.home() / "Documents" / "JARVIS" / "intel_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")


# ── Shared helpers ──────────────────────────────────────────────────────────────

def _get(url: str, headers: dict = None, timeout: int = 8):
    try:
        import requests
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=timeout)
        return r if r.ok else None
    except Exception:
        return None


def _cache_get(key: str, ttl_minutes: int = 10):
    f = _CACHE_DIR / f"{re.sub(r'[^a-zA-Z0-9_]', '_', key)}.json"
    if f.exists():
        age = (datetime.now().timestamp() - f.stat().st_mtime) / 60
        if age < ttl_minutes:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def _cache_set(key: str, data):
    try:
        f = _CACHE_DIR / f"{re.sub(r'[^a-zA-Z0-9_]', '_', key)}.json"
        f.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


def _ai(prompt: str, timeout: int = 40) -> str:
    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": _OLLAMA_MODEL, "prompt": prompt,
                  "system": "You are a sharp financial analyst. Be direct, specific, concise.",
                  "stream": False},
            timeout=timeout,
        )
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return "(Local AI offline)"


# ══════════════════════════════════════════════════════════════════════════════
# STOCKTWITS
# ══════════════════════════════════════════════════════════════════════════════

def _alpaca_data_get(path: str, params: dict = None, timeout: int = 10):
    """Alpaca public market-data API (trade tape, quotes) — reuses .env Alpaca keys."""
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_API_SECRET", "")
    if not key or not secret:
        return None
    try:
        import requests
        hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        r = requests.get(f"https://data.alpaca.markets{path}", headers=hdrs,
                         params=params, timeout=timeout)
        return r.json() if r.ok else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# RETAIL ORDER-FLOW (public trade tape)
# ══════════════════════════════════════════════════════════════════════════════

def retail_trade_flow(symbol: str) -> dict:
    """
    Retail buy/sell pressure proxy from the public trade tape (Alpaca IEX feed).
    Classifies each print with the tick rule (uptick=buy-side, downtick=sell-side)
    and flags odd-lot prints (<=100 shares) as likely-retail activity — institutions
    rarely route full size through a single small print.
    Returns dict: {buy_ratio, retail_pct, trade_count, sentiment, summary}
    """
    sym = symbol.upper().strip()
    key = f"tradeflow_{sym}"
    cached = _cache_get(key, ttl_minutes=5)
    if cached:
        return cached

    data   = _alpaca_data_get(f"/v2/stocks/{sym}/trades", params={"limit": 300, "feed": "iex"})
    trades = (data or {}).get("trades", [])

    if not trades:
        result = {"buy_ratio": 0.5, "retail_pct": 0, "trade_count": 0,
                  "sentiment": "NO DATA", "summary": f"No trade tape available for {sym}"}
        _cache_set(key, result)
        return result

    buy_vol = sell_vol = 0.0
    retail_prints = 0
    last_price = None
    for t in trades:
        price = t.get("p", 0) or 0
        size  = t.get("s", 0) or 0
        if last_price is not None and price > last_price:
            buy_vol += size
        elif last_price is not None and price < last_price:
            sell_vol += size
        else:
            buy_vol  += size / 2
            sell_vol += size / 2
        if 0 < size <= 100:
            retail_prints += 1
        last_price = price

    total     = buy_vol + sell_vol
    buy_ratio = round(buy_vol / total, 3) if total else 0.5
    retail_pct = round(retail_prints / len(trades) * 100, 1)

    if buy_ratio >= 0.62:   sentiment = "STRONG BUY PRESSURE"
    elif buy_ratio >= 0.54: sentiment = "BUY PRESSURE"
    elif buy_ratio <= 0.38: sentiment = "STRONG SELL PRESSURE"
    elif buy_ratio <= 0.46: sentiment = "SELL PRESSURE"
    else:                   sentiment = "BALANCED"

    result = {
        "buy_ratio": buy_ratio, "retail_pct": retail_pct,
        "trade_count": len(trades), "sentiment": sentiment,
        "summary": (
            f"{sym} Tape: {sentiment} | buy-side {buy_ratio:.0%} of volume | "
            f"{retail_pct:.0f}% odd-lot (likely retail) prints of {len(trades)} recent trades"
        ),
    }
    _cache_set(key, result)
    return result


def stocktwits_sentiment(symbol: str) -> dict:
    """
    StockTwits real-time crowd sentiment — no API key needed.
    Returns dict: {bull, bear, total, score, sentiment, watchlist_count, summary}
    """
    sym = symbol.upper().strip()
    key = f"stocktwits_{sym}"
    cached = _cache_get(key, ttl_minutes=5)
    if cached:
        return cached

    r = _get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json")
    if not r:
        return {"bull": 0, "bear": 0, "total": 0, "score": 0.5,
                "sentiment": "UNAVAILABLE", "watchlist_count": 0,
                "summary": f"StockTwits unavailable for {sym}"}
    try:
        data     = r.json()
        messages = data.get("messages", [])
        bull = sum(1 for m in messages
                   if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish")
        bear = sum(1 for m in messages
                   if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish")
        total    = len(messages)
        wl_count = (data.get("symbol") or {}).get("watchlist_count", 0)

        score = (bull / (bull + bear)) if (bull + bear) > 0 else 0.5

        if score >= 0.70:   sentiment = "VERY BULLISH"
        elif score >= 0.60: sentiment = "BULLISH"
        elif score <= 0.30: sentiment = "VERY BEARISH"
        elif score <= 0.40: sentiment = "BEARISH"
        else:               sentiment = "NEUTRAL"

        result = {
            "bull": bull, "bear": bear, "total": total,
            "score": round(score, 3), "sentiment": sentiment,
            "watchlist_count": wl_count,
            "summary": (
                f"{sym} StockTwits: {sentiment} | "
                f"{bull} bull vs {bear} bear of {total} msgs | "
                f"{wl_count:,} watching"
            ),
        }
        _cache_set(key, result)
        return result
    except Exception as e:
        return {"bull": 0, "bear": 0, "total": 0, "score": 0.5,
                "sentiment": "ERROR", "watchlist_count": 0,
                "summary": f"StockTwits parse error: {e}"}


def stocktwits_trending() -> str:
    """Pull the top trending tickers from StockTwits right now."""
    r = _get("https://api.stocktwits.com/api/2/trending/symbols.json")
    lines = ["StockTwits — Trending NOW", ""]
    if r:
        try:
            symbols = r.json().get("symbols", [])[:15]
            for i, s in enumerate(symbols, 1):
                sym  = s.get("symbol", "")
                name = s.get("title", "")[:35]
                wl   = s.get("watchlist_count", 0)
                lines.append(f"  #{i:>2}  {sym:<8}  {wl:>8,} watching  {name}")
        except Exception:
            lines.append("  (Parse error)")
    else:
        lines.append("  StockTwits trending unavailable")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# REDDIT
# ══════════════════════════════════════════════════════════════════════════════

_BULL_WORDS = ["bull", "long", "buy", "calls", "moon", "squeeze", "rocket",
               "green", "gains", "pump", "yolo", "bullish", "calls", "ath"]
_BEAR_WORDS = ["bear", "short", "sell", "puts", "crash", "dump", "drop",
               "red", "loss", "tank", "puts", "baghold", "bearish"]
_EXCLUDE    = {"THE","AND","FOR","BUY","SELL","GET","SET","RUN","SHOW","FROM",
               "WITH","THIS","THAT","AUTO","HUNT","JUST","LIKE","ARE","NOT",
               "WERE","BEEN","HAVE","WILL","INTO","OVER","SUCH","YOUR","THEIR"}


def reddit_sentiment(symbol: str, subreddits: list = None) -> dict:
    """
    Reddit WSB + stocks + investing sentiment via public JSON API (no PRAW).
    Returns dict: {posts, score, bull_posts, bear_posts, top_titles, sentiment, summary}
    """
    sym = symbol.upper().strip()
    key = f"reddit_{sym}"
    cached = _cache_get(key, ttl_minutes=15)
    if cached:
        return cached

    if subreddits is None:
        subreddits = ["wallstreetbets", "stocks", "investing", "StockMarket"]

    all_posts = []
    hdrs = {"User-Agent": "JARVIS:1.0 (financial research)"}

    for sub in subreddits[:3]:
        url = (
            f"https://www.reddit.com/r/{sub}/search.json"
            f"?q={sym}&sort=new&limit=20&restrict_sr=1&t=day"
        )
        r = _get(url, headers=hdrs)
        if not r:
            continue
        try:
            posts = r.json().get("data", {}).get("children", [])
            for p in posts:
                pd    = p.get("data", {})
                title = pd.get("title", "")
                if sym in title.upper():
                    all_posts.append({
                        "title": title[:120],
                        "score": pd.get("score", 0),
                        "sub":   sub,
                    })
        except Exception:
            pass
        time.sleep(0.25)

    if not all_posts:
        result = {"posts": 0, "score": 0.5, "bull_posts": 0, "bear_posts": 0,
                  "top_titles": [], "sentiment": "NO DATA",
                  "summary": f"No Reddit mentions of {sym} in last 24h"}
        _cache_set(key, result)
        return result

    bull_count = bear_count = 0
    for post in all_posts:
        text  = post["title"].lower()
        b_hit = sum(1 for w in _BULL_WORDS if w in text)
        r_hit = sum(1 for w in _BEAR_WORDS if w in text)
        if b_hit > r_hit:
            bull_count += 1
        elif r_hit > b_hit:
            bear_count += 1

    scored = bull_count + bear_count
    score  = (bull_count / scored) if scored > 0 else 0.5

    top = sorted(all_posts, key=lambda x: x["score"], reverse=True)[:3]

    if score >= 0.65:   sentiment = "BULLISH"
    elif score <= 0.35: sentiment = "BEARISH"
    else:               sentiment = "NEUTRAL"

    result = {
        "posts": len(all_posts), "score": round(score, 3),
        "bull_posts": bull_count, "bear_posts": bear_count,
        "top_titles": [p["title"] for p in top],
        "sentiment": sentiment,
        "summary": (
            f"Reddit {sym}: {sentiment} | {len(all_posts)} posts today | "
            f"bull:{bull_count} bear:{bear_count}"
        ),
    }
    _cache_set(key, result)
    return result


def reddit_wsb_hot() -> str:
    """What is r/wallstreetbets talking about right now."""
    r = _get("https://www.reddit.com/r/wallstreetbets/hot.json?limit=10",
             headers={"User-Agent": "JARVIS:1.0"})
    lines = ["Reddit r/wallstreetbets — Hot Posts RIGHT NOW", ""]
    if r:
        try:
            posts = r.json().get("data", {}).get("children", [])
            for p in posts[:8]:
                pd    = p.get("data", {})
                title = pd.get("title", "")[:80]
                upv   = pd.get("score", 0)
                cmts  = pd.get("num_comments", 0)
                lines.append(f"  [{upv:>5}↑ {cmts:>4}💬] {title}")
        except Exception:
            lines.append("  (Parse error)")
    else:
        lines.append("  Reddit unavailable")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# FINVIZ
# ══════════════════════════════════════════════════════════════════════════════

def finviz_headlines(symbol: str) -> list[str]:
    """Scrape Finviz news headlines for a symbol."""
    sym = symbol.upper().strip()
    key = f"finviz_{sym}"
    cached = _cache_get(key, ttl_minutes=10)
    if cached:
        return cached.get("headlines", [])

    r = _get(f"https://finviz.com/quote.ashx?t={sym}",
             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    if not r:
        return []

    html = r.text
    # Finviz news-link-left anchors contain headlines
    matches = re.findall(
        r'class="news-link-left"[^>]*>\s*<a[^>]*>([^<]{10,120})</a>', html
    )
    if not matches:
        # Fallback pattern
        matches = re.findall(
            r'<td[^>]*class="[^"]*news[^"]*"[^>]*>.*?<a[^>]*>([^<]{15,100})</a>',
            html, re.DOTALL
        )

    headlines = [h.strip() for h in matches[:10] if h.strip()]
    _cache_set(key, {"headlines": headlines})
    return headlines


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED SOCIAL SIGNAL (for conviction scoring)
# ══════════════════════════════════════════════════════════════════════════════

def social_signal(symbol: str) -> tuple[int, str]:
    """
    Combined social + retail order-flow sentiment score used in conviction_score().
    Returns: (points: 0-15, detail_str)

    Allocation:
      StockTwits sentiment ratio      0-6 pts
      Reddit sentiment + mentions     0-5 pts
      Retail trade-tape buy pressure  0-4 pts
    """
    sym = symbol.upper().strip()

    st = stocktwits_sentiment(sym)
    rd = reddit_sentiment(sym)
    tf = retail_trade_flow(sym)

    # ── StockTwits score 0-6 ──
    st_score = st.get("score", 0.5)
    st_total = st.get("total", 0)
    if st_total == 0:
        st_pts = 3  # neutral when no data
    elif st_score >= 0.70:
        st_pts = 6
    elif st_score >= 0.60:
        st_pts = 5
    elif st_score >= 0.50:
        st_pts = 3
    elif st_score >= 0.40:
        st_pts = 1
    else:
        st_pts = 0

    # Boost for high watchlist popularity
    if st.get("watchlist_count", 0) > 50_000:
        st_pts = min(6, st_pts + 1)

    # ── Reddit score 0-5 ──
    rd_posts = rd.get("posts", 0)
    rd_score = rd.get("score", 0.5)
    if rd_posts == 0:
        rd_pts = 2  # neutral when no data
    elif rd_score >= 0.65:
        rd_pts = 5
    elif rd_score >= 0.55:
        rd_pts = 4
    elif rd_score >= 0.45:
        rd_pts = 2
    else:
        rd_pts = 0
    if rd_posts >= 10:
        rd_pts = min(5, rd_pts + 1)  # high engagement boost

    # ── Retail trade-tape buy pressure 0-4 ──
    buy_ratio = tf.get("buy_ratio", 0.5)
    tf_count  = tf.get("trade_count", 0)
    if tf_count == 0:
        tf_pts = 2  # neutral when no data
    elif buy_ratio >= 0.62:
        tf_pts = 4
    elif buy_ratio >= 0.54:
        tf_pts = 3
    elif buy_ratio >= 0.46:
        tf_pts = 2
    elif buy_ratio >= 0.38:
        tf_pts = 1
    else:
        tf_pts = 0

    total = min(15, st_pts + rd_pts + tf_pts)

    detail = (
        f"ST:{st.get('sentiment','?')}({st.get('bull',0)}bull/"
        f"{st.get('bear',0)}bear) | "
        f"Reddit:{rd.get('sentiment','?')}({rd_posts}posts) | "
        f"Tape:{tf.get('sentiment','?')}({tf.get('retail_pct',0):.0f}%retail)"
    )
    return total, detail


# ══════════════════════════════════════════════════════════════════════════════
# FULL SOCIAL INTELLIGENCE REPORT
# ══════════════════════════════════════════════════════════════════════════════

def social_report(symbol: str) -> str:
    """Full social intelligence report for a symbol."""
    sym = symbol.upper().strip()

    st = stocktwits_sentiment(sym)
    rd = reddit_sentiment(sym)
    tf = retail_trade_flow(sym)
    fv = finviz_headlines(sym)
    pts, _ = social_signal(sym)

    lines = [
        f"Social Intelligence Report: {sym}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "─" * 55,
        "",
        "  STOCKTWITS (Real-Time Crowd):",
        f"    Sentiment:   {st.get('sentiment', 'UNKNOWN')}",
        f"    Bull/Bear:   {st.get('bull', 0)} bullish vs {st.get('bear', 0)} bearish ({st.get('total', 0)} msgs)",
        f"    Watching:    {st.get('watchlist_count', 0):,} users on StockTwits",
        "",
        "  REDDIT (WSB + stocks + investing + StockMarket):",
        f"    Sentiment:   {rd.get('sentiment', 'UNKNOWN')}",
        f"    Posts today: {rd.get('posts', 0)} mentions",
        f"    Bull/Bear:   {rd.get('bull_posts', 0)} bullish vs {rd.get('bear_posts', 0)} bearish posts",
    ]
    for t in rd.get("top_titles", []):
        lines.append(f"    ‣ \"{t[:78]}\"")

    lines += [
        "",
        "  RETAIL ORDER FLOW (public trade tape, tick-rule classified):",
        f"    Sentiment:   {tf.get('sentiment', 'UNKNOWN')}",
        f"    Buy-side:    {tf.get('buy_ratio', 0.5):.0%} of recent volume",
        f"    Odd-lot %:   {tf.get('retail_pct', 0):.0f}% of {tf.get('trade_count', 0)} recent prints (likely retail-sized)",
    ]

    lines += ["", "  FINVIZ HEADLINES:"]
    if fv:
        for h in fv[:5]:
            lines.append(f"    • {h[:80]}")
    else:
        lines.append("    (No headlines scraped)")

    lines += [
        "",
        f"  COMBINED SOCIAL SCORE: {pts}/15 pts",
        "",
        "─" * 55,
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GEOPOLITICAL INTELLIGENCE (multi-source)
# ══════════════════════════════════════════════════════════════════════════════

def geopolitical_deep_brief() -> str:
    """
    Pull from 5 news RSS feeds, run through local LLM for trade ideas.
    Works fully offline (LLM) + public RSS feeds.
    """
    sources = [
        ("Google Markets",  "https://news.google.com/rss/search?q=markets+economy+stocks&hl=en-US&gl=US"),
        ("Google Geo",      "https://news.google.com/rss/search?q=geopolitical+risk+war+sanctions+trade&hl=en-US"),
        ("Google Fed",      "https://news.google.com/rss/search?q=Federal+Reserve+interest+rates+inflation&hl=en-US"),
        ("Google Defense",  "https://news.google.com/rss/search?q=defense+spending+military+NATO&hl=en-US"),
        ("Google Tech",     "https://news.google.com/rss/search?q=AI+semiconductor+chip+tech+earnings&hl=en-US"),
    ]

    all_headlines = []
    for src_name, url in sources:
        r = _get(url)
        if r:
            titles = re.findall(r"<title>(.*?)</title>", r.text, re.DOTALL)
            for t in titles[1:4]:  # skip feed title, take up to 3
                clean = re.sub(r"<[^>]+>", "", t).strip()
                if clean and len(clean) > 10:
                    all_headlines.append(f"[{src_name}] {clean}")

    if not all_headlines:
        return "Geopolitical news feeds unavailable. Check internet connection."

    headline_block = "\n".join(all_headlines[:15])

    prompt = f"""Analyze these market-moving news headlines and provide a structured intelligence brief:

{headline_block}

Provide EXACTLY this format:
TOP RISKS:
1. [specific risk + affected sectors]
2. [specific risk + affected sectors]
3. [specific risk + affected sectors]

OPPORTUNITIES:
1. [sector/theme + why + ETF ticker]
2. [sector/theme + why + ETF ticker]

BUY SECTORS: [2-3 sector ETFs: XLE, XLK, XLF, XLD, IWM, etc. with one-line reason each]
AVOID: [1-2 sectors at risk with reason]

KEY CATALYST TO WATCH: [single most important item for traders this week]"""

    ai_brief = _ai(prompt, timeout=50)

    lines = [
        "═══ GEOPOLITICAL INTELLIGENCE BRIEF ═══",
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}",
        f"Sources: {len(sources)} RSS feeds | {len(all_headlines)} headlines analyzed",
        "",
        "── RAW HEADLINES ──────────────────────────────────────",
    ]
    for h in all_headlines[:12]:
        lines.append(f"  • {h[:105]}")

    lines += [
        "",
        "── AI ANALYSIS (Local LLM — Ollama) ──────────────────",
        ai_brief,
        "",
        "━" * 55,
    ]
    return "\n".join(lines)


def trending_social_now() -> str:
    """Trending tickers across StockTwits + Reddit hot posts."""
    lines = [
        "Social Media — What's HOT Right Now",
        f"Updated: {datetime.now().strftime('%H:%M')}",
        "",
    ]
    lines.append(stocktwits_trending())
    lines += ["", ""]
    lines.append(reddit_wsb_hot())
    return "\n".join(lines)
