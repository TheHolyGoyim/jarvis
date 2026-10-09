"""
remote.py â€” JARVIS Remote Access Manager
Exposes JARVIS to the internet so you can reach it from your phone over cellular.

Usage:
  python remote.py          â†’ starts ngrok tunnel + shows QR code
  python remote.py setup    â†’ interactive setup wizard

Requirements:
  pip install pyngrok
  Get a free ngrok account at ngrok.com (needed for stable URLs)
"""

import os, sys, json, time, subprocess, threading, secrets, string
from pathlib import Path
from datetime import datetime

ROOT     = Path(__file__).parent
ENV_FILE = ROOT / ".env"
URL_FILE = ROOT / ".tunnel_url"   # written so server.py can read it

# â”€â”€ .env helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _env_load() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def _env_set(key: str, value: str):
    env  = _env_load()
    env[key] = value
    lines = []
    if ENV_FILE.exists():
        raw = ENV_FILE.read_text(encoding="utf-8").splitlines()
        written = False
        for line in raw:
            if line.strip().startswith(key + "="):
                lines.append(f'{key}="{value}"')
                written = True
            else:
                lines.append(line)
        if not written:
            lines.append(f'{key}="{value}"')
    else:
        lines = [f'{key}="{value}"']
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_get(key: str, default: str = "") -> str:
    return _env_load().get(key, os.getenv(key, default))


# â”€â”€ API key management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _gen_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return "jrv_" + "".join(secrets.choice(alphabet) for _ in range(32))


def ensure_api_key() -> str:
    key = _env_get("JARVIS_API_KEY")
    if not key:
        key = _gen_api_key()
        _env_set("JARVIS_API_KEY", key)
        print(f"Generated new API key: {key}")
    return key


# â”€â”€ Terminal QR code (ASCII art) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _qr_ascii(data: str) -> str:
    """Generate a minimal QR-like display. Uses qrcode library if available."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(data)
        qr.make(fit=True)
        f = qr.make_image(fill_color="black", back_color="white")
        # Print ASCII
        import io
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        return buf.getvalue()
    except ImportError:
        return "(Install qrcode for QR: pip install qrcode)"


def _print_banner(url: str, api_key: str):
    print()
    print("=" * 60)
    print("  JARVIS REMOTE ACCESS")
    print("=" * 60)
    print()
    print(f"  Public URL:  {url}")
    print(f"  API Key:     {api_key}")
    print()
    print("  Phone setup:")
    print(f"  1. Open JARVIS on your phone")
    print(f"  2. Tap âš™ï¸ Settings")
    print(f"  3. Paste URL: {url}")
    print(f"  4. Paste API key: {api_key}")
    print(f"  5. Tap SAVE & CONNECT")
    print()
    print("  QR Code for URL:")
    qr = _qr_ascii(f"{url}|{api_key}")
    print(qr)
    print("=" * 60)
    print()


# â”€â”€ Ngrok tunnel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _find_ngrok() -> str:
    """Locate the ngrok binary from PATH or common install locations."""
    import shutil
    found = shutil.which("ngrok")
    if found:
        return found
    candidates = [
        Path.home() / "AppData" / "Local" / "ngrok" / "ngrok.exe",   # winget default
        Path("C:/ngrok/ngrok.exe"),
        Path("C:/tools/ngrok/ngrok.exe"),
        Path("/usr/local/bin/ngrok"),   # macOS / Linux
        Path("/usr/bin/ngrok"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "ngrok"   # last resort â€” hope it's on PATH


def _start_ngrok(port: int = 5005) -> str | None:
    try:
        from pyngrok import ngrok, conf

        ngrok_path = _find_ngrok()
        cfg = conf.PyngrokConfig(ngrok_path=ngrok_path)
        conf.set_default(cfg)

        token = _env_get("NGROK_AUTH_TOKEN")
        if token:
            cfg.auth_token = token

        tunnel = ngrok.connect(port, "http")
        url    = tunnel.public_url.replace("http://", "https://")
        return url
    except ImportError:
        print("pyngrok not installed. Run: pip install pyngrok")
        return None
    except Exception as e:
        print(f"ngrok error: {e}")
        if "authentication" in str(e).lower() or "authtoken" in str(e).lower():
            print()
            print("  Free ngrok account needed:")
            print("  1. Sign up at https://ngrok.com (free)")
            print("  2. Copy your auth token from https://dashboard.ngrok.com/get-started/your-authtoken")
            print("  3. Run: python remote.py setup")
        return None


def _try_cloudflare(port: int = 5005) -> str | None:
    """Try cloudflared as fallback."""
    try:
        r = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        # Read output until we see the URL
        import re
        for _ in range(60):
            line = r.stderr.readline()
            if not line:
                time.sleep(0.5)
                continue
            m = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
            if m:
                return m.group(0)
        return None
    except FileNotFoundError:
        return None


def _try_tailscale() -> str | None:
    """Get Tailscale IP if running."""
    try:
        r = subprocess.run(["tailscale", "ip"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ip = r.stdout.strip().split()[0]
            return f"http://{ip}:5005"
    except Exception:
        pass
    return None


# â”€â”€ Setup wizard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def setup_wizard():
    print()
    print("JARVIS Remote Access Setup")
    print("-" * 40)
    print()
    print("Choose your connection method:")
    print()
    print("  [1] ngrok (recommended â€” works everywhere, free account needed)")
    print("      â†’ Public HTTPS URL, works over cellular")
    print("      â†’ Get free account at https://ngrok.com")
    print()
    print("  [2] Tailscale (best for permanent use â€” free personal plan)")
    print("      â†’ Private network between your devices, no public URL")
    print("      â†’ Download at https://tailscale.com")
    print()
    print("  [3] Cloudflare Tunnel (free, no account needed for testing)")
    print("      â†’ Download cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
    print()

    choice = input("Choose [1/2/3]: ").strip()
    print()

    if choice == "1":
        token = input("Paste your ngrok auth token (from dashboard.ngrok.com): ").strip()
        if token:
            _env_set("NGROK_AUTH_TOKEN", token)
            print("Token saved.")

    elif choice == "2":
        print("Tailscale setup:")
        print("  1. Download Tailscale: winget install tailscale OR https://tailscale.com/download")
        print("  2. Install and log in on your PC")
        print("  3. Install Tailscale on your phone (iOS/Android)")
        print("  4. Log in with the same account")
        print("  5. Run: python remote.py")
        print()
        print("Tailscale gives your PC a stable 100.x.x.x IP.")
        print("Enter that IP in JARVIS settings on your phone (e.g. http://100.64.1.2:5005)")
        return

    elif choice == "3":
        print("Cloudflare Tunnel setup:")
        print("  1. Download cloudflared.exe from:")
        print("     https://github.com/cloudflare/cloudflared/releases/latest")
        print("  2. Place cloudflared.exe in C:\\cloudflared\\ and add to PATH")
        print("  3. Run: python remote.py")
        return

    # Generate API key
    key = ensure_api_key()
    print(f"API key set: {key}")
    print()
    print("Setup complete. Run: python remote.py")


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def start(port: int = 5005):
    print(f"[REMOTE] Starting JARVIS remote access on port {port}...")

    api_key = ensure_api_key()
    url     = None

    # Try ngrok first
    url = _start_ngrok(port)

    # Try Cloudflare tunnel
    if not url:
        print("[REMOTE] Trying Cloudflare tunnel...")
        url = _try_cloudflare(port)

    # Try Tailscale
    if not url:
        ts_url = _try_tailscale()
        if ts_url:
            url = ts_url
            print(f"[REMOTE] Tailscale detected: {url}")

    if not url:
        print("[REMOTE] Could not start any tunnel.")
        print()
        print("Options:")
        print("  1. Install pyngrok and get a free ngrok account:")
        print("     pip install pyngrok")
        print("     Sign up at https://ngrok.com")
        print("     Then run: python remote.py setup")
        print()
        print("  2. Install Tailscale (recommended for permanent use):")
        print("     https://tailscale.com/download")
        print()
        print("  3. On your home WiFi, use your PC's local IP:")
        import socket
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            print(f"     Local IP: http://{local_ip}:{port}")
        except Exception:
            print("     Run 'ipconfig' to find your local IP")
        return

    # Write URL file so server.py can report it
    URL_FILE.write_text(json.dumps({
        "url":     url,
        "api_key": api_key,
        "started": datetime.now().isoformat(),
    }), encoding="utf-8")

    _print_banner(url, api_key)

    print("[REMOTE] Tunnel active. Press Ctrl+C to stop.")
    print("[REMOTE] Starting JARVIS server...")
    print()

    # Start JARVIS server in this same process context
    try:
        # Import and start server
        sys.path.insert(0, str(ROOT))
        import server as _srv
        _srv.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n[REMOTE] Shutting down.")
        URL_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup_wizard()
    else:
        port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5005
        start(port)
