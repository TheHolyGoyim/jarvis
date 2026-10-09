"""
game_ai.py — JARVIS General Game AI
Profile-based autonomous game player. Delegates to specialized modules for
CS2 and Fall Guys; provides generic keyboard/mouse/controller primitives for
every other game.
"""

import os
import sys
import time
import threading
import subprocess
import datetime
import pathlib

# ── Optional imports (graceful fallback when deps missing) ────────────────────

try:
    import cs2_pro as _cs2_mod
    _cs2_donk = _cs2_mod._donk          # DonkAI instance
    _ri       = _cs2_donk.ri            # RawInput
    _vision   = _cs2_donk.vision        # ProVision
    _spray    = _cs2_donk.spray         # SprayController
    _CS2_OK   = True
except Exception as _e:
    _CS2_OK   = False
    _cs2_donk = None
    _ri       = None
    _vision   = None
    _spray    = None

try:
    import controller as _ctrl_mod
    _xbox     = _ctrl_mod._xbox         # VirtualXbox instance
    _CTRL_OK  = True
except Exception:
    _CTRL_OK  = False
    _xbox     = None

try:
    import game_vision as _gv_mod
    _GV_OK    = True
except Exception:
    _GV_OK    = False
    _gv_mod   = None

try:
    import requests as _req
    _OLLAMA_OK = True
except Exception:
    _OLLAMA_OK = False

# ── Profile registry ──────────────────────────────────────────────────────────
# sens_mult: mouse sensitivity multiplier relative to CS2 baseline (1.0)
# A higher number means this game needs more mouse movement to cover the same angle.

PROFILES = {
    # ── Counter-Strike (CS2 pro backend) ─────────────────────────
    "cs2":                  {"type":"fps","module":"cs2_pro",   "control":"mouse+kb","display":"Counter-Strike 2",      "sens_mult":1.0},
    "counter-strike":       {"type":"fps","module":"cs2_pro",   "control":"mouse+kb","display":"Counter-Strike 2",      "sens_mult":1.0},
    "counter-strike 2":     {"type":"fps","module":"cs2_pro",   "control":"mouse+kb","display":"Counter-Strike 2",      "sens_mult":1.0},

    # ── Fall Guys (vision + controller backend) ───────────────────
    "fall guys":            {"type":"platformer","module":"game_vision","control":"controller","display":"Fall Guys",   "sens_mult":1.0},
    "fallguys":             {"type":"platformer","module":"game_vision","control":"controller","display":"Fall Guys",   "sens_mult":1.0},

    # ── Call of Duty — all titles ─────────────────────────────────
    "black ops":            {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Call of Duty: Black Ops", "sens_mult":1.1},
    "black ops 6":          {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Black Ops 6",          "sens_mult":1.1},
    "black ops 6 ranked":   {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Black Ops 6",          "sens_mult":1.1},
    "bo6":                  {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Black Ops 6",          "sens_mult":1.1},
    "black ops cold war":   {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Black Ops Cold War",   "sens_mult":1.1},
    "cold war":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Black Ops Cold War",   "sens_mult":1.1},
    "modern warfare":       {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Modern Warfare",       "sens_mult":1.1},
    "modern warfare 2":     {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Modern Warfare 2",     "sens_mult":1.1},
    "modern warfare 3":     {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Modern Warfare 3",     "sens_mult":1.1},
    "mw2":                  {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Modern Warfare 2",     "sens_mult":1.1},
    "mw3":                  {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Modern Warfare 3",     "sens_mult":1.1},
    "warzone":              {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Warzone",              "sens_mult":1.1},
    "warzone 2":            {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Warzone 2",            "sens_mult":1.1},
    "call of duty":         {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Call of Duty",         "sens_mult":1.1},
    "cod":                  {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Call of Duty",         "sens_mult":1.1},
    "vanguard":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"CoD: Vanguard",        "sens_mult":1.1},
    "ww2":                  {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"CoD: WWII",            "sens_mult":1.1},

    # ── Other popular FPS/shooter games ──────────────────────────
    "valorant":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Valorant",             "sens_mult":0.9},
    "apex":                 {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Apex Legends",         "sens_mult":1.2},
    "apex legends":         {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Apex Legends",         "sens_mult":1.2},
    "fortnite":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Fortnite",             "sens_mult":1.3},
    "overwatch":            {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Overwatch 2",          "sens_mult":1.0},
    "overwatch 2":          {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Overwatch 2",          "sens_mult":1.0},
    "battlefield":          {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Battlefield",          "sens_mult":1.1},
    "battlefield 2042":     {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Battlefield 2042",     "sens_mult":1.1},
    "rainbow six":          {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Rainbow Six Siege",    "sens_mult":0.9},
    "r6":                   {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Rainbow Six Siege",    "sens_mult":0.9},
    "siege":                {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Rainbow Six Siege",    "sens_mult":0.9},
    "halo":                 {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Halo Infinite",        "sens_mult":1.2},
    "halo infinite":        {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Halo Infinite",        "sens_mult":1.2},
    "rust":                 {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Rust",                 "sens_mult":1.0},
    "pubg":                 {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"PUBG",                 "sens_mult":1.1},
    "hunt showdown":        {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Hunt: Showdown",       "sens_mult":1.0},
    "escape from tarkov":   {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Escape from Tarkov",   "sens_mult":0.8},
    "tarkov":               {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Escape from Tarkov",   "sens_mult":0.8},
    "destiny 2":            {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Destiny 2",            "sens_mult":1.1},
    "the finals":           {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"The Finals",           "sens_mult":1.1},
    "xdefiant":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"XDefiant",             "sens_mult":1.1},
    "deadlock":             {"type":"fps","module":"generic_fps","control":"mouse+kb","display":"Deadlock",             "sens_mult":1.0},

    # ── Non-FPS ───────────────────────────────────────────────────
    "minecraft":            {"type":"action","module":None,       "control":"mouse+kb","display":"Minecraft",           "sens_mult":1.0},
    "rocket league":        {"type":"sport", "module":None,       "control":"controller","display":"Rocket League",     "sens_mult":1.0},
}

# Direction → key mappings for generic FPS/action games
_DIR_KEYS = {
    "forward":       "w",
    "back":          "s",
    "backward":      "s",
    "left":          "a",
    "right":         "d",
    "forward-left":  ("w", "a"),
    "forward-right": ("w", "d"),
    "back-left":     ("s", "a"),
    "back-right":    ("s", "d"),
}

# Look direction → mouse deltas (pixels)
_LOOK_DIRS = {
    "left":      (-1,  0),
    "right":     ( 1,  0),
    "up":        ( 0, -1),
    "down":      ( 0,  1),
    "up-left":   (-1, -1),
    "up-right":  ( 1, -1),
    "down-left": (-1,  1),
    "down-right":( 1,  1),
}

# ── State ─────────────────────────────────────────────────────────────────────

_current_profile: dict | None = None
_current_game: str             = ""
_auto_thread: threading.Thread | None = None
_auto_active: bool             = False
_auto_paused: bool             = False
_recording: list               = []         # list of screenshot paths
_recording_active: bool        = False
_record_dir: pathlib.Path      = pathlib.Path.home() / "Documents" / "JARVIS" / "recordings"

# ── Internal helpers ──────────────────────────────────────────────────────────

def _ollama(prompt: str, system: str = "") -> str:
    if not _OLLAMA_OK:
        return ""
    try:
        payload = {
            "model": "llama3",
            "prompt": prompt,
            "system": system or "You are a professional esports coach and game AI assistant. Be concise.",
            "stream": False,
        }
        r = _req.post("http://localhost:11434/api/generate", json=payload, timeout=15)
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return ""


def _get_foreground_title() -> str:
    """Return the title of the currently focused window."""
    try:
        r = subprocess.run(
            'powershell -c "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Sort-Object CPU -Descending | Select-Object -First 1).MainWindowTitle"',
            shell=True, capture_output=True, text=True, timeout=4
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _match_profile(name: str) -> tuple[str, dict]:
    """Find best matching profile for a game name. Returns (key, profile)."""
    name_l = name.lower().strip()
    if name_l in PROFILES:
        return name_l, PROFILES[name_l]
    # Partial match
    for k, v in PROFILES.items():
        if k in name_l or name_l in k:
            return k, v
    return "", {}


def _require_ri(fn_name: str):
    if not _CS2_OK or _ri is None:
        raise RuntimeError(f"{fn_name}: RawInput not available (cs2_pro import failed)")


def _require_xbox(fn_name: str):
    if not _CTRL_OK or _xbox is None:
        raise RuntimeError(f"{fn_name}: VirtualXbox not available (controller import failed)")


# ── Public API ────────────────────────────────────────────────────────────────

def game_load(game="cs2") -> str:
    """
    Load a game profile. Initializes the right AI backend.
    game: name of the game (e.g. 'cs2', 'fall guys', 'valorant')
    """
    global _current_profile, _current_game

    key, profile = _match_profile(game)
    if not profile:
        # Auto-detect from foreground window
        title = _get_foreground_title()
        if title:
            key, profile = _match_profile(title)

    if not profile:
        # Fall back to generic FPS
        key = "default"
        profile = {"type": "fps", "module": None, "control": "mouse+kb", "display": game}

    _current_profile = profile
    _current_game    = game

    module   = profile.get("module", "")
    control  = profile.get("control", "")
    display  = profile.get("display", game)

    status_lines = [f"Game loaded: {display}",
                    f"Type: {profile.get('type','generic')} | Control: {control}"]

    if module == "cs2_pro":
        status_lines.append(f"CS2 backend: {'ready' if _CS2_OK else 'ERROR — cs2_pro import failed'}")
    elif module == "game_vision":
        status_lines.append(f"Fall Guys vision backend: {'ready' if _GV_OK else 'ERROR — game_vision import failed'}")
        if _GV_OK and _CTRL_OK and _gv_mod._player is None:
            _gv_mod.init_player(_ctrl_mod._fg_ctrl)
    else:
        status_lines.append("Generic backend (keyboard+mouse primitives)")

    if "controller" in control:
        status_lines.append(f"Xbox controller: {'connected' if _CTRL_OK else 'unavailable'}")

    return "\n".join(status_lines)


def game_advice(game="", situation="general") -> str:
    """Get tactical AI coaching for the current or specified game."""
    profile = _current_profile or {}
    target  = game or _current_game or "general gaming"
    module  = profile.get("module", "")

    if module == "cs2_pro" and _CS2_OK:
        try:
            return _cs2_mod.cs2_advice(situation or "general")
        except Exception:
            pass

    prompt = (f"I'm playing {target}. Situation: {situation or 'general gameplay'}. "
              f"Give me 3 specific, actionable tips to improve right now. Be brief.")
    response = _ollama(prompt)
    if response:
        return response

    # Hard-coded fallback advice per game type
    gtype = profile.get("type", "fps")
    fallbacks = {
        "fps": [
            "Pre-aim corners at head height before peeking.",
            "Use sound — stop moving when you hear footsteps.",
            "Don't hold the same angle twice — reposition after a kill.",
        ],
        "platformer": [
            "Stay near the middle of platforms to give yourself recovery room.",
            "Jump early — most platformers have coyote time.",
            "Watch where other players fall and avoid those paths.",
        ],
        "action": [
            "Save your cooldowns for dangerous situations, not trash mobs.",
            "Learn enemy attack telegraphs — every animation has a tell.",
            "Dodge into attacks, not away — most hitboxes trail the animation.",
        ],
    }
    tips = fallbacks.get(gtype, fallbacks["fps"])
    return f"Tips for {target}:\n" + "\n".join(f"• {t}" for t in tips)


def game_analyze() -> str:
    """Capture the current screen and describe what's happening in the game."""
    lines = []

    # Active window
    title = _get_foreground_title()
    if title:
        lines.append(f"Active window: {title}")

    # Loaded profile
    if _current_game:
        lines.append(f"Loaded game: {_current_game}")

    # Vision analysis for Fall Guys
    profile = _current_profile or {}
    if profile.get("module") == "game_vision" and _GV_OK:
        try:
            sa  = _gv_mod.ScreenAnalyzer()
            gs  = sa.analyze_full()
            mg, conf = sa.detect_minigame(gs)
            lines += [
                f"Mini-game: {mg} ({conf:.0%} confidence)",
                f"Player position: ({gs.player_x}, {gs.player_y})",
                f"Falling: {gs.is_falling} | Stuck: {gs.is_stuck}",
                f"Slime level: {gs.slime_level:.2f}",
                f"Obstacle ahead: {gs.obstacle_ahead}",
                f"Players visible: {gs.player_count}",
                f"Edge left: {gs.edge_left} | Edge right: {gs.edge_right}",
            ]
            return "\n".join(lines)
        except Exception as e:
            lines.append(f"Vision error: {e}")

    # CS2 enemy detection
    if profile.get("module") == "cs2_pro" and _CS2_OK:
        try:
            enemies = _vision.find_enemies()
            if enemies:
                lines.append(f"Enemies detected: {len(enemies)}")
                for i, e in enumerate(enemies[:3]):
                    lines.append(f"  [{i+1}] at ({e['x']}, {e['y']}) area={e.get('area',0)}")
            else:
                lines.append("No enemies detected in frame.")
            return "\n".join(lines)
        except Exception as e:
            lines.append(f"CS2 vision error: {e}")

    lines.append("Generic analysis — load a specific game for detailed vision.")
    return "\n".join(lines)


def game_move(direction="forward", duration=0.5, speed=1.0) -> str:
    """Move the player. direction: forward/back/left/right/forward-left/etc."""
    profile = _current_profile or {}
    control = profile.get("control", "mouse+kb")

    if "controller" in control and _CTRL_OK:
        stick_map = {
            "forward":       (0.0,  speed),
            "back":          (0.0, -speed),
            "backward":      (0.0, -speed),
            "left":          (-speed, 0.0),
            "right":         (speed,  0.0),
            "forward-left":  (-speed * 0.7,  speed * 0.7),
            "forward-right": ( speed * 0.7,  speed * 0.7),
            "back-left":     (-speed * 0.7, -speed * 0.7),
            "back-right":    ( speed * 0.7, -speed * 0.7),
        }
        xy = stick_map.get(direction.lower(), (0.0, speed))
        _xbox.stick("left", xy[0], xy[1], duration)
        return f"Controller: moved {direction} for {duration}s"

    _require_ri("game_move")
    keys = _DIR_KEYS.get(direction.lower())
    if keys is None:
        return f"Unknown direction: {direction}"
    if isinstance(keys, tuple):
        for k in keys:
            _ri.key_down(k)
        time.sleep(duration)
        for k in keys:
            _ri.key_up(k)
    else:
        _ri.key_hold(keys, duration)
    return f"Moved {direction} for {duration}s"


def game_look(direction="right", amount=200, smooth=True) -> str:
    """Move the camera/crosshair. direction: left/right/up/down. amount: pixels."""
    _require_ri("game_look")
    dv = _LOOK_DIRS.get(direction.lower(), (1, 0))
    dx = dv[0] * amount
    dy = dv[1] * amount
    if smooth:
        _ri.mouse_move_smooth(dx, dy)
    else:
        _ri.mouse_move(dx, dy)
    return f"Looked {direction} by {amount}px"


def game_shoot(button="left", burst=1, interval=0.1) -> str:
    """Fire the weapon. Uses spray compensation for CS2 if loaded."""
    profile = _current_profile or {}

    if profile.get("module") == "cs2_pro" and _CS2_OK and _spray is not None:
        try:
            _spray.burst(burst)
            return f"CS2 burst: {burst} shot(s) with spray compensation"
        except Exception as e:
            pass  # fall through to raw click

    _require_ri("game_shoot")
    for i in range(max(1, burst)):
        _ri.click(button)
        if i < burst - 1:
            time.sleep(interval)
    return f"Shot {burst} round(s)"


def game_action(action="jump") -> str:
    """
    Perform a named game action.
    action: jump, crouch, reload, use, interact, grab, dive, sprint, melee
    """
    profile = _current_profile or {}
    control = profile.get("control", "mouse+kb")

    action_keys = {
        "jump":     "space",
        "crouch":   "ctrl",
        "reload":   "r",
        "use":      "e",
        "interact": "e",
        "grab":     "e",
        "dive":     "ctrl",
        "sprint":   "shift",
        "melee":    "f",
        "prone":    "z",
        "walk":     "alt",
    }

    if "controller" in control and _CTRL_OK:
        btn_map = {
            "jump":     "a",
            "crouch":   "b",
            "dive":     "b",
            "reload":   "x",
            "interact": "x",
            "grab":     "x",
            "melee":    "y",
            "sprint":   "ls",
        }
        btn = btn_map.get(action.lower(), "a")
        _xbox.press(btn)
        return f"Controller: {action} (button {btn})"

    _require_ri("game_action")
    key = action_keys.get(action.lower(), action.lower())
    _ri.key_press(key)
    return f"Action: {action}"


def game_press_key(key="e") -> str:
    """Press and release a keyboard key."""
    _require_ri("game_press_key")
    _ri.key_press(key)
    return f"Pressed: {key}"


def game_hold_key(key="w", duration=1.0) -> str:
    """Hold a key for a duration (seconds)."""
    _require_ri("game_hold_key")
    _ri.key_hold(key, float(duration))
    return f"Held {key} for {duration}s"


def game_hotkey(keys="ctrl+c", delay=0.05) -> str:
    """Press a key combo. keys: string like 'ctrl+c' or 'alt+tab'."""
    _require_ri("game_hotkey")
    parts = [k.strip() for k in str(keys).split("+")]
    for k in parts:
        _ri.key_down(k)
        time.sleep(float(delay))
    time.sleep(0.05)
    for k in reversed(parts):
        _ri.key_up(k)
    return f"Hotkey: {'+'.join(str(k) for k in keys)}"


def xbox_press(button="a", duration=0.1) -> str:
    """Press an Xbox controller button. button: a/b/x/y/lb/rb/lt/rt/ls/rs/start/back"""
    _require_xbox("xbox_press")
    _xbox.press(button, float(duration))
    return f"Xbox pressed: {button}"


def xbox_stick(stick="left", x=0.0, y=0.0, duration=0.5) -> str:
    """Move an Xbox stick. stick: left/right. x,y: -1.0 to 1.0"""
    _require_xbox("xbox_stick")
    _xbox.stick(stick, float(x), float(y), float(duration))
    return f"Xbox {stick} stick: ({x}, {y}) for {duration}s"


def xbox_trigger(side="right", value=255, duration=0.2) -> str:
    """Press an Xbox trigger. side: left/right. value: 0-255"""
    _require_xbox("xbox_trigger")
    _xbox.trigger(side, int(value), float(duration))
    return f"Xbox {side} trigger: {value} for {duration}s"


# ── Auto-play loop ────────────────────────────────────────────────────────────

def game_auto_fps(duration=60, game="") -> str:
    """
    Run the autonomous game-playing loop for the loaded (or specified) game.
    duration: seconds to play. game: override the loaded profile.
    """
    global _auto_thread, _auto_active, _auto_paused

    if _auto_active:
        return "Already running an auto-play session. Say 'game stop' first."

    if game:
        game_load(game)

    profile = _current_profile or {}
    module  = profile.get("module")
    display = profile.get("display", _current_game or "game")

    _auto_active = True
    _auto_paused = False

    if module == "game_vision" and _GV_OK:
        # Fall Guys — delegate entirely to IntelligentPlayer
        def _fg_run():
            global _auto_active
            try:
                if _gv_mod._player is None and _CTRL_OK:
                    _gv_mod.init_player(_ctrl_mod._fg_ctrl)
                _gv_mod.fg_smart_start(int(duration) // 60 or 1)
                # Wait until the player finishes
                while _gv_mod._player and _gv_mod._player.active:
                    if not _auto_active:
                        _gv_mod.fg_smart_stop()
                        break
                    time.sleep(1)
            except Exception as e:
                pass
            _auto_active = False

        _auto_thread = threading.Thread(target=_fg_run, daemon=True)
        _auto_thread.start()
        return (f"Fall Guys AI started for {duration}s.\n"
                f"Vision + controller active. Switch to Fall Guys now!\n"
                f"Say 'game stop' or 'stop fall guys' to end.")

    if module == "cs2_pro" and _CS2_OK:
        # CS2 — use DonkAI auto loop
        def _cs2_run():
            global _auto_active
            try:
                _cs2_mod.cs2_start(int(duration) // 60 or 1)
            except Exception:
                pass
            _auto_active = False

        _auto_thread = threading.Thread(target=_cs2_run, daemon=True)
        _auto_thread.start()
        return (f"CS2 AI started for {duration}s.\n"
                f"Vision targeting + spray compensation active.\n"
                f"Say 'game stop' to end.")

    # Generic FPS — real YOLO-powered targeting loop
    sens_mult = profile.get("sens_mult", 1.0)
    _auto_thread = threading.Thread(
        target=_generic_fps_ai_loop,
        args=(float(duration), display, sens_mult),
        daemon=True
    )
    _auto_thread.start()
    yolo_note = _yolo_status_note()
    return (f"🎯 {display} AI started for {duration}s\n"
            f"{yolo_note}\n"
            f"Switch to {display} now — starting in 3 seconds\n"
            f"Say 'game stop' to end")


def _yolo_status_note() -> str:
    """Return a one-line YOLO readiness note for the user."""
    try:
        import cs2_yolo as _ym
        det = _ym.get_detector()
        if det and det.loaded:
            return f"Vision: YOLO active ({det.model_name} on {det.device})"
        if det and det._load_thread and det._load_thread.is_alive():
            return "Vision: YOLO loading in background — targeting activates when ready"
        pts = list((pathlib.Path.home() / "Documents" / "JARVIS" / "models").glob("*.pt"))
        if not pts:
            return "Vision: No YOLO model — say 'setup yolo' for AI targeting (CV2 fallback active)"
        return "Vision: YOLO model found, loading..."
    except Exception:
        return "Vision: CV2 fallback active"


def _get_yolo_detector():
    """Return the loaded YOLO detector, or None if not ready."""
    try:
        import cs2_yolo as _ym
        det = _ym.get_detector()
        if det and det.is_ready:
            return det
    except Exception:
        pass
    return None


def _generic_fps_ai_loop(duration_secs: float, display: str, sens_mult: float = 1.0):
    """
    Real YOLO-powered FPS AI loop for any game.
    - Uses the CS2 YOLO model to detect player silhouettes (works in most FPS games)
    - Falls back to edge-based CV2 detection when YOLO isn't loaded
    - Aims at the nearest detected target and fires
    - Moves intelligently: forward exploration + strafe when no target found
    """
    global _auto_active, _auto_paused
    import random

    try:
        import numpy as np
        import pyautogui
        _HAS_VIS = True
    except ImportError:
        _HAS_VIS = False

    if not _CS2_OK:
        _auto_active = False
        return

    sw, sh = (2560, 1440)
    try:
        if _HAS_VIS:
            sw, sh = pyautogui.size()
    except Exception:
        pass
    cx, cy = sw // 2, sh // 2

    time.sleep(3)  # give the player time to switch to the game

    end          = time.time() + duration_secs
    last_target  = None
    no_target_t  = 0.0
    scan_dir     = 1      # 1 = right, -1 = left
    scan_sweep   = 0
    last_shot    = 0.0
    last_move    = 0.0
    last_strafe  = 0.0

    AIM_SPEED    = 0.55 * sens_mult   # fraction of delta to correct per frame
    ON_TARGET_PX = 40                  # pixels from center considered "on target"
    SCAN_PIXELS  = 250                 # mouse pixels per scan sweep
    FIRE_COOLDOWN = 0.08

    while _auto_active and time.time() < end:
        if _auto_paused:
            time.sleep(0.1)
            continue

        try:
            # ── Capture screen ────────────────────────────────────
            if not _HAS_VIS:
                time.sleep(0.1)
                continue
            frame = np.array(pyautogui.screenshot())

            # ── Detect enemies ────────────────────────────────────
            enemies = []
            det = _get_yolo_detector()
            if det:
                enemies = det.detect(frame)
            else:
                # CV2 fallback — edge blob detection
                try:
                    import cv2
                    gray  = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                    roi   = gray[int(sh * 0.1):int(sh * 0.8), int(sw * 0.15):int(sw * 0.85)]
                    edges = cv2.Canny(roi, 40, 120)
                    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in cnts:
                        a = cv2.contourArea(c)
                        if 400 < a < 20000:
                            x, y, w, h = cv2.boundingRect(c)
                            bx = x + w // 2 + int(sw * 0.15)
                            by = y + h // 2 + int(sh * 0.1)
                            dist = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
                            enemies.append({"x": bx, "y": by, "head_x": bx,
                                            "head_y": y + int(sh * 0.1),
                                            "dist": dist, "conf": 0.4})
                    enemies.sort(key=lambda e: e["dist"])
                except Exception:
                    pass

            now = time.time()

            if enemies:
                no_target_t = 0.0
                target      = enemies[0]
                aim_x = target.get("head_x", target["x"])
                aim_y = target.get("head_y", target["y"])

                dx = aim_x - cx
                dy = aim_y - cy

                # Smooth aim towards target
                move_x = int(dx * AIM_SPEED)
                move_y = int(dy * AIM_SPEED)
                if abs(move_x) > 1 or abs(move_y) > 1:
                    _ri.mouse_move_smooth(move_x, move_y)

                # Fire when roughly on target
                if abs(dx) < ON_TARGET_PX and abs(dy) < ON_TARGET_PX:
                    if now - last_shot > FIRE_COOLDOWN:
                        _ri.click()
                        last_shot = now

                # Keep moving forward while engaging
                if now - last_move > 0.6:
                    _ri.key_hold("w", 0.15)
                    last_move = now

            else:
                # No target — scan and explore
                no_target_t += 0.033

                # Sweep the mouse left/right to scan
                if scan_sweep <= 0:
                    _ri.mouse_move_smooth(SCAN_PIXELS * scan_dir, 0)
                    scan_dir    = -scan_dir
                    scan_sweep  = 8  # frames between sweeps
                scan_sweep -= 1

                # Move forward periodically
                if now - last_move > 1.2:
                    _ri.key_hold("w", random.uniform(0.3, 0.7))
                    last_move = now

                # Strafe occasionally to change angle
                if now - last_strafe > 2.5:
                    key = random.choice(["a", "d"])
                    _ri.key_hold(key, random.uniform(0.15, 0.35))
                    last_strafe = now

                # Jump occasionally over obstacles
                if random.random() < 0.005:
                    _ri.key_press("space")

            time.sleep(0.033)  # ~30 fps loop

        except Exception as _loop_err:
            time.sleep(0.1)

    _ri.release_all() if hasattr(_ri, "release_all") else None
    _auto_active = False


def game_stop() -> str:
    """Stop the current auto-play session."""
    global _auto_active
    _auto_active = False

    profile = _current_profile or {}
    module  = profile.get("module")

    if module == "game_vision" and _GV_OK:
        try:
            return _gv_mod.fg_smart_stop()
        except Exception:
            pass

    if module == "cs2_pro" and _CS2_OK:
        try:
            _cs2_mod.cs2_stop()
        except Exception:
            pass

    if _CTRL_OK and _xbox:
        try:
            _xbox.reset()
        except Exception:
            pass

    return "Auto-play stopped."


def game_pause() -> str:
    """Pause or resume the current auto-play session."""
    global _auto_paused
    _auto_paused = not _auto_paused

    profile = _current_profile or {}
    module  = profile.get("module")

    if module == "game_vision" and _GV_OK:
        try:
            return _gv_mod.fg_smart_pause()
        except Exception:
            pass

    return "Paused." if _auto_paused else "Resumed."


# ── Target detection ─────────────────────────────────────────────────────────

def game_detect_targets() -> str:
    """Scan the screen for enemies or targets."""
    profile = _current_profile or {}
    module  = profile.get("module")

    if module == "cs2_pro" and _CS2_OK:
        try:
            enemies = _vision.find_enemies()
            if not enemies:
                return "No targets detected."
            lines = [f"Detected {len(enemies)} target(s):"]
            for i, e in enumerate(enemies[:5]):
                lines.append(f"  [{i+1}] x={e['x']} y={e['y']} area={e.get('area',0)} method={e.get('method','?')}")
            return "\n".join(lines)
        except Exception as e:
            return f"Detection error: {e}"

    if module == "game_vision" and _GV_OK:
        try:
            sa = _gv_mod.ScreenAnalyzer()
            gs = sa.analyze_full()
            count = gs.player_count
            return (f"Players visible: {count}\n"
                    f"Nearby: {[{'x':p['x'],'y':p['y']} for p in gs.nearby_players[:5]]}")
        except Exception as e:
            return f"Vision error: {e}"

    # Generic — try YOLO first, fall back to CV2
    try:
        import numpy as np
        import pyautogui
        frame = np.array(pyautogui.screenshot())

        det = _get_yolo_detector()
        if det:
            enemies = det.detect(frame)
            if enemies:
                lines = [f"YOLO detected {len(enemies)} target(s) ({det.model_name}):"]
                for i, e in enumerate(enemies[:5]):
                    lines.append(f"  [{i+1}] pos=({e['x']},{e['y']}) conf={e['conf']:.0%} method={e.get('method','?')}")
                return "\n".join(lines)
            return f"YOLO active ({det.model_name}) — no targets on screen."

        # CV2 fallback
        import cv2
        gray   = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        h, w   = gray.shape
        roi    = gray[int(h*0.1):int(h*0.9), int(w*0.1):int(w*0.9)]
        edges  = cv2.Canny(roi, 50, 150)
        cnts, _= cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs  = [c for c in cnts if 400 < cv2.contourArea(c) < 20000]
        return (f"CV2 scan: {len(blobs)} player-sized blobs detected.\n"
                f"Say 'setup yolo' for accurate YOLO targeting.")
    except Exception as e:
        return f"Detection unavailable: {e}"


# ── Sequence execution ────────────────────────────────────────────────────────

def game_sequence(game="", task="") -> str:
    """
    Load a game profile then use AI to plan and execute a task.
    game: game name. task: what to do (e.g. 'get to the crown in Fall Mountain')
    """
    if game:
        load_result = game_load(game)
    else:
        load_result = f"Using loaded profile: {_current_game or 'none'}"

    if not task:
        return f"{load_result}\nNo task specified. Say what you want to do."

    # Ask Ollama to break task into JARVIS actions
    profile  = _current_profile or {}
    gtype    = profile.get("type", "fps")
    control  = profile.get("control", "mouse+kb")

    system = (
        "You are a game AI action planner. The user wants to perform a task in a game. "
        "Output ONLY a numbered list of 3-7 concrete steps using these action types: "
        "move(direction,duration), look(direction,amount), shoot(burst), action(name), wait(seconds). "
        "Be very brief — one line per step."
    )
    plan = _ollama(f"Game: {game or _current_game}. Task: {task}", system=system)
    if not plan:
        plan = (f"1. move(forward, 1.0)\n2. look(right, 100)\n3. shoot(burst=3)\n"
                f"4. move(forward, 0.5)\n5. action(jump)")

    return f"{load_result}\n\nTask plan for '{task}':\n{plan}\n\n(Use specific game_move/game_shoot/etc. commands to execute each step)"


# ── Recording ─────────────────────────────────────────────────────────────────

def game_record_start() -> str:
    """Start recording a screenshot sequence."""
    global _recording_active, _recording

    if _recording_active:
        return "Already recording. Say 'game record stop' first."

    _record_dir.mkdir(parents=True, exist_ok=True)
    _recording        = []
    _recording_active = True

    def _rec_loop():
        global _recording_active
        while _recording_active:
            try:
                import pyautogui
                ts   = datetime.datetime.now().strftime("%H%M%S_%f")
                path = _record_dir / f"frame_{ts}.png"
                pyautogui.screenshot(str(path))
                _recording.append(str(path))
                if len(_recording) > 3000:
                    _recording_active = False
            except Exception:
                pass
            time.sleep(0.1)

    threading.Thread(target=_rec_loop, daemon=True).start()
    return f"Recording started. Frames saved to: {_record_dir}"


def game_record_stop() -> str:
    """Stop the recording."""
    global _recording_active
    _recording_active = False
    count = len(_recording)
    return f"Recording stopped. {count} frames captured in {_record_dir}"


def game_replay(speed=1.0) -> str:
    """Show a summary of the last recording session."""
    if not _recording:
        return "No recording found. Start one with 'game record start'."
    total = len(_recording)
    first = _recording[0] if _recording else "none"
    last  = _recording[-1] if _recording else "none"
    return (f"Recording summary:\n"
            f"  Frames: {total}\n"
            f"  First: {first}\n"
            f"  Last:  {last}\n"
            f"  Location: {_record_dir}\n"
            f"  Duration: ~{total * 0.1:.1f}s at 10fps")


# ── Profile listing ───────────────────────────────────────────────────────────

def list_game_profiles() -> str:
    """List all known game profiles."""
    lines = ["Known game profiles:", ""]
    seen  = set()
    for key, p in PROFILES.items():
        display = p.get("display", key)
        if display in seen:
            continue
        seen.add(display)
        module  = p.get("module") or "generic"
        control = p.get("control", "mouse+kb")
        gtype   = p.get("type", "?")
        lines.append(f"  {display:<22} type={gtype:<12} control={control:<14} backend={module}")

    lines += [
        "",
        f"CS2 backend ready:        {'yes' if _CS2_OK else 'no (cs2_pro import failed)'}",
        f"Fall Guys vision ready:   {'yes' if _GV_OK else 'no (game_vision import failed)'}",
        f"Xbox controller ready:    {'yes' if _CTRL_OK else 'no (ViGEm not installed?)'}",
        f"Keyboard/mouse ready:     {'yes' if _CS2_OK else 'no (RawInput unavailable)'}",
        "",
        "Say 'load game [name]' to activate a profile.",
    ]
    return "\n".join(lines)
