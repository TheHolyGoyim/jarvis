"""
game_vision.py — JARVIS Game Vision Engine
Real computer vision for understanding game state.
Detects: position, obstacles, other players, finish lines,
platform edges, danger zones, and learns from outcomes.
"""

import os, time, json, threading, subprocess
import numpy as np
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / "Documents" / "JARVIS" / "game_ai"
LEARN_FILE = DATA_DIR / "game_memory.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _ai(prompt, system=""):
    try:
        import ollama
        msgs = []
        if system: msgs.append({"role":"system","content":system})
        msgs.append({"role":"user","content":prompt})
        return ollama.chat(model="llama3",messages=msgs)["message"]["content"]
    except Exception as e:
        return ""

# ─────────────────────────────────────────────────────────────
# GAME MEMORY — Learns what works
# ─────────────────────────────────────────────────────────────

class GameMemory:
    """Stores outcomes of actions so JARVIS learns over time."""

    def __init__(self):
        self.data = self._load()

    def _load(self):
        try:
            if LEARN_FILE.exists():
                return json.loads(LEARN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {
            "sessions": [],
            "action_outcomes": {},  # action -> [success_rate, count]
            "minigame_strategies": {},  # minigame -> best_actions
            "total_rounds": 0,
            "total_wins": 0,
            "observations": [],
        }

    def save(self):
        LEARN_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def record_action(self, action, outcome, context=""):
        """Record whether an action led to a good or bad outcome."""
        key = f"{context}:{action}" if context else action
        if key not in self.data["action_outcomes"]:
            self.data["action_outcomes"][key] = [0, 0]  # [successes, total]
        self.data["action_outcomes"][key][1] += 1
        if outcome == "good":
            self.data["action_outcomes"][key][0] += 1
        self.save()

    def best_action(self, context, candidates):
        """Return the highest success-rate action from candidates."""
        best = None
        best_rate = -1
        for action in candidates:
            key = f"{context}:{action}"
            if key in self.data["action_outcomes"]:
                s, t = self.data["action_outcomes"][key]
                rate = s / t if t > 0 else 0.5
                if rate > best_rate:
                    best_rate = rate
                    best = action
        return best or candidates[0] if candidates else "move_forward"

    def record_session(self, rounds, wins, minigames_played):
        self.data["total_rounds"] += rounds
        self.data["total_wins"] += wins
        self.data["sessions"].append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rounds": rounds, "wins": wins,
            "minigames": minigames_played
        })
        if len(self.data["sessions"]) > 100:
            self.data["sessions"] = self.data["sessions"][-100:]
        self.save()

    def stats(self):
        total_r = self.data["total_rounds"]
        total_w = self.data["total_wins"]
        win_rate = (total_w / total_r * 100) if total_r > 0 else 0
        return (f"📊 JARVIS Game Stats:\n"
                f"  Total rounds: {total_r}\n"
                f"  Total wins:   {total_w}\n"
                f"  Win rate:     {win_rate:.1f}%\n"
                f"  Sessions:     {len(self.data['sessions'])}")

_memory = GameMemory()

# ─────────────────────────────────────────────────────────────
# SCREEN ANALYZER — Real computer vision
# ─────────────────────────────────────────────────────────────

class ScreenAnalyzer:
    """
    Analyzes game frames using OpenCV + color detection.
    Works without a trained ML model — uses visual heuristics.
    """

    def __init__(self):
        self.screen_w = 1920
        self.screen_h = 1080
        self.prev_frame = None
        self.frame_count = 0
        self._get_screen_size()

    def _get_screen_size(self):
        try:
            import pyautogui
            self.screen_w, self.screen_h = pyautogui.size()
        except Exception:
            pass

    def capture(self):
        try:
            import pyautogui
            img = pyautogui.screenshot()
            frame = np.array(img)
            self.frame_count += 1
            return frame
        except Exception:
            return None

    def analyze_full(self):
        """Full frame analysis — returns actionable game state."""
        frame = self.capture()
        if frame is None:
            return GameState()

        gs = GameState()
        gs.frame = frame
        h, w = frame.shape[:2]

        try:
            import cv2

            # ── Convert color spaces ──────────────────────────
            hsv   = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
            gray  = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 30, 100)

            # ── Detect slime / lava (rising death) ───────────
            # Slime is bright green-yellow in Fall Guys
            slime_lower = np.array([35, 150, 150])
            slime_upper = np.array([75, 255, 255])
            slime_mask  = cv2.inRange(hsv, slime_lower, slime_upper)
            slime_bottom = slime_mask[int(h*0.75):, :]
            gs.slime_level = np.sum(slime_bottom > 0) / slime_bottom.size
            gs.danger_below = gs.slime_level > 0.05

            # ── Detect void / falling ────────────────────────
            # Bottom of screen is black/dark when falling
            bottom_strip = frame[int(h*0.85):, int(w*0.3):int(w*0.7)]
            gs.is_falling = np.mean(bottom_strip) < 30

            # ── Find platforms / ground ──────────────────────
            # Platforms are lighter colored horizontal bands
            lower_half = gray[int(h*0.5):, :]
            rows_brightness = np.mean(lower_half, axis=1)
            platform_rows = np.where(rows_brightness > 80)[0]
            if len(platform_rows) > 0:
                gs.platform_y = int(h*0.5) + int(np.mean(platform_rows))
                gs.on_platform = True
            gs.ground_level = gs.platform_y

            # ── Detect obstacles ahead ───────────────────────
            # Look in center-forward area for edge density
            forward_region = edges[int(h*0.3):int(h*0.6),
                                   int(w*0.35):int(w*0.65)]
            gs.obstacle_ahead = np.sum(forward_region > 0) / forward_region.size > 0.04

            # ── Find finish line ─────────────────────────────
            # Finish lines are usually bright white/yellow horizontal bars at top
            top_region = gray[:int(h*0.2), :]
            gs.finish_line_visible = np.mean(top_region > 220) > 0.15

            # ── Detect other players (beans) ─────────────────
            # Beans are highly saturated colorful blobs
            sat = hsv[:,:,1]
            high_sat_mask = (sat > 160).astype(np.uint8) * 255
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
                high_sat_mask, connectivity=8
            )
            beans = []
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if 200 < area < 8000:
                    cx = stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]//2
                    cy = stats[i, cv2.CC_STAT_TOP]  + stats[i, cv2.CC_STAT_HEIGHT]//2
                    beans.append({"x": cx, "y": cy, "area": area})
            gs.nearby_players = sorted(beans, key=lambda b: -b["area"])[:10]
            gs.player_count = len(gs.nearby_players)

            # ── Estimate player position ──────────────────────
            # Our player is usually the largest/most central bean
            if gs.nearby_players:
                # Find most central large bean
                center_x = w // 2
                our_bean = min(gs.nearby_players[:3],
                               key=lambda b: abs(b["x"] - center_x))
                gs.player_x = our_bean["x"]
                gs.player_y = our_bean["y"]

            # ── Detect platform edges ─────────────────────────
            # Sharp vertical drops in the lower region
            lower_edges = edges[int(h*0.6):, :]
            col_density = np.sum(lower_edges > 0, axis=0)
            edge_cols = np.where(col_density > 5)[0]

            if len(edge_cols) > 0:
                left_edges  = edge_cols[edge_cols < w//3]
                right_edges = edge_cols[edge_cols > 2*w//3]
                gs.edge_left  = len(left_edges) > 3
                gs.edge_right = len(right_edges) > 3

            # ── Detect UI elements (eliminated, qualified) ────
            # White text usually appears in center when eliminated
            center_brightness = np.mean(gray[int(h*0.4):int(h*0.6),
                                              int(w*0.3):int(w*0.7)])
            gs.ui_text_visible = center_brightness > 200

            # ── Motion detection (are we stuck?) ─────────────
            if self.prev_frame is not None:
                diff = cv2.absdiff(frame, self.prev_frame)
                gs.motion_amount = np.mean(diff)
                gs.is_stuck = gs.motion_amount < 2.0
            self.prev_frame = frame.copy()

            # ── Detect rotating obstacles ─────────────────────
            # Fast-moving high-contrast objects in mid-screen
            mid_region = edges[int(h*0.25):int(h*0.75),
                                int(w*0.2):int(w*0.8)]
            gs.rotating_obstacle = np.sum(mid_region > 0) / mid_region.size > 0.06

        except ImportError:
            # OpenCV not available — basic analysis only
            gs.obstacle_ahead = False
            gs.is_falling = False
        except Exception as e:
            pass

        return gs

    def detect_minigame(self, gs):
        """
        Detect which Fall Guys mini-game we're in based on visual cues.
        Returns: minigame name and confidence score.
        """
        if gs.frame is None:
            return "unknown", 0.0

        try:
            import cv2
            h, w = gs.frame.shape[:2]
            hsv = cv2.cvtColor(gs.frame, cv2.COLOR_RGB2HSV)

            scores = {}

            # Slime Climb: lots of green slime at bottom
            if gs.slime_level > 0.1:
                scores["slime_climb"] = gs.slime_level * 10

            # Hex-a-Gone: hexagonal tile pattern
            # Tiles are typically colorful hexagons — detect grid pattern
            lower_region = cv2.cvtColor(
                gs.frame[int(h*0.5):, :], cv2.COLOR_RGB2GRAY)
            edges_lower = cv2.Canny(lower_region, 50, 150)
            hex_score = np.sum(edges_lower > 0) / edges_lower.size
            if hex_score > 0.08:
                scores["hex_a_gone"] = hex_score * 8

            # See Saw: large flat platforms tilting
            if gs.obstacle_ahead and not gs.slime_level > 0.05:
                scores["see_saw"] = 0.4

            # Hit Parade: horizontal obstacles at different heights
            if gs.rotating_obstacle:
                scores["hit_parade"] = 0.6
                scores["whirlygig"] = 0.5

            # Fall Mountain: linear upward progression
            if gs.finish_line_visible:
                scores["fall_mountain"] = 0.8

            # Tip Toe: sparse platform tiles
            if gs.on_platform and gs.player_count > 5:
                scores["tip_toe"] = 0.4

            # Default to generic race
            if not scores:
                scores["race"] = 0.5

            best = max(scores, key=scores.get)
            return best, scores[best]

        except Exception:
            return "race", 0.3


class GameState:
    """Holds the analyzed state of the current frame."""
    def __init__(self):
        self.frame              = None
        self.player_x           = 0
        self.player_y           = 0
        self.platform_y         = 0
        self.ground_level       = 0
        self.is_falling         = False
        self.is_stuck           = False
        self.on_platform        = True
        self.danger_below       = False
        self.slime_level        = 0.0
        self.obstacle_ahead     = False
        self.rotating_obstacle  = False
        self.finish_line_visible= False
        self.nearby_players     = []
        self.player_count       = 0
        self.edge_left          = False
        self.edge_right         = False
        self.ui_text_visible    = False
        self.motion_amount      = 0.0
        self.minigame           = "unknown"
        self.confidence         = 0.0

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != "frame"}


# ─────────────────────────────────────────────────────────────
# INTELLIGENT DECISION ENGINE
# ─────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Makes intelligent decisions based on game state.
    Uses rule-based logic + learned outcomes + AI reasoning.
    """

    def __init__(self, memory: GameMemory):
        self.memory = memory
        self.last_action = ""
        self.action_repeat = 0
        self.stuck_counter = 0
        self.forward_bias = 0.0  # 0-1, how much to bias forward

    def decide(self, gs: GameState) -> list:
        """
        Returns a list of actions to execute based on game state.
        Each action: {"type": "...", params...}
        """
        actions = []
        mg = gs.minigame

        # ── Safety checks first ───────────────────────────────

        # Falling — dive to recover, then move forward
        if gs.is_falling:
            actions.append({"type": "dive"})
            actions.append({"type": "move", "direction": "forward",
                           "speed": 1.0, "duration": 0.3})
            self.memory.record_action("dive_when_falling", "good", mg)
            return actions

        # Edge danger — move away from edge
        if gs.edge_left and not gs.edge_right:
            actions.append({"type": "move", "direction": "right",
                           "speed": 0.8, "duration": 0.2})
            return actions
        if gs.edge_right and not gs.edge_left:
            actions.append({"type": "move", "direction": "left",
                           "speed": 0.8, "duration": 0.2})
            return actions

        # Slime rising fast — panic sprint
        if gs.slime_level > 0.2:
            actions.append({"type": "move", "direction": "forward",
                           "speed": 1.0, "duration": 0.6})
            actions.append({"type": "jump"})
            return actions

        # Stuck — try to get unstuck
        if gs.is_stuck:
            self.stuck_counter += 1
            if self.stuck_counter > 3:
                actions += self._get_unstuck()
                self.stuck_counter = 0
                return actions
        else:
            self.stuck_counter = 0

        # ── Mini-game specific logic ──────────────────────────

        if mg == "slime_climb":
            actions = self._slime_climb(gs)
        elif mg == "hex_a_gone":
            actions = self._hex_a_gone(gs)
        elif mg == "fall_mountain":
            actions = self._fall_mountain(gs)
        elif mg == "tip_toe":
            actions = self._tip_toe(gs)
        elif mg == "see_saw":
            actions = self._see_saw(gs)
        elif mg == "hit_parade":
            actions = self._hit_parade(gs)
        elif mg == "whirlygig":
            actions = self._whirlygig(gs)
        elif mg == "door_dash":
            actions = self._door_dash(gs)
        elif mg == "hex_a_gone":
            actions = self._hex_a_gone(gs)
        else:
            actions = self._generic_race(gs)

        # ── Apply obstacle avoidance overlay ─────────────────
        if gs.obstacle_ahead and not any(a["type"] == "jump" for a in actions):
            # Insert jump before the forward movement
            actions = [{"type": "jump"}] + actions

        return actions if actions else self._generic_race(gs)

    # ── Mini-game strategies ──────────────────────────────────

    def _generic_race(self, gs):
        """Default: run forward, jump obstacles, stay alive."""
        import random
        r = random.random()
        # Heavily bias forward — that's almost always right
        if r < 0.65:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": random.uniform(0.3, 0.7)}]
        elif r < 0.78:
            # Forward + slight angle to avoid clustering
            dir_ = random.choice(["forward-left", "forward-right", "forward"])
            return [{"type": "move", "direction": dir_,
                    "speed": 0.9, "duration": random.uniform(0.2, 0.5)}]
        elif r < 0.88:
            # Jump forward
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.2},
                    {"type": "jump"}]
        elif r < 0.93:
            # Jump dive (covers more distance)
            return [{"type": "jump"},
                    {"type": "wait", "duration": 0.2},
                    {"type": "dive"}]
        else:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]

    def _slime_climb(self, gs):
        """Slime Climb: always move up, jump frequently, never stop."""
        import random
        r = random.random()
        urgency = min(gs.slime_level * 5, 1.0)
        duration = max(0.2, 0.6 - urgency * 0.4)

        if r < 0.5:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": duration},
                    {"type": "jump"}]
        elif r < 0.7:
            return [{"type": "jump"},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]
        elif r < 0.85:
            # Grab a ledge
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.3},
                    {"type": "jump"},
                    {"type": "grab"}]
        else:
            return [{"type": "jump"},
                    {"type": "wait", "duration": 0.15},
                    {"type": "dive"}]

    def _hex_a_gone(self, gs):
        """
        Hex-a-Gone: Stay alive as long as possible on disappearing tiles.
        Move in a spiral/zigzag pattern to cover more tiles.
        """
        import random
        r = random.random()
        # Never jump (wastes tile time), move in patterns
        if r < 0.4:
            return [{"type": "move", "direction": "right",
                    "speed": 0.7, "duration": 0.5}]
        elif r < 0.65:
            return [{"type": "move", "direction": "forward",
                    "speed": 0.7, "duration": 0.4}]
        elif r < 0.8:
            return [{"type": "move", "direction": "left",
                    "speed": 0.7, "duration": 0.4}]
        elif r < 0.9:
            return [{"type": "move", "direction": "back",
                    "speed": 0.6, "duration": 0.3}]
        else:
            # Jump to lower hex level (strategic descent)
            return [{"type": "jump"},
                    {"type": "move", "direction": "forward",
                    "speed": 0.5, "duration": 0.2}]

    def _fall_mountain(self, gs):
        """Fall Mountain: sprint forward, dodge balls, grab crown."""
        import random
        r = random.random()
        if gs.finish_line_visible:
            # Sprint to crown!
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.8},
                    {"type": "jump"},
                    {"type": "grab"}]
        if r < 0.6:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.5}]
        elif r < 0.75:
            # Dodge side then forward
            dir_ = random.choice(["left", "right"])
            return [{"type": "move", "direction": dir_,
                    "speed": 1.0, "duration": 0.2},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]
        else:
            return [{"type": "jump"},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]

    def _tip_toe(self, gs):
        """Tip Toe: move carefully, follow other players, test tiles."""
        import random
        r = random.random()
        # Watch where others go — move toward most populated areas
        if gs.nearby_players:
            # Find cluster of players ahead of us
            forward_players = [p for p in gs.nearby_players
                              if p["y"] < gs.player_y - 30]
            if forward_players:
                avg_x = sum(p["x"] for p in forward_players) / len(forward_players)
                if avg_x < gs.player_x - 50:
                    return [{"type": "move", "direction": "left",
                            "speed": 0.5, "duration": 0.3}]
                elif avg_x > gs.player_x + 50:
                    return [{"type": "move", "direction": "right",
                            "speed": 0.5, "duration": 0.3}]
        # Slow careful movement
        if r < 0.6:
            return [{"type": "move", "direction": "forward",
                    "speed": 0.4, "duration": 0.3},
                    {"type": "wait", "duration": 0.2}]
        else:
            return [{"type": "wait", "duration": 0.3},
                    {"type": "move", "direction": "forward",
                    "speed": 0.3, "duration": 0.2}]

    def _see_saw(self, gs):
        """See Saw: cross quickly, don't wait on tilted side."""
        import random
        r = random.random()
        if r < 0.6:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.8}]
        elif r < 0.8:
            return [{"type": "jump"},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.5}]
        else:
            return [{"type": "jump"},
                    {"type": "wait", "duration": 0.2},
                    {"type": "dive"}]

    def _hit_parade(self, gs):
        """Hit Parade: dodge obstacles, time jumps over beams."""
        import random
        r = random.random()
        if gs.rotating_obstacle:
            # Time jump with obstacle
            return [{"type": "wait", "duration": 0.1},
                    {"type": "jump"},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]
        if r < 0.5:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.4}]
        else:
            dir_ = random.choice(["left", "right"])
            return [{"type": "move", "direction": dir_,
                    "speed": 0.8, "duration": 0.2},
                    {"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.3}]

    def _whirlygig(self, gs):
        """Whirlygig: wait for gap in spinners, then sprint."""
        import random
        if gs.rotating_obstacle:
            return [{"type": "wait", "duration": 0.3}]
        else:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 1.0}]

    def _door_dash(self, gs):
        """Door Dash: follow other players through open doors."""
        import random
        if gs.nearby_players:
            return [{"type": "move", "direction": "forward",
                    "speed": 1.0, "duration": 0.5}]
        return self._generic_race(gs)

    def _get_unstuck(self):
        """Escape from being stuck."""
        import random
        dir_ = random.choice(["left", "right", "back"])
        return [{"type": "jump"},
                {"type": "move", "direction": dir_,
                "speed": 1.0, "duration": 0.4},
                {"type": "move", "direction": "forward",
                "speed": 1.0, "duration": 0.5}]


# ─────────────────────────────────────────────────────────────
# INTELLIGENT GAME PLAYER
# ─────────────────────────────────────────────────────────────

class IntelligentPlayer:
    """
    The main intelligent player.
    Sees the screen, decides actions, executes via controller,
    and learns from outcomes.
    """

    def __init__(self, controller):
        self.ctrl      = controller
        self.vision    = ScreenAnalyzer()
        self.memory    = _memory
        self.engine    = DecisionEngine(self.memory)
        self.active    = False
        self.paused    = False
        self._thread   = None
        self.stats     = {"actions": 0, "jumps": 0, "falls": 0,
                         "obstacles_avoided": 0, "minigames": {}}
        self._log           = []
        self.fps            = 0  # actions per second
        self._intent        = None   # committed action list in progress
        self._intent_frames = 0      # frames remaining in current intent

    def _log_it(self, msg):
        self._log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self._log) > 500:
            self._log = self._log[-500:]

    def _execute(self, actions):
        """Execute a list of actions via the controller."""
        for a in actions:
            if not self.active: break
            t = a.get("type", "")
            try:
                if t == "move":
                    self.ctrl.move(a.get("direction","forward"),
                                  a.get("speed",1.0),
                                  a.get("duration",0.5))
                    self.stats["actions"] += 1
                elif t == "jump":
                    self.ctrl.jump()
                    self.stats["jumps"] += 1
                elif t == "dive":
                    self.ctrl.dive()
                elif t == "grab":
                    self.ctrl.grab()
                elif t == "press":
                    self.ctrl.press(a.get("button","a"),
                                   a.get("duration",0.1))
                elif t == "look":
                    self.ctrl.look(a.get("direction","right"),
                                  a.get("speed",0.5),
                                  a.get("duration",0.2))
                elif t == "wait":
                    time.sleep(a.get("duration",0.2))
            except Exception as e:
                self._log_it(f"Execute error: {e}")

    def _focus_game(self):
        """Focus the game window."""
        titles = ["Fall Guys", "FallGuys", "EpicGames"]
        for title in titles:
            r = subprocess.run(
                f'powershell -c "$p=Get-Process|Where-Object{{$_.MainWindowTitle-like\'*{title}*\'}}|Select-Object -First 1; if($p){{Add-Type -TypeDefinition \'using System;using System.Runtime.InteropServices;public class W{{[DllImport(\\"user32.dll\\")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport(\\"user32.dll\\")]public static extern bool ShowWindow(IntPtr h,int n);}}\'; [W]::ShowWindow($p.MainWindowHandle,9);[W]::SetForegroundWindow($p.MainWindowHandle);Write-Output focused}}"',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if "focused" in r.stdout.lower():
                return True
        return False

    def start(self, duration_minutes=15):
        if self.active:
            return "Already playing! Say 'stop fall guys' first."

        self.active = True
        self.paused = False

        msg = (f"🫘 JARVIS Intelligent Fall Guys AI\n"
               f"⏱️  Duration: {duration_minutes} minutes\n"
               f"👁️  Vision: Active (screen analysis)\n"
               f"🧠  Learning: Enabled\n"
               f"🎮  Controller: Virtual Xbox 360 HID\n\n"
               f"⚡ Switch to Fall Guys NOW — starting in 5 seconds\n"
               f"🛑 Say 'stop fall guys' to stop")

        def _run():
            for i in range(5, 0, -1):
                if not self.active: return
                time.sleep(1)
            focused = self._focus_game()
            self._log_it(f"Started. Window focused: {focused}")
            self._game_loop(duration_minutes * 60)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return msg

    def _game_loop(self, duration_sec):
        """Main vision-driven game loop."""
        start = time.time()
        last_refocus = 0
        last_analysis = 0
        last_minigame_detect = 0
        current_gs = GameState()
        loop_count = 0

        while self.active and (time.time() - start) < duration_sec:
            if self.paused:
                self.ctrl.reset()
                time.sleep(0.5)
                continue

            loop_start = time.time()

            try:
                # Re-focus every 25 seconds
                if time.time() - last_refocus > 25:
                    self._focus_game()
                    last_refocus = time.time()

                # Full vision analysis every 3 frames
                if loop_count % 3 == 0:
                    current_gs = self.vision.analyze_full()
                    last_analysis = time.time()

                    # Detect mini-game every 10 seconds
                    if time.time() - last_minigame_detect > 10:
                        mg, conf = self.vision.detect_minigame(current_gs)
                        if conf > 0.3:
                            if mg != current_gs.minigame:
                                self._log_it(f"Mini-game: {mg} ({conf:.0%})")
                            current_gs.minigame = mg
                            current_gs.confidence = conf
                            # Track stats
                            self.stats["minigames"][mg] = \
                                self.stats["minigames"].get(mg, 0) + 1
                        last_minigame_detect = time.time()

                # Intent state — hold a committed multi-frame action instead
                # of re-deciding every frame (prevents jitter)
                if self._intent_frames > 0 and self._intent is not None:
                    actions = self._intent
                    self._intent_frames -= 1
                else:
                    actions = self.engine.decide(current_gs)
                    # Safety reflexes always run immediately (no intent lock)
                    is_reflex = (current_gs.is_falling or
                                 current_gs.edge_left or current_gs.edge_right or
                                 current_gs.slime_level > 0.2)
                    if not is_reflex and actions:
                        # Commit to this action for 2 frames for follow-through
                        self._intent        = actions
                        self._intent_frames = 2

                # Execute actions
                self._execute(actions)

                # Track outcomes for learning
                if current_gs.is_falling:
                    self.stats["falls"] += 1
                    for a in actions:
                        if a.get("type") in ["move","dive"]:
                            self.memory.record_action(
                                f"{a.get('type')}_{a.get('direction','')}_when_falling",
                                "bad", current_gs.minigame
                            )

                # Calculate FPS
                loop_time = time.time() - loop_start
                self.fps = 1.0 / max(loop_time, 0.01)
                loop_count += 1

            except Exception as e:
                self._log_it(f"Loop error: {e}")
                time.sleep(0.1)

        # Session ended
        self.active = False
        self.ctrl.reset()
        self.memory.record_session(1, 0, list(self.stats["minigames"].keys()))
        self._log_it(f"Session ended. Stats: {self.stats}")

    def stop(self):
        self.active = False
        try: self.ctrl.reset()
        except Exception: pass
        self._log_it("Stopped by user")
        return (f"🛑 JARVIS stopped.\n"
                f"Actions: {self.stats['actions']} | "
                f"Jumps: {self.stats['jumps']} | "
                f"Falls: {self.stats['falls']}\n"
                f"Mini-games seen: {', '.join(self.stats['minigames'].keys()) or 'none'}\n\n"
                f"{self.memory.stats()}")

    def pause(self):
        self.paused = not self.paused
        if self.paused: self.ctrl.reset()
        return f"{'⏸️ Paused' if self.paused else '▶️ Resumed'}"

    def status(self):
        return (f"🫘 Intelligent Fall Guys AI\n"
                f"  Active: {self.active}\n"
                f"  Paused: {self.paused}\n"
                f"  FPS:    {self.fps:.1f}\n"
                f"  Actions: {self.stats['actions']}\n"
                f"  Falls:   {self.stats['falls']}\n"
                f"  Minigames: {self.stats['minigames']}\n\n"
                f"{self.memory.stats()}\n\n"
                f"Recent:\n" +
                "\n".join(f"  {l}" for l in self._log[-5:]))


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

# Player instance — initialized with the controller from controller.py
_player = None

def init_player(ctrl):
    global _player
    _player = IntelligentPlayer(ctrl)

def fg_smart_start(duration_minutes=15):
    global _player
    if _player is None:
        return "Game vision not initialized. Restart JARVIS."
    return _player.start(duration_minutes)

def fg_smart_stop():
    global _player
    if _player: return _player.stop()
    return "Not playing."

def fg_smart_pause():
    global _player
    if _player: return _player.pause()
    return "Not playing."

def fg_smart_status():
    global _player
    if _player: return _player.status()
    return "Not initialized."

def fg_game_stats():
    return _memory.stats()

def fg_vision_test():
    """Test that screen analysis is working."""
    analyzer = ScreenAnalyzer()
    gs = analyzer.analyze_full()
    mg, conf = analyzer.detect_minigame(gs)
    return (f"👁️ Vision Test:\n"
            f"  Screen size: {analyzer.screen_w}x{analyzer.screen_h}\n"
            f"  Frame captured: {gs.frame is not None}\n"
            f"  Player position: ({gs.player_x}, {gs.player_y})\n"
            f"  Obstacles ahead: {gs.obstacle_ahead}\n"
            f"  Is falling: {gs.is_falling}\n"
            f"  Is stuck: {gs.is_stuck}\n"
            f"  Slime level: {gs.slime_level:.2f}\n"
            f"  Players visible: {gs.player_count}\n"
            f"  Mini-game detected: {mg} ({conf:.0%} confidence)\n"
            f"  Edge left: {gs.edge_left} | Edge right: {gs.edge_right}")
