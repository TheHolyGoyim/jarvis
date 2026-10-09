"""
fallguys_ai.py — JARVIS Fall Guys AI Player
Full autonomous player for Fall Guys via Epic Games.
Uses screen vision + AI decision making + keyboard/mouse/controller input.
"""

import os, sys, time, json, re, threading, subprocess, random
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / "Documents" / "JARVIS" / "game_ai" / "fallguys"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Epic Games paths — tries multiple common install locations
EPIC_PATHS = [
    r"D:\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
]
# Fall Guys launch URL — this is the correct Epic URI scheme
FALLGUYS_LAUNCH_URI = "com.epicgames.launcher://apps/0a2d9f6403244d12969e11da6713137b%3A6db3b9f0722c4df9866a42c59de3e494%3ASalt?action=launch&silent=true"
# Fallback: just search for Fall Guys in Epic launcher
FALLGUYS_SEARCH_URL = "com.epicgames.launcher://store/product/fall-guys"

def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def _focus_game_window():
    """Find Fall Guys window and bring it to focus."""
    # Method 1: Use PowerShell to find and focus Fall Guys window
    titles_to_try = ["Fall Guys", "FallGuys", "Fall_Guys", "EpicGamesLauncher"]
    for title in titles_to_try:
        result = _run(
            f'''powershell -c "
$p = Get-Process | Where-Object {{$_.MainWindowTitle -like '*{title}*'}} | Select-Object -First 1
if ($p) {{
    $hwnd = $p.MainWindowHandle
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class WinAPI {{ [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd); [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); }}' 
    [WinAPI]::ShowWindow($hwnd, 9)
    [WinAPI]::SetForegroundWindow($hwnd)
    Write-Output 'focused'
}} else {{
    Write-Output 'not found'
}}
"'''
        )
        if 'focused' in result.lower():
            time.sleep(0.5)
            return f"Focused: {title}"

    # Method 2: Use pygetwindow
    try:
        import pygetwindow as gw
        windows = gw.getAllTitles()
        for w_title in windows:
            if any(fg in w_title.lower() for fg in ['fall guys', 'fallguys']):
                win = gw.getWindowsWithTitle(w_title)[0]
                win.activate()
                time.sleep(0.5)
                return f"Focused via pygetwindow: {w_title}"
    except Exception:
        pass

    # Method 3: Alt+Tab to cycle to the game (last resort)
    try:
        import pyautogui
        pyautogui.hotkey('alt', 'tab')
        time.sleep(0.5)
        return "Used Alt+Tab to switch windows"
    except Exception:
        pass

    return "Could not focus game window - please click on Fall Guys manually"

def _test_input():
    """Test that inputs are actually being received."""
    try:
        import pyautogui
        # Move mouse slightly to confirm pyautogui works
        x, y = pyautogui.position()
        pyautogui.moveRel(1, 0)
        pyautogui.moveRel(-1, 0)
        return True
    except Exception:
        return False

def _ai(prompt, system=""):
    try:
        import ollama
        msgs = []
        if system:
            msgs.append({"role":"system","content":system})
        msgs.append({"role":"user","content":prompt})
        return ollama.chat(model="llama3", messages=msgs)["message"]["content"]
    except Exception as e:
        return f"(AI unavailable: {e})"

def _screenshot():
    try:
        import pyautogui
        from PIL import Image
        img = pyautogui.screenshot()
        path = DATA_DIR / f"frame_{datetime.now().strftime('%H%M%S%f')}.png"
        img.save(str(path))
        return path, img
    except Exception as e:
        return None, None

# ─────────────────────────────────────────────────────────────
# INPUT HANDLER
# ─────────────────────────────────────────────────────────────

class Input:
    """Unified input handler — keyboard/mouse or Xbox controller."""

    def __init__(self, mode="keyboard"):
        self.mode = mode
        self.gamepad = None
        if mode == "xbox":
            try:
                import vgamepad as vg
                self.gamepad = vg.VX360Gamepad()
                self.vg = vg
            except Exception:
                self.mode = "keyboard"

    # ── Keyboard/Mouse ────────────────────────────────────────
    def _key(self, key, duration=0.05):
        """Send key input using multiple methods for maximum compatibility."""
        # Map common key names
        key_map = {
            'space': 'space', 'ctrl': 'ctrl', 'shift': 'shift',
            'enter': 'return', 'esc': 'escape', 'escape': 'escape',
            'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
        }
        mapped_key = key_map.get(key.lower(), key.lower())

        # Method 1: keyboard library (works with most games)
        try:
            import keyboard as kb_lib
            kb_lib.press(mapped_key)
            time.sleep(max(duration, 0.05))
            kb_lib.release(mapped_key)
            return
        except Exception:
            pass

        # Method 2: pyautogui (fallback)
        try:
            import pyautogui
            pyautogui.keyDown(mapped_key)
            time.sleep(max(duration, 0.05))
            pyautogui.keyUp(mapped_key)
            return
        except Exception:
            pass

        # Method 3: ctypes SendInput (lowest level - works with DirectInput games)
        try:
            import ctypes
            VK_CODES = {
                'w':0x57,'a':0x41,'s':0x53,'d':0x44,'r':0x52,'f':0x46,
                'e':0x45,'q':0x51,'space':0x20,'ctrl':0x11,'shift':0x10,
                'return':0x0D,'escape':0x1B,'tab':0x09,
                'up':0x26,'down':0x28,'left':0x25,'right':0x27,
            }
            vk = VK_CODES.get(mapped_key)
            if vk:
                KEYEVENTF_KEYUP = 0x0002
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                time.sleep(max(duration, 0.05))
                ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass

    def _mouse_move(self, dx, dy):
        try:
            import pyautogui
            pyautogui.moveRel(dx, dy, duration=0.01)
        except Exception: pass

    def _mouse_click(self, btn="left"):
        try:
            import pyautogui
            pyautogui.click(button=btn)
        except Exception: pass

    # ── Xbox ──────────────────────────────────────────────────
    def _xbox_btn(self, btn, duration=0.1):
        if not self.gamepad: return self._key_fallback(btn)
        try:
            import vgamepad as vg
            bmap = {
                "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            }
            b = bmap.get(btn.lower())
            if b:
                self.gamepad.press_button(button=b)
                self.gamepad.update()
                time.sleep(duration)
                self.gamepad.release_button(button=b)
                self.gamepad.update()
        except Exception as e:
            self._key_fallback(btn)

    def _xbox_stick(self, stick="left", x=0.0, y=0.0, duration=0.5):
        if not self.gamepad:
            self._stick_kb_fallback(x, y, duration)
            return
        try:
            xv, yv = int(x*32767), int(y*32767)
            if stick == "left":
                self.gamepad.left_joystick(x_value=xv, y_value=yv)
            else:
                self.gamepad.right_joystick(x_value=xv, y_value=yv)
            self.gamepad.update()
            time.sleep(duration)
            if stick == "left":
                self.gamepad.left_joystick(x_value=0, y_value=0)
            else:
                self.gamepad.right_joystick(x_value=0, y_value=0)
            self.gamepad.update()
        except Exception:
            self._stick_kb_fallback(x, y, duration)

    def _key_fallback(self, btn):
        kb_map = {"a":"space","b":"ctrl","x":"e","y":"f",
                  "lb":"q","rb":"r","start":"enter","lt":"shift","rt":"mouse1"}
        key = kb_map.get(btn.lower(), btn)
        if key == "mouse1": self._mouse_click("left")
        else: self._key(key)

    def _stick_kb_fallback(self, x, y, duration):
        if y > 0.3:    self._key("w", duration)
        elif y < -0.3: self._key("s", duration)
        elif x > 0.3:  self._key("d", duration)
        elif x < -0.3: self._key("a", duration)

    # ── Game Actions ──────────────────────────────────────────
    def move_forward(self, duration=0.5):
        if self.mode == "xbox": self._xbox_stick("left", 0, 1, duration)
        else: self._key("w", duration)

    def move_back(self, duration=0.3):
        if self.mode == "xbox": self._xbox_stick("left", 0, -1, duration)
        else: self._key("s", duration)

    def move_left(self, duration=0.3):
        if self.mode == "xbox": self._xbox_stick("left", -1, 0, duration)
        else: self._key("a", duration)

    def move_right(self, duration=0.3):
        if self.mode == "xbox": self._xbox_stick("left", 1, 0, duration)
        else: self._key("d", duration)

    def jump(self):
        if self.mode == "xbox": self._xbox_btn("a", 0.1)
        else: self._key("space", 0.1)

    def dive(self):
        """Dive / ragdoll — crucial in Fall Guys."""
        if self.mode == "xbox": self._xbox_btn("rb", 0.1)
        else: self._key("ctrl", 0.15)

    def grab(self, hold=False):
        """Grab other players or objects."""
        if self.mode == "xbox": self._xbox_btn("rb", 0.5 if hold else 0.1)
        else: self._key("f", 0.5 if hold else 0.1)

    def look(self, dx, dy):
        if self.mode == "xbox": self._xbox_stick("right", dx/500, -dy/500, 0.1)
        else: self._mouse_move(dx, dy)

    def sprint(self, direction="forward", duration=1.0):
        """Sprint in a direction."""
        key_map = {"forward":"w","back":"s","left":"a","right":"d"}
        key = key_map.get(direction, "w")
        if self.mode == "xbox":
            stick_map = {"forward":(0,1),"back":(0,-1),"left":(-1,0),"right":(1,0)}
            x, y = stick_map.get(direction, (0,1))
            self._xbox_stick("left", x, y, duration)
        else:
            self._key(key, duration)

    def jump_dive(self):
        """Jump then dive — great for crossing gaps."""
        self.jump()
        time.sleep(0.2)
        self.dive()

    def strafe_jump(self, direction="right"):
        """Jump while strafing — useful for platforming."""
        import threading
        t = threading.Thread(target=self.jump, daemon=True)
        t.start()
        time.sleep(0.05)
        getattr(self, f"move_{direction}")(0.4)
        t.join()

    def navigate_to(self, dx, dy):
        """Move toward a relative position."""
        # Horizontal movement
        if abs(dx) > 50:
            if dx > 0: self.move_right(min(abs(dx)/200, 1.0))
            else: self.move_left(min(abs(dx)/200, 1.0))
        # Vertical movement (in screen space — forward/back)
        if abs(dy) > 50:
            if dy > 0: self.move_forward(min(abs(dy)/200, 1.0))
            else: self.move_back(min(abs(dy)/200, 1.0))

    def menu_select(self):
        if self.mode == "xbox": self._xbox_btn("a", 0.1)
        else: self._key("enter", 0.1)

    def menu_back(self):
        if self.mode == "xbox": self._xbox_btn("b", 0.1)
        else: self._key("escape", 0.1)


# ─────────────────────────────────────────────────────────────
# GAME STATE ANALYZER
# ─────────────────────────────────────────────────────────────

class FallGuysVision:
    """Analyzes Fall Guys screen state using color detection and AI."""

    def __init__(self):
        self.screen_w = 1920
        self.screen_h = 1080

    def get_screen_size(self):
        try:
            import pyautogui
            self.screen_w, self.screen_h = pyautogui.size()
        except Exception: pass

    def capture(self):
        return _screenshot()

    def analyze_state(self):
        """Determine current game state from screen."""
        path, img = self.capture()
        if not img: return {"state": "unknown"}

        try:
            import numpy as np
            frame = np.array(img)
            h, w = frame.shape[:2]

            state = {"state": "unknown", "width": w, "height": h}

            # Detect if we're in a round (lots of color activity)
            center_region = frame[h//3:2*h//3, w//3:2*w//3]
            color_variance = np.std(center_region)
            state["active"] = color_variance > 40

            # Try to detect finish line (often bright/white horizontal band)
            top_region = frame[:h//4, :]
            brightness = np.mean(top_region)
            state["finish_line_visible"] = brightness > 200

            # Detect if we're falling (character in air — center of screen is sky)
            mid_strip = frame[h//2-20:h//2+20, w//2-20:w//2+20]
            avg_color = np.mean(mid_strip, axis=(0,1))
            # Sky is usually blue-ish
            is_sky = avg_color[2] > avg_color[0] and avg_color[2] > 150
            state["in_air"] = is_sky

            # Detect other players nearby (skin tones / bean colors)
            state["players_nearby"] = self._count_beans(frame)

            # Detect obstacles (dark regions at player level)
            player_level = frame[h//2:3*h//4, :]
            dark_ratio = np.mean(player_level < 50) 
            state["obstacles_ahead"] = dark_ratio > 0.1

            return state

        except ImportError:
            return {"state": "active", "active": True}
        except Exception as e:
            return {"state": "error", "error": str(e)}

    def _count_beans(self, frame):
        """Count approximate number of other players (beans) visible."""
        try:
            import numpy as np
            import cv2
            # Fall Guys beans are very colorful — look for saturated blobs
            hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
            # High saturation mask
            sat_mask = hsv[:,:,1] > 150
            # Connected components
            sat_uint8 = sat_mask.astype('uint8') * 255
            num_labels, _ = cv2.connectedComponents(sat_uint8)
            return min(num_labels // 3, 20)  # rough estimate
        except Exception:
            return 0

    def detect_platform_edges(self, img):
        """Detect platform edges to avoid falling off."""
        try:
            import numpy as np
            import cv2
            frame = np.array(img)
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            h, w = edges.shape
            # Check bottom region for edges
            bottom = edges[3*h//4:, :]
            edge_density = np.sum(bottom > 0) / bottom.size
            return edge_density > 0.05
        except Exception:
            return False

    def ai_describe_screen(self):
        """Get AI description of current game state."""
        path, img = self.capture()
        if not path: return "Cannot capture screen."
        state = self.analyze_state()
        return _ai(
            f"""You are playing Fall Guys (the colorful battle royale party game).
Current screen analysis: {json.dumps(state, indent=2)}

Based on this data, what is likely happening in the game right now?
What is the best action to take? Be specific:
- Are we in a menu, loading, or actively playing?
- What mini-game/obstacle might we be facing?
- What exact movement should we make next?

Keep response under 100 words.""",
            system="You are an expert Fall Guys player AI."
        )


# ─────────────────────────────────────────────────────────────
# FALL GUYS MINI-GAME STRATEGIES
# ─────────────────────────────────────────────────────────────

class FallGuysStrategy:
    """AI strategies for different Fall Guys mini-games."""

    MINIGAME_STRATEGIES = {
        "door_dash": {
            "desc": "Run through doors — some are fake",
            "strategy": "Stay center-right, follow other players through open doors, dive through if unsure",
            "actions": [("sprint","forward",2.0), ("dive",), ("sprint","forward",1.0)]
        },
        "fall_mountain": {
            "desc": "Climb mountain to reach crown",
            "strategy": "Stay on the path, jump over rolling balls, grab crown immediately",
            "actions": [("sprint","forward",1.0), ("jump",), ("sprint","forward",0.5)]
        },
        "see_saw": {
            "desc": "Balance on seesaws across gap",
            "strategy": "Cross quickly, don't wait on tilted side, dive across if needed",
            "actions": [("sprint","forward",0.8), ("jump",), ("sprint","forward",0.5)]
        },
        "tip_toe": {
            "desc": "Find safe tiles — wrong tiles fall",
            "strategy": "Watch which tiles other players fall through, move carefully",
            "actions": [("move_forward",0.3), ("wait",0.5), ("move_forward",0.3)]
        },
        "hit_parade": {
            "desc": "Dodge obstacles and reach finish",
            "strategy": "Dodge side to side, time jumps over rotating beams",
            "actions": [("sprint","forward",1.0), ("jump",), ("move_right",0.3)]
        },
        "whirlygig": {
            "desc": "Navigate spinning obstacles",
            "strategy": "Time your run between spinner blades, sprint when clear",
            "actions": [("wait",0.5), ("sprint","forward",1.5), ("jump",)]
        },
        "team_game": {
            "desc": "Team-based objective game",
            "strategy": "Follow teammates, focus on objective not fighting",
            "actions": [("sprint","forward",1.0), ("jump",), ("grab",)]
        },
        "slime_climb": {
            "desc": "Climb while slime rises below",
            "strategy": "Move fast, always keep moving up, grab ledges",
            "actions": [("sprint","forward",1.0), ("jump",), ("sprint","forward",0.8)]
        },
        "hex_a_gone": {
            "desc": "Last one standing on disappearing tiles",
            "strategy": "Stay on tiles as long as possible, move in patterns",
            "actions": [("move_right",0.5), ("move_forward",0.5), ("move_left",0.5)]
        },
        "fall_ball": {
            "desc": "Soccer with giant balls",
            "strategy": "Stay in goal area, dive to block, rush ball when close",
            "actions": [("sprint","forward",0.5), ("dive",), ("sprint","back",0.5)]
        },
        "egg_scramble": {
            "desc": "Steal eggs into your team's basket",
            "strategy": "Grab eggs, run to basket, protect your eggs",
            "actions": [("sprint","forward",0.8), ("grab",), ("sprint","back",1.0)]
        },
        "royal_fumble": {
            "desc": "Hold the tail the longest",
            "strategy": "Chase the tail holder, grab immediately, run when you have it",
            "actions": [("sprint","forward",1.0), ("grab",), ("sprint","right",0.5)]
        },
    }

    def identify_minigame(self, screen_description):
        """AI identifies which mini-game is being played."""
        result = _ai(
            f"""Fall Guys mini-game detection.
Screen/state info: {screen_description}

Which Fall Guys mini-game is this most likely?
Options: door_dash, fall_mountain, see_saw, tip_toe, hit_parade, 
         whirlygig, team_game, slime_climb, hex_a_gone, fall_ball,
         egg_scramble, royal_fumble, unknown

Reply with ONLY the mini-game name.""",
            system="You identify Fall Guys mini-games."
        ).strip().lower()

        for key in self.MINIGAME_STRATEGIES:
            if key in result: return key
        return "unknown"

    def get_strategy(self, minigame):
        """Get strategy for a specific mini-game."""
        s = self.MINIGAME_STRATEGIES.get(minigame, {})
        if not s: return "Stay alive, keep moving forward, jump over obstacles!"
        return f"{s['desc']}\n\nStrategy: {s['strategy']}"

    def get_actions(self, minigame):
        """Get the action sequence for a mini-game."""
        s = self.MINIGAME_STRATEGIES.get(minigame, {})
        return s.get("actions", [("sprint","forward",1.0), ("jump",)])

    def adaptive_strategy(self, game_state, minigame="unknown"):
        """Generate adaptive strategy based on current state."""
        if minigame in self.MINIGAME_STRATEGIES:
            base = self.get_strategy(minigame)
        else:
            base = "General: move forward, jump obstacles, avoid edges"

        prompt = f"""Fall Guys game state: {json.dumps(game_state)}
Mini-game: {minigame}
Base strategy: {base}

Obstacles ahead: {game_state.get('obstacles_ahead', False)}
In air: {game_state.get('in_air', False)}
Players nearby: {game_state.get('players_nearby', 0)}

What single action should I take RIGHT NOW?
Reply with ONLY ONE of: move_forward, move_back, move_left, move_right, jump, dive, grab, sprint_forward, sprint_right, sprint_left, wait"""
        action = _ai(prompt, system="You are a Fall Guys expert AI.").strip().lower()
        # Clean up response
        valid = ["move_forward","move_back","move_left","move_right",
                 "jump","dive","grab","sprint_forward","sprint_right","sprint_left","wait"]
        for v in valid:
            if v in action: return v
        return "move_forward"


# ─────────────────────────────────────────────────────────────
# MAIN FALL GUYS PLAYER
# ─────────────────────────────────────────────────────────────

class FallGuysPlayer:
    """Full autonomous Fall Guys player."""

    def __init__(self, control_mode="keyboard"):
        self.inp      = Input(control_mode)
        self.vision   = FallGuysVision()
        self.strategy = FallGuysStrategy()
        self.active   = False
        self.paused   = False
        self._thread  = None
        self.control_mode = control_mode
        self.current_minigame = "unknown"
        self.stats = {"rounds_played":0,"eliminations":0,"wins":0,"actions_taken":0}
        self._log = []

    def _log_action(self, action):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {action}"
        self._log.append(entry)
        if len(self._log) > 200: self._log = self._log[-200:]

    def launch_game(self):
        """Launch Fall Guys via Epic Games Launcher."""
        lines = ["🎮 Launching Fall Guys via Epic Games..."]

        # Step 1: Make sure Epic Launcher is running
        epic_running = _run('tasklist /fi "imagename eq EpicGamesLauncher.exe" 2>nul | find /i "epic"')
        if "epic" not in epic_running.lower():
            # Try to find and launch Epic
            epic_launched = False
            for path in EPIC_PATHS:
                if Path(path).exists():
                    subprocess.Popen(f'"{path}"', shell=True)
                    lines.append(f"Starting Epic Games Launcher...")
                    time.sleep(10)
                    epic_launched = True
                    break
            if not epic_launched:
                # Epic might be installed elsewhere - try opening via Windows
                subprocess.Popen("start epicgameslauncher:", shell=True)
                lines.append("Opening Epic Games Launcher...")
                time.sleep(8)
        else:
            lines.append("Epic Games Launcher already running.")

        # Step 2: Launch Fall Guys using the URI scheme
        # Method 1: Direct URI launch (most reliable)
        try:
            subprocess.Popen(f'start "" "{FALLGUYS_LAUNCH_URI}"', shell=True)
            lines.append("Launching Fall Guys...")
        except Exception:
            # Method 2: Open Epic store page for Fall Guys
            subprocess.Popen(f'start "" "{FALLGUYS_SEARCH_URL}"', shell=True)
            lines.append("Opening Fall Guys in Epic launcher...")

        lines.append("")
        lines.append("⏳ Game should start in ~30-60 seconds.")
        lines.append("Once you see the Fall Guys menu, say:")
        lines.append("  'Play Fall Guys for 20 minutes' — to let JARVIS play")
        lines.append("  'Fall Guys advice' — for tips while you play yourself")
        return "\n".join(lines)

    def start_playing(self, duration_minutes=15):
        """Start autonomous gameplay loop."""
        if self.active:
            return "Already playing! Say 'stop fall guys' to stop first."
        self.active = True
        self.paused = False
        duration_sec = duration_minutes * 60

        result = [
            f"🫘 JARVIS Fall Guys AI Starting!",
            f"⏱️  Playing for {duration_minutes} minutes",
            f"🎮 Control mode: {self.control_mode}",
            "",
            f"⚡ IMPORTANT — Do these RIGHT NOW:",
            f"  1. Click on your Fall Guys window to make it active",
            f"  2. Make sure you are IN A MATCH (not in menus)",
            f"  3. JARVIS will auto-focus and start in 5 seconds",
            "",
            f"🛑 Emergency stop: move mouse to TOP-LEFT corner of screen",
            f"💬 Say 'pause fall guys' to pause anytime",
        ]
        def _countdown():
            # Give user 5 seconds to switch to Fall Guys
            for i in range(5, 0, -1):
                if not self.active:
                    return
                time.sleep(1)

            if not self.active:
                return

            # Focus the game window
            focus_result = _focus_game_window()
            self._log_action(f"Window focus: {focus_result}")
            time.sleep(0.5)

            # Test that inputs work
            if not _test_input():
                self._log_action("WARNING: Input test failed")

            # Start playing
            self._main_loop(duration_sec)
        self._thread = threading.Thread(target=_countdown, daemon=True)
        self._thread.start()
        return "\n".join(result)

    def _main_loop(self, duration_sec):
        """Core gameplay loop."""
        start = time.time()
        action_count = 0
        re_queue_attempts = 0

        last_focus_time = 0
        while self.active and (time.time() - start) < duration_sec:
            if self.paused:
                time.sleep(0.5)
                continue

            try:
                # Re-focus game window every 30 seconds
                if time.time() - last_focus_time > 30:
                    _focus_game_window()
                    last_focus_time = time.time()

                # Phase 1: Analyze screen
                state = self.vision.analyze_state()

                # Phase 2: Handle menus / loading screens
                if not state.get("active", True):
                    self._handle_menu()
                    time.sleep(1)
                    continue

                # Phase 3: Get optimal action
                if action_count % 30 == 0:
                    # Every 30 actions, re-identify the mini-game
                    desc = self.vision.ai_describe_screen()
                    self.current_minigame = self.strategy.identify_minigame(desc)
                    self._log_action(f"Mini-game identified: {self.current_minigame}")

                # Phase 4: Execute action
                action = self.strategy.adaptive_strategy(state, self.current_minigame)
                self._execute_action(action)
                self._log_action(action)
                action_count += 1
                self.stats["actions_taken"] += 1

                # Phase 5: Randomize timing to look more human
                time.sleep(random.uniform(0.08, 0.25))

            except Exception as e:
                self._log_action(f"Error: {e}")
                time.sleep(0.5)

        self.active = False
        self._log_action("Session ended")

    def _execute_action(self, action):
        """Execute a named action."""
        action = action.lower().strip()
        if action == "move_forward":    self.inp.move_forward(random.uniform(0.2, 0.6))
        elif action == "move_back":     self.inp.move_back(random.uniform(0.2, 0.4))
        elif action == "move_left":     self.inp.move_left(random.uniform(0.2, 0.4))
        elif action == "move_right":    self.inp.move_right(random.uniform(0.2, 0.4))
        elif action == "jump":          self.inp.jump()
        elif action == "dive":          self.inp.dive()
        elif action == "grab":          self.inp.grab()
        elif action == "sprint_forward":self.inp.sprint("forward", random.uniform(0.5, 1.5))
        elif action == "sprint_right":  self.inp.sprint("right", random.uniform(0.3, 0.8))
        elif action == "sprint_left":   self.inp.sprint("left", random.uniform(0.3, 0.8))
        elif action == "jump_dive":     self.inp.jump_dive()
        elif action == "wait":          time.sleep(random.uniform(0.1, 0.4))

        # Occasionally throw in survival moves
        r = random.random()
        if r < 0.05:    self.inp.jump()           # random jump
        elif r < 0.08:  self.inp.look(random.randint(-150,150), 0)  # look around

    def _handle_menu(self):
        """Handle menu screens — queue up, accept matches, etc."""
        import pyautogui
        try:
            screen_w, screen_h = pyautogui.size()
        except Exception:
            screen_w, screen_h = 1920, 1080

        # Try to click common menu positions
        # "Play" button — usually center of screen
        center_x, center_y = screen_w // 2, screen_h // 2
        try:
            pyautogui.click(center_x, center_y)
            time.sleep(0.3)
        except Exception: pass
        # Also press Enter/Space which usually advances menus
        self.inp.menu_select()
        time.sleep(0.5)

    def stop(self):
        self.active = False
        if self._thread: self._thread.join(timeout=3)
        return f"🛑 Fall Guys AI stopped. Stats: {json.dumps(self.stats)}"

    def pause(self):
        self.paused = not self.paused
        return f"{'⏸️ Paused' if self.paused else '▶️ Resumed'} Fall Guys AI."

    def get_status(self):
        return (f"🫘 Fall Guys AI Status\n"
                f"  Active: {self.active}\n"
                f"  Paused: {self.paused}\n"
                f"  Mini-game: {self.current_minigame}\n"
                f"  Actions taken: {self.stats['actions_taken']}\n"
                f"  Control mode: {self.control_mode}\n"
                f"\nRecent actions:\n" +
                "\n".join(f"  {l}" for l in self._log[-5:]))

    def get_advice(self, situation=""):
        """Get real-time advice without taking over control."""
        state = self.vision.analyze_state()
        desc = self.vision.ai_describe_screen()
        minigame = self.strategy.identify_minigame(desc)
        strategy = self.strategy.get_strategy(minigame)
        return (f"🫘 Fall Guys Advice\n\n"
                f"Detected: {minigame.replace('_',' ').title()}\n\n"
                f"{strategy}\n\n"
                f"Right now: {self.strategy.adaptive_strategy(state, minigame).replace('_',' ')}")

    def set_control_mode(self, mode):
        """Switch between keyboard and Xbox controller."""
        self.control_mode = mode
        self.inp = Input(mode)
        return f"✅ Control mode set to: {mode}"

    def teach_minigame(self, minigame_name):
        """Get detailed AI coaching for a specific mini-game."""
        key = minigame_name.lower().replace(" ","_")
        if key in self.strategy.MINIGAME_STRATEGIES:
            s = self.strategy.MINIGAME_STRATEGIES[key]
            return f"🎓 {minigame_name.replace('_',' ').title()} Guide\n\n{s['desc']}\n\nStrategy: {s['strategy']}"
        # Ask AI for advice
        result = _ai(f"""Give expert tips for the Fall Guys mini-game: {minigame_name}
Cover: what the objective is, best movement strategy, common mistakes to avoid, pro tips.
Be specific and practical.""",
            system="You are an expert Fall Guys player.")
        return f"🎓 {minigame_name} Tips\n\n{result}"


# ─────────────────────────────────────────────────────────────
# GLOBAL INSTANCE & PUBLIC API
# ─────────────────────────────────────────────────────────────

_fg = FallGuysPlayer(control_mode="keyboard")

def fallguys_launch():
    return _fg.launch_game()

def fallguys_start(duration_minutes=15, control_mode="keyboard"):
    _fg.set_control_mode(control_mode)
    return _fg.start_playing(duration_minutes)

def fallguys_stop():
    return _fg.stop()

def fallguys_pause():
    return _fg.pause()

def fallguys_status():
    return _fg.get_status()

def fallguys_advice(situation=""):
    return _fg.get_advice(situation)

def fallguys_teach(minigame):
    return _fg.teach_minigame(minigame)

def fallguys_set_controller(mode="xbox"):
    return _fg.set_control_mode(mode)

def fallguys_analyze():
    state = _fg.vision.analyze_state()
    desc = _fg.vision.ai_describe_screen()
    return f"👁️ Fall Guys Screen Analysis\n\n{desc}\n\nRaw state: {json.dumps(state, indent=2)}"

def fallguys_minigame_list():
    lines = ["🫘 Fall Guys Mini-Games I Know:\n"]
    for k, v in FallGuysStrategy.MINIGAME_STRATEGIES.items():
        lines.append(f"  • {k.replace('_',' ').title()}: {v['desc']}")
    lines.append("\nSay 'teach me [mini-game name]' for detailed strategy!")
    return "\n".join(lines)


def fallguys_test_input():
    """Test that keyboard input is working - presses W briefly."""
    focus = _focus_game_window()
    time.sleep(0.5)
    p = FallGuysPlayer()
    p.inp.move_forward(0.3)
    return (f"Input test complete!\n"
            f"Window focus: {focus}\n"
            f"Sent: W key (forward) for 0.3 seconds\n"
            f"If your character moved forward in Fall Guys, inputs are working!")
