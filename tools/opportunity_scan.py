"""
tools/opportunity_scan.py — dual-mode opportunity hunting + ranked queue.

BROAD scan  (every 30 min, market hours): the whole NYSE+NASDAQ roster via
  batched Alpaca snapshots → movers on volume → shortlist enriched with
  RSI-cross / 52-week-high / unusual-options / short-interest checks →
  ranked with the cross-sector bridge multiplier → top 10 into the queue.
NARROW scan (every 5 min, market hours): watchlist + open positions + last
  broad top-20. Alerts (pushed into the chat via the reminders channel) on:
  >1.5% move in 5 min, volume spike >5x, break of prior-day high.
AUTO-FILL: when capital is available and the autonomy gate is open, the top
  queue entry is conviction-checked and opened within risk parameters —
  at most one entry per 10 minutes.

Queue persists in store.py ('opportunity_queue'); the user can promote /
demote / remove entries from the Markets dashboard at any time.
"""

import time
import threading
from datetime import datetime, date
from pathlib import Path
from tools.store import get, put

_Q_KEY   = "opportunity_queue"
_LOG     = Path.home() / "Documents" / "JARVIS" / "trading" / "scanner_log.txt"
_LOG.parent.mkdir(parents=True, exist_ok=True)

_state = {
    "running": False, "last_broad": 0.0, "last_narrow": 0.0, "last_fill": 0.0,
    "broad_top20": [], "alert_throttle": {}, "removed_today": ("", []),
    "broad_runs": 0, "narrow_runs": 0, "clock_cache": (0.0, False),
}

# ── Trade-frequency counters (Bug 3: scans vs found vs executed vs skipped) ────
_freq = {"day": "", "scans_broad": 0, "scans_narrow": 0, "found": 0,
         "executed": 0, "skipped": []}


def _freq_today() -> dict:
    day = str(date.today())
    if _freq["day"] != day:
        _freq.update({"day": day, "scans_broad": 0, "scans_narrow": 0,
                      "found": 0, "executed": 0, "skipped": []})
    return _freq


def _skip(symbol: str, reason: str):
    f = _freq_today()
    entry = f"[{datetime.now().strftime('%H:%M')}] {symbol}: {reason}"
    f["skipped"].append(entry)
    if len(f["skipped"]) > 60:
        f["skipped"].pop(0)
    _log(f"Auto-fill skipped — {symbol}: {reason}")
    try:
        import tools.trade_monitor as MON
        MON.log_skip(symbol, reason, source="opportunity_queue")
    except Exception:
        pass


def frequency_report() -> str:
    """Today's autonomous-trading activity: how many scans ran, opportunities
    found, executed, and skipped — with the reason for every skip."""
    f = _freq_today()
    lines = [
        "📊 TRADE FREQUENCY — " + f["day"], "━" * 30,
        f"  broad scans run:    {f['scans_broad']}  (every 30 min, market hours)",
        f"  narrow scans run:   {f['scans_narrow']}  (every 5 min)",
        f"  opportunities found:{f['found']:>4}",
        f"  executed:           {f['executed']:>4}",
        f"  skipped:            {len(f['skipped']):>4}",
    ]
    if f["skipped"]:
        lines.append("  ── skip reasons ──")
        lines += [f"  {s}" for s in f["skipped"][-15:]]
    lines.append(f"  full log: {_LOG}")
    return "\n".join(lines)


def _log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _market_open() -> bool:
    ts, val = _state["clock_cache"]
    if time.time() - ts < 300:
        return val
    try:
        import tools.trading as TRD
        val = bool(TRD._api("GET", "/v2/clock").get("is_open"))
    except Exception:
        val = False
    _state["clock_cache"] = (time.time(), val)
    return val


def _snapshots(symbols: list) -> dict:
    """Batched snapshots with daily + prev-daily bars for %chg and vol ratio."""
    import tools.trading as TRD
    out = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        try:
            data = TRD._data("/v2/stocks/snapshots", params={"symbols": ",".join(chunk)})
        except Exception:
            continue
        for sym, snap in (data or {}).items():
            d, pv = snap.get("dailyBar") or {}, snap.get("prevDailyBar") or {}
            price = (snap.get("latestTrade") or {}).get("p") or d.get("c") or 0
            if not price or not pv.get("c"):
                continue
            out[sym] = {
                "price": float(price),
                "chg_pct": (float(price) - pv["c"]) / pv["c"] * 100,
                "vol": d.get("v") or 0, "prev_vol": pv.get("v") or 0,
                "prev_high": pv.get("h") or 0, "day_high": d.get("h") or 0,
            }
        time.sleep(0.12)
    return out


def _alert(kind: str, symbol: str, text: str, throttle_s: int = 1800):
    key = f"{kind}:{symbol}"
    if time.time() - _state["alert_throttle"].get(key, 0) < throttle_s:
        return
    _state["alert_throttle"][key] = time.time()
    _log(f"ALERT {text}")
    try:
        import tools.trade_monitor as MON
        MON._push_user_alert(f"📡 {text}")
    except Exception:
        pass


# ── Queue ──────────────────────────────────────────────────────────────────────

def _removed_today() -> list:
    day, lst = _state["removed_today"]
    return lst if day == str(date.today()) else []


def queue_get() -> list:
    return get(_Q_KEY) or []


def _queue_save(q: list):
    put(_Q_KEY, q[:15])


def queue_action(action: str, symbol: str) -> str:
    """User controls: promote / demote / remove."""
    q = queue_get()
    sym = symbol.upper()
    idx = next((i for i, e in enumerate(q) if e["symbol"] == sym), -1)
    if idx < 0:
        return f"{sym} isn't in the queue."
    if action == "remove":
        q.pop(idx)
        day = str(date.today())
        lst = _removed_today() + [sym]
        _state["removed_today"] = (day, lst)
        _queue_save(q)
        return f"Removed {sym} from the opportunity queue (won't re-add today)."
    if action == "promote" and idx > 0:
        q[idx - 1], q[idx] = q[idx], q[idx - 1]
        q[max(0, idx - 1)]["pinned"] = True
    elif action == "demote" and idx < len(q) - 1:
        q[idx + 1], q[idx] = q[idx], q[idx + 1]
    _queue_save(q)
    return f"{action.title()}d {sym}. Queue: " + " → ".join(e["symbol"] for e in q[:6])


def queue_show() -> str:
    q = queue_get()
    if not q:
        return ("📡 Opportunity queue is empty — the broad scan fills it every "
                "30 min during market hours.")
    lines = ["📡 OPPORTUNITY QUEUE", "━" * 30]
    for i, e in enumerate(q, 1):
        pin = "📌" if e.get("pinned") else "  "
        lines.append(f"{pin}#{i} {e['symbol']:<5} score {e['score']:>3.0f} ${e.get('price', 0):,.2f}")
        for r in e.get("reasons", [])[:2]:
            lines.append(f"     → {r}")
    lines.append("Auto-fills the top pick when capital is free (within risk params).")
    return "\n".join(lines)


# ── BROAD scan ─────────────────────────────────────────────────────────────────

def broad_scan() -> int:
    """Full-roster movers scan → enrich shortlist → rank → queue top 10."""
    import tools.conviction as CVN
    import tools.market as MKT
    try:
        import tools.bridge_map as BRG
    except Exception:
        BRG = None
    roster = CVN._fetch_tradable_universe()
    if not roster:
        return 0
    snaps = _snapshots(roster)

    # First pass: price up >3% on volume ~2x prior day (avg-volume proxy)
    movers = []
    for sym, s in snaps.items():
        if s["chg_pct"] >= 3.0 and s["prev_vol"] and s["vol"] >= 2 * s["prev_vol"]:
            movers.append((sym, s))
    movers.sort(key=lambda x: -(x[1]["chg_pct"] * min(x[1]["vol"] / max(x[1]["prev_vol"], 1), 5)))
    shortlist = movers[:25]
    _log(f"Broad scan: {len(snaps)} snapshotted, {len(movers)} movers, enriching top {len(shortlist)}")

    ranked, removed = [], set(_removed_today())
    for sym, s in shortlist:
        if sym in removed:
            continue
        reasons = [f"+{s['chg_pct']:.1f}% on {s['vol']/max(s['prev_vol'],1):.1f}x volume"]
        score = s["chg_pct"] * 2 + min(s["vol"] / max(s["prev_vol"], 1), 5) * 4
        try:                                    # RSI crossing above 60 from below
            hist = MKT._fetch_history(sym, 30)
            if len(hist) >= 16:
                ta_now, ta_prev = MKT._compute_ta(hist), MKT._compute_ta(hist[:-1])
                r_now, r_prev = ta_now.get("rsi"), ta_prev.get("rsi")
                if r_now and r_prev and r_now > 60 >= r_prev:
                    score += 6
                    reasons.append(f"RSI crossed above 60 ({r_prev:.0f}→{r_now:.0f})")
        except Exception:
            pass
        try:                                    # new 52-week high on rising volume
            import yfinance as yf
            yh = yf.Ticker(sym).fast_info.year_high
            if yh and s["price"] >= float(yh) * 0.995:
                score += 6
                reasons.append("new 52-week high on rising volume")
        except Exception:
            pass
        if BRG:                                 # bridge multiplier
            b = BRG.bridge_bonus(sym)
            if b:
                score += b * 3
                reasons.append(BRG.bridge_line(sym))
        ranked.append({"symbol": sym, "score": round(score, 1), "price": s["price"],
                       "reasons": reasons, "ts": datetime.now().strftime("%H:%M"),
                       "source": "broad", "pinned": False})

    # Deep checks (options flow + short interest) only for the current top 8
    ranked.sort(key=lambda e: -e["score"])
    for e in ranked[:8]:
        try:
            import tools.options_engine as OPT
            uoa = str(OPT.unusual_options_activity(e["symbol"])).lower()
            if "unusual" in uoa or "skew" in uoa and "call" in uoa:
                e["score"] += 5
                e["reasons"].append("unusual call activity")
        except Exception:
            pass
        try:
            import tools.intel as INTEL
            si = str(INTEL.short_interest(e["symbol"]))
            import re as _re
            m = _re.search(r'(\d+(?:\.\d+)?)\s*%', si)
            if m and float(m.group(1)) >= 20:
                e["score"] += 6
                e["reasons"].append(f"short interest {m.group(1)}% — squeeze potential")
        except Exception:
            pass
    ranked.sort(key=lambda e: -e["score"])

    # Merge: user-pinned entries stay on top, fresh ranked fill the rest
    pinned = [e for e in queue_get() if e.get("pinned") and e["symbol"] not in removed]
    fresh = [e for e in ranked if e["symbol"] not in {p["symbol"] for p in pinned}]
    _queue_save(pinned + fresh[:10])
    _state["broad_top20"] = [e["symbol"] for e in ranked[:20]]
    _state["broad_runs"] += 1
    f = _freq_today()
    f["scans_broad"] += 1
    f["found"] += len(fresh[:10])
    _log(f"Broad scan done: queue = {[e['symbol'] for e in (pinned + fresh[:10])]}")
    return len(ranked)


# ── NARROW scan ────────────────────────────────────────────────────────────────

def narrow_scan() -> int:
    """Fast sweep of watchlist + positions + last broad top-20 for instant alerts."""
    import tools.trading as TRD
    import tools.market as MKT
    targets = set(_state["broad_top20"])
    try:
        targets |= set(MKT._load(MKT._WATCHLIST_FILE, {}).keys())
    except Exception:
        pass
    try:
        targets |= {p["symbol"] for p in TRD._api("GET", "/v2/positions")}
    except Exception:
        pass
    if not targets:
        return 0
    targets = sorted(targets)[:60]
    snaps = _snapshots(targets)

    # 5-minute movement via 5Min bars (batched)
    bars5 = {}
    try:
        data = TRD._data("/v2/stocks/bars", params={
            "symbols": ",".join(targets), "timeframe": "5Min", "limit": "3"})
        for sym, bl in (data.get("bars") or {}).items():
            if len(bl) >= 2:
                bars5[sym] = (bl[-2]["c"], bl[-1]["c"], bl[-1]["v"])
    except Exception:
        pass

    for sym in targets:
        s = snaps.get(sym)
        if not s:
            continue
        if sym in bars5:
            prev_c, last_c, last_v = bars5[sym]
            move5 = (last_c - prev_c) / prev_c * 100 if prev_c else 0
            if abs(move5) >= 1.5:
                _alert("move5", sym, f"{sym} moved {move5:+.1f}% in 5 minutes (${last_c:.2f})")
            avg5 = (s["prev_vol"] / 78) if s["prev_vol"] else 0
            if avg5 and last_v >= 5 * avg5:
                _alert("volspike", sym, f"{sym} volume spike: {last_v/avg5:.0f}x the 5-min average")
        if s["prev_high"] and s["price"] > s["prev_high"]:
            _alert("dayhigh", sym, f"{sym} broke above prior-day high "
                                   f"(${s['price']:.2f} > ${s['prev_high']:.2f})", 14400)
    _state["narrow_runs"] += 1
    _freq_today()["scans_narrow"] += 1
    return len(targets)


# ── Auto-fill from the queue ───────────────────────────────────────────────────

def _auto_fill():
    """Open the top queue opportunity whenever capital + autonomy + conviction
    allow it — purely quality-gated (conviction threshold, capital, guard
    checks below), no time-based or count-based throttle. Every skip is
    counted with its reason so the user can see found vs executed vs skipped
    ('trade frequency')."""
    q = [e for e in queue_get() if not e.get("opened")]
    if not q:
        return
    try:
        import tools.risk_params as RP
        import tools.trading as TRD
        e = q[0]
        ok, why = RP.autonomy_gate(e["symbol"])
        if not ok:
            _skip(e["symbol"], f"autonomy gate — {why}")
            return
        p = RP.get_params()
        import tools.trade_monitor as MON
        conv = MON._get_conviction(e["symbol"])
        _state["last_fill"] = time.time()
        min_bar = RP.min_conviction_engine()
        if conv < min_bar:
            _skip(e["symbol"], f"conviction {conv} < bar {min_bar}")
            return
        # Conviction-tier allocation of available capital (Bug-2 spec)
        budget = TRD._budget_remaining()
        spend = min(budget, RP.position_size_dollars(max(0, conv)))
        if e["price"] > spend:
            _skip(e["symbol"], f"price ${e['price']:.2f} > allocation ${spend:,.2f}")
            return
        ok2, why2 = TRD._guard(e["symbol"])
        if not ok2:
            _skip(e["symbol"], f"guard — {why2}")
            return
        try:
            import tools.account_sync as SYNC
            ok3, why3 = SYNC.pre_trade_check(e["symbol"], spend)
            if not ok3:
                _skip(e["symbol"], f"pre-trade — {why3}")
                return
        except Exception:
            pass
        qty = int(spend // e["price"])
        if qty < 1:
            _skip(e["symbol"], f"allocation ${spend:,.2f} below one share (${e['price']:.2f})")
            return
        price = e["price"]
        stop_p = round(price * (1 - p["stop_loss_pct"] / 100), 2)
        target_p = round(price * (1 + p["take_profit_pct"] / 100), 2)
        r = TRD._api("POST", "/v2/orders", {
            "symbol": e["symbol"], "qty": str(qty), "side": "buy",
            "type": "market", "time_in_force": "day", "order_class": "bracket",
            "take_profit": {"limit_price": f"{target_p:.2f}"},
            "stop_loss": {"stop_price": f"{stop_p:.2f}"}})
        reasoning = f"Opportunity-queue fill (conviction {conv}/100):\n  " + "\n  ".join(e["reasons"])
        MON.register_trade(e["symbol"], qty, price, stop_p, target_p, conv, reasoning)
        e["opened"] = True
        _queue_save([x for x in queue_get() if x["symbol"] != e["symbol"]])
        _freq_today()["executed"] += 1
        msg = (f"✅ Bought {e['symbol']} ${qty * price:,.0f} — {e['reasons'][0] if e['reasons'] else 'opportunity-queue setup'}, "
               f"conviction {conv}/100, stop ${stop_p}, target ${target_p}. "
               f"Say 'explain {e['symbol']}' for full analysis.")
        _log(msg)
        MON._push_user_alert(msg)
    except Exception as ex:
        _log(f"Auto-fill error: {ex}")


# ── Scheduler ──────────────────────────────────────────────────────────────────

def _loop():
    _log("Opportunity scanner started (broad 30min / narrow 5min, market hours)")
    while _state["running"]:
        try:
            if _market_open():
                now = time.time()
                if now - _state["last_broad"] >= 1800:
                    _state["last_broad"] = now
                    broad_scan()
                    # Chart-pattern sweep on the watchlist rides the 30-min
                    # cadence (per-ticker detection is too heavy for 5-min)
                    try:
                        import tools.chart_patterns as CP
                        CP.scan_watchlist_alerts()
                    except Exception:
                        pass
                if now - _state["last_narrow"] >= 300:
                    _state["last_narrow"] = now
                    narrow_scan()
                    _auto_fill()
        except Exception as e:
            _log(f"Scanner loop error: {e}")
        time.sleep(30)


def start_scanners() -> str:
    if _state["running"]:
        return "Scanners already running."
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True).start()
    return "Opportunity scanners started (broad 30min / narrow 5min during market hours)."


def scan_status() -> str:
    f = _freq_today()
    return "\n".join([
        "📡 OPPORTUNITY SCANNERS", "━" * 30,
        f"  running: {'yes' if _state['running'] else 'NO'}",
        f"  market open: {'yes' if _market_open() else 'no'}",
        f"  broad runs: {_state['broad_runs']} (every 30 min)",
        f"  narrow runs: {_state['narrow_runs']} (every 5 min)",
        f"  queue: {', '.join(e['symbol'] for e in queue_get()) or 'empty'}",
        f"  today: {f['found']} found / {f['executed']} executed / {len(f['skipped'])} skipped"
        f" — say 'trade frequency' for reasons",
        f"  log: {_LOG}",
    ])
