"""
voice.py — JARVIS Voice I/O (speech-to-text + text-to-speech)

Fully local, matching the rest of Jarvis's "decentralized, no cloud
dependency" design (see jarvis_memory / social_intel / market — same pattern):

  STT:  faster-whisper (ctranslate2) — runs on the RTX 4070S if CUDA is
        available, else CPU. Model downloads once from Hugging Face on first
        use, then works fully offline. Any browser-recorded audio (webm/opus
        on Chrome/Android, mp4/aac on Safari/iOS) decodes fine — faster-whisper
        bundles PyAV, so no separate ffmpeg install is required.
  TTS:  pyttsx3 over Windows SAPI5 — zero download, uses whatever voices are
        already registered on this PC (Settings > Time & Language > Speech >
        Add voices for more). Presets are named combos of {voice, rate,
        volume} the user can add/rename/delete — this is the "voice preset"
        layer requested, independent of how many raw SAPI voices exist.

Both halves degrade gracefully (matching trade_stream.py's _HAS_WEBSOCKET
pattern) — if a package isn't installed, callers get a clear one-line
install hint instead of a stack trace.
"""

import os, io, wave, tempfile, threading, uuid
from pathlib import Path

import tools.store as STORE

# ── STT: faster-whisper ──────────────────────────────────────────────────────

try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
except Exception:
    _HAS_WHISPER = False

_WHISPER_MODEL_NAME = os.getenv("JARVIS_STT_MODEL", "base.en")
_whisper_lock   = threading.Lock()
_whisper_model  = None
_whisper_device = None   # "cuda" or "cpu", once loaded — for stt_status()
_force_cpu      = False  # latched True the first time CUDA fails at inference time


def _load_whisper_model(device: str):
    if device == "cuda":
        return WhisperModel(_WHISPER_MODEL_NAME, device="cuda", compute_type="float16")
    return WhisperModel(_WHISPER_MODEL_NAME, device="cpu", compute_type="int8")


def _get_whisper():
    """Load the Whisper model once. ctranslate2's CUDA path loads the actual
    cuBLAS/cuDNN libraries LAZILY on the first real .transcribe() call, not at
    construction time — so a model built with device="cuda" can look fine
    here and still blow up later with 'Library cublas64_12.dll is not found'
    the moment it's actually used. This only guards construction; the real
    fallback (for the lazy-load failure) lives in transcribe() below."""
    global _whisper_model, _whisper_device
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                if _force_cpu:
                    _whisper_model, _whisper_device = _load_whisper_model("cpu"), "cpu"
                else:
                    try:
                        _whisper_model, _whisper_device = _load_whisper_model("cuda"), "cuda"
                    except Exception:
                        _whisper_model, _whisper_device = _load_whisper_model("cpu"), "cpu"
    return _whisper_model


def _is_cuda_lib_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("cublas", "cudnn", "cuda", ".dll"))


def _reload_on_cpu():
    """Force a CPU reload after a CUDA library failure surfaces during actual
    inference, and latch _force_cpu so every later call skips the doomed CUDA
    attempt entirely instead of re-failing on every request."""
    global _whisper_model, _whisper_device, _force_cpu
    with _whisper_lock:
        _force_cpu = True
        _whisper_model = _load_whisper_model("cpu")
        _whisper_device = "cpu"
    return _whisper_model


def stt_status() -> dict:
    return {
        "installed": _HAS_WHISPER,
        "model": _WHISPER_MODEL_NAME,
        "loaded": _whisper_model is not None,
        "device": _whisper_device,
        "hint": None if _HAS_WHISPER else "pip install faster-whisper",
    }


def _silence_wav_bytes(seconds: int = 1, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * (rate * seconds))
    return buf.getvalue()


def warm_up():
    """Load the model (and resolve the CUDA-vs-CPU question) at server boot,
    in a background thread, instead of on whoever's first real voice command.
    Without this, the first user request pays for: the one-time ~140MB model
    download, construction, AND — if the GPU path is broken on this machine —
    a failed CUDA attempt plus a full CPU reload, all before decoding a single
    word. That easily blows past a UI fetch timeout and shows up as
    'transcription failed / signal timed out' for something that was really
    just a slow cold start.

    Deliberately calls the real transcribe() (via a real temp WAV file, same
    as a browser upload) rather than hand-rolling a shortcut through the
    model — an earlier version of this function called model.transcribe() on
    a raw numpy array directly, which skips vad_filter/file-decoding entirely
    and therefore didn't actually warm up (or catch problems in) the code
    path a real request takes.
    """
    if not _HAS_WHISPER:
        return
    try:
        transcribe(_silence_wav_bytes(), "warmup.wav")
    except RuntimeError:
        pass  # "no speech detected" on pure silence is expected — the point
              # was to prove the model loads and decodes without hanging/crashing
    except Exception:
        pass


def transcribe(audio_bytes: bytes, filename_hint: str = "audio.webm") -> str:
    """
    Transcribe recorded speech to text. `audio_bytes` is whatever the browser's
    MediaRecorder produced (webm/opus, mp4/aac, wav — faster-whisper's bundled
    decoder handles all of them from the raw bytes via a temp file).
    Raises RuntimeError with a clear message on failure (caller turns that
    into a friendly chat/HTTP response, same convention as options_engine._api).
    """
    if not _HAS_WHISPER:
        raise RuntimeError(
            "Speech-to-text isn't installed yet. On the PC running Jarvis, run:\n"
            "  pip install faster-whisper"
        )
    if not audio_bytes:
        raise RuntimeError("No audio received.")

    suffix = Path(filename_hint).suffix or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        model = _get_whisper()
        # vad_filter deliberately OFF: it pulls in a second model (Silero VAD
        # via onnxruntime) that can itself try a GPU execution provider and
        # stall — not worth it here since push-to-talk already gives a clear
        # speech boundary (the user explicitly holds the button), unlike a
        # continuously-open mic where VAD earns its keep trimming silence.
        try:
            segments, _info = model.transcribe(
                tmp_path, beam_size=1, condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            # ctranslate2 loads cuBLAS lazily — a CUDA model can fail HERE,
            # on first real use, even though it constructed fine. Reload on
            # CPU and retry once instead of surfacing a DLL error to the user.
            if _whisper_device == "cuda" and _is_cuda_lib_error(e):
                model = _reload_on_cpu()
                segments, _info = model.transcribe(
                    tmp_path, beam_size=1, condition_on_previous_text=False,
                )
                text = " ".join(seg.text.strip() for seg in segments).strip()
            else:
                raise
        if not text:
            raise RuntimeError("Didn't catch that — no speech detected.")
        return text
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── TTS: pyttsx3 / SAPI5 ─────────────────────────────────────────────────────

try:
    import pyttsx3
    _HAS_TTS = True
except Exception:
    _HAS_TTS = False

_tts_lock = threading.Lock()

_PRESETS_KEY  = "voice_presets"
_DEFAULT_KEY  = "voice_default_preset"

# Seed presets are voice-agnostic (voice_id resolved lazily against whatever
# SAPI voices this PC actually has) — rate/volume differences alone still
# give the user real preset variety even on a stock 1-2-voice Windows install.
_SEED_PRESETS = [
    {"id": "default", "name": "Jarvis (Default)", "voice_index": 0, "rate": 175, "volume": 1.0},
    {"id": "calm",    "name": "Calm",              "voice_index": 0, "rate": 150, "volume": 0.9},
    {"id": "brisk",   "name": "Brisk",             "voice_index": 0, "rate": 210, "volume": 1.0},
    {"id": "deep",    "name": "Deep",              "voice_index": 1, "rate": 165, "volume": 1.0},
]


def _system_voices() -> list:
    """Raw SAPI voices installed on this PC: [{id, name, index}, ...]."""
    if not _HAS_TTS:
        return []
    try:
        eng = pyttsx3.init()
        voices = eng.getProperty("voices") or []
        out = [{"index": i, "id": v.id, "name": v.name} for i, v in enumerate(voices)]
        eng.stop()
        return out
    except Exception:
        return []


def _load_presets() -> list:
    presets = STORE.get(_PRESETS_KEY)
    if not presets:
        presets = [dict(p) for p in _SEED_PRESETS]
        STORE.put(_PRESETS_KEY, presets)
    return presets


def list_presets() -> dict:
    voices  = _system_voices()
    presets = _load_presets()
    default = STORE.get(_DEFAULT_KEY) or "default"
    # Clamp voice_index against however many real voices exist so a preset
    # never points at a voice that isn't installed on this machine.
    n = max(1, len(voices))
    for p in presets:
        p["voice_index"] = min(p.get("voice_index", 0), n - 1)
    return {
        "installed":       _HAS_TTS,
        "hint":            None if _HAS_TTS else "pip install pyttsx3",
        "presets":         presets,
        "default_preset":  default,
        "system_voices":   voices,
    }


def save_preset(preset: dict) -> dict:
    """Create or update a preset. Requires id+name; rate/volume/voice_index
    optional (defaults applied). Returns the refreshed preset list."""
    pid = (preset.get("id") or "").strip() or uuid.uuid4().hex[:8]
    presets = _load_presets()
    existing = next((p for p in presets if p["id"] == pid), None)
    entry = {
        "id":          pid,
        "name":        (preset.get("name") or pid).strip()[:40],
        "voice_index": int(preset.get("voice_index", 0)),
        "rate":        max(80, min(320, int(preset.get("rate", 175)))),
        "volume":      max(0.0, min(1.0, float(preset.get("volume", 1.0)))),
    }
    if existing:
        presets[presets.index(existing)] = entry
    else:
        presets.append(entry)
    STORE.put(_PRESETS_KEY, presets)
    return list_presets()


def delete_preset(preset_id: str) -> dict:
    presets = [p for p in _load_presets() if p["id"] != preset_id]
    STORE.put(_PRESETS_KEY, presets)
    if STORE.get(_DEFAULT_KEY) == preset_id:
        STORE.put(_DEFAULT_KEY, "default")
    return list_presets()


def set_default_preset(preset_id: str) -> dict:
    STORE.put(_DEFAULT_KEY, preset_id)
    return list_presets()


def _resolve_preset(preset_id: str = None) -> dict:
    presets = _load_presets()
    pid = preset_id or STORE.get(_DEFAULT_KEY) or "default"
    return next((p for p in presets if p["id"] == pid), presets[0] if presets else dict(_SEED_PRESETS[0]))


def speak(text: str, preset_id: str = None) -> bytes:
    """
    Synthesize `text` with the given (or default) preset. Returns raw WAV
    bytes ready to stream back as audio/wav. Serialized behind a lock —
    pyttsx3's SAPI COM engine isn't safe for concurrent calls, and a personal
    assistant only ever needs to speak one reply at a time anyway.
    """
    if not _HAS_TTS:
        raise RuntimeError(
            "Text-to-speech isn't installed yet. On the PC running Jarvis, run:\n"
            "  pip install pyttsx3"
        )
    text = (text or "").strip()
    if not text:
        raise RuntimeError("No text to speak.")
    # Keep spoken replies sane — this is for conversational turns, not for
    # reading a 2,000-character report aloud.
    if len(text) > 1200:
        text = text[:1200].rsplit(" ", 1)[0] + "…"

    preset = _resolve_preset(preset_id)
    tmp_path = None
    with _tts_lock:
        try:
            eng = pyttsx3.init()
            voices = eng.getProperty("voices") or []
            if voices:
                idx = min(preset.get("voice_index", 0), len(voices) - 1)
                eng.setProperty("voice", voices[idx].id)
            eng.setProperty("rate", preset.get("rate", 175))
            eng.setProperty("volume", preset.get("volume", 1.0))

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            eng.save_to_file(text, tmp_path)
            eng.runAndWait()
            eng.stop()

            data = Path(tmp_path).read_bytes()
            if not data or len(data) < 100:
                raise RuntimeError("TTS engine produced no audio (check installed voices in Windows Speech settings).")
            return data
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Speech synthesis failed: {e}")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


def voice_status() -> str:
    """Human-readable status for the 'voice status' chat command."""
    s = stt_status()
    p = list_presets()
    lines = [
        "Voice I/O Status",
        f"  Speech-to-text: {'READY (' + s['model'] + ', ' + (s['device'] or 'not loaded yet') + ')' if s['installed'] else 'NOT INSTALLED — ' + (s['hint'] or '')}",
        f"  Text-to-speech: {'READY' if p['installed'] else 'NOT INSTALLED — ' + (p['hint'] or '')}",
        f"  System voices:  {len(p['system_voices'])} installed"
        + (" (" + ", ".join(v['name'] for v in p['system_voices'][:4]) + ")" if p['system_voices'] else ""),
        f"  Presets:        {len(p['presets'])} ({', '.join(x['name'] for x in p['presets'])})",
        f"  Default preset: {p['default_preset']}",
    ]
    return "\n".join(lines)
