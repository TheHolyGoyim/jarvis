"""
pc_control.py — JARVIS Full PC Vision & Control
JARVIS can see your screen, control your mouse/keyboard,
read/write any file, manage processes, registry, network,
and execute any Windows operation autonomously.
"""

import os, sys, json, re, subprocess, time, threading, shutil, ctypes
import urllib.parse, webbrowser
from pathlib import Path
from datetime import datetime

# ── Install required packages on first run ────────────────────
def _ensure_packages():
    pkgs = ["pyautogui", "pillow", "psutil", "pygetwindow",
            "pynput", "pyperclip", "pytesseract", "keyboard"]
    for pkg in pkgs:
        try: __import__(pkg.replace("-","_"))
        except ImportError:
            subprocess.run(f"pip install {pkg} --quiet", shell=True, capture_output=True)

_ensure_packages()

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # Move mouse to top-left corner to abort
    pyautogui.PAUSE = 0.05
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

DATA_DIR = Path.home() / "Documents" / "JARVIS"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ── Auto-delete screenshots older than 12 hours ───────────────
def _cleanup_screenshots():
    """Runs in background — deletes screenshots older than 12 hours."""
    while True:
        try:
            cutoff = time.time() - (12 * 3600)  # 12 hours ago
            deleted = 0
            for f in SCREENSHOT_DIR.glob("*.png"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            if deleted:
                pass  # Silent cleanup
        except Exception:
            pass
        time.sleep(3600)  # Check every hour

# Start cleanup thread immediately
_cleanup_thread = threading.Thread(target=_cleanup_screenshots, daemon=True)
_cleanup_thread.start()

def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def _ai(prompt):
    try:
        import ollama, os
        model = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")
        return ollama.chat(model=model,
            messages=[{"role":"user","content":prompt}])["message"]["content"]
    except Exception as e:
        return f"(AI unavailable: {e})"

# ═════════════════════════════════════════════════════════════
# VISION — See the screen
# ═════════════════════════════════════════════════════════════

def screen_capture(region=None, save=True):
    """Take a screenshot and optionally analyze it with AI."""
    try:
        import pyautogui
        from PIL import Image
        img = pyautogui.screenshot(region=region)
        path = SCREENSHOT_DIR / f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img.save(str(path))
        return str(path), img
    except Exception as e:
        return None, None

def screen_read_text():
    """Read all visible text on the screen using OCR."""
    try:
        import pytesseract
        path, img = screen_capture()
        if img:
            text = pytesseract.image_to_string(img)
            return f"Text on screen:\n{text[:2000]}"
        return "Could not capture screen."
    except ImportError:
        # Fallback: use Windows built-in accessibility
        path, img = screen_capture()
        if path:
            return f"Screenshot saved: {path}\n(Install pytesseract for text reading)"
        return "Screen capture failed."

def screen_analyze():
    """Take a screenshot and describe what's on screen using AI vision."""
    path, img = screen_capture()
    if not path:
        return "Could not capture screen."
    # Try to get window titles as context
    windows = _run('powershell -c "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -ExpandProperty MainWindowTitle"')
    open_windows = [w.strip() for w in windows.split('\n') if w.strip()]
    result = _ai(f"""I took a screenshot of a Windows 11 desktop.
Open windows: {', '.join(open_windows[:10]) if open_windows else 'unknown'}
Describe what the user is likely looking at and what they might need help with.
Be brief and practical.""")
    return f"👁️ Screen Analysis:\n\nOpen windows: {', '.join(open_windows[:5]) if open_windows else 'none detected'}\n\n{result}\n\nScreenshot: {path}"

def get_active_window():
    """Get the title of the currently active window."""
    result = _run('powershell -c "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Sort-Object CPU -Descending | Select-Object -First 1).MainWindowTitle"')
    return f"Active window: {result or 'Unknown'}"

def list_open_windows():
    """List all open windows."""
    result = _run('powershell -c "Get-Process | Where-Object {$_.MainWindowTitle -ne \'\'} | Select-Object Name,MainWindowTitle | Format-Table -AutoSize"')
    return f"Open Windows:\n{result}"

# ═════════════════════════════════════════════════════════════
# MOUSE & KEYBOARD CONTROL
# ═════════════════════════════════════════════════════════════

def mouse_click(x=None, y=None, button="left", clicks=1, target_description=""):
    """Click at coordinates or find and click an element by description."""
    if not HAS_GUI: return "pyautogui not available."
    try:
        if target_description:
            # Try to find element using image recognition or description
            result = _find_and_click(target_description)
            return result
        if x is not None and y is not None:
            pyautogui.click(int(x), int(y), button=button, clicks=clicks)
            return f"Clicked at ({x}, {y})"
        return "No coordinates or target provided."
    except Exception as e:
        return f"Click error: {e}"

def _find_and_click(description):
    """Find UI element by description and click it."""
    try:
        # Use accessibility API to find elements
        result = _run(f'powershell -c "Add-Type -AssemblyName UIAutomationClient; $ae = [System.Windows.Automation.AutomationElement]::RootElement; $cond = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty, \'{description}\'); $el = $ae.FindFirst(\'Subtree\', $cond); if ($el) {{ $pt = $el.GetClickablePoint(); Write-Output \"$($pt.X),$($pt.Y)\" }} else {{ Write-Output \'not found\' }}"')
        if result and ',' in result and 'not found' not in result:
            parts = result.strip().split(',')
            x, y = float(parts[0]), float(parts[1])
            pyautogui.click(x, y)
            return f"Clicked '{description}' at ({x:.0f}, {y:.0f})"
        return f"Could not find UI element: '{description}'"
    except Exception as e:
        return f"Find/click error: {e}"

def mouse_move(x, y):
    if not HAS_GUI: return "pyautogui not available."
    pyautogui.moveTo(int(x), int(y), duration=0.2)
    return f"Mouse moved to ({x}, {y})"

def mouse_scroll(direction="down", amount=3):
    if not HAS_GUI: return "pyautogui not available."
    pyautogui.scroll(-amount if direction=="down" else amount)
    return f"Scrolled {direction} {amount} units"

def keyboard_type(text, interval=0.02):
    """Type text at the current cursor position."""
    if not HAS_GUI: return "pyautogui not available."
    try:
        pyautogui.typewrite(text, interval=interval)
        return f"Typed: {text[:50]}{'...' if len(text)>50 else ''}"
    except Exception:
        # Fallback for special characters
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        return f"Pasted: {text[:50]}"

def keyboard_hotkey(*keys):
    """Press a keyboard shortcut. E.g. ('ctrl', 'c') for copy."""
    if not HAS_GUI: return "pyautogui not available."
    pyautogui.hotkey(*keys)
    return f"Pressed: {'+'.join(keys)}"

def keyboard_press(key):
    """Press a single key."""
    if not HAS_GUI: return "pyautogui not available."
    pyautogui.press(key)
    return f"Pressed: {key}"

def type_and_enter(text):
    """Type text and press Enter."""
    keyboard_type(text)
    time.sleep(0.1)
    keyboard_press('enter')
    return f"Typed and submitted: {text[:50]}"

# ═════════════════════════════════════════════════════════════
# FILE SYSTEM — Full access
# ═════════════════════════════════════════════════════════════

def fs_read(path):
    """Read any file on the PC."""
    try:
        p = Path(path)
        if not p.exists(): return f"File not found: {path}"
        if p.stat().st_size > 5*1024*1024: return f"File too large (>{5}MB). Use fs_read_lines for large files."
        suffix = p.suffix.lower()
        if suffix == '.docx':
            from docx import Document
            doc = Document(str(p))
            return "\n".join(para.text for para in doc.paragraphs)
        elif suffix in ['.xlsx', '.xls']:
            return f"Excel file. Use 'open {path}' to view in Excel."
        elif suffix in ['.jpg','.jpeg','.png','.gif','.bmp','.webp']:
            return f"Image file: {path}"
        elif suffix in ['.exe','.dll','.bin']:
            return f"Binary file: {path} ({p.stat().st_size//1024}KB)"
        else:
            return p.read_text(encoding='utf-8', errors='replace')[:5000]
    except Exception as e:
        return f"Read error: {e}"

def fs_write(path, content, mode="overwrite"):
    """Write content to any file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, 'a', encoding='utf-8') as f: f.write(content)
        else:
            p.write_text(content, encoding='utf-8')
        return f"✅ Written to {path} ({len(content)} chars)"
    except Exception as e:
        return f"Write error: {e}"

def fs_list(path=".", pattern="*", recursive=False):
    """List files in any directory."""
    try:
        p = Path(path)
        if not p.exists(): return f"Path not found: {path}"
        if recursive:
            files = list(p.rglob(pattern))[:50]
        else:
            files = list(p.glob(pattern))[:50]
        if not files: return f"No files matching '{pattern}' in {path}"
        lines = [f"📁 {p} ({len(files)} items):"]
        for f in sorted(files, key=lambda x: (x.is_file(), x.name)):
            size = f"{f.stat().st_size//1024}KB" if f.is_file() else "DIR"
            lines.append(f"  {'📄' if f.is_file() else '📁'} {f.name} ({size})")
        return "\n".join(lines)
    except Exception as e:
        return f"List error: {e}"

def fs_search(query, path="C:\\Users", file_type=""):
    """Search for files by name across the PC."""
    try:
        ext = f"*.{file_type}" if file_type else "*"
        result = _run(f'dir /s /b "{Path(path)}\\{ext}" 2>nul | findstr /i "{query}"', timeout=20)
        if not result: return f"No files matching '{query}' found in {path}"
        lines = result.split('\n')[:20]
        return f"Found {len(lines)} files matching '{query}':\n" + "\n".join(f"  {l.strip()}" for l in lines if l.strip())
    except Exception as e:
        return f"Search error: {e}"

def fs_delete(path, confirm=True):
    """Delete a file or folder."""
    try:
        p = Path(path)
        if not p.exists(): return f"Not found: {path}"
        if p.is_dir():
            shutil.rmtree(str(p))
            return f"🗑️ Deleted folder: {path}"
        else:
            p.unlink()
            return f"🗑️ Deleted file: {path}"
    except Exception as e:
        return f"Delete error: {e}"

def fs_copy(source, destination):
    try:
        s, d = Path(source), Path(destination)
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir(): shutil.copytree(str(s), str(d))
        else: shutil.copy2(str(s), str(d))
        return f"✅ Copied {s.name} → {d}"
    except Exception as e:
        return f"Copy error: {e}"

def fs_move(source, destination):
    try:
        shutil.move(source, destination)
        return f"✅ Moved {source} → {destination}"
    except Exception as e:
        return f"Move error: {e}"

def fs_create_folder(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"✅ Created folder: {path}"
    except Exception as e:
        return f"Error: {e}"

def fs_open_file(path):
    """Open any file with its default application."""
    try:
        subprocess.Popen(f'start "" "{path}"', shell=True)
        return f"✅ Opened: {path}"
    except Exception as e:
        return f"Open error: {e}"

def fs_get_size(path):
    """Get size of file or folder."""
    try:
        p = Path(path)
        if p.is_file():
            s = p.stat().st_size
            return f"{path}: {s//2**20}MB ({s:,} bytes)"
        total = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        return f"{path}: {total//2**20}MB total"
    except Exception as e:
        return f"Error: {e}"

# ═════════════════════════════════════════════════════════════
# PROCESS MANAGEMENT
# ═════════════════════════════════════════════════════════════

def process_list(sort_by="cpu", filter_name=""):
    """List all running processes."""
    if not HAS_PSUTIL:
        result = _run('tasklist /FO CSV /NH')
        return f"Running processes:\n{result[:3000]}"
    procs = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_info','status']):
        try:
            info = p.info
            if filter_name and filter_name.lower() not in info['name'].lower(): continue
            cpu = info.get('cpu_percent', 0) or 0
            mem = (info.get('memory_info') or psutil._common.pmem(0,0)).rss
            procs.append((cpu, mem, info['pid'], info['name']))
        except Exception: pass
    procs.sort(key=lambda x: -x[0 if sort_by=="cpu" else 1])
    lines = [f"Processes (top by {sort_by}):"]
    for cpu, mem, pid, name in procs[:20]:
        lines.append(f"  {name[:30]:<30} CPU:{cpu:5.1f}% MEM:{mem//2**20:4}MB PID:{pid}")
    return "\n".join(lines)

def process_kill(name_or_pid):
    """Kill a process by name or PID."""
    try:
        if str(name_or_pid).isdigit():
            result = _run(f'taskkill /f /pid {name_or_pid}')
        else:
            result = _run(f'taskkill /f /im "{name_or_pid}.exe" /t')
        return f"Process killed: {name_or_pid}\n{result}"
    except Exception as e:
        return f"Kill error: {e}"

def process_start(command, hidden=False):
    """Start a process or application."""
    try:
        if hidden:
            subprocess.Popen(command, shell=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(command, shell=True)
        return f"✅ Started: {command}"
    except Exception as e:
        return f"Start error: {e}"

def get_system_resources():
    """Get real-time CPU, RAM, disk, GPU usage."""
    if not HAS_PSUTIL:
        return _run('wmic cpu get loadpercentage /value')
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('C:\\')
    lines = [
        "📊 System Resources:",
        f"  CPU:  {cpu:.1f}% used",
        f"  RAM:  {mem.used//2**30}GB / {mem.total//2**30}GB ({mem.percent:.0f}%)",
        f"  Disk C: {disk.used//2**30}GB / {disk.total//2**30}GB ({disk.percent:.0f}%)",
        f"  Free RAM: {mem.available//2**30}GB",
    ]
    # GPU
    gpu = _run('nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits')
    if gpu and ',' in gpu:
        parts = gpu.split(',')
        if len(parts) >= 4:
            lines.append(f"  GPU:  {parts[0].strip()}% used | VRAM: {parts[1].strip()}MB/{parts[2].strip()}MB | Temp: {parts[3].strip()}°C")
    return "\n".join(lines)

# ═════════════════════════════════════════════════════════════
# REGISTRY
# ═════════════════════════════════════════════════════════════

def registry_read(key_path, value_name=""):
    """Read a Windows registry value."""
    try:
        if value_name:
            result = _run(f'reg query "{key_path}" /v "{value_name}"')
        else:
            result = _run(f'reg query "{key_path}"')
        return f"Registry: {key_path}\n{result[:2000]}"
    except Exception as e:
        return f"Registry read error: {e}"

def registry_write(key_path, value_name, value, value_type="REG_SZ"):
    """Write a Windows registry value."""
    try:
        result = _run(f'reg add "{key_path}" /v "{value_name}" /t {value_type} /d "{value}" /f')
        return f"✅ Registry written: {key_path}\\{value_name} = {value}\n{result}"
    except Exception as e:
        return f"Registry write error: {e}"

def registry_delete(key_path, value_name=""):
    """Delete a registry key or value."""
    try:
        if value_name:
            result = _run(f'reg delete "{key_path}" /v "{value_name}" /f')
        else:
            result = _run(f'reg delete "{key_path}" /f')
        return f"🗑️ Registry deleted: {key_path}\n{result}"
    except Exception as e:
        return f"Registry delete error: {e}"

# ═════════════════════════════════════════════════════════════
# NETWORK CONTROL
# ═════════════════════════════════════════════════════════════

def network_status():
    """Full network status."""
    lines = ["🌐 Network Status:"]
    # Interfaces
    adapters = _run('powershell -c "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | Select-Object Name,LinkSpeed,MediaType | Format-Table -AutoSize"')
    lines.append(f"\nActive Adapters:\n{adapters}")
    # IP
    ip = _run('ipconfig /all')
    # Grab key lines
    for line in ip.split('\n'):
        if any(x in line for x in ['IPv4','IPv6','Default Gateway','DNS Servers','Physical Address']):
            lines.append(f"  {line.strip()}")
    return "\n".join(lines)

def network_connections():
    """Show active network connections."""
    result = _run('netstat -ano')
    return f"Active Connections:\n{result[:3000]}"

def wifi_profiles():
    """List saved WiFi networks."""
    result = _run('netsh wlan show profiles')
    return f"Saved WiFi Networks:\n{result}"

def wifi_password(network_name):
    """Get WiFi password for a saved network."""
    result = _run(f'netsh wlan show profile name="{network_name}" key=clear')
    # Extract password
    for line in result.split('\n'):
        if 'Key Content' in line:
            return f"WiFi Password for '{network_name}': {line.split(':')[-1].strip()}"
    return f"Could not retrieve password for '{network_name}'."

def ping(host="8.8.8.8", count=4):
    result = _run(f'ping -n {count} {host}')
    return f"Ping {host}:\n{result}"

def traceroute(host):
    result = _run(f'tracert -h 15 {host}', timeout=30)
    return f"Traceroute to {host}:\n{result[:2000]}"

def port_scan(host="localhost", ports="80,443,8080,3000,5000"):
    """Check if ports are open."""
    results = []
    for port in str(ports).split(','):
        port = port.strip()
        r = _run(f'powershell -c "Test-NetConnection -ComputerName {host} -Port {port} -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded"')
        status = "✅ OPEN" if "True" in r else "❌ CLOSED"
        results.append(f"  Port {port}: {status}")
    return f"Port scan {host}:\n" + "\n".join(results)

# ═════════════════════════════════════════════════════════════
# WINDOWS SETTINGS & TWEAKS
# ═════════════════════════════════════════════════════════════

def set_wallpaper(image_path):
    """Change desktop wallpaper."""
    try:
        ctypes.windll.user32.SystemParametersInfoW(20, 0, str(image_path), 3)
        return f"✅ Wallpaper set to: {image_path}"
    except Exception as e:
        return f"Wallpaper error: {e}"

def set_display_brightness(level):
    """Set screen brightness 0-100."""
    result = _run(f'powershell -c "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"')
    return f"Brightness set to {level}%"

def set_power_plan(plan="balanced"):
    """Set Windows power plan."""
    plans = {
        "balanced":    "381b4222-f694-41f0-9685-ff5bb260df2e",
        "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "powersaver":  "a1841308-3541-4fab-bc81-f71556f20b4a",
    }
    guid = plans.get(plan.lower(), plans["balanced"])
    result = _run(f'powercfg /setactive {guid}')
    return f"Power plan set to: {plan}"

def get_startup_programs():
    """List programs that run at startup."""
    result = _run('wmic startup get caption,command,location /format:list')
    return f"Startup Programs:\n{result[:3000]}"

def disable_startup_program(name):
    """Disable a startup program."""
    result = _run(f'reg delete "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" /v "{name}" /f')
    return f"Disabled startup: {name}\n{result}"

def set_volume(level):
    """Set system volume 0-100."""
    result = _run(f'powershell -c "$obj = New-Object -ComObject WScript.Shell; $vol = {level}/100; (New-Object -ComObject Shell.Application).SetProperty(\'SysVolume\', $vol)"')
    # Fallback using nircmd if available
    nircmd = Path(os.environ.get("PROGRAMFILES","C:\\Program Files")) / "NirCmd" / "nircmd.exe"
    if nircmd.exists():
        _run(f'"{nircmd}" setsysvolume {int(level*655.35)}')
    return f"Volume set to {level}%"

def get_installed_software():
    """List all installed software."""
    result = _run('wmic product get name,version /format:csv', timeout=30)
    lines = [l for l in result.split('\n') if l.strip() and l.strip() != 'Node,Name,Version'][:50]
    return "Installed Software:\n" + "\n".join(f"  • {','.join(l.split(',')[1:])}" for l in lines if l)

def run_as_admin(command):
    """Run a command with administrator privileges."""
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c {command}', None, 1)
        return f"Running as admin: {command}"
    except Exception as e:
        return f"Admin run error: {e}"

# ═════════════════════════════════════════════════════════════
# CLIPBOARD
# ═════════════════════════════════════════════════════════════

def clipboard_get():
    """Get current clipboard content."""
    try:
        import pyperclip
        content = pyperclip.paste()
        return f"Clipboard: {content[:500]}{'...' if len(content)>500 else ''}"
    except Exception as e:
        result = _run('powershell -c "Get-Clipboard"')
        return f"Clipboard: {result[:500]}"

def clipboard_set(text):
    """Set clipboard content."""
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        subprocess.run('clip', input=text.encode('utf-16'), shell=True)
    return f"Clipboard set: {text[:100]}"

# ═════════════════════════════════════════════════════════════
# SCHEDULED TASKS & AUTOMATION
# ═════════════════════════════════════════════════════════════

def schedule_task(name, command, trigger_time):
    """Schedule a Windows task."""
    result = _run(f'schtasks /create /tn "{name}" /tr "{command}" /sc once /st {trigger_time} /f')
    return f"Task scheduled: {name} at {trigger_time}\n{result}"

def list_scheduled_tasks():
    result = _run('schtasks /query /fo LIST /v', timeout=20)
    return f"Scheduled Tasks:\n{result[:3000]}"

def delete_scheduled_task(name):
    result = _run(f'schtasks /delete /tn "{name}" /f')
    return f"Deleted task: {name}\n{result}"

def set_reminder(message, minutes_from_now):
    """Set a popup reminder."""
    subprocess.Popen(
        f'powershell -c "Start-Sleep {int(minutes_from_now)*60}; '
        f'Add-Type -AssemblyName System.Windows.Forms; '
        f'[System.Windows.Forms.MessageBox]::Show(\'{message}\',\'JARVIS Reminder\')"',
        shell=True)
    return f"⏰ Reminder set: '{message}' in {minutes_from_now} minutes."

# ═════════════════════════════════════════════════════════════
# AUTONOMOUS TASK EXECUTION
# ═════════════════════════════════════════════════════════════

def execute_task_autonomously(task_description):
    """
    JARVIS figures out HOW to complete a task on your PC
    without needing step-by-step instructions.
    Uses AI to plan, then executes.
    """
    plan = _ai(f"""You are controlling a Windows 11 PC autonomously.
Task: {task_description}

Available actions:
- fs_read(path), fs_write(path, content), fs_list(path), fs_search(query, path)
- fs_delete(path), fs_copy(src, dst), fs_move(src, dst), fs_open_file(path)
- process_list(), process_kill(name), process_start(command)
- keyboard_type(text), keyboard_hotkey(*keys), keyboard_press(key)
- mouse_click(x, y), screen_analyze()
- registry_read(key, value), registry_write(key, value, data)
- _run(cmd) for any Windows command
- set_volume(level), set_wallpaper(path)

Write a Python execution plan as a numbered list of specific function calls.
Be concrete. If you need to find a file first, search for it.
Format: Step 1: function_call(args)""")

    log_path = DATA_DIR / "task_log.txt"
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"\n[{datetime.now()}] TASK: {task_description}\nPLAN:\n{plan}\n{'='*50}\n")

    return f"🤖 Autonomous Task: {task_description}\n\nExecution Plan:\n{plan}\n\n📋 Log saved: {log_path}"

def ai_diagnose_problem(problem):
    """AI diagnoses and fixes a PC problem."""
    # Gather system context
    resources = get_system_resources()
    recent_errors = _run('powershell -c "Get-EventLog -LogName System -EntryType Error -Newest 5 | Select-Object TimeGenerated,Source,Message | Format-List"', timeout=10)
    plan = _ai(f"""Windows 11 PC problem: {problem}

System state:
{resources}

Recent system errors:
{recent_errors[:500]}

Diagnose the problem and provide:
1. Most likely cause
2. Exact fix steps for Windows 11 (command-line or specific settings)
3. Prevention tip
Be specific and practical.""")
    return f"🔧 PC Diagnosis: {problem}\n\n{plan}"

def explain_whats_running():
    """Tell the user what's running on their PC and why."""
    if not HAS_PSUTIL:
        return "psutil not available."
    procs = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_info']):
        try:
            info = p.info
            cpu = info.get('cpu_percent',0) or 0
            mem = (info.get('memory_info') or psutil._common.pmem(0,0)).rss//2**20
            if cpu > 0.5 or mem > 50:
                procs.append(f"{info['name']} (CPU:{cpu:.1f}% RAM:{mem}MB)")
        except Exception: pass
    if not procs: return "No significant processes running."
    result = _ai(f"""These processes are running on a Windows PC:
{chr(10).join(procs[:15])}

Briefly explain what each does in plain English and flag anything suspicious.""")
    return f"💻 What's Running:\n\n{result}"
