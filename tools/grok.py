"""
grok.py — JARVIS bridge to xAI's Grok API

A deliberate, explicit exception to the rest of Jarvis's brain (Ollama,
fully local — see server.py's OLLAMA_MODEL): Taco asked to wire in his own
xAI API key so Jarvis can call out to Grok as an additional tool for things
the local model isn't well-suited to (harder reasoning, very current
events/real-time knowledge, a second opinion) — a callable capability
alongside the local brain, not a replacement for it, and NOT wired into
autonomous trade execution (analysis/conversation only, same footing as
web_research/company_research).

Requires XAI_API_KEY in .env (https://console.x.ai). Talks to xAI's
OpenAI-compatible REST API directly via `requests` (already a project
dependency) rather than adding the `openai` package for one endpoint.
"""

import os
import requests

_API_BASE      = "https://api.x.ai/v1"
_DEFAULT_MODEL = os.getenv("GROK_MODEL", "grok-4-latest")
_resolved_model = None  # cached once a working model name is confirmed


def _cfg(k: str, d: str = "") -> str:
    return os.getenv(k, d)


def _headers() -> dict:
    key = _cfg("XAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Grok isn't configured. Add XAI_API_KEY to .env "
            "(get one at https://console.x.ai) and restart Jarvis."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _list_models() -> list:
    r = requests.get(f"{_API_BASE}/models", headers=_headers(), timeout=15)
    r.raise_for_status()
    return [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]


def _pick_fallback_model(models: list) -> str:
    chat = [m for m in models if m.lower().startswith("grok") and "image" not in m.lower()]
    return (chat or models or [_DEFAULT_MODEL])[0]


def _chat(messages: list, temperature: float = 0.3, max_tokens: int = 1200) -> str:
    """POST a chat completion. If the configured/default model name doesn't
    exist on this account (xAI rotates/renames model ids over time), resolve
    a real one from /v1/models and retry once rather than hard-failing on a
    stale hardcoded model string."""
    global _resolved_model
    mdl  = _resolved_model or _DEFAULT_MODEL
    body = {"model": mdl, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    r = requests.post(f"{_API_BASE}/chat/completions", headers=_headers(), json=body, timeout=60)

    if r.status_code in (400, 404) and "model" in r.text.lower():
        try:
            fallback = _pick_fallback_model(_list_models())
        except Exception:
            pass
        else:
            _resolved_model = fallback
            body["model"] = fallback
            r = requests.post(f"{_API_BASE}/chat/completions", headers=_headers(), json=body, timeout=60)

    if not r.ok:
        raise RuntimeError(f"Grok API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


def ask_grok(query: str, context: str = "") -> str:
    """
    Ask Grok (xAI) a question — for harder reasoning, very current events, or
    a second opinion the local model isn't well suited to give. Purely
    conversational/analysis: never used to place or size a trade.
    """
    query = (query or "").strip()
    if not query:
        return "Ask Grok what, exactly?"
    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": query})
    try:
        return _chat(messages)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Grok request failed: {e}"


def grok_status() -> str:
    """Human-readable status for the 'grok status' chat command."""
    key = _cfg("XAI_API_KEY")
    if not key:
        return "Grok (xAI): NOT CONFIGURED — add XAI_API_KEY to .env, then restart Jarvis."
    try:
        models = _list_models()
        lines = [
            "Grok (xAI) Status",
            "  API key: configured",
            f"  Model:   {_resolved_model or _DEFAULT_MODEL}"
            + (" (fallback-resolved)" if _resolved_model else ""),
            f"  Models visible to this key: {len(models)}"
            + (f" — e.g. {', '.join(models[:5])}" if models else ""),
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Grok (xAI): configured, but the status check failed — {e}"
