"""
input_monitor.py — Human Input Detection
Detects when the real player starts using keyboard/mouse
and immediately halts all AI inputs.
Acts as a kill switch for any AI automation.
"""

import ctypes, time, threading, sys
from pathlib import Path

# ── State ─────────────────────────────────────────────────────
_ai_active      = False   # Is AI currently controlling input?
_human_detected = False   # Did we detect a human input?
_monitor_thread = None
_callbacks      = []      # Functions to call when human takes over
_callbacks_lock = threading.Lock()
_last_ai_input  = 0       # Timestamp of last AI input
_GRACE_PERIOD   = 0.15    # Seconds after AI input before human check

# ── Windows input hook ────────────────────────────────────────

WH_KEYBOARD_LL = 13
WH_MOUSE_LL    = 14
WM_KEYDOWN     = 0x0100
WM_MOUSEMOVE   = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.c_uint32),
        ("scanCode",    ctypes.c_uint32),
        ("flags",       ctypes.c_uint32),
        ("time",        ctypes.c_uint32),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",          ctypes.c_longlong),
        ("mouseData",   ctypes.c_uint32),
        ("flags",       ctypes.c_uint32),
        ("time",        ctypes.c_uint32),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

_kb_hook   = None
_ms_hook   = None
_kb_proc   = None
_ms_proc   = None

def _on_keyboard(nCode, wParam, lParam):
    global _human_detected, _ai_active
    if nCode >= 0 and wParam == WM_KEYDOWN and _ai_active:
        # Check grace period — ignore inputs right after AI sent one
        if time.time() - _last_ai_input > _GRACE_PERIOD:
            _trigger_human_takeover("keyboard")
    return ctypes.windll.user32.CallNextHookEx(_kb_hook, nCode, wParam, lParam)

def _on_mouse(nCode, wParam, lParam):
    global _human_detected, _ai_active
    if nCode >= 0 and _ai_active:
        if wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            if time.time() - _last_ai_input > _GRACE_PERIOD:
                _trigger_human_takeover("mouse click")
    return ctypes.windll.user32.CallNextHookEx(_ms_hook, nCode, wParam, lParam)

def _trigger_human_takeover(source):
    global _human_detected, _ai_active
    _human_detected = True
    _ai_active      = False
    print(f"\n[JARVIS] Human input detected ({source}) — AI releasing control immediately")
    # Call all registered callbacks (snapshot list under lock to avoid race)
    with _callbacks_lock:
        cbs = list(_callbacks)
    for cb in cbs:
        try: cb()
        except Exception: pass

def _install_hooks():
    global _kb_hook, _ms_hook, _kb_proc, _ms_proc
    try:
        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))

        _kb_proc = HOOKPROC(_on_keyboard)
        _ms_proc = HOOKPROC(_on_mouse)

        _kb_hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, _kb_proc,
            ctypes.windll.kernel32.GetModuleHandleW(None), 0)
        _ms_hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL, _ms_proc,
            ctypes.windll.kernel32.GetModuleHandleW(None), 0)

        # Message pump — required for hooks to fire
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    except Exception as e:
        print(f"[JARVIS] Input monitor hook error: {e}")

def _remove_hooks():
    if _kb_hook: ctypes.windll.user32.UnhookWindowsHookEx(_kb_hook)
    if _ms_hook: ctypes.windll.user32.UnhookWindowsHookEx(_ms_hook)

# ── Public API ─────────────────────────────────────────────────

def start_monitoring():
    """Start the human input detection thread."""
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(
        target=_install_hooks, daemon=True)
    _monitor_thread.start()

def set_ai_active(active: bool):
    """Call this when AI starts/stops sending inputs."""
    global _ai_active, _human_detected, _last_ai_input
    _ai_active      = active
    _human_detected = False
    if active:
        _last_ai_input = time.time()

def notify_ai_input():
    """Call this every time AI sends an input — updates grace period."""
    global _last_ai_input
    _last_ai_input = time.time()

def is_human_active() -> bool:
    """Returns True if human has taken over."""
    return _human_detected

def register_takeover_callback(fn):
    """Register a function to call the moment human input is detected."""
    with _callbacks_lock:
        _callbacks.append(fn)

def clear_takeover():
    """Reset — allow AI to resume after human explicitly re-enables it."""
    global _human_detected
    _human_detected = False

def stop_monitoring():
    _remove_hooks()

# Start monitoring immediately on import
start_monitoring()
