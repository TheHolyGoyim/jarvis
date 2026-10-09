@echo off
setlocal enabledelayedexpansion
title JARVIS v4.4  —  AI Trading Butler
color 0B
cls

echo.
echo  ============================================================
echo    JARVIS v4.4  --  AI Trading Butler
echo  ============================================================
echo.

REM ── Lock to this folder ──────────────────────────────────────
cd /d "%~dp0"

REM ── Python check ─────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH.
    echo.
    echo         Download Python 3.11+ from https://python.org
    echo         During install, check "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [ OK ] %%v found

REM ── server.py check ──────────────────────────────────────────
if not exist "server.py" (
    echo [ERROR] server.py not found.
    echo         Make sure START_JARVIS.bat is inside the jarvis4 folder.
    echo.
    pause
    exit /b 1
)

REM ── First-run: create .env from template ─────────────────────
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [ OK ] Created .env from template
    ) else (
        echo. > .env
    )
)

REM ── First-run: ask for user name ─────────────────────────────
findstr /i "JARVIS_USER_NAME" .env | findstr /v "Your Name" | findstr /v '=""' >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ── First-Time Setup ─────────────────────────────────────
    echo.
    set /p UNAME="  What should JARVIS call you? "
    if not "!UNAME!"=="" (
        python -c "
import re, pathlib
env = pathlib.Path('.env').read_text(encoding='utf-8')
env = re.sub(r'JARVIS_USER_NAME=.*', 'JARVIS_USER_NAME=\"!UNAME!\"', env)
if 'JARVIS_USER_NAME' not in env:
    env += '\nJARVIS_USER_NAME=\"!UNAME!\"\n'
pathlib.Path('.env').write_text(env, encoding='utf-8')
"
        echo [ OK ] Welcome, !UNAME!. JARVIS will remember your name.
    )
    echo.
    echo  ── Alpaca Trading Account (optional but recommended) ─────
    echo  JARVIS can trade stocks for you via Alpaca Markets.
    echo  Paper trading is FREE — no real money needed to start.
    echo  Sign up at https://alpaca.markets and paste your keys.
    echo.
    set /p ALKEY="  Alpaca API Key (Enter to skip): "
    if not "!ALKEY!"=="" (
        set /p ALSEC="  Alpaca API Secret: "
        python -c "
import re, pathlib
env = pathlib.Path('.env').read_text(encoding='utf-8')
env = re.sub(r'ALPACA_API_KEY=.*', 'ALPACA_API_KEY=\"!ALKEY!\"', env)
env = re.sub(r'ALPACA_API_SECRET=.*', 'ALPACA_API_SECRET=\"!ALSEC!\"', env)
if 'ALPACA_API_KEY' not in env:
    env += '\nALPACA_API_KEY=\"!ALKEY!\"\n'
if 'ALPACA_API_SECRET' not in env:
    env += '\nALPACA_API_SECRET=\"!ALSEC!\"\n'
pathlib.Path('.env').write_text(env, encoding='utf-8')
"
        echo [ OK ] Alpaca keys saved. Paper trading is active by default.
    )
    echo.
    echo  ── Remote Access via ngrok (optional) ───────────────────
    echo  For phone access over cellular. Skip to use on WiFi only.
    echo.
    set /p NGTOK="  ngrok auth token (Enter to skip): "
    if not "!NGTOK!"=="" (
        python -c "
import re, pathlib
env = pathlib.Path('.env').read_text(encoding='utf-8')
env = re.sub(r'NGROK_AUTH_TOKEN=.*', 'NGROK_AUTH_TOKEN=\"!NGTOK!\"', env)
if 'NGROK_AUTH_TOKEN' not in env:
    env += '\nNGROK_AUTH_TOKEN=\"!NGTOK!\"\n'
pathlib.Path('.env').write_text(env, encoding='utf-8')
"
        echo [ OK ] ngrok token saved.
    )
    echo.
)

REM ── Install / update packages ─────────────────────────────────
echo [....] Installing required packages...
python -m pip install -r requirements.txt --quiet --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] Some packages failed to install. Retrying without --quiet...
    python -m pip install -r requirements.txt --no-warn-script-location
)
echo [ OK ] Packages ready

REM ── Resolve the brain model from .env (JARVIS_MODEL) ──────────
set JARVIS_MODEL=
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /i "%%a"=="JARVIS_MODEL" set JARVIS_MODEL=%%b
    )
)
if defined JARVIS_MODEL set JARVIS_MODEL=!JARVIS_MODEL:"=!
if "!JARVIS_MODEL!"=="" set JARVIS_MODEL=qwen2.5:14b-instruct

REM ── Ollama check and start ────────────────────────────────────
echo [....] Starting Ollama AI engine...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Ollama not found. AI reasoning will fall back to rule-based responses.
    echo        Install from https://ollama.com — then run: ollama pull !JARVIS_MODEL!
    echo.
    goto :skip_ollama
)
REM Start ollama serve if nothing is actually LISTENING on port 11434.
REM (The old "tasklist | findstr ollama" check matched the tray helper
REM  "ollama app.exe" even when the API server wasn't running.)
netstat -ano | findstr /c:":11434" | findstr /i "LISTENING" >nul
if %errorlevel% neq 0 (
    start "Ollama" /min cmd /c "ollama serve"
    timeout /t 5 /nobreak >nul
)
echo [ OK ] Ollama ready

REM ── Pull the brain model if not present ───────────────────────
ollama list 2>nul | findstr /i /c:"!JARVIS_MODEL!" >nul
if %errorlevel% neq 0 (
    echo [....] Downloading !JARVIS_MODEL! — first time only, several GB...
    ollama pull !JARVIS_MODEL!
    if %errorlevel% neq 0 (
        echo [WARN] Could not download model. Trading tools still work without it.
    ) else (
        echo [ OK ] !JARVIS_MODEL! ready
    )
) else (
    echo [ OK ] AI model ready ^(!JARVIS_MODEL!^)
)

:skip_ollama

REM ── Get local IP ──────────────────────────────────────────────
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "169.254"') do (
    set LOCAL_IP=%%a
    set LOCAL_IP=!LOCAL_IP: =!
    goto :got_ip
)
:got_ip
if "!LOCAL_IP!"=="" set LOCAL_IP=localhost

REM ── Create desktop shortcut on first run ─────────────────────
if exist "install_shortcut.vbs" (
    if not exist "%USERPROFILE%\Desktop\JARVIS.lnk" (
        cscript //nologo "install_shortcut.vbs" >nul 2>&1
        if %errorlevel%==0 (
            echo [ OK ] Desktop shortcut created
        )
    )
)

REM ── Launch JARVIS via the ONE canonical launcher ──────────────
REM jarvis_app.py boots Ollama + the server (hidden) and opens the web
REM app window. Same thing the desktop shortcut does — this .bat is just
REM first-run setup that ends by handing off to it.
echo.
echo  ============================================================
echo    Setup complete — launching JARVIS...
echo.
echo    Desktop app window opens automatically.
echo    Phone ^(same WiFi^): http://!LOCAL_IP!:5005/app
echo  ============================================================
echo.
start "" pythonw "%~dp0jarvis_app.py"
timeout /t 3 /nobreak >nul
exit /b 0
