"""
tools/market_outlook.py — JARVIS Market Outlook Gate

Assesses overall market conditions before deciding how aggressively to trade.
Some days justify 0 trades; this turns that judgment into a number instead of
leaving it implicit.

MARKET OUTLOOK SCORE (0-100), baseline 50, adjusted by:
  VIX level:        <15 low fear (+20) | 15-20 normal (+10) |
                     20-25 elevated (-10) | >25 high fear (-20)
  SPY trend today:   up >0.5% (+15) | flat (0) | down >0.5% (-15)
  Sector breadth:    7+/9 sectors positive (+15) | 4-6 (0) | <4 (-15)
  Volume vs 20d avg: >1.2x (+10) | <0.8x (-10)
  Geopolitical risk (tools/political_intel): LOW (+10) | MEDIUM (0) |
                     HIGH (-15) | CRITICAL (-25)

SCORE → TRADING MODE:
  70-100  AGGRESSIVE — trade all high-conviction opportunities, full tiers
  50-69   NORMAL     — standard parameters
  30-49   SELECTIVE  — conviction threshold raised +10
  10-29   CAUTIOUS   — only conviction 85+, position sizes cut 50%
  0-9     STANDBY    — no new positions, monitor + tighten stops only

Recomputed lazily, cached 30 minutes (tools/store.py, so it's shared across
the server process and the Task Scheduler process like risk_params.py).
Wired into tools/risk_params.py: autonomy_gate() blocks new entries at
STANDBY; min_conviction_engine() / position_size_dollars() apply the
SELECTIVE/CAUTIOUS adjustments.

User overrides (both day-scoped, cleared automatically the next day):
  force_mode("aggressive"|"normal"|"selective"|"cautious"|"standby")
  ignore_today() / resume_outlook() — gate stops blocking entirely for today
  resume_auto() — clears a forced mode, back to the computed score
"""

from datetime import datetime, date
from tools.store import get, put

_CACHE_KEY    = "market_outlook_cache"
_OVERRIDE_KEY = "market_outlook_override"
_IGNORE_KEY   = "market_outlook_ignore"
_TTL_SECONDS  = 1800   # 30 minutes

_MODES = ("aggressive", "normal", "selective", "cautious", "standby")

_MODE_MEANING = {
    "AGGRESSIVE": "AGGRESSIVE — trade all high-conviction opportunities, use full conviction tiers.",
    "NORMAL":     "NORMAL — standard risk parameters, no adjustment.",
    "SELECTIVE":  "SELECTIVE — only the top signals; conviction threshold raised +10.",
    "CAUTIOUS":   "CAUTIOUS — only conviction 85+ trades; position sizes cut 50%.",
    "STANDBY":    "STANDBY — no new positions; monitor and tighten stops on existing only.",
}

_SECTOR_ETFS = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLI", "XLB", "XLU"]


# ── Component scores ───────────────────────────────────────────────────────────

def _score_vix() -> tuple:
    try:
        import yfinance as yf
        vix = float(yf.Ticker("^VIX").fast_info.last_price or 0)
    except Exception:
        return 0, "VIX unavailable"
    if not vix:
        return 0, "VIX unavailable"
    if vix < 15:
        return 20, f"VIX {vix:.1f} — low fear (bullish)"
    elif vix <= 20:
        return 10, f"VIX {vix:.1f} — normal"
    elif vix <= 25:
        return -10, f"VIX {vix:.1f} — elevated"
    else:
        return -20, f"VIX {vix:.1f} — high fear (bearish)"


def _score_spy_trend() -> tuple:
    try:
        import tools.market as MKT
        bars = MKT._fetch_history("SPY", 30)
        ta = MKT._compute_ta(bars) if bars else {}
        chg = ta.get("pct_change")
    except Exception:
        chg = None
    if chg is None:
        return 0, "SPY trend unavailable"
    if chg > 0.5:
        return 15, f"SPY {chg:+.2f}% today — bullish"
    elif chg < -0.5:
        return -15, f"SPY {chg:+.2f}% today — bearish"
    else:
        return 0, f"SPY {chg:+.2f}% today — flat"


def _score_sector_breadth() -> tuple:
    try:
        import tools.trading as TRD
        snap = TRD._data("/v2/stocks/snapshots", {"symbols": ",".join(_SECTOR_ETFS)})
        pos, n = 0, 0
        for etf in _SECTOR_ETFS:
            s = snap.get(etf, {})
            bar, prev = s.get("dailyBar") or {}, s.get("prevDailyBar") or {}
            c, pc = float(bar.get("c") or 0), float(prev.get("c") or 0)
            if not c or not pc:
                continue
            n += 1
            if c > pc:
                pos += 1
    except Exception:
        return 0, "Sector breadth unavailable"
    if n == 0:
        return 0, "Sector breadth unavailable"
    if pos >= 7:
        return 15, f"{pos}/{n} sectors positive — broad rally"
    elif pos >= 4:
        return 0, f"{pos}/{n} sectors positive — mixed"
    else:
        return -15, f"{pos}/{n} sectors positive — narrow/weak"


def _score_volume() -> tuple:
    try:
        import tools.market as MKT
        bars = MKT._fetch_history("SPY", 30)
        ta = MKT._compute_ta(bars) if bars else {}
        ratio = ta.get("vol_ratio")
    except Exception:
        ratio = None
    if ratio is None:
        return 0, "Volume data unavailable"
    if ratio > 1.2:
        return 10, f"Volume {ratio:.2f}x 20d avg — strong participation"
    elif ratio < 0.8:
        return -10, f"Volume {ratio:.2f}x 20d avg — low conviction"
    else:
        return 0, f"Volume {ratio:.2f}x 20d avg — normal"


def _score_geo() -> tuple:
    try:
        import tools.political_intel as PI
        score = PI.geo_risk_score()
        band = PI.geo_band(score)
    except Exception:
        return 0, "Geo risk unavailable"
    mapping = {"NORMAL": (10, "LOW"), "ELEVATED": (0, "MEDIUM"),
               "HIGH": (-15, "HIGH"), "CRITICAL": (-25, "CRITICAL")}
    pts, label = mapping.get(band, (0, "MEDIUM"))
    return pts, f"Geopolitical risk {label} ({score}/100)"


def _mode_for_score(score: int) -> str:
    if score >= 70:
        return "AGGRESSIVE"
    if score >= 50:
        return "NORMAL"
    if score >= 30:
        return "SELECTIVE"
    if score >= 10:
        return "CAUTIOUS"
    return "STANDBY"


# ── Scoring + cache ────────────────────────────────────────────────────────────

def compute_outlook() -> dict:
    """Fresh (uncached) 0-100 outlook score + mode + component breakdown."""
    vix_pts, vix_note = _score_vix()
    spy_pts, spy_note = _score_spy_trend()
    breadth_pts, breadth_note = _score_sector_breadth()
    vol_pts, vol_note = _score_volume()
    geo_pts, geo_note = _score_geo()
    score = max(0, min(100, round(50 + vix_pts + spy_pts + breadth_pts + vol_pts + geo_pts)))
    return {
        "score": score,
        "mode": _mode_for_score(score),
        "components": [vix_note, spy_note, breadth_note, vol_note, geo_note],
        "computed_at": datetime.now().isoformat(),
    }


def outlook_snapshot(force: bool = False) -> dict:
    """Cached score/mode — recomputed at most every 30 minutes (per spec).
    force=True bypasses the cache for an on-demand rebuild."""
    cached = get(_CACHE_KEY)
    if not force and cached:
        try:
            age = (datetime.now() - datetime.fromisoformat(cached["computed_at"])).total_seconds()
            if age < _TTL_SECONDS:
                return cached
        except Exception:
            pass
    snap = compute_outlook()
    put(_CACHE_KEY, snap)
    return snap


# ── User overrides (day-scoped) ────────────────────────────────────────────────

def _active_override_mode():
    o = get(_OVERRIDE_KEY)
    if o and o.get("date") == str(date.today()):
        return o.get("mode", "").upper()
    return None


def _is_ignored_today() -> bool:
    ig = get(_IGNORE_KEY)
    return bool(ig and ig.get("date") == str(date.today()))


def force_mode(mode: str) -> str:
    """'force aggressive mode' / 'go to standby mode' — pins the mode for
    today regardless of the computed score. Say 'resume auto outlook' to
    release it back to the computed score."""
    m = (mode or "").strip().lower()
    if m not in _MODES:
        return f"Unknown mode '{mode}'. Choose from: {', '.join(x.upper() for x in _MODES)}."
    put(_OVERRIDE_KEY, {"mode": m, "date": str(date.today())})
    return (f"Market outlook mode forced to {m.upper()} for today — overriding the "
            f"computed score. Say 'resume auto outlook' to release it.")


def resume_auto() -> str:
    put(_OVERRIDE_KEY, None)
    return "Market outlook override cleared — back to the computed score/mode."


def ignore_today() -> str:
    """'ignore market outlook today' — the outlook gate stops blocking new
    entries for the rest of today (other risk gates — daily loss, geo risk,
    blocked tickers, trading hours — still apply)."""
    put(_IGNORE_KEY, {"date": str(date.today())})
    return ("Market outlook gate ignored for today — it will not block autonomous "
            "trading (other risk gates still apply). Say 'stop ignoring market "
            "outlook' to re-enable it.")


def resume_outlook() -> str:
    put(_IGNORE_KEY, None)
    return "Market outlook gate re-enabled."


# ── Effective mode + integration points ────────────────────────────────────────

def effective_mode() -> str:
    """The mode actually governing behavior right now: an active override
    wins, otherwise the computed score's mode."""
    return _active_override_mode() or outlook_snapshot()["mode"]


def outlook_gate() -> tuple:
    """Called by risk_params.autonomy_gate() on every autonomous entry.
    Returns (ok, reason)."""
    if _is_ignored_today():
        return True, ""
    mode = effective_mode()
    if mode == "STANDBY":
        snap = outlook_snapshot()
        return False, (
            f"Market Outlook: STANDBY ({snap['score']}/100) — no new positions, "
            f"monitoring existing only. Say 'force aggressive mode' or "
            f"'ignore market outlook today' to override."
        )
    return True, ""


def adjust_min_conviction(base_100: int) -> int:
    """Called by risk_params.min_conviction_engine(). SELECTIVE raises the
    bar +10; CAUTIOUS forces it to at least 85; STANDBY is moot (entries are
    already blocked by outlook_gate())."""
    mode = effective_mode()
    if mode == "SELECTIVE":
        return base_100 + 10
    if mode == "CAUTIOUS":
        return max(base_100, 85)
    return base_100


def size_multiplier() -> float:
    """Called by risk_params.position_size_dollars(). CAUTIOUS halves size."""
    return 0.5 if effective_mode() == "CAUTIOUS" else 1.0


# ── Reporting ──────────────────────────────────────────────────────────────────

def outlook_report() -> str:
    """Human-readable outlook summary (chat tool + Markets tab header)."""
    snap = outlook_snapshot()
    ov = _active_override_mode()
    ignored = _is_ignored_today()
    mode = ov or snap["mode"]
    tag = (" [forced]" if ov else "") + (" [gate ignored today]" if ignored else "")
    lines = [f"MARKET OUTLOOK: {mode} ({snap['score']}/100){tag}", ""]
    lines += [f"  {c}" for c in snap["components"]]
    lines += ["", f"  {_MODE_MEANING.get(mode, '')}"]
    if not ov:
        lines.append("  Say 'force aggressive mode' / 'go to standby mode' / "
                     "'ignore market outlook today' to override.")
    return "\n".join(lines)


def outlook_snapshot_json() -> dict:
    """Structured snapshot for the Markets tab header (JSON API)."""
    snap = outlook_snapshot()
    ov = _active_override_mode()
    mode = ov or snap["mode"]
    return {
        "score": snap["score"],
        "computed_mode": snap["mode"],
        "mode": mode,
        "forced": bool(ov),
        "ignored_today": _is_ignored_today(),
        "components": snap["components"],
        "meaning": _MODE_MEANING.get(mode, ""),
        "updated_at": snap["computed_at"],
    }
