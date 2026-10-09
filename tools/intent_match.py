"""
intent_match.py — JARVIS Semantic Intent Matcher

The regex dispatch table only understands exact phrasings, and the raw LLM
fallback has to pick from ~150 tools cold. This is the missing middle layer:
match what the user MEANS, not the words they used.

How it works:
  • A corpus of example phrasings (the Commands-tab examples + the user's OWN
    real phrasings mined from interaction memory) is embedded into vectors
    with a small local Ollama embedding model (nomic-embed-text, ~270MB,
    fully offline — same decentralized rule as everything else).
  • An incoming message that the regex table couldn't place is embedded and
    compared by cosine similarity.
  • HIGH confidence + safe tool  → dispatch directly, no LLM needed.
  • MEDIUM confidence           → the LLM is told "this most resembles these
    3 tools" so it picks from 3 instead of guessing from 150.
  • No embedding model installed → lexical fallback (token overlap + fuzzy
    ratio), weaker but never a hard dependency.

Self-learning loop: every semantic dispatch is logged to interaction memory,
which feeds learned_command_examples(), which feeds this corpus — the more
you talk to Jarvis in your own vernacular, the better it understands it.

Money-moving tools (buy/sell/close/cancel) are NEVER auto-dispatched from a
similarity score — they can be hinted to the LLM, which must fill explicit
parameters, but a fuzzy match alone will never place an order.
"""

import os, re, json, math, hashlib, difflib, threading
from pathlib import Path

_CACHE_DIR  = Path.home() / "Documents" / "JARVIS" / "memory"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_VEC_CACHE  = _CACHE_DIR / "intent_vectors.json"

_EMBED_MODEL = os.getenv("JARVIS_EMBED_MODEL", "nomic-embed-text")

# Tools that move money or change positions — never triggered by similarity
_NEVER_AUTODISPATCH = {
    "trading_buy", "trading_sell", "trading_bracket", "trading_trail",
    "trading_cancel", "trading_close", "trading_close_all",
    "options_buy", "options_close", "strategy_execute", "auto_hunt",
}

# Thresholds (embeddings are well-calibrated; lexical fallback must be stricter)
_EMBED_DISPATCH  = 0.78
_EMBED_HINT      = 0.60
_LEX_DISPATCH    = 0.87
_LEX_HINT        = 0.55
_MARGIN          = 0.04   # best must beat runner-up (different tool) by this

_lock        = threading.Lock()
_vec_cache   = None       # {key: [floats]}
_embed_ok    = None       # tri-state: None unknown, True/False checked
_corpus      = []         # [{"phrase","tool","needs_symbol"}]
_corpus_vecs = []         # aligned vectors (or None per entry)

_PLACEHOLDER_TICKERS = {"SOFI", "AAPL", "NVDA", "TSLA", "SPY", "QQQ", "AMD"}
_COMMON_UPPER = {
    "I", "A", "OK", "AI", "PC", "TV", "US", "USA", "NYSE", "NASDAQ", "WSB",
    "ETF", "CEO", "IPO", "SEC", "FED", "GDP", "CPI", "RSI", "ATR", "VIX",
    "PDT", "YOLO", "CS2", "FPS", "GPU", "CPU", "RAM", "URL", "API", "LLM",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _extract_ticker(msg: str) -> str:
    """Best-effort ticker pull: $XXX always wins, else a lone UPPERCASE token."""
    m = re.search(r"\$([A-Za-z]{1,5})\b", msg)
    if m:
        return m.group(1).upper()
    for tok in re.findall(r"\b[A-Z]{2,5}\b", msg):
        if tok not in _COMMON_UPPER:
            return tok
    return ""


# ── Embeddings via local Ollama ─────────────────────────────────────────────────
def _embed_available() -> bool:
    global _embed_ok
    if _embed_ok is not None:
        return _embed_ok
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m.get("name", "") for m in r.json().get("models", [])] if r.ok else []
        _embed_ok = any(_EMBED_MODEL in m for m in models)
    except Exception:
        _embed_ok = False
    return _embed_ok


def _load_vec_cache() -> dict:
    global _vec_cache
    if _vec_cache is None:
        try:
            _vec_cache = json.loads(_VEC_CACHE.read_text(encoding="utf-8"))
        except Exception:
            _vec_cache = {}
    return _vec_cache


def _save_vec_cache():
    try:
        _VEC_CACHE.write_text(json.dumps(_vec_cache), encoding="utf-8")
    except Exception:
        pass


def _embed(text: str, cache: bool = True):
    """Vector for text via Ollama; disk-cached per (model, phrase). None on failure."""
    key = f"{_EMBED_MODEL}:{hashlib.sha1(_norm(text).encode()).hexdigest()[:16]}"
    c = _load_vec_cache()
    if cache and key in c:
        return c[key]
    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": _norm(text)},
            timeout=10,
        )
        if r.ok:
            vec = r.json().get("embedding")
            if vec:
                if cache:
                    with _lock:
                        c[key] = vec
                        _save_vec_cache()
                return vec
    except Exception:
        pass
    return None


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ── Lexical fallback (no embedding model installed) ─────────────────────────────
_STOP = {"the", "a", "an", "my", "me", "for", "of", "to", "on", "in", "is",
         "whats", "what", "show", "give", "get", "can", "you", "please", "jarvis"}

def _lex_sim(a: str, b: str) -> float:
    ta = {w for w in re.findall(r"[a-z']+", _norm(a)) if w not in _STOP}
    tb = {w for w in re.findall(r"[a-z']+", _norm(b)) if w not in _STOP}
    if not ta or not tb:
        return 0.0
    jacc = len(ta & tb) / len(ta | tb)
    fuzz = difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    return 0.6 * jacc + 0.4 * fuzz


# ── Corpus ───────────────────────────────────────────────────────────────────────
def set_corpus(entries: list):
    """
    Load/refresh the example corpus. entries: [{"phrase","tool"}].
    needs_symbol is inferred from placeholder tickers in the canned examples.
    Embeddings are computed lazily (first match) and disk-cached.
    """
    global _corpus, _corpus_vecs
    seen = set()
    out  = []
    for e in entries:
        phrase = (e.get("phrase") or "").strip()
        tool   = (e.get("tool") or "").strip()
        if not phrase or not tool:
            continue
        k = _norm(phrase)
        if k in seen:
            continue
        seen.add(k)
        out.append({
            "phrase": phrase,
            "tool":   tool,
            "needs_symbol": any(t in phrase.split() for t in _PLACEHOLDER_TICKERS),
        })
    with _lock:
        _corpus      = out
        _corpus_vecs = [None] * len(out)


def _ensure_vecs():
    """Embed any corpus entries that don't have vectors yet (disk-cache backed)."""
    for i, entry in enumerate(_corpus):
        if _corpus_vecs[i] is None:
            _corpus_vecs[i] = _embed(entry["phrase"]) or False  # False = failed


# ── Matching ─────────────────────────────────────────────────────────────────────
def match_intent(msg: str) -> dict:
    """
    Semantic match of msg against the corpus.
    Returns {"dispatch": (tool, params) | None, "candidates": [(tool, phrase, score)],
             "method": "embed"|"lexical"|"none"}
    """
    out = {"dispatch": None, "candidates": [], "method": "none"}
    if not _corpus or not msg or len(msg) > 200:
        return out

    scored = []
    if _embed_available():
        out["method"] = "embed"
        qv = _embed(msg, cache=False)
        if qv:
            _ensure_vecs()
            for entry, vec in zip(_corpus, _corpus_vecs):
                if vec:
                    scored.append((entry, _cosine(qv, vec)))
        dispatch_thr, hint_thr = _EMBED_DISPATCH, _EMBED_HINT
    if not scored:
        out["method"] = "lexical"
        for entry in _corpus:
            scored.append((entry, _lex_sim(msg, entry["phrase"])))
        dispatch_thr, hint_thr = _LEX_DISPATCH, _LEX_HINT

    scored.sort(key=lambda x: -x[1])
    top = scored[:6]

    # Candidates: best score per distinct tool
    cand, seen_tools = [], set()
    for entry, score in top:
        if score < hint_thr or entry["tool"] in seen_tools:
            continue
        seen_tools.add(entry["tool"])
        cand.append((entry["tool"], entry["phrase"], round(score, 3)))
        if len(cand) == 3:
            break
    out["candidates"] = cand
    if not cand:
        return out

    best_entry, best_score = top[0]
    runner_up = next((s for e, s in top if e["tool"] != best_entry["tool"]), 0.0)

    # Conservative auto-dispatch: confident, unambiguous, safe tool,
    # and short message (long messages carry context a similarity score can't see)
    if (best_score >= dispatch_thr
            and best_score - runner_up >= _MARGIN
            and best_entry["tool"] not in _NEVER_AUTODISPATCH
            and len(msg.split()) <= 15):
        params = {}
        if best_entry["needs_symbol"]:
            sym = _extract_ticker(msg)
            if not sym:
                return out           # needs a ticker we couldn't find — hint only
            params = {"symbol": sym}
        out["dispatch"] = (best_entry["tool"], params)
    return out


def hint_text(candidates: list) -> str:
    """One-line prompt injection for the LLM when confidence is medium."""
    if not candidates:
        return ""
    opts = " | ".join(f'{t} (like "{p}", {s:.0%})' for t, p, s in candidates)
    return ("\nINTENT HINT: semantic analysis says this message most resembles: "
            f"{opts}. Strongly consider calling the best of these (with proper "
            "params) — or reply in plain text if none truly fits.")


def intent_status() -> str:
    method = "embeddings" if _embed_available() else "lexical fallback"
    return "\n".join([
        "Semantic Intent Matcher",
        f"  Method:      {method}  (model: {_EMBED_MODEL})",
        f"  Corpus:      {len(_corpus)} example phrasings",
        f"  Vector cache: {_VEC_CACHE.name} "
        f"({len(_load_vec_cache())} cached embeddings)",
        f"  Auto-dispatch excluded: {', '.join(sorted(_NEVER_AUTODISPATCH))}",
    ])
