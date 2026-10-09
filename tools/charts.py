"""
charts.py — JARVIS Visual Analysis Engine

Renders findings as PNG charts instead of ASCII-only text: sector heat maps,
market scans, conviction breakdowns, price/TA charts. Saved under
~/Documents/JARVIS/charts/ (inside the shared JARVIS files dir), so server.py's
existing file-attachment pipeline (_extract_file_refs) picks up the path from
the returned text automatically and the web UI shows it inline in chat.

Callers just append the returned path to their text reply, e.g.:
    path = CHARTS.sector_heat_chart(results)
    lines.append(f"Chart saved: {path}")
"""

from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_CHART_DIR = Path.home() / "Documents" / "JARVIS" / "charts"
_CHART_DIR.mkdir(parents=True, exist_ok=True)

# ── JARVIS UI color palette (matches app/index.html dark theme) ────────────────
_BG      = "#080810"
_PANEL   = "#111120"
_BORDER  = "#1e1e32"
_ACCENT  = "#00d4ff"
_ACCENT2 = "#7b5ea7"
_GREEN   = "#00ff9d"
_RED     = "#ff3b6b"
_TEXT    = "#e8eaf0"
_MUTED   = "#8a8aa8"


def _style(fig, ax) -> None:
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_PANEL)
    ax.tick_params(colors=_TEXT, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(_BORDER)
    ax.title.set_color(_TEXT)
    ax.xaxis.label.set_color(_MUTED)
    ax.yaxis.label.set_color(_MUTED)
    ax.grid(axis="x", color=_BORDER, linewidth=0.6, alpha=0.6)


def _save(fig, prefix: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _CHART_DIR / f"{prefix}_{ts}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(path)


def sector_heat_chart(results: list) -> str:
    """Horizontal bar chart of sector day-change %, sorted strongest-first."""
    if not results:
        return ""
    labels = [f"{r['sector']} ({r['proxy']})" for r in results]
    values = [r.get("day_chg", 0) for r in results]
    colors = [_GREEN if v >= 0 else _RED for v in values]

    fig, ax = plt.subplots(figsize=(7.5, 0.55 * len(results) + 1.2))
    y = range(len(results))
    ax.barh(y, values, color=colors)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.axvline(0, color=_MUTED, linewidth=0.8)
    ax.set_xlabel("Day Change %")
    ax.set_title(f"Sector Heat Map — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    span = max(values) - min(values) or 1.0
    pad  = span * 0.18
    ax.set_xlim(min(values) - pad, max(values) + pad)
    for i, v in enumerate(values):
        offset = span * 0.02
        ax.text(v + (offset if v >= 0 else -offset), i, f"{v:+.2f}%", va="center",
                ha="left" if v >= 0 else "right", color=_TEXT, fontsize=8)
    _style(fig, ax)
    return _save(fig, "sector_heat")


def market_scan_chart(results: list) -> str:
    """Horizontal bar chart of TA scores per symbol, green/red by direction."""
    if not results:
        return ""
    ranked = sorted(results, key=lambda x: x.get("score", 0))
    labels = [r.get("symbol", "?") for r in ranked]
    values = [r.get("score", 0) for r in ranked]
    colors = [_GREEN if v > 0 else _RED if v < 0 else _MUTED for v in values]

    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(ranked) + 1.2))
    y = range(len(ranked))
    ax.barh(y, values, color=colors)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.axvline(0, color=_MUTED, linewidth=0.8)
    ax.set_xlabel("TA Score (-10 bearish → +10 bullish)")
    ax.set_title(f"Market Scan — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    _style(fig, ax)
    return _save(fig, "market_scan")


def conviction_breakdown_chart(symbol: str, total: int, breakdown: dict) -> str:
    """Bar chart of the multi-signal conviction breakdown for one symbol."""
    if not breakdown:
        return ""
    labels = list(breakdown.keys())
    values = list(breakdown.values())

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(labels, values, color=_ACCENT)
    ax.set_title(f"{symbol.upper()} Conviction Breakdown — {total}/100")
    ax.set_ylabel("Points")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right", fontsize=8)
    _style(fig, ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=_BORDER, linewidth=0.6, alpha=0.6)
    return _save(fig, f"conviction_{symbol.lower()}")


def price_chart(symbol: str, bars: list, ta: dict = None) -> str:
    """
    Price line chart with moving-average overlays (from a TA dict, if given)
    and an RSI sub-panel when available. `bars` = list of {date, close, ...}.
    """
    if not bars:
        return ""
    ta = ta or {}
    dates  = [b["date"] for b in bars]
    closes = [b["close"] for b in bars]

    has_rsi = ta.get("rsi") is not None and len(bars) >= 15
    if has_rsi:
        fig, (ax, ax2) = plt.subplots(
            2, 1, figsize=(8.5, 5.5), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
        )
    else:
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        ax2 = None

    ax.plot(dates, closes, color=_ACCENT, linewidth=1.6, label="Close")

    def _sma(n, color, label):
        if len(closes) >= n:
            vals = [sum(closes[max(0, i - n + 1):i + 1]) / len(closes[max(0, i - n + 1):i + 1])
                    for i in range(len(closes))]
            ax.plot(dates, vals, color=color, linewidth=1.0, linestyle="--", label=label, alpha=0.85)

    _sma(20, _ACCENT2, "SMA20")
    _sma(50, _GREEN,   "SMA50")
    if ta.get("sma200"):
        _sma(200, _RED, "SMA200")

    step = max(1, len(dates) // 8)
    ax.set_xticks(dates[::step])
    plt.setp(ax.get_xticklabels(), rotation=40, ha="right", fontsize=7)
    ax.set_title(f"{symbol.upper()} — Price  (${closes[-1]:,.2f})")
    ax.legend(facecolor=_PANEL, edgecolor=_BORDER, labelcolor=_TEXT, fontsize=8, loc="upper left")
    _style(fig, ax)

    if ax2 is not None:
        # Simple rolling RSI series for the sub-panel (14-period)
        rsi_vals = []
        n = 14
        for i in range(len(closes)):
            window = closes[max(0, i - n):i + 1]
            if len(window) < 2:
                rsi_vals.append(50)
                continue
            gains  = [max(window[j] - window[j-1], 0) for j in range(1, len(window))]
            losses = [max(window[j-1] - window[j], 0) for j in range(1, len(window))]
            ag, al = sum(gains) / len(gains), sum(losses) / len(losses)
            rsi_vals.append(100 if al == 0 else round(100 - 100 / (1 + ag / al), 1))
        ax2.plot(dates, rsi_vals, color=_ACCENT2, linewidth=1.2)
        ax2.axhline(70, color=_RED,   linewidth=0.7, linestyle=":")
        ax2.axhline(30, color=_GREEN, linewidth=0.7, linestyle=":")
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("RSI")
        _style(fig, ax2)

    return _save(fig, f"price_{symbol.lower()}")


def bar_chart(title: str, labels: list, values: list, xlabel: str = "") -> str:
    """Generic labeled bar chart — fallback for any ad hoc 'chart X' request."""
    if not labels or not values:
        return ""
    colors = [_GREEN if v >= 0 else _RED for v in values]
    fig, ax = plt.subplots(figsize=(7, 0.5 * len(labels) + 1.2))
    y = range(len(labels))
    ax.barh(y, values, color=colors)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.axvline(0, color=_MUTED, linewidth=0.8)
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.set_title(title)
    _style(fig, ax)
    return _save(fig, "chart")
