"""
tools/bridge_map.py — cross-sector bridge companies.

Companies operating across multiple sectors at once are the highest-value
hunt targets: multiple simultaneous tailwinds. Three categories:
  A infrastructure — every sector needs them to function
  B transition     — sit exactly on a boundary between sectors
  C picks_shovels  — sell the tools every competitor in a hot sector must buy

The seed map below is static; Jarvis extends it at runtime via bridge_add()
(persisted in store.py key 'bridge_map_custom') as it discovers new bridges
through research. conviction.auto_hunt() weights these higher in ranking and
always names the bridged sectors in trade reasoning.
"""

from tools.store import get, put

_KEY = "bridge_map_custom"

# ticker: (category, [sectors], note)
_SEED = {
    # ── A: infrastructure bridges ──
    "AMZN":  ("infrastructure", ["Technology", "Consumer", "Communication"], "AWS powers every sector + retail"),
    "MSFT":  ("infrastructure", ["Technology", "Communication", "Industrials"], "Azure/cloud underpins every sector"),
    "GOOGL": ("infrastructure", ["Technology", "Communication"], "GCP + ads infrastructure"),
    "V":     ("infrastructure", ["Financials", "Technology", "Consumer"], "payment rails — every transaction"),
    "MA":    ("infrastructure", ["Financials", "Technology", "Consumer"], "payment rails — every transaction"),
    "PYPL":  ("infrastructure", ["Financials", "Technology", "Consumer"], "digital payment rails"),
    "SQ":    ("infrastructure", ["Financials", "Technology", "Consumer"], "merchant payment rails"),
    "UPS":   ("infrastructure", ["Industrials", "Consumer", "Technology"], "every physical product moves through"),
    "FDX":   ("infrastructure", ["Industrials", "Consumer", "Technology"], "logistics backbone"),
    "XPO":   ("infrastructure", ["Industrials", "Consumer"], "freight/logistics"),
    "SAIA":  ("infrastructure", ["Industrials", "Consumer"], "LTL freight"),
    "TSM":   ("infrastructure", ["Technology", "Industrials", "Communication"], "foundry for every electronic device"),
    "INTC":  ("infrastructure", ["Technology", "Industrials"], "chips + foundry"),
    "ASML":  ("infrastructure", ["Technology", "Industrials"], "the only EUV lithography source"),
    # ── B: sector-transition companies ──
    "TSLA":  ("transition", ["Consumer", "Energy", "Technology"], "auto + energy storage + tech"),
    "GEV":   ("transition", ["Industrials", "Energy", "Utilities"], "GE Vernova: power generation boundary"),
    "HON":   ("transition", ["Industrials", "Technology"], "Honeywell: industrial + aerospace + tech"),
    "DE":    ("transition", ["Industrials", "Technology", "Materials"], "Deere: agriculture + autonomy tech"),
    "UNH":   ("transition", ["Healthcare", "Technology", "Financials"], "healthcare + tech + insurance"),
    "BX":    ("transition", ["Financials", "Real Estate"], "Blackstone: finance + real assets"),
    "BN":    ("transition", ["Utilities", "Real Estate", "Financials"], "Brookfield: infra + real assets"),
    "PLD":   ("transition", ["Real Estate", "Industrials", "Consumer"], "Prologis: warehouses = e-commerce rails"),
    # ── C: picks and shovels ──
    "NVDA":  ("picks_shovels", ["Technology", "Communication", "Industrials"], "AI boom: everyone needs GPUs"),
    "AMD":   ("picks_shovels", ["Technology", "Communication"], "AI compute alternative"),
    "SMCI":  ("picks_shovels", ["Technology", "Industrials"], "AI server racks"),
    "DELL":  ("picks_shovels", ["Technology", "Industrials"], "AI server integrator"),
    "ALB":   ("picks_shovels", ["Materials", "Energy", "Consumer"], "EV boom: lithium regardless of winner"),
    "SQM":   ("picks_shovels", ["Materials", "Energy"], "lithium supply"),
    "CRWD":  ("picks_shovels", ["Technology", "Financials", "Healthcare"], "every company needs security"),
    "ZS":    ("picks_shovels", ["Technology", "Financials"], "zero-trust security"),
    "PANW":  ("picks_shovels", ["Technology", "Financials", "Industrials"], "security platform"),
    "DDOG":  ("picks_shovels", ["Technology", "Communication"], "every cloud app needs monitoring"),
    "SNOW":  ("picks_shovels", ["Technology", "Financials"], "every company's data warehouse"),
    "MDB":   ("picks_shovels", ["Technology", "Communication"], "app database layer"),
    "ILMN":  ("picks_shovels", ["Healthcare", "Technology"], "every drug program needs sequencing"),
    "A":     ("picks_shovels", ["Healthcare", "Technology", "Materials"], "Agilent: lab tools for all biotech"),
    "IQV":   ("picks_shovels", ["Healthcare", "Technology"], "every trial needs a CRO"),
}


def get_map() -> dict:
    """Seed map merged with runtime-discovered bridges."""
    out = {k: {"category": c, "sectors": s, "note": n} for k, (c, s, n) in _SEED.items()}
    try:
        for k, v in (get(_KEY) or {}).items():
            if isinstance(v, dict) and v.get("sectors"):
                out[k.upper()] = v
    except Exception:
        pass
    return out


def bridge_info(symbol: str):
    """(n_sectors, sectors, category, note) or None if not a known bridge."""
    e = get_map().get(symbol.upper())
    if not e:
        return None
    return len(e["sectors"]), e["sectors"], e["category"], e.get("note", "")


def bridge_bonus(symbol: str) -> int:
    """Ranking bonus: +2 per sector beyond the first, capped at +6. Kept OUT
    of the calibrated 100-pt conviction score — applied at ranking time only."""
    info = bridge_info(symbol)
    if not info:
        return 0
    return min(6, (info[0] - 1) * 2)


def bridge_line(symbol: str) -> str:
    """One-line explanation for trade reasoning, e.g.
    '⛓ bridges Consumer + Energy + Technology (transition)'."""
    info = bridge_info(symbol)
    if not info:
        return ""
    n, sectors, cat, note = info
    return f"⛓ bridges {' + '.join(sectors)} ({cat}" + (f": {note})" if note else ")")


def bridge_tickers() -> list:
    return sorted(get_map().keys())


def bridges_for_sector(sector: str) -> list:
    """All bridge companies touching a sector — scanned when it shows strength."""
    sec = sector.strip().lower()
    return sorted(sym for sym, e in get_map().items()
                  if any(sec in s.lower() or s.lower() in sec for s in e["sectors"]))


def bridge_add(ticker: str, sectors, category: str = "discovered", note: str = "") -> str:
    """Jarvis learned a new bridge company through research — persist it."""
    t = str(ticker).upper().strip()
    if not (1 <= len(t) <= 5 and t.isalpha()):
        return f"'{ticker}' doesn't look like a ticker."
    if isinstance(sectors, str):
        sectors = [s.strip().title() for s in sectors.replace("+", ",").split(",") if s.strip()]
    if len(sectors) < 2:
        return "A bridge company needs at least 2 sectors."
    custom = get(_KEY) or {}
    custom[t] = {"category": category, "sectors": sectors[:4], "note": note[:120]}
    put(_KEY, custom)
    return f"⛓ Added {t} to the bridge map: {' + '.join(sectors[:4])} ({category})"


def bridge_show() -> str:
    m = get_map()
    cats = {"infrastructure": [], "transition": [], "picks_shovels": [], "discovered": []}
    for sym, e in sorted(m.items()):
        cats.setdefault(e["category"], []).append(f"  {sym}: {' + '.join(e['sectors'])}")
    out = [f"⛓ CROSS-SECTOR BRIDGE MAP ({len(m)} companies)", "━" * 30]
    labels = {"infrastructure": "A — INFRASTRUCTURE (every sector needs them)",
              "transition": "B — SECTOR TRANSITIONS (boundary companies)",
              "picks_shovels": "C — PICKS & SHOVELS (sell to every competitor)",
              "discovered": "D — DISCOVERED (added through research)"}
    for c, rows in cats.items():
        if rows:
            out.append(labels.get(c, c.upper()))
            out += rows
    out.append("These rank higher in hunts — multiple simultaneous sector tailwinds.")
    return "\n".join(out)
