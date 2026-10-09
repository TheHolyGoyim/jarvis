"""
tools/goal_engine.py — goal-based adaptive trading (Feature 1).

The user states any financial goal with a deadline in plain English:
    "Turn $100,000 into $150,000 by end of July"
    "Make $500 profit this week"
    "Grow the account 20% this month"
    "I need $10,000 by Friday"

The engine then:
  1. Computes required gain, required $/day and %/day against TRADING days left
  2. Maps required daily return to a risk profile and applies it:
       < 0.5%/day  → conservative
       0.5-1.5%    → moderate
       1.5-3%      → aggressive
       3-5%        → high_risk     (NEVER auto-selected — suggestion only)
       > 5%        → speculative   (NEVER auto-selected — suggestion only)
     HARD CEILING (user rule): automatic selection and automatic escalation
     stop at AGGRESSIVE. high_risk/speculative only on explicit instruction.
  3. Tracks pace vs. required every check cycle; when behind pace it
     escalates ONE tier (max aggressive) and warns:
       "You are behind pace. Escalating to <profile> profile to catch up.
        Say 'hold profile' to prevent this."
     'hold profile' latches the current profile against auto-changes.
  4. Notifies immediately on goal completion and asks what's next.

State persists in store.py key 'trading_goal'. The Markets tab reads
/goal (server.py) for the live tracker panel.
"""

import re, time, threading
from datetime import datetime, date, timedelta
from tools.store import get, put

_KEY = "trading_goal"
_state = {"running": False, "last_check": 0.0}

# Profile ladder + auto ceiling come from risk_params (single source of truth)
def _rp():
    import tools.risk_params as RP
    return RP


def _portfolio_value() -> float:
    try:
        import tools.account_sync as SYNC
        return SYNC.portfolio_value() or SYNC.equity()
    except Exception:
        return 0.0


def _push_alert(text: str):
    try:
        import tools.trade_monitor as MON
        MON._push_user_alert(text)
    except Exception:
        pass


# ── Deadline / date parsing ────────────────────────────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
_WEEKDAYS = {d.lower(): i for i, d in enumerate(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])}


def _parse_deadline(text: str) -> date:
    """Best-effort natural-language deadline. Defaults to +30 days."""
    t = text.lower()
    today = date.today()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)                       # ISO date
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"by\s+(?:end\s+of\s+)?([a-z]+)\s+(\d{1,2})", t)     # "by July 25"
    if m and m.group(1) in _MONTHS:
        mo, dy = _MONTHS[m.group(1)], int(m.group(2))
        yr = today.year + (1 if (mo, dy) < (today.month, today.day) else 0)
        return date(yr, mo, dy)
    m = re.search(r"end\s+of\s+([a-z]+)", t)                           # "end of July"
    if m and m.group(1) in _MONTHS:
        mo = _MONTHS[m.group(1)]
        yr = today.year + (1 if mo < today.month else 0)
        nxt = date(yr + (1 if mo == 12 else 0), 1 if mo == 12 else mo + 1, 1)
        return nxt - timedelta(days=1)
    for wd, idx in _WEEKDAYS.items():                                  # "by Friday"
        if re.search(rf"\b(?:by|until|before)\s+{wd}\b", t):
            delta = (idx - today.weekday()) % 7 or 7
            return today + timedelta(days=delta)
    if "this week" in t or "end of week" in t or "end of the week" in t:
        return today + timedelta(days=(4 - today.weekday()) % 7 or 7)  # Friday
    if "this month" in t or "end of month" in t or "end of the month" in t:
        nxt = date(today.year + (1 if today.month == 12 else 0),
                   1 if today.month == 12 else today.month + 1, 1)
        return nxt - timedelta(days=1)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "today" in t:
        return today
    m = re.search(r"(?:in|within)\s+(\d+)\s+(day|week|month)s?", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return today + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit])
    return today + timedelta(days=30)


def _trading_days_between(start: date, end: date) -> int:
    """Weekdays (Mon-Fri) from the day after start through end, minimum 1."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return max(1, n)


def _parse_amount(s: str) -> float:
    s = s.replace(",", "").replace("$", "").strip().lower()
    mult = 1.0
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        return float(s) * mult
    except Exception:
        return 0.0


# ── Goal CRUD ──────────────────────────────────────────────────────────────────

def goal_set(text: str) -> str:
    """Parse a plain-English goal, persist it, and apply the mapped risk
    profile (capped at aggressive for automatic selection)."""
    text = (text or "").strip()
    if not text:
        return ("State a goal with a deadline, e.g. 'turn 100k into 150k by end "
                "of July', 'make $500 profit this week', 'grow the account 20% "
                "this month', or 'I need $10,000 by Friday'.")
    t = text.lower()
    current = _portfolio_value()
    if current <= 0:
        return "Can't set a goal: live portfolio value unavailable from Alpaca."

    deadline = _parse_deadline(t)
    target_value = 0.0

    # "turn X into Y"
    m = re.search(r"turn\s+\$?([\d.,]+\s*[km]?)\s+into\s+\$?([\d.,]+\s*[km]?)", t)
    if m:
        target_value = _parse_amount(m.group(2))
    if not target_value:                      # "grow ... 20%"
        m = re.search(r"(?:grow|gain|increase|up)\b.*?([\d.]+)\s*%", t)
        if m:
            target_value = current * (1 + float(m.group(1)) / 100)
    if not target_value:                      # "make $500 profit" / "I need $10,000"
        m = re.search(r"(?:make|profit\s+of|need|earn|clear)\s+\$?([\d.,]+\s*[km]?)", t)
        if m:
            amt = _parse_amount(m.group(1))
            # An amount below the account value reads as PROFIT wanted;
            # at/above the account value it reads as a target value.
            target_value = amt if amt > current else current + amt
    if not target_value:
        m = re.search(r"(?:reach|hit|to)\s+\$?([\d.,]+\s*[km]?)", t)
        if m:
            target_value = _parse_amount(m.group(1))
    if target_value <= current:
        return (f"Couldn't parse a target above the current portfolio value "
                f"(${current:,.2f}) from: \"{text}\". Try 'turn 100k into 150k "
                f"by end of July' or 'make $2,000 this week'.")

    goal = {
        "text":         text,
        "start_value":  round(current, 2),
        "target_value": round(target_value, 2),
        "deadline":     deadline.isoformat(),
        "set_on":       date.today().isoformat(),
        "active":       True,
        "achieved":     False,
        "hold_profile": False,
        "profile_at_set": "",
    }
    put(_KEY, goal)

    # Map required return → profile; automatic selection caps at aggressive.
    req = required_metrics(goal)
    RP = _rp()
    mapped = _profile_for_daily_pct(req["required_daily_pct"])
    applied = mapped
    cap_idx = RP.PROFILE_ORDER.index(RP.MAX_AUTO_PROFILE)
    note = ""
    if RP.PROFILE_ORDER.index(mapped) > cap_idx:
        applied = RP.MAX_AUTO_PROFILE
        note = (f"\n  ⚠ Required pace ({req['required_daily_pct']:.1f}%/day) maps to "
                f"{mapped.upper().replace('_',' ')}, but automatic selection is capped at "
                f"AGGRESSIVE. Say 'use {mapped.replace('_',' ')} profile' to enable it explicitly.")
    try:
        RP.set_params({"risk_profile": applied})
        goal["profile_at_set"] = applied
        put(_KEY, goal)
    except Exception:
        pass

    return "\n".join(filter(None, [
        "🎯 GOAL SET",
        f"  {text}",
        f"  Start:    ${current:,.2f}   →   Target: ${target_value:,.2f}",
        f"  Deadline: {deadline.strftime('%A, %B %d %Y')}  "
        f"({req['trading_days_left']} trading days)",
        f"  Required: +${req['required_daily_dollars']:,.0f}/day "
        f"({req['required_daily_pct']:+.2f}% daily)",
        f"  Risk profile applied: {applied.upper().replace('_', ' ')}" + note,
        "",
        "  Track anytime with 'goal status'. Say 'hold profile' to freeze the",
        "  risk profile against automatic escalation, or 'clear goal' to stop.",
    ]))


def goal_get() -> dict:
    g = get(_KEY) or {}
    return g if g.get("active") else {}


def goal_clear() -> str:
    g = get(_KEY) or {}
    if not g:
        return "No goal is set."
    g["active"] = False
    put(_KEY, g)
    return "Goal cleared. Risk profile stays where it is — adjust in the Markets tab."


def goal_hold() -> str:
    """'hold profile' — freeze the current risk profile against auto-escalation."""
    g = get(_KEY) or {}
    if not g.get("active"):
        return "No active goal — nothing to hold. Profile only auto-changes while a goal is set."
    g["hold_profile"] = True
    put(_KEY, g)
    prof = _rp().get_params()["risk_profile"]
    return (f"Profile held at {prof.upper().replace('_', ' ')} — the goal engine "
            f"will keep tracking pace but will NOT auto-escalate. "
            f"Say 'release profile' to re-enable.")


def goal_release() -> str:
    g = get(_KEY) or {}
    if not g.get("active"):
        return "No active goal."
    g["hold_profile"] = False
    put(_KEY, g)
    return "Profile hold released — automatic escalation (max AGGRESSIVE) is back on."


# ── Math ───────────────────────────────────────────────────────────────────────

def _profile_for_daily_pct(pct: float) -> str:
    if pct < 0.5:
        return "conservative"
    if pct <= 1.5:
        return "moderate"
    if pct <= 3.0:
        return "aggressive"
    if pct <= 5.0:
        return "high_risk"
    return "speculative"


def required_metrics(goal: dict = None) -> dict:
    g = goal or goal_get()
    if not g:
        return {}
    current  = _portfolio_value() or g.get("start_value", 0)
    target   = float(g.get("target_value", 0))
    deadline = date.fromisoformat(g["deadline"])
    days     = _trading_days_between(date.today(), deadline)
    gain_needed = max(0.0, target - current)
    req_day  = gain_needed / days
    req_pct  = (req_day / current * 100) if current else 0.0

    # Pace so far: gain per elapsed trading day since the goal was set
    set_on   = date.fromisoformat(g.get("set_on", date.today().isoformat()))
    elapsed  = _trading_days_between(set_on - timedelta(days=1), date.today())
    gained   = current - float(g.get("start_value", current))
    pace_day = gained / max(1, elapsed) if date.today() > set_on else 0.0

    return {
        "current_value":            round(current, 2),
        "target_value":             round(target, 2),
        "start_value":              float(g.get("start_value", 0)),
        "gain_needed":              round(gain_needed, 2),
        "trading_days_left":        days,
        "deadline":                 g["deadline"],
        "required_daily_dollars":   round(req_day, 2),
        "required_daily_pct":       round(req_pct, 2),
        "gained_so_far":            round(gained, 2),
        "pace_daily_dollars":       round(pace_day, 2),
        "on_track":                 pace_day >= req_day * 0.9,
        "progress_pct":             round(
            (current - g.get("start_value", 0)) /
            max(1e-9, target - g.get("start_value", 0)) * 100, 2),
        "achieved":                 current >= target,
    }


def goal_snapshot() -> dict:
    """Structured goal + metrics for the /goal route and the Markets tab."""
    g = goal_get()
    if not g:
        return {}
    m = required_metrics(g)
    m.update({"text": g.get("text", ""), "hold_profile": g.get("hold_profile", False),
              "profile": _rp().get_params()["risk_profile"]})
    return m


def goal_progress_lines() -> list:
    """Short progress block appended to capital status / reports."""
    m = goal_snapshot()
    if not m:
        return []
    bar_fill = max(0, min(20, int(m["progress_pct"] / 5)))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    return [
        f"  Goal: {m['text']}",
        f"    ${m['start_value']:,.0f} → ${m['target_value']:,.0f}   "
        f"[{bar}] {m['progress_pct']:.1f}%",
        f"    Required: +${m['required_daily_dollars']:,.0f}/day "
        f"({m['required_daily_pct']:+.2f}%/day) over {m['trading_days_left']} trading days",
        f"    Pace: +${m['pace_daily_dollars']:,.0f}/day — "
        f"{'ON TRACK ✓' if m['on_track'] else 'BEHIND ⚠'}"
        + ("  (profile HELD)" if m.get("hold_profile") else ""),
    ]


def goal_status() -> str:
    """Full goal tracker (chat tool)."""
    g = goal_get()
    if not g:
        return ("🎯 No trading goal set.\n"
                "Say e.g. 'turn 100k into 150k by end of July', 'make $500 "
                "profit this week', or 'I need $10,000 by Friday' and I'll "
                "adapt the whole trading behavior to it.")
    m = required_metrics(g)
    if m["achieved"]:
        return goal_check(force=True)
    days_txt = f"{m['trading_days_left']} trading days left (deadline {m['deadline']})"
    return "\n".join([
        "🎯 GOAL TRACKER", "━" * 30,
        *goal_progress_lines(),
        f"    {days_txt}",
        f"    Risk profile: {_rp().get_params()['risk_profile'].upper().replace('_', ' ')}"
        + ("  [held — no auto-escalation]" if g.get("hold_profile") else
           "  [auto-escalates when behind, ceiling: AGGRESSIVE]"),
    ])


# ── Periodic check: completion + capped escalation ─────────────────────────────

def goal_check(force: bool = False) -> str:
    """Called by the background loop (and 'goal status' when achieved).
    Handles completion notification and behind-pace escalation."""
    g = goal_get()
    if not g:
        return ""
    m = required_metrics(g)
    RP = _rp()

    # Completion
    if m["achieved"]:
        g["active"], g["achieved"] = False, True
        put(_KEY, g)
        days_spare = m["trading_days_left"]
        msg = (f"🎯 GOAL ACHIEVED! Portfolio reached ${m['current_value']:,.2f} "
               f"(target ${m['target_value']:,.2f})"
               + (f" with {days_spare} trading day{'s' if days_spare != 1 else ''} to spare"
                  if days_spare > 0 else "") + ".\n"
               "Want to set a new goal, or keep the current risk parameters?")
        _push_alert(msg)
        return msg

    # Behind pace → escalate ONE tier, hard ceiling at aggressive (user rule)
    if not m["on_track"] and not g.get("hold_profile") and not force:
        params  = RP.get_params()
        order   = RP.PROFILE_ORDER
        cur_idx = order.index(params["risk_profile"]) if params["risk_profile"] in order else 1
        cap_idx = order.index(RP.MAX_AUTO_PROFILE)
        if cur_idx < cap_idx:
            new_prof = order[cur_idx + 1]
            try:
                RP.set_params({"risk_profile": new_prof})
                msg = (f"⚠ You are behind pace. Escalating to "
                       f"{new_prof.upper().replace('_', ' ')} profile to catch up. "
                       f"Say 'hold profile' to prevent this.")
                _push_alert(msg)
                return msg
            except Exception:
                pass
        elif cur_idx == cap_idx:
            need = _profile_for_daily_pct(m["required_daily_pct"])
            if order.index(need) > cap_idx:
                return (f"Behind pace at the AGGRESSIVE ceiling. Required pace "
                        f"({m['required_daily_pct']:.1f}%/day) maps to "
                        f"{need.upper().replace('_', ' ')} — I won't go there "
                        f"automatically. Say 'use {need.replace('_', ' ')} profile' "
                        f"to enable it explicitly.")
    return ""


def _loop():
    while _state["running"]:
        try:
            now = time.time()
            if now - _state["last_check"] >= 900:      # every 15 min
                _state["last_check"] = now
                if goal_get():
                    # Only escalate during market hours — pace can't change overnight
                    try:
                        import tools.trading as TRD
                        if TRD._is_open():
                            goal_check()
                        else:
                            # still catch completion off-hours
                            m = required_metrics()
                            if m and m.get("achieved"):
                                goal_check()
                    except Exception:
                        goal_check()
        except Exception:
            pass
        time.sleep(60)


def start_goal_engine() -> str:
    if _state["running"]:
        return "Goal engine already running."
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-goal-engine").start()
    return "Goal engine started (pace check every 15 min; escalation ceiling: AGGRESSIVE)."
