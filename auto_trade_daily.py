"""
auto_trade_daily.py — JARVIS Autonomous Daily Trading Runner

Schedule: Mon–Fri at 8:00 AM ET (Task Scheduler) — 1.5h before NYSE open
Phase 1  (8:00 AM)  — pre-market spectate: market regime, sector heat, conviction
                      scan (curated + broad NYSE/NASDAQ screen), social sentiment, geo brief
Phase 2  (9:30 AM)  — NYSE open: first full scan-and-trade cycle
Phase 3  (all day)  — a full scan-and-trade cycle EVERY 30 MINUTES until close
                      (capital: live Alpaca buying power × conviction-tier sizing)

There is NO hardcoded end date — the runner never stops firing because a
"mission window" closed. MISSION_END below is informational only.
"""

import os, sys, time, json
from datetime import datetime, date, timezone
from pathlib import Path

ROOT     = Path(__file__).parent
LOG_DIR  = Path.home() / "Documents" / "JARVIS" / "trading"
LOG_FILE = LOG_DIR / "trade_log.txt"
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))

# Informational only — NEVER used to block trading (user rule).
MISSION_END = date(2027, 12, 31)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v


def _log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _win_notify(title: str, msg: str):
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, msg, duration=8, threaded=True)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40 | 0x1000)
        except Exception:
            pass


def _market_clock():
    import tools.trading as TRD
    return TRD._api("GET", "/v2/clock")


# ── Phase 1: Pre-market analysis (runs at 8 AM) ────────────────────────────────

def pre_market_analysis():
    _log("=" * 70)
    _log("PHASE 1 — PRE-MARKET ANALYSIS (8:00 AM ET)")
    _log("=" * 70)

    # Market regime — bull/bear/sideways/volatile classification
    _log("Checking market regime...")
    try:
        import tools.conviction as CVN
        regime = CVN.market_regime()
        for line in str(regime).split("\n")[:10]:
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"Market regime error: {e}")

    # Sector heat — which sectors are running hot today
    _log("")
    _log("Checking sector heat map...")
    try:
        import tools.conviction as CVN
        heat = CVN.sector_heat()
        for line in str(heat).split("\n")[:14]:
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"Sector heat error: {e}")

    # Conviction scan — no trading, just rank candidates (already sweeps the
    # curated watchlist + a live broad NYSE/NASDAQ screen)
    _log("")
    _log("Running conviction scan on universe (no trades yet)...")
    try:
        import tools.conviction as CVN
        scan = CVN.auto_hunt(auto_trade=False)
        _log("Pre-market conviction rankings:")
        for line in scan.split("\n")[:20]:
            if line.strip():
                _log("  " + line)
        _log("Conviction scan complete.")
    except Exception as e:
        _log(f"Conviction scan error: {e}")

    # Social sentiment on top watchlist names
    _log("")
    _log("Checking social sentiment (StockTwits + Reddit WSB)...")
    top_tickers = ["SOFI", "PLTR", "NVDA", "TSLA", "SPY"]
    try:
        import tools.social_intel as SOC
        for sym in top_tickers:
            try:
                pts, detail = SOC.social_signal(sym)
                _log(f"  {sym}: {detail}")
            except Exception:
                pass
    except Exception as e:
        _log(f"Social intel error: {e}")

    # Geopolitical brief
    _log("")
    _log("Fetching geopolitical brief...")
    try:
        import tools.social_intel as SOC
        brief = SOC.geopolitical_deep_brief()
        _log("Geo brief:")
        for line in str(brief).split("\n")[:8]:
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"Geo brief error: {e}")

    # Budget check
    _log("")
    _log("Pre-market budget status:")
    try:
        import tools.trading as TRD
        status = TRD.trading_budget_status()
        for line in status.split("\n"):
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"Budget status error: {e}")

    _log("")
    _log("Pre-market analysis complete. Waiting for NYSE open (9:30 AM ET)...")


# ── Wait for market open ───────────────────────────────────────────────────────

def wait_for_market_open(max_wait_minutes: int = 120) -> bool:
    """
    Poll Alpaca's market clock until the market opens.
    Returns True when open, False if it never opens within max_wait_minutes.
    """
    deadline = time.time() + max_wait_minutes * 60
    last_log  = 0

    while time.time() < deadline:
        try:
            clock = _market_clock()
            if clock.get("is_open"):
                _log("NYSE is OPEN. Executing trade phase now.")
                return True

            next_open_str = clock.get("next_open", "")
            if next_open_str:
                next_open = datetime.fromisoformat(
                    next_open_str.replace("Z", "+00:00")
                )
                now_utc    = datetime.now(timezone.utc)
                secs_left  = (next_open - now_utc).total_seconds()

                if secs_left <= 0:
                    # Clock says not open but time has passed — recheck once
                    time.sleep(5)
                    continue

                if secs_left > max_wait_minutes * 60:
                    _log(f"NYSE opens in {secs_left/3600:.1f}h — beyond wait window. Skipping.")
                    return False

                # Log every 5 minutes
                if time.time() - last_log >= 300:
                    mins = int(secs_left // 60)
                    secs = int(secs_left % 60)
                    _log(f"Waiting for open: {mins}m {secs}s remaining...")
                    last_log = time.time()

                # Sleep in 30s intervals until close to open
                sleep_secs = min(30, max(5, int(secs_left) - 10))
                time.sleep(sleep_secs)
            else:
                time.sleep(30)

        except Exception as e:
            _log(f"Clock check error: {e}")
            time.sleep(30)

    _log("Wait timeout reached — market did not open within window.")
    return False


# ── Phase 2: Execute trades at market open (9:30 AM ET) ───────────────────────

def market_open_execution():
    _log("")
    _log("=" * 70)
    _log("PHASE 2 — MARKET OPEN EXECUTION (9:30 AM ET)")
    _log("=" * 70)

    # Start trade monitor
    try:
        import tools.trade_monitor as MON
        MON.start_monitor()
        _log("Trade monitor started.")
    except Exception as e:
        _log(f"Monitor start skipped: {e}")

    # Log to self-learning memory
    try:
        import tools.jarvis_memory as MEM
        MEM.log_interaction(f"market_open_trade_{date.today()}", "auto_hunt")
    except Exception:
        pass

    # Markets-dashboard master switch: OFF = analyze only, no execution.
    # (auto_hunt gates itself too — this makes the daily log say so up front.)
    autonomous = True
    try:
        import tools.risk_params as RP
        params = RP.get_params()
        autonomous = params["autonomous_enabled"]
        _log(f"Risk params: profile={params['risk_profile']} | "
             f"max pos {params['max_position_pct']}% of buying power | "
             f"daily loss {params['max_daily_loss_pct']}% of portfolio | "
             f"min conviction {params['min_conviction']}/10 | "
             f"stop {params['stop_loss_pct']}% / target {params['take_profit_pct']}% | "
             f"autonomous={'ON' if autonomous else 'OFF'}")
    except Exception as e:
        _log(f"Risk params unavailable ({e}) — using built-in defaults.")

    # Auto Hunt — scan and trade (or analyze-only when the master switch is off)
    _log("Running auto hunt with live execution..." if autonomous
         else "Autonomous trading OFF — running analysis-only scan...")
    stock_result = ""
    try:
        import tools.conviction as CVN
        stock_result = CVN.auto_hunt(auto_trade=autonomous)
        _log("STOCK HUNT RESULT:")
        for line in stock_result.split("\n"):
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"AUTO HUNT ERROR: {e}")
        import traceback
        _log(traceback.format_exc())
        _win_notify("JARVIS — Auto Hunt Error", str(e)[:200])
        return ""

    # Options hunt
    _log("")
    _log("Checking for options plays (need ≥$25 free, conviction bar from risk_params)...")
    try:
        import tools.options_engine as OPT
        budget_rem = OPT._budget_remaining()
        if not autonomous:
            _log("  Options skipped: autonomous trading is OFF (Markets dashboard).")
        elif budget_rem >= 25:
            opts_result = OPT.options_auto_hunt()
            _log("OPTIONS HUNT:")
            for line in opts_result.split("\n"):
                if line.strip():
                    _log("  " + line)
        else:
            _log(f"  Options skipped: ${budget_rem:.2f} remaining (need ≥$25)")
    except Exception as e:
        _log(f"Options hunt error: {e}")

    # Capital status after the opening cycle
    _log("")
    _log("CAPITAL STATUS POST-TRADE:")
    try:
        import tools.trading as TRD
        for line in TRD.trading_budget_status().split("\n"):
            if line.strip():
                _log("  " + line)
    except Exception as e:
        _log(f"Capital status error: {e}")

    return stock_result


# ── Phase 3: full scan-and-trade cycle every 30 minutes until close ───────────

def intraday_cycles(interval_minutes: int = 30) -> int:
    """
    Bug-3 fix: JARVIS no longer trades once at the open and goes idle.
    A full scan-and-trade cycle runs every `interval_minutes` for the whole
    session. Each cycle re-reads the risk params (so a goal-engine profile
    escalation mid-day takes effect immediately) and re-checks the autonomy
    master switch. Runs until Alpaca's clock says the market closed.
    """
    cycle = 0
    while True:
        # Sleep FIRST — the 9:30 execution already ran as cycle 0
        time.sleep(interval_minutes * 60)
        try:
            clock = _market_clock()
            if not clock.get("is_open"):
                _log("Market closed — intraday cycle loop complete.")
                break
        except Exception as e:
            _log(f"Clock check error in cycle loop: {e} — retrying next interval")
            continue
        cycle += 1
        _log("")
        _log(f"── INTRADAY CYCLE #{cycle}  ({datetime.now().strftime('%H:%M:%S')}) " + "─" * 28)
        autonomous = True
        try:
            import tools.risk_params as RP
            autonomous = RP.get_params()["autonomous_enabled"]
        except Exception:
            pass
        try:
            import tools.conviction as CVN
            result = CVN.auto_hunt(auto_trade=autonomous)
            for line in result.split("\n"):
                if line.strip():
                    _log("  " + line)
        except Exception as e:
            _log(f"Cycle #{cycle} error: {e}")
        # Goal-engine pace check rides along each cycle
        try:
            import tools.goal_engine as GOAL
            note = GOAL.goal_check()
            if note:
                _log(f"GOAL ENGINE: {note}")
        except Exception:
            pass
    return cycle


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _load_env()
    today = date.today()

    _log("=" * 70)
    _log(f"JARVIS DAILY TRADER — {today.strftime('%A, %B %d %Y')}")
    _log("=" * 70)
    # No mission-window gate: the runner never stops on a hardcoded date.
    if today > MISSION_END:
        _log(f"(Note: informational MISSION_END {MISSION_END} has passed — trading continues.)")

    # ── Phase 1: Pre-market analysis ──────────────────────────────────────────
    pre_market_analysis()

    # ── Wait for NYSE to open (9:30 AM ET) ───────────────────────────────────
    opened = wait_for_market_open(max_wait_minutes=120)

    if not opened:
        _log("Market did not open — aborting trade execution.")
        _win_notify("JARVIS — Market Closed", "NYSE did not open during wait window. No trades executed.")
        return

    # No post-open pause — conviction/capital/tape gates inside auto_hunt()
    # already protect against buying into first-minute noise, and the 30-min
    # scan cycle handles pacing from here.

    # ── Phase 2: Execute trades at open ──────────────────────────────────────
    result = market_open_execution()

    # ── Opening-cycle notification ────────────────────────────────────────────
    notify_msg = "Opening cycle done — trading every 30 min until close."
    if result:
        if "EXECUTED" in result:
            lines = result.split("\n")
            for i, ln in enumerate(lines):
                if "EXECUTED" in ln:
                    detail = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    notify_msg = f"{ln.strip()}\n{detail}"
                    break
        elif "No high-conviction setup" in result or "No affordable" in result:
            notify_msg = "No setup passed the gates at the open — re-scanning every 30 min."
    _win_notify(f"JARVIS — Daily Trader ({today})", notify_msg)

    # ── Phase 3: full scan-and-trade cycle every 30 minutes until close ──────
    cycles = intraday_cycles(interval_minutes=30)

    _win_notify(f"JARVIS — Session Complete ({today})",
                f"Ran {cycles + 1} scan-and-trade cycles. See trade_log.txt.")
    _log(f"Done — {cycles + 1} total cycles this session.")
    _log("=" * 70)


if __name__ == "__main__":
    main()
