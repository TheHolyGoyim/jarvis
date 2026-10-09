"""
tools/political_intel.py — role-based political & geopolitical market intelligence.

Tracks political figures by ROLE, not name: the role carries the market-impact
map, so when a new person assumes the role the same map applies automatically.
Holders are updateable at runtime (store key 'political_roles') — the seeded
names are "as of early 2026" and may rotate.

Pieces:
  classify_entity(text)   — PERSON / TICKER / COMPANY / SECTOR / CONCEPT
  person_impact(name)     — role-based market-impact analysis (never yfinance)
  15-min news scanner     — role headlines → impact map → catalyst score 1-10;
                            ≥6 queues affected tickers, ≥8 alerts the user
  geo risk score 0-100    — live, drives position sizing + conviction scaling
  political_briefing()    — morning-brief section + on-demand report
  catalyst_multiplier(sym)— conviction multiplier for politically-driven names
"""

import re
import time
import threading
import hashlib
from datetime import datetime
from pathlib import Path
from tools.store import get, put

_ROLES_KEY = "political_roles"
_CAT_KEY   = "political_catalysts"     # symbol → {score, note, ts}
_GEO_KEY   = "geo_risk"                # {score, factors[]}
_SEEN_FILE = Path.home() / "Documents" / "JARVIS" / "trading" / "political_seen.txt"
_LOG_FILE  = Path.home() / "Documents" / "JARVIS" / "trading" / "political_log.txt"
_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)

_state = {"running": False, "runs": 0, "last_hits": [], "last_scan": 0.0}


def _log(msg: str):
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%m-%d %H:%M')}] {msg}\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ROLE REGISTRY — role defines impact; holder names are replaceable data
# ══════════════════════════════════════════════════════════════════════════════

_ROLE_SEED = {   # role: (title, holder-as-of-early-2026, [aliases], weight 1-10)
    "us_president":     ("US President", "Donald Trump", ["trump", "president trump", "potus"], 10),
    "fed_chair":        ("Federal Reserve Chair", "Jerome Powell", ["powell", "fed chair"], 10),
    "treasury_sec":     ("US Treasury Secretary", "Scott Bessent", ["bessent", "treasury secretary"], 8),
    "state_sec":        ("US Secretary of State", "Marco Rubio", ["rubio", "secretary of state"], 7),
    "defense_sec":      ("US Secretary of Defense", "Pete Hegseth", ["hegseth", "defense secretary", "pentagon chief"], 7),
    "china_leader":     ("China Head of State", "Xi Jinping", ["xi jinping", "xi"], 9),
    "russia_leader":    ("Russia Head of State", "Vladimir Putin", ["putin"], 8),
    "eu_leader":        ("EU Commission President", "Ursula von der Leyen", ["von der leyen"], 7),
    "uk_leader":        ("UK Prime Minister", "Keir Starmer", ["starmer"], 6),
    "japan_leader":     ("Japan Prime Minister", "Sanae Takaichi", ["takaichi", "japan pm"], 6),
    "saudi_energy":     ("Saudi Energy Minister", "Abdulaziz bin Salman", ["abdulaziz bin salman", "saudi energy minister"], 8),
    "opec_sg":          ("OPEC Secretary General", "Haitham al-Ghais", ["al-ghais", "opec secretary"], 8),
    "ecb_head":         ("ECB President", "Christine Lagarde", ["lagarde", "ecb president"], 7),
    "boj_head":         ("BOJ Governor", "Kazuo Ueda", ["ueda", "boj governor"], 6),
    "boe_head":         ("BOE Governor", "Andrew Bailey", ["bailey", "boe governor"], 6),
    "ceo_aapl":         ("Apple CEO", "Tim Cook", ["tim cook"], 6),
    "ceo_msft":         ("Microsoft CEO", "Satya Nadella", ["nadella"], 6),
    "ceo_googl":        ("Google CEO", "Sundar Pichai", ["pichai"], 6),
    "ceo_meta":         ("Meta CEO", "Mark Zuckerberg", ["zuckerberg"], 6),
    "ceo_amzn":         ("Amazon CEO", "Andy Jassy", ["jassy"], 6),
    "ceo_nvda":         ("Nvidia CEO", "Jensen Huang", ["jensen huang", "huang"], 7),
    "ceo_tsla":         ("Tesla CEO", "Elon Musk", ["elon musk", "musk", "elon"], 7),
}


def get_roles() -> dict:
    roles = {k: {"title": t, "holder": h, "aliases": a, "weight": w}
             for k, (t, h, a, w) in _ROLE_SEED.items()}
    try:
        for k, v in (get(_ROLES_KEY) or {}).items():
            if k in roles and isinstance(v, dict):
                roles[k].update({x: v[x] for x in ("holder", "aliases") if x in v})
    except Exception:
        pass
    return roles


def role_set(role: str, holder: str) -> str:
    """A new person assumed a role — same impact map applies automatically."""
    roles = get_roles()
    key = next((k for k in roles if role.lower().replace(" ", "_") in k
                or role.lower() in roles[k]["title"].lower()), None)
    if not key:
        return f"Unknown role '{role}'. Known: " + ", ".join(r["title"] for r in roles.values())
    custom = get(_ROLES_KEY) or {}
    custom[key] = {"holder": holder.strip(),
                   "aliases": [holder.strip().lower(), holder.strip().split()[-1].lower()]}
    put(_ROLES_KEY, custom)
    return f"Updated: {roles[key]['title']} = {holder}. The {roles[key]['title']} impact map now applies to them."


# ══════════════════════════════════════════════════════════════════════════════
# IMPACT MAPS — (trigger regex, longs, shorts, note, score 1-10)
# ══════════════════════════════════════════════════════════════════════════════

_IMPACT = {
    "us_president": [
        (r'tariff|trade restriction|trade war|import tax', ["X", "NUE", "STLD", "CLF"], ["importer supply chains"], "tariffs: long domestic producers, short importers", 8),
        (r'infrastructure|spending bill|stimulus', ["CAT", "VMC", "MLM", "URI"], [], "spending: long construction/materials", 7),
        (r'deregulat', [], [], "deregulation: long the named sector broadly", 7),
        (r'investigat|antitrust|new regulation|crackdown', [], ["targeted sector"], "regulation: short the target", 7),
        (r'drill|fossil|oil and gas|energy independence|pipeline', ["XOM", "CVX", "OXY", "KMI"], ["ICLN", "TAN", "EV names"], "fossil push: long oil/gas, short renewables", 7),
        (r'green energy|climate|clean energy|solar|wind power', ["TAN", "ICLN", "ENPH", "FSLR"], ["XOM", "CVX"], "green push: long clean energy", 7),
        (r'crypto|bitcoin|digital asset', ["MSTR", "COIN", "RIOT", "MARA"], [], "crypto promotion: long BTC-adjacent", 8),
        (r'domestic manufactur|made in america|reshor', ["X", "NUE", "F", "GM", "CAT"], [], "reshoring: long US industrials/steel/auto", 7),
    ],
    "fed_chair": [
        (r'raise rates|rate hike|hawkish|tighten|higher for longer|inflation remains', ["XLF", "KRE"], ["XLRE", "XLU", "TLT", "growth tech"], "hawkish: long banks, short REITs/utilities/growth", 9),
        (r'cut rates|rate cut|dovish|easing|accommodat', ["XLRE", "XLU", "TLT", "QQQ"], ["XLF"], "dovish: long real estate/utilities/growth", 9),
        (r'hold rates|pause|patient|wait and see', ["SPY"], [], "pause: mild broad positive", 6),
        (r'quantitative tightening|balance sheet reduction|runoff', [], ["ARKK", "COIN", "MSTR"], "QT: short speculative growth", 7),
        (r'quantitative easing|asset purchases', ["QQQ", "ARKK", "IWM"], [], "QE: long risk assets", 8),
    ],
    "treasury_sec": [
        (r'strong dollar|dollar strength', [], ["multinationals", "GLD", "EEM"], "strong dollar: short multinationals/EM", 6),
        (r'sanction', ["LMT", "RTX", "CRWD", "PANW"], ["exposed revenue names"], "sanctions: long defense/cyber", 7),
        (r'debt ceiling|default|spending concern', [], ["TLT", "SPY"], "debt stress: short bonds/risk", 7),
    ],
    "state_sec": [
        (r'escalat|conflict|strike|military action|troops', ["LMT", "RTX", "NOC", "GD", "AXON", "XOM"], ["JETS", "airlines", "XLY"], "escalation: long defense/oil, short travel", 8),
        (r'peace|ceasefire|diplomacy|de-escalat|agreement', [], ["LMT", "RTX", "NOC"], "peace progress: short defense, long trade", 6),
    ],
    "foreign_leader": [
        (r'tariff|trade|export ban|import', [], [], "trade policy: map to affected import/export sectors", 7),
        (r'military|territorial|invasion|missile|drill', ["LMT", "RTX", "GLD", "TLT"], ["regional risk assets"], "military action: long defense/safe havens", 8),
        (r'stimulus|economic support|rate cut', ["FXI", "commodities", "LVMH-adjacent"], [], "stimulus: long commodities/exposure names", 6),
        (r'currency|devalu|intervention', [], ["exposed multinationals"], "currency move: check FX-exposed names", 6),
    ],
    "energy_official": [
        (r'production cut|cut output|reduce production', ["XOM", "CVX", "OXY", "XLE"], [], "OPEC cut: long all energy", 9),
        (r'production increase|raise output|boost production', [], ["XLE", "XOM", "OXY"], "OPEC increase: short energy", 8),
        (r'emergency meeting', [], [], "OPEC emergency meeting: volatility signal", 7),
    ],
    "central_banker": [
        (r'rate|policy|guidance|inflation', [], [], "central bank guidance: currency-bloc sensitivity", 6),
    ],
    "tech_ceo": [
        (r'announc|launch|unveil|new product', ["company + suppliers"], [], "product launch: long company + suppliers", 6),
        (r'guidance|outlook|forecast', [], [], "guidance: direct price impact", 7),
        (r'testimony|hearing|regulator', [], [], "regulatory testimony: sector sentiment", 5),
        (r'job cuts|layoff', [], ["RHI", "staffing"], "layoffs: efficiency narrative long, staffing short", 5),
    ],
}

_ROLE_TO_MAP = {"us_president": "us_president", "fed_chair": "fed_chair",
                "treasury_sec": "treasury_sec", "state_sec": "state_sec",
                "defense_sec": "state_sec", "china_leader": "foreign_leader",
                "russia_leader": "foreign_leader", "eu_leader": "foreign_leader",
                "uk_leader": "foreign_leader", "japan_leader": "foreign_leader",
                "saudi_energy": "energy_official", "opec_sg": "energy_official",
                "ecb_head": "central_banker", "boj_head": "central_banker",
                "boe_head": "central_banker"}


def _map_key(role_key: str) -> str:
    """Every ceo_* role shares the tech_ceo impact map."""
    return _ROLE_TO_MAP.get(role_key, "tech_ceo" if role_key.startswith("ceo_") else role_key)


def _role_for_text(text: str):
    """Match a headline to a role via holder name/aliases or title keywords.
    Word-boundary matching — a bare substring would let alias 'xi' match
    inside 'Mexico' and misattribute headlines."""
    low = text.lower()
    for key, r in get_roles().items():
        names = [r["holder"].lower()] + [a.lower() for a in r["aliases"]] + [r["title"].lower()]
        for n in names:
            if n and re.search(r'\b' + re.escape(n) + r'\b', low):
                return key, r
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# ENTITY CLASSIFICATION (Bug 1: people are never stock lookups)
# ══════════════════════════════════════════════════════════════════════════════

_SECTORS = ["technology", "healthcare", "energy", "financials", "consumer",
            "industrials", "materials", "utilities", "real estate", "communication",
            "defense", "semiconductors", "banks", "biotech", "crypto"]
_CONCEPTS = ["inflation", "rates", "recession", "tariffs", "gdp", "unemployment",
             "the fed", "fomc", "earnings season", "the dollar", "oil prices"]


def is_person(name: str) -> bool:
    """True only for KNOWN political/CEO figures — never guesses on other names,
    so real companies can't be misclassified."""
    key, _ = _role_for_text(name)
    return key is not None


def classify_entity(text: str) -> str:
    t = text.strip()
    low = t.lower()
    if is_person(t):
        return "PERSON"
    if re.fullmatch(r'[A-Z]{1,5}', t):
        return "TICKER"
    if any(s == low or low in (s, s + " sector", s + " stocks") for s in _SECTORS):
        return "SECTOR"
    if any(c in low for c in _CONCEPTS):
        return "CONCEPT"
    return "COMPANY"


def person_impact(name: str) -> str:
    """Role-based market impact analysis for a political figure — the answer to
    'what is this person's role and how does their activity affect markets?'"""
    key, r = _role_for_text(name)
    if not key:
        return f"{name} isn't in my political role registry — treating as a company/topic."
    rules = _IMPACT.get(_map_key(key), [])
    lines = [f"🏛 {r['holder']} — {r['title']} (market weight {r['weight']}/10)", "━" * 30,
             "Impact map (what their statements move):"]
    for _pat, longs, shorts, note, sc in rules[:8]:
        lines.append(f"  • {note}  [catalyst {sc}/10]")
    # Recent headlines mentioning them
    heads = _headlines(f'"{r["holder"]}" market OR economy OR policy', 4)
    if heads:
        lines.append("Recent headlines:")
        lines += [f"  → {h[:90]}" for h in heads]
    lines.append("NOTE: this is a PERSON — analyzed by role impact, never a stock lookup.")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# NEWS SCANNING (every 15 min in market hours, hourly overnight)
# ══════════════════════════════════════════════════════════════════════════════

_FEEDS = [
    ("Fed official",  "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("White House",   "https://news.google.com/rss/search?q=White+House+OR+president+statement+economy&hl=en-US"),
    ("Fed news",      "https://news.google.com/rss/search?q=Federal+Reserve+Powell+rates&hl=en-US"),
    ("Treasury",      "https://news.google.com/rss/search?q=Treasury+Secretary+dollar+sanctions&hl=en-US"),
    ("Geopolitics",   "https://news.google.com/rss/search?q=sanctions+OR+military+OR+conflict+markets&hl=en-US"),
    ("OPEC",          "https://news.google.com/rss/search?q=OPEC+oil+production&hl=en-US"),
    ("Central banks", "https://news.google.com/rss/search?q=ECB+OR+BOJ+OR+%22central+bank%22+rate+decision&hl=en-US"),
    ("Hearings",      "https://news.google.com/rss/search?q=congressional+hearing+testimony+CEO&hl=en-US"),
    ("World leaders", "https://news.google.com/rss/search?q=G7+OR+G20+OR+%22Xi+Jinping%22+OR+Putin+economy&hl=en-US"),
]


def _headlines(query_or_url: str, n: int = 6) -> list:
    import requests
    url = (query_or_url if query_or_url.startswith("http") else
           f"https://news.google.com/rss/search?q={requests.utils.quote(query_or_url)}&hl=en-US")
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", r.text, re.DOTALL)
        return [re.sub(r"\s+", " ", t).strip() for t in titles[1:n + 1] if t.strip()]
    except Exception:
        return []


def _seen(h: str) -> bool:
    hh = hashlib.md5(h.lower().encode()).hexdigest()[:12]
    try:
        seen = set(_SEEN_FILE.read_text(encoding="utf-8").splitlines()[-400:]) if _SEEN_FILE.exists() else set()
    except Exception:
        seen = set()
    if hh in seen:
        return True
    try:
        with open(_SEEN_FILE, "a", encoding="utf-8") as f:
            f.write(hh + "\n")
    except Exception:
        pass
    return False


def _save_catalyst(sym: str, score: int, note: str):
    cats = get(_CAT_KEY) or {}
    cats[sym.upper()] = {"score": score, "note": note[:160], "ts": time.time()}
    # prune >24h
    cats = {k: v for k, v in cats.items() if time.time() - v.get("ts", 0) < 86400}
    put(_CAT_KEY, cats)


# ── Geo risk score ─────────────────────────────────────────────────────────────

_GEO_TRIGGERS = [
    (r'nuclear|wmd|chemical weapon', 30, "WMD-level threat language"),
    (r'(?:g7|nato|united states|us|uk|france|germany|japan|canada|italy).{0,40}(?:conflict|war|strike|attack)|(?:conflict|war|strike|attack).{0,40}(?:g7|nato)', 25, "conflict involving G7/NATO"),
    (r'emergency (?:meeting|session).{0,30}(?:g7|g20|security council|un\b)|security council emergency', 15, "emergency G7/UN session"),
    (r'major sanctions|sweeping sanctions|sanctions on (?:china|russia|japan|germany|india|uk|france|brazil|italy|canada)', 15, "major-economy sanctions"),
    (r'oil (?:supply )?(?:disruption|halt|blockade)|strait of hormuz', 20, "oil supply disruption"),
    (r'currency crisis|currency collapse|capital controls', 15, "G20 currency crisis"),
]


def _geo_get() -> dict:
    g = get(_GEO_KEY) or {"score": 10, "factors": []}
    # decay factors older than 48h
    fresh = [f for f in g.get("factors", []) if time.time() - f.get("ts", 0) < 172800]
    g["factors"] = fresh
    g["score"] = max(5, min(100, 10 + sum(f["pts"] for f in fresh)))
    return g


def geo_risk_score() -> int:
    return _geo_get()["score"]


def geo_band(score: int = None) -> str:
    s = geo_risk_score() if score is None else score
    return ("NORMAL" if s <= 30 else "ELEVATED" if s <= 60 else
            "HIGH" if s <= 80 else "CRITICAL")


def geo_size_factor() -> float:
    """Position-size multiplier from geo risk: 1.0 / 0.75 / 0.5 / 0 (halt)."""
    s = geo_risk_score()
    return 1.0 if s <= 30 else 0.75 if s <= 60 else 0.5 if s <= 80 else 0.0


def geo_conviction_multiplier() -> float:
    s = geo_risk_score()
    return 1.0 if s <= 60 else 0.75 if s <= 80 else 0.5


def catalyst_multiplier(symbol: str):
    """(multiplier, note) for a politically-driven ticker, 24h window."""
    c = (get(_CAT_KEY) or {}).get(symbol.upper())
    if not c or time.time() - c.get("ts", 0) > 86400:
        return 1.0, ""
    s = c.get("score", 0)
    mult = 1.5 if s >= 10 else 1.4 if s >= 8 else 1.25 if s >= 6 else 1.0
    return mult, c.get("note", "")


def geo_risk_show() -> str:
    g = _geo_get()
    s = g["score"]
    band = geo_band(s)
    meaning = {"NORMAL": "normal trading parameters",
               "ELEVATED": "position sizes reduced 25%, tilt defensive",
               "HIGH": "position sizes reduced 50%, defensive sectors only",
               "CRITICAL": "NEW POSITIONS HALTED, stops tightened"}[band]
    lines = [f"🌍 GEOPOLITICAL RISK: {s}/100 — {band}", "━" * 30, f"  effect: {meaning}"]
    if g["factors"]:
        lines.append("  active factors:")
        lines += [f"    • {f['label']} (+{f['pts']}, {datetime.fromtimestamp(f['ts']).strftime('%m-%d %H:%M')})"
                  for f in g["factors"][-6:]]
    else:
        lines.append("  no active risk factors — baseline")
    return "\n".join(lines)


# ── The scan cycle ─────────────────────────────────────────────────────────────

def scan_political(push: bool = True) -> list:
    """One full pass over the political feeds. Returns list of hits."""
    hits = []
    geo = _geo_get()
    for src, url in _FEEDS:
        for h in _headlines(url, 6):
            if _seen(h):
                continue
            low = h.lower()
            # geo risk triggers apply to every headline
            for pat, pts, label in _GEO_TRIGGERS:
                if re.search(pat, low):
                    geo["factors"].append({"label": f"{label}: {h[:70]}", "pts": pts, "ts": time.time()})
                    _log(f"GEO +{pts}: {h[:90]}")
            role_key, role = _role_for_text(h)
            if not role_key:
                continue
            rules = _IMPACT.get(_map_key(role_key), [])
            for pat, longs, shorts, note, base_score in rules:
                if not re.search(pat, low):
                    continue
                score = min(10, base_score + (1 if role["weight"] >= 9 else 0))
                tickers = [t for t in longs if re.fullmatch(r'[A-Z]{1,5}', t)]
                hit = {"headline": h[:140], "who": role["holder"], "role": role["title"],
                       "note": note, "score": score, "tickers": tickers,
                       "shorts": [t for t in shorts if re.fullmatch(r'[A-Z]{1,5}', str(t))],
                       "ts": datetime.now().strftime("%m-%d %H:%M"), "src": src}
                hits.append(hit)
                _log(f"POLITICAL {score}/10 [{role['title']}] {h[:90]} → {note}")
                for t in tickers[:4]:
                    _save_catalyst(t, score, f"{role['title']}: {note}")
                if push and score >= 6 and tickers:
                    _queue_political(hit)
                if push and score >= 8:
                    _alert_user(hit)
                break
    put(_GEO_KEY, {"score": geo["score"], "factors": geo["factors"]})
    _state["last_hits"] = (hits + _state["last_hits"])[:30]
    _state["runs"] += 1
    _state["last_scan"] = time.time()
    return hits


def _queue_political(hit: dict):
    try:
        import tools.opportunity_scan as OPP
        q = OPP.queue_get()
        existing = {e["symbol"] for e in q}
        for t in hit["tickers"][:3]:
            if t in existing:
                continue
            tag = ("Presidential mention — 24hr priority" if "President" in hit["role"]
                   else f"Political catalyst ({hit['role']})")
            q.insert(0, {"symbol": t, "score": 60 + hit["score"] * 4, "price": 0,
                         "reasons": [f"{tag}: {hit['note']}", hit["headline"][:80]],
                         "ts": hit["ts"], "source": "political",
                         "pinned": hit["score"] >= 8})
        OPP._queue_save(q)
    except Exception as e:
        _log(f"queue push failed: {e}")


def _alert_user(hit: dict):
    try:
        import tools.trade_monitor as MON
        MON._push_user_alert(
            f"🏛 POLITICAL CATALYST {hit['score']}/10 — {hit['who']} ({hit['role']}): "
            f"{hit['note']}. {('Watch: ' + ', '.join(hit['tickers'][:4])) if hit['tickers'] else ''}\n"
            f"“{hit['headline'][:100]}”")
    except Exception:
        pass


# ── Reports ────────────────────────────────────────────────────────────────────

def political_briefing() -> str:
    day = datetime.now().strftime("%A, %b %d")
    if time.time() - _state["last_scan"] > 900:
        try:
            scan_political(push=False)
        except Exception:
            pass
    hits = _state["last_hits"]
    lines = [f"🏛 Political Intelligence for {day}:", "━" * 30]
    if hits:
        lines.append("Recent political events affecting markets:")
        for h in hits[:5]:
            tick = f" → {', '.join(h['tickers'][:3])}" if h["tickers"] else ""
            lines.append(f"  [{h['score']}/10] {h['who']}: {h['note']}{tick}")
    else:
        lines.append("  No market-moving political events detected in recent scans.")
    sched = _headlines("Fed speech OR congressional hearing OR economic data today", 4)
    if sched:
        lines.append("On the calendar / speaking today:")
        lines += [f"  • {s[:85]}" for s in sched]
    lines.append(geo_risk_show().split("\n")[0] + f" ({geo_band()})")
    cats = sorted((get(_CAT_KEY) or {}).items(), key=lambda kv: -kv[1]["score"])[:3]
    if cats:
        lines.append("Top politically-driven opportunities:")
        lines += [f"  {i}. {sym} — {v['note']} [{v['score']}/10]"
                  for i, (sym, v) in enumerate(cats, 1)]
    return "\n".join(lines)


def political_movers() -> str:
    """'Who is moving markets today' — recent role-holder hits."""
    if time.time() - _state["last_scan"] > 900:
        try:
            scan_political(push=False)
        except Exception:
            pass
    hits = _state["last_hits"]
    if not hits:
        return ("🏛 No political figures moving markets in recent scans. "
                f"Geo risk {geo_risk_score()}/100 ({geo_band()}).")
    by_who = {}
    for h in hits[:15]:
        by_who.setdefault(f"{h['who']} ({h['role']})", []).append(h)
    lines = ["🏛 WHO IS MOVING MARKETS", "━" * 30]
    for who, hs in list(by_who.items())[:6]:
        lines.append(f"  {who} — {len(hs)} catalyst(s), max {max(x['score'] for x in hs)}/10")
        lines.append(f"    latest: {hs[0]['note']}")
    return "\n".join(lines)


def role_news(role_query: str) -> str:
    """'What did the Fed chair say recently' — headlines for a role holder."""
    key, r = _role_for_text(role_query)
    if not key:
        # try matching by title words
        for k, rr in get_roles().items():
            if any(w in rr["title"].lower() for w in role_query.lower().split() if len(w) > 3):
                key, r = k, rr
                break
    if not key:
        return f"Couldn't map '{role_query}' to a tracked role. Say 'political briefing' for the overview."
    heads = _headlines(f'"{r["holder"]}"', 6)
    lines = [f"🏛 {r['holder']} ({r['title']}) — recent:", "━" * 30]
    lines += [f"  → {h[:95]}" for h in heads] or ["  (no recent headlines found)"]
    return "\n".join(lines)


def scanner_status() -> str:
    return "\n".join([
        "🏛 POLITICAL SCANNER", "━" * 30,
        f"  running: {'yes' if _state['running'] else 'NO'}",
        f"  scans completed: {_state['runs']}",
        f"  recent hits: {len(_state['last_hits'])}",
        f"  geo risk: {geo_risk_score()}/100 ({geo_band()})",
        f"  roles tracked: {len(get_roles())}",
        f"  log: {_LOG_FILE}",
    ])


# ── Scheduler ──────────────────────────────────────────────────────────────────

def _loop():
    _log("Political scanner started (15min market hours / 60min overnight)")
    while _state["running"]:
        try:
            open_now = False
            try:
                import tools.trading as TRD
                open_now = bool(TRD._api("GET", "/v2/clock").get("is_open"))
            except Exception:
                pass
            interval = 900 if open_now else 3600
            if time.time() - _state["last_scan"] >= interval:
                scan_political(push=open_now)   # queue/alerts only in market hours
        except Exception as e:
            _log(f"loop error: {e}")
        time.sleep(60)


def start_political_scanner() -> str:
    if _state["running"]:
        return "Political scanner already running."
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True).start()
    return "Political scanner started (15-min cycles in market hours)."
