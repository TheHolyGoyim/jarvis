"""
intel.py — JARVIS Online Intelligence Engine
The skills of a superpowered human whose only expression is online.

No API keys required for most tools — uses free public endpoints.
Optional: HIBP_API_KEY in .env for Have I Been Pwned full breach data.
"""

import os, re, json, time, hashlib, math, urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

_DATA_DIR = Path.home() / "Documents" / "JARVIS" / "intel"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_MONITORS_FILE = _DATA_DIR / "web_monitors.json"
_PRICES_FILE   = _DATA_DIR / "price_watches.json"

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

def _get(url, params=None, headers=None, timeout=10):
    import requests
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r

def _ai(prompt, system="You are a sharp analyst. Be direct and specific."):
    try:
        import requests as _r
        resp = _r.post("http://localhost:11434/api/generate",
                       json={"model":_OLLAMA_MODEL,"prompt":prompt,"system":system,"stream":False},
                       timeout=25)
        if resp.ok:
            return resp.json().get("response","").strip()
    except Exception:
        pass
    return "(AI unavailable)"

def _load(f, default=None):
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}

def _save(f, data):
    try:
        f.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# WEB RESEARCH — bridges Jarvis's own knowledge gaps
# ══════════════════════════════════════════════════════════════════════════════

def web_research(query: str) -> str:
    """
    Actually research a topic using free, keyless public sources (DuckDuckGo's
    Instant Answer API + Wikipedia search) and return real content to reason over.

    Unlike web_search() — which just opens a browser tab for the human — this
    fetches and reads results server-side, so Jarvis can use it to close its own
    knowledge gaps (anything past training data, obscure facts, definitions,
    entities) instead of guessing or refusing. Best for factual/definitional
    lookups; weaker for subjective "best of" or highly current queries — pair
    with news_fetch() for anything time-sensitive.
    """
    q = query.strip()
    if not q:
        return "No research query given."

    lines = [f"Web Research: {q}", ""]
    found = False

    # 1. DuckDuckGo Instant Answer — fast, authoritative when it matches
    try:
        r = _get("https://api.duckduckgo.com/", params={
            "q": q, "format": "json", "no_html": 1, "skip_disambig": 1
        })
        d = r.json()
        abstract = (d.get("AbstractText") or "").strip()
        if abstract:
            found = True
            heading = d.get("Heading") or q
            src = d.get("AbstractURL") or ""
            lines += [f"[{heading}]", abstract]
            if src:
                lines.append(f"Source: {src}")
            lines.append("")
        elif d.get("RelatedTopics"):
            rel = [t.get("Text", "") for t in d["RelatedTopics"]
                   if isinstance(t, dict) and t.get("Text")][:4]
            if rel:
                found = True
                lines.append("Related:")
                lines += [f"  • {t}" for t in rel]
                lines.append("")
    except Exception:
        pass

    # 2. Wikipedia search + summary — broader factual/entity fallback
    try:
        sr = _get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": q,
            "format": "json", "srlimit": 3,
        })
        results = sr.json().get("query", {}).get("search", [])
        if results:
            top_title = results[0]["title"]
            safe_title = urllib.parse.quote(top_title.replace(" ", "_"))
            try:
                sumr = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}")
                extract = (sumr.json().get("extract") or "").strip()
            except Exception:
                extract = ""
            if extract:
                found = True
                lines += [f"[Wikipedia: {top_title}]", extract,
                          f"Source: https://en.wikipedia.org/wiki/{safe_title}", ""]
            other = [x["title"] for x in results[1:3]]
            if other:
                lines.append(f"Also see: {', '.join(other)}")
    except Exception:
        pass

    if not found:
        lines.append(
            "No direct match from free keyless sources for this query. "
            "Try news_fetch() if it's current-events related, or narrow the query."
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

def fear_greed() -> str:
    """Crypto + Stock Market Fear & Greed Index — real-time sentiment (0=max fear, 100=max greed)."""
    lines = ["Fear & Greed Index", ""]

    # Crypto Fear & Greed (Alternative.me — always free, no auth)
    try:
        r    = _get("https://api.alternative.me/fng/?limit=8&format=json")
        data = r.json().get("data", [])
        if data:
            now   = data[0]
            score = int(now["value"])
            label = now["value_classification"].replace("_"," ").title()
            bar   = "█" * (score // 5) + "░" * (20 - score // 5)
            yesterday = int(data[1]["value"]) if len(data) > 1 else None
            week_ago  = int(data[7]["value"]) if len(data) > 7 else None
            lines += [
                f"  Crypto Sentiment:  {score}/100  [{bar}]",
                f"  Rating:            {label}",
            ]
            if yesterday is not None:
                lines.append(f"  Yesterday:         {yesterday}/100")
            if week_ago is not None:
                lines.append(f"  1 Week Ago:        {week_ago}/100")
    except Exception as e:
        lines.append(f"  Crypto index unavailable: {e}")

    # Market signal interpretation
    score_val = score if 'score' in dir() else 50
    lines.append("")
    if score_val < 25:
        lines.append("  Signal: EXTREME FEAR — historically strong buy zone for contrarians.")
    elif score_val < 45:
        lines.append("  Signal: FEAR — market may be approaching oversold conditions.")
    elif score_val < 55:
        lines.append("  Signal: NEUTRAL — no strong directional edge.")
    elif score_val < 75:
        lines.append("  Signal: GREED — consider taking partial profits, watch for reversals.")
    else:
        lines.append("  Signal: EXTREME GREED — historically a warning sign. Exercise caution.")

    return "\n".join(lines)


def insider_trades(symbol: str, days: int = 30) -> str:
    """
    Recent insider buying/selling for any stock via SEC EDGAR Form 4.
    Insiders know their own company — this is legal, public, and powerful.
    """
    symbol = symbol.upper().strip()
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url   = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q":         f'"{symbol}"',
            "forms":     "4",
            "dateRange": "custom",
            "startdt":   since,
            "hits.hits._source": "period_of_report,entity_name,file_date,form_type",
        }
        r    = _get(url, params=params)
        hits = r.json().get("hits",{}).get("hits",[])

        if not hits:
            return f"No insider filings found for {symbol} in the last {days} days."

        lines = [f"Insider Trades: {symbol} (last {days} days from SEC EDGAR)", ""]
        seen  = set()
        for h in hits[:15]:
            src  = h.get("_source", {})
            name = src.get("entity_name","Unknown")
            date = src.get("file_date","?")[:10]
            key  = f"{name}-{date}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"  {date}  {name}")

        lines += [
            "",
            f"  {len(seen)} insider filing(s) found.",
            "  View details: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&company={symbol}&type=4&dateb=&owner=include&count=20",
        ]

        summary = _ai(
            f"These SEC Form 4 insider filings were found for {symbol}:\n" +
            "\n".join(lines) +
            "\n\nIn 2 sentences: is the pattern of insider activity bullish, bearish, or neutral? "
            "What should an investor infer?",
            system="You are a securities analyst expert in insider trading signals."
        )
        lines += ["", "Analysis:", summary]
        return "\n".join(lines)
    except Exception as e:
        return f"SEC EDGAR error: {e}"


def sec_filings(company: str, form_type: str = "") -> str:
    """
    Search SEC EDGAR for any company's recent filings.
    form_type examples: 10-K (annual), 10-Q (quarterly), 8-K (events), 4 (insider),
                        S-1 (IPO registration), DEF 14A (proxy).
    Leave form_type blank to get all recent filings.
    """
    try:
        params = {
            "q":       f'"{company}"',
            "dateRange": "custom",
            "startdt": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
        }
        if form_type:
            params["forms"] = form_type.upper()

        r    = _get("https://efts.sec.gov/LATEST/search-index", params=params)
        hits = r.json().get("hits",{}).get("hits",[])

        if not hits:
            return f"No SEC filings found for '{company}'" + (f" (form: {form_type})" if form_type else "") + " in the last 90 days."

        lines = [f"SEC Filings: {company}" + (f" [{form_type}]" if form_type else ""), ""]
        for h in hits[:10]:
            src  = h.get("_source", {})
            date = src.get("file_date","?")[:10]
            form = src.get("form_type","?")
            name = src.get("entity_name","?")
            desc = src.get("file_description","") or ""
            lines.append(f"  {date}  {form:<10} {name}")
            if desc:
                lines.append(f"             {desc[:60]}")

        lines.append(f"\n  Full search: https://efts.sec.gov/LATEST/search-index?q={company.replace(' ','%20')}")
        return "\n".join(lines)
    except Exception as e:
        return f"SEC EDGAR search error: {e}"


def options_chain(symbol: str) -> str:
    """
    Options chain snapshot — top calls and puts, implied volatility, open interest.
    Useful for spotting unusual bets and gauging market expectations.
    """
    symbol = symbol.upper().strip()
    try:
        r    = _get(f"https://query1.finance.yahoo.com/v7/finance/options/{symbol}")
        data = r.json()["optionChain"]["result"][0]

        price  = data["quote"]["regularMarketPrice"]
        exp_ts = data["expirationDates"][0]
        exp    = datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d")
        calls  = sorted(data["options"][0]["calls"],
                        key=lambda x: x.get("openInterest",0), reverse=True)[:5]
        puts   = sorted(data["options"][0]["puts"],
                        key=lambda x: x.get("openInterest",0), reverse=True)[:5]

        def fmt_contract(c):
            strike = c.get("strike",0)
            oi     = c.get("openInterest",0)
            iv     = c.get("impliedVolatility",0) * 100
            last   = c.get("lastPrice",0)
            vol    = c.get("volume",0) or 0
            arrow  = "▲" if strike > price else "▼"
            return f"    ${strike:>7.2f} {arrow}  last=${last:.2f}  OI={oi:,}  vol={vol:,}  IV={iv:.0f}%"

        lines = [
            f"Options Chain: {symbol}  (spot=${price:.2f}  exp={exp})",
            "",
            "  Top Calls by Open Interest:",
        ]
        for c in calls:
            lines.append(fmt_contract(c))
        lines += ["", "  Top Puts by Open Interest:"]
        for p in puts:
            lines.append(fmt_contract(p))

        call_oi = sum(c.get("openInterest",0) for c in data["options"][0]["calls"])
        put_oi  = sum(c.get("openInterest",0) for c in data["options"][0]["puts"])
        ratio   = put_oi / call_oi if call_oi else 0
        bias    = "BEARISH bias" if ratio > 1.2 else "BULLISH bias" if ratio < 0.8 else "NEUTRAL"
        lines  += [
            "",
            f"  Put/Call Ratio: {ratio:.2f}  ({bias})",
            f"  Total Call OI:  {call_oi:,}",
            f"  Total Put OI:   {put_oi:,}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Options chain error for {symbol}: {e}"


def analyst_ratings(symbol: str) -> str:
    """Wall Street analyst consensus — buy/hold/sell breakdown and price targets."""
    symbol = symbol.upper().strip()
    try:
        import yfinance as yf
        tk   = yf.Ticker(symbol)
        info = tk.info

        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low  = info.get("targetLowPrice")
        current     = info.get("currentPrice") or info.get("regularMarketPrice")
        recommend   = info.get("recommendationMean")  # 1=strong buy, 5=strong sell
        rec_key     = info.get("recommendationKey","").replace("_"," ").upper()
        num_analysts= info.get("numberOfAnalystOpinions",0)

        if not target_mean:
            return f"No analyst data available for {symbol}."

        upside = ((target_mean - current) / current * 100) if current else 0
        arrow  = "▲" if upside > 0 else "▼"

        stars = "★" * round(5 - (recommend or 3)) + "☆" * (5 - round(5 - (recommend or 3)))

        lines = [
            f"Analyst Ratings: {symbol}",
            "",
            f"  Consensus:    {rec_key}  {stars}",
            f"  Score:        {recommend:.1f}/5.0  (1=Strong Buy, 5=Strong Sell)" if recommend else "",
            f"  Analysts:     {num_analysts} covering",
            f"  Current:      ${current:,.2f}" if current else "",
            f"  Target (avg): ${target_mean:,.2f}  ({arrow} {upside:+.1f}% upside)",
            f"  Target range: ${target_low:,.2f} — ${target_high:,.2f}",
        ]
        return "\n".join(l for l in lines if l)
    except Exception as e:
        return f"Analyst ratings error: {e}"


def short_interest(symbol: str) -> str:
    """Short interest data — what % of float is being bet against this stock."""
    symbol = symbol.upper().strip()
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        short_pct  = info.get("shortPercentOfFloat", 0) * 100
        short_rat  = info.get("shortRatio", 0)       # days to cover
        shares_sh  = info.get("sharesShort", 0)
        float_sh   = info.get("floatShares", 0)
        prev_short = info.get("sharesShortPriorMonth", 0)
        chg        = ((shares_sh - prev_short) / prev_short * 100) if prev_short else 0

        squeeze_risk = (
            "HIGH squeeze risk" if short_pct > 20 and short_rat > 5 else
            "MODERATE squeeze risk" if short_pct > 10 else
            "Low squeeze risk"
        )

        lines = [
            f"Short Interest: {symbol}",
            "",
            f"  Short % of Float:  {short_pct:.1f}%",
            f"  Days to Cover:     {short_rat:.1f}  (higher = harder to exit)",
            f"  Shares Short:      {shares_sh:,}",
            f"  vs Prior Month:    {chg:+.1f}%",
            "",
            f"  Squeeze Risk: {squeeze_risk}",
        ]
        if short_pct > 10:
            lines.append("  Note: High short interest can amplify moves in both directions.")
        return "\n".join(lines)
    except Exception as e:
        return f"Short interest error: {e}"


def economic_events(days_ahead: int = 14) -> str:
    """
    Upcoming high-impact economic events — Fed meetings, CPI, jobs report, GDP.
    Pulls from FRED and known fixed schedule.
    """
    try:
        # Fetch economic calendar from investing.com RSS
        r = _get("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
                 headers={"X-Requested-With": "XMLHttpRequest",
                          "Referer": "https://www.investing.com/economic-calendar/"})
        # Fallback to known events if blocked
    except Exception:
        pass

    # Static high-value calendar (Fed schedule is published annually)
    now  = datetime.now()
    year = now.year
    lines = [
        f"Upcoming Market-Moving Events (next {days_ahead} days)",
        "",
        "  Pulling from known Federal Reserve schedule + news...",
        "",
    ]
    # Fetch FRED calendar via news
    try:
        from tools.market import news_fetch
        news = news_fetch("Federal Reserve FOMC CPI jobs report GDP " + str(year), num=8)
        lines.append(news)
    except Exception:
        lines.append("  Install requests for live news: pip install requests")

    lines += [
        "",
        "  Key recurring dates to watch:",
        "  • FOMC meetings: 8x per year (Fed funds rate decisions)",
        "  • CPI release:   ~13th of each month",
        "  • Jobs report:   First Friday of each month",
        "  • GDP:           Quarterly (end of Jan/Apr/Jul/Oct)",
        "  • PCE (inflation): Last Friday of most months",
        "",
        "  Full calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# OSINT & RECON
# ══════════════════════════════════════════════════════════════════════════════

def domain_intel(domain: str) -> str:
    """
    Full domain recon — registration info, IP, hosting, server, SSL, DNS records.
    The kind of lookup a security analyst does on any domain.
    """
    domain = domain.strip().lower().replace("https://","").replace("http://","").split("/")[0]
    lines  = [f"Domain Intelligence: {domain}", ""]

    # WHOIS
    try:
        r    = _get(f"https://www.whoisxmlapi.com/whoisserver/WhoisService?apiKey=at_free&domainName={domain}&outputFormat=JSON")
        data = r.json().get("WhoisRecord",{})
        reg  = data.get("registrarName","?")
        created = data.get("createdDate","?")[:10] if data.get("createdDate") else "?"
        expires = data.get("expiresDate","?")[:10] if data.get("expiresDate") else "?"
        registrant = data.get("registrant",{}).get("organization","Private/Redacted")
        lines += [
            "  Registration:",
            f"    Registrar:  {reg}",
            f"    Created:    {created}",
            f"    Expires:    {expires}",
            f"    Registrant: {registrant}",
            "",
        ]
    except Exception:
        # Fallback: rdap
        try:
            tld  = domain.split(".")[-1]
            r    = _get(f"https://rdap.org/domain/{domain}")
            data = r.json()
            events = {e["eventAction"]: e["eventDate"][:10] for e in data.get("events",[])}
            lines += [
                "  Registration (RDAP):",
                f"    Created: {events.get('registration','?')}",
                f"    Updated: {events.get('last changed','?')}",
                f"    Expires: {events.get('expiration','?')}",
                "",
            ]
        except Exception:
            lines.append("  Registration: lookup failed\n")

    # IP / hosting
    try:
        import socket
        ip   = socket.gethostbyname(domain)
        r    = _get(f"https://ipwho.is/{ip}")
        geo  = r.json()
        isp  = geo.get("connection",{}).get("org","?")
        city = geo.get("city","?")
        ctry = geo.get("country","?")
        asn  = geo.get("connection",{}).get("asn","?")
        lines += [
            "  IP / Hosting:",
            f"    IP:      {ip}",
            f"    ISP/AS:  {isp}  (ASN {asn})",
            f"    Location: {city}, {ctry}",
            "",
        ]
    except Exception:
        lines.append("  IP lookup failed\n")

    # HTTP headers / server fingerprint
    try:
        import requests
        resp    = requests.head(f"https://{domain}", timeout=6, headers={"User-Agent": _UA}, allow_redirects=True)
        server  = resp.headers.get("Server","?")
        powered = resp.headers.get("X-Powered-By","?")
        cdn     = resp.headers.get("CF-Ray","") and "Cloudflare" or resp.headers.get("x-amz-cf-id","") and "CloudFront" or "?"
        hsts    = bool(resp.headers.get("Strict-Transport-Security"))
        lines += [
            "  Server Fingerprint:",
            f"    Server:    {server}",
            f"    Powered by:{powered}",
            f"    CDN:       {cdn}",
            f"    HSTS:      {'yes' if hsts else 'no'}",
            "",
        ]
    except Exception:
        lines.append("  Server fingerprint: failed\n")

    lines.append(f"  Full WHOIS: https://who.is/whois/{domain}")
    return "\n".join(lines)


def site_status(url: str) -> str:
    """Check if a website is up, response time, and basic server info."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        import requests, time as _t
        start = _t.time()
        r     = requests.get(url, timeout=10, headers={"User-Agent": _UA}, allow_redirects=True)
        ms    = int((_t.time() - start) * 1000)
        bar   = "🟢" if ms < 500 else "🟡" if ms < 1500 else "🔴"
        return "\n".join([
            f"Site Status: {url}",
            "",
            f"  Status:    {r.status_code} {'OK' if r.ok else 'ERROR'}  {bar}",
            f"  Response:  {ms}ms",
            f"  Final URL: {r.url}",
            f"  Server:    {r.headers.get('Server','?')}",
            f"  Size:      {len(r.content):,} bytes",
        ])
    except Exception as e:
        return f"Site unreachable: {url}\nError: {e}"


def pwned_check(email: str) -> str:
    """
    Check if an email address appears in known data breaches.
    Uses Have I Been Pwned API (free breach list, no key required for basic check).
    """
    email = email.strip().lower()
    try:
        api_key = os.getenv("HIBP_API_KEY","")
        headers = {"User-Agent": "JARVIS-Butler", "hibp-api-key": api_key} if api_key else {"User-Agent": "JARVIS-Butler"}
        r = _get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}?truncateResponse=false",
                 headers=headers, timeout=10)
        breaches = r.json()
        lines    = [f"Breach Check: {email}", "", f"  EXPOSED in {len(breaches)} breach(es):", ""]
        for b in sorted(breaches, key=lambda x: x.get("BreachDate",""), reverse=True)[:10]:
            name  = b.get("Name","?")
            date  = b.get("BreachDate","?")
            count = b.get("PwnCount",0)
            data  = ", ".join(b.get("DataClasses",[])[:4])
            lines.append(f"  • {name} ({date}) — {count:,} records — {data}")
        lines += ["", "  Action: Change passwords where you reuse credentials from these breaches."]
        return "\n".join(lines)
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e):
            return f"Breach Check: {email}\n\n  CLEAN — not found in any known breach. (Source: HaveIBeenPwned)"
        if "401" in str(e) or "Unauthorized" in str(e):
            return (f"HIBP requires an API key for breach lookups.\n"
                    f"Get a free key at https://haveibeenpwned.com/API/Key\n"
                    f"Add to .env: HIBP_API_KEY=your_key\n\n"
                    f"Check manually: https://haveibeenpwned.com/account/{email}")
        return f"Breach check error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def github_trending(language: str = "", since: str = "daily") -> str:
    """
    GitHub trending repositories — what developers are building and watching right now.
    language: python, javascript, rust, go, etc. (blank = all)
    since: daily, weekly, monthly
    """
    try:
        # GitHub Search API — repos created recently with most stars
        days_map = {"daily": 1, "weekly": 7, "monthly": 30}
        days     = days_map.get(since, 1)
        since_dt = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        q        = f"created:>{since_dt}" + (f" language:{language}" if language else "")
        token    = os.getenv("GITHUB_TOKEN", "")
        hdrs     = {"Authorization": f"token {token}"} if token else {}
        r        = _get("https://api.github.com/search/repositories",
                        params={"q": q, "sort": "stars", "order": "desc", "per_page": 10},
                        headers=hdrs)
        items = r.json().get("items", [])

        period = {"daily":"Today","weekly":"This Week","monthly":"This Month"}.get(since, since.title())
        lines  = [f"GitHub Trending — {period}" + (f" [{language}]" if language else ""), ""]
        for i, repo in enumerate(items[:10]):
            name  = repo["full_name"]
            desc  = (repo.get("description") or "")[:85]
            stars = repo["stargazers_count"]
            lang  = repo.get("language") or ""
            lines.append(f"  {i+1:2}. ⭐ {stars:>6}   {name}" + (f"  [{lang}]" if lang else ""))
            if desc:
                lines.append(f"           {desc}")
        lines.append(f"\n  Full trending: https://github.com/trending/{language}?since={since}")
        return "\n".join(lines)
    except Exception as e:
        return f"GitHub trending error: {e}\n  Browse: https://github.com/trending"


def wikipedia(topic: str) -> str:
    """
    Wikipedia summary for any topic — the world's knowledge base, instantly.
    Returns the introduction + key facts.
    """
    try:
        r    = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic.replace(' ','_')}")
        data = r.json()
        if data.get("type") == "disambiguation":
            options = "\n".join(f"  • {o}" for o in data.get("titles",{}).get("normalized","").split(",")[:5])
            return f"'{topic}' is ambiguous. Did you mean:\n{options}\n\nTry being more specific."
        title   = data.get("title","")
        extract = data.get("extract","")
        url     = data.get("content_urls",{}).get("desktop",{}).get("page","")
        lines   = [f"Wikipedia: {title}", "", extract[:1200]]
        if url:
            lines.append(f"\n  Full article: {url}")
        return "\n".join(lines)
    except Exception as e:
        return f"Wikipedia error: {e}"


def translate_text(text: str, target_lang: str = "es") -> str:
    """
    Translate any text to any language.
    Common codes: es=Spanish, fr=French, de=German, zh=Chinese,
                  ja=Japanese, pt=Portuguese, ar=Arabic, ru=Russian, ko=Korean
    """
    try:
        r = _get("https://api.mymemory.translated.net/get",
                 params={"q": text[:500], "langpair": f"en|{target_lang}"})
        d   = r.json()
        out = d.get("responseData",{}).get("translatedText","")
        if not out or "INVALID" in out.upper():
            return f"Translation failed. Check language code: {target_lang}"
        lang_names = {
            "es":"Spanish","fr":"French","de":"German","zh":"Chinese",
            "ja":"Japanese","pt":"Portuguese","ar":"Arabic","ru":"Russian",
            "ko":"Korean","it":"Italian","nl":"Dutch","hi":"Hindi","tr":"Turkish",
        }
        lang_name = lang_names.get(target_lang, target_lang.upper())
        return f"Translation ({lang_name}):\n\n  Original: {text[:200]}\n\n  {lang_name}: {out}"
    except Exception as e:
        return f"Translation error: {e}"


def page_summary(url: str) -> str:
    """
    Fetch any webpage and give an AI-powered summary of what it contains.
    Works on news articles, research papers, product pages, documentation, anything.
    """
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r    = _get(url, timeout=12)
        html = r.text
        # Strip scripts, styles, nav
        html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r'<[^>]+>', ' ', html)
        html = re.sub(r'&[a-z]+;', ' ', html)
        text = re.sub(r'\s{3,}', '\n', html).strip()[:4000]

        summary = _ai(
            f"Here is the content of a webpage ({url}):\n\n{text}\n\n"
            "Summarize in 4-6 bullet points: What is this page about? "
            "What are the key facts, data points, or claims? "
            "Is there anything actionable or surprising?",
            system="You are a research analyst. Extract key information and be specific."
        )
        return f"Page Summary: {url}\n\n{summary}"
    except Exception as e:
        return f"Could not fetch {url}: {e}"


def patent_search(query: str, num: int = 8) -> str:
    """
    Search Google Patents for any invention, technology, or company.
    Great for competitive intel — see what companies are building before they announce it.
    """
    try:
        from urllib.parse import quote
        # Google Patents RSS
        r    = _get(f"https://patents.google.com/xhr/query?url=q%3D{quote(query)}&exp=&tags=&ajax=1",
                    headers={"X-Requested-With":"XMLHttpRequest"}, timeout=10)
        text = r.text[:6000]
    except Exception:
        text = ""

    # Fallback: use Google Patents search URL + scrape title tags
    try:
        from urllib.parse import quote as q
        r     = _get(f"https://patents.google.com/?q={q(query)}&before=priority:20260101")
        html  = r.text
        titles = re.findall(r'<span[^>]*class="[^"]*patent-title[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)[:num]
        dates  = re.findall(r'(\d{4}-\d{2}-\d{2})', html)[:num]
        assignees = re.findall(r'<span[^>]*class="[^"]*assignee[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)[:num]

        if titles:
            lines = [f"Patent Search: {query}", ""]
            for i, title in enumerate(titles[:num]):
                title = re.sub(r'\s+',' ',title).strip()
                date  = dates[i] if i < len(dates) else "?"
                asgn  = re.sub(r'\s+',' ', assignees[i]).strip() if i < len(assignees) else "?"
                lines.append(f"  {i+1}. {title}")
                lines.append(f"     {date}  by {asgn}")
            lines.append(f"\n  Full results: https://patents.google.com/?q={q(query)}")
            return "\n".join(lines)
    except Exception:
        pass

    return (f"Patent search for '{query}':\n\n"
            f"  Browse directly: https://patents.google.com/?q={query.replace(' ','+')} \n"
            f"  (JavaScript-heavy page — best viewed in browser)")


def job_scan(title: str, location: str = "remote", num: int = 10) -> str:
    """
    Scan job postings for any role and location.
    Great for salary research, market demand, or actually finding a job.
    """
    try:
        from urllib.parse import quote as q
        # Indeed RSS feed
        url = f"https://www.indeed.com/rss?q={q(title)}&l={q(location)}&sort=date"
        r   = _get(url, timeout=10)
        # Parse RSS
        titles   = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
        links    = re.findall(r'<link>(https?://[^<]+)</link>', r.text)
        snippets = re.findall(r'<description><!\[CDATA\[(.*?)\]\]></description>', r.text, re.DOTALL)

        titles = [t for t in titles if "Indeed" not in t][:num]
        if not titles:
            raise ValueError("No results")

        lines = [f"Job Scan: {title} — {location}", ""]
        for i, t in enumerate(titles):
            snip = re.sub(r'<[^>]+>',' ', snippets[i] if i < len(snippets) else "").strip()[:100]
            lines.append(f"  {i+1}. {t}")
            if snip:
                lines.append(f"     {snip}")
        lines.append(f"\n  More: https://www.indeed.com/jobs?q={q(title)}&l={q(location)}&sort=date")
        return "\n".join(lines)
    except Exception:
        # Fallback to RemoteOK for remote roles
        try:
            r    = _get(f"https://remoteok.com/api?tag={title.replace(' ','-').lower()}")
            jobs = r.json()
            if isinstance(jobs, list) and len(jobs) > 1:
                jobs = [j for j in jobs if isinstance(j, dict) and j.get("position")][:num]
                lines = [f"Job Scan (RemoteOK): {title}", ""]
                for j in jobs:
                    comp = j.get("company","?")
                    pos  = j.get("position","?")
                    sal  = j.get("salary","")
                    lines.append(f"  • {pos} @ {comp}" + (f"  [{sal}]" if sal else ""))
                return "\n".join(lines)
        except Exception:
            pass
        return (f"Job scan: https://www.indeed.com/jobs?q={title.replace(' ','+')} \n"
                f"Remote: https://remoteok.com/remote-{title.replace(' ','-').lower()}-jobs")


def company_funding(company: str) -> str:
    """
    VC funding rounds, investors, valuation for any startup or private company.
    Sources: Crunchbase public data, news search.
    """
    try:
        from tools.market import news_fetch
        news = news_fetch(f"{company} funding round valuation investors raised 2024 2025 2026", num=8)
        summary = _ai(
            f"Here is news about {company}'s funding/valuation:\n\n{news}\n\n"
            "Extract and list: latest funding round (Series ?), amount raised, "
            "lead investors, current valuation, and total raised to date. "
            "If not a startup, note what type of company it is. Be specific.",
            system="You are a venture capital analyst. Extract funding data precisely."
        )
        return f"Funding Intelligence: {company}\n\n{summary}\n\nSources:\n{news}"
    except Exception as e:
        return f"Funding lookup error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# MONITORING (persistent — checks run on demand or scheduled)
# ══════════════════════════════════════════════════════════════════════════════

def web_monitor_add(url: str, label: str = "", keyword: str = "") -> str:
    """
    Add a webpage to JARVIS's watch list.
    JARVIS will detect when it changes and alert you.
    label: friendly name (e.g. 'Tesla announcement page')
    keyword: optional — only alert when this word appears (e.g. 'IPO', 'sale')
    """
    if not url.startswith("http"):
        url = "https://" + url
    monitors = _load(_MONITORS_FILE, {})
    try:
        r       = _get(url, timeout=10)
        content = re.sub(r'<[^>]+>', ' ', r.text)
        content = re.sub(r'\s+',' ', content).strip()
        h       = hashlib.md5(content.encode()).hexdigest()
        monitors[url] = {
            "label":     label or url,
            "keyword":   keyword.lower(),
            "hash":      h,
            "last_check": datetime.now().isoformat(),
            "added":     datetime.now().isoformat(),
            "changes":   0,
        }
        _save(_MONITORS_FILE, monitors)
        return (f"Monitoring: {label or url}\n"
                f"  Will alert when the page changes" +
                (f" and '{keyword}' appears" if keyword else "") + ".\n"
                f"  Say 'check monitors' anytime to scan for updates.")
    except Exception as e:
        return f"Could not add monitor for {url}: {e}"


def web_monitor_check() -> str:
    """
    Check all monitored webpages for changes since last check.
    """
    monitors = _load(_MONITORS_FILE, {})
    if not monitors:
        return "No pages being monitored. Say 'monitor [url]' to add one."

    changed = []
    checked = 0
    for url, info in monitors.items():
        try:
            r       = _get(url, timeout=10)
            content = re.sub(r'<[^>]+>', ' ', r.text)
            content = re.sub(r'\s+',' ', content).strip()
            h       = hashlib.md5(content.encode()).hexdigest()
            now     = datetime.now().isoformat()
            kw      = info.get("keyword","")
            if h != info["hash"]:
                kw_found = not kw or kw in content.lower()
                if kw_found:
                    info["changes"] += 1
                    changed.append({
                        "label":   info["label"],
                        "url":     url,
                        "keyword": kw,
                        "times":   info["changes"],
                    })
                info["hash"]       = h
            info["last_check"] = now
            monitors[url]      = info
            checked += 1
        except Exception:
            pass

    _save(_MONITORS_FILE, monitors)

    lines = [f"Web Monitor Check — {checked} sites scanned", ""]
    if changed:
        lines.append(f"  CHANGES DETECTED ({len(changed)}):")
        for c in changed:
            lines.append(f"  🔔 {c['label']}")
            lines.append(f"     {c['url']}")
            if c["keyword"]:
                lines.append(f"     Keyword '{c['keyword']}' found!")
    else:
        lines.append("  No changes detected on any monitored page.")

    lines += ["", f"  Monitoring {len(monitors)} page(s) total."]
    return "\n".join(lines)


def web_monitor_list() -> str:
    """List all currently monitored web pages."""
    monitors = _load(_MONITORS_FILE, {})
    if not monitors:
        return "No pages being monitored. Say 'monitor [url] for [keyword]' to add one."
    lines = [f"Monitored Pages ({len(monitors)})", ""]
    for url, info in monitors.items():
        last = info.get("last_check","?")[:16].replace("T"," ")
        chgs = info.get("changes", 0)
        kw   = info.get("keyword","")
        lines.append(f"  • {info['label']}")
        lines.append(f"    {url}")
        lines.append(f"    Last checked: {last}  Changes: {chgs}" + (f"  Keyword: {kw}" if kw else ""))
    return "\n".join(lines)


def web_monitor_remove(label_or_url: str) -> str:
    """Remove a page from the monitor list."""
    monitors = _load(_MONITORS_FILE, {})
    to_remove = [u for u, v in monitors.items()
                 if label_or_url.lower() in u.lower() or label_or_url.lower() in v.get("label","").lower()]
    for u in to_remove:
        del monitors[u]
    _save(_MONITORS_FILE, monitors)
    return f"Removed {len(to_remove)} monitor(s) matching '{label_or_url}'." if to_remove else "No match found."


def price_watch_add(url: str, product_name: str, target_price: float) -> str:
    """
    Watch any product page for a price drop.
    Works on Amazon, Best Buy, Newegg, most retail sites.
    JARVIS will alert when the price hits your target.
    """
    if not url.startswith("http"):
        url = "https://" + url
    watches = _load(_PRICES_FILE, {})
    try:
        r    = _get(url, timeout=10)
        html = r.text
        # Find price patterns in page
        prices = re.findall(r'\$\s*([\d,]+\.?\d{0,2})', html)
        prices = [float(p.replace(",","")) for p in prices if 0.5 < float(p.replace(",","")) < 50000]
        current = min(prices) if prices else None
        watches[url] = {
            "product":    product_name,
            "target":     target_price,
            "current":    current,
            "added":      datetime.now().isoformat(),
            "last_check": datetime.now().isoformat(),
        }
        _save(_PRICES_FILE, watches)
        msg = f"Watching: {product_name}\n  Target: ${target_price:.2f}"
        if current:
            msg += f"\n  Current: ${current:.2f}"
            if current <= target_price:
                msg += "\n  ALREADY AT OR BELOW TARGET PRICE!"
        return msg
    except Exception as e:
        return f"Could not add price watch: {e}"


def price_watch_check() -> str:
    """Check all price watches — alert on anything at or below target."""
    watches = _load(_PRICES_FILE, {})
    if not watches:
        return "No price watches set. Say 'watch price of [product] at [url] target $X'."

    hits   = []
    misses = []
    for url, info in watches.items():
        try:
            r      = _get(url, timeout=10)
            prices = re.findall(r'\$\s*([\d,]+\.?\d{0,2})', r.text)
            prices = [float(p.replace(",","")) for p in prices if 0.5 < float(p.replace(",","")) < 50000]
            if prices:
                current = min(prices)
                info["current"]    = current
                info["last_check"] = datetime.now().isoformat()
                watches[url]       = info
                if current <= info["target"]:
                    hits.append({**info, "url": url, "current": current})
                else:
                    misses.append({**info, "url": url, "current": current})
        except Exception:
            pass

    _save(_PRICES_FILE, watches)
    lines = [f"Price Watch Report — {len(watches)} items", ""]
    if hits:
        lines.append("  PRICE ALERTS:")
        for h in hits:
            lines.append(f"  🎯 {h['product']}")
            lines.append(f"     Current: ${h['current']:.2f}  Target: ${h['target']:.2f}")
            lines.append(f"     BUY: {h['url']}")
    if misses:
        lines.append("" if hits else "")
        lines.append("  Watching:")
        for m in misses:
            lines.append(f"  • {m['product']}: ${m.get('current','?'):.2f} (target ${m['target']:.2f})")
    return "\n".join(lines)
