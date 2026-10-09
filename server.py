"""
server.py  —  JARVIS v4.3
Single-file server. Run: python server.py
"""
import sys, os, json, re, logging, time, secrets, threading
from datetime import datetime
from pathlib import Path
import inspect

# ── Path setup ────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from flask import Flask, request, jsonify, send_file, Response
import tools.tools as T

try:
    import cs2_pro as CS2
    HAS_CS2 = True
except Exception as _cs2e:
    HAS_CS2 = False
    class _CS2Fallback:
        _msg = "CS2 AI unavailable: " + str(_cs2e)
        def __getattr__(self, n):
            return lambda *a, **kw: _CS2Fallback._msg

    CS2 = _CS2Fallback()

try:
    import controller as CTRL
    HAS_CTRL = True
except Exception as _ce:
    HAS_CTRL = False
    class _CtrlFallback:
        _msg = "Controller unavailable: " + str(_ce)
        def __getattr__(self, n):
            return lambda *a, **kw: _CtrlFallback._msg

    CTRL = _CtrlFallback()

try:
    import fallguys_ai as FG
    HAS_FG = True
except Exception as _fge:
    HAS_FG = False
    class _FGFallback:
        _msg = "Fall Guys AI unavailable: " + str(_fge)
        def __getattr__(self, n):
            return lambda *a, **kw: _FGFallback._msg

    FG = _FGFallback()

try:
    import game_ai as G
    HAS_GAME = True
except Exception as _ge:
    HAS_GAME = False
    class _GFallback:
        _msg = "Game AI unavailable (install: pip install pyautogui keyboard vgamepad): " + str(_ge)
        def __getattr__(self, n):
            return lambda *a, **kw: _GFallback._msg

    G = _GFallback()

try:
    import tools.market as MKT
    HAS_MKT = True
except Exception as _mkte:
    HAS_MKT = False
    class _MktFallback:
        _msg = "Market module unavailable: " + str(_mkte)
        def __getattr__(self, n):
            return lambda *a, **kw: _MktFallback._msg
    MKT = _MktFallback()

try:
    import tools.intel as INTEL
    HAS_INTEL = True
except Exception as _ie:
    HAS_INTEL = False
    class _IntelFallback:
        _msg = "Intel module unavailable: " + str(_ie)
        def __getattr__(self, n):
            return lambda *a, **kw: _IntelFallback._msg
    INTEL = _IntelFallback()

try:
    import tools.devices as DEV
    HAS_DEV = True
except Exception as _deve:
    HAS_DEV = False
    class _DevFallback:
        _msg = "Devices module unavailable: " + str(_deve)
        def __getattr__(self, n):
            return lambda *a, **kw: _DevFallback._msg
    DEV = _DevFallback()

try:
    import tools.trading as TRD
    HAS_TRD = True
except Exception as _trde:
    HAS_TRD = False
    class _TrdFallback:
        _msg = "Trading module unavailable: " + str(_trde)
        def __getattr__(self, n):
            return lambda *a, **kw: _TrdFallback._msg
    TRD = _TrdFallback()

try:
    import tools.conviction as CVN
    HAS_CVN = True
except Exception as _cvne:
    HAS_CVN = False
    class _CvnFallback:
        _msg = "Conviction engine unavailable: " + str(_cvne)
        def __getattr__(self, n):
            return lambda *a, **kw: _CvnFallback._msg
    CVN = _CvnFallback()

try:
    import tools.trade_monitor as MON
    HAS_MON = True
except Exception as _mone:
    HAS_MON = False
    class _MonFallback:
        _msg = "Trade monitor unavailable: " + str(_mone)
        def __getattr__(self, n):
            return lambda *a, **kw: _MonFallback._msg
    MON = _MonFallback()

try:
    import tools.social_intel as SOC
    HAS_SOC = True
except Exception as _soce:
    HAS_SOC = False
    class _SocFallback:
        _msg = "Social intel unavailable: " + str(_soce)
        def __getattr__(self, n):
            return lambda *a, **kw: _SocFallback._msg
    SOC = _SocFallback()

try:
    import tools.options_engine as OPT
    HAS_OPT = True
except Exception as _opte:
    HAS_OPT = False
    class _OptFallback:
        _msg = "Options engine unavailable: " + str(_opte)
        def __getattr__(self, n):
            return lambda *a, **kw: _OptFallback._msg
    OPT = _OptFallback()

try:
    import tools.flow_intel as FLOW
    HAS_FLOW = True
except Exception as _flowe:
    HAS_FLOW = False
    class _FlowFallback:
        _msg = "Flow intel module unavailable: " + str(_flowe)
        def __getattr__(self, n):
            return lambda *a, **kw: _FlowFallback._msg
    FLOW = _FlowFallback()

try:
    import tools.jarvis_memory as MEM
    HAS_MEM = True
except Exception as _meme:
    HAS_MEM = False
    class _MemFallback:
        _msg = "Memory system unavailable: " + str(_meme)
        def __getattr__(self, n):
            return lambda *a, **kw: _MemFallback._msg
    MEM = _MemFallback()

try:
    import tools.trade_stream as TAPE
    HAS_TAPE = True
except Exception as _tapee:
    HAS_TAPE = False
    class _TapeFallback:
        _msg = "Live trade stream unavailable: " + str(_tapee)
        def __getattr__(self, n):
            return lambda *a, **kw: _TapeFallback._msg
    TAPE = _TapeFallback()

try:
    import tools.daily_brief as DBRF
    HAS_DBRF = True
except Exception as _dbrfe:
    HAS_DBRF = False
    class _DbrfFallback:
        _msg = "Daily brief module unavailable: " + str(_dbrfe)
        def __getattr__(self, n):
            return lambda *a, **kw: _DbrfFallback._msg
    DBRF = _DbrfFallback()

try:
    import tools.assistant_tools as AST
    HAS_AST = True
except Exception as _aste:
    HAS_AST = False
    class _AstFallback:
        _msg = "Assistant tools unavailable: " + str(_aste)
        def __getattr__(self, n):
            return lambda *a, **kw: _AstFallback._msg
    AST = _AstFallback()

try:
    import tools.risk_params as RPRM
    HAS_RPRM = True
except Exception as _rpe:
    HAS_RPRM = False
    class _RpFallback:
        _msg = "Risk params unavailable: " + str(_rpe)
        def __getattr__(self, n):
            return lambda *a, **kw: _RpFallback._msg
    RPRM = _RpFallback()

try:
    import tools.math_engine as MTH
    HAS_MATH = True
except Exception as _mthe:
    HAS_MATH = False
    class _MathFallback:
        _msg = "Math engine unavailable: " + str(_mthe)
        def __getattr__(self, n):
            return lambda *a, **kw: _MathFallback._msg
    MTH = _MathFallback()

try:
    import tools.intent_match as INTENT
    HAS_INTENT = True
except Exception as _inte:
    HAS_INTENT = False
    class _IntentFallback:
        _msg = "Intent matcher unavailable: " + str(_inte)
        def __getattr__(self, n):
            return lambda *a, **kw: _IntentFallback._msg
    INTENT = _IntentFallback()

try:
    import tools.voice as VOICE
    HAS_VOICE = True
except Exception as _voe:
    HAS_VOICE = False
    class _VoiceFallback:
        _msg = "Voice module unavailable: " + str(_voe)
        def __getattr__(self, n):
            return lambda *a, **kw: _VoiceFallback._msg
    VOICE = _VoiceFallback()

try:
    import tools.grok as GROK
    HAS_GROK = True
except Exception as _groke:
    HAS_GROK = False
    class _GrokFallback:
        _msg = "Grok module unavailable: " + str(_groke)
        def __getattr__(self, n):
            return lambda *a, **kw: _GrokFallback._msg
    GROK = _GrokFallback()


logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("JARVIS")

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV_FILE = ROOT / ".env"
def _load_env():
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v
_load_env()

OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

# ── Auth ──────────────────────────────────────────────────────────────────────
_API_KEY      = os.getenv("JARVIS_API_KEY", "")
_USER_NAME    = os.getenv("JARVIS_USER_NAME", "")
_TUNNEL_FILE  = ROOT / ".tunnel_url"
_SESSIONS_FILE = ROOT / ".sessions.json"

_SESSION_DAYS = 180

def _sessions_load() -> dict:
    try:
        if _SESSIONS_FILE.exists():
            return json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _sessions_save(data: dict):
    try:
        _SESSIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

def _session_create() -> tuple:
    """Create a 180-day session token. Returns (token, expires_iso)."""
    sessions = _sessions_load()
    now = time.time()
    # Prune expired sessions
    sessions = {k: v for k, v in sessions.items() if v.get("expires", 0) > now}
    token   = secrets.token_hex(32)
    expires = now + _SESSION_DAYS * 24 * 3600
    sessions[token] = {
        "created":     datetime.now().isoformat(),
        "expires":     expires,
        "expires_iso": datetime.fromtimestamp(expires).isoformat(),
    }
    _sessions_save(sessions)
    return token, datetime.fromtimestamp(expires).isoformat()

def _session_valid(token: str) -> bool:
    if not token or len(token) < 16:
        return False
    sessions = _sessions_load()
    entry = sessions.get(token)
    if not entry:
        return False
    return entry.get("expires", 0) > time.time()

def _check_auth(req) -> bool:
    """Return True if request is authorized. Always true on localhost."""
    if not _API_KEY:
        return True  # no key configured — open access
    remote = req.remote_addr or ""
    if remote in ("127.0.0.1", "::1", "localhost"):
        return True
    # 180-day session token (X-Session-Token header or ?session= query param)
    sess = req.headers.get("X-Session-Token", "") or req.args.get("session", "")
    if sess and _session_valid(sess):
        return True
    # Raw API key (Authorization Bearer or X-API-Key header or ?key= query param)
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _API_KEY:
        return True
    if req.headers.get("X-API-Key", "") == _API_KEY:
        return True
    if req.args.get("key") == _API_KEY:
        return True
    return False

def _tunnel_url() -> str:
    try:
        if _TUNNEL_FILE.exists():
            data = json.loads(_TUNNEL_FILE.read_text(encoding="utf-8"))
            return data.get("url", "")
    except Exception:
        pass
    return ""

# ── Files ─────────────────────────────────────────────────────────────────────
_FILES_DIR = Path.home() / "Documents" / "JARVIS"
_ALLOWED_EXT = {".pdf", ".xlsx", ".xls", ".csv", ".txt", ".png", ".jpg",
                ".docx", ".json", ".html", ".mp3", ".wav", ".zip", ".ab"}

app = Flask(__name__)

@app.after_request
def cors(r):
    r.headers.update({
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-API-Key,X-Session-Token,Authorization",
    })
    return r

@app.route("/", methods=["OPTIONS"])
@app.route("/<path:p>", methods=["OPTIONS"])
def opts(p=""): return "", 204

history = []

# ── Tool registry ──────────────────────────────────────────────────────────────
def _c(params, fn):
    """Strip params not accepted by the function."""
    try:
        valid = set(inspect.signature(fn).parameters)
        return {k: v for k, v in params.items() if k in valid}
    except Exception:
        return params

TOOLS = {




    # ── CS2 AI ───────────────────────────────────────────────
    "cs2_launch":       lambda p: CS2.cs2_launch(),
    "cs2_start":        lambda p: CS2.cs2_start(**p),
    "cs2_stop":         lambda p: CS2.cs2_stop(),
    "cs2_pause":        lambda p: CS2.cs2_pause(),
    "cs2_status":       lambda p: CS2.cs2_status(),
    "cs2_aim_assist":   lambda p: CS2.cs2_aim_assist(),
    "cs2_advice":       lambda p: CS2.cs2_advice(**p),
    "cs2_practice":     lambda p: CS2.cs2_practice(**p),
    "cs2_sensitivity":  lambda p: CS2.cs2_sensitivity(**p),
    "cs2_vision_test":  lambda p: CS2.cs2_vision_test(),
    "cs2_weapon":       lambda p: CS2.cs2_weapon(**p),
    "cs2_reaction":     lambda p: CS2.cs2_reaction_time(**p),
    "cs2_resume":       lambda p: CS2.cs2_resume(),
    "cs2_input_test":   lambda p: CS2.cs2_input_test(),
    "cs2_combat_start":  lambda p: CS2.cs2_combat_start(**p),
    "cs2_combat_stop":   lambda p: CS2.cs2_combat_stop(),
    "cs2_combat_status": lambda p: CS2.cs2_combat_status(),
    "cs2_combat_pause":  lambda p: CS2.cs2_combat_pause() if hasattr(CS2,"cs2_combat_pause") else "ok",
    "cs2_test_shot":     lambda p: CS2.cs2_test_shot() if hasattr(CS2,"cs2_test_shot") else "ok",
    "cs2_setup_yolo":    lambda p: CS2.cs2_setup_yolo(),
    "cs2_yolo_status":  lambda p: CS2.cs2_yolo_status(),
    "cs2_yolo_test":    lambda p: CS2.cs2_yolo_test(),
    "cs2_yolo_conf":    lambda p: CS2.cs2_yolo_confidence(**p),
    "cs2_set_map":      lambda p: CS2.cs2_set_map(**p),
    "cs2_callout":      lambda p: CS2.cs2_callout(**p),
    "cs2_where_to_look":lambda p: CS2.cs2_where_to_look(**p),
    "cs2_tips":         lambda p: CS2.cs2_tips(**p),
    "cs2_map_list":     lambda p: CS2.cs2_map_list(),
    "cs2_agent_list":   lambda p: CS2.cs2_agent_list(),
    "cs2_position":     lambda p: CS2.cs2_position_advice(**p),
    "cs2_takeover":     lambda p: CS2.cs2_takeover_status(),
    # ── Hardware Controller ───────────────────────────────────
    "ctrl_list_devices":   lambda p: CTRL.ctrl_list_devices(),
    "ctrl_install_vigem":  lambda p: CTRL.ctrl_install_vigem(),
    "ctrl_status":         lambda p: CTRL.ctrl_status(),
    "ctrl_press":          lambda p: CTRL.ctrl_press(**p),
    "ctrl_trigger":        lambda p: CTRL.ctrl_trigger(**p),
    "ctrl_stick":          lambda p: CTRL.ctrl_stick(**p),
    "ctrl_move":           lambda p: CTRL.ctrl_move(**p),
    "ctrl_look":           lambda p: CTRL.ctrl_look(**p),
    "ctrl_jump":           lambda p: CTRL.ctrl_jump(),
    "ctrl_dive":           lambda p: CTRL.ctrl_dive(),
    "ctrl_grab":           lambda p: CTRL.ctrl_grab(),
    "ctrl_shoot":          lambda p: CTRL.ctrl_shoot(),
    "ctrl_reset":          lambda p: CTRL.ctrl_reset(),
    "fallguys_ctrl_start": lambda p: CTRL.fallguys_ctrl_start(**p),
    "fallguys_ctrl_stop":  lambda p: CTRL.fallguys_ctrl_stop(),
    "fallguys_ctrl_pause": lambda p: CTRL.fallguys_ctrl_pause(),
    "fallguys_ctrl_status":lambda p: CTRL.fallguys_ctrl_status(),
    "fallguys_ctrl_test":  lambda p: CTRL.fallguys_ctrl_test(),
    "fallguys_smart_start":  lambda p: CTRL.fallguys_smart_start(**p),
    "fallguys_smart_stop":   lambda p: CTRL.fallguys_smart_stop(),
    "fallguys_smart_pause":  lambda p: CTRL.fallguys_smart_pause(),
    "fallguys_smart_status": lambda p: CTRL.fallguys_smart_status(),
    "fallguys_vision_test":  lambda p: CTRL.fallguys_vision_test(),
    "fallguys_stats":        lambda p: CTRL.fallguys_stats(),
    # ── Fall Guys AI ─────────────────────────────────────────
    "fallguys_launch":      lambda p: FG.fallguys_launch(),
    "fallguys_start":       lambda p: FG.fallguys_start(**p),
    "fallguys_stop":        lambda p: FG.fallguys_stop(),
    "fallguys_pause":       lambda p: FG.fallguys_pause(),
    "fallguys_status":      lambda p: FG.fallguys_status(),
    "fallguys_advice":      lambda p: FG.fallguys_advice(**p),
    "fallguys_teach":       lambda p: FG.fallguys_teach(**p),
    "fallguys_analyze":     lambda p: FG.fallguys_analyze(),
    "fallguys_minigames":   lambda p: FG.fallguys_minigame_list(),
    "fallguys_controller":  lambda p: FG.fallguys_set_controller(**p),
    "fallguys_test_input":  lambda p: FG.fallguys_test_input(),
    # ── Game AI ───────────────────────────────────────────────
    "game_load":          lambda p: G.game_load(**p),
    "game_advice":        lambda p: G.game_advice(**p),
    "game_analyze":       lambda p: G.game_analyze(),
    "game_move":          lambda p: G.game_move(**p),
    "game_look":          lambda p: G.game_look(**p),
    "game_shoot":         lambda p: G.game_shoot(**p),
    "game_action":        lambda p: G.game_action(**p),
    "game_sequence":      lambda p: G.game_sequence(**p),
    "game_auto_fps":      lambda p: G.game_auto_fps(**p),
    "game_stop":          lambda p: G.game_stop(),
    "game_pause":         lambda p: G.game_pause(),
    "game_record_start":  lambda p: G.game_record_start(),
    "game_record_stop":   lambda p: G.game_record_stop(),
    "game_replay":        lambda p: G.game_replay(**p),
    "game_detect_targets":lambda p: G.game_detect_targets(),
    "game_press_key":     lambda p: G.game_press_key(**p),
    "game_hold_key":      lambda p: G.game_hold_key(**p),
    "game_hotkey":        lambda p: G.game_hotkey(**p),
    "xbox_press":         lambda p: G.xbox_press(**p),
    "xbox_stick":         lambda p: G.xbox_stick(**p),
    "xbox_trigger":       lambda p: G.xbox_trigger(**p),
    "list_game_profiles": lambda p: G.list_game_profiles(),
    # ── Live Trading (Alpaca) ──────────────────────────────────
    "market_clock":       lambda p: TRD.market_clock(),
    "trading_account":    lambda p: TRD.trading_account(),
    "trading_positions":  lambda p: TRD.trading_positions(),
    "trading_pnl":        lambda p: TRD.trading_pnl_today(),
    "trading_orders":     lambda p: TRD.trading_orders(**p),
    "trading_history":    lambda p: TRD.trading_history(**p),
    "trading_buy":        lambda p: TRD.trading_buy(**p),
    "trading_sell":       lambda p: TRD.trading_sell(**p),
    "trading_bracket":    lambda p: TRD.trading_bracket(**p),
    "trading_trail":      lambda p: TRD.trading_trail_stop(**p),
    "trading_cancel":     lambda p: TRD.trading_cancel(**p),
    "trading_close":      lambda p: TRD.trading_close_position(**p),
    "trading_close_all":  lambda p: TRD.trading_close_all(),
    "trading_quote":      lambda p: TRD.trading_quote(**p),
    "trading_snapshot":   lambda p: TRD.trading_snapshot(**p),
    "trading_bars":       lambda p: TRD.trading_bars(**p),
    "trading_size":       lambda p: TRD.trading_position_size(**p),
    "trading_risk":       lambda p: TRD.trading_risk_status(),
    "trading_perf":       lambda p: TRD.trading_performance(**p),
    "strategy_momentum":  lambda p: TRD.strategy_momentum_scan(**p),
    "strategy_orb":       lambda p: TRD.strategy_orb(**p),
    "strategy_vwap":      lambda p: TRD.strategy_vwap(**p),
    "strategy_gaps":      lambda p: TRD.strategy_gap_scanner(**p),
    "strategy_execute":   lambda p: TRD.strategy_auto_execute(**p),
    "trading_budget":     lambda p: TRD.trading_budget_status(),
    # ── Conviction Engine ($100 → $10K Mission) ───────────────
    "conviction_score":   lambda p: CVN.conviction_score(**p),
    "geo_brief":          lambda p: CVN.geopolitical_brief(),
    "auto_hunt":          lambda p: CVN.auto_hunt(**_c(p, CVN.auto_hunt)),
    "market_regime":      lambda p: CVN.market_regime(),
    "sector_heat":        lambda p: CVN.sector_heat(),
    "squeeze_scan":       lambda p: CVN.short_squeeze_scan(),
    "nyse_screener":      lambda p: CVN.nyse_budget_screener(**_c(p, CVN.nyse_budget_screener)),
    # ── Goal Engine + Account Sync + Technical/Pattern/Prediction Suite ──
    "goal_set":           lambda p: __import__("tools.goal_engine", fromlist=["x"]).goal_set(
                              p.get("text") or p.get("goal") or p.get("query", "")),
    "goal_status":        lambda p: __import__("tools.goal_engine", fromlist=["x"]).goal_status(),
    "goal_hold":          lambda p: __import__("tools.goal_engine", fromlist=["x"]).goal_hold(),
    "goal_release":       lambda p: __import__("tools.goal_engine", fromlist=["x"]).goal_release(),
    "goal_clear":         lambda p: __import__("tools.goal_engine", fromlist=["x"]).goal_clear(),
    "account_sync_status": lambda p: __import__("tools.account_sync", fromlist=["x"]).account_status(),
    "tech_score":         lambda p: __import__("tools.technical_suite", fromlist=["x"]).technical_report(
                              p.get("symbol") or p.get("ticker", "")),
    "pattern_detect":     lambda p: __import__("tools.chart_patterns", fromlist=["x"]).pattern_report(
                              p.get("symbol") or p.get("ticker", "")),
    "price_prediction":   lambda p: __import__("tools.prediction", fromlist=["x"]).predict(
                              p.get("symbol") or p.get("ticker", "")),
    # ── Trade Monitor & Portfolio ─────────────────────────────
    "monitor_start":      lambda p: MON.start_monitor(),
    "monitor_stop":       lambda p: MON.stop_monitor(),
    "monitor_status":     lambda p: MON.monitor_status(),
    "portfolio":          lambda p: MON.portfolio_dashboard(),
    "trade_why":          lambda p: MON.trade_reasoning(p.get("symbol","")),
    "trade_skip_why":     lambda p: MON.skip_reason(p.get("symbol","")),
    "trades_by_result":   lambda p: MON.trades_by_result(p.get("result","")),
    "trades_by_date":     lambda p: MON.trades_by_date(p.get("date","")),
    "trades_by_reason":   lambda p: MON.trades_by_reason(p.get("keyword","")),
    "trade_history_full": lambda p: MON.trade_history_full(),
    "options_threshold_set": lambda p: RPRM.set_options_threshold(p.get("value", p.get("threshold", 55))),
    "market_outlook_show":  lambda p: __import__("tools.market_outlook", fromlist=["x"]).outlook_report(),
    "market_outlook_force": lambda p: __import__("tools.market_outlook", fromlist=["x"]).force_mode(p.get("mode","")),
    "market_outlook_ignore":lambda p: __import__("tools.market_outlook", fromlist=["x"]).ignore_today(),
    "market_outlook_resume":lambda p: __import__("tools.market_outlook", fromlist=["x"]).resume_outlook(),
    "market_outlook_auto":  lambda p: __import__("tools.market_outlook", fromlist=["x"]).resume_auto(),
    # ── Daily Intelligence Cycle (autonomous morning brief + evening review) ──
    "daily_brief":        lambda p: DBRF.show_daily_brief(),
    "brief_rebuild":      lambda p: DBRF.build_morning_brief(force=True),
    "evening_review":     lambda p: DBRF.show_evening_review(),
    "evening_rebuild":    lambda p: DBRF.build_evening_review(force=True),
    "brief_status":       lambda p: DBRF.scheduler_status(),
    "intent_status":      lambda p: INTENT.intent_status(),
    "autonomy_status":    lambda p: RPRM.params_report(),
    "risk_params_show":   lambda p: RPRM.params_report(),
    # ── Opportunity scanning + cross-sector bridge map ────────────────────────
    "queue_show":         lambda p: __import__("tools.opportunity_scan", fromlist=["x"]).queue_show(),
    "queue_action":       lambda p: __import__("tools.opportunity_scan", fromlist=["x"]).queue_action(
                              p.get("action", "remove"), p.get("symbol", "")),
    "scan_status":        lambda p: __import__("tools.opportunity_scan", fromlist=["x"]).scan_status(),
    "trade_frequency":    lambda p: __import__("tools.opportunity_scan", fromlist=["x"]).frequency_report(),
    "bridge_show":        lambda p: __import__("tools.bridge_map", fromlist=["x"]).bridge_show(),
    "bridge_add":         lambda p: __import__("tools.bridge_map", fromlist=["x"]).bridge_add(
                              p.get("ticker", ""), p.get("sectors", ""),
                              p.get("category", "discovered"), p.get("note", "")),
    # ── Political intelligence (role-based) ────────────────────────────────────
    "political_briefing": lambda p: __import__("tools.political_intel", fromlist=["x"]).political_briefing(),
    "geo_risk":           lambda p: __import__("tools.political_intel", fromlist=["x"]).geo_risk_show(),
    "political_movers":   lambda p: __import__("tools.political_intel", fromlist=["x"]).political_movers(),
    "role_news":          lambda p: __import__("tools.political_intel", fromlist=["x"]).role_news(
                              p.get("role") or p.get("person") or p.get("query", "")),
    "person_impact":      lambda p: __import__("tools.political_intel", fromlist=["x"]).person_impact(
                              p.get("name") or p.get("person", "")),
    "role_set":           lambda p: __import__("tools.political_intel", fromlist=["x"]).role_set(
                              p.get("role", ""), p.get("holder") or p.get("name", "")),
    "political_scan_now": lambda p: "\n".join(
                              f"[{h['score']}/10] {h['who']}: {h['note']}" for h in
                              __import__("tools.political_intel", fromlist=["x"]).scan_political(push=False)
                          ) or "Scan complete — no new political catalysts.",
    "political_status":   lambda p: __import__("tools.political_intel", fromlist=["x"]).scanner_status(),
    # ── Everyday Assistant (free/keyless APIs or fully local) ─────────────────
    "weather_now":        lambda p: AST.weather_now(p.get("location") or p.get("city", "")),
    "remind":             lambda p: AST.remind(p.get("text") or p.get("reminder")
                                               or p.get("description", "")),
    "reminders_list":     lambda p: AST.reminders_list(),
    "reminder_cancel":    lambda p: AST.reminder_cancel(p.get("which") or p.get("id", "")),
    "unit_convert":       lambda p: AST.unit_convert(p.get("query") or p.get("expression", "")),
    "currency_convert":   lambda p: AST.currency_convert(p.get("query") or p.get("expression", "")),
    "world_time":         lambda p: AST.world_time(p.get("place") or p.get("city")
                                                   or p.get("location", "")),
    "define_word":        lambda p: AST.define_word(p.get("word") or p.get("term", "")),
    "roll_random":        lambda p: AST.roll_random(p.get("query") or p.get("text", "")),
    "password_gen":       lambda p: AST.password_gen(p.get("length", 16), p.get("count", 3)),
    "next_holidays":      lambda p: AST.next_holidays(p.get("country", "US")),
    "file_find":          lambda p: AST.file_find(p.get("name") or p.get("filename", ""),
                                                  p.get("where", "")),
    # ── Math & Quant Lab (fully local: sympy/numpy/scipy) ─────────────────────
    "math_solve":         lambda p: MTH.compute(p.get("expression") or p.get("expr")
                                                or p.get("query") or p.get("problem", "")),
    "pattern_scan":       lambda p: MTH.pattern_scan(p.get("symbol") or p.get("ticker", ""),
                                                     p.get("days", 180)),
    "pair_correlation":   lambda p: MTH.pair_correlation(
                              p.get("symbol_a") or p.get("a") or p.get("symbol1", ""),
                              p.get("symbol_b") or p.get("b") or p.get("symbol2", ""),
                              p.get("days", 120)),
    # ── Live Trade Tape (real-time, free — Alpaca IEX WebSocket) ──
    "live_movers":        lambda p: TAPE.live_movers(**_c(p, TAPE.live_movers)),
    "live_tape":          lambda p: TAPE.live_tape_signal(p.get("symbol","SPY"))[1],
    "stream_status":      lambda p: TAPE.stream_status(),
    "stream_start":       lambda p: TAPE.start_trade_stream(),
    "stream_stop":        lambda p: TAPE.stop_trade_stream(),
    # ── Social Intelligence ───────────────────────────────────
    "social_report":      lambda p: SOC.social_report(**p),
    "social_signal":      lambda p: SOC.social_report(p.get("symbol","SPY")),
    "stocktwits":         lambda p: SOC.stocktwits_sentiment(p.get("symbol","SPY")).get("summary",""),
    "trending_social":    lambda p: SOC.trending_social_now(),
    "geo_deep":           lambda p: SOC.geopolitical_deep_brief(),
    "wsb_hot":            lambda p: SOC.reddit_wsb_hot(),
    "retail_flow":        lambda p: SOC.retail_trade_flow(p.get("symbol","SPY")).get("summary",""),
    # ── Options Trading ───────────────────────────────────────
    "options_chain":      lambda p: OPT.options_chain(**p),
    "options_scan":       lambda p: OPT.options_best_play(p.get("symbol",""), p.get("conviction",0)),
    "options_buy":        lambda p: OPT.options_buy(**p),
    "options_close":      lambda p: OPT.options_close(**p),
    "options_positions":  lambda p: OPT.options_positions(),
    "options_hunt":       lambda p: OPT.options_auto_hunt(),
    "options_unusual":    lambda p: OPT.unusual_options_activity(p.get("symbol","")),
    # ── Voice I/O ──────────────────────────────────────────────
    "voice_status":       lambda p: VOICE.voice_status(),
    # ── Grok (xAI) — supplementary reasoning tool ─────────────
    "ask_grok":           lambda p: GROK.ask_grok(**_c(p, GROK.ask_grok)),
    "grok_status":        lambda p: GROK.grok_status(),
    # ── Free flow intelligence (homegrown, no paid API) ───────────────────────
    "congress_trades":    lambda p: FLOW.congress_trades(**_c(p, FLOW.congress_trades)),
    "gamma_exposure":     lambda p: FLOW.gamma_exposure(p.get("ticker","")),
    "vix_term_structure": lambda p: FLOW.vix_term_structure(),
    "block_trade_scan":   lambda p: FLOW.block_trade_scan(**_c(p, FLOW.block_trade_scan)),
    # ── Jarvis Memory / Self-Learning ────────────────────────
    "memory_status":      lambda p: MEM.memory_summary(),
    "remember":           lambda p: _stage_memory("remember", p.get("note") or p.get("text", "")),
    "forget":             lambda p: _stage_memory("forget", p.get("keyword") or p.get("note", "")),
    "jarvis_status":      lambda p: MEM.jarvis_offline_status(),
    "conversation_history": lambda p: MEM.conversation_history(**_c(p, MEM.conversation_history)),
    "consolidate_memory":   lambda p: MEM.consolidate_now(),
    # Enhanced TA
    "intraday_analysis":  lambda p: MKT.intraday_analysis(**p),
    "multi_timeframe":    lambda p: MKT.multi_timeframe_analysis(**p),
    # Market Intelligence
    "market_technicals":  lambda p: MKT.market_technicals(**p),
    "trade_signal":       lambda p: MKT.trade_signal(**p),
    "market_scan":        lambda p: MKT.market_scan(**p),
    "chart_price":        lambda p: MKT.chart_price(**_c(p, MKT.chart_price)),
    "watchlist_add":      lambda p: MKT.watchlist_add(**p),
    "watchlist_remove":   lambda p: MKT.watchlist_remove(**p),
    "watchlist_view":     lambda p: MKT.watchlist_view(),
    "watchlist_alert":    lambda p: MKT.watchlist_alert(**p),
    "crypto_price":       lambda p: MKT.crypto_price(**p),
    "crypto_dominance":   lambda p: MKT.crypto_dominance(),
    "crypto_analyze":     lambda p: MKT.crypto_analyze(**p),
    "paper_trade":        lambda p: MKT.paper_trade(**p),
    "paper_portfolio":    lambda p: MKT.paper_portfolio(),
    "web_fetch":          lambda p: MKT.web_fetch(**p),
    "web_research":       lambda p: INTEL.web_research(**_c(p, INTEL.web_research)),
    "news_fetch":         lambda p: MKT.news_fetch(**p),
    "news_sentiment":     lambda p: MKT.news_sentiment(**p),
    "reddit_sentiment":   lambda p: MKT.reddit_sentiment(**p),
    "risk_check":         lambda p: MKT.risk_check(**p),
    "strategy_define":    lambda p: MKT.strategy_define(**p),
    "strategy_run":       lambda p: MKT.strategy_run(),
    "retirement_plan":    lambda p: MKT.retirement_plan(**p),
    "manual_trade_log":   lambda p: MKT.manual_trade_log(**p),
    "market_calendar":    lambda p: MKT.market_calendar(),
    "company_research":   lambda p: MKT.company_research(**p),
    # Online Intelligence
    "fear_greed":         lambda p: INTEL.fear_greed(),
    "insider_trades":     lambda p: INTEL.insider_trades(**p),
    "sec_filings":        lambda p: INTEL.sec_filings(**p),
    "options_chain_yahoo":lambda p: INTEL.options_chain(**p),  # Yahoo Finance options data
    "analyst_ratings":    lambda p: INTEL.analyst_ratings(**p),
    "short_interest":     lambda p: INTEL.short_interest(**p),
    "economic_events":    lambda p: INTEL.economic_events(**p),
    "domain_intel":       lambda p: INTEL.domain_intel(**p),
    "site_status":        lambda p: INTEL.site_status(**p),
    "pwned_check":        lambda p: INTEL.pwned_check(**p),
    "github_trending":    lambda p: INTEL.github_trending(**p),
    "wikipedia":          lambda p: INTEL.wikipedia(**p),
    "translate_text":     lambda p: INTEL.translate_text(**p),
    "page_summary":       lambda p: INTEL.page_summary(**p),
    "patent_search":      lambda p: INTEL.patent_search(**p),
    "job_scan":           lambda p: INTEL.job_scan(**p),
    "company_funding":    lambda p: INTEL.company_funding(**p),
    "web_monitor_add":    lambda p: INTEL.web_monitor_add(**p),
    "web_monitor_check":  lambda p: INTEL.web_monitor_check(),
    "web_monitor_list":   lambda p: INTEL.web_monitor_list(),
    "web_monitor_remove": lambda p: INTEL.web_monitor_remove(**p),
    "price_watch_add":    lambda p: INTEL.price_watch_add(**p),
    "price_watch_check":  lambda p: INTEL.price_watch_check(),
    # Device Intelligence
    "devices_list":       lambda p: DEV.devices_list(),
    "phone_info":         lambda p: DEV.phone_info(**p),
    "phone_backup":       lambda p: DEV.phone_backup(**p),
    "phone_root_plan":    lambda p: DEV.phone_root_plan(**p),
    "phone_adb_shell":    lambda p: DEV.phone_adb_shell(**p),
    "webcam_info":        lambda p: DEV.webcam_info(),
    "smart_devices_scan": lambda p: DEV.smart_devices_scan(),
    "tasmota_plan":       lambda p: DEV.tasmota_plan(**p),
    "device_confirm":     lambda p: DEV.device_confirm(**p),
    "device_pending":     lambda p: DEV.device_pending(),
    "device_log":         lambda p: DEV.device_log(),
    # Grocery
    "grocery_add":       lambda p: T.grocery_add(**_c(p, T.grocery_add)),
    "grocery_show":      lambda p: T.grocery_show(),
    "grocery_remove":    lambda p: T.grocery_remove(**_c(p, T.grocery_remove)),
    "grocery_clear":     lambda p: T.grocery_clear(),
    "grocery_check":     lambda p: T.grocery_check(**_c(p, T.grocery_check)),
    "grocery_order":     lambda p: T.grocery_order(**_c(p, T.grocery_order)),
    "pantry_update":     lambda p: T.pantry_update(**_c(p, T.pantry_update)),
    "pantry_show":       lambda p: T.pantry_show(),
    # Finance
    "finance_add_bill":  lambda p: T.finance_add_bill(**_c(p, T.finance_add_bill)),
    "finance_list_bills":lambda p: T.finance_list_bills(),
    "finance_audit":     lambda p: T.finance_audit(),
    "finance_upcoming":  lambda p: T.finance_upcoming(**_c(p, T.finance_upcoming)),
    "finance_remove_bill":lambda p: T.finance_remove_bill(**_c(p, T.finance_remove_bill)),
    "finance_set_budget":lambda p: T.finance_set_budget(**_c(p, T.finance_set_budget)),
    "finance_show_budget":lambda p: T.finance_show_budget(),
    "finance_log_expense":lambda p: T.finance_log_expense(**_c(p, T.finance_log_expense)),
    "finance_spending":  lambda p: T.finance_spending(**_c(p, T.finance_spending)),
    "finance_add_goal":  lambda p: T.finance_add_goal(**_c(p, T.finance_add_goal)),
    "finance_show_goals":lambda p: T.finance_show_goals(),
    "finance_update_goal":lambda p: T.finance_update_goal(**_c(p, T.finance_update_goal)),
    "finance_health":    lambda p: T.finance_health(),
    # Tasks & Planner
    "task_add":          lambda p: T.task_add(**_c(p, T.task_add)),
    "task_complete":     lambda p: T.task_complete(**_c(p, T.task_complete)),
    "task_show":         lambda p: T.task_show(**_c(p, T.task_show)),
    "task_delete":       lambda p: T.task_delete(**_c(p, T.task_delete)),
    "task_remove":       lambda p: T.task_remove(p.get("spec") or p.get("name")
                                                 or p.get("task") or p.get("keyword", "")),
    "note_add":          lambda p: T.note_add(**_c(p, T.note_add)),
    "note_show":         lambda p: T.note_show(**_c(p, T.note_show)),
    "note_search":       lambda p: T.note_search(**_c(p, T.note_search)),
    "habit_add":         lambda p: T.habit_add(**_c(p, T.habit_add)),
    "habit_complete":    lambda p: T.habit_complete(**_c(p, T.habit_complete)),
    "habit_show":        lambda p: T.habit_show(),
    "morning_briefing":  lambda p: T.morning_briefing(),
    # Health
    "health_add_med":    lambda p: T.health_add_med(**_c(p, T.health_add_med)),
    "health_list_meds":  lambda p: T.health_list_meds(),
    "health_med_reminder":lambda p: T.health_med_reminder(),
    "health_log_workout":lambda p: T.health_log_workout(**_c(p, T.health_log_workout)),
    "health_workout_summary":lambda p: T.health_workout_summary(**_c(p, T.health_workout_summary)),
    "health_log":        lambda p: T.health_log(**_c(p, T.health_log)),
    "health_summary":    lambda p: T.health_summary(),
    # Contacts
    "contact_add":       lambda p: T.contact_add(**_c(p, T.contact_add)),
    "contact_find":      lambda p: T.contact_find(**_c(p, T.contact_find)),
    "contact_list":      lambda p: T.contact_list(),
    "contact_birthdays": lambda p: T.contact_birthdays(**_c(p, T.contact_birthdays)),
    # (legacy reminder_add/reminder_show removed — superseded by remind/reminders_list)
    # Tech / PC
    "tech_open":         lambda p: T.tech_open(**_c(p, T.tech_open)),
    "tech_system_info":  lambda p: T.tech_system_info(),
    "tech_disk_cleanup": lambda p: T.tech_disk_cleanup(),
    "tech_network":      lambda p: T.tech_network(),
    "tech_flush_dns":    lambda p: T.tech_flush_dns(),
    "tech_lock":         lambda p: T.tech_lock(),
    "tech_screenshot":   lambda p: T.tech_screenshot(),
    "tech_volume":       lambda p: T.tech_volume(**_c(p, T.tech_volume)),
    "tech_update":       lambda p: T.tech_update(),
    "tech_shutdown":     lambda p: T.tech_shutdown(**_c(p, T.tech_shutdown)),
    "tech_restart":      lambda p: T.tech_restart(),
    # Web
    "web_open":          lambda p: T.web_open(**_c(p, T.web_open)),
    "web_search":        lambda p: T.web_search(**_c(p, T.web_search)),
    "web_news":          lambda p: T.web_news(**_c(p, T.web_news)),
    "web_directions":    lambda p: T.web_directions(**_c(p, T.web_directions)),
    "web_nearby":        lambda p: T.web_nearby(**_c(p, T.web_nearby)),
    "web_track":         lambda p: T.web_track(**_c(p, T.web_track)),
    # Travel & Food
    "travel_flights":    lambda p: T.travel_flights(**_c(p, T.travel_flights)),
    "travel_hotels":     lambda p: T.travel_hotels(**_c(p, T.travel_hotels)),
    "travel_uber":       lambda p: T.travel_uber(**_c(p, T.travel_uber)),
    "travel_lyft":       lambda p: T.travel_lyft(**_c(p, T.travel_lyft)),
    "food_order":        lambda p: T.food_order(**_c(p, T.food_order)),
    "food_find":         lambda p: T.food_find(**_c(p, T.food_find)),
    "food_ubereats":     lambda p: T.food_ubereats(**_c(p, T.food_ubereats)),
    # Entertainment
    "ent_netflix":       lambda p: T.ent_netflix(**_c(p, T.ent_netflix)),
    "ent_spotify":       lambda p: T.ent_spotify(**_c(p, T.ent_spotify)),
    "ent_youtube":       lambda p: T.ent_youtube(**_c(p, T.ent_youtube)),
    "ent_tickets":       lambda p: T.ent_tickets(**_c(p, T.ent_tickets)),
    "ent_reservation":   lambda p: T.ent_reservation(**_c(p, T.ent_reservation)),
    # Google Apps
    "google_open":       lambda p: T.google_open(**_c(p, T.google_open)),
    "google_new_sheet":  lambda p: T.google_new_sheet(),
    "google_new_doc":    lambda p: T.google_new_doc(),
    "google_new_slide":  lambda p: T.google_new_slide(),
    "google_build_spreadsheet": lambda p: T.google_build_spreadsheet(**_c(p, T.google_build_spreadsheet)),
    # Stocks & Finance Intel
    "stock_quote":       lambda p: T.stock_quote(**_c(p, T.stock_quote)),
    "stock_portfolio":   lambda p: T.stock_portfolio(),
    "stock_order":       lambda p: T.stock_order(**_c(p, T.stock_order)),
    "market_analysis":   lambda p: T.market_analysis(**_c(p, T.market_analysis)),
    "stock_analyze":     lambda p: T.stock_analyze(**_c(p, T.stock_analyze)),
    "stock_due_diligence":lambda p: T.stock_due_diligence(**_c(p, T.stock_due_diligence)),
    "dd_top_picks":       lambda p: T.dd_top_picks(p.get("count", 20)),
    "dd_status":          lambda p: T.dd_status(),
    "stock_compare":     lambda p: T.stock_compare(**_c(p, T.stock_compare)),
    "stock_screen":      lambda p: T.stock_screen(**_c(p, T.stock_screen)),
    "portfolio_build":   lambda p: T.portfolio_build(**_c(p, T.portfolio_build)),
    "market_news":       lambda p: T.market_news(),
    "earnings_cal":      lambda p: T.earnings_cal(),
    "ipo_pipeline":      lambda p: T.ipo_pipeline(),
    # Memory
    "memory_show":       lambda p: T.memory_show(),
    "memory_clear":      lambda p: T.memory_clear(),
}

# ── Memory-change confirmation ─────────────────────────────────────────────────
# remember/forget are STAGED, not executed: Jarvis repeats back exactly what it
# is about to save or delete and waits for a yes/no. Committed in process()
# before any other routing. Pending changes expire after 5 minutes.
_PENDING_MEM = {}

def _stage_memory(action: str, payload: str) -> str:
    payload = (payload or "").strip()
    if not payload:
        return ("Remember what? Say e.g. 'jarvis remember I prefer swing trades'."
                if action == "remember" else
                "Forget what? Give me a keyword, e.g. 'jarvis forget swing trades'.")
    _PENDING_MEM.clear()
    _PENDING_MEM.update({"action": action, "payload": payload, "ts": time.time()})
    if action == "remember":
        return (f"📌 I'm about to remember this permanently:\n\n"
                f"  \"{payload[:250]}\"\n\n"
                f"Say \"yes\" to save it, or \"no\" to cancel.")
    return (f"🗑 I'm about to delete every memory containing:\n\n"
            f"  \"{payload[:120]}\"\n\n"
            f"Say \"yes\" to delete, or \"no\" to keep it.")

_YES_RE = re.compile(r"^(?:yes|y|yep|yeah|yup|sure|confirm|confirmed|correct|do it|"
                     r"go ahead|save it|delete it|please do|ok(?:ay)?)[\s!.]*$", re.I)
_NO_RE  = re.compile(r"^(?:no|n|nope|nah|cancel|don'?t|stop|nevermind|never mind|"
                     r"keep it|leave it)[\s!.]*$", re.I)

def _resolve_pending_memory(user_msg: str):
    """If a staged remember/forget is awaiting confirmation, handle yes/no.
    Returns a reply string when this message resolved it, else None."""
    if not _PENDING_MEM:
        return None
    if time.time() - _PENDING_MEM.get("ts", 0) > 300:
        _PENDING_MEM.clear()
        return None
    msg = user_msg.strip()
    if _YES_RE.match(msg):
        act, pay = _PENDING_MEM["action"], _PENDING_MEM["payload"]
        _PENDING_MEM.clear()
        try:
            return MEM.remember(pay) if act == "remember" else MEM.forget(pay)
        except Exception as e:
            return f"Memory change failed: {e}"
    if _NO_RE.match(msg):
        _PENDING_MEM.clear()
        return "Cancelled — no memory change made."
    # Anything else: the user moved on. Drop the staged change and let the
    # message route normally.
    _PENDING_MEM.clear()
    return None

def run_tool(name, params):
    fn = TOOLS.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return fn(params)
    except TypeError as e:
        # Fan-out params (schema-drift recovery: same value under many keys)
        # over-supply tools that unpack **p directly — retry one key at a time.
        if isinstance(params, dict) and len(params) > 1 and len(set(params.values())) == 1:
            for k, v in params.items():
                try:
                    return fn({k: v})
                except TypeError:
                    continue
                except Exception as e2:
                    log.error(f"Tool error {name}: {e2}")
                    return f"Error: {e2}"
        log.error(f"Tool error {name}: {e}")
        if "required positional argument" in str(e) or "unexpected keyword" in str(e):
            return (f"I tried to run {name} but didn't have the details it needs — "
                    "say it again with the specifics and I'll do it directly.")
        return f"Error: {e}"
    except Exception as e:
        log.error(f"Tool error {name}: {e}")
        return f"Error: {e}"

# ── Direct keyword matching ────────────────────────────────────────────────────
VERBS = r'(?:open|launch|start|show|check|set|add|search|track|order|play|find|get|make|create|build)'

DIRECT = [
    # ── CS2 Combat (must be before generic CS2 patterns) ─────
    (r"stop\s+(?:cs2\s+)?combat",
        "cs2_combat_stop", lambda m: {}),
    (r"pause\s+(?:cs2\s+)?combat|combat\s+pause",
        "cs2_combat_pause", lambda m: {}),
    (r"test\s+aim|aim\s+test|check\s+aim",
        "cs2_test_shot", lambda m: {}),
    (r"onetap\s*test|one\s*tap\s*test",
        "cs2_test_shot", lambda m: {}),
    (r"(?:cs2\s+)?combat(?:\s+mode)?(?:\s+for\s+(\d+)\s*(?:sec|s|min))?",
        "cs2_combat_start", lambda m: {"duration": int(m.group(1) or 60)}),
    (r"start\s+combat(?:\s+for\s+(\d+)\s*(?:sec|s|min))?",
        "cs2_combat_start", lambda m: {"duration": int(m.group(1) or 60)}),
    (r"(?:let|have)\s+jarvis\s+(?:shoot|kill|fight|frag|aim)",
        "cs2_combat_start", lambda m: {"duration": 60}),
    (r"cs2\s+(?:kill|fight|engage|frag|shoot\s+enemies)",
        "cs2_combat_start", lambda m: {"duration": 60}),
    (r"combat\s+status",
        "cs2_combat_status", lambda m: {}),
    # ── YOLO Setup ───────────────────────────────────────────
    (r"(?:setup|install|download|get)\s+(?:cs2\s+)?yolo(?:v?\d+)?",
        "cs2_setup_yolo", lambda m: {}),
    (r"yolo\s+(?:setup|install|download)",
        "cs2_setup_yolo", lambda m: {}),
    (r"yolo\s+(?:status|ready|loaded|working|check)",
        "cs2_yolo_status", lambda m: {}),
    (r"(?:cs2\s+)?yolo\s+(?:test|detect|detection)",
        "cs2_yolo_test", lambda m: {}),
    (r"test\s+(?:cs2\s+)?yolo|yolo\s+test",
        "cs2_yolo_test", lambda m: {}),
    (r"(?:set\s+)?yolo\s+confidence\s+(?:to\s+)?([0-9.]+)",
        "cs2_yolo_conf", lambda m: {"conf": float(m.group(1))}),
    # ── CS2 ──────────────────────────────────────────────────
    (r"(?:launch|open|start)\s+(?:counter.?strike|cs2|cs\s*2)",
        "cs2_launch", lambda m: {}),
    (r"(?:play|start\s+(?:playing|ai\s+for|bot\s+for))\s+(?:counter.?strike|cs2|cs\s*2)(?:\s+for\s+(\d+)\s*min(?:utes?)?)?",
        "cs2_start", lambda m: {"duration_minutes": int(m.group(1) or 20)}),
    (r"stop\s+(?:cs2|counter.?strike)",
        "cs2_stop", lambda m: {}),
    (r"pause\s+(?:cs2|counter.?strike)",
        "cs2_pause", lambda m: {}),
    (r"(?:cs2|counter.?strike)\s+status",
        "cs2_status", lambda m: {}),
    (r"(?:cs2\s+)?aim\s+assist|help\s+me\s+aim\s+in\s+cs2",
        "cs2_aim_assist", lambda m: {}),
    (r"cs2\s+(?:advice|tips|strategy)|how\s+to\s+play\s+cs2",
        "cs2_advice", lambda m: {}),
    (r"cs2\s+practice|practice\s+(?:aim\s+)?(?:in\s+)?cs2",
        "cs2_practice", lambda m: {}),
    (r"set\s+cs2\s+sensitivity\s+(?:to\s+)?([\d.]+)(?:\s+at\s+(\d+)\s*dpi)?",
        "cs2_sensitivity", lambda m: {"sens": float(m.group(1)), "dpi": int(m.group(2) or 800)}),
    (r"test\s+cs2\s+(?:vision|screen)",
        "cs2_vision_test", lambda m: {}),
    (r"test\s+cs2\s+(?:input|control|keyboard|keys?|mouse)",
        "cs2_input_test", lambda m: {}),
    (r"set\s+cs2\s+weapon\s+(?:to\s+)?([\w\s]+)",
        "cs2_weapon", lambda m: {"weapon": m.group(1).strip()}),
    (r"set\s+reaction\s+time\s+(?:to\s+)?(\d+)\s*ms",
        "cs2_reaction", lambda m: {"ms": int(m.group(1))}),
    (r"resume\s+cs2|re.?enable\s+cs2|give\s+(?:me\s+)?(?:back\s+)?cs2\s+control",
        "cs2_resume", lambda m: {}),
    # ── Controller ───────────────────────────────────────────
    (r"(?:list|show|detect|find|what|scan).*(?:devices?|controllers?|gamepads?|inputs?|connected)",
        "ctrl_list_devices", lambda m: {}),
    (r"install\s+vigem|setup\s+(?:virtual\s+)?controller|install\s+controller\s+driver",
        "ctrl_install_vigem", lambda m: {}),
    (r"(?:virtual\s+)?controller\s+status|is\s+(?:the\s+)?controller\s+(?:connected|working)",
        "ctrl_status", lambda m: {}),
    (r"test\s+(?:fall\s*guys\s+)?controller|controller\s+test",
        "fallguys_ctrl_test", lambda m: {}),
    (r"(?:play|start|use\s+controller\s+(?:for|to\s+play))\s+fall\s*guys.*controller(?:\s+for\s+(\d+)\s*min(?:utes?)?)?",
        "fallguys_smart_start", lambda m: {"duration_minutes": int(m.group(1) or 15)}),
    (r"stop\s+fall\s*guys\s+controller|controller\s+stop",
        "fallguys_ctrl_stop", lambda m: {}),
    (r"pause\s+fall\s*guys\s+controller|controller\s+pause",
        "fallguys_ctrl_pause", lambda m: {}),

    # ── Fall Guys (must be BEFORE generic game patterns) ────────
    (r"(?:play|start|bot|auto.?play)\s+fall\s*guys(?:\s+for\s+(\d+)\s*(?:min(?:utes?)?|hours?))?",
        "fallguys_smart_start", lambda m: {"duration_minutes": int(m.group(1) or 15)}),
    (r"(?:launch|open)\s+fall\s*guys",
        "fallguys_launch", lambda m: {}),
    (r"stop\s+fall\s*guys",
        "fallguys_stop", lambda m: {}),
    (r"pause\s+fall\s*guys",
        "fallguys_pause", lambda m: {}),
    (r"fall\s*guys\s+(?:status|how)",
        "fallguys_status", lambda m: {}),
    (r"(?:fall\s*guys\s+advice|help.*fall\s*guys)",
        "fallguys_advice", lambda m: {}),
    (r"fall\s*guys\s+mini.?games|what\s+mini.?games.*fall",
        "fallguys_minigames", lambda m: {}),
    (r"teach\s+me\s+(\w[\w\s]+?)(?:\s+in\s+fall\s*guys)?$",
        "fallguys_teach", lambda m: {"minigame": m.group(1).strip()}),
    (r"use\s+(?:xbox|controller).*fall\s*guys",
        "fallguys_controller", lambda m: {"mode": "xbox"}),
    (r"(?:analyze|what.*happening).*fall\s*guys",
        "fallguys_analyze", lambda m: {}),
    (r"test\s+(?:fall\s*guys\s+)?input|input\s+(?:test|working)",
        "fallguys_test_input", lambda m: {}),
    # ── Generic game AI (after fall guys) ────────────────────
    (r"(?:play|load|start)\s+(?:game\s+)?([a-zA-Z0-9][\w\s'-]{1,35}?)(?:\s+for\s+me)?$",
        "game_load", lambda m: {"game_name": m.group(1).strip()}),
    (r"what\s+(?:game\s+)?(?:profiles?|games?)\s+(?:do\s+you\s+(?:know|support)|are\s+available)",
        "list_game_profiles", lambda m: {}),
    (r"(?:game\s+)?strategy|what\s+should\s+i\s+do\s+in\s+(?:this\s+)?game|help\s+me\s+(?:in\s+)?(?:the\s+)?game",
        "game_advice", lambda m: {}),
    (r"analyze\s+(?:my\s+)?(?:current\s+)?game|look\s+at\s+(?:the\s+)?game\s+and\s+(?:help|tell)",
        "game_analyze", lambda m: {}),
    (r"(?:detect|find|see)\s+(?:any\s+)?(?:enemies|targets|players)\s+(?:on\s+screen)?",
        "game_detect_targets", lambda m: {}),
    (r"(?:auto\s*play|play\s+for\s+me|take\s+over|bot)\s+(?:fps|the\s+game)?(?:\s+for\s+(\d+)\s*(?:sec|min|s|m))?",
        "game_auto_fps", lambda m: {"duration": int(m.group(1) or 30) * (60 if "m" in (m.group(0) or "") else 1)}),
    (r"stop\s+(?:playing|the\s+game\s+ai|auto\s*play|bot)",
        "game_stop", lambda m: {}),
    (r"(?:pause|resume)\s+(?:game\s+)?(?:ai|bot|auto)",
        "game_pause", lambda m: {}),
    (r"start\s+(?:game\s+)?recording",
        "game_record_start", lambda m: {}),
    (r"stop\s+(?:game\s+)?recording",
        "game_record_stop", lambda m: {}),
    (r"move\s+(?:me\s+)?(?:game\s+)?(forward|back(?:ward)?|left|right)(?:\s+for\s+([\d.]+)\s*s(?:ec)?)?",
        "game_move", lambda m: {"direction": m.group(1), "duration": float(m.group(2) or 0.5)}),
    (r"look\s+(?:game\s+)?(left|right|up|down)(?:\s+(\d+))?",
        "game_look", lambda m: {"direction": m.group(1), "amount": int(m.group(2) or 200)}),
    (r"(?:shoot|fire|click)\s+(?:in\s+(?:the\s+)?game)?",
        "game_shoot", lambda m: {}),
    (r"(?:press|hit)\s+(?:the\s+)?xbox\s+(?:button\s+)?(\w+)",
        "xbox_press", lambda m: {"button": m.group(1).lower()}),
    (r"do\s+(.+?)\s+in\s+(.+?)(?:\s+for\s+me)?$",
        "game_sequence", lambda m: {"game_name": m.group(2).strip(), "task": m.group(1).strip()}),
    # URLs — must be first
    (r'(?:https?://\S+|(?:www\.)?\S+\.(?:com|org|net|io|co|tv|app|gov|edu|me|ly)(?:/\S*)?)',
        "web_open", lambda m: {"url": m.group(0).strip()}),
    # Google Apps
    (r'(?:make|create|build).*?(?:spreadsheet|excel)(?:.*?(?:for|about|to track|called)\s+(.+))?',
        "google_build_spreadsheet", lambda m: {"description": (m.group(1) or "general spreadsheet").strip()}),
    (r'open\s+(?:a\s+new\s+)?(?:google\s+)?sheets?|new\s+(?:google\s+)?spreadsheet',
        "google_new_sheet", lambda m: {}),
    (r'open\s+(?:a\s+new\s+)?(?:google\s+)?docs?|new\s+(?:google\s+)?doc',
        "google_new_doc", lambda m: {}),
    (r'open\s+(?:a\s+new\s+)?(?:google\s+)?slides?|new\s+presentation',
        "google_new_slide", lambda m: {}),
    (r'open\s+(?:google\s+)?(drive|gmail|calendar|meet|forms?|photos?)',
        "google_open", lambda m: {"app_name": m.group(1).lower()}),
    # App opening
    (r'(?:open|launch|start)\s+([\w][\w\s]{1,35}?)(?=\s+and\b|\s+then\b|\s*,|\s*$)',
        "tech_open", lambda m: {"app_name": m.group(1).strip().title()}),
    # PC controls
    (r'lock\s+(?:my\s+)?(?:pc|computer|desktop)',  "tech_lock",        lambda m: {}),
    (r'\bscreenshot\b',                             "tech_screenshot",  lambda m: {}),
    (r'disk\s+clean|clean.*disk',                  "tech_disk_cleanup",lambda m: {}),
    (r'check.*(?:wifi|internet|network)|network\s+check', "tech_network", lambda m: {}),
    (r'flush\s+dns',                               "tech_flush_dns",   lambda m: {}),
    (r'windows\s+update',                          "tech_update",      lambda m: {}),
    (r'system\s+info',                             "tech_system_info", lambda m: {}),
    (r'(\d+)\s*min(?:ute)?s?\s+timer|timer\s+(?:for\s+)?(\d+)\s*min',
        "remind", lambda m: {"text": f"set a timer for {m.group(1) or m.group(2)} minutes"}),
    (r'set\s+volume\s+(?:to\s+)?(\d+)',            "tech_volume",      lambda m: {"level":int(m.group(1))}),
    # Info queries
    (r'morning\s+briefing|good\s+morning',         "morning_briefing", lambda m: {}),
    (r'my\s+tasks?|show.*tasks?|\btodo\b',         "task_show",        lambda m: {}),
    (r'my\s+bills?|show.*bills?',                  "finance_list_bills",lambda m: {}),
    (r'audit.*bills?|bill\s+audit',                "finance_audit",    lambda m: {}),
    (r'my\s+goals?|show.*goals?',                  "finance_show_goals",lambda m: {}),
    (r'my\s+budget|show.*budget',                  "finance_show_budget",lambda m: {}),
    (r'my\s+habits?|show.*habits?',                "habit_show",       lambda m: {}),
    # Add/remove must precede the bare "grocery list" (show) pattern — that
    # substring appears inside these phrases too, and first match wins.
    (r'add\s+([\w\s,]+?)\s+to\s+(?:my\s+|the\s+)?(?:grocery|shopping)\s+list',
        "grocery_add", lambda m: {"items": m.group(1).strip()}),
    (r'(?:remove|take|delete)\s+(.+?)\s+(?:from|off)\s+(?:my\s+|the\s+)?(?:grocery|shopping)\s+list',
        "grocery_remove", lambda m: {"item": m.group(1).strip()}),
    (r'clear\s+(?:my\s+|the\s+)?(?:grocery|shopping)\s+list',
        "grocery_clear", lambda m: {}),
    (r'grocery\s+list|shopping\s+list',            "grocery_show",     lambda m: {}),
    (r'my\s+pantry|show.*pantry',                  "pantry_show",      lambda m: {}),
    (r'my\s+contacts?|show.*contacts?',            "contact_list",     lambda m: {}),
    (r'my\s+meds?|my\s+medications?',              "health_list_meds", lambda m: {}),
    (r'health\s+summary',                          "health_summary",   lambda m: {}),
    (r'my\s+notes?|show.*notes?',                  "note_show",        lambda m: {}),
    (r'my\s+reminders?|show.*reminders?|list\s+reminders?', "reminders_list", lambda m: {}),
    (r'financial\s+health|finance\s+check',        "finance_health",   lambda m: {}),
    (r'bills?\s+due|upcoming\s+bills?',            "finance_upcoming", lambda m: {}),
    (r'\bbirthdays?\b',                            "contact_birthdays",lambda m: {}),
    (r'weather\s+(?:in|for|at)\s+(.+?)\s*$',       "weather_now",      lambda m: {"location": m.group(1)}),
    (r'\bweather\b|\bforecast\b',                  "weather_now",      lambda m: {}),
    (r'\bnews\b',                                  "web_news",         lambda m: {}),
    (r'\bspotify\b',                               "ent_spotify",      lambda m: {}),
    (r'\bnetflix\b',                               "ent_netflix",      lambda m: {}),
    (r'\byoutube\b',                               "ent_youtube",      lambda m: {}),
    # Actions with args
    (r'add\s+(?:a\s+)?task[:\s]+(.+)',             "task_add",         lambda m: {"task":m.group(1).strip()}),
    # Task removal — every phrasing routes to task_remove; grocery_remove
    # requires an explicit grocery/shopping mention and can never catch these.
    (r'(?:remove|delete|clear)\s+all\s+(?:my\s+)?tasks?\b|clear\s+(?:my\s+)?tasks\b',
        "task_remove", lambda m: {"spec": "all"}),
    (r'(?:remove|delete)\s+tasks?\s+((?:\d+[\s,]*(?:and\s+)?)+)$',
        "task_remove", lambda m: {"spec": m.group(1)}),
    (r'(?:remove|delete)\s+(?:those|these|them|the)?\s*tasks?$',
        "task_remove", lambda m: {"spec": "those"}),
    (r'(?:remove|delete)\s+(?:the\s+)?task[:\s]+(.+)',
        "task_remove", lambda m: {"spec": m.group(1).strip()}),
    (r'(?:remove|delete)\s+(?:the\s+)?(.{2,40}?)\s+task$',
        "task_remove", lambda m: {"spec": m.group(1).strip()}),
    (r'take\s+a\s+note[:\s]+(.+)',                 "note_add",         lambda m: {"content":m.group(1).strip()}),
    (r'uber\s+to\s+([\w\s]+?)(?=\s+and\b|\s*,|\s*$)', "travel_uber",  lambda m: {"destination":m.group(1).strip()}),
    (r'lyft\s+to\s+([\w\s]+?)(?=\s+and\b|\s*,|\s*$)', "travel_lyft",  lambda m: {"destination":m.group(1).strip()}),
    (r'order\s+(?:food\s+from\s+|from\s+)?([\w\s]+?)(?=\s+and\b|\s*,|\s*$)',
        "food_order", lambda m: {"restaurant":m.group(1).strip()}),
    (r'directions?\s+to\s+([\w\s]+?)(?=\s+and\b|\s*,|\s*$)',
        "web_directions", lambda m: {"destination":m.group(1).strip()}),
    (r'track\s+(?:my\s+)?package\s+([\w]+)',       "web_track",        lambda m: {"tracking_number":m.group(1)}),
    # "tell me about the NET position" must beat the generic "positions?"
    # pattern just below (bare substring match on "position" would otherwise
    # win first and lose the specific ticker — routing to trading_positions
    # instead of trade_why).
    (r'tell\s+me\s+about\s+(?:the\s+)?\$?([A-Z]{1,5})\s+position\b',
        "trade_why", lambda m: {"symbol": m.group(1).upper()}),
    # ── Live Trading ─────────────────────────────────────────────
    (r'is\s+(?:the\s+)?market\s+(?:open|closed)|market\s+(?:hours?|clock|status|open)',
        "market_clock",    lambda m: {}),
    (r'(?:my\s+)?trading\s+account|alpaca\s+account|account\s+(?:balance|value|equity)',
        "trading_account", lambda m: {}),
    (r'(?:open\s+)?positions?(?:\s+list)?|what\s+am\s+i\s+holding|my\s+holdings',
        "trading_positions", lambda m: {}),
    (r"today(?:'s)?\s+(?:pnl|p[/&]l|gains?|profit|loss)|how\s+am\s+i\s+doing\s+today",
        "trading_pnl",     lambda m: {}),
    (r'open\s+orders?|pending\s+orders?|unfilled\s+orders?',
        "trading_orders",  lambda m: {"status": "open"}),
    (r'trade\s+history|closed\s+(?:orders?|trades?)|recent\s+trades?',
        "trading_history", lambda m: {}),
    # Buy orders — market
    (r'buy\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*(?:shares?|sh)?(?:\s+at\s+market)?$',
        "trading_buy",
        lambda m: {"symbol": m.group(1).upper(), "qty": float(m.group(2))}),
    # Buy limit
    (r'buy\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*(?:shares?|sh)?\s+(?:limit|at)\s+\$?([\d.]+)',
        "trading_buy",
        lambda m: {"symbol": m.group(1).upper(), "qty": float(m.group(2)),
                   "order_type": "limit", "limit_price": float(m.group(3))}),
    # Buy dollar amount
    (r'buy\s+\$?([\d,]+)\s+(?:of|worth\s+of)\s+([A-Z]{1,5})\b',
        "trading_buy",
        lambda m: {"symbol": m.group(2).upper(), "notional": float(m.group(1).replace(",",""))}),
    # Sell orders — market
    (r'sell\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*(?:shares?|sh)?(?:\s+at\s+market)?$',
        "trading_sell",
        lambda m: {"symbol": m.group(1).upper(), "qty": float(m.group(2))}),
    # Sell limit
    (r'sell\s+([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*(?:shares?|sh)?\s+(?:limit|at)\s+\$?([\d.]+)',
        "trading_sell",
        lambda m: {"symbol": m.group(1).upper(), "qty": float(m.group(2)),
                   "order_type": "limit", "limit_price": float(m.group(3))}),
    # Bracket orders
    (r'bracket\s+(?:order\s+)?([A-Z]{1,5})\s+(\d+)',
        "trading_bracket",
        lambda m: {"symbol": m.group(1).upper(), "qty": int(m.group(2))}),
    (r'bracket\s+(?:order\s+)?([A-Z]{1,5})\s+(\d+)\s+stop\s+([\d.]+)\s+target\s+([\d.]+)',
        "trading_bracket",
        lambda m: {"symbol": m.group(1).upper(), "qty": int(m.group(2)),
                   "stop_loss_pct": float(m.group(3)), "take_profit_pct": float(m.group(4))}),
    # Trailing stop
    (r'trail(?:ing)?\s+stop\s+([A-Z]{1,5})\s+(\d+)(?:\s+([\d.]+)%)?',
        "trading_trail",
        lambda m: {"symbol": m.group(1).upper(), "qty": int(m.group(2)),
                   "trail_pct": float(m.group(3) or 1.5)}),
    # Cancel / close
    (r'cancel\s+all\s+orders?|cancel\s+every(?:thing)?',
        "trading_cancel",  lambda m: {"order_id": "all"}),
    (r'cancel\s+order\s+([A-Za-z0-9\-]{8,})',
        "trading_cancel",  lambda m: {"order_id": m.group(1).strip()}),
    (r'close\s+all\s+positions?|liquidate\s+everything|flatten\s+all',
        "trading_close_all", lambda m: {}),
    (r'close\s+(?:my\s+)?([A-Z]{1,5})\s+position|exit\s+([A-Z]{1,5})',
        "trading_close",
        lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    # Live quotes
    (r'live\s+quote\s+([A-Z]{1,5})|bid\s*(?:ask|\/ask)\s+([A-Z]{1,5})',
        "trading_quote",
        lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    (r'snapshot\s+([A-Z]{1,5}(?:[,\s]+[A-Z]{1,5})*)',
        "trading_snapshot",
        lambda m: {"symbols": m.group(1).upper()}),
    # Intraday bars
    (r'(?:intraday|5.?min|1.?min|15.?min)\s+bars?\s+(?:for\s+)?([A-Z]{1,5})',
        "trading_bars",
        lambda m: {"symbol": m.group(1).upper()}),
    # Position sizing
    (r'(?:position\s+)?siz(?:e|ing)\s+(?:for\s+)?([A-Z]{1,5})',
        "trading_size",    lambda m: {"symbol": m.group(1).upper()}),
    (r'how\s+many\s+shares?\s+of\s+([A-Z]{1,5})',
        "trading_size",    lambda m: {"symbol": m.group(1).upper()}),
    # Risk and performance
    (r'trading\s+(?:risk|status)|risk\s+status|daily\s+loss',
        "trading_risk",    lambda m: {}),
    (r'trading\s+(?:performance|stats?|record)|win\s+rate',
        "trading_perf",    lambda m: {}),
    # Strategy commands
    (r'momentum\s+scan|scan\s+(?:for\s+)?momentum(?:\s+stocks?)?',
        "strategy_momentum", lambda m: {"symbols": "momentum"}),
    (r'momentum\s+scan\s+(watchlist|sp500|tech)',
        "strategy_momentum", lambda m: {"symbols": m.group(1).lower()}),
    (r'(?:auto\s+)?execute\s+([A-Z]{1,5})(?:\s+(momentum|orb|vwap))?',
        "strategy_execute",
        lambda m: {"symbol": m.group(1).upper(), "strategy": m.group(2) or "momentum"}),
    (r'(?:orb|opening\s+range\s+breakout)\s+(?:for\s+|on\s+)?([A-Z]{1,5})',
        "strategy_orb",    lambda m: {"symbol": m.group(1).upper()}),
    (r'vwap\s+(?:trade|setup|signal|analysis)\s+(?:for\s+|on\s+)?([A-Z]{1,5})',
        "strategy_vwap",   lambda m: {"symbol": m.group(1).upper()}),
    (r'gap\s+(?:scanner?|up\s+stocks?|movers?|plays?)|pre.?market\s+gaps?',
        "strategy_gaps",   lambda m: {}),
    # Enhanced TA
    (r'intraday\s+(?:analysis|ta|technicals?)\s+(?:for\s+|on\s+)?([A-Z]{1,5})',
        "intraday_analysis", lambda m: {"symbol": m.group(1).upper()}),
    (r'multi.?timeframe\s+(?:analysis|ta)?\s*(?:for\s+|on\s+)?([A-Z]{1,5})',
        "multi_timeframe", lambda m: {"symbol": m.group(1).upper()}),
    (r'mtf\s+([A-Z]{1,5})',
        "multi_timeframe", lambda m: {"symbol": m.group(1).upper()}),
    # ── Portfolio & Monitor ───────────────────────────────────────
    # Trade explanation / journal queries — MUST come before the generic
    # "portfolio|my trades?|trade history" catch-all below, and before the
    # LLM free-text path, so these never misfire onto the legacy
    # manual_trade_log tool (Bug 1: "check the journal for NET" used to route
    # to a write-only logger and return an empty templated line).
    (r'explain\s+(?:to\s+me\s+)?(?:why\s+)?(?:did\s+you\s+|you\s+)?'
     r'(?:buy|bought|purchase[d]?|trade[d]?|enter(?:ed)?|open(?:ed)?)\s+\$?([A-Z]{1,5})\b',
        "trade_why", lambda m: {"symbol": m.group(1).upper()}),
    (r'explain\s+\$?([A-Z]{1,5})\s+trade\b',
        "trade_why", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:check\s+)?(?:the\s+)?(?:trading\s+)?journal\s+(?:entry\s+)?for\s+\$?([A-Z]{1,5})\b|'
     r'\$?([A-Z]{1,5})\s+journal\s+entry\b',
        "trade_why", lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    (r'what\s+(?:was|is)\s+your\s+reasoning\s+for\s+\$?([A-Z]{1,5})\b|'
     r'justify\s+(?:the\s+)?\$?([A-Z]{1,5})\s+trade\b|'
     r'\$?([A-Z]{1,5})\s+trade\s+explanation\b',
        "trade_why", lambda m: {"symbol": next(g for g in m.groups() if g).upper()}),
    (r"why\s+(?:didn'?t|did\s+not|did\s+you\s+not)\s+(?:you\s+)?(?:buy|trade)\s+\$?([A-Z]{1,5})\b|"
     r"why\s+(?:did\s+you\s+)?(?:skip|pass\s+on)\s+\$?([A-Z]{1,5})\b",
        "trade_skip_why", lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    (r'(?:show\s+(?:me\s+)?)?(?:my\s+)?(losing|winning|losses?|wins?)\s+trades?',
        "trades_by_result",
        lambda m: {"result": "LOSS" if m.group(1).lower().startswith(("los", "loss")) else "WIN"}),
    (r'what\s+did\s+(?:you|i)\s+trade\s+on\s+(.+?)\??$|'
     r'trades?\s+on\s+((?:january|february|march|april|may|june|july|august|september|'
     r'october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|today|yesterday)\b',
        "trades_by_date", lambda m: {"date": (m.group(1) or m.group(2)).strip()}),
    (r'(?:show\s+(?:me\s+)?)?trades?\s+based\s+on\s+(.+?)$',
        "trades_by_reason", lambda m: {"keyword": m.group(1).strip()}),
    (r'(?:show\s+(?:me\s+)?)?(?:my\s+)?(?:full|complete|entire|all)\s+trad(?:e|ing)\s+history|'
     r'show\s+(?:me\s+)?all\s+(?:my\s+)?trades?',
        "trade_history_full", lambda m: {}),
    (r'portfolio|my\s+trades?|trade\s+history|mission\s+report|how\s+(?:are|is)\s+(?:my\s+)?trades?',
        "portfolio", lambda m: {}),
    (r'why\s+(?:did\s+you|did\s+i|are\s+you|\'d\s+you)\s+buy\s+([A-Z]{1,5})\b|'
     # Bare "why TICKER" / "why TICKER trade" — anchored to the WHOLE clause
     # (not just searched anywhere) so it can't swallow ordinary "why do/can/
     # we ..." questions mid-sentence; "?" is optional (both must work).
     r'^why\s+(?!is\b|it\b|so\b|not\b|me\b)([A-Z]{1,5})(?:\s+trade)?[\s!.?]*$|'
     r'(?:trade\s+)?reasoning\s+(?:for\s+|on\s+|behind\s+)([A-Z]{1,5})\b',
        "trade_why", lambda m: {"symbol": (m.group(1) or m.group(2) or m.group(3)).upper()}),
    (r'([A-Z]{1,5})\s+(?:trade\s+)?reasoning|why\s+(?:did\s+you\s+)?trade\s+([A-Z]{1,5})',
        "trade_why", lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    # ── Options threshold + market outlook (plain-English settings) ────
    (r'set\s+options?\s+conviction\s+threshold\s+to\s+(\d+(?:\.\d+)?)',
        "options_threshold_set", lambda m: {"value": float(m.group(1))}),
    (r'(?:force\s+)?(?:go\s+(?:to\s+)?)?(aggressive|standby|selective|cautious)\s+mode|'
     r'go\s+(?:to\s+)?(aggressive|standby|selective|cautious)\b|'
     r'force\s+(?:the\s+)?(?:market\s+)?(?:outlook\s+)?(?:mode\s+)?to\s+(aggressive|standby|selective|cautious|normal)',
        "market_outlook_force",
        lambda m: {"mode": next(g for g in m.groups() if g).lower()}),
    (r'go\s+(?:to\s+)?normal(?:\s+mode)?|force\s+normal\s+mode',
        "market_outlook_force", lambda m: {"mode": "normal"}),
    (r'ignore\s+(?:the\s+)?market\s+outlook\s+today',
        "market_outlook_ignore", lambda m: {}),
    (r'(?:stop\s+ignoring|re-?enable|resume)\s+(?:the\s+)?market\s+outlook(?:\s+gate)?',
        "market_outlook_resume", lambda m: {}),
    (r'resume\s+auto\s+outlook|(?:release|clear)\s+(?:the\s+)?(?:market\s+)?outlook\s+(?:override|force)',
        "market_outlook_auto", lambda m: {}),
    (r'market\s+outlook|outlook\s+(?:score|mode|status)',
        "market_outlook_show", lambda m: {}),
    (r'monitor\s+(?:status|check|running)|trade\s+monitor|is\s+(?:the\s+)?monitor',
        "monitor_status", lambda m: {}),
    (r'start\s+(?:the\s+)?(?:trade\s+)?monitor',
        "monitor_start", lambda m: {}),
    (r'stop\s+(?:the\s+)?(?:trade\s+)?monitor',
        "monitor_stop", lambda m: {}),
    # ── Daily Intelligence Cycle ───────────────────────────────────
    (r'(?:trading\s+|game\s+)?plan\s+for\s+tomorrow|tomorrow\'?s?\s+(?:trading\s+|game\s+)?plan',
        "evening_review", lambda m: {}),
    (r'(?:daily|market|morning)\s+(?:brief(?!ing)|report)|today\'?s?\s+(?:game\s+)?plan|trading\s+plan\s+(?:for\s+)?today|'
     r'what[\'’]?s?\s+(?:the|our)\s+(?:trading\s+|game\s+)?plan\b(?!\s+for\s+tomorrow)',
        "daily_brief", lambda m: {}),
    (r'rebuild\s+(?:the\s+)?(?:daily\s+|market\s+|morning\s+)?brief|(?:build|run)\s+(?:a\s+)?(?:fresh|new)\s+brief',
        "brief_rebuild", lambda m: {}),
    (r'(?:run|build|do)\s+(?:the\s+)?evening\s+review',
        "evening_rebuild", lambda m: {}),
    (r'evening\s+review|daily\s+(?:wrap|recap|review)|how\s+did\s+(?:we|trading)\s+do\s+today',
        "evening_review", lambda m: {}),
    (r'brief\s+(?:scheduler\s+)?status|(?:is\s+the\s+)?(?:daily\s+)?brief\s+(?:running|scheduled)',
        "brief_status", lambda m: {}),
    # Autonomy capability questions get a deterministic, factual answer —
    # the LLM once claimed "I don't have the capability" (it demonstrably does)
    (r'(?:are\s+you|can\s+you|able\s+(?:and\s+capable\s+)?to)\b.*\btrade\b.*\b(?:on\s+your\s+own|autonomous|by\s+yourself|all\s+day|while\s+i(?:\'m|\s+am)?\s+(?:away|gone|out|at\s+work))|'
     r'autonom(?:y|ous)\s+(?:status|trading\s+status)|trade\s+for\s+me\s+while',
        "autonomy_status", lambda m: {}),
    (r'risk\s+param(?:eter)?s?|my\s+risk\s+settings|trading\s+risk\s+settings',
        "risk_params_show", lambda m: {}),
    (r'(promote|demote|remove)\s+([A-Za-z]{1,5})\s+(?:in|from|on)\s+(?:the\s+)?queue',
        "queue_action", lambda m: {"action": m.group(1).lower(), "symbol": m.group(2).upper()}),
    (r'^(?:show\s+(?:me\s+)?(?:the\s+)?)?(?:opportunity\s+)?queue(?:\s+(?:show|status))?$',
        "queue_show", lambda m: {}),
    (r'scan(?:ner)?s?\s+status|(?:broad|narrow)\s+scan\s+status',
        "scan_status", lambda m: {}),
    (r'trade\s+frequency|how\s+many\s+(?:trades?|scans?)\s+(?:today|ran|executed)|'
     r'(?:found|executed|skipped)\s+(?:vs|versus)\s+(?:executed|skipped)',
        "trade_frequency", lambda m: {}),
    (r'bridge\s+(?:map|companies)|cross[\s-]?sector\s+(?:map|companies|bridges)',
        "bridge_show", lambda m: {}),
    # ── Political intelligence ──────────────────────────────────────
    (r'political\s+brief(?:ing)?|political\s+intel(?:ligence)?',
        "political_briefing", lambda m: {}),
    (r'geo(?:political)?\s+risk(?:\s+score)?|risk\s+score',
        "geo_risk", lambda m: {}),
    (r'who\s+is\s+moving\s+(?:the\s+)?markets?(?:\s+today)?|political\s+movers',
        "political_movers", lambda m: {}),
    (r'what\s+(?:is|did)\s+the\s+(president|fed\s+chair|fed|treasury\s+secretary|[a-z\s]{3,25}?)\s+say(?:ing)?(?:\s+(?:about|recently|today).*)?',
        "role_news", lambda m: {"role": m.group(1).strip()}),
    (r'any\s+(fed|president(?:ial)?|opec|treasury|central\s+bank|world\s+leader)\s+news(?:\s+today)?(?:\s+affecting\s+markets)?',
        "role_news", lambda m: {"role": m.group(1).strip()}),
    (r'political\s+news(?:\s+(?:for|on)\s+(.+))?',
        "role_news", lambda m: {"role": (m.group(1) or "president").strip()}),
    (r'(?:run\s+a?\s*)?political\s+scan(?:\s+now)?',
        "political_scan_now", lambda m: {}),
    (r'political\s+(?:scanner\s+)?status',
        "political_status", lambda m: {}),
    (r'(?:the\s+)?([a-z][a-z\s]{3,30}?)\s+is\s+now\s+(?:the\s+)?(president|fed\s+chair|treasury\s+secretary|[a-z\s]{3,30})$',
        "role_set", lambda m: {"holder": m.group(1).strip().title(), "role": m.group(2).strip()}),
    (r'add\s+([A-Za-z]{1,5})\s+to\s+(?:the\s+)?bridge\s+map(?:\s*[:,]?\s*(.+))?',
        "bridge_add", lambda m: {"ticker": m.group(1).upper(), "sectors": (m.group(2) or "").strip()}),
    (r'intent\s+(?:matcher\s+)?status|semantic\s+(?:matcher|status)',
        "intent_status", lambda m: {}),
    (r'tomorrow\'?s?\s+watchlist|watchlist\s+for\s+tomorrow',
        "evening_review", lambda m: {}),
    # ── Live Trade Tape (real-time trade stream) ───────────────────
    (r'live\s+(?:tape\s+)?movers?|what\'?s\s+moving\s+(?:right\s+)?now|real[\s-]?time\s+(?:tape|movers?)',
        "live_movers", lambda m: {}),
    (r'live\s+tape\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "live_tape", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+live\s+tape',
        "live_tape", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:trade\s+)?stream\s+status|is\s+the\s+(?:trade\s+)?stream\s+(?:running|up|connected)',
        "stream_status", lambda m: {}),
    (r'start\s+(?:the\s+)?(?:trade\s+|live\s+)?stream',
        "stream_start", lambda m: {}),
    (r'stop\s+(?:the\s+)?(?:trade\s+|live\s+)?stream',
        "stream_stop", lambda m: {}),
    # ── Everyday Assistant ──────────────────────────────────────────
    (r'remind\s+me\b.*',
        "remind", lambda m: {"text": m.group(0)}),
    (r'set\s+a\s+timer\b.*|start\s+a\s+\d+\s*min.*timer.*',
        "remind", lambda m: {"text": m.group(0)}),
    (r'cancel\s+(?:the\s+)?(?:reminder|timer)\s*#?\s*(\w[\w\s]*)?',
        "reminder_cancel", lambda m: {"which": (m.group(1) or "").strip()}),
    (r'convert\s+\$?[\d.,]+\s*[\w°$€£¥ ]+?\s+(?:to|in|into|as)\s+[\w°$€£¥ ]+|'
     r'how\s+many\s+\w+\s+(?:is|are|in)\s+[\d.]+\s*\w+',
        "unit_convert", lambda m: {"query": m.group(0)}),
    (r'what\s+time\s+is\s+it\s+in\s+(.+?)\s*$|time\s+in\s+([a-z][a-z\s]+?)\s*$',
        "world_time", lambda m: {"place": (m.group(1) or m.group(2) or "").strip()}),
    (r'define\s+["\']?(\w[\w-]*)["\']?\s*$|definition\s+of\s+(\w[\w-]*)|'
     r'what\s+does\s+["\']?(\w[\w-]*)["\']?\s+mean',
        "define_word", lambda m: {"word": m.group(1) or m.group(2) or m.group(3)}),
    (r'flip\s+a?\s*coin|roll\s+(?:a\s+)?(?:die|dice|\d*d\d+).*|random\s+number.*|'
     r'(?:pick|choose)\s+(?:between|one\s+of|from)\s+.+',
        "roll_random", lambda m: {"query": m.group(0)}),
    (r'(?:generate|make|create|give\s+me|need)\s+(?:a\s+)?(?:new\s+|strong\s+|secure\s+)?password(?:\s+(\d+))?',
        "password_gen", lambda m: {"length": int(m.group(1) or 16)}),
    (r'(?:next|upcoming)\s+(?:public\s+|federal\s+)?holidays?(?:\s+in\s+([a-z]{2}))?|'
     r'when\s+is\s+the\s+next\s+holiday',
        "next_holidays", lambda m: {"country": (m.group(1) or "US").upper()
                                    if m.lastindex else "US"}),
    (r'find\s+(?:a\s+|the\s+|my\s+)?file\s+(?:named\s+|called\s+)?(.+)|'
     r'where\s+is\s+(?:the\s+|my\s+)?file\s+(.+)|search\s+(?:my\s+)?(?:pc|computer)\s+for\s+(.+)',
        "file_find", lambda m: {"name": (m.group(1) or m.group(2) or m.group(3) or "").strip()}),
    # ── Math & Quant Lab ────────────────────────────────────────────
    (r'(?:calculate|calc|compute|evaluate|work\s+out|how\s+much\s+is)\s+(.+)',
        "math_solve", lambda m: {"expression": m.group(1)}),
    # "solve" only when it looks like actual math (has = or names an equation)
    (r'solve\s+(.+=.+|(?:the\s+)?(?:equation|system|ode|differential).*|.+\bfor\s+[a-z]\s*$)',
        "math_solve", lambda m: {"expression": m.group(0)}),
    (r'\b(?:(?:\w+\s+)?derivative\s+of|differentiate|integrate|integral\s+of|antiderivative\s+of|limit\s+of|d/d[a-z])\b.*',
        "math_solve", lambda m: {"expression": m.group(0)}),
    (r'\b(?:simplify|expand)\s+[\w\d\s\^\*\+\-/\(\)\.]+$',
        "math_solve", lambda m: {"expression": m.group(0)}),
    (r'(?:prime\s+)?factor(?:s|ize|ise)?\s+(?:of\s+)?\d+$|is\s+\d+\s+(?:a\s+)?prime|(?:gcd|lcm)\s+(?:of\s+)?[\d\s]+$',
        "math_solve", lambda m: {"expression": m.group(0)}),
    (r'^(?:what[\'’]?s?\s+|whats\s+|what\s+is\s+)?([\d.]+\s*%\s*of\s+[\d.,]+)\s*\??$',
        "math_solve", lambda m: {"expression": m.group(1)}),
    # Bare arithmetic: message is nothing but numbers/operators ("2^32", "(5+3)/2")
    (r'^(?:what[\'’]?s?\s+|whats\s+|what\s+is\s+)?([\d\(\)\-][\d\s\.\+\-\*/\^\(\)%!]*[\d\)%!])\s*\??$',
        "math_solve", lambda m: {"expression": m.group(1)}),
    (r'(?:stats|statistics)\s+(?:of|on|for)\s+([\d\.\,\s\-]+)$',
        "math_solve", lambda m: {"expression": "stats of " + m.group(1)}),
    (r'(?:find\s+|hunt\s+|scan\s+for\s+)?patterns?\s+(?:in|for|on)\s+([A-Z]{1,5})\b(?:\s+(?:over\s+)?(\d+)\s*d(?:ays)?)?',
        "pattern_scan", lambda m: {"symbol": m.group(1).upper(),
                                   "days": int(m.group(2)) if m.group(2) else 180}),
    (r'pattern\s+scan\s+([A-Z]{1,5})\b|([A-Z]{1,5})\s+pattern\s+scan',
        "pattern_scan", lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    (r'correlat(?:e|ion)(?:\s+between)?\s+([A-Z]{1,5})\s+(?:and|vs\.?|with|to)\s+([A-Z]{1,5})\b|'
     r'([A-Z]{1,5})\s+vs\.?\s+([A-Z]{1,5})\s+correlation',
        "pair_correlation", lambda m: {"symbol_a": (m.group(1) or m.group(3)).upper(),
                                       "symbol_b": (m.group(2) or m.group(4)).upper()}),
    # ── Capital status + Goal Engine ─────────────────────────────
    (r'budget\s+(?:status|mission|progress)|capital\s+status|mission\s+(?:status|progress)|how.*mission',
        "trading_budget", lambda m: {}),
    (r'(?:trading\s+)?budget\s+(?:cap|limit|remaining)|how\s+much.*budget',
        "trading_budget", lambda m: {}),
    (r'goal\s+(?:status|progress|tracker|check)|how\s+(?:is|am\s+i\s+doing\s+on)\s+(?:the\s+|my\s+)?goal',
        "goal_status", lambda m: {}),
    (r'hold\s+(?:the\s+|my\s+)?profile',
        "goal_hold", lambda m: {}),
    (r'release\s+(?:the\s+|my\s+)?profile|unhold\s+profile',
        "goal_release", lambda m: {}),
    (r'(?:clear|cancel|remove|stop|drop)\s+(?:the\s+|my\s+)?(?:trading\s+)?goal',
        "goal_clear", lambda m: {}),
    (r'set\s+(?:a\s+)?(?:trading\s+)?goal[:\s]+(.+)',
        "goal_set", lambda m: {"text": m.group(1).strip()}),
    (r'account\s+sync(?:\s+status)?|sync(?:ed)?\s+account|alpaca\s+sync',
        "account_sync_status", lambda m: {}),
    # Technical suite / chart patterns / prediction — BEFORE chart_price's
    # generic "chart X" pattern, which would otherwise swallow "chart patterns"
    (r'(?:technical|tech|composite)\s+score\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b|([A-Z]{1,5})\s+(?:technical|tech)\s+score',
        "tech_score", lambda m: {"symbol": (m.group(1) or m.group(2)).upper()}),
    (r'chart\s+patterns?\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b|detect\s+patterns?\s+(?:for\s+|on\s+|in\s+)?([A-Z]{1,5})\b|'
     r'([A-Z]{1,5})\s+chart\s+patterns?',
        "pattern_detect", lambda m: {"symbol": (m.group(1) or m.group(2) or m.group(3)).upper()}),
    (r'predict(?:ion)?\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b|([A-Z]{1,5})\s+(?:price\s+)?prediction|'
     r'where\s+is\s+([A-Z]{1,5})\s+(?:going|headed)',
        "price_prediction", lambda m: {"symbol": (m.group(1) or m.group(2) or m.group(3)).upper()}),
    # ── Conviction Engine ─────────────────────────────────────────
    (r'conviction\s+(?:score|rating|analysis|check)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+conviction\s+(?:score|rating)',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'score\s+([A-Z]{1,5})\b(?!\s+(?:points|goals|runs))',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:geo(?:political)?|macro|political)\s+(?:brief|intelligence|analysis|outlook|update|events?)',
        "geo_brief", lambda m: {}),
    (r'geopolitical\s+trades?|macro\s+trades?|political\s+(?:plays?|trades?)',
        "geo_brief", lambda m: {}),
    (r'market\s+regime|(?:bull|bear|volatile)\s+market\s+(?:now|today|check)',
        "market_regime", lambda m: {}),
    (r'sector\s+(?:heat|rotation|map|strength|hot|momentum)',
        "sector_heat", lambda m: {}),
    (r'which\s+sector|hottest\s+sector|best\s+sector\s+(?:now|today)',
        "sector_heat", lambda m: {}),
    (r'auto\s+hunt(?:\s+and\s+trade)?|hunt\s+(?:for\s+)?(?:best\s+)?(?:trade|stock|setup)',
        "auto_hunt", lambda m: {"auto_trade": "trade" in m.group(0).lower() and "hunt and" in m.group(0).lower()}),
    (r'find\s+(?:the\s+)?(?:best|top|highest)\s+(?:conviction\s+)?(?:trade|setup|stock)',
        "auto_hunt", lambda m: {"auto_trade": False}),
    (r'short\s+squeeze\s+(?:scan|candidates?|plays?|list)|squeeze\s+scan',
        "squeeze_scan", lambda m: {}),
    (r'conviction\s+trade\s+([A-Z]{1,5})\b',
        "strategy_execute", lambda m: {"symbol": m.group(1).upper(), "strategy": "momentum"}),
    (r'(?:nyse|nasdaq|broad|wide)\s+(?:screen(?:er)?|scan|hunt|search)|'
     r'(?:cheap|budget[\s-]friendly|affordable)\s+(?:stocks?|tickers?)(?:\s+with\s+(?:good|great)\s+sentiment)?',
        "nyse_screener", lambda m: {}),
    (r'search\s+(?:the\s+)?(?:whole\s+|full\s+|entire\s+)?(?:nyse|market|nasdaq)\s+for\s+(?:cheap|budget)',
        "nyse_screener", lambda m: {}),
    # ── Social Intelligence ──────────────────────────────────────────────────
    (r'social\s+(?:report|sentiment|intel(?:ligence)?)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+social\s+(?:sentiment|report|intel)',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    (r'stocktwits\s+(?:sentiment\s+|data\s+)?(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "stocktwits", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+stocktwits',
        "stocktwits", lambda m: {"symbol": m.group(1).upper()}),
    (r'reddit\s+wsb\s+(?:hot|trending|now)|wsb\s+(?:hot|trending|now)|what(?:\'s|\s+is)\s+wsb\s+(?:saying|talking)',
        "wsb_hot", lambda m: {}),
    (r'trending\s+(?:social|tickers?|stocks?)\s+(?:now|today|right\s+now)|what(?:\'s|\s+is)\s+trending',
        "trending_social", lambda m: {}),
    (r'geopolitical\s+deep\s+brief|full\s+geo\s+brief|deep\s+geo(?:political)?',
        "geo_deep", lambda m: {}),
    (r'retail\s+(?:flow|order\s+flow|buy(?:ing)?\s+pressure|sentiment)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "retail_flow", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+retail\s+(?:flow|order\s+flow|buy(?:ing)?\s+pressure)',
        "retail_flow", lambda m: {"symbol": m.group(1).upper()}),
    # ── Options Trading ──────────────────────────────────────────────────────
    (r'options?\s+(?:chain|chains?)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "options_chain", lambda m: {"symbol": m.group(1).upper(), "option_type": "call"}),
    (r'([A-Z]{1,5})\s+(?:call|put)\s+options?|options?\s+(?:calls?|puts?)\s+(?:for\s+|on\s+)?([A-Z]{1,5})',
        "options_chain",
        lambda m: {"symbol": (m.group(1) or m.group(2)).upper(),
                   "option_type": "put" if "put" in m.group(0).lower() else "call"}),
    (r'buy\s+(?:call|put)\s+(?:option\s+)?([A-Z0-9]{10,25})',
        "options_buy", lambda m: {"contract_symbol": m.group(1).upper()}),
    (r'options?\s+buy\s+([A-Z0-9]{10,25})',
        "options_buy", lambda m: {"contract_symbol": m.group(1).upper()}),
    (r'close\s+option\s+([A-Z0-9]{10,25})|sell\s+(?:to\s+close\s+)?option\s+([A-Z0-9]{10,25})',
        "options_close",
        lambda m: {"contract_symbol": (m.group(1) or m.group(2)).upper()}),
    (r'options?\s+positions?|my\s+options?|open\s+options?',
        "options_positions", lambda m: {}),
    (r'options?\s+(?:hunt|scan|plays?|opportunities?)|best\s+options?\s+(?:play|trade)',
        "options_hunt", lambda m: {}),
    (r'unusual\s+options?\s+(?:activity\s+)?(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "options_unusual", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+(?:unusual\s+options?|options?\s+flow)',
        "options_unusual", lambda m: {"symbol": m.group(1).upper()}),
    (r'best\s+(?:call|put)\s+(?:option\s+)?(?:for\s+|on\s+)?([A-Z]{1,5})',
        "options_scan",
        lambda m: {"symbol": m.group(1).upper(),
                   "conviction": 65 if "call" in m.group(0).lower() else 35}),
    # ── Free flow intelligence (homegrown, no paid API) ───────────────────────
    (r'dark\s*pool\s*(?:prints?|trades?|activity)?\s*(?:for\s+|on\s+)?([A-Z]{1,5})?\b',
        "block_trade_scan", lambda m: {"ticker": (m.group(1) or "").upper()}),
    (r'block\s+trades?\s*(?:for\s+|on\s+)?([A-Z]{1,5})?\b',
        "block_trade_scan", lambda m: {"ticker": (m.group(1) or "").upper()}),
    (r'(?:greek|gamma)\s+exposure\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b|\bgex\s+([A-Z]{1,5})\b',
        "gamma_exposure", lambda m: {"ticker": (m.group(1) or m.group(2)).upper()}),
    (r'(?:congress(?:ional)?\s+trad(?:es?|ing)|politician\s+trades?)\s*(?:for\s+|on\s+)?([A-Z]{1,5})?\b',
        "congress_trades", lambda m: {"ticker": (m.group(1) or "").upper()}),
    (r'(?:market\s+tide|vix\s+term\s+structure|vix\s+curve)',
        "vix_term_structure", lambda m: {}),
    # ── Memory / Self-Learning ───────────────────────────────────────────────
    (r'(?:jarvis\s+)?remember\s+(?:that\s+|this:?\s*)(.{5,200})',
        "remember", lambda m: {"note": m.group(1).strip()}),
    (r'(?:jarvis\s+)?forget\s+(?:about\s+|that\s+)?(.{3,80})',
        "forget", lambda m: {"keyword": m.group(1).strip()}),
    (r'jarvis\s+(?:memory|what\s+(?:have\s+you\s+)?learned|what\s+do\s+you\s+know\s+about\s+me)',
        "memory_status", lambda m: {}),
    (r'jarvis\s+(?:system\s+)?status|how\s+is\s+jarvis\s+(?:running|doing)|jarvis\s+offline',
        "jarvis_status", lambda m: {}),
    (r'how\s+(?:to\s+)?(?:run|use)\s+jarvis\s+(?:without|offline|no)\s+(?:claude|anthropic|internet)',
        "jarvis_status", lambda m: {}),
    (r'(?:show\s+|our\s+)?conversation\s+history|what\s+have\s+we\s+(?:talked|discussed)|'
     r'what\s+did\s+we\s+(?:talk|discuss)\s+about',
        "conversation_history", lambda m: {}),
    (r'consolidate\s+(?:my\s+|the\s+)?memory|clean\s+up\s+(?:my\s+|the\s+)?(?:conversation\s+)?(?:memory|history)',
        "consolidate_memory", lambda m: {}),
    # ── Stocks & Market ──────────────────────────────────────────
    # Ticker symbols: 1-5 ALL-CAPS letters, but NOT common English words
    # Matches: "TSLA stock", "AAPL price", "quote NVDA"
    (r'\b(?!(?:MY|A|I|IN|AT|OF|IS|IT|ON|THE|FOR|TO|SO|DO|GO|OR|AN|AS|NO|UP|BY|IF|WE|ME|HE|WHO|HIS|HER|GET|SET|PUT|NEW|OLD|ALL|ANY|NOT|BUT|AND|ITS|HOW|WHY|WHAT|WHEN|THIS|THAT|THEN|FROM|WITH|YOUR|BEEN|HAVE|WILL|SOME|MAKE|JUST|LIKE|KNOW|SHOW|WELL|ALSO|INTO|OVER|SUCH)\b)([A-Z]{2,5})\s+(?:stock|ticker|price|quote)\b',
        "stock_quote", lambda m: {"symbol": m.group(1)}),
    (r'(?:quote|price)\s+(?:for\s+|of\s+)?(?!(?:MY|A|THE|IT|ON|AT|IN)\b)([A-Z]{2,5})\b',
        "stock_quote", lambda m: {"symbol": m.group(1)}),
    # Company name + "stock/price" → company_research (handles "Tesla stock", "Apple price", etc.)
    # NOTE: matching is case-insensitive against an already-lowercased message
    # everywhere in this table, so [A-Z] here can't actually detect capitalization
    # — \bstock\b (not "stocks") is what excludes generic category phrases like
    # "growth stocks" / "smaller stocks" from being misread as a company name.
    (r'(?:what(?:\'s|\s+is)\s+)?([a-z][a-z\s]{1,18}?)\s+(?:stock\b(?:\s+price)?|share\s+price|trading\s+at|stock\s+doing)\b',
        "company_research", lambda m: {"company": m.group(1).strip()}),
    # Standalone ticker lookups: "TSLA", "check NVDA", "how's AAPL"
    (r'(?:check|how(?:\'s|\s+is)|what(?:\'s|\s+is))\s+([A-Z]{2,5})\b(?!\s+[a-z]{3,})',
        "stock_quote", lambda m: {"symbol": m.group(1)}),
    (r'my\s+portfolio|show\s+portfolio',           "stock_portfolio",  lambda m: {}),
    (r'market\s+overview|how.*markets?\s+today|how.*stock\s+market',
        "market_analysis",  lambda m: {"topic":"overview"}),
    (r'geopolit|geopolitical.*market',             "market_analysis",  lambda m: {"topic":"geopolitical"}),
    (r'emerging\s+tickers?|growth\s+tickers?',     "market_analysis",  lambda m: {"topic":"emerging"}),
    (r'market\s+forecast|where.*market.*going',    "market_analysis",  lambda m: {"topic":"forecast"}),
    (r'macro\s+analysis|macro\s+outlook',          "market_analysis",  lambda m: {"topic":"macro"}),
    (r'analyze\s+([A-Z]{2,5})\b|deep\s+dive.*\b([A-Z]{2,5})\b',
        "stock_analyze", lambda m: {"symbol":(m.group(1) or m.group(2)).upper()}),
    # Multi-ticker batch MUST precede the single-ticker pattern ("top picks"
    # was being captured as ticker "TOP")
    (r'(?:due\s+diligence|dd)\s+(?:on\s+|for\s+)?(?:(?:my|your|the)\s+)?(?:(\d+)(?:\s*[-–]\s*|\s+to\s+)?(\d+)?\s+)?top\s+picks?',
        "dd_top_picks", lambda m: {"count": int(m.group(2) or m.group(1) or 20)}),
    (r'dd\s+status|due\s+diligence\s+(?:status|progress)|how.*dd\s+(?:batch|run|going)',
        "dd_status", lambda m: {}),
    # match_all lowercases everything, so [A-Z] can't enforce "real ticker" —
    # exclude common English words that follow "due diligence on ..."
    (r'due\s+diligence\s+(?:on|for)\s+'
     r'(?!top\b|now\b|right\b|the\b|my\b|all\b|this\b|that\b|these\b|those\b|some\b|each\b|every\b|a\b|an\b|it\b|them\b)'
     r'([A-Za-z]{1,5})\b',
        "stock_due_diligence", lambda m: {"symbol":m.group(1).upper()}),
    (r'compare\s+([A-Z]{2,5}(?:\s*[,/&]\s*[A-Z]{2,5})+)',
        "stock_compare", lambda m: {"symbols":m.group(1)}),
    (r'screen\s+(?:for\s+)?(growth|value|momentum|dividend|ai|defense|small\s*cap)\s+stocks?',
        "stock_screen", lambda m: {"criteria": m.group(1).strip()}),
    (r'earnings\s+calendar|upcoming\s+earnings',  "earnings_cal",     lambda m: {}),
    (r'ipo\s+pipeline|upcoming\s+ipos?',           "ipo_pipeline",     lambda m: {}),
    # ── Company research — works for ANY company: public, private, IPO-pending ──
    # Catches: "SpaceX IPO", "tell me about Stripe", "is Databricks public",
    #          "research Apple", "what's the ticker for Palantir", etc.
    # Negative lookbehinds exclude "market/broad/thorough/further/more research"
    # used as a NOUN ("you should do more research") rather than a command
    # ("research Apple") — the two read identically to a plain \bresearch\b check.
    (r'(?<!market\s)(?<!broad\s)(?<!thorough\s)(?<!further\s)(?<!additional\s)'
     r'(?<!some\s)(?<!more\s)(?<!good\s)(?<!proper\s)'
     r'\b(?:research|look\s+up|tell\s+me\s+about|deep\s+dive\s+(?:into|on))\s+([\w][\w\s]{2,24}?)(?:\s+(?:stock|company|ipo|ticker))?$',
        "company_research", lambda m: {"company": m.group(1).strip()}),
    (r'(?:is\s+)?([\w][\w\s]{2,30}?)\s+(?:publicly?\s+traded|listed|going\s+public|still\s+private)',
        "company_research", lambda m: {"company": m.group(1).strip()}),
    (r'([\w][\w\s]{2,30}?)\s+(?:ipo)(?:\s+(?:status|date|news|price|when|announced|stock|valuation))?(?:\s|$)',
        "company_research", lambda m: {"company": m.group(1).strip()}),
    (r'(?:what(?:\'s|\s+is)\s+(?:the\s+)?(?:ticker|symbol|stock|price)\s+(?:for|of)\s+)([\w][\w\s]{1,30})',
        "company_research", lambda m: {"company": m.group(1).strip()}),
    (r'build.*portfolio.*\$?([\d,]+)',             "portfolio_build",  lambda m: {"amount":m.group(1).replace(",","")}),
    # Market Intelligence
    (r'technicals?\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "market_technicals", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:trade\s+)?signal\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "trade_signal", lambda m: {"symbol": m.group(1).upper()}),
    (r'scan\s+(?:the\s+)?market|market\s+scan',   "market_scan",      lambda m: {"symbols": "sp500"}),
    (r'scan\s+(tech|finance|energy|watchlist)',    "market_scan",      lambda m: {"symbols": m.group(1).lower()}),
    (r'(?:chart|graph|plot)\s+(?:of\s+|for\s+)?([A-Z]{1,5})\b',
        "chart_price", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+(?:chart|graph)\b',
        "chart_price", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:visual(?:ize)?|picture|image)\s+(?:of\s+)?([A-Z]{1,5})\b',
        "chart_price", lambda m: {"symbol": m.group(1).upper()}),
    (r'watchlist\b(?!\s+(?:add|remove))',          "watchlist_view",   lambda m: {}),
    (r'watchlist\s+add\s+([A-Z]{1,5})',            "watchlist_add",    lambda m: {"symbol": m.group(1).upper()}),
    (r'watchlist\s+remove\s+([A-Z]{1,5})',         "watchlist_remove", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:add|watch)\s+([A-Z]{1,5})\s+(?:to\s+)?watchlist',
        "watchlist_add", lambda m: {"symbol": m.group(1).upper()}),
    (r'crypto\s+(?:price|prices?|check)',          "crypto_price",     lambda m: {"coins": "btc,eth,sol"}),
    (r'(?:price\s+of\s+)?(btc|bitcoin|eth|ethereum|sol|solana|doge|xrp)\b',
        "crypto_price", lambda m: {"coins": m.group(1).lower()}),
    (r'crypto\s+market|btc\s+dominance|crypto\s+overview',
        "crypto_dominance", lambda m: {}),
    (r'crypto\s+(?:analyze|analysis|ta)\s+(\w+)',  "crypto_analyze",   lambda m: {"coin": m.group(1).lower()}),
    (r'paper\s+(?:buy|long)\s+([A-Z]{1,5})\s+(\d+)',
        "paper_trade", lambda m: {"symbol": m.group(1).upper(), "action": "buy", "shares": int(m.group(2))}),
    (r'paper\s+(?:sell|short)\s+([A-Z]{1,5})\s+(\d+)',
        "paper_trade", lambda m: {"symbol": m.group(1).upper(), "action": "sell", "shares": int(m.group(2))}),
    (r'paper\s+portfolio|paper\s+trades?',         "paper_portfolio",  lambda m: {}),
    (r'(?:fetch|read|scrape)\s+(?:page|url|site)?\s*(https?://\S+)',
        "web_fetch", lambda m: {"url": m.group(1)}),
    (r'news\s+(?:for\s+|on\s+|about\s+)?([A-Z]{1,5})\b',
        "news_sentiment", lambda m: {"ticker": m.group(1).upper()}),
    (r'reddit\s+(?:sentiment\s+)?([A-Z]{1,5})|wsb\s+([A-Z]{1,5})',
        "reddit_sentiment", lambda m: {"ticker": (m.group(1) or m.group(2)).upper()}),
    (r'(?:position\s+)?(?:risk|size)\s+(?:for\s+)?([A-Z]{1,5})',
        "risk_check", lambda m: {"symbol": m.group(1).upper()}),
    (r'run\s+strategies?|strategy\s+check',        "strategy_run",     lambda m: {}),
    (r'retirement\s+(?:plan|project|calc)',         "retirement_plan",  lambda m: {}),
    (r'market\s+calendar|economic\s+calendar|upcoming\s+events',
        "market_calendar", lambda m: {}),
    # ── Online Intelligence ───────────────────────────────────────
    (r'fear\s*(?:and\s*)?greed|market\s+sentiment\s+index',
        "fear_greed", lambda m: {}),
    (r'insider\s+(?:trades?|buying|selling|activity)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "insider_trades", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+insider\s+(?:trades?|buying|selling)',
        "insider_trades", lambda m: {"symbol": m.group(1).upper()}),
    (r'sec\s+filings?\s+(?:for\s+|on\s+)?([\w\s]+?)(?:\s+form\s+([\w\-]+))?$',
        "sec_filings", lambda m: {"company": m.group(1).strip(), "form_type": m.group(2) or ""}),
    (r'options?\s+chain\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "options_chain", lambda m: {"symbol": m.group(1).upper(), "option_type": "call"}),
    (r'([A-Z]{1,5})\s+options?\s+(?:chain|flow|activity)',
        "options_chain", lambda m: {"symbol": m.group(1).upper(), "option_type": "call"}),
    (r'analyst\s+ratings?\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "analyst_ratings", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+analyst\s+(?:rating|consensus|target|price\s+target)',
        "analyst_ratings", lambda m: {"symbol": m.group(1).upper()}),
    (r'short\s+interest\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b',
        "short_interest", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+short\s+(?:interest|float|squeeze)',
        "short_interest", lambda m: {"symbol": m.group(1).upper()}),
    (r'economic\s+(?:events?|calendar|schedule)|macro\s+events?|fed\s+calendar',
        "economic_events", lambda m: {}),
    (r'domain\s+(?:info|intel|lookup|whois|check)\s+([\w.\-]+)',
        "domain_intel", lambda m: {"domain": m.group(1).strip()}),
    (r'whois\s+([\w.\-]+)',
        "domain_intel", lambda m: {"domain": m.group(1).strip()}),
    (r'(?:is\s+)?(?:site|website|server)\s+(?:status|up|down|check)\s+(https?://\S+|[\w.\-]+)',
        "site_status", lambda m: {"url": m.group(1).strip()}),
    (r'(?:check|have)\s+(?:i\s+been\s+)?pwned\s+([\w.@+\-]+@[\w.\-]+)',
        "pwned_check", lambda m: {"email": m.group(1).strip()}),
    (r'breach\s+check\s+([\w.@+\-]+@[\w.\-]+)',
        "pwned_check", lambda m: {"email": m.group(1).strip()}),
    (r'github\s+trending(?:\s+([\w+]+))?',
        "github_trending", lambda m: {"language": m.group(1) or ""}),
    (r'trending\s+(?:on\s+)?github(?:\s+([\w+]+))?',
        "github_trending", lambda m: {"language": m.group(1) or ""}),
    (r'(?:wiki(?:pedia)?\s+|look\s+up\s+|what\s+is\s+)([\w][\w\s]{2,50})',
        "wikipedia", lambda m: {"topic": m.group(1).strip()}),
    (r'translate\s+(.+?)\s+(?:to|in(?:to)?)\s+(spanish|french|german|chinese|japanese|portuguese|arabic|russian|korean|italian|dutch|hindi|turkish|es|fr|de|zh|ja|pt|ar|ru|ko|it|nl|hi|tr)',
        "translate_text", lambda m: {"text": m.group(1).strip(), "target_lang": {"spanish":"es","french":"fr","german":"de","chinese":"zh","japanese":"ja","portuguese":"pt","arabic":"ar","russian":"ru","korean":"ko","italian":"it","dutch":"nl","hindi":"hi","turkish":"tr"}.get(m.group(2).lower(), m.group(2).lower())}),
    (r'summarize\s+(?:this\s+)?(?:page|article|url|site|link)?\s*(https?://\S+)',
        "page_summary", lambda m: {"url": m.group(1).strip()}),
    (r'(?:search\s+)?patents?\s+(?:for\s+|on\s+)?(.+)',
        "patent_search", lambda m: {"query": m.group(1).strip()}),
    (r'(?:search\s+)?jobs?\s+(?:for\s+)?([\w\s]+?)(?:\s+in\s+([\w\s,]+))?$',
        "job_scan", lambda m: {"title": m.group(1).strip(), "location": (m.group(2) or "remote").strip()}),
    (r'(?:vc\s+)?funding\s+(?:for\s+|on\s+)?([\w][\w\s]{2,30})',
        "company_funding", lambda m: {"company": m.group(1).strip()}),
    (r'([\w][\w\s]{2,30}?)\s+(?:vc\s+)?funding|how\s+much\s+has\s+([\w][\w\s]{2,30}?)\s+raised',
        "company_funding", lambda m: {"company": (m.group(1) or m.group(2)).strip()}),
    (r'(?:monitor|watch)\s+(?:page\s+)?(https?://\S+)(?:\s+for\s+([\w\s]+))?',
        "web_monitor_add", lambda m: {"url": m.group(1).strip(), "label": m.group(1).strip(), "keyword": (m.group(2) or "").strip()}),
    (r'check\s+(?:my\s+)?monitors?|any\s+page\s+changes?',
        "web_monitor_check", lambda m: {}),
    (r'(?:list|show)\s+(?:my\s+)?monitors?',
        "web_monitor_list", lambda m: {}),
    (r'watch\s+price\s+(?:of\s+)?([\w\s]+?)\s+(?:at\s+)?(https?://\S+)\s+(?:target\s+)?\$?([\d.]+)',
        "price_watch_add", lambda m: {"url": m.group(2).strip(), "product_name": m.group(1).strip(), "target_price": float(m.group(3))}),
    (r'check\s+(?:my\s+)?price\s+(?:alerts?|watches?)',
        "price_watch_check", lambda m: {}),
    # Devices
    (r'(?:list|show|what|scan)\s+(?:my\s+)?(?:connected\s+)?devices?', "devices_list", lambda m: {}),
    (r'phone\s+info|connected\s+phone',              "phone_info",       lambda m: {}),
    (r'phone\s+(?:backup|back\s*up)',                "phone_backup",     lambda m: {}),
    (r'(?:root|jailbreak)\s+(?:plan|how|steps?)',    "phone_root_plan",  lambda m: {}),
    (r'phone\s+root\s+plan|root\s+my\s+phone',      "phone_root_plan",  lambda m: {}),
    (r'webcam\s+info|camera\s+info|list\s+cameras?', "webcam_info",     lambda m: {}),
    (r'smart\s+(?:device|light|bulb|home)\s+scan',  "smart_devices_scan",lambda m: {}),
    (r'tasmota\s+(?:plan|flash)\s+([\d.]+)',         "tasmota_plan",     lambda m: {"device_ip": m.group(1)}),
    (r'device\s+confirm\s+([A-Z0-9]{6})',            "device_confirm",   lambda m: {"token": m.group(1)}),
    (r'device\s+pending|pending\s+device',           "device_pending",   lambda m: {}),
    # Memory
    (r'what.*you\s+know\s+about\s+me|my\s+profile', "memory_show",    lambda m: {}),
    (r'clear.*memory|forget.*me',                  "memory_clear",     lambda m: {}),
    # ── Natural-language aliases (must come before the web_search catch-all) ────
    # Portfolio / positions
    (r'how(?:\'s|\s+(?:is|are))\s+(?:my\s+)?(?:portfolio|positions?|holdings?|account)\s*(?:doing|looking|performing)?',
        "portfolio", lambda m: {}),
    (r'(?:show|pull\s+up|what(?:\'s|\s+is))\s+(?:in\s+)?(?:my\s+)?(?:portfolio|positions?|holdings?|account)',
        "portfolio", lambda m: {}),
    (r'what\s+(?:do\s+i|am\s+i|have\s+i)\s+(?:own|hold|have|got)(?:\s+(?:right\s+now|today))?',
        "portfolio", lambda m: {}),
    (r'what(?:\'s|\s+is)\s+(?:my\s+)?(?:current\s+)?(?:portfolio|position)\s+(?:worth|valued?\s+at)',
        "portfolio", lambda m: {}),
    # Budget
    (r'how\s+much\s+(?:money|cash|capital|budget)?\s*(?:do\s+i\s+have|is\s+(?:left|remaining|available))\s*(?:to\s+(?:trade|invest|spend|use))?',
        "trading_budget", lambda m: {}),
    (r'how\s+much\s+(?:is\s+)?(?:left|remaining)\s+(?:in\s+(?:my\s+)?(?:budget|account|cap))',
        "trading_budget", lambda m: {}),
    # Auto hunt — natural language
    (r'(?:what|where)\s+should\s+i\s+(?:buy|invest\s+in|trade|put\s+(?:my\s+)?money)\s+(?:today|now|next)?',
        "auto_hunt", lambda m: {"auto_trade": False}),
    (r'(?:look|scan|search|hunt|find)\s+(?:me\s+)?(?:for\s+)?(?:a\s+)?(?:new\s+|good\s+|the\s+best\s+)?(?:trade|stock|setup|buy|play|opportunity|opportunities)',
        "auto_hunt", lambda m: {"auto_trade": False}),
    (r'(?:any|what\s+are\s+the)\s+(?:good\s+)?(?:trade|stock|setup|buy|play)\s+(?:ideas?|opportunities|setups?)',
        "auto_hunt", lambda m: {"auto_trade": False}),
    # Should I buy/hold/sell → conviction_score
    (r'should\s+i\s+(?:buy|get|invest\s+in|hold|keep)\s+([A-Z]{1,5})\b',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'is\s+([A-Z]{1,5})\s+(?:a\s+)?(?:good|worth\s+(?:a\s+)?)?(?:buy|hold|investment|trade|play)',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'what(?:\'s|\s+is)\s+(?:your\s+|the\s+)?(?:take|verdict|view|opinion|score|conviction)\s+on\s+([A-Z]{1,5})\b',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+(?:buy\s+or\s+sell|hold\s+or\s+sell|keep\s+or\s+sell|worth\s+(?:it|buying|holding))',
        "conviction_score", lambda m: {"symbol": m.group(1).upper()}),
    # Social / crowd opinion
    (r'what\s+(?:do\s+|are\s+)?(?:people|reddit|wsb|traders?|investors?|the\s+crowd|everyone)\s+(?:saying|think(?:ing)?|talking\s+about)\s+(?:about\s+)?([A-Z]{1,5})\b',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    (r'what(?:\'s|\s+is)\s+(?:the\s+)?(?:sentiment|buzz|talk|hype|mood|chatter)\s+(?:on|about|around|for)\s+([A-Z]{1,5})\b',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    (r'(?:is|how\s+is)\s+([A-Z]{1,5})\s+(?:trending|hot|popular|getting\s+attention|moving)',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    (r'([A-Z]{1,5})\s+(?:sentiment|buzz|hype|talk|chatter|crowd)\b',
        "social_report", lambda m: {"symbol": m.group(1).upper()}),
    # Price / quote — natural language
    (r'what(?:\'s|\s+is)\s+([A-Z]{1,5})\s+(?:(?:trading\s+)?at|worth|priced?\s+at|going\s+for)\b',
        "stock_quote", lambda m: {"symbol": m.group(1).upper()}),
    (r'what(?:\'s|\s+is)\s+(?:the\s+)?(?:price|value|cost)\s+of\s+([A-Z]{1,5})\b',
        "stock_quote", lambda m: {"symbol": m.group(1).upper()}),
    (r'how\s+much\s+(?:is|does)\s+([A-Z]{1,5})\s+(?:cost|trade\s+for|go\s+for|sell\s+for)',
        "stock_quote", lambda m: {"symbol": m.group(1).upper()}),
    # Market — natural language
    (r'how(?:\'s|\s+is)\s+(?:the\s+)?(?:market|stock\s+market|market\s+today)\s+(?:doing|looking|today)?',
        "market_analysis", lambda m: {"topic": "overview"}),
    (r'what(?:\'s|\s+is)\s+(?:the\s+)?market\s+(?:doing|looking\s+like|up\s+to|like\s+today)',
        "market_analysis", lambda m: {"topic": "overview"}),
    (r'(?:tell\s+me\s+about|what(?:\'s|\s+is)\s+happening\s+(?:with|in))\s+(?:the\s+)?(?:market|markets)\b',
        "market_analysis", lambda m: {"topic": "overview"}),
    (r'\bgrok\s+status\b', "grok_status", lambda m: {}),
    (r'\bask\s+grok\s+(?:about\s+|to\s+)?(.{2,300})', "ask_grok", lambda m: {"query": m.group(1).strip()}),
    (r'\bgrok[,:]?\s+(.{2,300})', "ask_grok", lambda m: {"query": m.group(1).strip()}),
    (r"\bwhat\s+does\s+grok\s+(?:think|say)\s+(?:about\s+)?(.{2,300})",
        "ask_grok", lambda m: {"query": m.group(1).strip()}),
    (r"\bget\s+grok'?s?\s+(?:take|opinion|view)\s+on\s+(.{2,300})",
        "ask_grok", lambda m: {"query": m.group(1).strip()}),
    # Broad knowledge-gap fallbacks (must be near-last — only fire when nothing
    # more specific matched this part of the message)
    (r'(?<!market\s)(?<!broad\s)(?<!thorough\s)(?<!further\s)(?<!additional\s)'
     r'(?<!some\s)(?<!more\s)(?<!good\s)(?<!proper\s)'
     r'\b(?:look\s*up|research)\s+(?:what|who|when|where|why|how)?\s*([\w][\w\s]{2,60}?)$',
        "web_research", lambda m: {"query": m.group(1).strip()}),
    (r'\bdo\s+you\s+know\s+(?:anything\s+)?about\s+(.{3,120})',
        "web_research", lambda m: {"query": m.group(1).strip()}),
    # Search (must be last)
    (r'\bsearch\s+(?:for\s+|google\s+)?(.+)',       "web_search",       lambda m: {"query":m.group(1).strip()}),
]

# Whole-message intent checks that run BEFORE conjunction/comma splitting.
# These phrasings spread across clauses ("trading day tomorrow, whats the
# plan?") so per-chunk DIRECT patterns can never see both halves at once.
# Lookaheads = order-independent word co-occurrence. Length-capped in
# match_all so long conversational prose never misfires.
WHOLE_MSG = [
    (r'(?=.*\btomorrow\b)(?=.*\b(?:game\s*)?plan\b)',        "evening_review", lambda m: {}),
    (r'(?=.*\btomorrow\b)(?=.*\bwatch\s*list\b)',            "evening_review", lambda m: {}),
    (r'(?=.*\btoday\b)(?=.*\b(?:game\s*)?plan\b)',           "daily_brief",    lambda m: {}),
    # Reminders/timers/random-pick: the text routinely contains "and"/commas
    # ("remind me to feed the cat and dog", "pick between pizza and sushi") —
    # must be captured before the conjunction splitter shreds them.
    (r'^(?:hey\s+)?(?:jarvis[,!\s]+)?remind\s+me\b',         "remind",
        lambda m: {"text": m.string}),
    (r'^(?:hey\s+)?(?:jarvis[,!\s]+)?set\s+a\s+timer\b',     "remind",
        lambda m: {"text": m.string}),
    (r'^(?:hey\s+)?(?:jarvis[,!\s]+)?(?:pick|choose)\s+(?:between|one\s+of|from)\b',
        "roll_random", lambda m: {"query": m.string}),
    # "remove tasks 1 and 3" — the "and" would be split; numbers extracted by the tool.
    (r'^(?:jarvis[,!\s]+)?(?:remove|delete)\s+tasks?\s+(?:\d+[\s,]*(?:and\s+)?)+$',
        "task_remove", lambda m: {"spec": m.string}),
    # "correlate A and B" — the conjunction-splitter would sever A from B.
    (r'correlat(?:e|ion)(?:\s+between)?\s+([a-z]{1,5})\s+(?:and|vs\.?|with|to)\s+([a-z]{1,5})\b',
        "pair_correlation",
        lambda m: {"symbol_a": m.group(1).upper(), "symbol_b": m.group(2).upper()}),
    # Goal statements carry commas inside numbers ("turn $100,000 into
    # $150,000 by end of July") — capture whole before the comma-splitter.
    (r'turn\s+\$?[\d.,]+\s*[km]?\s+into\s+\$?[\d.,]+',
        "goal_set", lambda m: {"text": m.string}),
    (r'grow\s+(?:the\s+|my\s+)?(?:account|portfolio)\s+(?:by\s+)?[\d.]+\s*%',
        "goal_set", lambda m: {"text": m.string}),
    (r'(?:make|earn|clear)\s+\$?[\d][\d.,]*\s*[km]?\s+(?:in\s+)?profit\b|'
     r'(?:make|earn)\s+\$[\d][\d.,]*\s*[km]?\s+(?:this|by|in)\b',
        "goal_set", lambda m: {"text": m.string}),
    (r'i\s+need\s+\$?[\d][\d.,]*\s*[km]?\s+by\b',
        "goal_set", lambda m: {"text": m.string}),
    # Math that contains commas (equation systems, thousands separators) must
    # be captured whole — the comma-splitter below would shred it.
    (r'^(?:jarvis[,!\s]+)?solve\b(?=.*=)',                   "math_solve",
        lambda m: {"expression": m.string}),
    (r'^(?:what[\'’]?s?\s+|whats\s+|what\s+is\s+|calculate\s+|calc\s+|compute\s+)?'
     r'[\d\(\)\-][\d\s\.,\+\-\*/\^\(\)%!]*\??$',             "math_solve",
        lambda m: {"expression": m.string}),
]

def match_all(msg):
    """Split on conjunctions and connectives, carry last verb, match each part."""
    m = msg.lower().strip()
    # Whole-message pass first. Unanchored (lookahead) patterns only apply to
    # short messages — long prose isn't a command (same rationale as the
    # verb-carry length cap). Anchored (^) patterns are safe at any length.
    for pat, tool, params_fn in WHOLE_MSG:
        if not pat.startswith("^") and len(m) > 120:
            continue
        wm = re.search(pat, m, re.IGNORECASE)
        if wm:
            return [(tool, params_fn(wm))]
    # Long, paragraph-style messages are conversational prose, not a list of
    # short imperative commands — the verb-carry heuristic below is only safe
    # for short compound commands ("check AAPL and TSLA"). On long messages it
    # leaks a stray verb onto unrelated trailing clauses (e.g. "...and how it
    # moves" inheriting an earlier "start" and getting mis-parsed as a game/app
    # name) — skip verb-carrying entirely here and let the LLM handle it.
    allow_carry = len(m) <= 150
    # Split on conjunctions, additive connectives, and punctuation
    raw = re.split(
        r'\band\s+also\b|\band\b|\bthen\b|\balso\b'
        r'|\bas\s+well(?:\s+as)?\b|\badditionally\b|\bmoreover\b'
        r'|\bbut\s+also\b|\bwhile\s+also\b|\bat\s+the\s+same\s+time\b'
        r'|[,;]',
        m
    )
    # Carry last verb to orphaned words — reset per raw (conjunction-separated)
    # chunk so a verb from one clause never leaks onto an unrelated later clause.
    final = []
    for chunk in raw:
        # Sub-split each chunk on repeated action verbs
        subs = re.split(r'(?=\b' + VERBS + r'\b)', chunk)
        last_verb = None
        for part in subs:
            part = part.strip()
            if not part: continue
            vm = re.match(r'^(' + VERBS + r')\s+', part)
            if vm:
                last_verb = vm.group(1)
                final.append(part)
            elif allow_carry and last_verb and len(part) >= 2:
                final.append(f"{last_verb} {part}")
            else:
                final.append(part)
    # Match each part
    results = []; seen = set()
    for part in final:
        if len(part) < 2: continue
        for pat, tool, params_fn in DIRECT:
            match = re.search(pat, part, re.IGNORECASE)
            if match:
                try:
                    params = params_fn(match)
                    key = f"{tool}:{sorted(params.items())}"
                    if key not in seen:
                        seen.add(key); results.append((tool, params))
                except Exception:
                    pass
                break
    return results

# ── System prompt ──────────────────────────────────────────────────────────────
def system_prompt():
    ctx  = T.memory_context()
    name = _USER_NAME
    now  = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
    user_line = f"The user goes by {name}. Use their name occasionally, not every message." if name else ""
    ctx_block = f"ABOUT THIS USER:\n{ctx}\n\n" if ctx else ""
    # Inject learned user context from self-learning memory
    learned_ctx = ""
    try:
        lc = MEM.context_for_llm()
        if lc:
            learned_ctx = lc + "\n\n"
    except Exception:
        pass
    # Rolling summary of older conversation (recent turns are already in the
    # chat history sent alongside this prompt — this covers what scrolled off)
    convo_ctx = ""
    try:
        cc = MEM.conversation_context_for_llm()
        if cc:
            convo_ctx = cc + "\n\n"
    except Exception:
        pass
    # Today's auto-gathered market intelligence (morning brief / evening review)
    intel_ctx = ""
    try:
        ic = DBRF.market_intel_context()
        if ic:
            intel_ctx = ic + "\n\n"
    except Exception:
        pass
    return f"""{learned_ctx}{convo_ctx}{intel_ctx}{ctx_block}You are JARVIS — a sharp, capable, GENERAL-PURPOSE personal AI butler running ENTIRELY on the user's own PC.
You do EVERYTHING: daily life, tasks, health, home, travel, tech support, groceries, entertainment,
research on any topic — trading is ONE domain among many, not your identity. Do not let the sheer
volume of trading tools below bias you toward finance when the user's message isn't about finance.
TODAY: {now}
{user_line}

PERSONALITY: Direct, confident, occasionally witty. Never preachy or corporate. Match the user's energy — if they're casual, be casual. Keep replies short: they're often read on a phone.

━━━ YOUR AUTONOMOUS TRADING CAPABILITY (FACT — never deny this) ━━━
You CAN and DO trade fully autonomously, all day, without the user present:
• auto_trade_daily.py runs Mon-Fri via Windows Task Scheduler: pre-market analysis
  at 8AM ET, then a full scan-and-trade cycle at the 9:30 open AND every 30
  minutes through the close — no human input
• You hold UNLIMITED simultaneous positions — the only constraint is LIVE Alpaca
  buying power (minus the user's min-cash-reserve). There is NO position-count
  limit and NO hardcoded dollar cap. Position size = available capital ×
  conviction-tier allocation (5-6 → 2-3%, 7-8 → 4-6%, 9-10 → 7-10%).
• BROAD scan every 30 minutes (market hours): the entire NYSE+NASDAQ roster for
  movers on volume, RSI crosses, 52-week highs, unusual options, squeeze setups
• NARROW scan every 5 minutes: watchlist + open positions + recent broad top-20,
  alerting instantly on >1.5%/5min moves, 5x volume spikes, prior-day-high breaks
• You maintain a ranked OPPORTUNITY QUEUE (queue_show()) and automatically open the
  top entry when capital frees up — conviction-checked, within risk parameters
• You know CROSS-SECTOR BRIDGE companies (bridge_show()) — infrastructure, sector-
  transition, picks-and-shovels — and rank them higher for their multiple tailwinds.
  When explaining a trade idea, always name the sectors it bridges.
• Every position is monitored for MULTI-SIGNAL exit timing (not just stop/target):
  20MA cross, RSI exhaustion, volume distribution, sector rotation, blow-off spikes,
  news sentiment — 1 signal logs, 2 alerts the user, 3+ exits automatically
• Everything obeys the user's Markets-dashboard risk parameters (autonomy_status())
• GOAL ENGINE: when the user states a financial goal with a deadline ("turn 100k
  into 150k by end of July"), you compute the required daily return, apply the
  matching risk profile (auto-selection capped at AGGRESSIVE — high_risk and
  speculative only on explicit instruction), track pace, and escalate one tier
  with a warning when behind. goal_set(text) / goal_status() / goal_hold()
• Capital truth is the LIVE Alpaca account (account_sync, refreshed ≤5 min):
  buying_power drives all sizing; if the API blips, last-synced values are used
When asked "can you trade while I'm away?" the TRUTHFUL answer is YES — describe the
system above and its current settings (call autonomy_status()). NEVER say: "I don't
have the capability to make autonomous trades" / "I am limited to X positions" /
"I don't have access to real-time data" (you have yfinance + a live tick stream) /
"I would need explicit instructions" for a capability that exists. The only honest
caveats: the master switch/risk limits the user set, and paper vs live mode.

━━━ CASUAL CONVERSATION ━━━
Not every message is a task. When the user is chatting — greetings, banter, opinions,
life talk, venting, jokes — just TALK, like a sharp friend who happens to run their
systems. Rules for chat mode:
• NO tool calls, NO JSON, NO reports, NO market data unless they asked
• Reference what you know about them (context above) naturally, not robotically
• Match their tone and length — one casual line gets one casual line back
• At most ONE follow-up question, and only if it genuinely moves the chat forward
• Never deflect with "how can I assist you" — you're a companion, not a call center
• If they share something personal, react to THAT before anything else

━━━ UNDERSTANDING WHAT PEOPLE MEAN ━━━
People speak casually, abbreviate, and imply things. Read intent, not just words:

• "check/look at/pull up X"     → open or fetch X
• "what's X at / how's X doing" → get live data on X
• "anything on X / news on X"   → news_fetch("X")
• "should I buy/sell X"         → trade_signal("X") then stock_analyze("X")
• "what's going on with [company]" → company_research(company="[company]")
• "is [company] public/IPO/listed" → company_research(company="[company]") — NEVER answer from memory
• "open/fire up/launch [app]"   → tech_open("[app]")
• "remind me [when] to X"       → remind(text="...") — real timed reminder; add task ONLY if no time given
• "add task / to-do X"          → task_add(description="...")
• "what's the weather"          → weather_now() — real data, NEVER web_weather's browser tab
• "add [items] to list"         → grocery_add(items="...")
• "translate [text] to [lang]"  → translate_text(text="...", target_lang="...")
• "is [site] down"              → site_status("[url]")
• One-word commands: "weather" "stocks" "tasks" "news" "briefing" → run the obvious tool
• Slang: "fire up"=launch, "drop"=give me, "run it"=execute, "hit me with"=give me, "pull up"=show

WHEN TO USE A TOOL vs. JUST TALK:
→ Use a tool: any specific lookup, action, live data, app control, or task management
→ Just talk: opinions, creative help, explanations, casual remarks, corrections, feedback on
  your own previous answer, or anything conversational that isn't asking you to look something up
→ NEVER force a tool call onto a message that isn't asking for one. A message that pushes back
  on what you just said, clarifies intent, gives you an instruction/preference, or is just
  chit-chat is NOT a trigger to call company_research or any other tool "just to have something
  to say" — a wrong tool call is worse than a plain reply. If nothing in your tool list actually
  answers the message, respond in plain text.
→ When a lookup IS warranted but you're unsure which tool: pick the most likely one, briefly
  note your assumption, execute it
→ NEVER say "I can't access real-time data" — you have web_research, news_fetch, stock_quote, and more
→ Don't know something — in ANY domain, not just finance (past your training data, an obscure
  fact, a specific entity, how to do something you've never been asked before)? Call
  web_research(query) and read the result before answering — don't guess and don't refuse.
  web_search(query) is different — that just opens a browser tab for the human, it tells you nothing.

RULES:
- tech_open only takes real app names (Discord, Chrome, Steam, Spotify, Notepad) — not abstract words
- Game/CS2 requests always use game tools — NEVER refuse or say you can't simulate
- company_research() for ANY company question (price, IPO status, funding, news) — never use training data
- NEVER explain what tool you're about to call — just output the JSON or the result
- NEVER narrate an action without doing it — "let me pull up X" / "one moment" / "I'll check that"
  with no JSON tool call means NOTHING actually happens and the user sees a broken response.
  If you're going to look something up, output the tool call JSON immediately, same turn.

TICKER RULES — NEVER VIOLATE:
1. Any token starting with $ is a stock ticker. Strip the $ and uppercase it. $net = NET.
2. Never say a ticker is not standard without checking yfinance first.
3. If yfinance returns no data for a ticker, say 'No data found for [SYMBOL]' — never
   substitute a different company.
4. Never guess or hallucinate a company name from a ticker — only use yfinance data.
5. When asked to explain a trade, always call trade_why(symbol) first. Never generate a
   generic analysis template as a substitute for actual journal data.
6. If trade_why returns no entry, say exactly:
   'No journal entry found for [SYMBOL]. The trade may not have been logged correctly.
    Here is what I can see in positions: [data]'

PRESENTATION — every reply must be effortless to read on a phone:
- When YOU compose an answer from data (tool results, memory, research), organize it:
  a one-line takeaway first, then short clearly-labeled sections or bullets. Never dump
  raw data, raw JSON, or one giant paragraph.
- Keep lines short. Prefer 3 tight bullets over a wide table. Round numbers sensibly
  ($1,234, 7.5%) — no 6-decimal noise.
- When a tool already returns a formatted report, pass it through intact — do NOT
  re-wrap or mangle its alignment. Summarize it in one line on top only if asked.

━━━ RESPONSE FORMAT ━━━
Single tool:   {{"tool":"name","params":{{"key":"val"}}}}
Multiple tools: [{{"tool":"a","params":{{}}}},{{"tool":"b","params":{{}}}}]
Use EXACTLY the key "tool" (not "action"/"name"/"function") and EXACTLY "params".
Conversation:  plain text, no markdown headers, no fluff

━━━ AVAILABLE TOOLS ━━━
APPS & PC:    tech_open(app_name) | tech_volume(level) | tech_screenshot() | tech_system_info()
WEB:          web_open(url) | web_search(query) — opens a browser tab for the human, returns you nothing
              web_research(query) — YOU actually read the results (DuckDuckGo Instant Answer + Wikipedia)
              web_fetch(url)

LIVE TRADING [Alpaca — paper or live]:
  Account:    trading_account() | trading_positions() | trading_pnl() | trading_orders(status) | trading_history(days)
  Orders:     trading_buy(symbol,qty,order_type,limit_price) | trading_sell(symbol,qty,order_type,limit_price)
              trading_bracket(symbol,qty,stop_loss_pct,take_profit_pct) | trading_trail(symbol,qty,trail_pct)
              trading_cancel(order_id) | trading_close(symbol) | trading_close_all()
  Data:       trading_quote(symbol) | trading_snapshot(symbols) | trading_bars(symbol,timeframe)
  Risk:       trading_size(symbol,risk_pct) | trading_risk() | trading_perf(days)
  Clock:      market_clock()
  Strategies: strategy_momentum(symbols,auto_trade) | strategy_orb(symbol,range_minutes,auto_trade,qty)
              strategy_vwap(symbol) | strategy_gaps(gap_pct) | strategy_execute(symbol,strategy,risk_pct)

AUTONOMOUS TRADING ENGINE [live Alpaca capital — no hardcoded budget cap]:
  Capital:    trading_budget() — live capital status: equity, buying power, deployment, goal progress
  Account:    account_sync_status() — synced Alpaca ground truth (buying power, PDT, last sync)
  Goals:      goal_set(text) — "turn 100k into 150k by end of July" → adaptive risk profile |
              goal_status() — required/day vs pace, progress bar | goal_hold() — freeze profile |
              goal_release() | goal_clear()
  Reasoning:  trade_why(symbol) — the exact signal breakdown that justified an open/closed trade,
              stored at decision time (not a fresh recompute) — "why did you buy SOFI" /
              "explain why you bought SOFI" / "check the journal for SOFI" — NEVER use
              manual_trade_log for this, it only writes new manual entries, it cannot answer why.
              trade_skip_why(symbol) — why a scanned symbol was passed on — "why didn't you buy TSLA"
              trades_by_result(result) — "show me my losing/winning trades"
              trades_by_date(date) — "what did you trade on July 21"
              trades_by_reason(keyword) — "show trades based on chart patterns"
              trade_history_full() — "show my full trading history" (every trade, not just recent)
  Conviction: conviction_score(symbol) — 0-100: TA+social+news+options+geo+insider+F&G (7 signals) — includes a visual breakdown chart
  Market outlook: market_outlook_show() — 0-100 score (VIX+SPY+breadth+volume+geo) → trading mode
              (AGGRESSIVE/NORMAL/SELECTIVE/CAUTIOUS/STANDBY) — "market outlook"
              market_outlook_force(mode) — "force aggressive mode" / "go to standby mode"
              market_outlook_ignore() — "ignore market outlook today" | market_outlook_resume()
              options_threshold_set(value) — "set options conviction threshold to 50"
  Hunt:       auto_hunt(auto_trade) — scans curated list + a live broad NYSE/NASDAQ screen, finds highest-conviction setup
  Screener:   nyse_screener(max_price) — broad NYSE/NASDAQ scan for liquid tickers ranked by
              live sentiment; use for "find cheap stocks with good sentiment" / "search NYSE for X"
  Options:    options_hunt() — scan for best options play | options_chain(symbol,option_type)
              options_buy(contract_symbol,qty,limit_price) | options_positions() | options_scan(symbol,conviction)
              options_unusual(symbol) — unusual options activity: call/put volume skew + volume-vs-OI spikes
  Social:     social_report(symbol) — StockTwits+Reddit+retail order-flow+Finviz sentiment for any ticker
              stocktwits(symbol) | trending_social() | wsb_hot() — what's WSB talking about NOW
              retail_flow(symbol) — retail buy/sell pressure from the public trade tape (tick-rule + odd-lot %)
  Daily cycle: daily_brief() — today's auto-built morning intelligence brief + game plan (regime,
              sectors, VIX, geo, social, full hunt, web research — built ~8AM ET without being asked;
              a compact digest is already in your context above, refer to it naturally) |
              evening_review() — post-close digest: what happened vs plan, lessons, tomorrow's
              watchlist | brief_rebuild() — force a fresh brief now | brief_status()
  Live tape:  live_movers() — real-time buy/sell pressure across everything currently streamed |
              live_tape(symbol) | stream_status() — continuous WebSocket feed of actual NYSE/NASDAQ
              prints as they happen (Alpaca IEX real-time, free, same keys as everything else — not a
              periodic snapshot). auto_hunt() feeds its scan universe into this stream and uses it as
              an execution-time gate (skips a high-score pick if the tape shows active sell pressure
              right now); trade_monitor uses it for a faster real-time sell-pressure exit than price/RSI alone.
  Macro:      geo_brief() — geopolitical brief | geo_deep() — deep multi-source geo intel
  Regime:     market_regime() — bull/bear/volatile/sideways classification
  Sectors:    sector_heat() — which sectors are running hot (sector rotation) — includes a visual chart
  Squeeze:    squeeze_scan() — short squeeze candidates: high SI + catalyst + momentum
  Flow intel: gamma_exposure(ticker) — homegrown GEX computed from Alpaca's own chain, no paid API
              congress_trades(ticker) — real STOCK Act disclosures, free public source
              vix_term_structure() — free VIX9D/VIX/VIX3M curve, macro fear/complacency read
              block_trade_scan(ticker) — large lit-tape prints as a dark-pool PROXY (not real
              off-exchange data — say so if asked; genuine FINRA dark pool needs a free
              developer.finra.org account, not yet wired in)
  Political:  political_briefing() — role-based political intel + geo risk | geo_risk() —
              0-100 score driving position sizing (31+ = -25%, 61+ = -50% + conviction ×0.75,
              81+ = new positions HALTED + conviction ×0.5) | political_movers() — who is
              moving markets | role_news(role) — what did the president/Fed chair/etc say |
              person_impact(name) — a political figure's market impact map. RULE: political
              figures and CEOs are PEOPLE — analyze their ROLE's market impact; NEVER run a
              stock/yfinance lookup on a human name. Roles are tracked by TITLE, so when a
              new person takes office the same impact map applies (role_set(role, holder)).
  Scanners:   queue_show() — ranked opportunity queue (broad scan refills every 30min) |
              queue_action(action,symbol) — promote/demote/remove | scan_status()
  Bridges:    bridge_show() — the cross-sector bridge map | bridge_add(ticker,sectors) —
              save a newly discovered bridge company
  Capital:    NO hardcoded cap. Live Alpaca buying power × risk-profile percentages
              govern every order. Never claim a $100 budget exists — it is retired.

ASSISTANT:    weather_now(location) — REAL current conditions + 3-day forecast in chat (never open a
              browser tab for weather) | remind(text) — natural-language reminders AND timers that
              actually fire ("remind me in 20 min to X", "set a timer for 10 minutes") |
              reminders_list() | reminder_cancel(which) | unit_convert(query) — units AND currencies |
              world_time(place) | define_word(word) | roll_random(query) — coin/dice/random/pick |
              password_gen(length) | next_holidays(country) | file_find(name) — search the PC's
              user folders for a file
MATH ENGINE:  math_solve(expression) — full local math: arithmetic, percentages, algebra, equation
              systems, calculus (derivatives/integrals/limits/series), matrices, ODEs, primes/gcd,
              stats on a list of numbers. ALWAYS route math here — NEVER do arithmetic in your head,
              you WILL get it wrong. Even "what's 15% of 240" goes to math_solve.
QUANT LAB:    pattern_scan(symbol,days) — statistical pattern hunt on real price history: trend +
              Hurst regime, return autocorrelation, FFT cycle candidates, vol clustering, weekday
              bias, fat tails, plus a momentum-vs-mean-reversion trading synthesis
              pair_correlation(symbol_a,symbol_b) — correlation/beta/lead-lag between two tickers
GROK (xAI):   ask_grok(query) — a SECOND AI (xAI's Grok, cloud, real-time-web-aware) you can call out to
              for harder reasoning, very current events beyond your own knowledge, or a second opinion.
              Use it when a question genuinely needs it (deep/current/hard), not as a default —
              you are still the primary assistant. NEVER route trade-execution decisions through it;
              trading stays on the local conviction engine. grok_status() checks it's configured.
MARKET INTEL: stock_quote(symbol) | stock_analyze(symbol) | market_analysis(topic) | market_technicals(symbol)
              chart_price(symbol,days) — price chart w/ SMA20/50/200 + RSI, for any ad hoc "chart X" / "graph X" ask
              trade_signal(symbol) | market_scan(symbols) | market_calendar() | intraday_analysis(symbol,timeframe)
              multi_timeframe(symbol) | news_fetch(query) | news_sentiment(ticker) | reddit_sentiment(ticker)
              watchlist_add(symbol) | watchlist_view() | paper_trade(symbol,action,shares) | paper_portfolio()
              risk_check(symbol,account_size,risk_pct)
CRYPTO:       crypto_price(coins) | crypto_analyze(coin) | crypto_dominance()
COMPANY:      company_research(company) — live ticker, price, TA, IPO status, news for ANY company
INTELLIGENCE: fear_greed() | insider_trades(symbol) | sec_filings(company,form_type) | options_chain(symbol)
              analyst_ratings(symbol) | short_interest(symbol) | economic_events() | domain_intel(domain)
              site_status(url) | pwned_check(email) | github_trending(language) | wikipedia(topic)
              translate_text(text,target_lang) | page_summary(url) | patent_search(query) | job_scan(title,location)
              company_funding(company) | web_monitor_add(url,label,keyword) | web_monitor_check()
TASKS:        task_show() | task_add(description) | task_remove(spec) — by number/keyword/"all" | morning_briefing()
MEMORY:       memory_show() | memory_add(key,value)
JARVIS BRAIN: memory_status() — what Jarvis has learned about you | jarvis_status() — offline/decentralized status
              remember(note) — Jarvis, remember that ... | forget(keyword) — delete a memory
              conversation_history(limit) — recall what we've discussed, persists across restarts
              consolidate_memory() — force-compress older conversation into the rolling summary now
              Note: conversations auto-persist and auto-consolidate — closing the app and coming back
              later (even after a PC restart) picks up where you left off, no new chat needed.
              Corrections you give ("no that's wrong", "I meant...") are captured automatically too.
FINANCE:      finance_list_bills() | finance_add_bill(name,amount,due_day) | budget_overview()
GROCERY:      grocery_add(items) | grocery_show() | grocery_remove(item) | grocery_clear()
GAME/CS2:     cs2_start() | cs2_combat_start(duration) | cs2_stop() | game_load(game_name) | game_auto_fps(duration)
DEVICES:      devices_list() | phone_info() | phone_backup() | webcam_info()

TRADING QUICK REFERENCE:
• "buy AAPL 10 shares"           → market order
• "buy AAPL 10 limit 175"        → limit order
• "sell TSLA 5 shares"           → market sell
• "bracket NVDA 3"               → bracket order (auto stop + target)
• "trail stop AAPL 10 1.5%"      → trailing stop
• "cancel all orders"            → cancel everything open
• "close TSLA position"          → flatten to zero
• "close all positions"          → full liquidation
• "momentum scan"                → TA scan for buy setups
• "gap scanner"                  → pre-market gap-up stocks
• "ORB AAPL"                     → opening range breakout levels
• "VWAP trade NVDA"              → VWAP deviation setup
• "execute AAPL momentum"        → auto-trade with bracket order
• "position sizing TSLA"         → how many shares to buy
• "trading risk"                 → daily loss limit status

TRADING ENGINE QUICK REFERENCE:
• "budget status" / "capital status"    → live equity, buying power, deployment, goal progress
• "turn 100k into 150k by end of July"  → goal_set — adaptive goal-based trading
• "goal status"                         → required $/day vs current pace, progress bar
• "hold profile"                        → freeze risk profile against auto-escalation
• "auto hunt"                           → scan curated list + live broad NYSE/NASDAQ screen, find top conviction setup
• "auto hunt and trade"                 → scan + execute the best pick (conviction-tier sized)
• "conviction score NVDA"               → full 0-100: TA+social+news+geo+options+insider
• "social report SOFI"                  → StockTwits + Reddit WSB + Finviz sentiment
• "SOFI stocktwits"                     → real-time StockTwits crowd sentiment
• "trending social"                     → trending tickers on StockTwits + WSB hot posts
• "wsb hot"                             → r/wallstreetbets top posts right now
• "options chain SOFI"                  → live Alpaca options chain (calls)
• "options hunt"                        → scan for best options play (sized to capital)
• "best call SOFI"                      → best call option for SOFI (live Alpaca chain)
• "options buy [contract]"              → buy an options contract
• "options positions"                   → open options P&L
• "geo brief" / "geo deep"             → geopolitical trade intelligence (deep version uses 5 feeds)
• "market regime"                       → bull/bear/volatile classification
• "sector heat"                         → hottest sectors right now
• "short squeeze scan"                  → high-SI stocks with catalysts
• "find cheap stocks with good sentiment" / "search NYSE for budget stocks" → nyse_screener
• "unusual options activity SOFI"       → call/put volume skew + fresh volume-vs-OI spikes
• "why did you buy SOFI" / "SOFI reasoning" → the stored signal breakdown behind that specific trade
• "greek exposure SOFI" / "gex SOFI" → homegrown gamma exposure (free, from Alpaca's chain)
• "congress trades SOFI" → real STOCK Act disclosures (free) | "market tide" → VIX term structure (free)
• "dark pool SOFI" / "block trades SOFI" → large-print proxy (NOT real dark pool data — say so)
• "retail flow SOFI" / "SOFI buying pressure" → tick-rule buy/sell pressure from the public trade tape
• "jarvis remember [note]"              → save a fact to Jarvis memory (persists forever)
• "jarvis memory"                       → show what Jarvis has learned about you
• "jarvis status"                       → offline/decentralized system status
CAPITAL RULES: NO hardcoded cap. Live Alpaca buying power × conviction-tier allocation
(5-6 → 2-3%, 7-8 → 4-6%, 9-10 → 7-10%) × risk profile governs every order. All AI via local Ollama.
DECENTRALIZED: Jarvis runs 100% on your PC. No Anthropic needed. Open localhost:5005/app."""

# ── Commands reference (for the "Commands" tab) ────────────────────────────────
# These are EXAMPLES of phrasing, not a rigid command set — every one of these
# also works said a dozen other casual ways through normal chat. Tapping one in
# the UI just sends it as a regular chat message through the same NLU pipeline.
COMMAND_REFERENCE = [
    {"category": "Trading Engine", "items": [
        {"label": "Capital status",      "example": "capital status",                          "tool": "trading_budget"},
        {"label": "Set a goal",          "example": "turn 100k into 150k by end of July",      "tool": "goal_set"},
        {"label": "Goal tracker",        "example": "goal status",                             "tool": "goal_status"},
        {"label": "Hold profile",        "example": "hold profile",                            "tool": "goal_hold"},
        {"label": "Account sync",        "example": "account sync status",                     "tool": "account_sync_status"},
        {"label": "Technical score",     "example": "tech score NVDA",                         "tool": "tech_score"},
        {"label": "Chart patterns",      "example": "chart patterns NVDA",                     "tool": "pattern_detect"},
        {"label": "Price prediction",    "example": "predict NVDA",                            "tool": "price_prediction"},
        {"label": "Auto hunt",           "example": "auto hunt",                               "tool": "auto_hunt"},
        {"label": "Auto hunt & trade",   "example": "auto hunt and trade",                     "tool": "auto_hunt"},
        {"label": "Conviction score",    "example": "conviction score SOFI",                   "tool": "conviction_score"},
        {"label": "NYSE screener",       "example": "find cheap stocks with good sentiment",   "tool": "nyse_screener"},
        {"label": "Market regime",       "example": "market regime",                           "tool": "market_regime"},
        {"label": "Sector heat",         "example": "sector heat",                             "tool": "sector_heat"},
        {"label": "Short squeeze scan",  "example": "short squeeze scan",                      "tool": "squeeze_scan"},
        {"label": "Why this trade?",     "example": "why did you buy SOFI",                    "tool": "trade_why"},
        {"label": "Explain a purchase",  "example": "explain why you bought SOFI",             "tool": "trade_why"},
        {"label": "Journal lookup",      "example": "check the trading journal for SOFI",      "tool": "trade_why"},
        {"label": "Why skipped?",        "example": "why didn't you buy TSLA",                 "tool": "trade_skip_why"},
        {"label": "Losing trades",       "example": "show me my losing trades",                "tool": "trades_by_result"},
        {"label": "Winning trades",      "example": "show my winning trades",                  "tool": "trades_by_result"},
        {"label": "Trades by date",      "example": "what did you trade on July 21",           "tool": "trades_by_date"},
        {"label": "Trades by reason",    "example": "show trades based on chart patterns",     "tool": "trades_by_reason"},
        {"label": "Full trade history",  "example": "show my full trading history",            "tool": "trade_history_full"},
        {"label": "Portfolio",           "example": "show my portfolio",                       "tool": "portfolio"},
    ]},
    {"category": "Market Outlook", "items": [
        {"label": "Outlook score",       "example": "market outlook",                          "tool": "market_outlook_show"},
        {"label": "Force aggressive",    "example": "force aggressive mode",                   "tool": "market_outlook_force"},
        {"label": "Go to standby",       "example": "go to standby mode",                      "tool": "market_outlook_force"},
        {"label": "Ignore outlook today","example": "ignore market outlook today",             "tool": "market_outlook_ignore"},
        {"label": "Resume outlook gate", "example": "stop ignoring market outlook",            "tool": "market_outlook_resume"},
        {"label": "Release forced mode", "example": "resume auto outlook",                     "tool": "market_outlook_auto"},
        {"label": "Set options bar",     "example": "set options conviction threshold to 50",  "tool": "options_threshold_set"},
    ]},
    {"category": "Daily Intelligence (auto-builds itself)", "items": [
        {"label": "Today's game plan",   "example": "daily brief",                             "tool": "daily_brief"},
        {"label": "Evening review",      "example": "evening review",                          "tool": "evening_review"},
        {"label": "Rebuild brief now",   "example": "rebuild the brief",                       "tool": "brief_rebuild"},
        {"label": "Cycle status",        "example": "brief status",                            "tool": "brief_status"},
    ]},
    {"category": "Math & Quant Lab", "items": [
        {"label": "Calculate",           "example": "calculate 15% of 240",                    "tool": "math_solve"},
        {"label": "Solve equation",      "example": "solve x^2 - 5x + 6 = 0",                  "tool": "math_solve"},
        {"label": "Calculus",            "example": "integrate x^2 sin(x)",                    "tool": "math_solve"},
        {"label": "Stats on numbers",    "example": "stats of 3, 5, 8, 13, 21",                "tool": "math_solve"},
        {"label": "Pattern scan",        "example": "find patterns in SOFI",                   "tool": "pattern_scan"},
        {"label": "Pair correlation",    "example": "correlate SOFI and HOOD",                 "tool": "pair_correlation"},
    ]},
    {"category": "Live Trade Tape (real-time, free)", "items": [
        {"label": "Live movers",         "example": "what's moving right now",                 "tool": "live_movers"},
        {"label": "Live tape (symbol)",  "example": "live tape SOFI",                           "tool": "live_tape"},
        {"label": "Stream status",       "example": "stream status",                           "tool": "stream_status"},
    ]},
    {"category": "Live Trading (Alpaca)", "items": [
        {"label": "Account",             "example": "trading account",                         "tool": "trading_account"},
        {"label": "Positions",           "example": "show my positions",                       "tool": "trading_positions"},
        {"label": "Buy shares",          "example": "buy AAPL 10 shares",                       "tool": "trading_buy"},
        {"label": "Sell shares",         "example": "sell TSLA 5 shares",                       "tool": "trading_sell"},
        {"label": "Bracket order",       "example": "bracket NVDA 3",                           "tool": "trading_bracket"},
        {"label": "Trailing stop",       "example": "trail stop AAPL 10 1.5%",                 "tool": "trading_trail"},
        {"label": "Close position",      "example": "close TSLA position",                     "tool": "trading_close"},
        {"label": "Close all",           "example": "close all positions",                     "tool": "trading_close_all"},
        {"label": "Quote",               "example": "quote AAPL",                              "tool": "trading_quote"},
        {"label": "Trading risk",        "example": "trading risk",                            "tool": "trading_risk"},
        {"label": "Autonomy status",     "example": "can you trade on your own",               "tool": "autonomy_status"},
        {"label": "Political briefing",  "example": "political briefing",                      "tool": "political_briefing"},
        {"label": "Geo risk score",      "example": "geopolitical risk score",                 "tool": "geo_risk"},
        {"label": "Market movers (pol)", "example": "who is moving markets today",             "tool": "political_movers"},
        {"label": "Role news",           "example": "any fed news today",                      "tool": "role_news"},
    ]},
    {"category": "Options", "items": [
        {"label": "Options chain",       "example": "options chain SOFI",                      "tool": "options_chain"},
        {"label": "Best call/put",       "example": "best call SOFI",                          "tool": "options_scan"},
        {"label": "Options hunt",        "example": "options hunt",                            "tool": "options_hunt"},
        {"label": "Options positions",   "example": "options positions",                       "tool": "options_positions"},
        {"label": "Unusual activity",    "example": "unusual options activity SOFI",           "tool": "options_unusual"},
    ]},
    {"category": "Voice", "items": [
        {"label": "Voice status",        "example": "voice status",                            "tool": "voice_status"},
    ]},
    {"category": "Grok (xAI)", "items": [
        {"label": "Ask Grok",            "example": "ask grok to explain quantum computing simply", "tool": "ask_grok"},
        {"label": "Grok status",         "example": "grok status",                             "tool": "grok_status"},
    ]},
    {"category": "Free Flow Intel (no paid API)", "items": [
        {"label": "Gamma exposure",       "example": "greek exposure SOFI",                     "tool": "gamma_exposure"},
        {"label": "Congress trades",      "example": "congress trades SOFI",                    "tool": "congress_trades"},
        {"label": "VIX term structure",   "example": "market tide",                             "tool": "vix_term_structure"},
        {"label": "Block trade scan",     "example": "dark pool SOFI",                          "tool": "block_trade_scan"},
    ]},
    {"category": "Social & Retail Sentiment", "items": [
        {"label": "Social report",       "example": "social report SOFI",                      "tool": "social_report"},
        {"label": "StockTwits",          "example": "SOFI stocktwits",                         "tool": "stocktwits"},
        {"label": "Trending now",        "example": "trending social",                         "tool": "trending_social"},
        {"label": "WSB hot",             "example": "wsb hot",                                 "tool": "wsb_hot"},
        {"label": "Retail order flow",   "example": "retail flow SOFI",                        "tool": "retail_flow"},
    ]},
    {"category": "Market Intel", "items": [
        {"label": "Technicals",          "example": "technicals on NVDA",                      "tool": "market_technicals"},
        {"label": "Trade signal",        "example": "trade signal AAPL",                       "tool": "trade_signal"},
        {"label": "Market scan",         "example": "scan the market",                         "tool": "market_scan"},
        {"label": "Chart a symbol",      "example": "chart AAPL",                              "tool": "chart_price"},
        {"label": "Intraday analysis",   "example": "intraday analysis SOFI",                  "tool": "intraday_analysis"},
        {"label": "Multi-timeframe",     "example": "multi timeframe NVDA",                    "tool": "multi_timeframe"},
        {"label": "Geo brief",           "example": "geo brief",                               "tool": "geo_brief"},
        {"label": "Company research",    "example": "what's going on with SpaceX",             "tool": "company_research"},
        {"label": "Due diligence",       "example": "due diligence on SOFI",                   "tool": "stock_due_diligence"},
        {"label": "DD top picks (batch)","example": "due diligence on 20 top picks",           "tool": "dd_top_picks"},
        {"label": "Crypto prices",       "example": "crypto prices",                           "tool": "crypto_price"},
        {"label": "Web research",        "example": "look up who invented the transistor",     "tool": "web_research"},
    ]},
    {"category": "Everyday Assistant", "items": [
        {"label": "Weather",             "example": "weather",                                 "tool": "weather_now"},
        {"label": "Weather anywhere",    "example": "weather in Tokyo",                        "tool": "weather_now"},
        {"label": "Reminder",            "example": "remind me in 20 minutes to check the oven", "tool": "remind"},
        {"label": "Timer",               "example": "set a timer for 10 minutes",              "tool": "remind"},
        {"label": "Show reminders",      "example": "show my reminders",                       "tool": "reminders_list"},
        {"label": "Cancel reminder",     "example": "cancel reminder 1",                       "tool": "reminder_cancel"},
        {"label": "Unit conversion",     "example": "convert 5 miles to km",                   "tool": "unit_convert"},
        {"label": "Currency",            "example": "convert 100 usd to eur",                  "tool": "currency_convert"},
        {"label": "World time",          "example": "what time is it in Tokyo",                "tool": "world_time"},
        {"label": "Define a word",       "example": "define serendipity",                      "tool": "define_word"},
        {"label": "Coin / dice / pick",  "example": "pick between pizza and sushi",            "tool": "roll_random"},
        {"label": "Password",            "example": "generate a password",                     "tool": "password_gen"},
        {"label": "Next holidays",       "example": "next holidays",                           "tool": "next_holidays"},
        {"label": "Find a file",         "example": "find file tax",                           "tool": "file_find"},
    ]},
    {"category": "Daily", "items": [
        {"label": "Morning briefing",    "example": "give me my morning briefing",             "tool": "morning_briefing"},
        {"label": "Tasks",               "example": "show my tasks",                           "tool": "task_show"},
        {"label": "Add task",            "example": "add a task: ",                            "tool": "task_add"},
        {"label": "Remove task",         "example": "remove task 1",                           "tool": "task_remove"},
        {"label": "Clear all tasks",     "example": "clear all tasks",                         "tool": "task_remove"},
        {"label": "Notes",               "example": "show my recent notes",                    "tool": "note_show"},
    ]},
    {"category": "Money (non-trading)", "items": [
        {"label": "Bills",               "example": "show all my bills",                       "tool": "finance_list_bills"},
        {"label": "Budget overview",     "example": "show my budget",                          "tool": "finance_show_budget"},
        {"label": "Spending",            "example": "show my spending this month",             "tool": "finance_spending"},
    ]},
    {"category": "PC & Tech", "items": [
        {"label": "System info",         "example": "show my system info",                     "tool": "tech_system_info"},
        {"label": "Screenshot",          "example": "take a screenshot",                       "tool": "tech_screenshot"},
        {"label": "Open app",            "example": "open Chrome",                             "tool": "tech_open"},
        {"label": "Volume",              "example": "set volume to 50",                        "tool": "tech_volume"},
    ]},
    {"category": "Jarvis Brain", "items": [
        {"label": "Remember something",  "example": "jarvis remember ",                        "tool": "remember"},
        {"label": "What Jarvis knows",   "example": "jarvis memory",                           "tool": "memory_status"},
        {"label": "System status",       "example": "jarvis status",                           "tool": "jarvis_status"},
        {"label": "Conversation history","example": "what have we talked about",               "tool": "conversation_history"},
    ]},
]

# ── Expected output per tool (shown in the Commands tab under each example) ────
TOOL_OUTPUTS = {
    "ask_grok":          "Grok's (xAI) answer to your question",
    "grok_status":       "Grok API key/model connectivity status",
    "voice_status":      "speech-to-text/text-to-speech install + preset status",
    "trading_budget":    "live capital status: equity, buying power, deployment, goal progress",
    "goal_set":          "parsed goal: target, deadline, required $/day, applied risk profile",
    "goal_status":       "goal tracker: progress bar, required vs actual pace, days left",
    "goal_hold":         "freezes the risk profile against automatic escalation",
    "goal_release":      "re-enables automatic escalation (ceiling: AGGRESSIVE)",
    "goal_clear":        "deactivates the current goal",
    "account_sync_status": "synced Alpaca ground truth: buying power, PDT, last sync time",
    "tech_score":        "composite 0-100 technical score: trend/momentum/volume/volatility/S-R",
    "pattern_detect":    "chart patterns found with score, volume confirmation, targets",
    "price_prediction":  "entry, targets, stop, confidence, timeframe, R/R for a ticker",
    "autonomy_status":   "full autonomous-trading settings: switch, limits, hours, mode",
    "risk_params_show":  "current risk parameters from the Markets dashboard",
    "auto_hunt":         "ranked conviction scores across the whole scan universe, top pick reasoning",
    "conviction_score":  "0-100 score breakdown: TA/social/news/geo/options/F&G/insider + chart",
    "nyse_screener":     "budget-affordable NYSE/NASDAQ tickers ranked by liquidity + sentiment",
    "market_regime":     "bull / bear / volatile / sideways classification with evidence",
    "sector_heat":       "sector ETF day-change ranking + heat chart image",
    "squeeze_scan":      "tickers with high short interest + catalyst + momentum",
    "trade_why":         "the stored reasoning captured at the moment the trade was placed",
    "trade_skip_why":    "the stored reason JARVIS passed on a symbol during a scan",
    "trades_by_result":  "closed trades filtered to wins or losses",
    "trades_by_date":    "trades entered or exited on a specific day",
    "trades_by_reason":  "trades whose stored reasoning matches a keyword",
    "trade_history_full":"every closed trade + open position, not just the last 15",
    "market_outlook_show":  "0-100 market outlook score, mode, and component breakdown",
    "market_outlook_force": "pins the trading mode for today, overriding the computed score",
    "market_outlook_ignore":"outlook gate stops blocking new entries for today",
    "market_outlook_resume":"re-enables the outlook gate",
    "market_outlook_auto":  "clears a forced mode, back to the computed score",
    "options_threshold_set":"confirms the new options conviction threshold",
    "portfolio":         "capital, P&L, win rate, open positions, recent closed trades",
    "daily_brief":       "morning game plan: regime, sectors, VIX, geo, top picks, watchlist",
    "evening_review":    "post-close digest: trades vs plan, lesson learned, tomorrow's watchlist",
    "brief_rebuild":     "a freshly rebuilt morning brief (takes ~1 min)",
    "brief_status":      "scheduler state + which briefs exist for today",
    "math_solve":        "exact + decimal answer, solutions, or step result — 🧮 MATH report",
    "pattern_scan":      "🔬 trend/Hurst, autocorrelation, cycles, vol, weekday bias + synthesis",
    "pair_correlation":  "correlation, beta, lead-lag between the two tickers + synthesis",
    "live_movers":       "real-time buy/sell pressure ranking of currently streamed symbols",
    "live_tape":         "tick-by-tick buy/sell imbalance + trade velocity for one symbol",
    "stream_status":     "WebSocket connection state, symbols streamed, ticks received",
    "trading_account":   "Alpaca account: equity, buying power, cash, day P&L",
    "trading_positions": "every open position: qty, entry, current, unrealized P&L",
    "trading_buy":       "order confirmation with fill details (risk-param gated)",
    "trading_sell":      "sell order confirmation with fill details",
    "trading_bracket":   "entry + auto stop-loss + take-profit order confirmation",
    "trading_trail":     "trailing-stop order confirmation",
    "trading_close":     "position flattened to zero, realized P&L",
    "trading_close_all": "full liquidation of all positions",
    "trading_quote":     "live bid/ask/last for the symbol",
    "trading_risk":      "daily loss-limit status and risk headroom",
    "options_chain":     "live option contracts: strikes, expiries, premiums",
    "options_scan":      "best call/put pick for the symbol with delta/expiry logic",
    "options_hunt":      "highest-conviction options play across the universe",
    "options_positions": "open option contracts with P&L",
    "options_unusual":   "call/put volume skew + contracts trading 2x+ open interest",
    "gamma_exposure":    "homegrown GEX: gamma wall strikes computed from the live chain",
    "congress_trades":   "recent STOCK Act disclosures (warns if the feed is stale)",
    "vix_term_structure":"VIX9D/VIX/VIX3M curve — fear vs complacency read",
    "block_trade_scan":  "large lit-tape prints (an honest proxy — NOT true dark pool)",
    "social_report":     "StockTwits + Reddit + retail tape + Finviz sentiment rollup",
    "stocktwits":        "real-time crowd sentiment % for the ticker",
    "trending_social":   "tickers trending across StockTwits/Reddit right now",
    "wsb_hot":           "hottest WallStreetBets discussion tickers",
    "retail_flow":       "retail buy/sell pressure: tick-rule + odd-lot % from the tape",
    "market_technicals": "RSI, MAs, ATR, support/resistance + price chart",
    "trade_signal":      "buy/hold/avoid signal with TA reasoning",
    "market_scan":       "multi-ticker TA sweep + chart",
    "chart_price":       "price chart image: SMA 20/50/200 + RSI panel",
    "intraday_analysis": "VWAP, stochastic, Williams %R from live intraday bars",
    "multi_timeframe":   "daily/hourly/15-min alignment read",
    "geo_brief":         "geopolitical themes affecting markets",
    "company_research":  "ticker, price, TA, IPO status, news for any company name",
    "crypto_price":      "spot prices + 24h change for major coins",
    "web_research":      "real web lookup (DuckDuckGo + Wikipedia) synthesized into an answer",
    "weather_now":       "current temp/conditions + 3-day outlook (real data, not a browser tab)",
    "remind":            "confirmation with fire time — reminder pops into chat when due",
    "reminders_list":    "all pending reminders with #ids and fire times",
    "reminder_cancel":   "cancellation confirmation",
    "unit_convert":      "converted value (length/mass/volume/temp/speed/data/area)",
    "currency_convert":  "live ECB exchange conversion with rate date",
    "world_time":        "current time + day in that city, offset vs local",
    "define_word":       "definitions by part of speech, example usage, synonyms",
    "roll_random":       "coin face / dice rolls / random number / picked option",
    "password_gen":      "3 cryptographically random passwords (never stored)",
    "next_holidays":     "next 8 public holidays with countdown days",
    "file_find":         "up to 15 matching files with size + modified date",
    "morning_briefing":  "life briefing: weather, tasks, bills, habits, meds",
    "task_show":         "open tasks grouped by priority",
    "task_add":          "task saved confirmation (duplicates rejected)",
    "stock_due_diligence": "full DD report with live fundamentals, saved as .txt",
    "dd_top_picks":      "kicks off background DD on top picks; reports save as they finish",
    "dd_status":         "batch progress: done/total, completed, skipped tickers",
    "task_remove":       "removed task names, or a numbered list if ambiguous",
    "note_show":         "recent saved notes",
    "finance_list_bills":"all bills with amounts and due days",
    "finance_show_budget":"budget categories vs actual spending",
    "finance_spending":  "spending log summary for the period",
    "tech_system_info":  "CPU/RAM/disk/GPU snapshot",
    "tech_screenshot":   "screenshot saved to Pictures + path",
    "tech_open":         "launches the app on the PC",
    "tech_volume":       "system volume set confirmation",
    "remember":          "fact saved to permanent memory",
    "memory_status":     "what Jarvis has learned: preferences, corrections, stats",
    "jarvis_status":     "offline/decentralized health: Ollama, memory DB, monitors",
    "conversation_history": "recap of recent conversations (survives restarts)",
}

# ── Tool catalog (for the "Tools" tab): every registered tool + its function ───
TOOL_DOCS = [
    ("Everyday Assistant", {
        "weather_now":      "real current conditions + 3-day forecast (Open-Meteo, keyless)",
        "remind":           "natural-language reminders/timers that fire into the chat",
        "reminders_list":   "list pending reminders",
        "reminder_cancel":  "cancel a reminder by # or keyword",
        "unit_convert":     "length/mass/volume/cooking/temp/speed/data/area conversion",
        "currency_convert": "live ECB currency conversion (frankfurter.app, keyless)",
        "world_time":       "time in any city (offline zoneinfo database)",
        "define_word":      "dictionary: definitions, examples, synonyms",
        "roll_random":      "coin flip, dice (NdM), random number, pick-for-me",
        "password_gen":     "cryptographically secure passwords, generated locally",
        "next_holidays":    "upcoming public holidays for any country",
        "file_find":        "search Desktop/Documents/Downloads/... for a file by name",
    }),
    ("Math & Quant Lab", {
        "math_solve":       "arithmetic → algebra → calculus → ODEs/matrices (sympy, local)",
        "pattern_scan":     "statistical pattern hunt on real price history + trading synthesis",
        "pair_correlation": "correlation / beta / lead-lag between two tickers",
    }),
    ("Trading Engine", {
        "trading_budget":   "live capital status + goal progress",
        "goal_set":         "state a financial goal — JARVIS adapts its trading to it",
        "goal_status":      "goal tracker: pace vs required, days left",
        "goal_hold":        "freeze risk profile against auto-escalation",
        "goal_release":     "re-enable auto-escalation (max aggressive)",
        "goal_clear":       "deactivate the goal",
        "account_sync_status": "live Alpaca account sync state",
        "tech_score":       "composite 0-100 technical score for a ticker",
        "pattern_detect":   "classical chart pattern detection + targets",
        "price_prediction": "multi-input price prediction block",
        "auto_hunt":        "scan universe, rank by conviction, optionally auto-trade the best",
        "conviction_score": "0-100 multi-signal score for one ticker",
        "nyse_screener":    "budget-friendly liquid stocks across all NYSE/NASDAQ",
        "market_regime":    "bull/bear/volatile/sideways classifier",
        "sector_heat":      "sector rotation ranking + chart",
        "squeeze_scan":     "short-squeeze candidate scan",
        "geo_brief":        "geopolitical macro brief",
    }),
    ("Daily Intelligence", {
        "daily_brief":      "auto-built morning game plan (builds itself ~8AM)",
        "evening_review":   "post-close review + tomorrow's watchlist (~4:10PM)",
        "brief_rebuild":    "force-rebuild the morning brief now",
        "evening_rebuild":  "force-rebuild the evening review now",
        "brief_status":     "daily-cycle scheduler status",
    }),
    ("Live Trading (Alpaca)", {
        "trading_account":  "account equity / buying power / cash",
        "trading_positions":"open positions with P&L",
        "trading_pnl":      "today's realized + unrealized P&L",
        "trading_orders":   "open orders", "trading_history": "recent order history",
        "trading_buy":      "market/limit buy", "trading_sell": "market/limit sell",
        "trading_bracket":  "entry + stop + target in one order",
        "trading_trail":    "trailing-stop order", "trading_cancel": "cancel open orders",
        "trading_close":    "flatten one position", "trading_close_all": "flatten everything",
        "trading_quote":    "live bid/ask", "trading_snapshot": "full quote snapshot",
        "trading_bars":     "recent OHLCV bars", "trading_size": "position-size calculator",
        "trading_risk":     "daily loss-limit status", "trading_perf": "win rate + P&L stats",
        "strategy_momentum":"momentum TA scan", "strategy_orb": "opening-range breakout levels",
        "strategy_vwap":    "VWAP deviation setup", "strategy_gaps": "pre-market gap scanner",
        "strategy_execute": "auto-trade a strategy with bracket order",
        "market_clock":     "is the market open right now",
        "autonomy_status":  "am I trading autonomously? settings + status",
        "risk_params_show": "current Markets-dashboard risk parameters",
        "political_briefing": "role-based political intel: events, calendar, geo risk, top plays",
        "geo_risk":         "geopolitical risk 0-100 + what it does to sizing/conviction",
        "political_movers": "which political figures are moving markets right now",
        "role_news":        "recent statements by a tracked role (president, Fed chair...)",
        "person_impact":    "a political figure's role-based market impact map",
        "role_set":         "update who holds a role — impact map follows the role",
        "political_scan_now": "run a political news scan immediately",
        "political_status": "political scanner health",
        "queue_show":       "ranked opportunity queue from the broad/narrow scanners",
        "queue_action":     "promote/demote/remove a queue entry",
        "scan_status":      "broad+narrow scanner health and run counts",
        "bridge_show":      "cross-sector bridge company map",
        "bridge_add":       "add a discovered bridge company to the map",
    }),
    ("Trade Monitor", {
        "monitor_start":    "start the 30s background position monitor",
        "monitor_stop":     "stop the monitor", "monitor_status": "monitor health + rules",
        "portfolio":        "full mission dashboard", "trade_why": "stored reasoning for a trade",
        "trade_skip_why":   "why a scanned symbol was passed on",
        "trades_by_result": "wins or losses filter", "trades_by_date": "trades on a given day",
        "trades_by_reason": "trades matching a reasoning keyword",
        "trade_history_full": "the complete closed + open trade history",
    }),
    ("Market Outlook", {
        "market_outlook_show":   "0-100 score, mode, and component breakdown",
        "market_outlook_force":  "pin today's trading mode, overriding the score",
        "market_outlook_ignore": "stop the outlook gate blocking new entries today",
        "market_outlook_resume": "re-enable the outlook gate",
        "market_outlook_auto":   "clear a forced mode",
        "options_threshold_set": "change the options conviction bar",
    }),
    ("Live Trade Tape", {
        "live_movers":      "real-time buy/sell pressure across streamed symbols",
        "live_tape":        "tick-by-tick pressure for one symbol",
        "stream_status":    "WebSocket stream health",
        "stream_start":     "start the live stream", "stream_stop": "stop the live stream",
    }),
    ("Options", {
        "options_chain":    "live chain: strikes/expiries/premiums",
        "options_scan":     "best call/put for a symbol", "options_hunt": "best play across universe",
        "options_buy":      "buy a contract", "options_close": "close a contract",
        "options_positions":"open option positions", "options_unusual": "unusual volume activity",
        "options_chain_yahoo": "options chain via Yahoo (backup source)",
    }),
    ("Voice", {
        "voice_status": "speech-to-text/text-to-speech install + preset status",
    }),
    ("Grok (xAI)", {
        "ask_grok":    "ask xAI's Grok — harder reasoning, very current events, second opinions",
        "grok_status": "Grok API key/model connectivity status",
    }),
    ("Flow Intel (free, homegrown)", {
        "gamma_exposure":   "GEX computed from the live chain (Black-Scholes, homegrown)",
        "congress_trades":  "STOCK Act congressional disclosures",
        "vix_term_structure":"VIX curve macro read",
        "block_trade_scan": "large lit prints (dark-pool PROXY, honestly labeled)",
    }),
    ("Social & Sentiment", {
        "social_report":    "combined social sentiment rollup for a ticker",
        "social_signal":    "same rollup (conviction-engine form)",
        "stocktwits":       "StockTwits crowd sentiment", "trending_social": "trending tickers now",
        "wsb_hot":          "WallStreetBets hot tickers", "retail_flow": "retail tape pressure",
        "geo_deep":         "deep multi-source geopolitical brief",
        "reddit_sentiment": "Reddit sentiment for a ticker",
    }),
    ("Market Intel", {
        "stock_quote":      "price quote", "stock_analyze": "full single-stock analysis",
        "stock_due_diligence": "DD report w/ REAL yfinance fundamentals, saved to Reports",
        "dd_top_picks":     "autonomous batch DD on Jarvis's top picks (background)",
        "dd_status":        "batch DD progress", "stock_compare": "side-by-side comparison",
        "stock_screen":     "screen by criteria", "portfolio_build": "model portfolio builder",
        "market_analysis":  "topic analysis", "market_technicals": "TA + chart",
        "trade_signal":     "buy/hold/avoid signal", "market_scan": "multi-ticker sweep",
        "chart_price":      "price chart image", "intraday_analysis": "intraday TA",
        "multi_timeframe":  "multi-timeframe alignment", "market_calendar": "market holidays",
        "market_news":      "market headlines", "earnings_cal": "earnings calendar",
        "ipo_pipeline":     "upcoming IPOs", "company_research": "research any company by name",
        "news_fetch":       "news search", "news_sentiment": "news tone for a ticker",
        "watchlist_add":    "add to watchlist", "watchlist_remove": "remove from watchlist",
        "watchlist_view":   "show watchlist", "watchlist_alert": "price alert",
        "crypto_price":     "crypto spot prices", "crypto_analyze": "single-coin analysis",
        "crypto_dominance": "BTC dominance", "paper_trade": "simulated trade",
        "paper_portfolio":  "simulated portfolio", "risk_check": "position-risk calculator",
        "strategy_define":  "save a custom strategy", "strategy_run": "run saved strategies",
        "retirement_plan":  "compound-growth projection",
        "stock_portfolio":  "brokerage portfolio", "stock_order": "brokerage order",
    }),
    ("Intelligence & Web", {
        "fear_greed":       "CNN-style fear & greed index", "insider_trades": "SEC Form 4 buys/sells",
        "sec_filings":      "SEC filings search", "analyst_ratings": "analyst price targets",
        "short_interest":   "short interest data", "economic_events": "macro calendar",
        "web_research":     "real web lookup (DuckDuckGo+Wikipedia) — answers in chat",
        "wikipedia":        "Wikipedia summary", "translate_text": "translate text",
        "page_summary":     "summarize a URL", "domain_intel": "whois/DNS intel",
        "site_status":      "is a site up", "pwned_check": "email breach check",
        "github_trending":  "trending GitHub repos", "patent_search": "patent search",
        "job_scan":         "job listings scan", "company_funding": "startup funding lookup",
        "web_monitor_add":  "watch a page for changes", "web_monitor_check": "check watched pages",
        "web_monitor_list": "list watched pages", "web_monitor_remove": "unwatch a page",
        "price_watch_add":  "watch a product price", "price_watch_check": "check price watches",
        "web_fetch":        "fetch a URL's text",
    }),
    ("Daily Life", {
        "morning_briefing": "weather+tasks+bills+habits digest",
        "task_add": "add task (duplicate-safe)", "task_show": "show tasks",
        "task_complete": "complete task", "task_delete": "delete task by name",
        "task_remove": "remove tasks by number/keyword/'all'",
        "note_add": "save note", "note_show": "recent notes",
        "note_search": "search notes", "habit_add": "track a habit",
        "habit_complete": "check off a habit", "habit_show": "habit streaks",
        "grocery_add": "add to grocery list", "grocery_show": "grocery list",
        "grocery_remove": "remove item", "grocery_clear": "clear list",
        "grocery_check": "is item on list", "grocery_order": "open store order page",
        "pantry_update": "update pantry stock", "pantry_show": "pantry contents",
    }),
    ("Money (personal)", {
        "finance_add_bill": "add a bill", "finance_list_bills": "all bills",
        "finance_audit": "bill audit", "finance_upcoming": "bills due soon",
        "finance_remove_bill": "remove bill", "finance_set_budget": "set category budget",
        "finance_show_budget": "budget overview", "finance_log_expense": "log an expense",
        "finance_spending": "spending summary", "finance_add_goal": "savings goal",
        "finance_show_goals": "goal progress", "finance_update_goal": "update goal",
        "finance_health": "overall financial health check",
    }),
    ("Health & People", {
        "health_add_med": "add medication", "health_list_meds": "medication list",
        "health_med_reminder": "meds due now", "health_log_workout": "log workout",
        "health_workout_summary": "workout stats", "health_log": "log a health metric",
        "health_summary": "health overview", "contact_add": "save contact",
        "contact_find": "find contact", "contact_list": "all contacts",
        "contact_birthdays": "upcoming birthdays",
    }),
    ("PC & Tech", {
        "tech_open": "launch an app", "tech_system_info": "hardware snapshot",
        "tech_disk_cleanup": "disk cleanup", "tech_network": "network check",
        "tech_flush_dns": "flush DNS", "tech_lock": "lock the PC",
        "tech_screenshot": "screenshot to Pictures",
        "tech_volume": "set volume", "tech_update": "open Windows Update",
        "tech_shutdown": "shut down PC", "tech_restart": "restart PC",
    }),
    ("Web & Apps (opens browser)", {
        "web_open": "open a URL", "web_search": "Google search tab",
        "web_news": "Google News tab", "web_directions": "Maps directions",
        "web_nearby": "nearby places", "web_track": "package tracking",
        "travel_flights": "flight search", "travel_hotels": "hotel search",
        "travel_uber": "Uber to destination", "travel_lyft": "Lyft to destination",
        "food_order": "order food", "food_find": "find restaurants",
        "food_ubereats": "UberEats", "ent_netflix": "Netflix", "ent_spotify": "Spotify",
        "ent_youtube": "YouTube", "ent_tickets": "event tickets",
        "ent_reservation": "restaurant reservation", "google_open": "open a Google app",
        "google_new_sheet": "new Sheet", "google_new_doc": "new Doc",
        "google_new_slide": "new Slides", "google_build_spreadsheet": "AI-built spreadsheet",
    }),
    ("Jarvis Brain (self-learning)", {
        "memory_status": "what Jarvis has learned about you",
        "remember": "save a fact forever", "forget": "delete a memory",
        "jarvis_status": "offline/decentralized health status",
        "conversation_history": "recall past conversations (survives restarts)",
        "consolidate_memory": "compress old conversation into summary now",
        "memory_show": "(legacy) keyword memory", "memory_add": "(legacy) save keyword memory",
        "memory_clear": "(legacy) clear keyword memory", "intent_status": "semantic matcher status",
    }),
    ("CS2 AI", {
        "cs2_launch": "launch CS2 via Steam", "cs2_start": "start the CS2 assist AI",
        "cs2_stop": "stop the CS2 AI", "cs2_pause": "pause the CS2 AI",
        "cs2_resume": "resume the CS2 AI", "cs2_status": "CS2 AI health + state",
        "cs2_combat_start": "start autonomous combat AI (aim + fire)",
        "cs2_combat_stop": "stop combat AI", "cs2_combat_pause": "pause combat AI",
        "cs2_combat_status": "combat AI state", "cs2_test_shot": "fire one test shot",
        "cs2_aim_assist": "toggle aim assist", "cs2_takeover": "takeover mode status",
        "cs2_setup_yolo": "install/repair the YOLO vision model",
        "cs2_yolo_status": "vision model status", "cs2_yolo_test": "run a vision test frame",
        "cs2_yolo_conf": "set vision confidence threshold",
        "cs2_vision_test": "screen-capture vision test", "cs2_input_test": "input pipeline test",
        "cs2_sensitivity": "get/set mouse sensitivity", "cs2_weapon": "weapon stats + advice",
        "cs2_reaction": "reaction-time trainer", "cs2_practice": "practice routine",
        "cs2_advice": "coaching advice", "cs2_tips": "tips for a map/situation",
        "cs2_set_map": "tell the AI which map you're on", "cs2_map_list": "known maps",
        "cs2_agent_list": "known agents", "cs2_callout": "map callout lookup",
        "cs2_position": "positioning advice", "cs2_where_to_look": "crosshair placement advice",
    }),
    ("Fall Guys AI", {
        "fallguys_launch": "launch Fall Guys", "fallguys_start": "start the Fall Guys AI",
        "fallguys_stop": "stop it", "fallguys_pause": "pause it",
        "fallguys_status": "AI state", "fallguys_advice": "minigame strategy advice",
        "fallguys_teach": "teach it a minigame", "fallguys_analyze": "analyze current screen",
        "fallguys_minigames": "known minigames", "fallguys_controller": "choose input mode",
        "fallguys_test_input": "input test",
        "fallguys_ctrl_start": "controller-based auto-play", "fallguys_ctrl_stop": "stop it",
        "fallguys_ctrl_pause": "pause it", "fallguys_ctrl_status": "controller AI state",
        "fallguys_ctrl_test": "controller test",
        "fallguys_smart_start": "vision-guided smart mode", "fallguys_smart_stop": "stop smart mode",
        "fallguys_smart_pause": "pause smart mode", "fallguys_smart_status": "smart mode state",
        "fallguys_vision_test": "vision test", "fallguys_stats": "session win stats",
    }),
    ("Game AI (any game)", {
        "game_load": "load/create a profile for any game", "game_advice": "strategy advice",
        "game_analyze": "analyze the current screen", "game_auto_fps": "generic FPS auto-play",
        "game_stop": "stop the game AI", "game_pause": "pause it",
        "game_move": "move the character", "game_look": "turn the camera",
        "game_shoot": "fire", "game_action": "perform a named action",
        "game_sequence": "run an action sequence", "game_detect_targets": "vision target scan",
        "game_press_key": "tap a key", "game_hold_key": "hold a key",
        "game_hotkey": "key combo", "game_record_start": "record your inputs",
        "game_record_stop": "stop recording", "game_replay": "replay a recording",
        "list_game_profiles": "saved game profiles",
    }),
    ("Virtual Controller", {
        "ctrl_status": "virtual Xbox controller status", "ctrl_list_devices": "input devices",
        "ctrl_install_vigem": "install the ViGEm controller driver",
        "ctrl_press": "press a button", "ctrl_trigger": "pull a trigger",
        "ctrl_stick": "move a stick", "ctrl_move": "movement macro",
        "ctrl_look": "camera macro", "ctrl_jump": "jump", "ctrl_dive": "dive",
        "ctrl_grab": "grab", "ctrl_shoot": "shoot", "ctrl_reset": "reset all inputs",
        "xbox_press": "press an Xbox button", "xbox_stick": "move an Xbox stick",
        "xbox_trigger": "pull an Xbox trigger",
    }),
    ("Devices", {
        "devices_list": "devices on the network", "phone_info": "phone details (ADB)",
        "phone_backup": "back up the phone", "phone_adb_shell": "run an ADB command (gated)",
        "phone_root_plan": "rooting research plan (info only)",
        "webcam_info": "webcam check", "smart_devices_scan": "smart-home device scan",
        "tasmota_plan": "smart-plug flashing plan (info only)",
        "device_confirm": "approve a pending device action",
        "device_pending": "pending device actions", "device_log": "device action history",
    }),
]

# ── Natural language normalization ─────────────────────────────────────────────
_SLANG = [
    (r'\bwdym\b', 'what do you mean'), (r'\bidk\b', "I don't know"),
    (r'\bimo\b', 'in my opinion'), (r'\btbh\b', 'to be honest'),
    (r'\bngl\b', 'not gonna lie'), (r'\bnvm\b', 'never mind'),
    (r'\brn\b', 'right now'), (r'\basap\b', 'as soon as possible'),
    (r'\bbtw\b', 'by the way'), (r'\bfyi\b', 'for your information'),
    (r'\bomg\b', 'oh my god'), (r'\blmk\b', 'let me know'),
    (r'\bhmu\b', 'hit me up'), (r'\bsmh\b', 'shaking my head'),
    (r'\bfr\b', 'for real'), (r'\bngl\b', 'not gonna lie'),
    (r'\bgoat\b', 'greatest of all time'), (r'\bslay\b', 'excellent'),
    (r'\blit\b', 'great'), (r'\bsick\b', 'impressive'),
    (r'\bfire\b(?!\s+up)', 'great'),
    (r'\bfire\s+up\b', 'launch'), (r'\bpull\s+up\b', 'open'),
    (r'\bdrop\b(?!\s+(?:by|in|out|off))', 'give me'),
    (r'\bhit\s+me\s+with\b', 'give me'), (r'\brun\s+it\b', 'execute'),
    (r'\bcheck\s+it\b', 'check'), (r'\bwhat(?:\'s|\s+is)\s+good\s+with\b', 'what is the status of'),
    (r'\bwhat(?:\'s|\s+is)\s+the\s+move\b', 'what should I do'),
    (r'\bwhat(?:\'s|\s+is)\s+poppin\b', 'what is happening'),
    (r'\bno\s+cap\b', ''), (r'\bfacts\b', 'yes'), (r'\bsay\s+less\b', 'okay'),
]
_HEDGE_PHRASES = [
    "i don't have access", "i cannot access", "i'm not able to", "i can't access",
    "i don't have real-time", "i cannot provide real-time", "as an ai",
    "i'm just an ai", "i don't have the ability", "i cannot browse",
    "i'm unable to", "unfortunately i", "i apologize", "i'm sorry, i can't",
    "i lack the ability", "i do not have access",
    "i don't have the capability", "i do not have the capability",
    "without explicit instructions", "i can't trade autonomously",
    "i cannot make autonomous", "i can't make autonomous",
    "i am limited to", "i'm limited to", "i would need explicit instructions",
    # Narrates an action instead of actually calling the tool — same failure
    # mode as a hedge: the user sees "let me pull up X" and then nothing happens.
    "let me pull up", "let me check", "let me look", "let me get",
    "let me find", "let me grab", "let me run", "let me fetch",
    "i'll pull up", "i'll check", "i'll look", "i'll get that",
    "i'll run", "i'll fetch", "pulling up", "give me a moment",
    "one moment", "let's take a look", "let me take a look",
]

# Wall Street $ticker notation ($net, $TSLA, $Aapl) — stripped and uppercased
# as the very first NLU step (called at the top of process(), before ANY
# other routing) so every downstream consumer — regex matching, the LLM —
# sees a plain ticker token it already knows how to handle. A $-prefixed
# token is unambiguous: it is ALWAYS a ticker, never an English word.
_DOLLAR_TICKER_RE = re.compile(r'\$([A-Za-z]{1,5})\b')

def _normalize_tickers(msg: str):
    """Strip the $ prefix from ticker mentions and uppercase them ($net -> NET).
    Returns (clean_msg, tickers) where tickers is the ordered list of symbols
    found this way — each one is KNOWN to be a ticker (the user typed $, not
    a guess), so callers can force a grounded lookup instead of letting the
    LLM guess/hallucinate when no other pattern claims it."""
    tickers = []
    def _sub(m):
        t = m.group(1).upper()
        tickers.append(t)
        return t
    clean = _DOLLAR_TICKER_RE.sub(_sub, msg)
    return clean, tickers

def _normalize(msg: str) -> str:
    """Expand slang and normalize casual phrasing so the LLM reads it clearly."""
    out = msg
    for pat, rep in _SLANG:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out.strip()

# Short replies that ANSWER the previous message rather than start a new
# request — "yes" after "want me to run an auto hunt?" must resolve against
# that question, not be treated as a standalone prompt.
_AFFIRM_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|y|sure|ok(?:ay)?|sounds good|do it|go ahead|go for it|"
    r"proceed|please do|let'?s do it|make it so|run it|execute|absolutely|definitely|"
    r"no|nope|nah|not now|maybe later|skip(?:\s+it)?|neither|"
    r"(?:the\s+)?(?:first|second|third|last)(?:\s+one|\s+option)?|that one|"
    r"option\s+\d|\d)[\s!.,]*$", re.I)

def _last_assistant(hist: list) -> str:
    return next((h["content"] for h in reversed(hist) if h["role"] == "assistant"), "")

def _enrich(msg: str, hist: list) -> str:
    """Add context hints to help LLM handle short or referential messages."""
    words = msg.split()
    hints = []
    affirm = bool(_AFFIRM_RE.match(msg.strip()))
    if affirm and hist:
        last = _last_assistant(hist)
        # The subject is often in THEIR previous message, not just your reply
        # ("should I add PTON to the watchlist?" → "confirm?" → "yes")
        last_user = next((h["content"] for h in reversed(hist)
                          if h["role"] == "user"), "")
        if last:
            hints.append(
                "CONTINUATION: the user is ANSWERING your previous message, which "
                f"ended: \"...{last[-200:].strip()}\"" +
                (f" (their request before that was: \"{last_user[-150:].strip()}\")"
                 if last_user else "") +
                " — decide which case this is:\n"
                "(a) You offered ONE specific action whose parameters (ticker, "
                "item, etc.) are already known from the discussion → output that "
                "tool-call JSON now.\n"
                "(b) Your question was strategic/open-ended (criteria, methods, "
                "'want help with X?') → they said yes to the APPROACH: carry it "
                "out or lay it out concretely yourself, running research tools "
                "whose parameters you can infer. NEVER call a tool with missing "
                "or empty parameters — if you don't have a parameter, don't "
                "call the tool.\n"
                "(c) They declined → acknowledge briefly.\n"
                "Do NOT treat this as a new standalone command and do NOT say "
                "you lack context")
    # Short commands — likely an action request (but never pressure small talk
    # or an answer-to-your-question into an unrelated tool call)
    if len(words) <= 3 and not _is_smalltalk(msg) and not affirm:
        hints.append("SHORT COMMAND: interpret as a direct request; use a tool if one applies")
    # Referential pronouns — resolve using history
    if re.search(r'\b(it|that|this|those|them|the same|the one)\b', msg, re.I) and hist:
        last = next((h["content"] for h in reversed(hist) if h["role"] == "assistant"), "")
        if last:
            hints.append(f"CONTEXT: previous response was about: {last[:120].strip()}")
    if hints:
        return f"[{'; '.join(hints)}]\n{msg}"
    return msg

# Local models drift on the tool-call schema no matter what the prompt says —
# real captured example: {"action": "brief_rebuild", "prompt": "..."} shown RAW
# to the user because only the "tool" key was recognized. Normalize the
# variants they actually emit instead of hoping the prompt holds.
_TOOL_KEY_ALIASES  = ("tool", "action", "name", "function", "tool_name", "command")
_PARAM_KEY_ALIASES = ("params", "parameters", "arguments", "args", "input")

def _normalize_tool_call(obj):
    """Map schema variants to {"tool":..., "params":...}. None if not a tool call."""
    if not isinstance(obj, dict):
        return None
    tool = ""
    tool_key = None
    for k in _TOOL_KEY_ALIASES:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            tool = v.strip()
            tool_key = k
            break
    if not tool:
        # Deeper schema drift: the tool name shows up as a VALUE under some
        # key we've never seen — real capture: {"status":"daily_brief",
        # "briefing":true}. Only an exact TOOLS name counts, so JSON data the
        # LLM merely quotes can never trigger execution.
        for k, v in obj.items():
            if isinstance(v, str) and v.strip() in TOOLS:
                tool = v.strip()
                tool_key = k
                break
    if not tool:
        # Or as the KEY: {"watchlist_add": "PTON"} / {"live_tape": {"symbol":
        # "SOFI"}} — real capture from a yes-continuation. Same exact-name gate.
        for k, v in obj.items():
            if k in TOOLS:
                if isinstance(v, dict):
                    return {"tool": k, "params": v}
                if isinstance(v, (str, int, float)) and str(v).strip():
                    # Scalar param with an unknown name — fan it out to the
                    # common param keys; dispatch lambdas pick the one they use.
                    s = str(v).strip()
                    return {"tool": k, "params": {
                        p_k: s for p_k in ("symbol", "ticker", "query", "expression",
                                           "text", "note", "item", "items", "name",
                                           "keyword", "task", "spec", "location",
                                           "place", "word", "company", "topic")}}
                return {"tool": k, "params": {}}
    if not tool:
        return None
    # The exact "tool" key keeps its historical behavior (run_tool reports
    # unknown names itself); alias keys must name a REAL tool so random JSON
    # the LLM happens to quote can never trigger execution.
    if "tool" not in obj and tool not in TOOLS:
        return None
    params = {}
    for k in _PARAM_KEY_ALIASES:
        v = obj.get(k)
        if isinstance(v, dict):
            params = v
            break
    if not params:
        # Loose scalar keys as params: {"action":"live_tape","symbol":"SOFI"}
        meta = set(_TOOL_KEY_ALIASES) | set(_PARAM_KEY_ALIASES) | {
            "prompt", "reason", "thought", "explanation", "message", tool_key}
        params = {k: v for k, v in obj.items()
                  if k not in meta and isinstance(v, (str, int, float, bool))}
    return {"tool": tool, "params": params}

def _extract_tool_calls(text: str) -> list:
    """Pull all tool-call objects (any recognized schema) out of LLM response text."""
    clean = re.sub(r'```(?:json)?', '', text).strip()
    calls = []
    # Try the whole string as a JSON array first
    try:
        arr = json.loads(clean)
        if isinstance(arr, list):
            for item in arr:
                tc = _normalize_tool_call(item)
                if tc:
                    calls.append(tc)
            if calls:
                return calls
    except Exception:
        pass
    # Walk character by character finding { ... } objects
    for m in re.finditer(r'\{', clean):
        start = m.start(); depth = 0
        for i, ch in enumerate(clean[start:]):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        tc = _normalize_tool_call(json.loads(clean[start:start + i + 1]))
                        if tc:
                            calls.append(tc)
                    except Exception:
                        pass
                    break
    return calls

def _sanitize_reply(text: str, fallback: str = "") -> str:
    """
    Final gate for every LLM-composed reply: the user must NEVER see raw JSON.
    - {"content"/"reply"/...: "..."} wrappers → unwrap the actual text
    - whole-reply JSON (data dumps, {"task": ...} echoes) → replaced by
      `fallback` (the real tool output when we have it)
    - JSON lines mixed into prose → the JSON lines are dropped, prose kept
    Local models mimic whatever is in recent history, so one leaked JSON reply
    breeds more — this plus history hygiene breaks that feedback loop.
    """
    t = re.sub(r'```(?:json)?|```', '', text or "").strip()
    if not t:
        return fallback or "(no response — try that once more)"
    if t[:1] in "{[":
        try:
            obj = json.loads(t)
        except Exception:
            obj = None
        if obj is not None:
            if isinstance(obj, dict):
                for k in ("content", "response", "reply", "text", "message",
                          "answer", "briefing", "summary"):
                    v = obj.get(k)
                    if isinstance(v, str) and len(v.strip()) >= 8:
                        return v.strip()
            return fallback or ("I garbled that reply into JSON — say it once "
                                "more and I'll answer properly.")
    # Mixed content: drop any line that is itself a complete JSON object/array
    kept, dropped = [], 0
    for ln in t.splitlines():
        s = ln.strip()
        if s[:1] in "{[" and s[-1:] in "}]":
            try:
                json.loads(s)
                dropped += 1
                continue
            except Exception:
                pass
        kept.append(ln)
    if dropped:
        t2 = "\n".join(kept).strip()
        return t2 or fallback or t
    return t


def _is_hedge(reply: str) -> bool:
    """Return True if the LLM punted instead of acting."""
    low = reply.lower()
    return any(p in low for p in _HEDGE_PHRASES)

# ── Semantic intent corpus ──────────────────────────────────────────────────────
_intent_built = 0.0

def _refresh_intent_corpus(force: bool = False):
    """
    (Re)build the semantic matcher's example corpus: every Commands-tab
    example/label PLUS the user's own learned phrasings from interaction
    memory — so Jarvis literally gets better at the user's vernacular over
    time. Refreshes hourly to pick up newly learned phrasings.
    """
    global _intent_built
    if not HAS_INTENT:
        return
    if not force and time.time() - _intent_built < 3600:
        return
    entries = []
    for cat in COMMAND_REFERENCE:
        for it in cat.get("items", []):
            tool = it.get("tool", "")
            if not tool:
                continue
            if it.get("example"):
                entries.append({"phrase": it["example"], "tool": tool})
            if it.get("label"):
                entries.append({"phrase": it["label"], "tool": tool})
    try:
        for tool, info in (MEM.learned_command_examples() or {}).items():
            ph = (info or {}).get("phrase", "")
            if ph:
                entries.append({"phrase": ph, "tool": tool})
    except Exception:
        pass
    INTENT.set_corpus(entries)
    _intent_built = time.time()

# ── LLM-based intent decomposition ────────────────────────────────────────────
def _llm_intent_parse(msg: str) -> list:
    """
    Use Ollama to break a complex message into discrete action strings.
    Each returned string is then run through match_all() independently.
    Returns [] on any failure so callers degrade gracefully.
    """
    try:
        import ollama
        r = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    "Break this message into separate, self-contained action strings. "
                    "Output ONLY a JSON array of short strings — no other text.\n"
                    "Rules: keep ticker symbols UPPERCASE, preserve action verbs, "
                    "each element must make sense alone.\n\n"
                    f'Message: "{msg}"\n\n'
                    'Example output: ["portfolio", "social report SOFI", "should I buy more SOFI"]'
                )
            }],
            options={"temperature": 0, "num_predict": 250}
        )
        text = r["message"]["content"].strip()
        m = re.search(r'\[[\s\S]*?\]', text)
        if m:
            parts = json.loads(m.group())
            if isinstance(parts, list) and len(parts) >= 1:
                return [str(p).strip() for p in parts if str(p).strip()]
    except Exception:
        pass
    return []


# ── Conversational enrichment detection ────────────────────────────────────────
_CONVERSATIONAL = re.compile(
    r'\b(tell me|what do you think|should i|explain|why is|how is|how do|'
    r'what about|also|additionally|thoughts|opinion|analysis|'
    r'recommend|suggest|is it|do you|can you|would you|think about|'
    r'talk about|what is|elaborate|what else|give me|help me|'
    r'make sense|understand|context|outlook|feel about)\b|\?',
    re.IGNORECASE
)

def _needs_enrichment(msg: str) -> bool:
    """True when the message has conversational content beyond a pure keyword."""
    return len(msg.split()) > 7 or bool(_CONVERSATIONAL.search(msg))


# ── Process ────────────────────────────────────────────────────────────────────
def _persist_turn(user_msg: str, reply: str) -> None:
    """
    Persist one exchange to durable conversation memory (survives restarts,
    feeds the rolling summary), and check whether this message is correcting
    the previous reply so Jarvis can learn from the critique automatically.
    """
    try:
        MEM.detect_and_log_critique(user_msg)
    except Exception:
        pass
    try:
        MEM.log_turn("user", user_msg)
        MEM.log_turn("assistant", reply)
        MEM.consolidate_conversation()
    except Exception:
        pass
    # Learn from ANY prompt: mine durable personal facts in the background so
    # replies are never slowed down. (Explicit "jarvis remember" still exists
    # for things the user wants saved verbatim.)
    try:
        threading.Thread(target=MEM.learn_from_message,
                         args=(user_msg,), daemon=True).start()
    except Exception:
        pass

# Casual chat detection — these must get a HUMAN reply, never a tool call or a
# report. Deliberately narrow: anything ambiguous still goes through normal
# routing. ("good morning" is excluded — it triggers the morning briefing.)
_SMALLTALK_RE = re.compile(
    r"^(?:hey|hi+|hello|yo|sup|what'?s\s+up|howdy|"
    r"how(?:'?s|\s+is|\s+are)?\s+(?:it\s+going|you(?:\s+doing)?|things|life|your\s+day)|"
    r"thanks?(?:\s+you)?(?:\s+man|\s+jarvis|\s+buddy)?|ty|appreciate\s+(?:it|you)|"
    r"good\s*night|bye|later|see\s+ya|peace(?:\s+out)?|"
    r"lo+l|lmao+|ha(?:ha)+|nice+|coo+l|awesome|sweet|dope|"
    r"good\s+(?:job|work|stuff|bot)|well\s+done|love\s+(?:it|that)|"
    r"tell\s+me\s+a\s+joke|make\s+me\s+laugh|"
    r"who\s+are\s+you|what\s+are\s+you|how\s+do\s+you\s+feel|"
    r"are\s+you\s+(?:there|alive|real|sentient|awake)|you\s+up)"
    r"[\s!?.,]*$", re.I)

def _is_smalltalk(msg: str) -> bool:
    m = msg.strip()
    # "hey jarvis, how's it going" — drop the address so the greeting matches
    m2 = re.sub(r'^(?:hey|hi+|hello|yo)?[,!\s]*jarvis[,!\s]*', '', m, flags=re.I).strip()
    if m2 != m and not m2:
        return True   # the whole message was just "hey jarvis" / "jarvis!"
    return bool(_SMALLTALK_RE.match(m2 or m))

def process(user_msg):
    global history

    # -2. Ticker normalization FIRST, before anything else touches the
    #     message: "$net" -> "NET" etc. Every downstream step (memory,
    #     critique detection, regex routing, the LLM) sees the plain ticker.
    user_msg, _dollar_tickers = _normalize_tickers(user_msg)

    # -1. A staged remember/forget awaiting confirmation intercepts yes/no
    #     before any other routing.
    _mem_reply = _resolve_pending_memory(user_msg)
    if _mem_reply is not None:
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": _mem_reply})
        _persist_turn(user_msg, _mem_reply)
        return _mem_reply

    # 0. Corrections/critiques get a dedicated conversational path FIRST — a
    #    message like "that's not what I asked for" must never get routed into
    #    an unrelated tool call just because the prompt is trading-tool-heavy.
    try:
        _critique = MEM.is_critique(user_msg)
    except Exception:
        _critique = False

    if _critique:
        history.append({"role": "user", "content": user_msg})
        try:
            import ollama
            correction_note = (
                "\n\nThe user's last message is correcting or pushing back on your "
                "previous response — it is NOT a request for a new lookup or tool. "
                "Engage with the correction directly: acknowledge what you got wrong, "
                "ask what they actually meant if it's unclear, or adjust course. "
                "Respond in plain text only — do not output a tool-call JSON."
            )
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "system", "content": system_prompt() + correction_note}]
                         + history[-10:]
            )
            reply = response["message"]["content"].strip()
        except Exception:
            reply = "You're right — that wasn't it. What did you actually want me to do?"
        history.append({"role": "assistant", "content": reply})
        _persist_turn(user_msg, reply)
        return reply

    # 1. Normalize casual speech before anything else
    clean_msg = _normalize(user_msg)

    # 1b. Is this short reply answering/continuing the previous exchange? If
    #     so, keyword/semantic matching must not touch it ("2" would become
    #     math, "yes" was semantically hijacked into watchlist_add) — it goes
    #     straight to the LLM with a CONTINUATION hint (added in _enrich).
    #     No "?" requirement: offers don't always end with a question mark.
    _cont = (bool(_AFFIRM_RE.match(user_msg.strip()))
             and bool(_last_assistant(history).strip()))

    # 2. Direct keyword match (fast path)
    actions = [] if _cont else (match_all(clean_msg) or match_all(user_msg))

    # 2a. $-prefixed tickers are ALWAYS real tickers (Wall Street notation).
    #     If nothing else claimed one, guarantee a grounded lookup instead of
    #     letting the LLM guess/hallucinate a different company (real bug:
    #     "$net" alone got answered as if it were NVIDIA). A leading buy/sell
    #     verb still means buy/sell even without a parsed qty ("buy $pltr")
    #     — routing that to a mere quote would be wrong, not just incomplete;
    #     trading_buy/trading_sell already prompt for qty when it's missing.
    if _dollar_tickers and not actions:
        sym = _dollar_tickers[0]
        if re.search(r'\bbuy\b', user_msg, re.IGNORECASE):
            actions = [("trading_buy", {"symbol": sym})]
        elif re.search(r'\bsell\b', user_msg, re.IGNORECASE):
            actions = [("trading_sell", {"symbol": sym})]
        else:
            actions = [("stock_quote", {"symbol": sym})]

    # A short command fully answered by ONE direct tool needs no LLM at all —
    # "give me my morning briefing" was getting its perfect plain-text reply
    # rewritten (and mangled into JSON) by the enrichment pass, purely because
    # "give me" looks conversational. Skip both LLM passes in that case.
    _fully_consumed = len(actions) == 1 and len(user_msg.split()) <= 6

    # 2b. For complex messages, use Ollama to decompose into discrete intents
    #     and re-run direct matching on each — catches multi-part requests
    if _needs_enrichment(user_msg) and not _fully_consumed:
        intents = _llm_intent_parse(user_msg)
        if intents:
            seen_keys = {f"{t}:{sorted(p.items())}" for t, p in actions}
            for intent in intents:
                for a_t, a_p in (match_all(_normalize(intent)) or match_all(intent)):
                    k = f"{a_t}:{sorted(a_p.items())}"
                    if k not in seen_keys:
                        seen_keys.add(k)
                        actions = list(actions) + [(a_t, a_p)]

    if actions:
        results = []
        for tname, params in actions:
            log.info(f"Direct: {tname} {params}")
            result = run_tool(tname, params)
            log.info(f"→ {str(result)[:80]}")
            results.append(result)
        tool_reply = "\n".join(results)

        # If message has conversational elements, let Ollama synthesize everything
        # and also trigger any additional tools it spots that direct matching missed
        if _needs_enrichment(user_msg) and not _fully_consumed:
            try:
                import ollama as _olm
                enrich_prompt = (
                    f"The user said: \"{user_msg}\"\n\n"
                    f"Tool data already retrieved:\n{tool_reply}\n\n"
                    "Respond to the COMPLETE request:\n"
                    "- If any part of the request still needs a tool not shown above, "
                    "output its JSON call on its own line first.\n"
                    "- Then give a concise, natural reply covering everything the user asked."
                )
                r = _olm.chat(
                    model=OLLAMA_MODEL,
                    messages=[{"role": "system", "content": system_prompt()}]
                             + history[-10:]
                             + [{"role": "user", "content": enrich_prompt}]
                )
                enrich_text = r["message"]["content"].strip()

                # Execute any extra tool calls Ollama identified
                extra_calls = _extract_tool_calls(enrich_text)
                if extra_calls:
                    extra_results = [
                        run_tool(tc.get("tool", ""), tc.get("params", {}))
                        for tc in extra_calls
                    ]
                    all_data = tool_reply + "\n\n" + "\n".join(extra_results)
                    synth = _olm.chat(
                        model=OLLAMA_MODEL,
                        messages=[{"role": "system", "content": system_prompt()}]
                                 + history[-10:]
                                 + [{"role": "user", "content":
                                     f'User: "{user_msg}"\n\nAll data:\n{all_data}\n\n'
                                     "Give a concise, complete response."}]
                    )
                    # Fallback = the real tool data: if the LLM mangles the
                    # synthesis into JSON, the user still gets the answer.
                    reply = _sanitize_reply(synth["message"]["content"], all_data)
                else:
                    reply = _sanitize_reply(enrich_text, tool_reply)
            except Exception:
                reply = tool_reply
        else:
            reply = tool_reply

        history.append({"role":"user","content":user_msg})
        history.append({"role":"assistant","content":reply})
        try: T.memory_update(user_msg, reply)
        except Exception: pass
        try:
            tool_names = ",".join(t for t, _ in actions)
            MEM.log_interaction(user_msg, tool_names)
        except Exception:
            pass
        _persist_turn(user_msg, reply)
        return reply

    # 2b2. Casual conversation fast path — greetings/banter must get a HUMAN
    # reply, never a forced tool pick or a report. Runs only when no direct
    # action matched, so "good morning" (→ briefing) etc. keep working.
    if _is_smalltalk(clean_msg):
        history.append({"role": "user", "content": user_msg})
        try:
            import ollama
            # Deliberately NOT system_prompt(): the 200-line tool manifest drowns
            # any "be casual" instruction and the model reverts to call-center
            # phrasing. A compact persona + memory context chats far better.
            mem_ctx = ""
            try:
                mem_ctx = MEM.context_for_llm() + "\n" + MEM.conversation_context_for_llm()
            except Exception:
                pass
            casual_sys = (
                f"You are JARVIS, {_USER_NAME or 'your user'}'s personal AI — sharp, "
                "loyal, a little witty, fully on their side. Right now you're just "
                "chatting like a close friend, not doing tasks.\n"
                "Rules:\n"
                "- 1-3 casual sentences, matching their tone and energy\n"
                "- NEVER say 'How can I assist you' or anything customer-service shaped\n"
                "- No JSON, no lists, no reports, no market data\n"
                "- Weave in what you know about them naturally when it fits\n\n"
                + mem_ctx
            )
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "system", "content": casual_sys}] + history[-10:]
            )
            # Even here, never leak JSON if the model misfires
            reply = _sanitize_reply(
                response["message"]["content"],
                f"All good here{', ' + _USER_NAME if _USER_NAME else ''}. What's on your mind?")
        except Exception:
            reply = "Hey — I'm here. What's up?"
        history.append({"role": "assistant", "content": reply})
        try:
            MEM.log_interaction(user_msg, "casual")
        except Exception:
            pass
        _persist_turn(user_msg, reply)
        return reply

    # 2c. Semantic intent match — understands the user's vernacular where the
    # regex table (exact phrasings) missed. High confidence → dispatch directly;
    # medium → tell the LLM which 3 tools this most resembles instead of
    # making it guess from ~150.
    sem_hint = ""
    if HAS_INTENT and not _cont:
        try:
            _refresh_intent_corpus()
            sem = INTENT.match_intent(clean_msg)
            if sem.get("dispatch"):
                tname, params = sem["dispatch"]
                log.info(f"Semantic dispatch ({sem['method']}): {tname} {params}")
                result = run_tool(tname, params)
                history.append({"role": "user", "content": user_msg})
                history.append({"role": "assistant", "content": result})
                try: T.memory_update(user_msg, result)
                except Exception: pass
                try: MEM.log_interaction(user_msg, tname)   # feeds learned phrasings
                except Exception: pass
                _persist_turn(user_msg, result)
                return result
            if sem.get("candidates"):
                sem_hint = INTENT.hint_text(sem["candidates"])
                log.info(f"Semantic hint: {sem['candidates']}")
        except Exception as _seme:
            log.warning(f"Semantic match error: {_seme}")

    # 3. Ollama — send enriched message so LLM has full context
    enriched = _enrich(clean_msg, history)
    history.append({"role":"user","content":user_msg})
    try:
        import ollama
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role":"system","content":system_prompt() + sem_hint}] + history[-20:] +
                      ([{"role":"user","content":enriched}] if enriched != user_msg else []))
        reply = response["message"]["content"].strip()
    except Exception as e:
        log.warning(f"Ollama: {e}")
        reply = "Ollama isn't running. Open a Command Prompt and type: ollama serve"
        history.append({"role":"assistant","content":reply})
        return reply

    log.info(f"Ollama raw: {reply[:120]}")

    # 4. Extract any tool calls from the response
    tool_calls = _extract_tool_calls(reply)

    # 5. If LLM hedged ("I can't access real-time data" etc.) — force a second pass
    #    with an explicit "pick a tool" instruction
    if not tool_calls and _is_hedge(reply):
        log.info("LLM hedged — forcing tool-selection retry")
        try:
            retry_prompt = (
                f"The user said: \"{user_msg}\"\n\n"
                "You just gave a non-answer. You have tools for this. "
                "Look at the tool list in your instructions and output the correct JSON tool call right now. "
                "Do NOT explain. Output ONLY the JSON."
            )
            retry = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role":"system","content":system_prompt() + sem_hint},
                           {"role":"user","content":retry_prompt}])
            retry_text = retry["message"]["content"].strip()
            tool_calls = _extract_tool_calls(retry_text)
            if tool_calls:
                reply = retry_text
                log.info(f"Retry found tools: {[tc.get('tool') for tc in tool_calls]}")
        except Exception as re_err:
            log.warning(f"Retry failed: {re_err}")

    # 5b. Last line of defense: the LLM emitted JSON-ish tool-call text that
    # still couldn't be parsed (malformed syntax, or a schema so drifted it
    # named no real tool — real capture: {"status":"daily_brief","briefing":
    # true} shown RAW). NEVER show raw JSON to the user — strip it, and if
    # nothing readable remains, say so plainly.
    if not tool_calls:
        reply = _sanitize_reply(reply)
        # Multi-line tool-call-ish JSON embedded in prose that survived the
        # line-based pass — strip the braced span rather than show it.
        if re.search(r'\{\s*"(?:tool|action|name|function|command|status|intent|task|type)"', reply):
            log.warning(f"Unparseable tool-call JSON suppressed: {reply[:100]}")
            first = reply.find("{"); last = reply.rfind("}")
            stripped = (reply[:first] + reply[last + 1:]).strip() if last > first else reply[:first].strip()
            reply = stripped or (
                "I tried to run a tool for that but garbled the call. "
                "Say it once more — or use one of the Commands-tab phrases and I'll run it directly."
            )

    # 6. Execute tool calls if found
    if tool_calls:
        # On continuation turns the model often force-picks tools it shouldn't
        # (case (b) failures) — a call with NO parameters after "yes" is never
        # right, so drop those before execution.
        if _cont:
            with_params = [tc for tc in tool_calls if tc.get("params")]
            tool_calls = with_params or tool_calls[:0]
        results = []
        for tc in tool_calls:
            r = run_tool(tc.get("tool",""), tc.get("params",{}))
            log.info(f"Tool {tc.get('tool')}: {str(r)[:80]}")
            results.append(r)
        reply = "\n".join(results) if results else reply

        # 6b. Continuation recovery: the user said "yes" to a strategic question
        # and the model force-picked tools anyway. If nothing executed, or any
        # executed call failed for missing details, or everything came back as
        # errors/no-data junk — answer the actual question in prose instead.
        if _cont and (
                not results
                or any("didn't have the details" in str(r) for r in results)
                or all(str(r).startswith(("Error", "No ", "Unknown tool")) for r in results)):
            log.info("Continuation produced a parameterless tool call — recovering in prose")
            try:
                recover = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=[{"role": "system", "content": system_prompt() +
                               "\n\nThe user just said yes to the approach you proposed "
                               "in your previous message. Do NOT output any tool-call "
                               "JSON. Carry out or concretely lay out that approach in "
                               "plain text now — specifics, not another question."}]
                             + history[-10:])
                reply = _sanitize_reply(recover["message"]["content"],
                                        "On it — give me one concrete detail to start with.")
            except Exception:
                pass

    # Deliver any due reminders with this reply (the UI poller is the primary
    # path; this catches them when the user is mid-conversation anyway).
    try:
        _due = AST.reminders_due()
        if _due:
            reply = "\n".join(_due) + "\n\n" + reply
    except Exception:
        pass

    history.append({"role":"assistant","content":reply})
    try: T.memory_update(user_msg, reply)
    except Exception: pass
    # Log to self-learning memory (all paths)
    try:
        tool_names = ",".join(tc.get("tool","") for tc in tool_calls) if tool_calls else "llm"
        MEM.log_interaction(user_msg, tool_names)
    except Exception:
        pass
    _persist_turn(user_msg, reply)
    return reply

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/auth", methods=["POST"])
def auth_endpoint():
    """Exchange the master API key for a 180-day session token.
    The phone calls this once after the user saves settings; subsequent
    requests carry the session token instead of the raw API key."""
    data = request.get_json(silent=True) or {}
    provided = (
        data.get("api_key") or
        request.headers.get("X-API-Key", "") or
        (request.headers.get("Authorization", "")[7:]
         if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    )
    remote = request.remote_addr or ""
    is_local = remote in ("127.0.0.1", "::1", "localhost")
    if not _API_KEY or is_local or provided == _API_KEY:
        token, expires = _session_create()
        return jsonify({"session_token": token, "expires": expires, "days": _SESSION_DAYS})
    return jsonify({"error": "Invalid API key"}), 401


@app.route("/chat", methods=["POST"])
def chat():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized — check API key in settings"}), 401
    data = request.get_json(silent=True) or {}
    msg  = data.get("message","").strip()
    if not msg: return jsonify({"error":"No message"}), 400
    reply = process(msg)
    # Find any file paths in the reply and build download links
    files = _extract_file_refs(reply)
    return jsonify({
        "reply": reply,
        "time":  datetime.now().strftime("%I:%M %p"),
        "files": files,
    })

@app.route("/health", methods=["GET"])
def health():
    # Direct HTTP check against Ollama itself — the old `import ollama;
    # ollama.list()` reported "offline" whenever the pip package was missing,
    # even with Ollama serving fine.
    ollama_running, model_present = False, False
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://localhost:11434/api/tags", timeout=3) as _r:
            _tags = json.loads(_r.read().decode("utf-8", "replace"))
        ollama_running = True
        _base = OLLAMA_MODEL.split(":")[0]
        model_present = any(
            OLLAMA_MODEL == (m.get("name") or "") or (m.get("name") or "").startswith(_base)
            for m in _tags.get("models", []))
    except Exception:
        pass
    ai = ("online" if ollama_running and model_present else
          f"online — model {OLLAMA_MODEL} not pulled" if ollama_running else
          "offline — run: ollama serve")
    tunnel = _tunnel_url()
    return jsonify({
        "status":  "JARVIS online",
        "ai":      ai,
        "ollama":  {"running": ollama_running, "model": OLLAMA_MODEL,
                    "model_present": model_present},
        "tools":   len(TOOLS),
        "version": "4.4",
        "time":    datetime.now().isoformat(),
        "tunnel":  tunnel or None,
        "auth":    bool(_API_KEY),
    })

@app.route("/commands", methods=["GET"])
def list_commands():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        learned = MEM.learned_command_examples()
    except Exception:
        learned = {}
    categories = []
    for cat in COMMAND_REFERENCE:
        items = []
        for it in cat["items"]:
            enriched = dict(it)
            hit = learned.get(it.get("tool", ""))
            if hit:
                enriched["learned_example"] = hit["phrase"]
                enriched["learned_count"] = hit["count"]
            out_hint = TOOL_OUTPUTS.get(it.get("tool", ""))
            if out_hint:
                enriched["output"] = out_hint
            items.append(enriched)
        categories.append({"category": cat["category"], "items": items})
    return jsonify({"categories": categories})

@app.route("/tools", methods=["GET"])
def tools_catalog():
    """Every registered tool + what it does — powers the UI's Tools tab.
    Iterates the LIVE TOOLS registry, so nothing available is ever hidden:
    tools missing a doc line show up under 'Other (specialist)'."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    cats, documented = [], set()
    for cat_name, docs in TOOL_DOCS:
        rows = [{"tool": t, "desc": d} for t, d in docs.items() if t in TOOLS]
        documented |= set(docs)
        if rows:
            cats.append({"category": cat_name, "items": rows})
    other = sorted(set(TOOLS) - documented)
    if other:
        cats.append({"category": "Other (specialist / game internals)",
                     "items": [{"tool": t, "desc": ""} for t in other]})
    return jsonify({"total": len(TOOLS), "categories": cats})

@app.route("/reminders/due", methods=["GET"])
def reminders_due_route():
    """Polled by the UI every 30s — due reminders pop into the chat."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify({"due": AST.reminders_due()})
    except Exception as e:
        return jsonify({"due": [], "error": str(e)})

@app.route("/voice/transcribe", methods=["POST"])
def voice_transcribe():
    """Speech-to-text. Accepts a multipart audio file (field name 'audio') —
    whatever MediaRecorder produced client-side (webm/opus, mp4/aac, wav)."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    f = request.files.get("audio")
    if not f:
        return jsonify({"error": "No audio file (expected multipart field 'audio')"}), 400
    try:
        text = VOICE.transcribe(f.read(), f.filename or "audio.webm")
        return jsonify({"text": text})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Transcription error: {e}"}), 500


@app.route("/voice/speak", methods=["POST"])
def voice_speak():
    """Text-to-speech. Body: {"text": "...", "preset": "id" (optional)}.
    Returns audio/wav bytes directly (the UI plays it via an <audio> tag)."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text"}), 400
    try:
        wav_bytes = VOICE.speak(text, data.get("preset"))
        return Response(wav_bytes, mimetype="audio/wav")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Speech synthesis error: {e}"}), 500


@app.route("/voice/presets", methods=["GET", "POST"])
def voice_presets_route():
    """GET = list presets + installed system voices + which is default.
    POST {"action":"save","preset":{...}} | {"action":"delete","id":"..."}
    | {"action":"set_default","id":"..."}."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET":
        return jsonify(VOICE.list_presets())
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "save")
    try:
        if action == "delete":
            return jsonify(VOICE.delete_preset(data.get("id", "")))
        if action == "set_default":
            return jsonify(VOICE.set_default_preset(data.get("id", "")))
        return jsonify(VOICE.save_preset(data.get("preset", data)))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/risk-params", methods=["GET", "POST"])
def risk_params_route():
    """Markets-dashboard risk controls. GET = all params; POST = update
    (validated — out-of-range values are rejected with a 400)."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET":
        try:
            return jsonify(RPRM.get_params())
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    data = request.get_json(silent=True) or {}
    if data.pop("_reset", False):
        return jsonify(RPRM.reset_params())
    try:
        return jsonify(RPRM.set_params(data))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/market-outlook", methods=["GET", "POST"])
def market_outlook_route():
    """Markets-tab outlook header. GET = current score/mode/components.
    POST {"mode": "aggressive"} forces a mode for today, {"ignore": true}
    ignores the gate today, {"resume": true} clears any override/ignore."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    import tools.market_outlook as MO
    if request.method == "GET":
        try:
            return jsonify(MO.outlook_snapshot_json())
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    data = request.get_json(silent=True) or {}
    try:
        if data.get("resume"):
            MO.resume_auto()
            MO.resume_outlook()
        elif data.get("ignore") is True:
            MO.ignore_today()
        elif data.get("ignore") is False:
            MO.resume_outlook()
        elif data.get("mode"):
            msg = MO.force_mode(data["mode"])
            if msg.startswith("Unknown"):
                return jsonify({"error": msg}), 400
        return jsonify(MO.outlook_snapshot_json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/goal", methods=["GET", "POST"])
def goal_route():
    """Markets-tab goal tracker. GET = snapshot (empty {} when none);
    POST {"text": "..."} sets a goal, {"action": "hold"|"release"|"clear"}
    controls it."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    import tools.goal_engine as GOAL
    if request.method == "GET":
        try:
            return jsonify(GOAL.goal_snapshot() or {})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    try:
        if action == "hold":
            return jsonify({"message": GOAL.goal_hold(), "goal": GOAL.goal_snapshot()})
        if action == "release":
            return jsonify({"message": GOAL.goal_release(), "goal": GOAL.goal_snapshot()})
        if action == "clear":
            return jsonify({"message": GOAL.goal_clear(), "goal": {}})
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "need text (a goal) or action (hold/release/clear)"}), 400
        return jsonify({"message": GOAL.goal_set(text), "goal": GOAL.goal_snapshot()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/geo-risk", methods=["GET"])
def geo_risk_route():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    import tools.political_intel as PI
    s = PI.geo_risk_score()
    return jsonify({"score": s, "band": PI.geo_band(s),
                    "size_factor": PI.geo_size_factor(),
                    "conviction_multiplier": PI.geo_conviction_multiplier()})

@app.route("/opportunity-queue", methods=["GET", "POST"])
def opportunity_queue_route():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    import tools.opportunity_scan as OPP
    if request.method == "GET":
        return jsonify({"queue": OPP.queue_get(), "status": OPP._state["running"]})
    data = request.get_json(silent=True) or {}
    action, symbol = data.get("action", ""), data.get("symbol", "")
    if action not in ("promote", "demote", "remove") or not symbol:
        return jsonify({"error": "need action (promote/demote/remove) + symbol"}), 400
    msg = OPP.queue_action(action, symbol)
    return jsonify({"message": msg, "queue": OPP.queue_get()})

@app.route("/portfolio/positions", methods=["GET"])
def portfolio_positions():
    """Open positions with live prices + intraday sparkline data (yfinance)."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        positions = TRD._api("GET", "/v2/positions")
    except Exception as e:
        return jsonify({"error": str(e), "positions": []}), 200
    out = []
    for p in positions:
        row = {
            "symbol":     p.get("symbol", ""),
            "qty":        float(p.get("qty", 0)),
            "avg_cost":   float(p.get("avg_entry_price", 0)),
            "price":      float(p.get("current_price", 0) or 0),
            "today_pct":  round(float(p.get("change_today", 0) or 0) * 100, 2),
            "pl":         round(float(p.get("unrealized_pl", 0) or 0), 2),
            "pl_pct":     round(float(p.get("unrealized_plpc", 0) or 0) * 100, 2),
            "spark":      [],
        }
        try:
            import yfinance as yf
            hist = yf.Ticker(row["symbol"]).history(period="1d", interval="5m")
            if not hist.empty:
                closes = [round(float(c), 4) for c in hist["Close"].tolist()]
                row["spark"] = closes[-78:]
                if not row["price"] and closes:
                    row["price"] = closes[-1]
        except Exception:
            pass
        out.append(row)
    acct = {}
    try:
        a = TRD._api("GET", "/v2/account")
        eq, last = float(a.get("equity", 0)), float(a.get("last_equity", 0))
        acct = {"equity": eq, "day_pl": round(eq - last, 2),
                "day_pl_pct": round((eq - last) / last * 100, 2) if last else 0,
                "cash": float(a.get("cash", 0)),
                "buying_power": float(a.get("buying_power", 0))}
    except Exception:
        pass
    return jsonify({"positions": out, "count": len(out), "account": acct})

@app.route("/portfolio/live", methods=["GET"])
def portfolio_live():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = MON.portfolio_live_data()
        if not isinstance(data, dict):
            return jsonify({"error": str(data)}), 503
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/files", methods=["GET"])
def list_files():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        results = []
        for p in sorted(_FILES_DIR.rglob("*"), key=lambda f: f.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix.lower() in _ALLOWED_EXT:
                try:
                    rel   = str(p.relative_to(_FILES_DIR))
                    stat  = p.stat()
                    results.append({
                        "name":     p.name,
                        "path":     rel.replace("\\", "/"),
                        "size":     stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "ext":      p.suffix.lower(),
                    })
                    if len(results) >= 50:
                        break
                except Exception:
                    pass
        return jsonify({"files": results, "base": str(_FILES_DIR)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download", methods=["GET"])
def download_file():
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    rel = request.args.get("path", "").replace("..", "").lstrip("/\\")
    if not rel:
        return jsonify({"error": "No path specified"}), 400
    target = _FILES_DIR / rel
    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404
    if target.suffix.lower() not in _ALLOWED_EXT:
        return jsonify({"error": "File type not allowed"}), 403
    return send_file(str(target), as_attachment=True,
                     download_name=target.name)

@app.route("/tunnel", methods=["GET"])
def tunnel_info():
    url = _tunnel_url()
    key = _API_KEY
    return jsonify({"url": url, "has_key": bool(key), "configured": bool(url)})

def _extract_file_refs(text: str) -> list:
    """Find file paths in JARVIS replies and return download metadata."""
    import re
    files = []
    # Match Windows paths and ~/Documents/JARVIS paths
    patterns = [
        r'([A-Za-z]:\\[^\s"\'<>]+\.(?:pdf|xlsx|csv|txt|docx|png|jpg|html))',
        r'((?:~/|/)[^\s"\'<>]+\.(?:pdf|xlsx|csv|txt|docx|png|jpg|html))',
        r'Documents[/\\]JARVIS[/\\][^\s"\'<>]+\.(?:pdf|xlsx|csv|txt|docx|png|jpg|html)',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            full = m.group(0)
            if full in seen:
                continue
            seen.add(full)
            p = Path(full.replace("~", str(Path.home())))
            if p.exists():
                try:
                    rel = str(p.relative_to(_FILES_DIR)).replace("\\", "/")
                    files.append({"name": p.name, "path": rel, "size": p.stat().st_size})
                except Exception:
                    pass
    return files

@app.route("/clear", methods=["POST"])
def clear():
    global history; history = []
    return jsonify({"status":"cleared"})

@app.route("/app")
@app.route("/app/")
def serve_app():
    f = ROOT / "app" / "index.html"
    return send_file(str(f)) if f.exists() else ("App not found", 404)

@app.route("/")
def root():
    # Serve the PWA if it exists; otherwise return API info
    f = ROOT / "app" / "index.html"
    if f.exists():
        return send_file(str(f))
    return jsonify({"status":"JARVIS v4.3 running","app":"/app"})

@app.route("/manifest.json")
def serve_manifest():
    f = ROOT / "app" / "manifest.json"
    return send_file(str(f), mimetype="application/manifest+json") if f.exists() else ("", 404)

@app.route("/sw.js")
def serve_sw():
    f = ROOT / "app" / "sw.js"
    r = send_file(str(f), mimetype="application/javascript") if f.exists() else ("", 404)
    if hasattr(r, 'headers'):
        r.headers['Service-Worker-Allowed'] = '/'
    return r

@app.route("/icon-<size>.png")
def serve_icon(size):
    # Serve a placeholder icon (cyan square) if no real icon exists
    f = ROOT / "app" / f"icon-{size}.png"
    if f.exists():
        return send_file(str(f), mimetype="image/png")
    # Generate minimal 1x1 PNG placeholder
    import base64
    # 1x1 cyan PNG
    _1px = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    from flask import Response
    return Response(_1px, mimetype="image/png")

if __name__ == "__main__":
    log.info("=" * 48)
    log.info("  JARVIS v4.3 — Personal AI Butler")
    log.info("=" * 48)
    log.info(f"  Tools: {len(TOOLS)}")
    log.info(f"  Data:  {T._MEM_FILE.parent}")
    log.info(f"  App:   http://YOUR-IP:5005/app")
    log.info("=" * 48)

    # ── Auto-load YOLO if model already downloaded ────────────
    # Only loads if model file exists — never downloads automatically
    # Say "setup yolo" once to download, then it auto-loads every startup
    try:
        from pathlib import Path as _Path
        _model_dir = _Path.home() / "Documents" / "JARVIS" / "models"
        _model_files = list(_model_dir.glob("*.pt")) if _model_dir.exists() else []
        if _model_files:
            log.info(f"  YOLO: Found {_model_files[0].name} — loading in background...")
            import threading as _threading
            def _load_yolo():
                try:
                    import cs2_yolo as _Y
                    det = _Y.get_detector()
                    # Find the best available model
                    for mf in sorted(_model_files, key=lambda f: f.stat().st_size, reverse=True):
                        model_name = mf.stem  # filename without .pt
                        ok = det.load(model_name)
                        if ok:
                            log.info(f"  YOLO: {model_name} ready on {det.device}")
                            break
                except Exception as e:
                    log.warning(f"  YOLO auto-load failed: {e}")
            _threading.Thread(target=_load_yolo, daemon=True).start()
        else:
            log.info("  YOLO: Not downloaded yet. Say 'setup yolo' to install.")
    except Exception as _ye:
        log.warning(f"  YOLO check failed: {_ye}")

    # ── Rehydrate conversation history from persistent memory ────
    # So closing the app (or restarting the PC/server) doesn't lose context —
    # Jarvis picks back up instead of starting a blank conversation.
    try:
        rehydrated = MEM.get_recent_turns(40)
        if rehydrated:
            history = rehydrated
            log.info(f"  Memory: rehydrated {len(rehydrated)} conversation turns")
        else:
            log.info("  Memory: no prior conversation history found")
    except Exception as _rhe:
        log.warning(f"  Memory: rehydration failed: {_rhe}")

    # ── Auto-start trade monitor ─────────────────────────────────
    if HAS_MON and os.getenv("ALPACA_API_KEY"):
        try:
            msg = MON.start_monitor()
            log.info(f"  Monitor: {msg}")
        except Exception as _me:
            log.warning(f"  Monitor failed to start: {_me}")
    else:
        log.info("  Monitor: Alpaca not configured — skipping")

    # ── Auto-start live trade tape (real-time NYSE/NASDAQ stream) ────
    if HAS_TAPE and os.getenv("ALPACA_API_KEY"):
        try:
            msg = TAPE.start_trade_stream()
            log.info(f"  Trade stream: {msg}")
        except Exception as _te:
            log.warning(f"  Trade stream failed to start: {_te}")
    else:
        log.info("  Trade stream: Alpaca not configured — skipping")

    # ── Warm up the speech-to-text model in the background ──────────
    # Loads it (and resolves GPU-vs-CPU) now instead of on someone's first
    # real voice command — avoids that first request timing out while it
    # downloads/loads/fails-over cold.
    if HAS_VOICE:
        threading.Thread(target=VOICE.warm_up, daemon=True, name="jarvis-voice-warmup").start()
        log.info("  Voice: warming up speech-to-text in background...")

    # ── Auto-start daily intelligence cycle (brief + evening review) ─
    if HAS_DBRF:
        try:
            msg = DBRF.start_daily_scheduler()
            log.info(f"  Daily brief: {msg}")
        except Exception as _de:
            log.warning(f"  Daily brief scheduler failed to start: {_de}")

    # ── Auto-start Alpaca account sync (live capital ground truth) ───
    if os.getenv("ALPACA_API_KEY"):
        try:
            import tools.account_sync as SYNC
            log.info("  Account sync: " + SYNC.start_account_sync())
        except Exception as _ase:
            log.warning(f"  Account sync failed to start: {_ase}")

    # ── Auto-start goal engine (pace tracking + capped escalation) ───
    if os.getenv("ALPACA_API_KEY"):
        try:
            import tools.goal_engine as GOAL
            log.info("  Goal engine: " + GOAL.start_goal_engine())
        except Exception as _ge:
            log.warning(f"  Goal engine failed to start: {_ge}")

    # ── Auto-start opportunity scanners (broad 30min / narrow 5min) ──
    if os.getenv("ALPACA_API_KEY"):
        try:
            import tools.opportunity_scan as OPP
            log.info("  Scanners: " + OPP.start_scanners())
        except Exception as _ope:
            log.warning(f"  Opportunity scanners failed to start: {_ope}")

    # ── Auto-start political intelligence scanner (15min market hours) ─
    try:
        import tools.political_intel as PI
        log.info("  Political: " + PI.start_political_scanner())
    except Exception as _pie:
        log.warning(f"  Political scanner failed to start: {_pie}")

    # ── Build semantic intent corpus (vernacular understanding) ──────
    if HAS_INTENT:
        try:
            _refresh_intent_corpus(force=True)
            log.info("  Intent: " + INTENT.intent_status().split("\n")[1].strip())
        except Exception as _ie:
            log.warning(f"  Intent corpus build failed: {_ie}")

    app.run(host="0.0.0.0", port=5005, debug=False, use_reloader=False)
