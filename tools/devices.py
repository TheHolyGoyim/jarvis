"""
devices.py — JARVIS Device Intelligence & Modding
Detect connected devices and apply mods/firmware — ONLY with explicit human approval.

Safety model:
  1. DETECT   — always safe, read-only
  2. PLAN     — explains exactly what would happen, no changes
  3. CONFIRM  — user must say "device confirm [token]" to proceed
  4. EXECUTE  — runs only the confirmed action

JARVIS never modifies any device without a confirmed approval token.
"""

import os, re, subprocess, json, time, hashlib
from datetime import datetime
from pathlib import Path

_DATA_DIR    = Path.home() / "Documents" / "JARVIS" / "devices"
_PENDING_FILE = _DATA_DIR / "pending_actions.json"
_LOG_FILE     = _DATA_DIR / "device_log.json"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Confirmation system ───────────────────────────────────────────────────────

def _pending_load() -> dict:
    try:
        return json.loads(_PENDING_FILE.read_text(encoding="utf-8")) if _PENDING_FILE.exists() else {}
    except Exception:
        return {}

def _pending_save(data: dict):
    try:
        _PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

def _make_token(action: str) -> str:
    return hashlib.md5(f"{action}{time.time()}".encode()).hexdigest()[:6].upper()

def _queue_action(action_type: str, params: dict, description: str) -> str:
    """
    Queue a device action requiring approval.
    Returns the confirmation token the user must speak.
    """
    token = _make_token(action_type)
    pending = _pending_load()
    pending[token] = {
        "type":        action_type,
        "params":      params,
        "description": description,
        "queued":      datetime.now().isoformat(),
        "expires":     (datetime.now().timestamp() + 600),  # 10 min expiry
    }
    _pending_save(pending)
    return token

def _log_action(action: str, result: str):
    try:
        log = json.loads(_LOG_FILE.read_text(encoding="utf-8")) if _LOG_FILE.exists() else []
        log.append({"time": datetime.now().isoformat(), "action": action, "result": result})
        _LOG_FILE.write_text(json.dumps(log[-200:], indent=2), encoding="utf-8")
    except Exception:
        pass

def device_confirm(token: str) -> str:
    """
    Execute a pending device action after human confirmation.
    token: the 6-character token shown in the plan step.
    """
    token = token.strip().upper()
    pending = _pending_load()

    if token not in pending:
        return (f"Token '{token}' not found or expired.\n"
                f"Pending tokens: {', '.join(pending.keys()) or 'none'}\n"
                f"Run the plan command again to get a fresh token.")

    action = pending[token]
    if time.time() > action.get("expires", 0):
        del pending[token]
        _pending_save(pending)
        return "Token expired (10 min limit). Run the plan again."

    # Execute the action
    del pending[token]
    _pending_save(pending)

    atype  = action["type"]
    params = action["params"]

    if atype == "adb_command":
        return _execute_adb(params.get("device_id", ""), params.get("command", ""))
    elif atype == "adb_install":
        return _execute_adb_install(params.get("device_id", ""), params.get("apk_path", ""))
    elif atype == "adb_shell":
        return _execute_adb_shell(params.get("device_id", ""), params.get("shell_cmd", ""))
    elif atype == "tasmota_flash":
        return _execute_tasmota_flash(params)
    elif atype == "magisk_push":
        return _execute_magisk_push(params)
    else:
        return f"Unknown action type: {atype}"


# ── USB / Device Detection ────────────────────────────────────────────────────

def _run_ps(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def devices_list() -> str:
    """Scan and list all connected USB and network devices."""
    lines = [f"Connected Devices — {datetime.now().strftime('%H:%M:%S')}", ""]

    # USB devices via WMI
    usb_raw = _run_ps(
        "Get-PnpDevice -PresentOnly | Where-Object {$_.Status -eq 'OK'} | "
        "Select-Object FriendlyName,Class,InstanceId | "
        "Sort-Object Class | Format-Table -AutoSize | Out-String -Width 120"
    )

    # Parse into useful categories
    phones   = []
    cameras  = []
    drives   = []
    audio    = []
    hubs     = []
    other    = []

    for line in usb_raw.splitlines():
        ll = line.lower()
        if not line.strip() or "friendlyname" in ll or "---" in ll:
            continue
        if any(w in ll for w in ["android", "iphone", "pixel", "samsung", "adb", "composite"]):
            phones.append(line.strip())
        elif any(w in ll for w in ["camera", "webcam", "capture", "video"]):
            cameras.append(line.strip())
        elif any(w in ll for w in ["disk", "storage", "drive", "flash", "volume"]):
            drives.append(line.strip())
        elif any(w in ll for w in ["audio", "speaker", "microphone", "headset", "sound"]):
            audio.append(line.strip())
        elif any(w in ll for w in ["hub", "root hub"]):
            hubs.append(line.strip())
        elif line.strip():
            other.append(line.strip())

    def section(title, items):
        if not items:
            return []
        return [f"  {title}:"] + [f"    • {i[:80]}" for i in items[:8]] + [""]

    lines += section("Phones / Mobile", phones)
    lines += section("Cameras / Webcams", cameras)
    lines += section("Storage Drives", drives)
    lines += section("Audio", audio)
    lines += section("Other Devices", other[:10])

    # ADB devices (Android)
    adb_devs = _adb_devices()
    if adb_devs:
        lines += ["  Android via ADB:"] + [f"    • {d}" for d in adb_devs] + [""]

    # Network devices (arp scan)
    arp_raw = _run_ps("arp -a")
    net_devices = [l.strip() for l in arp_raw.splitlines()
                   if re.match(r'\s+\d+\.\d+\.\d+\.\d+', l)]
    if net_devices:
        lines += [f"  Network devices: {len(net_devices)} found (say 'network scan' for details)", ""]

    if not any([phones, cameras, drives, audio, adb_devs]):
        lines.append("  No interesting devices detected beyond standard PC hardware.")

    lines += [
        "Say 'phone info' to inspect a connected phone.",
        "Say 'webcam info' to inspect cameras.",
        "Say 'phone root plan' to see what rooting would involve.",
    ]
    return "\n".join(lines)


def _adb_path() -> str | None:
    """Find ADB executable."""
    # Common locations
    candidates = [
        "adb",
        r"C:\platform-tools\adb.exe",
        str(Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"),
        str(Path.home() / "platform-tools/adb.exe"),
    ]
    for c in candidates:
        try:
            r = subprocess.run([c, "version"], capture_output=True, timeout=3)
            if r.returncode == 0:
                return c
        except Exception:
            pass
    return None


def _adb_run(args: list, timeout: int = 15) -> str:
    adb = _adb_path()
    if not adb:
        return "ADB not found. Install Android Platform Tools."
    try:
        r = subprocess.run([adb] + args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)


def _adb_devices() -> list[str]:
    out = _adb_run(["devices"])
    lines = []
    for l in out.splitlines():
        if l and not l.startswith("List") and "\t" in l:
            dev_id, status = l.split("\t", 1)
            lines.append(f"{dev_id.strip()} [{status.strip()}]")
    return lines


# ── Phone Intelligence ────────────────────────────────────────────────────────

def phone_info(device_id: str = "") -> str:
    """
    Get detailed information about a connected Android phone.
    Requires USB debugging enabled on the phone.
    """
    adb = _adb_path()
    if not adb:
        return (
            "ADB not installed.\n"
            "Download: https://developer.android.com/studio/releases/platform-tools\n"
            "Install to C:\\platform-tools\\ then reconnect your phone."
        )

    devs = _adb_devices()
    if not devs:
        return (
            "No Android devices detected via ADB.\n\n"
            "To connect your phone:\n"
            "  1. Go to Settings → About Phone → tap Build Number 7 times\n"
            "  2. Settings → Developer Options → Enable USB Debugging\n"
            "  3. Connect USB cable and tap 'Allow' on your phone"
        )

    target = device_id.strip() if device_id else devs[0].split()[0]

    def _prop(prop: str) -> str:
        return _adb_run(["-s", target, "shell", "getprop", prop]).strip()

    model       = _prop("ro.product.model")
    brand       = _prop("ro.product.brand")
    android_ver = _prop("ro.build.version.release")
    sdk         = _prop("ro.build.version.sdk")
    build       = _prop("ro.build.display.id")
    bootloader  = _prop("ro.bootloader")
    serial      = _prop("ro.serialno")
    arch        = _prop("ro.product.cpu.abi")
    root_status = _adb_run(["-s", target, "shell", "su", "-c", "echo rooted"])

    is_rooted     = "rooted" in root_status.lower()
    bl_raw        = _adb_run(["-s", target, "shell", "getprop", "ro.boot.verifiedbootstate"])
    bl_unlocked   = bl_raw.strip() in ("orange", "yellow")

    # Storage
    storage_raw = _adb_run(["-s", target, "shell", "df", "/data"])
    storage_info = storage_raw.splitlines()[-1] if len(storage_raw.splitlines()) > 1 else "unknown"

    # Battery
    battery_raw  = _adb_run(["-s", target, "shell", "dumpsys", "battery"])
    battery_match = re.search(r'level:\s*(\d+)', battery_raw)
    battery       = battery_match.group(1) + "%" if battery_match else "unknown"

    return "\n".join([
        f"Phone Info: {brand} {model}",
        f"  Android:    {android_ver}  (SDK {sdk})",
        f"  Build:      {build}",
        f"  Arch:       {arch}",
        f"  Bootloader: {bootloader}",
        f"  Serial:     {serial}",
        f"  Battery:    {battery}",
        f"  Rooted:     {'YES' if is_rooted else 'No'}",
        f"  BL Locked:  {'No (unlocked)' if bl_unlocked else 'Yes (locked)'}",
        "",
        f"  ADB ID: {target}",
        "",
        "Next steps:",
        "  • 'phone root plan' — see full rooting walkthrough (no changes yet)",
        "  • 'phone backup' — back up before any mods",
        "  • 'phone adb shell [command]' — run a command on the phone",
    ])


def phone_backup(device_id: str = "") -> str:
    """Back up the phone's app data via ADB before any modding."""
    devs = _adb_devices()
    if not devs:
        return "No Android device connected."
    target   = device_id.strip() if device_id else devs[0].split()[0]
    backup_path = Path.home() / "Documents" / "JARVIS" / "backups" / f"phone_{target}_{datetime.now().strftime('%Y%m%d_%H%M')}.ab"
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    token = _queue_action("adb_command", {
        "device_id": target,
        "command":   f"backup -apk -shared -all -f \"{backup_path}\""
    }, f"ADB backup of {target} → {backup_path}")

    return (
        f"Backup Plan:\n"
        f"  Device:  {target}\n"
        f"  Output:  {backup_path}\n"
        f"  Method:  ADB backup (apps + shared storage)\n\n"
        f"  IMPORTANT: Your phone will ask you to confirm the backup on-screen.\n\n"
        f"  To proceed: say 'device confirm {token}'\n"
        f"  Token expires in 10 minutes."
    )


def phone_root_plan(device_id: str = "") -> str:
    """
    Show a detailed rooting plan for the connected phone.
    Read-only — no changes made. Shows what would happen step by step.
    """
    devs = _adb_devices()
    if not devs:
        return (
            "No Android device connected via ADB.\n"
            "Enable USB Debugging first, then reconnect."
        )
    target = device_id.strip() if device_id else devs[0].split()[0]

    def _prop(p): return _adb_run(["-s", target, "shell", "getprop", p]).strip()

    model       = _prop("ro.product.model")
    brand       = _prop("ro.product.brand")
    android_ver = _prop("ro.build.version.release")
    bl_raw      = _adb_run(["-s", target, "shell", "getprop", "ro.boot.verifiedbootstate"])
    bl_locked   = bl_raw.strip() not in ("orange", "yellow")

    # Rootability assessment
    magisk_url  = "https://github.com/topjohnwu/Magisk/releases"
    twrp_url    = f"https://twrp.me/Devices/"

    warnings = []
    if bl_locked:
        warnings.append("Bootloader is LOCKED — unlocking WIPES all data on the device")
    warnings.append("Root voids warranty on most devices")
    warnings.append("Banking apps (Google Pay, etc.) may stop working until Magisk Hide is configured")

    return "\n".join([
        f"Root Plan: {brand} {model} (Android {android_ver})",
        f"  Device ID: {target}",
        "",
        "WHAT WOULD HAPPEN (no changes yet):",
        "",
        "  Step 1: Back up all data (adb backup)",
        f"  Step 2: {'Unlock bootloader → WIPES device' if bl_locked else 'Bootloader already unlocked — skip'}",
        "  Step 3: Download Magisk APK and patch the boot.img",
        "  Step 4: Flash patched boot.img via fastboot",
        "  Step 5: Reboot and install Magisk Manager",
        "  Step 6: Configure Magisk Hide for banking/SafetyNet apps",
        "",
        "  WARNINGS:",
    ] + [f"    ⚠️  {w}" for w in warnings] + [
        "",
        f"  Resources:",
        f"    Magisk:  {magisk_url}",
        f"    TWRP:    {twrp_url}",
        f"    Guide:   https://xdaforums.com (search your model)",
        "",
        "THIS IS READ-ONLY — no changes were made.",
        "Rooting requires multiple manual steps that cannot be fully automated.",
        "JARVIS can guide you through each step and run ADB/fastboot commands for you.",
        "",
        "To start: say 'phone backup' first (always back up before rooting).",
        "Then: 'phone adb shell [command]' for specific ADB steps.",
    ])


def phone_adb_shell(command: str, device_id: str = "") -> str:
    """
    Plan an ADB shell command on the connected phone.
    Shows what the command does before asking for confirmation.
    """
    devs = _adb_devices()
    if not devs:
        return "No Android device connected."
    target = device_id.strip() if device_id else devs[0].split()[0]

    # Danger assessment
    danger_words = ["rm ", "format", "mkfs", "dd ", "wipe", "flash", "fastboot erase"]
    is_dangerous = any(w in command.lower() for w in danger_words)
    safe_words   = ["ls", "cat", "echo", "getprop", "pm list", "dumpsys", "df ", "ps "]
    is_safe      = any(command.lower().startswith(w) for w in safe_words)

    if is_safe:
        # Run immediately, no confirmation needed
        result = _adb_run(["-s", target, "shell", command])
        _log_action(f"adb shell {command}", result[:200])
        return f"ADB [{target}] $ {command}\n\n{result}"

    token = _queue_action(
        "adb_shell",
        {"device_id": target, "shell_cmd": command},
        f"Run on {target}: adb shell {command}"
    )

    warning = " ⚠️  DESTRUCTIVE COMMAND" if is_dangerous else ""
    return (
        f"ADB Shell Plan:{warning}\n"
        f"  Device:  {target}\n"
        f"  Command: adb shell {command}\n\n"
        f"  This will execute the command on your phone's shell.\n"
        f"  {'WARNING: This could delete or modify system files.' if is_dangerous else 'This command will modify your phone.'}\n\n"
        f"  To execute: say 'device confirm {token}'\n"
        f"  Token expires in 10 minutes."
    )


def _execute_adb(device_id: str, command: str) -> str:
    adb = _adb_path()
    if not adb:
        return "ADB not found."
    parts = command.split()
    result = _adb_run(["-s", device_id] + parts)
    _log_action(f"adb -s {device_id} {command}", result[:200])
    return f"Executed: adb {command}\nResult: {result}"


def _execute_adb_shell(device_id: str, shell_cmd: str) -> str:
    result = _adb_run(["-s", device_id, "shell", shell_cmd])
    _log_action(f"adb shell {shell_cmd}", result[:200])
    return f"$ {shell_cmd}\n{result}"


def _execute_adb_install(device_id: str, apk_path: str) -> str:
    result = _adb_run(["-s", device_id, "install", "-r", apk_path])
    _log_action(f"adb install {apk_path}", result[:200])
    return f"Install result: {result}"


# ── Webcam Intelligence ───────────────────────────────────────────────────────

def webcam_info() -> str:
    """Detect and describe connected webcams/cameras."""
    lines = [f"Webcam / Camera Devices", ""]

    # DirectShow / WMI enumeration
    raw = _run_ps(
        "Get-PnpDevice -PresentOnly -Class Camera,Image | "
        "Select-Object FriendlyName,Status,InstanceId | "
        "Format-List | Out-String -Width 120"
    )
    if not raw.strip() or "No matching" in raw:
        raw = _run_ps(
            "Get-WmiObject Win32_PnPEntity | "
            "Where-Object {$_.Name -like '*camera*' -or $_.Name -like '*webcam*' -or $_.Name -like '*capture*'} | "
            "Select-Object Name,Status | Format-List"
        )

    if raw.strip():
        lines.append("  Detected:")
        for l in raw.splitlines():
            if l.strip() and ("Name" in l or "Friendly" in l):
                lines.append(f"    • {l.split(':', 1)[-1].strip()}")
    else:
        lines.append("  No cameras detected.")

    # Check if OpenCV can open them
    try:
        import cv2
        working = []
        for i in range(4):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                working.append(f"Camera {i}: {w}x{h} @ {fps:.0f}fps")
                cap.release()
        if working:
            lines += ["", "  OpenCV accessible:"] + [f"    ✓ {c}" for c in working]
    except ImportError:
        lines.append("  (Install opencv-python for resolution/fps details)")

    lines += [
        "",
        "Note: Webcam firmware modding is model-specific and rarely needed.",
        "For IP camera setup, say 'network scan' to find devices.",
        "For JARVIS to use the webcam in CS2, vision is already active.",
    ]
    return "\n".join(lines)


# ── Smart Device / IoT ────────────────────────────────────────────────────────

def smart_devices_scan() -> str:
    """
    Scan local network for smart devices (lights, plugs, cameras, etc.).
    Uses ARP + port scanning for common IoT ports.
    """
    lines = ["Smart Device Network Scan", ""]

    arp_raw = _run_ps("arp -a")
    hosts = re.findall(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f\-:]+)', arp_raw, re.IGNORECASE)

    # Common IoT manufacturer OUIs (first 3 octets of MAC)
    iot_ouis = {
        "50:c7:bf": "TP-Link/Tapo", "30:de:4b": "TP-Link",
        "b0:95:75": "Tuya/Smart Life", "a8:42:e3": "Shelly",
        "ec:fa:bc": "Espressif (ESP8266/ESP32)", "e8:db:84": "Espressif",
        "24:62:ab": "Espressif", "dc:4f:22": "Espressif",
        "18:fe:34": "Espressif", "ac:cf:23": "HiLink (Tuya OEM)",
        "68:c6:3a": "Philips Hue", "00:17:88": "Philips Hue",
        "b4:e6:2d": "Lutron", "cc:50:e3": "Espressif",
    }

    iot_found = []
    for ip, mac in hosts:
        mac_prefix = mac.replace("-", ":").lower()[:8]
        for oui, brand in iot_ouis.items():
            if mac_prefix.startswith(oui.lower()):
                iot_found.append({"ip": ip, "mac": mac, "brand": brand})
                break

    if iot_found:
        lines.append("  IoT / Smart Devices Found:")
        for d in iot_found:
            lines.append(f"    • {d['ip']:<16} {d['mac']}  — {d['brand']}")
        lines.append("")

    lines.append(f"  Total network hosts: {len(hosts)}")
    lines += [
        "",
        "Smart device capabilities:",
        "  • Tuya/Smart Life bulbs → Tasmota firmware flash (say 'tasmota plan [ip]')",
        "  • Shelly devices → direct HTTP API control",
        "  • Espressif chips → custom firmware via esptool",
        "",
        "For Tasmota flashing: say 'tasmota plan [device_ip]'",
    ]
    return "\n".join(lines)


def tasmota_plan(device_ip: str, device_type: str = "smart_bulb") -> str:
    """
    Plan a Tasmota firmware flash for a compatible smart device.
    Shows exactly what would happen — no changes made until confirmed.
    """
    token = _queue_action(
        "tasmota_flash",
        {"ip": device_ip, "device_type": device_type},
        f"Flash Tasmota firmware to {device_type} at {device_ip}"
    )

    return "\n".join([
        f"Tasmota Flash Plan: {device_type} at {device_ip}",
        "",
        "WHAT WOULD HAPPEN (no changes yet):",
        "",
        "  Step 1: Check if device is reachable and on same network",
        "  Step 2: Download Tasmota firmware for your device type",
        "            → tasmota.bin (generic) or tasmota-lite.bin",
        "  Step 3: Attempt OTA flash (works on older Tuya firmware)",
        "            OR provide serial flash instructions for newer devices",
        "  Step 4: Configure WiFi and MQTT settings",
        "  Step 5: Test device control via Tasmota web UI",
        "",
        "  BENEFITS of Tasmota:",
        "    ✓ Full local control (no cloud required)",
        "    ✓ Works with Home Assistant, MQTT, Alexa, Google Home",
        "    ✓ Schedule, automation, power monitoring",
        "    ✓ Device stays on your network only",
        "",
        "  RISKS:",
        "    ⚠️  May brick device if power is cut during flash",
        "    ⚠️  Newer Tuya devices (2021+) have patched OTA — require serial flash",
        "    ⚠️  Warranty void",
        "",
        f"  Firmware source: https://github.com/arendst/Tasmota/releases",
        f"  Tool needed:     esptool (pip install esptool)",
        "",
        f"  To proceed: say 'device confirm {token}'",
        f"  Token expires in 10 minutes.",
        "",
        "THIS IS READ-ONLY — nothing has been changed.",
    ])


def _execute_tasmota_flash(params: dict) -> str:
    ip          = params.get("ip", "")
    device_type = params.get("device_type", "smart_bulb")

    # Verify connectivity first
    ping = _run_ps(f"ping -n 1 -w 1000 {ip}")
    if "TTL=" not in ping and "Reply" not in ping:
        return f"Device at {ip} is not reachable. Check IP and WiFi connection."

    # Check if esptool is available
    try:
        r = subprocess.run(["esptool.py", "--help"], capture_output=True, timeout=5)
        has_esptool = r.returncode == 0
    except Exception:
        has_esptool = False

    if not has_esptool:
        return (
            f"esptool not installed. Run: pip install esptool\n\n"
            f"After installing, say 'tasmota plan {ip}' again."
        )

    # For now, provide step-by-step guidance rather than fully automated flash
    # (actual serial flash requires knowing the exact pins and UART adapter)
    return (
        f"Tasmota Flash: {device_type} at {ip}\n\n"
        f"Device is reachable. esptool is available.\n\n"
        f"For OTA flash attempt, open the Tasmota web installer:\n"
        f"  https://tasmota.github.io/install/\n\n"
        f"Or for serial flash, I need to know your UART adapter port.\n"
        f"Say: 'tasmota serial flash {ip} COM3' (replace COM3 with your port)\n\n"
        f"Check Device Manager for your COM port."
    )


def _execute_magisk_push(params: dict) -> str:
    device_id = params.get("device_id", "")
    apk_path  = params.get("apk_path", "")
    if not apk_path or not Path(apk_path).exists():
        return f"Magisk APK not found at {apk_path}. Download it first from https://github.com/topjohnwu/Magisk/releases"
    result = _adb_run(["-s", device_id, "install", apk_path])
    _log_action(f"magisk install on {device_id}", result[:200])
    return f"Magisk install result:\n{result}"


# ── Device log ────────────────────────────────────────────────────────────────

def device_log() -> str:
    """Show recent device actions performed by JARVIS."""
    try:
        log = json.loads(_LOG_FILE.read_text(encoding="utf-8")) if _LOG_FILE.exists() else []
        if not log:
            return "No device actions logged yet."
        lines = [f"Device Action Log ({len(log)} entries)", ""]
        for e in reversed(log[-20:]):
            lines.append(f"  {e['time'][:16]}  {e['action'][:60]}")
        return "\n".join(lines)
    except Exception:
        return "Error reading device log."


def device_pending() -> str:
    """Show all pending device actions waiting for confirmation."""
    pending = _pending_load()
    if not pending:
        return "No pending device actions."
    lines = ["Pending Device Actions (require 'device confirm [token]'):", ""]
    now = time.time()
    for token, a in pending.items():
        mins_left = max(0, int((a.get("expires", now) - now) / 60))
        lines.append(f"  [{token}] {a['description']} ({mins_left}m remaining)")
    return "\n".join(lines)
