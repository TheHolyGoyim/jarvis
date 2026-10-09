"""
daily_brief.py — JARVIS Autonomous Daily Market Intelligence Cycle

Nobody should have to type "auto hunt". A scheduler thread inside server.py
builds two intelligence products every trading day, unprompted:

  MORNING BRIEF  (~8:00 AM ET, or catch-up whenever the PC comes on)
    market regime, sector heat, VIX term structure, Fear & Greed, geopolitical
    themes, trending social/WSB names, a full universe conviction hunt, live
    web research on the dominant macro theme, yesterday's carry-forward
    watchlist — synthesized by the local LLM into a written game plan.

  EVENING REVIEW  (~4:10 PM ET)
    what closed today and why, what the monitor did, open risk, a fresh
    post-close hunt → tomorrow's watchlist — synthesized into lessons +
    a plan for tomorrow.

Everything persists to ~/Documents/JARVIS/trading/daily_briefs/YYYY-MM-DD.json
(one file per day, kept forever — Jarvis can compare today to any past day),
and market_intel_context() injects a compact digest into EVERY system prompt,
so Jarvis already knows today's plan when you talk to him.
"""

import os, json, re, threading, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BRIEF_DIR = Path.home() / "Documents" / "JARVIS" / "trading" / "daily_briefs"
_BRIEF_DIR.mkdir(parents=True, exist_ok=True)

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

_scheduler_thread  = None
_scheduler_running = False
_build_lock        = threading.Lock()


# ── Local AI ────────────────────────────────────────────────────────────────────
def _ai(prompt: str, system: str, timeout: int = 90) -> str:
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


# ── Storage ─────────────────────────────────────────────────────────────────────
def _day_file(day: str = "") -> Path:
    day = day or datetime.now().strftime("%Y-%m-%d")
    return _BRIEF_DIR / f"{day}.json"


def _load_day(day: str = "") -> dict:
    f = _day_file(day)
    try:
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_day(data: dict, day: str = ""):
    try:
        _day_file(day).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _latest_day_with(part: str):
    """Most recent (day, data) that contains the given part ('morning'/'evening')."""
    try:
        for f in sorted(_BRIEF_DIR.glob("*.json"), reverse=True):
            data = _load_day(f.stem)
            if data.get(part):
                return f.stem, data
    except Exception:
        pass
    return None, {}


# ── Section gatherers (each best-effort — a dead source never kills the brief) ──
def _grab(fn, *a, **kw) -> str:
    try:
        return str(fn(*a, **kw))
    except Exception as e:
        return f"(unavailable: {e})"


def _top_picks_from_hunt(hunt_text: str) -> list[dict]:
    """Parse 'auto_hunt' output into structured top picks."""
    picks = []
    for m in re.finditer(
        r'#(\d)\s+([A-Z]{1,5})\s+(\d+)/100\s+\[[█░]+\]\s+\$\s*([\d,.]+)', hunt_text
    ):
        picks.append({
            "rank":   int(m.group(1)),
            "symbol": m.group(2),
            "score":  int(m.group(3)),
            "price":  float(m.group(4).replace(",", "")),
        })
    return picks


# ══════════════════════════════════════════════════════════════════════════════
# MORNING BRIEF
# ══════════════════════════════════════════════════════════════════════════════

def build_morning_brief(force: bool = False) -> str:
    """Gather all pre-market intelligence, synthesize a game plan, persist it."""
    day = datetime.now().strftime("%Y-%m-%d")
    with _build_lock:
        data = _load_day(day)
        if data.get("morning") and not force:
            return data["morning"].get("text", "Morning brief already built today.")

        import tools.conviction as CVN

        sections = {}
        sections["regime"]  = _grab(CVN.market_regime)
        sections["sectors"] = _grab(CVN.sector_heat)
        try:
            import tools.flow_intel as FLOW
            sections["vix"] = _grab(FLOW.vix_term_structure)
        except Exception:
            sections["vix"] = "(flow intel unavailable)"
        try:
            fg_pts, fg_v = CVN._fear_greed_signal()
            sections["fear_greed"] = fg_v
        except Exception:
            sections["fear_greed"] = "(unavailable)"

        geo_themes = []
        try:
            geo = CVN._geo_brief_themes()
            geo_themes = geo.get("themes", [])
            sections["geo"] = ("Themes: " + ", ".join(geo_themes) + "\n"
                               + geo.get("headline_context", ""))
        except Exception as e:
            sections["geo"] = f"(unavailable: {e})"

        try:
            import tools.social_intel as SOC
            sections["social"] = _grab(SOC.trending_social_now)
            sections["wsb"]    = _grab(SOC.reddit_wsb_hot)
        except Exception:
            sections["social"] = sections["wsb"] = "(social intel unavailable)"

        # Live internet research on the dominant macro theme — real current
        # info from the web, not just feeds Jarvis already polls.
        sections["web_research"] = "(no theme to research)"
        if geo_themes:
            try:
                import tools.intel as INTEL
                q = f"{geo_themes[0]} stock market impact {datetime.now().strftime('%B %Y')}"
                sections["web_research"] = f"Query: {q}\n" + _grab(INTEL.web_research, q)
            except Exception as e:
                sections["web_research"] = f"(unavailable: {e})"

        # The full universe hunt — rankings only, execution stays with the
        # 9:30 runner / post-close re-hunt which have their own guards.
        hunt_text = _grab(CVN.auto_hunt, auto_trade=False)
        sections["hunt"]  = hunt_text
        top_picks         = _top_picks_from_hunt(hunt_text)

        try:
            import tools.trading as TRD
            sections["budget"] = _grab(TRD.trading_budget_status)
        except Exception:
            sections["budget"] = "(trading unavailable)"

        # Continuity: what did yesterday's evening review tell us to watch?
        carry = ""
        prev_day, prev = _latest_day_with("evening")
        if prev_day and prev_day < day:
            ev = prev.get("evening", {})
            wl = ev.get("tomorrow_watchlist", [])
            if wl:
                carry = f"Carried from {prev_day} evening review — watchlist: " + ", ".join(wl)
                if ev.get("synthesis"):
                    carry += "\nYesterday's takeaways:\n" + ev["synthesis"][:600]
        sections["carry_forward"] = carry or "(no prior evening review)"

        # Political intelligence: overnight events, officials speaking today,
        # geo risk score, top politically-driven opportunities
        try:
            import tools.political_intel as PI
            sections["political"] = _grab(PI.political_briefing)
        except Exception as e:
            sections["political"] = f"(political intel unavailable: {e})"

        # LLM synthesis → the actual game plan
        raw_block = "\n\n".join(
            f"### {k.upper()}\n{v[:1500]}" for k, v in sections.items()
        )
        synthesis = _ai(
            f"Today is {datetime.now().strftime('%A %Y-%m-%d')}, before NYSE open.\n"
            f"Here is every piece of market intelligence gathered this morning:\n\n"
            f"{raw_block}\n\n"
            f"Write today's trading game plan in under 15 lines:\n"
            f"1. REGIME — one line\n"
            f"2. TOP 3 SETUPS — ticker, conviction score, one-line why (from the hunt rankings)\n"
            f"3. MACRO WATCH — the one theme/event most likely to move things today\n"
            f"4. RISK — what would invalidate the plan\n"
            f"5. PLAN — given the budget status, what should be done today\n"
            f"Be specific and direct. No preamble.",
            system=("You are JARVIS's overnight analyst. You turn raw multi-source market "
                    "intelligence into one sharp, actionable morning game plan."),
        ) or "(LLM offline — raw sections below stand on their own)"

        # Keep every line short (~60 chars) and sections clearly headed —
        # this renders in a phone-width chat bubble, not a terminal.
        rule = "━" * 30
        text_lines = [
            f"🌅 MORNING BRIEF — {datetime.now().strftime('%a %b %d, %H:%M')}",
            rule, "",
            "🎯 GAME PLAN",
            synthesis, "",
            "📊 TOP PICKS",
        ]
        for p in top_picks:
            text_lines.append(f"  #{p['rank']} {p['symbol']}  {p['score']}/100  ${p['price']:,.2f}")
        if not top_picks:
            text_lines.append("  (no picks parsed — say 'auto hunt' for the full scan)")
        text_lines += ["", "🏛 POLITICAL INTEL"]
        pol_lines = [l for l in sections.get("political", "").split("\n") if l.strip()]
        text_lines += [f"  {l[:64]}" for l in pol_lines[:10]] or ["  (unavailable)"]
        text_lines += ["", "🧭 CONTEXT"]
        labels = {"regime": "Regime", "fear_greed": "Fear/Greed",
                  "vix": "VIX", "carry_forward": "Yesterday"}
        for key, label in labels.items():
            first = [l.strip() for l in sections.get(key, "").split("\n") if l.strip()]
            if not first:
                continue
            text_lines.append(f"  • {label}: {first[0][:60]}")
            text_lines += [f"    {l[:60]}" for l in first[1:3]]
        text = "\n".join(text_lines)

        data["morning"] = {
            "built_at":  datetime.now().isoformat(),
            "synthesis": synthesis,
            "top_picks": top_picks,
            "sections":  sections,
            "text":      text,
        }
        _save_day(data, day)

        try:
            import tools.jarvis_memory as MEM
            MEM.log_interaction(f"morning_brief_{day}", "daily_brief")
        except Exception:
            pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# EVENING REVIEW
# ══════════════════════════════════════════════════════════════════════════════

def build_evening_review(force: bool = False) -> str:
    """Digest the trading day after the close and prepare tomorrow's watchlist."""
    day = datetime.now().strftime("%Y-%m-%d")
    with _build_lock:
        data = _load_day(day)
        if data.get("evening") and not force:
            return data["evening"].get("text", "Evening review already built today.")

        # What actually happened today (journal is ground truth)
        closed_today, adjustments, open_pos = [], [], []
        try:
            import tools.trade_monitor as MON
            j = MON._load_journal()
            for t in j.get("closed_trades", []):
                if str(t.get("exit_time", "")).startswith(day):
                    closed_today.append(t)
            for sym, pos in j.get("positions", {}).items():
                open_pos.append(pos)
                for adj in pos.get("adjustments", []):
                    if str(adj.get("time", "")).startswith(day):
                        adjustments.append(f"{sym}: {adj.get('action')} — {adj.get('detail','')[:80]}")
        except Exception:
            pass

        day_summary = []
        for t in closed_today:
            day_summary.append(
                f"{t.get('result','?'):<4} {t.get('symbol','?'):<6} "
                f"${t.get('entry_price',0):.2f}→${t.get('exit_price',0):.2f}  "
                f"P&L ${t.get('pnl',0):+.2f} ({t.get('pnl_pct',0):+.1f}%)  {t.get('reason','')}"
            )
        for p in open_pos:
            day_summary.append(
                f"OPEN {p.get('symbol','?'):<6} entry ${p.get('entry_price',0):.2f} "
                f"×{p.get('qty',0)}  conviction {p.get('conviction_score',0)}/100"
            )

        import tools.conviction as CVN
        try:
            import tools.trading as TRD
            budget = _grab(TRD.trading_budget_status)
        except Exception:
            budget = "(unavailable)"

        # Fresh post-close hunt → tomorrow's watchlist
        hunt_text = _grab(CVN.auto_hunt, auto_trade=False)
        top_picks = _top_picks_from_hunt(hunt_text)
        watchlist = [p["symbol"] for p in top_picks[:5]]
        for p in open_pos:  # never lose sight of what we hold
            if p.get("symbol") and p["symbol"] not in watchlist:
                watchlist.append(p["symbol"])

        morning = data.get("morning", {})
        synthesis = _ai(
            f"Today is {datetime.now().strftime('%A %Y-%m-%d')}, after NYSE close.\n\n"
            f"THIS MORNING'S PLAN WAS:\n{morning.get('synthesis','(no morning brief)')[:1200]}\n\n"
            f"WHAT ACTUALLY HAPPENED TODAY:\n" + ("\n".join(day_summary) or "(no trades)") + "\n\n"
            f"MONITOR ACTIONS TODAY:\n" + ("\n".join(adjustments[:12]) or "(none)") + "\n\n"
            f"BUDGET NOW:\n{budget[:600]}\n\n"
            f"POST-CLOSE HUNT RANKINGS (tomorrow's candidates):\n{hunt_text[:1200]}\n\n"
            f"Write the evening review in under 12 lines:\n"
            f"1. TODAY — what happened vs the plan, one or two lines\n"
            f"2. LESSON — the single most useful takeaway (be honest about mistakes)\n"
            f"3. TOMORROW — top 3 candidates with scores and one-line theses\n"
            f"4. OVERNIGHT RISK — what to check first at the open\n"
            f"No preamble.",
            system=("You are JARVIS's end-of-day reviewer. You compare the plan to what "
                    "actually happened, extract lessons, and set up tomorrow."),
        ) or "(LLM offline — raw data below)"

        rule = "━" * 30
        text_lines = [
            f"🌇 EVENING REVIEW — {datetime.now().strftime('%a %b %d, %H:%M')}",
            rule, "",
            synthesis, "",
            "📋 TODAY'S TRADES",
        ] + (["  " + s for s in day_summary] or ["  (none)"]) + [
            "",
            "👀 TOMORROW'S WATCHLIST",
            "  " + (", ".join(watchlist) or "(none)"),
        ]
        text = "\n".join(text_lines)

        data["evening"] = {
            "built_at":           datetime.now().isoformat(),
            "synthesis":          synthesis,
            "closed_today":       closed_today,
            "adjustments":        adjustments,
            "tomorrow_watchlist": watchlist,
            "hunt":               hunt_text,
            "text":               text,
        }
        _save_day(data, day)

        # Seed the live tape stream with tomorrow's names overnight
        try:
            import tools.trade_stream as TAPE
            TAPE.update_watchlist(watchlist)
        except Exception:
            pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# RETRIEVAL
# ══════════════════════════════════════════════════════════════════════════════

def show_daily_brief() -> str:
    """Latest morning brief (today's, or the most recent one, clearly dated)."""
    day, data = _latest_day_with("morning")
    if not day:
        # Never make the user ask twice — if no brief exists at all, build one
        # right now (full scan + synthesis, takes a minute) instead of
        # deflecting to a different command.
        return build_morning_brief(force=True)
    text = data["morning"].get("text", "")
    if day != datetime.now().strftime("%Y-%m-%d"):
        text = f"(Most recent brief is from {day} — today's hasn't built yet.)\n\n" + text
    return text


def show_evening_review() -> str:
    day, data = _latest_day_with("evening")
    if not day:
        # Same on-demand rule as the morning brief: asked = delivered.
        return build_evening_review(force=True)
    text = data["evening"].get("text", "")
    if day != datetime.now().strftime("%Y-%m-%d"):
        text = f"(Most recent review is from {day}.)\n\n" + text
    return text


def market_intel_context() -> str:
    """
    Compact digest of the latest brief/review for injection into EVERY system
    prompt — this is how Jarvis 'already knows' the day's plan in conversation.
    Kept under ~900 chars so it never crowds out the rest of the prompt.
    """
    parts = []
    m_day, m_data = _latest_day_with("morning")
    if m_day:
        m = m_data["morning"]
        picks = ", ".join(f"{p['symbol']} {p['score']}/100" for p in m.get("top_picks", [])[:3])
        parts.append(f"[MARKET BRIEF {m_day}] Top setups: {picks or 'none parsed'}")
        syn = m.get("synthesis", "")
        if syn and not syn.startswith("(LLM offline"):
            parts.append(syn[:450])
    e_day, e_data = _latest_day_with("evening")
    if e_day:
        e = e_data["evening"]
        wl = ", ".join(e.get("tomorrow_watchlist", [])[:6])
        if wl:
            parts.append(f"[EVENING REVIEW {e_day}] Watchlist: {wl}")
    if not parts:
        return ""
    return ("CURRENT MARKET INTELLIGENCE (auto-gathered daily — refer to this "
            "when the user asks about the market, the plan, or what to trade):\n"
            + "\n".join(parts))[:1200]


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER — runs inside server.py, no Task Scheduler setup needed
# ══════════════════════════════════════════════════════════════════════════════

def _now_et() -> datetime:
    """Eastern time via Alpaca's clock when available, UTC-4/5 heuristic if not."""
    try:
        import tools.trading as TRD
        ts = TRD._api("GET", "/v2/clock").get("timestamp", "")
        if ts:
            return datetime.fromisoformat(ts[:26] + ts[26:].replace("Z", "+00:00")
                                          if "Z" in ts else ts)
    except Exception:
        pass
    # Fallback: assume EDT (UTC-4); worst case the brief builds an hour early/late
    return datetime.now(timezone.utc) - timedelta(hours=4)


def _scheduler_loop():
    global _scheduler_running
    while _scheduler_running:
        try:
            et = _now_et()
            if et.weekday() < 5:  # Mon–Fri
                day     = datetime.now().strftime("%Y-%m-%d")
                data    = _load_day(day)
                minutes = et.hour * 60 + et.minute
                # Morning brief: from 7:30 ET; catch-up until 15:30 if PC was off
                if 450 <= minutes < 930 and not data.get("morning"):
                    build_morning_brief()
                # Evening review: from 16:10 ET
                if minutes >= 970 and not data.get("evening"):
                    build_evening_review()
        except Exception:
            traceback.print_exc()
        time.sleep(300)


def start_daily_scheduler() -> str:
    global _scheduler_thread, _scheduler_running
    if _scheduler_running and _scheduler_thread and _scheduler_thread.is_alive():
        return "Daily intelligence scheduler already running."
    _scheduler_running = True
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, daemon=True, name="jarvis-daily-brief"
    )
    _scheduler_thread.start()
    return ("Daily intelligence scheduler started — morning brief ~8AM ET "
            "(catch-up if the PC was off), evening review ~4:10PM ET.")


def scheduler_status() -> str:
    alive = bool(_scheduler_thread and _scheduler_thread.is_alive())
    m_day, _ = _latest_day_with("morning")
    e_day, _ = _latest_day_with("evening")
    return "\n".join([
        f"Daily Intelligence Cycle: {'RUNNING' if alive else 'STOPPED'}",
        f"  Latest morning brief:  {m_day or 'never'}",
        f"  Latest evening review: {e_day or 'never'}",
        f"  Archive: {_BRIEF_DIR}  ({len(list(_BRIEF_DIR.glob('*.json')))} days kept)",
    ])
