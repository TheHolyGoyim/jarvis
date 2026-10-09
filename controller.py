"""
controller.py — JARVIS Hardware Controller Integration
Detects all connected input devices and emulates a real Xbox 360 controller
at the HID/driver level using ViGEm Bus Driver.
"""

import os, sys, time, json, subprocess, threading, ctypes
try:
    import input_monitor as IM
    import focus_monitor as FM
except Exception:
    class _IM:
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
from pathlib import Path

DATA_DIR = Path.home() / "Documents" / "JARVIS"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# DEVICE DETECTION
# ─────────────────────────────────────────────────────────────

def list_connected_devices():
    """List all HID and input devices connected to the PC."""
    lines = ["🎮 Connected Input Devices:\n"]

    # Method 1: WMI — all HID devices
    result = subprocess.run(
        'powershell -c "Get-PnpDevice | Where-Object {$_.Class -in @(\'HIDClass\',\'Xbox Peripherals\',\'XboxComposite\',\'USB\',\'Bluetooth\')} | Where-Object {$_.Status -eq \'OK\'} | Select-Object FriendlyName,Class,DeviceID | Format-Table -AutoSize -Wrap"',
        shell=True, capture_output=True, text=True, timeout=15
    )
    if result.stdout.strip():
        lines.append("HID / Input Devices:")
        for line in result.stdout.strip().split('\n'):
            if line.strip() and not line.startswith('-') and not line.startswith('F'):
                lines.append(f"  {line.strip()}")

    # Method 2: DirectInput devices via PowerShell
    result2 = subprocess.run(
        'powershell -c "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SystemInformation]::MonitorCount"',
        shell=True, capture_output=True, text=True, timeout=5
    )

    # Method 3: Check for Xbox controllers specifically
    xbox_check = subprocess.run(
        'powershell -c "Get-PnpDevice | Where-Object {$_.FriendlyName -like \'*Xbox*\' -or $_.FriendlyName -like \'*Controller*\' -or $_.FriendlyName -like \'*Gamepad*\' -or $_.FriendlyName -like \'*HID*\'} | Select-Object FriendlyName,Status | Format-Table -AutoSize"',
        shell=True, capture_output=True, text=True, timeout=10
    )
    lines.append("\nControllers / Gamepads:")
    if xbox_check.stdout.strip():
        for line in xbox_check.stdout.strip().split('\n'):
            if line.strip() and not line.startswith('-') and not line.startswith('F'):
                lines.append(f"  {line.strip()}")
    else:
        lines.append("  No controllers detected via PnP")

    # Method 4: xinput check
    xinput = subprocess.run(
        'powershell -c "1..4 | ForEach-Object { $id = $_; try { Add-Type -TypeDefinition \'using System; using System.Runtime.InteropServices; public class XInput { [DllImport(\"xinput1_4.dll\")] public static extern int XInputGetState(int i, IntPtr s); }\'; $p=[System.Runtime.InteropServices.Marshal]::AllocHGlobal(20); $r=[XInput]::XInputGetState($id-1,$p); if($r -eq 0){Write-Output \"XInput Controller $id: CONNECTED\"} } catch {} }"',
        shell=True, capture_output=True, text=True, timeout=8
    )
    if "CONNECTED" in xinput.stdout:
        lines.append("\nXInput Controllers (physical):")
        for line in xinput.stdout.strip().split('\n'):
            if "CONNECTED" in line:
                lines.append(f"  🎮 {line.strip()}")

    # Method 5: ViGEm status
    vigem_check = subprocess.run(
        'sc query ViGEmBus',
        shell=True, capture_output=True, text=True, timeout=5
    )
    lines.append("\nViGEm Bus Driver (virtual controller):")
    if "RUNNING" in vigem_check.stdout:
        lines.append("  ✅ ViGEm Bus: RUNNING — virtual controllers ready")
    elif "STOPPED" in vigem_check.stdout:
        lines.append("  ⚠️  ViGEm Bus: STOPPED — run 'install vigem' to start")
    else:
        lines.append("  ❌ ViGEm Bus: NOT INSTALLED")
        lines.append("  → Say 'install vigem' to install it (required for game control)")

    return "\n".join(lines)


def install_vigem():
    """Install ViGEm Bus Driver — needed for virtual Xbox controller."""
    lines = ["🔧 Installing ViGEm Bus Driver...\n"]

    # Method 1: pip install vgamepad (installs ViGEm automatically)
    r = subprocess.run(
        "pip install vgamepad --quiet",
        shell=True, capture_output=True, text=True, timeout=60
    )
    lines.append(f"pip install vgamepad: {'OK' if r.returncode == 0 else r.stderr[:100]}")

    # Method 2: Try to start ViGEm service if already installed
    subprocess.run("sc start ViGEmBus", shell=True, capture_output=True)

    # Method 3: Download ViGEm installer if not present
    vigem_check = subprocess.run(
        'sc query ViGEmBus', shell=True, capture_output=True, text=True
    )
    if "RUNNING" not in vigem_check.stdout and "STOPPED" not in vigem_check.stdout:
        lines.append("\nViGEm not found. Downloading installer...")
        try:
            import urllib.request
            url = "https://github.com/nefarius/ViGEmBus/releases/latest/download/ViGEmBus_Setup_x64.exe"
            dest = str(Path.home() / "Downloads" / "ViGEmBus_Setup_x64.exe")
            urllib.request.urlretrieve(url, dest)
            subprocess.Popen(f'"{dest}"', shell=True)
            lines.append(f"✅ Installer downloaded and opened: {dest}")
            lines.append("Complete the installation, then restart JARVIS.")
        except Exception as e:
            lines.append(f"Download failed: {e}")
            lines.append("Manual install: https://github.com/nefarius/ViGEmBus/releases/latest")
    else:
        lines.append("✅ ViGEm Bus found!")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# VIRTUAL XBOX 360 CONTROLLER
# ─────────────────────────────────────────────────────────────

class VirtualXbox:
    """
    Creates a virtual Xbox 360 controller via ViGEm Bus.
    Games see this as a real physical Xbox controller (HID device).
    """

    def __init__(self):
        self.pad = None
        self.connected = False
        self._init()

    def _init(self):
        try:
            import vgamepad as vg
            self.pad = vg.VX360Gamepad()
            self.vg  = vg
            self.connected = True
            # Immediately update to register device
            self.pad.update()
            print("[JARVIS] Virtual Xbox 360 controller connected as HID device")
        except Exception as e:
            self.connected = False
            print(f"[JARVIS] Virtual controller unavailable: {e}")
            print("[JARVIS] Run: pip install vgamepad  (or say 'install vigem')")

    def _check(self):
        if not self.connected:
            return False, "Virtual controller not connected. Say 'install vigem' first."
        return True, None

    # ── Buttons ───────────────────────────────────────────────

    def press(self, button, duration=0.1):
        ok, err = self._check()
        if not ok: return err
        IM.notify_ai_input()
        try:
            import vgamepad as vg
            BTN = {
                "a":      vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "b":      vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "x":      vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "y":      vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "lb":     vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "rb":     vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "start":  vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                "back":   vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                "select": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                "up":     vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
                "down":   vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                "left":   vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
                "right":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
                "ls":     vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                "rs":     vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
                "guide":  vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
            }
            btn = BTN.get(button.lower())
            if not btn:
                return f"Unknown button: {button}. Valid: {', '.join(BTN.keys())}"
            self.pad.press_button(button=btn)
            self.pad.update()
            time.sleep(duration)
            self.pad.release_button(button=btn)
            self.pad.update()
            return f"Xbox {button.upper()} pressed"
        except Exception as e:
            return f"Button error: {e}"

    def hold(self, button, duration=1.0):
        return self.press(button, duration)

    def trigger(self, side="right", value=255, duration=0.2):
        """Press a trigger. value 0-255."""
        ok, err = self._check()
        if not ok: return err
        try:
            val = int(value)
            if side.lower() in ("right", "rt"):
                self.pad.right_trigger(value=val)
            else:
                self.pad.left_trigger(value=val)
            self.pad.update()
            time.sleep(duration)
            if side.lower() in ("right", "rt"):
                self.pad.right_trigger(value=0)
            else:
                self.pad.left_trigger(value=0)
            self.pad.update()
            return f"{side.upper()} trigger ({val}/255) for {duration}s"
        except Exception as e:
            return f"Trigger error: {e}"

    # ── Sticks ────────────────────────────────────────────────

    def stick(self, side="left", x=0.0, y=0.0, duration=0.5):
        """
        Move analog stick. x/y range: -1.0 to 1.0
        y positive = up/forward, y negative = down/back
        x positive = right,      x negative = left
        """
        ok, err = self._check()
        if not ok: return err
        try:
            xv = int(max(-1.0, min(1.0, x)) * 32767)
            yv = int(max(-1.0, min(1.0, y)) * 32767)
            if side.lower() == "left":
                self.pad.left_joystick(x_value=xv, y_value=yv)
            else:
                self.pad.right_joystick(x_value=xv, y_value=yv)
            self.pad.update()
            time.sleep(duration)
            if side.lower() == "left":
                self.pad.left_joystick(x_value=0, y_value=0)
            else:
                self.pad.right_joystick(x_value=0, y_value=0)
            self.pad.update()
            return f"{side} stick ({x:.2f},{y:.2f}) for {duration:.2f}s"
        except Exception as e:
            return f"Stick error: {e}"

    def stick_hold(self, side="left", x=0.0, y=0.0):
        """Hold stick in position (non-blocking, call stick_release to stop)."""
        ok, err = self._check()
        if not ok: return err
        try:
            xv = int(max(-1.0, min(1.0, x)) * 32767)
            yv = int(max(-1.0, min(1.0, y)) * 32767)
            if side.lower() == "left":
                self.pad.left_joystick(x_value=xv, y_value=yv)
            else:
                self.pad.right_joystick(x_value=xv, y_value=yv)
            self.pad.update()
            return f"Holding {side} stick at ({x:.2f},{y:.2f})"
        except Exception as e:
            return f"Stick hold error: {e}"

    def stick_release(self, side="left"):
        """Release stick back to center."""
        ok, err = self._check()
        if not ok: return err
        try:
            if side.lower() == "left":
                self.pad.left_joystick(x_value=0, y_value=0)
            else:
                self.pad.right_joystick(x_value=0, y_value=0)
            self.pad.update()
            return f"{side} stick released to center"
        except Exception as e:
            return f"Release error: {e}"

    def reset(self):
        """Reset all inputs to neutral."""
        ok, err = self._check()
        if not ok: return err
        try:
            self.pad.left_joystick(x_value=0, y_value=0)
            self.pad.right_joystick(x_value=0, y_value=0)
            self.pad.left_trigger(value=0)
            self.pad.right_trigger(value=0)
            self.pad.update()
            return "Controller reset to neutral"
        except Exception as e:
            return f"Reset error: {e}"

    def rumble(self, left=128, right=128, duration=0.5):
        """Rumble/vibrate the controller."""
        ok, err = self._check()
        if not ok: return err
        try:
            self.pad.left_trigger(value=0)   # can't rumble directly but this confirms connection
            self.pad.update()
            return f"Rumble: L={left} R={right} for {duration}s (ViGEm limitation: rumble feedback only)"
        except Exception as e:
            return f"Rumble error: {e}"

    # ── High-level movement ───────────────────────────────────

    def move(self, direction, speed=1.0, duration=0.5):
        """Move in a direction using left stick."""
        DIRS = {
            "forward":   (0.0,  speed),
            "up":        (0.0,  speed),
            "back":      (0.0, -speed),
            "backward":  (0.0, -speed),
            "down":      (0.0, -speed),
            "left":      (-speed, 0.0),
            "right":     (speed,  0.0),
            "forward-left":  (-speed*0.7, speed*0.7),
            "forward-right": (speed*0.7,  speed*0.7),
        }
        x, y = DIRS.get(direction.lower(), (0.0, speed))
        return self.stick("left", x, y, duration)

    def look(self, direction, speed=0.8, duration=0.3):
        """Look/rotate camera using right stick."""
        DIRS = {
            "right":  (speed,  0.0),
            "left":   (-speed, 0.0),
            "up":     (0.0,    speed),
            "down":   (0.0,   -speed),
        }
        x, y = DIRS.get(direction.lower(), (speed, 0.0))
        return self.stick("right", x, y, duration)

    def jump(self):        return self.press("a", 0.1)
    def dive(self):        return self.press("b", 0.15)
    def grab(self):        return self.press("rb", 0.1)
    def shoot(self):       return self.trigger("right", 255, 0.15)
    def aim(self):         return self.trigger("left", 255, 0.1)
    def interact(self):    return self.press("x", 0.1)
    def ability(self):     return self.press("y", 0.1)
    def pause_game(self):  return self.press("start", 0.1)
    def sprint(self, direction="forward", duration=1.0):
        """Sprint — hold left stick fully in direction."""
        return self.move(direction, 1.0, duration)

    def combo(self, actions):
        """
        Execute a sequence of controller actions.
        actions: list of dicts with keys: type, and action-specific params
        Example: [{"type":"move","direction":"forward","duration":0.5},
                  {"type":"press","button":"a"},
                  {"type":"wait","duration":0.3}]
        """
        results = []
        for a in actions:
            t = a.get("type", "")
            try:
                if t == "press":      results.append(self.press(a["button"], a.get("duration", 0.1)))
                elif t == "trigger":  results.append(self.trigger(a.get("side","right"), a.get("value",255), a.get("duration",0.2)))
                elif t == "stick":    results.append(self.stick(a.get("side","left"), a.get("x",0), a.get("y",0), a.get("duration",0.5)))
                elif t == "move":     results.append(self.move(a["direction"], a.get("speed",1.0), a.get("duration",0.5)))
                elif t == "look":     results.append(self.look(a["direction"], a.get("speed",0.8), a.get("duration",0.3)))
                elif t == "jump":     results.append(self.jump())
                elif t == "dive":     results.append(self.dive())
                elif t == "grab":     results.append(self.grab())
                elif t == "wait":     time.sleep(a.get("duration", 0.3)); results.append("waited")
                elif t == "reset":    results.append(self.reset())
            except Exception as e:
                results.append(f"Action error: {e}")
        return "\n".join(results)

    def status(self):
        vigem = subprocess.run('sc query ViGEmBus', shell=True, capture_output=True, text=True)
        vigem_status = "RUNNING" if "RUNNING" in vigem.stdout else "STOPPED/NOT INSTALLED"
        return (f"🎮 Virtual Xbox Controller\n"
                f"  Connected: {self.connected}\n"
                f"  ViGEm Bus: {vigem_status}\n"
                f"  Games see this as: Xbox 360 Controller (HID)\n"
                f"  XInput port: 1 (first controller slot)")


# ─────────────────────────────────────────────────────────────
# FALL GUYS CONTROLLER PLAYER
# ─────────────────────────────────────────────────────────────

class FallGuysControllerPlayer:
    """
    Plays Fall Guys using the virtual Xbox controller.
    Game receives input as if from a real physical controller.
    """

    def __init__(self):
        self.pad    = VirtualXbox()
        self.active = False
        self.paused = False
        self._thread = None
        self.minigame = "unknown"
        self._log = []

    def _log_it(self, msg):
        self._log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self._log) > 300:
            self._log = self._log[-300:]

    def _focus_fallguys(self):
        """Bring Fall Guys window to front."""
        result = subprocess.run(
            '''powershell -c "
$titles = @('Fall Guys', 'FallGuys', 'fall guys')
foreach ($title in $titles) {
    $p = Get-Process | Where-Object {$_.MainWindowTitle -like \"*$title*\"} | Select-Object -First 1
    if ($p) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public class WinFocus {
    [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport(\"user32.dll\")] public static extern bool BringWindowToTop(IntPtr h);
}
'@
        $h = $p.MainWindowHandle
        [WinFocus]::ShowWindow($h, 9)
        [WinFocus]::BringWindowToTop($h)
        [WinFocus]::SetForegroundWindow($h)
        Write-Output 'focused'
        break
    }
}
"''',
            shell=True, capture_output=True, text=True, timeout=5
        )
        return 'focused' in result.stdout.lower()

    def start(self, duration_minutes=15):
        if not self.pad.connected:
            return ("❌ Virtual controller not connected!\n\n"
                    "Fix: Open Command Prompt and run:\n"
                    "  pip install vgamepad\n\n"
                    "Then restart JARVIS and try again.")

        self.active = True
        self.paused = False

        msg = (f"🫘 Fall Guys Controller AI Starting!\n"
               f"⏱️  Duration: {duration_minutes} minutes\n"
               f"🎮 Using: Virtual Xbox 360 Controller (HID)\n\n"
               f"⚡ RIGHT NOW:\n"
               f"  1. Make sure Fall Guys is open and in a match\n"
               f"  2. JARVIS will auto-focus the game in 5 seconds\n"
               f"  3. Controller inputs will start immediately\n\n"
               f"🛑 Say 'stop fall guys' to stop at any time")

        IM.clear_takeover()
        FM.clear_callbacks()
        FM.start(["Fall Guys", "FallGuys"])

        def _on_human():
            self.active = False
            self.pad.reset()
            self._log_it("Human takeover — controller released")

        FM.on_focus_lost(lambda t: (self.pad.reset(), self._log_it(f"Tabbed out — controller paused")))

        IM.register_takeover_callback(_on_human)

        def _run():
            for i in range(5, 0, -1):
                if not self.active: return
                time.sleep(1)

            IM.set_ai_active(True)
            focused = FM.focus_game(["Fall Guys", "FallGuys"])
            self._log_it(f"Starting. Fall Guys focused: {focused}")
            self._log_it(f"Window focus: {focused}")

            # Small rumble to confirm controller is working
            if self.pad.connected:
                self.pad.press("a", 0.05)  # brief A press to confirm connection
                time.sleep(0.2)
                self.pad.reset()

            # Start the game loop
            self._game_loop(duration_minutes * 60)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return msg

    def _game_loop(self, duration_sec):
        """Main AI game loop using controller input."""
        import random
        start = time.time()
        action_count = 0
        last_refocus = 0

        while self.active and (time.time() - start) < duration_sec:
            if self.paused:
                self.pad.reset()
                time.sleep(0.5)
                continue

            try:
                # ── Human takeover check ─────────────────────
                if IM.is_human_active():
                    self.pad.reset()
                    self.active = False
                    self._log_it("Human takeover — AI stopped")
                    break

                # ── Focus check — pause if tabbed out ────────
                if not FM.is_game_focused():
                    self.pad.reset()
                    self._log_it("Tabbed out — pausing controller")
                    while self.active and not FM.is_game_focused():
                        time.sleep(0.25)
                    if self.active:
                        self._log_it("Back in game — resuming")
                    continue

                # Re-focus every 20 seconds
                if time.time() - last_refocus > 20:
                    self._focus_fallguys()
                    last_refocus = time.time()

                # Decision making — adaptive based on action count
                r = random.random()

                # Phase-based strategy (cycles through movement patterns)
                phase = (action_count // 20) % 6

                if phase == 0:
                    # Sprint forward
                    if r < 0.7:
                        self.pad.move("forward", 1.0, random.uniform(0.3, 0.8))
                    elif r < 0.85:
                        self.pad.jump()
                        time.sleep(0.1)
                        self.pad.move("forward", 1.0, 0.3)
                    else:
                        self.pad.dive()

                elif phase == 1:
                    # Navigate with turns
                    if r < 0.5:
                        self.pad.move("forward", 1.0, random.uniform(0.2, 0.5))
                    elif r < 0.65:
                        self.pad.move("left", 0.8, random.uniform(0.2, 0.4))
                        self.pad.move("forward", 1.0, 0.3)
                    elif r < 0.8:
                        self.pad.move("right", 0.8, random.uniform(0.2, 0.4))
                        self.pad.move("forward", 1.0, 0.3)
                    else:
                        self.pad.jump()

                elif phase == 2:
                    # Jump-heavy (platforming sections)
                    if r < 0.4:
                        self.pad.move("forward", 1.0, 0.3)
                        time.sleep(0.05)
                        self.pad.jump()
                    elif r < 0.6:
                        self.pad.jump()
                        time.sleep(0.15)
                        self.pad.move("forward", 1.0, 0.4)
                    elif r < 0.75:
                        self.pad.move("forward", 1.0, 0.5)
                    else:
                        # Jump dive combo — good for crossing gaps
                        self.pad.move("forward", 1.0, 0.2)
                        self.pad.jump()
                        time.sleep(0.2)
                        self.pad.dive()

                elif phase == 3:
                    # Grab-heavy (good for team games and grabbing others)
                    if r < 0.5:
                        self.pad.move("forward", 1.0, 0.4)
                    elif r < 0.7:
                        self.pad.grab()
                        time.sleep(0.1)
                        self.pad.move("forward", 1.0, 0.3)
                    elif r < 0.85:
                        self.pad.jump()
                    else:
                        self.pad.dive()

                elif phase == 4:
                    # Evasive — dodge side to side
                    if r < 0.4:
                        dir_ = random.choice(["left", "right"])
                        self.pad.move(dir_, 0.9, random.uniform(0.15, 0.35))
                        self.pad.move("forward", 1.0, 0.3)
                    elif r < 0.7:
                        self.pad.move("forward", 1.0, random.uniform(0.3, 0.6))
                    elif r < 0.85:
                        self.pad.jump()
                        time.sleep(0.1)
                        dir_ = random.choice(["left", "right"])
                        self.pad.move(dir_, 0.7, 0.2)
                    else:
                        self.pad.dive()

                elif phase == 5:
                    # Aggressive forward push
                    self.pad.move("forward", 1.0, random.uniform(0.4, 1.0))
                    if r < 0.3:
                        self.pad.jump()

                action_count += 1

                # Human-like timing variation
                time.sleep(random.uniform(0.05, 0.18))

            except Exception as e:
                self._log_it(f"Loop error: {e}")
                time.sleep(0.2)

        # Clean up
        self.pad.reset()
        self.active = False
        IM.set_ai_active(False)
        self._log_it("Session ended — controller reset")

    def stop(self):
        self.active = False
        self.pad.reset()
        return f"🛑 Fall Guys AI stopped. Actions taken: {len(self._log)}"

    def pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pad.reset()
        return f"{'⏸️ Paused' if self.paused else '▶️ Resumed'} — controller {'released' if self.paused else 'active'}"

    def status(self):
        return (f"🫘 Fall Guys Controller AI\n"
                f"  Active: {self.active}\n"
                f"  Paused: {self.paused}\n"
                f"  Controller: {self.pad.status()}\n"
                f"\nRecent actions:\n" +
                "\n".join(f"  {l}" for l in self._log[-6:]))

    def test(self):
        """Test controller by doing a small movement."""
        if not self.pad.connected:
            return ("❌ Controller not connected. Run: pip install vgamepad")
        focused = self._focus_fallguys()
        time.sleep(0.3)
        self.pad.move("forward", 1.0, 0.5)
        time.sleep(0.1)
        self.pad.jump()
        time.sleep(0.3)
        self.pad.reset()
        return (f"✅ Controller test sent!\n"
                f"  • Moved forward for 0.5s\n"
                f"  • Jumped\n"
                f"Window focused: {focused}\n\n"
                f"If your character moved and jumped in Fall Guys, the controller is working!")


# ─────────────────────────────────────────────────────────────
# GLOBAL INSTANCES
# ─────────────────────────────────────────────────────────────

_xbox     = VirtualXbox()
_fg_ctrl  = FallGuysControllerPlayer()

# ── Public API ────────────────────────────────────────────────

def ctrl_list_devices():                            return list_connected_devices()
def ctrl_install_vigem():                           return install_vigem()
def ctrl_status():                                  return _xbox.status()
def ctrl_press(button, duration=0.1):               return _xbox.press(button, duration)
def ctrl_trigger(side="right", value=255, duration=0.2): return _xbox.trigger(side, value, duration)
def ctrl_stick(side="left", x=0.0, y=0.0, duration=0.5): return _xbox.stick(side, x, y, duration)
def ctrl_move(direction, speed=1.0, duration=0.5): return _xbox.move(direction, speed, duration)
def ctrl_look(direction, speed=0.8, duration=0.3): return _xbox.look(direction, speed, duration)
def ctrl_jump():                                    return _xbox.jump()
def ctrl_dive():                                    return _xbox.dive()
def ctrl_grab():                                    return _xbox.grab()
def ctrl_shoot():                                   return _xbox.shoot()
def ctrl_reset():                                   return _xbox.reset()
def ctrl_combo(actions):                            return _xbox.combo(actions)

def fallguys_ctrl_start(duration_minutes=15):       return _fg_ctrl.start(duration_minutes)
def fallguys_ctrl_stop():                           return _fg_ctrl.stop()
def fallguys_ctrl_pause():                          return _fg_ctrl.pause()
def fallguys_ctrl_status():                         return _fg_ctrl.status()
def fallguys_ctrl_test():                           return _fg_ctrl.test()

# ── Initialize intelligent vision player ──────────────────────
try:
    import game_vision as GV
    GV.init_player(_xbox)
    HAS_VISION = True
except Exception as _ve:
    HAS_VISION = False

def fallguys_smart_start(duration_minutes=15):
    if HAS_VISION:
        return GV.fg_smart_start(duration_minutes)
    return fallguys_ctrl_start(duration_minutes)

def fallguys_smart_stop():
    if HAS_VISION: return GV.fg_smart_stop()
    return fallguys_ctrl_stop()

def fallguys_smart_pause():
    if HAS_VISION: return GV.fg_smart_pause()
    return fallguys_ctrl_pause()

def fallguys_smart_status():
    if HAS_VISION: return GV.fg_smart_status()
    return fallguys_ctrl_status()

def fallguys_vision_test():
    if HAS_VISION: return GV.fg_vision_test()
    return "Vision not available. Run: pip install opencv-python numpy"

def fallguys_stats():
    if HAS_VISION: return GV.fg_game_stats()
    return "No stats yet."

