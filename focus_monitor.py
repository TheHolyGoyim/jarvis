"""
focus_monitor.py — Window Focus Monitor
JARVIS only sends game inputs when the target game window is focused.
The moment the player clicks elsewhere, AI input pauses automatically.
The moment the player tabs back in, AI input resumes.
"""

import ctypes, time, threading, subprocess

_target_titles  = []   # Window titles we consider "in game"
_is_game_focused = False
_monitor_active  = False
_monitor_thread  = None
_pause_callbacks  = []  # Called when focus lost
_resume_callbacks = []  # Called when focus regained
_CHECK_INTERVAL   = 0.25  # Check every 250ms

def _get_active_window_title():
    """Get the title of the currently active window."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""

def _title_matches(title, targets):
    """Check if window title matches any target."""
    title_lower = title.lower()
    for t in targets:
        if t.lower() in title_lower:
            return True
    return False

def _monitor_loop():
    global _is_game_focused, _monitor_active
    was_focused = False

    while _monitor_active:
        try:
            active_title = _get_active_window_title()
            now_focused  = _title_matches(active_title, _target_titles)
            _is_game_focused = now_focused

            if was_focused and not now_focused:
                # Lost focus — pause AI
                for cb in _pause_callbacks:
                    try: cb(active_title)
                    except Exception: pass

            elif not was_focused and now_focused:
                # Regained focus — resume AI
                for cb in _resume_callbacks:
                    try: cb(active_title)
                    except Exception: pass

            was_focused = now_focused

        except Exception:
            pass

        time.sleep(_CHECK_INTERVAL)

def start(target_window_titles):
    """
    Start monitoring. target_window_titles is a list of strings
    that should appear in the game window title.
    E.g. ["Counter-Strike", "cs2"] or ["Fall Guys"]
    """
    global _target_titles, _monitor_active, _monitor_thread
    _target_titles = target_window_titles
    _monitor_active = True

    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _monitor_thread.start()

def stop():
    global _monitor_active
    _monitor_active = False

def is_game_focused():
    return _is_game_focused

def on_focus_lost(callback):
    """Register callback for when player tabs out."""
    _pause_callbacks.append(callback)

def on_focus_gained(callback):
    """Register callback for when player tabs back in."""
    _resume_callbacks.append(callback)

def clear_callbacks():
    _pause_callbacks.clear()
    _resume_callbacks.clear()

def get_active_title():
    return _get_active_window_title()

def wait_for_focus(timeout=30):
    """Block until game window is focused, or timeout."""
    start_t = time.time()
    while not _is_game_focused:
        if time.time() - start_t > timeout:
            return False
        time.sleep(0.25)
    return True

def focus_game(titles):
    """Try to bring game window to foreground."""
    for title in titles:
        r = subprocess.run(
            f'powershell -c "$p=Get-Process|Where-Object{{$_.MainWindowTitle-like\'*{title}*\'}}|Select-Object -First 1; if($p){{Add-Type -TypeDefinition \'using System;using System.Runtime.InteropServices;public class W{{[DllImport(\\"user32.dll\\")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport(\\"user32.dll\\")]public static extern bool ShowWindow(IntPtr h,int n);}}\';[W]::ShowWindow($p.MainWindowHandle,9);[W]::SetForegroundWindow($p.MainWindowHandle);Write-Output focused}}"',
            shell=True, capture_output=True, text=True, timeout=5
        )
        if "focused" in r.stdout.lower():
            time.sleep(0.3)
            return True
    return False
