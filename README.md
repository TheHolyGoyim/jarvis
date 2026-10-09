# JARVIS — Self-Learning Personal AI Assistant

A fully local, self-hosted AI assistant template that runs on your own Windows PC and grows into an extension of yourself. Completely private — inference runs on your machine via Ollama, your data never leaves it. No subscription, no cloud brain, no shared backend.

JARVIS is not limited to one job. The same assistant that manages your day can autonomously trade a stock budget, monitor your positions in real time, control your PC, and learn your phrasing, corrections, and preferences the longer you use it.

## What JARVIS Can Do

- **Self-learning memory** — every conversation persists across restarts (SQLite), corrections you give ("no, that's wrong") are captured automatically, older history auto-consolidates into a rolling summary, and the Commands tab learns *your* phrasing for each tool
- **Autonomous trading** (Alpaca, paper or live) — a 7-signal conviction engine (technicals, social sentiment, news, geopolitics, options flow, Fear & Greed, insider filings) scores the entire NYSE/NASDAQ universe, executes bracket orders inside a hard budget cap, and a background monitor hawks every position: breakeven stops, trailing stops, partial profit-taking, RSI cuts, thesis re-checks, scale-ins
- **Real-time trade tape** — continuous WebSocket stream of live NYSE/NASDAQ prints (Alpaca IEX, free) used as an execution gate and fast exit signal — not just polled snapshots
- **Market intelligence** — live quotes, multi-timeframe TA, charts (rendered as images in chat), sector rotation, short-squeeze scans, gamma exposure, VIX term structure, congress trades, SEC filings, crypto
- **Daily life** — tasks, habits, notes, reminders, morning briefings, bills, budgets, groceries
- **PC control** — open apps, screenshots, lock, volume, system info, disk cleanup
- **Games** — CS2 AI assist, Fall Guys bot, generic game AI, controller emulation
- **Web research** — DuckDuckGo + Wikipedia lookups JARVIS actually reads (keyless, free)
- **Remote access** — reach JARVIS from your phone over cellular via ngrok tunnel
- **Voice I/O** — tap the mic to speak to JARVIS (local speech-to-text via faster-whisper) and have replies read back in a voice you pick (local text-to-speech via SAPI, with named presets you can create/rename/delete in Settings). Fully local, no cloud speech API. Mic input requires a secure context (HTTPS or localhost) — on your iPhone that means connecting through the `python remote.py` ngrok tunnel, not a plain `http://` LAN address
- **150+ tools** dispatched by natural language — no rigid command syntax

---

## Requirements

- **Windows 10/11** (64-bit)
- **Python 3.10+** — [python.org](https://python.org) — check "Add Python to PATH"
- **Ollama** — [ollama.com](https://ollama.com) — runs the local AI model
- **~12GB VRAM or RAM** for the default brain model (`qwen2.5:14b-instruct`); set `JARVIS_MODEL` to a smaller model like `qwen2.5:7b-instruct` on lighter hardware

Optional for remote phone access: **ngrok** free account — [ngrok.com](https://ngrok.com)

---

## Installation

### 1. Get the code

```
git clone https://github.com/YOUR_USERNAME/jarvis4
cd jarvis4
```

Or download and extract the ZIP.

### 2. Configure

Copy the environment template:
```
copy .env.example .env
```

Open `.env` and set at minimum:
```
JARVIS_USER_NAME="Your Name"
```

Everything else is optional — JARVIS generates its own API key on first run.

### 3. Start JARVIS

First time: double-click **`START_JARVIS.bat`** — it walks you through setup,
downloads the AI model from your `JARVIS_MODEL` setting (several GB, one time
only), creates a **JARVIS desktop shortcut**, and launches.

Every time after: double-click the **JARVIS desktop icon**. It starts Ollama +
the server (hidden) and opens the app window — the web UI is the one and only
frontend (same UI as the phone). A small control panel handles restart /
model pull / shutdown. Closing the panel leaves JARVIS running.

---

## Accessing JARVIS

### On this PC

```
http://localhost:5005/app
```

### Same WiFi (phone or PC)

Run `ipconfig` in a terminal, find your IPv4 address, then open:
```
http://192.168.x.x:5005/app
```

### Over cellular from your phone (ngrok)

1. Create a free account at [ngrok.com](https://ngrok.com)
2. Add your auth token to `.env`: `NGROK_AUTH_TOKEN="your_token_here"`
3. Start JARVIS — the public `https://` URL appears in the console
4. Open that URL on your phone → Share → Add to Home Screen to install as an app

### API Key (for remote access)

JARVIS generates a unique API key automatically on first run, saved in `.env` as `JARVIS_API_KEY`. Enter it in the phone app under Settings when connecting remotely. Sessions last 180 days.

---

## Autonomous Trading (Optional)

Free paper-trading account at [alpaca.markets](https://alpaca.markets) — no real money required. Add to `.env`:

```
ALPACA_API_KEY="your_key"
ALPACA_API_SECRET="your_secret"
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```

> ⚠ **Capital limits are live and percent-based.** JARVIS reads buying power from your Alpaca account and sizes every position by conviction tier × the Markets-dashboard risk profile (max position %, daily loss %, cash reserve %). There is no dollar cap in `.env`. Keep `ALPACA_BASE_URL` on the paper URL until you have watched it trade for a while and trust it.

Then try, in plain English:

| Say | JARVIS does |
|---|---|
| `auto hunt` | scans the full NYSE/NASDAQ universe, ranks the top setups |
| `auto hunt and trade` | executes the best affordable setup as a bracket order |
| `budget status` | mission tracker: deployed, available, P&L, progress to goal |
| `why did you buy SOFI` | the exact signal breakdown stored at decision time |
| `what's moving right now` | real-time buy/sell pressure from the live tape |
| `conviction score NVDA` | full 0–100 signal breakdown with chart |
| `show my portfolio` | live positions, history, win rate |

While any position is open, the background monitor re-checks it every 30 seconds and manages stops, profit-taking, and early exits on its own. Everything it does is logged and journaled with reasoning.

---

## Optional Features

### Game AI (CS2 / Fall Guys)

```
pip install vgamepad inputs pyautogui keyboard
ollama pull llama3        (lower-latency model used only by game modules)
```

ViGEmBus driver needed for controller emulation — JARVIS prompts you to install it on first use. For CS2 enemy detection, say `setup yolo` (downloads ~6MB model).

---

## Project Structure

```
jarvis4/
  server.py            — Flask server: routes, tool registry, NL dispatch, LLM loop
  remote.py            — ngrok tunnel manager
  auto_trade_daily.py  — scheduled daily trading runner (Windows Task Scheduler)
  game_ai.py / cs2_*.py / fallguys_ai.py / controller.py — game AI stack
  tools/
    tools.py           — general life tools (tasks, finance, health, ...)
    market.py          — TA indicators, intraday analysis, watchlists, charts
    trading.py         — Alpaca orders, risk guard, budget cap, strategies
    conviction.py      — 7-signal conviction engine + universe screener + auto-hunt
    trade_monitor.py   — background position monitor (stops, exits, scale-ins)
    trade_stream.py    — real-time NYSE/NASDAQ trade tape (WebSocket, free IEX feed)
    options_engine.py  — options chains, buys, positions, unusual activity
    social_intel.py    — StockTwits + Reddit + retail order-flow sentiment
    intel.py           — Fear & Greed, insider trades, SEC filings, web research
    flow_intel.py      — gamma exposure, VIX term structure, congress trades
    math_engine.py     — full math engine (arithmetic→calculus/ODEs, sympy) +
                         quant pattern lab (Hurst, autocorrelation, FFT cycles,
                         pair correlation) on real price history
    political_intel.py — role-based political intelligence: impact maps per
                         role (president/Fed/Treasury/OPEC/CEOs...), 15-min
                         news scanner, geo risk score 0-100 driving sizing
    opportunity_scan.py— broad (30min) + narrow (5min) market scanners feeding
                         a ranked opportunity queue with auto-fill
    bridge_map.py      — cross-sector bridge companies (infrastructure /
                         transition / picks-and-shovels) weighted in hunts
    risk_params.py     — Markets-dashboard risk parameters, enforced across
                         the whole trading pipeline
    assistant_tools.py — everyday assistant: real weather (Open-Meteo), timed
                         reminders/timers that fire into the chat, unit +
                         currency conversion, world time, dictionary, holidays,
                         file finder, passwords, dice/coin — all free/keyless
    jarvis_memory.py   — self-learning memory: conversations, corrections, stats
    charts.py          — headless matplotlib charts rendered into the chat
    devices.py         — device detection (with approval gates)
  app/
    index.html         — phone/browser PWA interface
    manifest.json      — PWA install manifest
    sw.js              — service worker for offline support
  jarvis_app.py        — THE launcher (desktop shortcut target): boots
                         Ollama + server, opens the app window + control panel
  START_JARVIS.bat     — first-run setup wizard, then hands off to jarvis_app.py
  install_shortcut.vbs — (re)creates the JARVIS desktop shortcut
  requirements.txt     — Python dependencies
  .env.example         — configuration template
```

---

## Privacy

- All AI inference runs locally via Ollama — no prompts or data sent to any cloud AI
- Conversations, learned preferences, and trade journals live in `~/Documents/JARVIS/` and a local SQLite DB — on your machine only
- `.env`, sessions, and tunnel state are in `.gitignore` — they will not be committed if you fork this repo
- Each person who clones JARVIS gets a completely separate, isolated instance
- Market data and news require internet (Alpaca, RSS, public APIs) — the brain itself does not

---

## Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `JARVIS_USER_NAME` | Recommended | What JARVIS calls you |
| `JARVIS_MODEL` | Recommended | Ollama brain model (default `qwen2.5:14b-instruct`) |
| `JARVIS_API_KEY` | Auto-generated | Phone auth key (don't change) |
| `NGROK_AUTH_TOKEN` | For remote access | From ngrok.com dashboard |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | For trading | From alpaca.markets |
| `ALPACA_BASE_URL` | For trading | Keep the paper URL until you trust it |
| `TRADING_GOAL` | Optional | Fallback capital target shown when no goal engine goal is set |

Position sizing, daily loss limits, and cash reserve are configured as **percentages of live buying power** in the 📈 Markets tab (risk profiles: conservative → moderate → aggressive → high risk → speculative).
