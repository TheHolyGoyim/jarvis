"""
jarvis_app.py — JARVIS Desktop Launcher & Control Panel.

Double-click the JARVIS desktop shortcut to launch. This:
  1. starts Ollama (hidden) if it isn't running
  2. starts the Flask server (hidden) if it isn't running
  3. opens the REAL Jarvis UI (localhost:5005/app) in an app-mode
     browser window — the same UI the phone uses

The web app is the SOLE frontend: chat, charts, reports, Commands tab,
Tools tab, portfolio, reminders — everything lives there. This window is
just a small control panel for the engines (status / restart / logs /
shutdown). The old built-in Tkinter chat was a second, feature-poor
frontend and was removed deliberately — it never showed charts, reports,
or the Commands/Tools tabs.

Closing this window LEAVES JARVIS RUNNING (so the app window and your
phone keep working). Use SHUTDOWN to actually stop everything.
"""

# ── Bootstrap: install missing packages before importing anything ──────────────
import sys, os, subprocess as _sub

def _ensure_packages():
    need = []
    for pkg in ("flask", "requests"):
        try:
            __import__(pkg)
        except ImportError:
            need.append(pkg)
    if need:
        _sub.run([sys.executable, "-m", "pip", "install", "--quiet"] + need,
                 timeout=180)

_ensure_packages()

# ── Imports ────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import font as tkfont
import threading, json, time, shutil
import urllib.request
from pathlib import Path

# ── Paths & globals ────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
ENV        = ROOT / ".env"
LOG_DIR    = Path.home() / "Documents" / "JARVIS"
SERVER_LOG = LOG_DIR / "server.log"
OLLAMA_LOG = LOG_DIR / "ollama.log"

SERVER_URL = "http://127.0.0.1:5005"
APP_URL    = SERVER_URL + "/app"
OLLAMA_URL = "http://localhost:11434"

SERVER_PROC = None
OLLAMA_PROC = None

# ── Load .env ──────────────────────────────────────────────────────────────────
if ENV.exists():
    for _ln in ENV.read_text(encoding="utf-8").splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _, _v = _ln.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

JARVIS_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

# ── Palette ────────────────────────────────────────────────────────────────────
C = {
    "bg": "#080c14", "bg2": "#0f1624", "border": "#1e3a5f",
    "accent": "#00d4ff", "green": "#00ff88", "red": "#ff4444",
    "yellow": "#ffd600", "text": "#d8e4f0", "dim": "#4a6080",
}


# ══════════════════════════════════════════════════════════════════════════════
# PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _python_exe() -> str:
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


def _hidden_popen(cmd, cwd=None, log_file=None):
    """Start a subprocess with no visible window, output to log_file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = open(log_file, "w", encoding="utf-8", buffering=1) if log_file else _sub.DEVNULL
    kwargs = {}
    if sys.platform == "win32":
        si = _sub.STARTUPINFO()
        si.dwFlags |= _sub.STARTF_USESHOWWINDOW
        si.wShowWindow = _sub.SW_HIDE
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = _sub.CREATE_NO_WINDOW
    return _sub.Popen(cmd, cwd=cwd, stdout=out, stderr=out, **kwargs)


def _alive(url: str, timeout=3) -> bool:
    try:
        return urllib.request.urlopen(url, timeout=timeout).status == 200
    except Exception:
        return False


def _ollama_alive() -> bool:
    return _alive(f"{OLLAMA_URL}/api/tags", 2)


def _server_alive() -> bool:
    return _alive(f"{SERVER_URL}/health", 3)


def _find_ollama() -> str:
    """Locate the ollama binary even when it isn't on this process's PATH —
    per-user installs are invisible to pythonw launched from a shortcut or
    Task Scheduler, which is why startup used to fail silently."""
    exe = shutil.which("ollama")
    if exe:
        return exe
    for cand in (
        os.path.expandvars(r"%LocalAppData%\Programs\Ollama\ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Program Files (x86)\Ollama\ollama.exe",
    ):
        if Path(cand).exists():
            return cand
    return ""


def _model_present() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode("utf-8", "replace"))
        base = JARVIS_MODEL.split(":")[0]
        return any(JARVIS_MODEL == (m.get("name") or "")
                   or (m.get("name") or "").startswith(base)
                   for m in tags.get("models", []))
    except Exception:
        return False


def _pull_model_if_missing(log=lambda m: None) -> bool:
    """Pull JARVIS_MODEL when Ollama is serving but the model isn't local."""
    if _model_present():
        return True
    ollama_bin = _find_ollama()
    if not ollama_bin:
        return False
    log(f"Model {JARVIS_MODEL} not present — pulling (first time only, several GB)...")
    try:
        proc = _hidden_popen([ollama_bin, "pull", JARVIS_MODEL])
        proc.wait(timeout=3600)
        ok = _model_present()
        log(f"Model {JARVIS_MODEL} ready." if ok else
            f"⚠ Model pull did not complete — see {OLLAMA_LOG}")
        return ok
    except Exception as e:
        log(f"⚠ Model pull failed: {e}")
        return False


def _start_ollama(log=lambda m: None) -> bool:
    """Ensure Ollama is serving on 11434. Waits up to 15s (1s pings).
    On failure JARVIS keeps running in degraded rule-based mode — the
    failure is LOGGED, never silent."""
    global OLLAMA_PROC
    if _ollama_alive():
        log("Ollama already running.")
        threading.Thread(target=_pull_model_if_missing, args=(log,), daemon=True).start()
        return True
    ollama_bin = _find_ollama()
    if not ollama_bin:
        log("⚠ Ollama not found on PATH or in standard install folders. "
            "AI DEGRADED to rule-based replies — install from https://ollama.com")
        return False
    log("Starting Ollama engine...")
    OLLAMA_PROC = _hidden_popen([ollama_bin, "serve"], log_file=OLLAMA_LOG)
    for _ in range(15):
        if _ollama_alive():
            log("Ollama online.")
            threading.Thread(target=_pull_model_if_missing, args=(log,), daemon=True).start()
            return True
        time.sleep(1)
    log(f"⚠ Ollama did not respond within 15s — continuing in DEGRADED mode "
        f"(rule-based replies). Check log: {OLLAMA_LOG}")
    return _ollama_alive()


def _kill_port_5005():
    try:
        res = _sub.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            if ":5005" in line and "LISTEN" in line:
                pid = line.strip().split()[-1]
                if pid and pid.isdigit() and pid != "0":
                    _sub.run(["taskkill", "/F", "/PID", pid],
                             capture_output=True, timeout=5)
    except Exception:
        pass


def _start_server():
    global SERVER_PROC
    if _server_alive():
        return
    SERVER_PROC = _hidden_popen(
        [_python_exe(), str(ROOT / "server.py")],
        cwd=str(ROOT), log_file=SERVER_LOG)


def _read_log_tail(path: Path, n: int = 30) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(no log)"


# ── Open the web UI as a desktop app window ────────────────────────────────────

def _browser_exe():
    """Prefer an app-mode capable Chromium browser: Chrome, then Edge."""
    for cand in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(cand).exists():
            return cand
    return None


def open_app_window():
    """Open the Jarvis web UI in a chromeless app window (or a tab as fallback)."""
    exe = _browser_exe()
    if exe:
        _sub.Popen([exe, f"--app={APP_URL}", "--window-size=1150,820"],
                   stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
    else:
        import webbrowser
        webbrowser.open(APP_URL)


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL PANEL (small — NOT a chat UI; the web app is the sole frontend)
# ══════════════════════════════════════════════════════════════════════════════

class ControlPanel:
    BOOT_TIMEOUT = 60

    def __init__(self, root: tk.Tk):
        self.root = root
        self._app_opened = False
        root.title("JARVIS Control")
        root.configure(bg=C["bg"])
        root.geometry("460x330")
        root.resizable(False, False)

        f_hdr = tkfont.Font(family="Consolas", size=15, weight="bold")
        f_sub = tkfont.Font(family="Consolas", size=9)
        f_btn = tkfont.Font(family="Consolas", size=10, weight="bold")
        self.f_log = tkfont.Font(family="Consolas", size=8)

        hdr = tk.Frame(root, bg=C["bg2"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="◈ JARVIS", font=f_hdr, bg=C["bg2"],
                 fg=C["accent"]).pack(side="left", padx=14, pady=10)
        self.dot = tk.Label(hdr, text="●", font=f_hdr, bg=C["bg2"], fg=C["red"])
        self.dot.pack(side="right", padx=(0, 14))
        self.status = tk.Label(hdr, text="STARTING...", font=f_sub,
                               bg=C["bg2"], fg=C["dim"])
        self.status.pack(side="right")

        tk.Label(root, text="Chat lives in the app window — this panel only "
                            "controls the engines.\nClosing this panel leaves "
                            "JARVIS running for the app + your phone.",
                 font=f_sub, bg=C["bg"], fg=C["dim"], justify="left"
                 ).pack(anchor="w", padx=14, pady=(8, 4))

        btns = tk.Frame(root, bg=C["bg"])
        btns.pack(fill="x", padx=12, pady=4)

        def mkbtn(txt, bg, fg, cmd, col, row=0):
            b = tk.Button(btns, text=txt, font=f_btn, bg=bg, fg=fg,
                          relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
                          command=cmd, width=16)
            b.grid(column=col, row=row, padx=3, pady=3)
            return b

        mkbtn("OPEN APP ▶", C["accent"], C["bg"], self._open_app, 0)
        mkbtn("RESTART SERVER", C["border"], C["text"], self._restart, 1)
        mkbtn(f"PULL MODEL", C["border"], C["text"], self._pull_model, 0, 1)
        mkbtn("SHUTDOWN ALL", C["red"], "#ffffff", self._shutdown, 1, 1)

        tk.Label(root, text=f"  model: {JARVIS_MODEL}  ·  server: {SERVER_URL}",
                 font=f_sub, bg=C["bg"], fg=C["dim"]).pack(anchor="w", padx=12)

        logf = tk.Frame(root, bg=C["bg"])
        logf.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.log = tk.Text(logf, bg=C["bg2"], fg=C["yellow"], font=self.f_log,
                           wrap="word", state="disabled", relief="flat",
                           bd=0, padx=8, pady=6, height=8)
        self.log.pack(fill="both", expand=True)

        self._log("Launching JARVIS...")
        threading.Thread(target=self._boot, daemon=True).start()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _log(self, text):
        def do():
            self.log.config(state="normal")
            self.log.insert("end", text + "\n")
            self.log.config(state="disabled")
            self.log.see("end")
        self.root.after(0, do)

    def _set_status(self, text, color):
        self.root.after(0, lambda: (self.dot.config(fg=color),
                                    self.status.config(text=text)))

    # ── boot ───────────────────────────────────────────────────────────────────
    def _boot(self):
        # Ollama is ensured on EVERY launch. The old code returned early when
        # the Flask server was still alive from a previous session (which is
        # normal — closing the panel leaves it running), so Ollama was never
        # started on any launch after the first. That was the root cause of
        # "Ollama doesn't start with JARVIS".
        self._set_status("STARTING AI ENGINE...", C["yellow"])
        threading.Thread(target=_start_ollama, args=(self._log,), daemon=True).start()
        if _server_alive():
            self._log("Server already running — opening the app.")
            self._online()
            return
        self._set_status("STARTING SERVER...", C["yellow"])
        _kill_port_5005()
        _start_server()
        for i in range(self.BOOT_TIMEOUT):
            if _server_alive():
                self._online()
                return
            time.sleep(1)
            self._set_status(f"STARTING... {i + 1}s", C["yellow"])
            if SERVER_PROC and SERVER_PROC.poll() is not None:
                break
        self._set_status("OFFLINE", C["red"])
        self._log("Server failed to start. Last log lines:")
        self._log(_read_log_tail(SERVER_LOG, 20))
        self._log("\nFix: terminal → cd C:\\Projects\\jarvis4 → python server.py, "
                  "then click RESTART SERVER.")

    def _online(self):
        self._set_status("ONLINE", C["green"])
        self._log(f"JARVIS online — AI: {'ON' if _ollama_alive() else 'OFF (starting)'}")
        if not self._app_opened:
            self._app_opened = True
            open_app_window()
            self._log("App window opened. This panel can be closed — "
                      "JARVIS keeps running.")

    # ── buttons ────────────────────────────────────────────────────────────────
    def _open_app(self):
        open_app_window()

    def _restart(self):
        def do():
            self._set_status("RESTARTING...", C["yellow"])
            self._log("Restarting server...")
            _kill_port_5005()
            time.sleep(1)
            _start_server()
            for _ in range(self.BOOT_TIMEOUT):
                if _server_alive():
                    self._set_status("ONLINE", C["green"])
                    self._log("Server back online.")
                    return
                time.sleep(1)
            self._set_status("OFFLINE", C["red"])
            self._log("Restart failed:\n" + _read_log_tail(SERVER_LOG, 15))
        threading.Thread(target=do, daemon=True).start()

    def _pull_model(self):
        def do():
            ollama_bin = _find_ollama()
            if not ollama_bin:
                self._log("Ollama not installed — get it at https://ollama.ai")
                return
            self._log(f"Pulling {JARVIS_MODEL} (can take several minutes)...")
            try:
                proc = _sub.Popen([ollama_bin, "pull", JARVIS_MODEL],
                                  stdout=_sub.PIPE, stderr=_sub.STDOUT,
                                  text=True, encoding="utf-8", errors="replace")
                last = ""
                for line in proc.stdout:
                    line = line.strip()
                    if line and line != last:
                        last = line
                        self._log("  " + line[:70])
                proc.wait()
                self._log("Pull complete.")
            except Exception as e:
                self._log(f"Pull failed: {e}")
        threading.Thread(target=do, daemon=True).start()

    def _shutdown(self):
        self._log("Shutting down JARVIS...")
        _kill_port_5005()
        global OLLAMA_PROC
        if OLLAMA_PROC and OLLAMA_PROC.poll() is None:
            try:
                OLLAMA_PROC.terminate()
            except Exception:
                pass
        OLLAMA_PROC = None
        self.root.after(600, self.root.destroy)

    def on_close(self):
        # Deliberately does NOT stop the server: the app window and the phone
        # PWA are still using it. SHUTDOWN ALL is the explicit off switch.
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ControlPanel(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
