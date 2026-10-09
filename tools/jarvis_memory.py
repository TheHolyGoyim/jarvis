"""
jarvis_memory.py — JARVIS Self-Learning Memory Engine
Fully local, offline, zero Anthropic dependency.
Storage: SQLite at ~/Documents/JARVIS/memory/jarvis_brain.db

What it learns:
  • Which commands the user runs most (tool preference profile)
  • Which stocks/sectors the user cares about (ticker frequency)
  • Trade outcomes: what worked, what didn't (conviction calibration)
  • Custom notes the user explicitly tells Jarvis to remember

This context is injected into every Ollama system prompt so Jarvis gets
smarter with each interaction — no cloud, no retraining, no API calls.
"""

import os, re, json, sqlite3
from datetime import datetime
from pathlib import Path

_MEM_DIR = Path.home() / "Documents" / "JARVIS" / "memory"
_MEM_DIR.mkdir(parents=True, exist_ok=True)
_DB      = _MEM_DIR / "jarvis_brain.db"

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

# Conversation consolidation thresholds — keep the raw table bounded so it
# never grows forever; older turns get compressed into a rolling summary
# instead of being kept verbatim.
_KEEP_RECENT   = 40   # raw turns (≈20 exchanges) always kept verbatim
_CHUNK_SIZE    = 20   # turns consolidated into the summary at a time
_SUMMARY_CAP   = 3000 # hard char cap on the stored summary, regardless of LLM output

_CRITIQUE_PATTERNS = [
    r"\bno,?\s+that'?s (not|wrong)\b", r"\bthat'?s not (what|right|it)\b",
    r"\bi meant\b", r"\bactually i (wanted|meant|need(ed)?)\b",
    r"\bnot what i asked\b", r"\btry again\b", r"\bredo (that|this)\b",
    r"\bfix (that|this)\b", r"\bdo(n'?t| not) do that\b",
    r"\bthat'?s (incorrect|inaccurate)\b", r"\bwrong (answer|approach|way)\b",
    r"\binstead,? (do|use|try)\b", r"\bi (already )?told you\b",
    r"\bstop doing that\b", r"\bplease don'?t\b",
]

_COMMON = {
    "THE","AND","FOR","BUY","SELL","GET","SET","RUN","SHOW","FROM","WITH",
    "THIS","THAT","AUTO","HUNT","JUST","LIKE","ARE","NOT","WERE","BEEN",
    "HAVE","WILL","INTO","OVER","SUCH","YOUR","THEIR","ALSO","WHEN","WHAT",
    "HOW","WHY","CAN","YOU","ME","MY","IT","IS","IN","ON","AT","OF","TO",
    "A","I","BY","DO","GO","UP","SO","WE","HE","HIS","HER","WHO",
}


# ── DB setup ──────────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            user_query  TEXT,
            tool_used   TEXT,
            success     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS trade_outcomes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            symbol      TEXT,
            direction   TEXT,
            entry       REAL,
            exit_price  REAL,
            pnl         REAL,
            conviction  INTEGER,
            outcome     TEXT,
            hold_mins   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            category    TEXT DEFAULT 'general',
            note        TEXT
        );
        CREATE TABLE IF NOT EXISTS preferences (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_summary (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            summary     TEXT,
            updated_at  TEXT
        );
    """)
    conn.commit()
    return conn


# ── Logging ───────────────────────────────────────────────────────────────────────

def log_interaction(user_query: str, tool_used: str = "", success: bool = True):
    """Call this on every user message. Async-safe — never raises."""
    try:
        c = _db()
        c.execute(
            "INSERT INTO interactions (ts, user_query, tool_used, success) VALUES (?,?,?,?)",
            (datetime.now().isoformat(), (user_query or "")[:400],
             (tool_used or "")[:80], 1 if success else 0)
        )
        c.commit()
        c.close()
    except Exception:
        pass


def log_trade_outcome(symbol: str, direction: str, entry: float, exit_price: float,
                      pnl: float, conviction: int = 0, outcome: str = "", hold_mins: int = 0):
    """Call when a trade closes to build the performance learning database."""
    try:
        c = _db()
        c.execute(
            """INSERT INTO trade_outcomes
               (ts, symbol, direction, entry, exit_price, pnl, conviction, outcome, hold_mins)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(), symbol.upper(), direction,
             entry, exit_price, pnl, conviction, outcome, hold_mins)
        )
        c.commit()
        c.close()
    except Exception:
        pass


def save_note(note: str, category: str = "general"):
    """Save a user-specific note (e.g. 'remember I prefer swing trades')."""
    try:
        c = _db()
        c.execute(
            "INSERT INTO user_notes (ts, category, note) VALUES (?,?,?)",
            (datetime.now().isoformat(), category, note[:500])
        )
        c.commit()
        c.close()
    except Exception:
        pass


def set_preference(key: str, value: str):
    """Explicitly set a user preference."""
    try:
        c = _db()
        c.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
            (key, value, datetime.now().isoformat())
        )
        c.commit()
        c.close()
    except Exception:
        pass


# ── Local AI (for consolidation summaries) ─────────────────────────────────────────

def _ai(prompt: str, system: str = "", timeout: int = 40) -> str:
    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": _OLLAMA_MODEL, "prompt": prompt,
                  "system": system or "You write terse, factual summaries. No fluff.",
                  "stream": False},
            timeout=timeout,
        )
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return ""


# ── Conversation history & consolidation ───────────────────────────────────────────
# The point: a persistent record of what was actually said (not just which tool was
# used), so Jarvis can be closed and reopened — even across a PC restart — and pick
# back up without the user re-explaining themselves or opening a new chat thread.
# The raw table is kept bounded by periodically compressing older turns into one
# rolling summary instead of storing the whole conversation verbatim forever.

def log_turn(role: str, content: str) -> None:
    """Persist one conversation turn (role: 'user' or 'assistant')."""
    if not content:
        return
    try:
        c = _db()
        c.execute(
            "INSERT INTO conversation_turns (ts, role, content) VALUES (?,?,?)",
            (datetime.now().isoformat(), role, content[:4000])
        )
        c.commit()
        c.close()
    except Exception:
        pass


def get_recent_turns(limit: int = 40) -> list:
    """Most recent conversation turns, chronological order — for rehydrating history on startup."""
    try:
        c = _db()
        rows = c.execute(
            "SELECT role, content FROM conversation_turns ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        c.close()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception:
        return []


def consolidate_conversation() -> str:
    """
    If the raw turn log has grown past the keep-recent window, compress the
    oldest chunk into the rolling summary (merging with whatever summary
    already exists) and delete those raw rows. Cheap no-op when under threshold
    — safe to call after every exchange.
    """
    try:
        c = _db()
        total = c.execute("SELECT COUNT(*) n FROM conversation_turns").fetchone()["n"]
        if total <= _KEEP_RECENT + _CHUNK_SIZE:
            c.close()
            return ""

        oldest = c.execute(
            "SELECT id, role, content FROM conversation_turns ORDER BY id ASC LIMIT ?",
            (_CHUNK_SIZE,)
        ).fetchall()
        if not oldest:
            c.close()
            return ""

        transcript = "\n".join(f"{r['role'].upper()}: {r['content'][:400]}" for r in oldest)
        prior = c.execute("SELECT summary FROM conversation_summary WHERE id=1").fetchone()
        prior_summary = prior["summary"] if prior else ""

        prompt = (
            (f"Existing summary of earlier conversation:\n{prior_summary}\n\n" if prior_summary else "")
            + f"New conversation excerpt to fold in:\n{transcript}\n\n"
            "Rewrite this into ONE updated, compact rolling summary covering the whole "
            "conversation so far: ongoing topics/projects, decisions made, stated "
            "preferences, and any unfinished threads. Bullet points, under 250 words. "
            "Do not repeat raw dialogue — capture what matters for continuing later."
        )
        new_summary = _ai(prompt, timeout=50) or prior_summary or transcript[:_SUMMARY_CAP]
        new_summary = new_summary[:_SUMMARY_CAP]

        c.execute(
            "INSERT INTO conversation_summary (id, summary, updated_at) VALUES (1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
            (new_summary, datetime.now().isoformat())
        )
        ids = [r["id"] for r in oldest]
        c.executemany("DELETE FROM conversation_turns WHERE id=?", [(i,) for i in ids])
        c.commit()
        c.close()
        return f"Consolidated {len(ids)} older turns into the rolling summary."
    except Exception as e:
        return f"Consolidation error: {e}"


def consolidate_now() -> str:
    """User-facing: force consolidation immediately, regardless of threshold."""
    global _KEEP_RECENT, _CHUNK_SIZE
    try:
        c = _db()
        total = c.execute("SELECT COUNT(*) n FROM conversation_turns").fetchone()["n"]
        c.close()
        if total <= 1:
            return "Nothing to consolidate yet — conversation history is still short."
        # Temporarily force the chunk to cover everything but the most recent few turns
        keep = min(_KEEP_RECENT, max(0, total - 1))
        chunk = total - keep
        if chunk <= 0:
            return "Conversation history is already within the keep-recent window — nothing to consolidate."
        orig_keep, orig_chunk = _KEEP_RECENT, _CHUNK_SIZE
        _KEEP_RECENT, _CHUNK_SIZE = keep, chunk
        try:
            result = consolidate_conversation()
        finally:
            _KEEP_RECENT, _CHUNK_SIZE = orig_keep, orig_chunk
        return result or "Nothing needed consolidating."
    except Exception as e:
        return f"Consolidation error: {e}"


def conversation_context_for_llm() -> str:
    """The rolling conversation summary, formatted for injection into the system prompt."""
    try:
        c = _db()
        row = c.execute("SELECT summary, updated_at FROM conversation_summary WHERE id=1").fetchone()
        c.close()
        if not row or not row["summary"]:
            return ""
        return (
            "[EARLIER CONVERSATION SUMMARY — for continuity across sessions]\n"
            f"{row['summary']}\n"
            "[END SUMMARY — more recent messages follow in full below]"
        )
    except Exception:
        return ""


def conversation_history(limit: int = 20) -> str:
    """Human-readable transcript of recent turns — 'what have we talked about'."""
    turns = get_recent_turns(limit)
    if not turns:
        return "No conversation history recorded yet."
    lines = [f"Conversation History (last {len(turns)} turns):", ""]
    for t in turns:
        who = "You" if t["role"] == "user" else "Jarvis"
        lines.append(f"  {who}: {t['content'][:200]}")
    try:
        c = _db()
        row = c.execute("SELECT updated_at FROM conversation_summary WHERE id=1").fetchone()
        c.close()
        if row:
            lines += ["", f"(Older history consolidated as of {row['updated_at'][:16].replace('T',' ')} "
                          f"— say 'consolidate memory' to force an update)"]
    except Exception:
        pass
    return "\n".join(lines)


def is_critique(msg: str) -> bool:
    """Pure pattern check, no side effects — safe to call for routing decisions."""
    if not msg:
        return False
    low = msg.lower()
    return any(re.search(p, low) for p in _CRITIQUE_PATTERNS)


def detect_and_log_critique(new_user_msg: str) -> bool:
    """
    Check whether the user's new message is correcting the previous exchange.
    If so, save it as a standing note (category='correction') so it informs
    every future prompt — this is how Jarvis 'learns' from being corrected
    without the user needing to say 'remember that'.
    """
    if not is_critique(new_user_msg):
        return False
    try:
        c = _db()
        rows = c.execute(
            "SELECT role, content FROM conversation_turns ORDER BY id DESC LIMIT 2"
        ).fetchall()
        c.close()
        prev_user  = next((r["content"] for r in rows if r["role"] == "user"), "")
        prev_reply = next((r["content"] for r in rows if r["role"] == "assistant"), "")
        note = (
            f"User corrected a previous response. "
            f"Original ask: \"{prev_user[:150]}\" | "
            f"Jarvis replied: \"{prev_reply[:150]}\" | "
            f"Correction: \"{new_user_msg[:200]}\""
        )
        save_note(note, category="correction")
        return True
    except Exception:
        return False


# ── Passive learning from ANY message ─────────────────────────────────────────
# The user shouldn't have to say "remember" for Jarvis to learn who they are.
# Runs in a background thread after every exchange (never blocks a reply).

_LEARN_HINT = re.compile(
    r"\b(?:i|i'm|im|i've|ive|my|mine|me|we|our|call me|i like|i love|i hate|"
    r"i prefer|i want|i need|i work|i live|i play|i use|don'?t ever|always|never)\b",
    re.I)

_LEARN_PROMPT = """From this user message, extract durable personal facts worth \
remembering long-term: identity, preferences, dislikes, possessions, goals, people, \
routines, standing instructions.

Message: "{msg}"

Rules:
- Output ONLY a JSON array of short third-person facts, e.g. ["prefers swing trades over day trades"]
- Max 2 facts. Most messages contain NONE — then output []
- NOT durable (output [] for these): one-off commands/questions, market chatter,
  anything about a specific trade or ticker price, temporary states ("I'm tired")
"""


def learn_from_message(user_msg: str):
    """Mine lasting facts from any prompt; dedupe; store as auto_learned notes."""
    try:
        msg = (user_msg or "").strip()
        if not (12 <= len(msg) <= 600):
            return
        if not _LEARN_HINT.search(msg):
            return
        if is_critique(msg):
            return  # correction capture already handles these
        raw = _ai(_LEARN_PROMPT.format(msg=msg.replace('"', "'")),
                  system="You extract facts as strict JSON arrays. No prose.")
        m = re.search(r'\[.*\]', raw or "", re.S)
        if not m:
            return
        facts = json.loads(m.group(0))
        if not isinstance(facts, list):
            return
        c = _db()
        for fact in facts[:2]:
            fact = str(fact).strip()[:300]
            if len(fact) < 8:
                continue
            # Dedupe: skip if a very similar note already exists
            dup = c.execute(
                "SELECT COUNT(*) n FROM user_notes WHERE lower(note) LIKE lower(?)",
                (f"%{fact[:60]}%",)).fetchone()["n"]
            if dup:
                continue
            c.execute("INSERT INTO user_notes (ts, category, note) VALUES (?,?,?)",
                      (datetime.now().isoformat(), "auto_learned", fact))
        c.commit()
        c.close()
    except Exception:
        pass  # background learning must never break anything


def learned_command_examples(min_count: int = 2, max_chars: int = 90) -> dict:
    """
    For each tool Jarvis has actually been asked to run, surface the user's OWN
    most common real phrasing instead of a canned example — this is how the
    Commands tab 'refines' itself as Jarvis learns the user's vernacular.
    Returns {tool_name: {"phrase": str, "count": int}}.
    """
    try:
        c = _db()
        rows = c.execute(
            "SELECT user_query, tool_used FROM interactions "
            "WHERE tool_used != '' AND tool_used != 'llm' "
            "ORDER BY ts DESC LIMIT 500"
        ).fetchall()
        c.close()
    except Exception:
        return {}

    # Bare confirmations must NEVER become learned tool phrasings — a "yes"
    # that once confirmed a watchlist_add would teach the semantic matcher
    # that "yes" MEANS watchlist_add (real self-poisoning incident 2026-07-02).
    _NOT_PHRASES = re.compile(
        r"^(?:yes|yeah|yep|yup|y|no|nope|nah|ok(?:ay)?|sure|do it|go ahead|"
        r"proceed|confirm|cancel|thanks?|please|that one|\d+)[\s!.,]*$", re.I)

    per_tool: dict = {}
    for row in rows:
        q = (row["user_query"] or "").strip()
        if not q or len(q) > max_chars * 2 or len(q) < 4 or _NOT_PHRASES.match(q):
            continue
        for t in (row["tool_used"] or "").split(","):
            t = t.strip()
            if not t:
                continue
            bucket = per_tool.setdefault(t, {})
            key = q.lower()
            if key not in bucket:
                bucket[key] = {"phrase": q[:max_chars], "count": 0}
            bucket[key]["count"] += 1

    result = {}
    for tool, phrases in per_tool.items():
        best = max(phrases.values(), key=lambda v: v["count"])
        if best["count"] >= min_count:
            result[tool] = best
    return result


# ── Analytics ─────────────────────────────────────────────────────────────────────

def get_preferences() -> dict:
    """Build a rich preference profile from behavioral data."""
    try:
        c = _db()

        # Top tools used (last 30 days)
        rows = c.execute(
            """SELECT tool_used, COUNT(*) as cnt
               FROM interactions
               WHERE ts > datetime('now','-30 days') AND tool_used != ''
               GROUP BY tool_used ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()
        top_tools = [(r["tool_used"], r["cnt"]) for r in rows]

        # Most mentioned tickers (last 30 days)
        rows = c.execute(
            "SELECT user_query FROM interactions WHERE ts > datetime('now','-30 days')"
        ).fetchall()
        ticker_counts: dict[str, int] = {}
        for row in rows:
            q = (row["user_query"] or "").upper()
            for tok in re.findall(r"\b[A-Z]{2,5}\b", q):
                if tok not in _COMMON:
                    ticker_counts[tok] = ticker_counts.get(tok, 0) + 1
        fav_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:8]

        # Trade performance summary
        perf = c.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
                      AVG(pnl) avg_pnl, SUM(pnl) total_pnl
               FROM trade_outcomes"""
        ).fetchone()

        # Peak activity hours
        hours = c.execute(
            """SELECT strftime('%H',ts) hr, COUNT(*) cnt
               FROM interactions GROUP BY hr ORDER BY cnt DESC LIMIT 3"""
        ).fetchall()
        active_hours = [f"{r['hr']}:00" for r in hours]

        # Explicit preferences
        prefs = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM preferences").fetchall()}

        # Recent user notes
        notes = [r["note"] for r in
                 c.execute("SELECT note FROM user_notes ORDER BY ts DESC LIMIT 8").fetchall()]

        c.close()
        return {
            "top_tools":     top_tools,
            "fav_tickers":   fav_tickers,
            "total_trades":  int(perf["total"] or 0) if perf else 0,
            "wins":          int(perf["wins"] or 0) if perf else 0,
            "avg_pnl":       float(perf["avg_pnl"] or 0) if perf else 0.0,
            "total_pnl":     float(perf["total_pnl"] or 0) if perf else 0.0,
            "active_hours":  active_hours,
            "prefs":         prefs,
            "notes":         notes,
        }
    except Exception as e:
        return {"error": str(e)}


def context_for_llm() -> str:
    """
    Build a context block to prepend to every Ollama system prompt.
    This is what gives Jarvis 'memory' without retraining any model.
    """
    try:
        p = get_preferences()
        if "error" in p:
            return ""

        lines = ["[JARVIS LEARNED USER CONTEXT]"]

        if p.get("fav_tickers"):
            tickers = ", ".join(t for t, _ in p["fav_tickers"][:5])
            lines.append(f"User's most-discussed stocks: {tickers}")

        if p.get("top_tools"):
            caps = ", ".join(f"{t}({n}x)" for t, n in p["top_tools"][:4])
            lines.append(f"Most-used Jarvis capabilities: {caps}")

        if p.get("total_trades", 0) > 0:
            total = p["total_trades"]
            wins  = p["wins"]
            wr    = (wins / total * 100) if total > 0 else 0
            lines.append(
                f"Trading history: {total} trades tracked | "
                f"win rate {wr:.0f}% | avg P&L ${p['avg_pnl']:+.2f} | "
                f"total ${p['total_pnl']:+.2f}"
            )

        for k, v in (p.get("prefs") or {}).items():
            lines.append(f"User preference — {k}: {v}")

        for note in (p.get("notes") or []):
            lines.append(f"User note: {note}")

        if p.get("active_hours"):
            lines.append(f"Typically active at: {', '.join(p['active_hours'])}")

        lines.append("[END USER CONTEXT]")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Memory summary (user-facing) ──────────────────────────────────────────────────

def memory_summary() -> str:
    """What has Jarvis learned about this user? Show the full profile."""
    try:
        c  = _db()
        total_int = c.execute("SELECT COUNT(*) n FROM interactions").fetchone()["n"]
        last_row  = c.execute(
            "SELECT ts FROM interactions ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        last_ts   = last_row["ts"][:16] if last_row else "Never"
        total_tr  = c.execute("SELECT COUNT(*) n FROM trade_outcomes").fetchone()["n"]
        c.close()

        p = get_preferences()

        lines = [
            "JARVIS Memory & Self-Learning System",
            f"Database: {_DB}",
            f"Updated:  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"  Interactions logged: {total_int:,} (last: {last_ts})",
            f"  Trades tracked:      {total_tr}",
            "",
            "  WHAT JARVIS HAS LEARNED ABOUT YOU:",
        ]

        if p.get("fav_tickers"):
            lines.append("  Favorite stocks (30 days):")
            for sym, cnt in p["fav_tickers"][:6]:
                lines.append(f"    {sym:<8} mentioned {cnt}× in your requests")
        else:
            lines.append("  (Still learning your preferences — use Jarvis more!)")

        if p.get("top_tools"):
            lines += ["", "  Most-used capabilities:"]
            for tool, cnt in p["top_tools"][:5]:
                lines.append(f"    {tool:<25} {cnt:>3} times")

        if p.get("total_trades", 0) > 0:
            total = p["total_trades"]
            wins  = p["wins"]
            lines += [
                "",
                "  Trading performance tracked:",
                f"    Win rate:  {wins}/{total} ({wins/total*100:.0f}%)",
                f"    Avg P&L:   ${p['avg_pnl']:+.2f} per trade",
                f"    Total P&L: ${p['total_pnl']:+.2f}",
            ]

        if p.get("notes"):
            lines += ["", "  Your notes:"]
            for n in p["notes"]:
                lines.append(f"    • {n}")

        if p.get("active_hours"):
            lines += ["", f"  Peak activity: {', '.join(p['active_hours'])}"]

        lines += [
            "",
            "  Jarvis learns from every request — the more you use it,",
            "  the more personalized and accurate it becomes.",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Memory system error: {e}"


def remember(note: str) -> str:
    """User-facing: 'Jarvis, remember that ...' handler."""
    save_note(note.strip(), category="user_instruction")
    return f"Got it. I've saved that to memory:\n  \"{note.strip()[:120]}\"\n\nIt will inform all future responses."


def forget(keyword: str) -> str:
    """Delete notes containing a keyword."""
    try:
        c   = _db()
        cur = c.execute(
            "DELETE FROM user_notes WHERE lower(note) LIKE lower(?)",
            (f"%{keyword}%",)
        )
        deleted = cur.rowcount
        c.commit()
        c.close()
        return f"Removed {deleted} memory note(s) containing '{keyword}'."
    except Exception as e:
        return f"Memory delete error: {e}"


# ── Offline system status ─────────────────────────────────────────────────────────

def jarvis_offline_status() -> str:
    """
    Full system health check — shows what works without Anthropic/Claude.
    Jarvis is designed to operate 100% on your local hardware.
    """
    lines = [
        "JARVIS — Decentralized System Status",
        "═" * 50,
        f"Checked: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Ollama (local AI)
    try:
        import requests as _req
        r = _req.get("http://localhost:11434/api/tags", timeout=3)
        if r.ok:
            models = [m.get("name", "?") for m in r.json().get("models", [])]
            lines.append(f"  ✅ Ollama AI:       ONLINE")
            lines.append(f"     Models loaded:  {', '.join(models[:4]) or '(none)'}")
            if not models:
                lines.append(f"     Run: ollama pull {_OLLAMA_MODEL}")
        else:
            lines.append("  ⚠️  Ollama AI:       OFFLINE (run: ollama serve)")
    except Exception:
        lines.append("  ❌ Ollama AI:       NOT INSTALLED")
        lines.append(f"     Install at: https://ollama.com  then: ollama pull {_OLLAMA_MODEL}")

    # Alpaca
    try:
        import tools.trading as TRD
        clock = TRD._api("GET", "/v2/clock")
        state = "OPEN" if clock.get("is_open") else "CLOSED"
        lines.append(f"  ✅ Alpaca Trading:  CONNECTED (market {state})")
    except Exception as e:
        lines.append(f"  ⚠️  Alpaca Trading:  {str(e)[:60]}")

    # Local memory DB
    if _DB.exists():
        kb = _DB.stat().st_size / 1024
        total_int = _db().execute("SELECT COUNT(*) n FROM interactions").fetchone()["n"]
        lines.append(f"  ✅ Local Memory:    ACTIVE ({kb:.1f} KB | {total_int:,} interactions logged)")
    else:
        lines.append("  ℹ️  Local Memory:    Empty (will initialize on first use)")

    # Trade files
    trade_dir = Path.home() / "Documents" / "JARVIS" / "trading"
    report    = trade_dir / "trade_report.txt"
    if report.exists():
        age_m = (datetime.now().timestamp() - report.stat().st_mtime) / 60
        lines.append(f"  ✅ Trade Report:    LIVE (last updated {age_m:.0f}m ago)")
    else:
        lines.append("  ℹ️  Trade Report:    Not yet created (starts when monitor runs)")

    # Web server
    lines += [
        "",
        "  HOW TO USE JARVIS WITHOUT ANTHROPIC TOKENS:",
        "  ─────────────────────────────────────────────",
        "  1. Open Command Prompt or PowerShell",
        "  2. Run:  python server.py  (from the jarvis4 folder)",
        "  3. Open: http://localhost:5005/app  in your browser",
        f"  4. Talk to Jarvis directly — all AI runs via Ollama ({_OLLAMA_MODEL})",
        "     No internet needed for the AI brain itself.",
        "     Trading data + news still need internet (Alpaca, RSS feeds).",
        "",
        "  Jarvis runs 100% on your hardware.",
        "  Zero Anthropic dependency. Zero cloud AI needed.",
    ]

    return "\n".join(lines)
