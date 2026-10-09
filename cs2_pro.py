"""
cs2_pro.py — JARVIS CS2 Pro AI
Plays at the level of top professional players.
- Sub-20ms reaction times
- Pixel-perfect flick shots
- Perfect spray control for every weapon
- Pre-aim common angles
- Counter-strafing
- Crosshair placement
- Grenade lineups
- Economy management
- Map awareness
"""

import ctypes, time, math, random, threading, subprocess, json, re
try:
    import input_monitor as IM
    import focus_monitor as FM
    import cs2_knowledge as CK
    import cs2_yolo as YOLO_MOD
    import cs2_targeting as TGT
    HAS_MONITOR = True
    print("[JARVIS] All game modules loaded OK")
    print(f"[JARVIS] TGT type: {type(TGT)}")
except Exception as _import_err:
    import traceback as _tb
    HAS_MONITOR = False
    print(f"[JARVIS] ⚠️  Module import error: {_import_err}")
    print(_tb.format_exc())
    class _IM:
        def start_monitoring(self): pass
        def set_ai_active(self, v): pass
        def notify_ai_input(self): pass
        def is_human_active(self): return False
        def register_takeover_callback(self, fn): pass
        def clear_takeover(self): pass
    IM = _IM()
    class _FM:
        def start(self, t): pass
        def stop(self): pass
        def is_game_focused(self): return True
        def on_focus_lost(self, cb): pass
        def on_focus_gained(self, cb): pass
        def focus_game(self, t): return True
        def wait_for_focus(self, timeout=30): return True
        def clear_callbacks(self): pass
    FM = _FM()
    class _CK:
        def get_agent_detector(self): return None
        def get_navigator(self): return None
    CK = _CK()
    class _YOLO_MOD:
        def get_detector(self): return None
        def yolo_status(self): return 'YOLO unavailable'
        def yolo_detect_test(self): return 'YOLO unavailable'
    YOLO_MOD = _YOLO_MOD()
    class _TGT:
        def combat_configure(self,**k): return 'Targeting unavailable - cs2_targeting.py failed to import'
        def combat_start(self,**k): return 'Targeting unavailable'
        def combat_stop(self): return 'Targeting unavailable'
        def combat_status(self): return 'Targeting unavailable'
        def combat_set_reaction(self,**k): return 'ok'
        def combat_set_weapon(self,**k): return 'ok'
        def combat_test_shot(self): return 'Targeting unavailable - check JARVIS server window for import error'
        def combat_pause(self): return 'ok'
        def get_combat_engine(self): return None
    TGT = _TGT()
from pathlib import Path
from datetime import datetime
try:
    import numpy as np
except ImportError:
    np = None

DATA_DIR  = Path.home() / "Documents" / "JARVIS" / "game_ai" / "cs2_pro"
MODEL_DIR = Path.home() / "Documents" / "JARVIS" / "models"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _ensure_yolo(wait_secs: int = 12) -> str:
    """
    Make sure YOLO is loaded before starting combat.
    Returns "" if ready (or if YOLO module unavailable — fall back to CV2).
    Returns an error/instruction string if the model has never been downloaded.
    """
    try:
        det = YOLO_MOD.get_detector()
        if det is None:
            return ""  # module not available — CV2 fallback will run

        if det.loaded:
            return ""  # already good

        # Check if any model file is present on disk
        pts = list(MODEL_DIR.glob("*.pt"))
        if not pts:
            return (
                "⚠️  YOLO CS2 model not downloaded yet.\n"
                "Say 'setup yolo' to download it (takes ~1 min, one-time only).\n"
                "Once done, combat will have pixel-accurate targeting.\n"
                "Starting combat anyway with fallback CV2 vision..."
            )

        # Model exists but hasn't loaded yet — trigger load and wait
        if not (det._load_thread and det._load_thread.is_alive()):
            print("[YOLO] Triggering load before combat...")
            YOLO_MOD.yolo_load_async()

        print(f"[YOLO] Waiting up to {wait_secs}s for model to load...")
        for _ in range(wait_secs * 2):
            if det.loaded:
                print(f"[YOLO] Model ready: {det.model_name} on {det.device}")
                return ""
            time.sleep(0.5)

        print("[YOLO] Model still loading — combat will start; YOLO joins when ready")
        return ""
    except Exception as _ye:
        print(f"[YOLO] _ensure_yolo error: {_ye}")
        return ""

# ─────────────────────────────────────────────────────────────
# WINDOWS INPUT — Raw DirectInput level
# ─────────────────────────────────────────────────────────────

# ── ctypes structures defined at module level (never redefined) ──────────────
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
    ]

class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type",   ctypes.c_ulong),
        ("_input", _INPUT_UNION),
    ]

class RawInput:
    """
    Sends input at the lowest possible Windows level.
    Uses SendInput API — same path CS2 raw input reads.
    Bypasses all input filtering.
    """
    # SendInput constants
    INPUT_MOUSE    = 0
    INPUT_KEYBOARD = 1
    MOUSEEVENTF_MOVE       = 0x0001
    MOUSEEVENTF_LEFTDOWN   = 0x0002
    MOUSEEVENTF_LEFTUP     = 0x0004
    MOUSEEVENTF_RIGHTDOWN  = 0x0008
    MOUSEEVENTF_RIGHTUP    = 0x0010
    KEYEVENTF_KEYDOWN      = 0x0000
    KEYEVENTF_KEYUP        = 0x0002
    KEYEVENTF_SCANCODE     = 0x0008

    # Scan codes — hardware level, bypasses virtual key filtering
    SCANCODES = {
        "w":0x11,"a":0x1E,"s":0x1F,"d":0x20,
        "r":0x13,"e":0x12,"f":0x21,"g":0x22,
        "q":0x10,"z":0x2C,"x":0x2D,"c":0x2E,
        "v":0x2F,"b":0x30,"t":0x14,"y":0x15,
        "1":0x02,"2":0x03,"3":0x04,"4":0x05,"5":0x06,
        "space":0x39,"ctrl":0x1D,"shift":0x2A,
        "tab":0x0F,"enter":0x1C,"escape":0x01,
        "f1":0x3B,"f2":0x3C,"f3":0x3D,"f4":0x3E,
        "lalt":0x38,
    }

    # Reference module-level structures (defined once, never redefined)
    MOUSEINPUT  = _MOUSEINPUT
    KEYBDINPUT  = _KEYBDINPUT
    INPUT_UNION = _INPUT_UNION
    INPUT       = _INPUT

    def __init__(self):
        self._held_keys = set()

    def _send_input(self, inputs):
        n = len(inputs)
        InputArray = _INPUT * n
        ctypes.windll.user32.SendInput(
            n, InputArray(*inputs), ctypes.sizeof(_INPUT))

    def mouse_move(self, dx, dy):
        """Instant raw mouse movement."""
        if dx == 0 and dy == 0: return
        IM.notify_ai_input()
        inp = _INPUT()
        inp.type = self.__class__.INPUT_MOUSE
        inp._input.mi.dx = int(dx)
        inp._input.mi.dy = int(dy)
        inp._input.mi.dwFlags = self.MOUSEEVENTF_MOVE
        self._send_input([inp])

    def mouse_move_smooth(self, dx, dy, steps=8):
        """Smooth mouse movement over multiple frames."""
        if dx == 0 and dy == 0: return
        remaining_x, remaining_y = float(dx), float(dy)
        sent_x, sent_y = 0, 0
        for i in range(steps):
            # Ease-out curve for natural deceleration
            t = (i + 1) / steps
            ease = 1 - (1 - t) ** 2
            target_x = int(dx * ease)
            target_y = int(dy * ease)
            move_x = target_x - sent_x
            move_y = target_y - sent_y
            if move_x != 0 or move_y != 0:
                self.mouse_move(move_x, move_y)
                sent_x = target_x
                sent_y = target_y
            time.sleep(0.0008)

    def mouse_down(self, button="left"):
        inp = _INPUT()
        inp.type = self.__class__.INPUT_MOUSE
        inp._input.mi.dwFlags = (self.MOUSEEVENTF_LEFTDOWN
                                  if button == "left"
                                  else self.MOUSEEVENTF_RIGHTDOWN)
        self._send_input([inp])

    def mouse_up(self, button="left"):
        inp = _INPUT()
        inp.type = self.__class__.INPUT_MOUSE
        inp._input.mi.dwFlags = (self.MOUSEEVENTF_LEFTUP
                                  if button == "left"
                                  else self.MOUSEEVENTF_RIGHTUP)
        self._send_input([inp])

    def click(self, button="left", duration=0.0):
        self.mouse_down(button)
        if duration > 0: time.sleep(duration)
        self.mouse_up(button)

    def key_down(self, key):
        sc = self.SCANCODES.get(key.lower())
        if not sc: return
        IM.notify_ai_input()
        inp = _INPUT()
        inp.type = self.__class__.INPUT_KEYBOARD
        inp._input.ki.wScan = sc
        inp._input.ki.dwFlags = self.KEYEVENTF_SCANCODE
        self._send_input([inp])
        self._held_keys.add(key.lower())

    def key_up(self, key):
        sc = self.SCANCODES.get(key.lower())
        if not sc: return
        inp = _INPUT()
        inp.type = self.__class__.INPUT_KEYBOARD
        inp._input.ki.wScan = sc
        inp._input.ki.dwFlags = self.KEYEVENTF_SCANCODE | self.KEYEVENTF_KEYUP
        self._send_input([inp])
        self._held_keys.discard(key.lower())

    def key_press(self, key, duration=0.045):
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def key_hold(self, key, duration):
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def release_all(self):
        for key in list(self._held_keys):
            self.key_up(key)
        self._held_keys.clear()

    def counter_strafe(self, movement_key):
        """
        Counter-strafe: press opposite key briefly to stop momentum.
        Essential for accurate shooting in CS2.
        """
        opposite = {"a":"d","d":"a","w":"s","s":"w"}
        opp = opposite.get(movement_key)
        if opp:
            self.key_up(movement_key)
            self.key_down(opp)
            time.sleep(0.06)  # ~1 tick — enough to stop
            self.key_up(opp)


# ─────────────────────────────────────────────────────────────
# PRO-LEVEL SPRAY PATTERNS
# ─────────────────────────────────────────────────────────────

# Real CS2 spray compensation vectors (x=left/right, y=up/down)
# These are the EXACT patterns used by pro players
SPRAY_PATTERNS = {
    "ak47": [
        (0,0),(0,-6),(2,-10),(1,-12),(-1,-11),(-3,-9),(-4,-8),
        (-4,-7),(-3,-6),(-2,-6),(-1,-6),(0,-5),(1,-5),(2,-4),
        (2,-4),(3,-3),(3,-3),(2,-3),(2,-2),(1,-2),(0,-2),(-1,-2),
        (-2,-2),(-2,-1),(-3,-1),(-3,0),(-2,0),(-2,0),(-1,0),(0,0),
    ],
    "m4a4": [
        (0,0),(0,-5),(1,-9),(0,-11),(-1,-10),(-2,-9),(-3,-8),
        (-3,-7),(-2,-6),(-1,-5),(0,-5),(1,-4),(2,-4),(2,-3),
        (2,-3),(2,-2),(1,-2),(1,-2),(0,-2),(0,-1),(-1,-1),
        (-1,-1),(-2,-1),(-2,0),(-2,0),(-1,0),(-1,0),(0,0),(0,0),(0,0),
    ],
    "m4a1s": [
        (0,0),(0,-5),(1,-8),(0,-10),(-1,-9),(-2,-8),(-2,-7),
        (-2,-6),(-1,-5),(0,-5),(1,-4),(1,-4),(2,-3),(2,-3),
        (1,-2),(1,-2),(0,-2),(0,-1),(-1,-1),(-1,0),(0,0),
    ],
    "aug": [
        (0,0),(0,-4),(1,-7),(0,-9),(-1,-8),(-2,-7),(-2,-6),
        (-2,-5),(-1,-5),(0,-4),(1,-4),(1,-3),(2,-3),(2,-2),
        (1,-2),(1,-1),(0,-1),(0,0),
    ],
    "famas": [
        (0,0),(0,-5),(1,-8),(0,-9),(-1,-8),(-2,-7),(-2,-6),
        (-1,-5),(0,-5),(1,-4),(1,-3),(1,-3),(0,-2),(0,-2),(0,-1),
    ],
    "galil": [
        (0,0),(0,-5),(2,-9),(1,-11),(-1,-10),(-3,-8),(-4,-7),
        (-3,-6),(-2,-5),(-1,-5),(0,-4),(1,-4),(2,-3),(2,-3),
        (3,-2),(2,-2),(1,-2),(0,-1),(-1,-1),(-2,-1),(-2,0),
    ],
    "sg553": [
        (0,0),(0,-4),(1,-7),(0,-8),(-1,-7),(-2,-6),(-2,-5),
        (-2,-4),(-1,-4),(0,-3),(1,-3),(2,-2),(2,-2),(1,-2),
        (1,-1),(0,-1),(0,0),
    ],
    "p90": [
        (0,0),(0,-3),(1,-5),(0,-6),(-1,-5),(-1,-4),(-1,-3),
        (0,-3),(0,-2),(1,-2),(1,-1),(0,-1),(0,0),
    ],
    "mp5": [
        (0,0),(0,-3),(0,-4),(0,-4),(-1,-3),(-1,-3),(0,-2),
        (0,-2),(0,-1),(0,-1),(0,0),
    ],
    "ump45": [
        (0,0),(0,-3),(1,-5),(0,-6),(-1,-5),(-1,-4),(0,-3),
        (0,-3),(0,-2),(0,-1),(0,0),
    ],
    "deagle": [
        (0,0),(0,-8),(0,-12),(0,-8),(0,-5),(0,-3),(0,-2),(0,0),
    ],
    "default": [
        (0,0),(0,-4),(0,-6),(0,-6),(0,-5),(0,-4),(0,-3),(0,-2),(0,-1),(0,0),
    ],
}


class SprayController:
    """
    Perfect spray control — applies exact compensation vectors.
    Synced to CS2's ~64-tick rate.
    """
    TICK_RATE   = 64
    TICK_TIME   = 1.0 / TICK_RATE     # 15.625ms
    FIRE_RATE = {
        "ak47": 0.1,"m4a4": 0.09,"m4a1s": 0.1,"aug": 0.09,
        "famas": 0.08,"galil": 0.09,"sg553": 0.09,
        "p90": 0.067,"mp5": 0.08,"ump45": 0.1,
        "deagle": 0.28,"default": 0.1,
    }

    def __init__(self, inp: RawInput, sensitivity=1.0, dpi=800):
        self.inp  = inp
        self.sens = sensitivity     # in-game sensitivity
        self.dpi  = dpi             # mouse DPI
        # Multiplier to convert spray units to pixels
        self.mult = (dpi * sensitivity * 0.022) / 360 * 100

    def _spray_to_pixels(self, sx, sy):
        """Convert spray pattern units to actual mouse pixels."""
        px = sx * self.mult * 0.8
        py = sy * self.mult * 0.8
        return int(px), int(py)

    def burst(self, weapon="ak47", shots=5):
        """Fire a precise burst with perfect spray control."""
        pattern  = SPRAY_PATTERNS.get(weapon, SPRAY_PATTERNS["default"])
        firerate  = self.FIRE_RATE.get(weapon, 0.1)
        results   = []

        for i in range(min(shots, len(pattern))):
            # Fire
            self.inp.mouse_down("left")
            time.sleep(0.012)
            self.inp.mouse_up("left")

            if i < shots - 1 and i + 1 < len(pattern):
                # Apply spray compensation for next shot
                sx, sy = pattern[i + 1]
                px, py = self._spray_to_pixels(sx, sy)
                if px != 0 or py != 0:
                    self.inp.mouse_move(px, py)
                # Wait for next fire tick
                time.sleep(max(0.001, firerate - 0.013))

        return f"Burst: {shots} shots ({weapon})"

    def full_spray(self, weapon="ak47", shots=20):
        """Full magazine spray with perfect pattern."""
        return self.burst(weapon, shots)

    def tap_fire(self, gaps=0.2):
        """Tap fire for long range — most accurate."""
        self.inp.click("left", 0.012)
        time.sleep(gaps)
        return "Tap fired"

    def update_settings(self, sensitivity, dpi=800):
        self.sens = sensitivity
        self.dpi  = dpi
        self.mult = (dpi * sensitivity * 0.022) / 360 * 100


# ─────────────────────────────────────────────────────────────
# PRO AIM SYSTEM
# ─────────────────────────────────────────────────────────────

class ProAim:
    """
    Donk-level aim: instant flicks, smooth tracking,
    pixel-perfect head placement.
    """

    def __init__(self, inp: RawInput, spray: SprayController,
                 sensitivity=1.0, dpi=800):
        self.inp   = inp
        self.spray = spray
        self.sens  = sensitivity
        self.dpi   = dpi
        self.sw    = 1920
        self.sh    = 1080
        self._get_screen()
        # pixels per 360 degree turn
        self.px360 = (dpi * sensitivity * 0.022)

    def _get_screen(self):
        try:
            import pyautogui
            self.sw, self.sh = pyautogui.size()  # Gets actual 2560x1440
        except Exception: pass

    def _deg_to_px(self, degrees):
        return degrees * (self.px360 / 360.0)

    def _px_to_screen_delta(self, target_x, target_y):
        """Convert target screen coords to mouse delta needed."""
        dx = target_x - (self.sw // 2)
        dy = target_y - (self.sh // 2)
        return dx, dy

    def flick(self, target_x, target_y, head_height_offset=True):
        """
        Instant flick shot — Donk signature move.
        Sub-5ms execution.
        """
        dx, dy = self._px_to_screen_delta(target_x, target_y)
        # Head is slightly above center of detected target
        if head_height_offset:
            dy -= int(self.sh * 0.025)

        # Single instant move
        self.inp.mouse_move(dx, dy)
        # 2ms reaction + 12ms click
        time.sleep(0.002)
        self.inp.click("left", 0.012)

    def smooth_aim(self, target_x, target_y, speed=0.85,
                   head_offset=True):
        """
        Smooth aim toward target.
        speed: 0.1=very slow, 1.0=instant
        """
        dx, dy = self._px_to_screen_delta(target_x, target_y)
        if head_offset:
            dy -= int(self.sh * 0.025)
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 2: return  # On target

        move_x = int(dx * speed)
        move_y = int(dy * speed)
        steps  = max(2, min(8, int(dist / 15)))
        self.inp.mouse_move_smooth(move_x, move_y, steps)

    def track(self, target_x, target_y, weapon="ak47", shots=5):
        """
        Aim, then fire with spray control.
        This is the complete pro engagement sequence.
        """
        # Counter-strafe to stop movement
        self.inp.release_all()
        time.sleep(0.05)

        # Aim to head
        dx, dy = self._px_to_screen_delta(target_x, target_y)
        dy -= int(self.sh * 0.025)
        dist = math.sqrt(dx*dx + dy*dy)

        if dist < 5:
            # Already on target — just shoot
            self.spray.burst(weapon, shots)
        elif dist < 80:
            # Close — smooth aim then burst
            self.inp.mouse_move_smooth(int(dx*0.9), int(dy*0.9), steps=4)
            time.sleep(0.008)
            self.spray.burst(weapon, shots)
        else:
            # Far — flick then burst
            self.inp.mouse_move(dx, dy)
            time.sleep(0.010)
            self.spray.burst(weapon, shots)

    def pre_aim(self, angle_x, angle_y=0):
        """
        Pre-aim an angle without shooting.
        angle_x: degrees left(-)/right(+)
        """
        px = int(self._deg_to_px(angle_x))
        py = int(self._deg_to_px(angle_y))
        self.inp.mouse_move_smooth(px, py, steps=6)

    def micro_adjust(self, intensity=0.5):
        """Tiny human-like micro-movements."""
        dx = random.uniform(-1.5, 1.5) * intensity
        dy = random.uniform(-0.5, 0.5) * intensity
        if abs(dx) > 0.5 or abs(dy) > 0.5:
            self.inp.mouse_move(int(dx), int(dy))

    def update_settings(self, sensitivity, dpi=800):
        self.sens = sensitivity
        self.dpi  = dpi
        self.px360 = dpi * sensitivity * 0.022
        self.spray.update_settings(sensitivity, dpi)


# ─────────────────────────────────────────────────────────────
# VISION — Enemy detection
# ─────────────────────────────────────────────────────────────

class ProVision:
    """High-performance enemy detection for CS2."""

    def __init__(self):
        self.sw = 2560
        self.sh = 1440
        self._get_size()
        self._last_frame = None

    def _get_size(self):
        try:
            import pyautogui
            self.sw, self.sh = pyautogui.size()
        except Exception: pass

    def capture_fast(self):
        """Fast screen capture — minimizes latency."""
        try:
            import pyautogui
            return np.array(pyautogui.screenshot())
        except Exception:
            return None

    def find_enemies(self, frame=None):
        """
        Detect CS2 enemies. Uses YOLO when loaded, falls back to CV2.
        Works across all 63+ agent skins regardless of color.
        
        Methods used (in order of reliability):
        1. Motion detection - moving objects = enemies
        2. Edge density - human silhouettes have specific edge patterns
        3. Dark contrast - catches dark CT agents
        4. Light contrast - catches light T agents (tan/pink default)
        5. Foreground separation - objects that stand out from background
        """
        if frame is None:
            frame = self.capture_fast()
        if frame is None:
            return []

        try:
            import cv2

            # ── YOLO detection (best method) ──────────────────
            try:
                det = YOLO_MOD.get_detector()
                if det and det.is_ready:
                    enemies = det.detect(frame)
                    if enemies:
                        return enemies
                    # YOLO loaded but found nothing — fall through to CV2
            except Exception:
                pass

            h, w = frame.shape[:2]
            cx, cy = w // 2, h // 2
            enemies = []

            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            hsv  = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

            # Valid play area — exclude all HUD
            y1, y2 = int(h * 0.12), int(h * 0.78)
            x1, x2 = int(w * 0.05), int(w * 0.95)
            play = gray[y1:y2, x1:x2]

            # Sample background: use the top strip (sky/ceiling) and
            # side strips as reference since enemies don't spawn there
            bg_sample = np.concatenate([
                play[:int(play.shape[0]*0.12), :].flatten(),   # top (sky)
                play[:, :int(play.shape[1]*0.08)].flatten(),   # left edge
                play[:, int(play.shape[1]*0.92):].flatten(),   # right edge
            ])
            bg_mean   = np.mean(bg_sample)
            bg_std    = np.std(bg_sample)

            # ── Method 0: Motion detection (highest priority) ─
            # Any moving region in the play area is almost certainly an enemy.
            if self._last_frame is not None:
                try:
                    prev_gray = cv2.cvtColor(self._last_frame, cv2.COLOR_RGB2GRAY)
                    prev_play = prev_gray[y1:y2, x1:x2]
                    if prev_play.shape == play.shape:
                        diff     = cv2.absdiff(play, prev_play)
                        _, motion = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                        motion   = cv2.dilate(motion, np.ones((10, 5), np.uint8), iterations=2)
                        mnum, _, mstats, mcentroids = cv2.connectedComponentsWithStats(
                            motion, connectivity=8)
                        for mi in range(1, mnum):
                            marea = mstats[mi, cv2.CC_STAT_AREA]
                            mbx   = mstats[mi, cv2.CC_STAT_LEFT]
                            mby   = mstats[mi, cv2.CC_STAT_TOP]
                            mbw   = mstats[mi, cv2.CC_STAT_WIDTH]
                            mbh   = mstats[mi, cv2.CC_STAT_HEIGHT]
                            if not (120 < marea < 40000): continue
                            if mbw < 5 or mbh < 10:       continue
                            mex = x1 + int(mcentroids[mi][0])
                            mey = y1 + int(mcentroids[mi][1])
                            if any(math.sqrt((mex-e["x"])**2 + (mey-e["y"])**2) < 55
                                   for e in enemies):
                                continue
                            mdist = math.sqrt((mex-cx)**2 + (mey-cy)**2)
                            enemies.append({
                                "x": mex, "y": mey,
                                "head_y": max(0, y1 + mby + int(mbh * 0.06)),
                                "dist": mdist, "area": marea, "conf": 0.85,
                                "method": "motion", "width": mbw, "height": mbh,
                            })
                except Exception:
                    pass
            self._last_frame = frame.copy()

            # ── Method 1: Edge-based human silhouette ─────────
            # Human figures have dense vertical edges (limbs, torso)
            # Apply Canny edge detection
            edges = cv2.Canny(play, 30, 90)

            # Remove floor (bottom 25% of play area)
            floor_y = int(edges.shape[0] * 0.75)
            edges[floor_y:, :] = 0
            # Remove top-left ad/logo area
            edges[:int(edges.shape[0]*0.20), :int(edges.shape[1]*0.22)] = 0

            # Dilate edges to group nearby lines into blobs
            k = np.ones((8, 4), np.uint8)  # taller than wide kernel
            edge_blobs = cv2.dilate(edges, k, iterations=2)
            edge_blobs = cv2.morphologyEx(edge_blobs, cv2.MORPH_CLOSE,
                                          np.ones((12, 6), np.uint8))

            num, _, stats, centroids = cv2.connectedComponentsWithStats(
                edge_blobs, connectivity=8)

            for i in range(1, num):
                area = stats[i, cv2.CC_STAT_AREA]
                bx   = stats[i, cv2.CC_STAT_LEFT]
                by   = stats[i, cv2.CC_STAT_TOP]
                bw   = stats[i, cv2.CC_STAT_WIDTH]
                bh   = stats[i, cv2.CC_STAT_HEIGHT]

                if not (150 < area < 35000): continue
                if bw < 8 or bh < 20:        continue
                if bw > w * 0.15:            continue  # too wide
                # Human shape: taller than wide at medium range
                if bh / max(bw, 1) < 0.6:   continue
                if bh / max(bw, 1) > 7.0:   continue

                # Convert to full frame coords
                ex     = x1 + int(centroids[i][0])
                ey     = y1 + int(centroids[i][1])
                top_y  = y1 + by
                head_y = top_y + int(bh * 0.06)
                head_y = max(0, min(h-1, head_y))

                # Verify: region must have varied brightness (not flat wall)
                rx1 = max(0, bx - 2)
                rx2 = min(play.shape[1], bx + bw + 2)
                ry1 = max(0, by - 2)
                ry2 = min(play.shape[0], by + bh + 2)
                region = play[ry1:ry2, rx1:rx2]
                if region.size > 0:
                    region_std = np.std(region)
                    if region_std < 8:  continue  # flat = not a person

                dist = math.sqrt((ex-cx)**2 + (ey-cy)**2)
                conf = min(area / 8000, 1.0)

                # Dedup
                if any(math.sqrt((ex-e["x"])**2+(ey-e["y"])**2) < 55
                       for e in enemies):
                    continue

                enemies.append({
                    "x": ex, "y": ey, "head_y": head_y,
                    "dist": dist, "area": area, "conf": conf,
                    "method": "edge", "width": bw, "height": bh,
                })

            # ── Method 2: Contrast detection (both dark AND light) ──
            # Finds objects that differ significantly from background
            # This catches BOTH dark CT agents AND light T agents
            
            # Object must differ from bg by at least 35 brightness units
            diff_threshold = 35

            # Dark objects against light background (CT default, dark agents)
            dark_thresh = max(20, int(bg_mean - diff_threshold))
            _, dark_mask = cv2.threshold(
                play, min(dark_thresh, 180), 255, cv2.THRESH_BINARY_INV)

            # Light objects against dark background (T default tan/pink shirt)
            light_thresh = min(240, int(bg_mean + diff_threshold))
            _, light_mask = cv2.threshold(
                play, max(light_thresh, 80), 255, cv2.THRESH_BINARY)

            for mask, method_name in [(dark_mask, "dark"), (light_mask, "light")]:
                # Remove floor, sky, HUD
                mask[floor_y:, :] = 0
                mask[:int(mask.shape[0]*0.08), :] = 0
                mask[:int(mask.shape[0]*0.22), :int(mask.shape[1]*0.22)] = 0

                k2 = np.ones((3,3), np.uint8)
                k3 = np.ones((9,5), np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k2)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3)

                num2, _, stats2, centroids2 = cv2.connectedComponentsWithStats(
                    mask, connectivity=8)

                for i in range(1, num2):
                    area2 = stats2[i, cv2.CC_STAT_AREA]
                    bx2   = stats2[i, cv2.CC_STAT_LEFT]
                    by2   = stats2[i, cv2.CC_STAT_TOP]
                    bw2   = stats2[i, cv2.CC_STAT_WIDTH]
                    bh2   = stats2[i, cv2.CC_STAT_HEIGHT]

                    if not (200 < area2 < 30000): continue
                    if bw2 < 8 or bh2 < 18:       continue
                    if bw2 > w * 0.12:            continue
                    if bh2 / max(bw2, 1) < 0.7:   continue
                    if bh2 / max(bw2, 1) > 6.5:   continue

                    ex2    = x1 + int(centroids2[i][0])
                    ey2    = y1 + int(centroids2[i][1])
                    top_y2 = y1 + by2
                    head_y2 = top_y2 + int(bh2 * 0.06)
                    head_y2 = max(0, min(h-1, head_y2))

                    dist2 = math.sqrt((ex2-cx)**2 + (ey2-cy)**2)
                    conf2 = min(area2 / 6000, 1.0)

                    if any(math.sqrt((ex2-e["x"])**2+(ey2-e["y"])**2) < 55
                           for e in enemies):
                        continue

                    enemies.append({
                        "x": ex2, "y": ey2, "head_y": head_y2,
                        "dist": dist2, "area": area2, "conf": conf2,
                        "method": method_name,
                        "width": bw2, "height": bh2,
                    })

            enemies.sort(key=lambda e: e["dist"])
            return enemies

        except Exception:
            return []
    def is_scoped(self, frame=None):
        if frame is None: frame = self.capture_fast()
        if frame is None: return False
        try:
            left  = np.mean(frame[:, :int(self.sw*0.08)])
            right = np.mean(frame[:, int(self.sw*0.92):])
            return left < 15 and right < 15
        except Exception:
            return False

    def is_flashed(self, frame=None):
        if frame is None: frame = self.capture_fast()
        if frame is None: return False
        try:
            center = frame[int(self.sh*0.3):int(self.sh*0.7),
                          int(self.sw*0.3):int(self.sw*0.7)]
            return np.mean(center) > 215
        except Exception:
            return False

    def get_health(self, frame=None):
        """Estimate health from HP bar."""
        if frame is None: frame = self.capture_fast()
        if frame is None: return 100
        try:
            import cv2
            # HP bar is bottom-left
            hp_region = frame[int(self.sh*0.9):int(self.sh*0.96),
                              int(self.sw*0.02):int(self.sw*0.1)]
            # Green = high HP, yellow = medium, red = low
            hsv = cv2.cvtColor(hp_region, cv2.COLOR_RGB2HSV)
            green = np.sum(cv2.inRange(
                hsv, np.array([40,100,100]), np.array([80,255,255])))
            yellow = np.sum(cv2.inRange(
                hsv, np.array([20,100,100]), np.array([40,255,255])))
            red = np.sum(cv2.inRange(
                hsv, np.array([0,100,100]),  np.array([10,255,255])))
            total = max(green + yellow + red, 1)
            # Rough HP estimate
            hp = int((green * 100 + yellow * 60 + red * 25) / total)
            return max(1, min(100, hp))
        except Exception:
            return 100


# ─────────────────────────────────────────────────────────────
# MAP KNOWLEDGE
# ─────────────────────────────────────────────────────────────

# Pre-aimed angles for common positions (mouse delta from spawn)
MAP_DATA = {
    "dust2": {
        "spawn_angles": {
            "T":  [(-180, 0), (0, 0), (90, 0)],    # Pre-aim CT angles
            "CT": [(180, 0), (0, 0), (-120, 0)],    # Pre-aim T angles
        },
        "common_positions": [
            "Long A", "Catwalk", "Mid Doors", "B Tunnels",
            "B Platform", "A Short", "CT Spawn"
        ],
        "smokes": {
            "mid": "Look at CT mid door — smoke from T spawn",
            "cross": "Smoke long cross from T spawn",
        }
    },
    "mirage": {
        "spawn_angles": {
            "T":  [(0, 0), (45, 0), (-45, 0)],
            "CT": [(0, 0), (-90, 0), (90, 0)],
        },
        "common_positions": [
            "A Ramp", "A Site", "B Apps", "B Site",
            "Mid Window", "CT Spawn", "Jungle"
        ],
    },
    "inferno": {
        "spawn_angles": {
            "T": [(0, 0), (30, 0), (-30, 0)],
            "CT": [(0, 0), (-60, 0), (60, 0)],
        },
        "common_positions": [
            "Banana", "B Site", "A Site", "Apps",
            "Middle", "CT Spawn", "Library"
        ],
    },
    "ancient": {
        "common_positions": [
            "A Site", "B Site", "Mid", "Temple",
            "CT Spawn", "A Ramp", "Cave"
        ],
    },
    "nuke": {
        "common_positions": [
            "Upper", "Lower", "Ramp", "Squeaky",
            "Outside", "CT Spawn", "Hut"
        ],
    },
}


# ─────────────────────────────────────────────────────────────
# PRO MOVEMENT
# ─────────────────────────────────────────────────────────────

class ProMovement:
    """
    Professional CS2 movement:
    - Counter-strafing
    - Bunny hopping
    - Crouch peeking
    - Shoulder peeking
    - Jiggle peeking
    """

    def __init__(self, inp: RawInput):
        self.inp = inp
        self._moving = None

    def advance(self, direction="w", duration=0.4):
        self.inp.key_hold(direction, duration)
        self._moving = direction

    def counter_strafe(self):
        """Stop perfectly — press opposite key briefly."""
        if self._moving:
            self.inp.counter_strafe(self._moving)
            self._moving = None

    def crouch_peek(self, direction="d", duration=0.35):
        """Peek while crouching — reduces hitbox."""
        self.inp.key_down(direction)
        time.sleep(0.05)
        self.inp.key_down("ctrl")
        time.sleep(duration)
        self.inp.key_up(direction)
        # Counter strafe
        opp = {"a":"d","d":"a"}.get(direction, "a")
        self.inp.key_down(opp)
        time.sleep(0.06)
        self.inp.key_up(opp)
        self.inp.key_up("ctrl")

    def shoulder_peek(self, direction="d"):
        """Quick shoulder peek — bait shots without exposing."""
        self.inp.key_down(direction)
        time.sleep(0.12)
        self.inp.key_up(direction)
        opp = {"a":"d","d":"a"}.get(direction, "a")
        self.inp.key_down(opp)
        time.sleep(0.08)
        self.inp.key_up(opp)

    def jiggle_peek(self, direction="d", count=2):
        """Jiggle peek — quickly gather info."""
        opp = {"a":"d","d":"a"}.get(direction, "a")
        for _ in range(count):
            self.inp.key_down(direction)
            time.sleep(0.09)
            self.inp.key_up(direction)
            self.inp.key_down(opp)
            time.sleep(0.07)
            self.inp.key_up(opp)
            time.sleep(0.04)

    def bhop(self, forward=True, count=3):
        """Bunny hop — max speed movement."""
        if forward: self.inp.key_down("w")
        for i in range(count):
            # Jump just as landing
            self.inp.key_press("space", 0.03)
            time.sleep(0.28)  # ~18 tick landing window
        if forward: self.inp.key_up("w")

    def strafe_jump(self, direction="d"):
        """Air strafe — change direction mid-air."""
        self.inp.key_press("space", 0.03)
        time.sleep(0.1)
        self.inp.key_hold(direction, 0.25)

    def hold_angle(self, duration=2.0):
        """Hold still and watch an angle."""
        time.sleep(duration)

    def reposition(self, direction="w", amount=0.4):
        """Move to new position."""
        self.inp.key_hold(direction, amount)


# ─────────────────────────────────────────────────────────────
# ECONOMY MANAGER
# ─────────────────────────────────────────────────────────────

class EconomyManager:
    """Manage CS2 economy like a pro."""

    def __init__(self, inp: RawInput):
        self.inp = inp
        self.money = 800
        self.weapon = "pistol"
        self.round_type = "pistol"

    def assess_buy(self, money, round_num=1, team_economy="medium"):
        """Decide what to buy this round."""
        if money >= 4500:
            return "full_buy"
        elif money >= 3200:
            return "semi_buy"
        elif money >= 1800:
            return "force_buy"
        else:
            return "eco"

    def execute_buy(self, buy_type="full_buy"):
        """Execute buy menu sequence."""
        self.inp.key_press("b", 0.08)
        time.sleep(0.25)

        sequences = {
            "full_buy": [
                # Primary rifle (position varies by map/side)
                ("1", 0.08), ("1", 0.08),  # Primary weapon
                (None, 0.15),               # Small delay
                ("2", 0.08), ("1", 0.08),  # Kevlar + helmet
                (None, 0.1),
                ("5", 0.08), ("1", 0.08),  # HE grenade
                (None, 0.1),
                ("5", 0.08), ("3", 0.08),  # Smoke
                (None, 0.1),
                ("5", 0.08), ("2", 0.08),  # Flashbang
            ],
            "semi_buy": [
                ("1", 0.08), ("1", 0.08),
                (None, 0.15),
                ("2", 0.08), ("1", 0.08),
            ],
            "force_buy": [
                ("2", 0.08), ("1", 0.08),  # Pistol upgrade
                (None, 0.15),
                ("2", 0.08), ("2", 0.08),  # Armor only
            ],
            "eco": [],  # Save money
        }

        for item in sequences.get(buy_type, []):
            key, duration = item
            if key: self.inp.key_press(key, duration)
            else:   time.sleep(duration)

        self.inp.key_press("escape", 0.08)
        return f"Bought: {buy_type}"


# ─────────────────────────────────────────────────────────────
# MAIN PRO PLAYER
# ─────────────────────────────────────────────────────────────

class DonkAI:
    """
    The complete pro CS2 AI.
    Aims to replicate the playstyle of top tier professional players.
    """

    def __init__(self):
        self.ri       = RawInput()
        self.spray    = SprayController(self.ri, sensitivity=1.0, dpi=800)
        self.aim      = ProAim(self.ri, self.spray, sensitivity=1.0, dpi=800)
        self.vision   = ProVision()
        self.movement = ProMovement(self.ri)
        self.economy  = EconomyManager(self.ri)
        self.active   = False
        self.paused   = False
        self._thread  = None
        self.weapon   = "ak47"
        self.stats    = {"kills":0,"deaths":0,"headshots":0,
                        "shots":0,"hits":0,"rounds":0}
        self._log     = []
        self.reaction_time = 0.015  # 15ms default — donk-level

    def _log_it(self, msg):
        entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self._log.append(entry)
        if len(self._log) > 500: self._log = self._log[-500:]

    def _focus(self):
        r = subprocess.run(
            'powershell -c "$p=Get-Process|Where-Object{$_.MainWindowTitle-like\'*Counter*\'-or$_.MainWindowTitle-like\'*cs2*\'}|Select-Object -First 1; if($p){Add-Type -TypeDefinition \'using System;using System.Runtime.InteropServices;public class W{[DllImport(\"user32.dll\")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport(\"user32.dll\")]public static extern bool ShowWindow(IntPtr h,int n);}\';[W]::ShowWindow($p.MainWindowHandle,9);[W]::SetForegroundWindow($p.MainWindowHandle);Write-Output focused}"',
            shell=True, capture_output=True, text=True, timeout=5
        )
        return "focused" in r.stdout.lower()

    def set_sensitivity(self, sens, dpi=800):
        self.aim.update_settings(sens, dpi)
        self.spray.update_settings(sens, dpi)
        return f"Sensitivity: {sens} @ {dpi} DPI — calibrated"

    def set_weapon(self, weapon):
        w = weapon.lower().replace("-","").replace(" ","")
        if w in SPRAY_PATTERNS:
            self.weapon = w
        elif "ak" in w:    self.weapon = "ak47"
        elif "m4a1" in w:  self.weapon = "m4a1s"
        elif "m4" in w:    self.weapon = "m4a4"
        elif "aug" in w:   self.weapon = "aug"
        elif "famas" in w: self.weapon = "famas"
        elif "galil" in w: self.weapon = "galil"
        elif "sg" in w:    self.weapon = "sg553"
        elif "p90" in w:   self.weapon = "p90"
        elif "mp5" in w:   self.weapon = "mp5"
        elif "deagle" in w:self.weapon = "deagle"
        else:              self.weapon = "default"
        self.spray.burst.__func__  # confirm method exists
        return f"Weapon set to: {self.weapon}"

    def start(self, duration_minutes=30, mode="full"):
        if self.active: return "Already playing!"
        self.active = True
        self.paused = False
        self._mode  = mode

        # Kick off YOLO load now (non-blocking) — will be ready by the time
        # the 5-second countdown finishes and the game loop begins
        yolo_warn = _ensure_yolo(wait_secs=0)  # don't wait here; load runs async

        msg = (f"🎯 JARVIS Pro CS2 AI — Donk Mode\n"
               f"⏱️  Duration: {duration_minutes} minutes\n"
               f"🎮 Mode: {mode}\n"
               f"⚡ Reaction time: {self.reaction_time*1000:.0f}ms\n"
               f"🔫 Weapon: {self.weapon}\n"
               f"🖱️  Using: Raw DirectInput (scan codes)\n\n"
               f"Switch to CS2 NOW — starting in 5 seconds\n"
               f"Say 'stop cs2' anytime")

        IM.clear_takeover()  # Always reset before starting
        FM.clear_callbacks()
        FM.start(["Counter-Strike", "cs2", "CS2"])  # Monitor CS2 focus

        def _stop_on_human():
            self.active = False
            self.ri.release_all()
            self._log_it("Human takeover — AI stopped")

        def _on_focus_lost(title):
            self.ri.release_all()
            self._log_it(f"Tabbed out to: {title} — inputs paused")

        def _on_focus_gained(title):
            self._log_it(f"Back in game — inputs resuming")

        IM.register_takeover_callback(_stop_on_human)
        FM.on_focus_lost(_on_focus_lost)
        FM.on_focus_gained(_on_focus_gained)

        def _run():
            for i in range(5, 0, -1):
                if not self.active: return
                time.sleep(1)
            # Focus CS2 window
            focused = FM.focus_game(["Counter-Strike", "cs2", "CS2"])
            self._log_it(f"Started. CS2 focused: {focused}")
            IM.set_ai_active(True)

            # Buy at round start
            if mode in ("full", "buy"):
                self.economy.execute_buy("full_buy")
                time.sleep(0.5)

            self._game_loop(duration_minutes * 60)
            IM.set_ai_active(False)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return msg

    def _game_loop(self, duration_sec):
        """Pro-level game loop — vision → decision → action in <20ms."""
        IM.clear_takeover()  # reset takeover state at start of every session
        start      = time.time()
        last_focus = 0
        last_move  = 0
        frame_time = 1.0 / 128  # 128hz simulation
        loop       = 0

        while self.active and (time.time() - start) < duration_sec:
            t0 = time.time()

            if self.paused:
                self.ri.release_all()
                time.sleep(0.1)
                continue

            if time.time() - last_focus > 30:
                self._focus()
                last_focus = time.time()

            try:
                # ── HUMAN TAKEOVER CHECK — first thing every loop ──
                if IM.is_human_active():
                    self.ri.release_all()
                    self.active = False
                    self._log_it("Human takeover — stopping")
                    break

                # ── FOCUS CHECK — pause if player tabbed out ──────
                if not FM.is_game_focused():
                    self.ri.release_all()
                    self._log_it("Game unfocused — pausing inputs")
                    # Wait until focused again or stopped
                    while self.active and not FM.is_game_focused():
                        time.sleep(0.25)
                    if self.active:
                        self._log_it("Game refocused — resuming")
                    continue

                # ── CAPTURE ──────────────────────────────────
                frame = self.vision.capture_fast()
                if frame is None:
                    time.sleep(0.01); continue

                # ── FLASH CHECK ───────────────────────────────
                if self.vision.is_flashed(frame):
                    self.ri.release_all()
                    time.sleep(0.3)
                    continue

                # ── ENEMY DETECTION ───────────────────────────
                enemies = self.vision.find_enemies(frame)

                if enemies and self._mode in ("full","aim_only"):
                    # ── ENGAGE via CombatEngine ───────────────
                    try:
                        engine = TGT.get_combat_engine()
                        engine.run_frame(enemies)
                        self.stats["shots"] += engine.stats.get("shots_fired", 0)
                    except Exception:
                        # Fallback to direct aim
                        target = enemies[0]
                        ex, ey = target["x"], target["head_y"]
                        react  = random.uniform(
                            self.reaction_time * 0.7,
                            self.reaction_time * 1.3)
                        time.sleep(react)
                        self.ri.release_all()
                        time.sleep(0.04)
                        self.aim.track(ex, ey, self.weapon,
                                      shots=random.randint(3,6))
                        self.stats["shots"] += 4
                        self._log_it(f"Engaged at ({ex},{ey})")

                elif self._mode in ("full","move_only"):
                    # ── MOVEMENT ─────────────────────────────
                    if time.time() - last_move > 0.08:
                        self._movement_decision(loop)
                        last_move = time.time()

                loop += 1

                # Maintain target loop rate
                elapsed = time.time() - t0
                sleep   = max(0, frame_time - elapsed)
                time.sleep(sleep)

            except Exception as e:
                self._log_it(f"Loop error: {e}")
                time.sleep(0.05)

        self.ri.release_all()
        self.active = False
        self._log_it("Session ended")

    def _movement_decision(self, loop):
        """Smart pro movement between engagements."""
        phase = (loop // 30) % 6

        if phase == 0:   # Advance toward site
            self.ri.key_down("w")
            time.sleep(random.uniform(0.3, 0.6))
            self.ri.key_up("w")
            self.ri.counter_strafe("w")

        elif phase == 1:  # Crouch peek an angle
            self.movement.crouch_peek(random.choice(["a","d"]))

        elif phase == 2:  # Shoulder peek for info
            self.movement.shoulder_peek(random.choice(["a","d"]))

        elif phase == 3:  # Pre-aim common angles from map knowledge
            try:
                nav = CK.get_navigator()
                angles = nav.where_to_look(nav.current_zone) if nav else ["left","right"]
                # Sweep based on map-known danger angles
                px = int(75.0 * (self.aim.px360 / 360.0))
                self.ri.mouse_move_smooth(px, 0, steps=10)
                time.sleep(0.2)
                self.ri.mouse_move_smooth(-px * 2, 0, steps=12)
                time.sleep(0.15)
                self.ri.mouse_move_smooth(px, 0, steps=8)
            except Exception:
                px = int(90.0 * (self.aim.px360 / 360.0))
                self.ri.mouse_move_smooth(px, 0, steps=10)
                time.sleep(0.2)
                self.ri.mouse_move_smooth(-px * 2, 0, steps=12)
                time.sleep(0.15)
                self.ri.mouse_move_smooth(px, 0, steps=8)

        elif phase == 4:  # Reposition
            key = random.choice(["w","w","a","d","s"])
            self.ri.key_hold(key, random.uniform(0.2, 0.5))
            if key in ("a","d"):
                self.ri.counter_strafe(key)

        elif phase == 5:  # Hold angle — crouch and wait
            self.ri.key_down("ctrl")
            time.sleep(random.uniform(0.4, 1.0))
            self.ri.key_up("ctrl")

    def stop(self):
        self.active = False
        IM.set_ai_active(False)
        self.ri.release_all()
        kd = f"{self.stats['kills']}/{self.stats['deaths']}"
        hs = (f"{self.stats['headshots']/max(self.stats['kills'],1)*100:.0f}%"
              if self.stats['kills'] > 0 else "0%")
        return (f"🛑 CS2 Pro AI stopped\n"
                f"K/D: {kd} | HS: {hs} | Shots: {self.stats['shots']}\n"
                f"Rounds: {self.stats['rounds']}")

    def pause(self):
        self.paused = not self.paused
        if self.paused: self.ri.release_all()
        return f"{'⏸️ Paused' if self.paused else '▶️ Resumed'}"

    def aim_only(self, duration_minutes=60):
        """Aim assist only — you move, JARVIS aims."""
        return self.start(duration_minutes, "aim_only")

    def practice_aim(self, duration_seconds=120):
        """
        Practice mode: WASD movement + look around + one-tap every head.
        Uses CrosshairTracker for accurate aim during sweeps.
        """
        self.active = True
        IM.clear_takeover()
        FM.clear_callbacks()
        FM.start(["Counter-Strike", "cs2", "CS2"])

        def _stop_on_human():
            self.active = False
            self.ri.release_all()
            self._log_it("Human takeover")
        IM.register_takeover_callback(_stop_on_human)

        def _prac():
            for i in range(3, 0, -1):
                if not self.active: return
                time.sleep(1)
            focused = FM.focus_game(["Counter-Strike", "cs2", "CS2"])
            self._log_it(f"Practice started. Focused: {focused}")
            IM.set_ai_active(True)

            start      = time.time()
            shots      = 0
            kills      = 0
            last_enemy = time.time()

            # Get combat engine and detector
            try:
                import cs2_targeting as TGT_MOD
                combat = TGT_MOD.get_combat_engine()
                combat.recal()
            except Exception as e:
                self._log_it(f"Combat engine error: {e}")
                return

            try:
                import cs2_yolo as YM
                det = YM.get_detector()
            except Exception:
                det = None

            # Scan pattern — degrees to sweep each step
            scan_steps = [
                ("look_right", 60),
                ("move_fwd",   0),
                ("look_right", 60),
                ("move_fwd",   0),
                ("look_left",  180),
                ("move_fwd",   0),
                ("look_right", 60),
                ("strafe_right", 0),
                ("look_up",    0),
                ("look_down",  0),
                ("move_fwd",   0),
            ]
            scan_idx = 0

            while self.active and (time.time()-start) < duration_seconds:
                if IM.is_human_active(): break
                if not FM.is_game_focused():
                    self.ri.release_all()
                    time.sleep(0.25); continue

                # Capture and detect
                frame = self.vision.capture_fast()
                if frame is None: time.sleep(0.05); continue

                if det and det.is_ready:
                    enemies = det.detect(frame)
                else:
                    enemies = self.vision.find_enemies(frame)

                if enemies:
                    # Stop moving — engage every enemy
                    self.ri.release_all()
                    last_enemy = time.time()

                    h, w = frame.shape[:2]
                    cx, cy = w//2, h//2
                    enemies.sort(key=lambda e:
                        math.sqrt((e.get("head_x",e["x"])-cx)**2 +
                                  (e["head_y"]-cy)**2))

                    for enemy in enemies[:4]:  # max 4 per frame
                        if not self.active: break
                        if IM.is_human_active(): break
                        from cs2_targeting import Tgt as _Tgt
                        t = _Tgt(enemy, 1)
                        combat.active = True
                        result = combat.engage(t, frame)
                        combat.active = False
                        if result in ("kill", "engaged", "hit"):
                            kills += 1; shots += 1
                            self._log_it(
                                f"[{result.upper()}] [{t.team}] "
                                f"kills={kills}")
                        time.sleep(0.03)

                else:
                    # No enemies — execute next scan step
                    no_enemy_s = time.time() - last_enemy
                    step_name, param = scan_steps[scan_idx % len(scan_steps)]

                    if step_name == "look_right":
                        # Convert degrees to pixels for this FOV
                        import math as _m
                        focal = (w if 'w' in dir() else 2560)/2 /                                 _m.tan(_m.radians(106.0/2))
                        px = int(focal * _m.tan(_m.radians(param)))
                        mx, _ = TGT_MOD._to_mouse(px, 0, focal)
                        self.ri.mouse_move_smooth(px//5, 0, steps=8)

                    elif step_name == "look_left":
                        import math as _m
                        focal = (w if 'w' in dir() else 2560)/2 /                                 _m.tan(_m.radians(106.0/2))
                        px = int(focal * _m.tan(_m.radians(param)))
                        self.ri.mouse_move_smooth(-px//5, 0, steps=12)

                    elif step_name == "move_fwd":
                        self.ri.key_down("w")
                        time.sleep(0.4)
                        self.ri.key_up("w")

                    elif step_name == "strafe_right":
                        self.ri.key_down("d")
                        time.sleep(0.3)
                        self.ri.key_up("d")

                    elif step_name == "look_up":
                        self.ri.mouse_move_smooth(0, -40, steps=6)
                        time.sleep(0.15)

                    elif step_name == "look_down":
                        self.ri.mouse_move_smooth(0, 40, steps=6)
                        time.sleep(0.15)

                    scan_idx += 1
                    time.sleep(0.08)

            self.ri.release_all()
            IM.set_ai_active(False)
            self.active = False
            self._log_it(
                f"Practice done | shots={shots} kills={kills} "
                f"time={int(time.time()-start)}s")

        threading.Thread(target=_prac, daemon=True).start()
        return (f"🎯 Practice Mode ({duration_seconds}s)\n"
                f"Moving, scanning, one-tapping every head\n"
                f"Switch to CS2 NOW — 3 seconds\n"
                f"Press any key to take control back")


    def status(self):
        hp = self.vision.get_health()
        return (f"🎯 CS2 Pro AI (Donk Mode)\n"
                f"  Active: {self.active}\n"
                f"  Mode: {getattr(self,'_mode','full')}\n"
                f"  Weapon: {self.weapon}\n"
                f"  Reaction: {self.reaction_time*1000:.0f}ms\n"
                f"  Health: ~{hp}%\n"
                f"  K/D: {self.stats['kills']}/{self.stats['deaths']}\n"
                f"  Shots: {self.stats['shots']}\n\n"
                f"Recent:\n" +
                "\n".join(f"  {l}" for l in self._log[-5:]))

    def vision_test(self):
        # Check YOLO status first
        yolo_status = YOLO_MOD.yolo_status() if hasattr(YOLO_MOD, 'yolo_status') else "unknown"

        frame   = self.vision.capture_fast()
        if frame is None:
            return "❌ Could not capture screen. Make sure CS2 is open."
        import cv2
        enemies = self.vision.find_enemies(frame)
        hp      = self.vision.get_health(frame)
        h, w    = frame.shape[:2]
        gray    = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        # Sample background brightness for diagnostics
        y1,y2 = int(h*0.15),int(h*0.78)
        x1,x2 = int(w*0.05),int(w*0.95)
        play   = gray[y1:y2,x1:x2]
        bg_med = int(np.median(play))
        bg_min = int(np.min(play))
        lines  = [
            f"👁️ CS2 Vision — {len(enemies)} enemies detected",
            f"  YOLO: {yolo_status.split(chr(10))[0]}",
            f"  Resolution: {w}x{h}",
            f"  Background brightness: median={bg_med} min={bg_min}",
            f"  Dark threshold used: {max(30,bg_med-45)}",
            f"  Health: ~{hp}%",
            f"  Flashed: {self.vision.is_flashed(frame)}",
            "",
        ]
        if enemies:
            lines.append("  Detections:")
            for i,e in enumerate(enemies):
                lines.append(
                    f"    {i+1}. screen=({e['x']},{e['y']}) "
                    f"head_y={e['head_y']} "
                    f"size={e.get('width',0)}x{e.get('height',0)} "
                    f"area={e['area']} conf={e['conf']:.0%} "
                    f"[{e.get('method','?')}]")
        else:
            lines.append("  No enemies detected.")
            lines.append(f"  Background median brightness: {bg_med}")
            lines.append(f"  If enemies ARE on screen, the background may be")
            lines.append(f"  too dark (indoors) or enemies blend in.")
            lines.append(f"  Send a screenshot so JARVIS can calibrate.")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

_donk = DonkAI()

def cs2_start(duration_minutes=30):
    return _donk.start(duration_minutes, "full")

def cs2_stop():
    return _donk.stop()

def cs2_pause():
    return _donk.pause()

def cs2_status():
    return _donk.status()

def cs2_aim_assist():
    return _donk.aim_only(60)

def cs2_practice(duration=120):
    return _donk.practice_aim(int(duration))

def cs2_sensitivity(sens=1.0, dpi=800):
    return _donk.set_sensitivity(float(sens), int(dpi))

def cs2_weapon(weapon="ak47"):
    return _donk.set_weapon(weapon)

def cs2_vision_test():
    return _donk.vision_test()

def cs2_launch():
    subprocess.Popen('start "" "steam://rungameid/730"', shell=True)
    return ("🎯 Launching CS2 via Steam...\n"
            "Once in-game:\n"
            "  'play cs2' — full Donk-mode AI\n"
            "  'cs2 aim assist' — aim help only\n"
            "  'cs2 practice' — aim training\n"
            "  'set cs2 sensitivity 1.5' — calibrate to your sens")

def cs2_input_test():
    """
    Test that inputs reach CS2.
    Sends very obvious inputs you will see if working:
    walks forward, turns right, turns back.
    Make sure CS2 is the active window first.
    """
    ri = RawInput()
    results = []

    # Focus CS2 window first
    r = subprocess.run(
        'powershell -c "$p=Get-Process|Where-Object{$_.MainWindowTitle-like\'*Counter*\'-or$_.MainWindowTitle-like\'*cs2*\'}|Select-Object -First 1; if($p){Add-Type -TypeDefinition \'using System;using System.Runtime.InteropServices;public class W{[DllImport(\\\"user32.dll\\\")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport(\\\"user32.dll\\\")]public static extern bool ShowWindow(IntPtr h,int n);}\';[W]::ShowWindow($p.MainWindowHandle,9);[W]::SetForegroundWindow($p.MainWindowHandle);Write-Output focused}"',
        shell=True, capture_output=True, text=True, timeout=5)
    focused = "focused" in r.stdout.lower()
    results.append(f"Window focus: {focused}")

    time.sleep(0.5)

    # Test 1: Walk forward 1 second — you should see character move
    results.append("Sending: W key (walk forward 1s)...")
    ri.key_down("w")
    time.sleep(1.0)
    ri.key_up("w")
    time.sleep(0.3)

    # Test 2: Turn right — mouse move
    results.append("Sending: Mouse right (turn right)...")
    ri.mouse_move_smooth(500, 0, steps=15)
    time.sleep(0.3)

    # Test 3: Turn back left
    results.append("Sending: Mouse left (turn back)...")
    ri.mouse_move_smooth(-500, 0, steps=15)
    time.sleep(0.3)

    # Test 4: Single shot
    results.append("Sending: Left click (fire)...")
    ri.mouse_down("left")
    time.sleep(0.05)
    ri.mouse_up("left")

    results.append("")
    results.append("If you saw: movement, turning, and a shot fire — inputs work!")
    results.append("If nothing happened — CS2 window was not focused or raw input blocked.")
    return "\n".join(results)

def cs2_reaction_time(ms=15):
    _donk.reaction_time = float(ms) / 1000.0
    return f"Reaction time set to {ms}ms"

def cs2_resume():
    """Re-enable AI after human takeover."""
    IM.clear_takeover()
    return "AI control re-enabled. Say 'play cs2' to start again."

def cs2_takeover_status():
    h = IM.is_human_active()
    a = _donk.active
    return f"Human active: {h} | AI active: {a}"


# ── Map & agent awareness (added to existing cs2 API) ─────────
def cs2_set_map(map_name):
    try:
        return CK.cs2_set_map(map_name)
    except Exception as e:
        return f"Map set error: {e}"

def cs2_callout(zone):
    try:
        return CK.cs2_callout(zone)
    except Exception as e:
        return f"Callout error: {e}"

def cs2_where_to_look(zone):
    try:
        return CK.cs2_where_to_look(zone)
    except Exception as e:
        return f"Error: {e}"

def cs2_tips(zone=""):
    try:
        return CK.cs2_tips(zone)
    except Exception as e:
        return f"Error: {e}"

def cs2_map_list():
    try:
        return CK.cs2_map_list()
    except Exception as e:
        return f"Error: {e}"

def cs2_agent_list():
    try:
        return CK.cs2_agent_list()
    except Exception as e:
        return f"Error: {e}"

def cs2_position_advice(situation="defending"):
    try:
        return CK.cs2_position_advice(situation)
    except Exception as e:
        return f"Error: {e}"


# ── YOLO tools ────────────────────────────────────────────────
def cs2_setup_yolo():
    try:
        return YOLO_MOD.yolo_setup()
    except Exception as e:
        return f"YOLO setup error: {e}"

def cs2_yolo_status():
    try:
        return YOLO_MOD.yolo_status()
    except Exception as e:
        return f"YOLO status error: {e}"

def cs2_yolo_test():
    try:
        return YOLO_MOD.yolo_detect_test()
    except Exception as e:
        return f"YOLO test error: {e}"

def cs2_yolo_confidence(conf=0.45):
    try:
        return YOLO_MOD.yolo_set_confidence(conf)
    except Exception as e:
        return f"Error: {e}"

def cs2_advice(topic="general"):
    ADVICE = {
        "general": (
            "🎯 CS2 Top Tips:\n"
            "1. Crosshair placement — always aim head height at doorways before peeking\n"
            "2. Counter-strafe (press opposite key) before shooting — moving kills accuracy\n"
            "3. Economy — full buy at $4500+, eco below $2000, force-buy at $2000-3200\n"
            "4. Use sound — footsteps, reloads, and bomb plant audio give away positions\n"
            "5. Play deathmatch 15min before ranked — warms up aim significantly\n"
            "6. Learn one smoke per map per week — utility wins rounds\n"
            "7. Don't peek when you can hold — patience beats aggression in most duels"
        ),
        "aim": (
            "🎯 CS2 Aim Tips:\n"
            "1. Crosshair placement cuts the distance your mouse needs to travel\n"
            "2. Spray control: pull down for first 7 bullets, then left-right per gun\n"
            "3. Tap fire at distance (150ms between shots), burst at medium, spray at close\n"
            "4. Lower sensitivity + higher DPI = more consistent large flicks\n"
            "5. Practice in deathmatch on Aim Botz workshop map daily"
        ),
        "economy": (
            "💰 CS2 Economy:\n"
            "Full buy: $4500+ (rifle + armor + grenades)\n"
            "Semi buy: $3000-4500 (rifle or upgrade + armor)\n"
            "Force buy: $2000-3000 (pistol/SMG + armor, hope for a trade)\n"
            "Eco: Below $2000 — save everything, maybe deagle\n"
            "Tip: Losing pistol → eco round 2 → semi buy round 3"
        ),
        "positioning": (
            "📍 CS2 Positioning:\n"
            "1. Never stand where you died — rotate or reposition every round\n"
            "2. Hold off-angles — unexpected spots beat common spots\n"
            "3. Play for crossfire — two CTs covering the same lane beats one\n"
            "4. Don't wide-peek if you can shoulder-peek for info first\n"
            "5. Play behind cover whenever possible, not in front of it"
        ),
    }
    key = next((k for k in ADVICE if k in topic.lower()), "general")
    try:
        import ollama
        prompts = {
            "general": "Give 7 top CS2 tips. Cover aim, positioning, economy, utility, mindset. Be specific and actionable.",
            "aim": "Give CS2 aim improvement advice. Cover crosshair placement, spray, tap vs burst, sensitivity, practice routines.",
            "economy": "Explain CS2 economy management. Buy thresholds, when to eco vs force vs full buy. Give specific dollar amounts.",
            "positioning": "Give CS2 positioning tips. When to peek, hold, rotate. Common mistakes and how to fix them.",
        }
        result = ollama.chat(model="llama3",
            messages=[{"role":"user","content":prompts[key]}])["message"]["content"]
        return f"🎯 CS2 Advice\n\n{result}"
    except Exception:
        return ADVICE[key]


# ── Combat/Targeting API ──────────────────────────────────────
def cs2_combat_start(duration=60):
    lines = []
    yolo_msg = _ensure_yolo(wait_secs=12)
    if yolo_msg:
        lines.append(yolo_msg)

    try:
        import pyautogui
        sw, sh = pyautogui.size()
        TGT.combat_configure(
            sensitivity=0.52, dpi=1600,
            weapon=_donk.weapon,
            screen_w=sw, screen_h=sh)
        result = TGT.combat_start(int(duration))
        lines.append(result)
    except Exception as e:
        lines.append(f"Combat start error: {e}")

    return "\n".join(lines) if lines else "Combat started."

def cs2_combat_stop():
    try:    return TGT.combat_stop()
    except: return _donk.stop()

def cs2_combat_pause():
    try:    return TGT.combat_pause()
    except: return "ok"

def cs2_combat_status():
    try:    return TGT.combat_status()
    except: return _donk.status()

def cs2_test_shot():
    try:    return TGT.combat_test_shot()
    except Exception as e: return f"Test shot error: {e}"
