"""
cs2_yolo.py — YOLO-based CS2 Player Detection
Uses pretrained YOLO models specifically trained on CS2 gameplay.
Labels: c=CT body, ch=CT head, t=T body, th=T head
Trained on 70-120 real CS2 games by Vombit on HuggingFace.
RTX 4070 Super runs this at ~2-5ms per frame.
"""

import os, sys, time, math, subprocess, threading
from pathlib import Path
import numpy as np

MODEL_DIR  = Path.home() / "Documents" / "JARVIS" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Model options — ordered by preference
# YOLO12 is newest/best, falls back to YOLOv8 variants
MODELS = [
    {
        "name":     "yolo12m_cs2",
        "file":     "yolo12m_cs2.pt",
        "url":      "https://huggingface.co/Vombit/yolo12m_cs2/resolve/main/yolo12m_cs2.pt",
        "size_mb":  40,
        "priority": 1,
    },
    {
        "name":     "yolo12n_cs2",
        "file":     "yolo12n_cs2.pt",
        "url":      "https://huggingface.co/Vombit/yolo12n_cs2/resolve/main/yolo12n_cs2.pt",
        "size_mb":  10,
        "priority": 2,
    },
    {
        "name":     "yolov8s_cs2",
        "file":     "yolov8s_cs2.pt",
        "url":      "https://huggingface.co/Vombit/yolov8s_cs2/resolve/main/yolov8s_cs2.pt",
        "size_mb":  21,
        "priority": 3,
    },
    {
        "name":     "yolov8n_cs2",
        "file":     "yolov8n_cs2.pt",
        "url":      "https://huggingface.co/Vombit/yolov8n_cs2/resolve/main/yolov8n_cs2.pt",
        "size_mb":  6,
        "priority": 4,
    },
]

# YOLO class labels from these models
LABELS = {
    0: "c",   # CT body
    1: "ch",  # CT head
    2: "t",   # T body
    3: "th",  # T head
}
LABEL_NAMES = {v: k for k, v in LABELS.items()}

# ─────────────────────────────────────────────────────────────
# MODEL MANAGER
# ─────────────────────────────────────────────────────────────

class YOLODetector:
    """
    Loads and runs the CS2 YOLO model.
    Automatically downloads on first run.
    Uses CUDA (RTX 4070 Super) for maximum speed.
    """

    def __init__(self):
        self.model      = None
        self.model_name = None
        self.device     = "cuda"  # RTX 4070 Super
        self.loaded     = False
        self.conf_threshold = 0.20   # confidence threshold
        self.screen_w   = 2560
        self.screen_h   = 1440
        self.fov        = 60
        self._load_thread = None

    def install_dependencies(self):
        """Install/upgrade ultralytics to latest (YOLO12 support) + torch CUDA."""
        lines = ["Installing YOLO dependencies..."]

        # Step 1: Upgrade ultralytics to latest — YOLO12 needs >= 8.3.x
        r = subprocess.run(
            "pip install -U ultralytics --quiet",
            shell=True, capture_output=True, text=True, timeout=120)
        lines.append(f"ultralytics upgrade: {'OK' if r.returncode==0 else r.stderr[:200]}")

        # Verify version supports YOLO12
        try:
            import importlib
            import importlib.metadata
            ver = importlib.metadata.version("ultralytics")
            lines.append(f"ultralytics version: {ver}")
        except Exception:
            pass

        # Step 2: Install torch with CUDA 12.1 (RTX 4070 Super compatible)
        # Check if CUDA torch already installed first
        cuda_check = subprocess.run(
            'python -c "import torch; print(torch.cuda.is_available())"',
            shell=True, capture_output=True, text=True)
        if "True" in cuda_check.stdout:
            lines.append("torch+cuda: Already installed and working")
        else:
            lines.append("Installing torch with CUDA 12.1...")
            r2 = subprocess.run(
                "pip install torch torchvision --index-url "
                "https://download.pytorch.org/whl/cu121 --quiet",
                shell=True, capture_output=True, text=True, timeout=600)
            lines.append(f"torch+cuda: {'OK' if r2.returncode==0 else 'Failed - ' + r2.stderr[:100]}")

        return "\n".join(lines)

    def download_model(self, model_info):
        """Download model weights from HuggingFace."""
        dest = MODEL_DIR / model_info["file"]
        if dest.exists():
            return str(dest)
        print(f"[YOLO] Downloading {model_info['name']} (~{model_info['size_mb']}MB)...")
        try:
            import urllib.request
            urllib.request.urlretrieve(
                model_info["url"], str(dest),
                reporthook=lambda b, bs, ts: print(
                    f"\r[YOLO] {min(100,int(b*bs/ts*100))}%...", end="", flush=True)
                    if ts > 0 else None
            )
            print(f"\n[YOLO] Downloaded: {dest.name}")
            return str(dest)
        except Exception as e:
            if dest.exists():
                dest.unlink()
            raise e

    def load(self, model_preference="yolo12m_cs2"):
        """Load CS2 YOLO model — checks local files, then downloads."""
        try:
            from ultralytics import YOLO
            import torch

            # Device setup - force CUDA for RTX 4070 Super
            cuda_ok = False
            try:
                if torch.cuda.is_available():
                    # Test CUDA actually works
                    test = torch.zeros(1).cuda()
                    del test
                    self.device = "cuda"
                    cuda_ok = True
                    print(f"[YOLO] GPU: {torch.cuda.get_device_name(0)}")
                    print(f"[YOLO] CUDA: {torch.version.cuda}")
            except Exception as ce:
                print(f"[YOLO] CUDA test failed: {ce}")
            if not cuda_ok:
                self.device = "cpu"
                print("[YOLO] Using CPU - run: pip install torch --index-url https://download.pytorch.org/whl/cu121")

            # ── Step 1: Check for local model files ───────────
            local_pts = sorted(MODEL_DIR.glob("*.pt"),
                               key=lambda f: f.stat().st_size, reverse=True)
            if local_pts:
                for lm in local_pts:
                    try:
                        print(f"[YOLO] Loading local: {lm.name}")
                        self.model = YOLO(str(lm))
                        self.model_name = lm.stem
                        try:
                            import torch
                            if torch.cuda.is_available():
                                self.device = "cuda"
                                self.model.to("cuda")
                                print(f"[YOLO] GPU: {torch.cuda.get_device_name(0)}")
                        except Exception:
                            pass
                        self._warmup()
                        self.loaded = True
                        print(f"[YOLO] Ready: {self.model_name} on {self.device}")
                        return True
                    except Exception as e:
                        print(f"[YOLO] {lm.name} failed: {e}")

            # ── Step 2: Download via huggingface_hub ──────────
            try:
                from huggingface_hub import hf_hub_download
                import traceback
                HF_FILES = [
                    ("Vombit/yolo12n_cs2", "yolo12n_cs2.pt", "yolo12n_cs2"),
                    ("Vombit/yolov9c_cs2", "yolov9c_cs2.pt", "yolov9c_cs2"),
                    ("Vombit/yolov8s_cs2", "yolov8s_cs2.pt", "yolov8s_cs2"),
                    ("Vombit/yolov8n_cs2", "yolov8n_cs2.pt", "yolov8n_cs2"),
                ]
                for repo, filename, model_name in HF_FILES:
                    try:
                        print(f"[YOLO] Downloading {model_name} from {repo}...")
                        path = hf_hub_download(
                            repo_id=repo,
                            filename=filename,
                            local_dir=str(MODEL_DIR),
                            force_download=False,
                        )
                        print(f"[YOLO] Downloaded to {path}")
                        self.model = YOLO(path)
                        self.model_name = model_name
                        # Force CUDA if available
                        try:
                            import torch
                            if torch.cuda.is_available():
                                self.device = "cuda"
                                self.model.to("cuda")
                                print(f"[YOLO] Moved to GPU: {torch.cuda.get_device_name(0)}")
                        except Exception as ge:
                            print(f"[YOLO] GPU move failed: {ge}, staying on CPU")
                        self._warmup()
                        self.loaded = True
                        print(f"[YOLO] Ready: {model_name} on {self.device}")
                        return True
                    except Exception as e:
                        print(f"[YOLO] {model_name} FULL ERROR: {traceback.format_exc()}")
                        continue
            except ImportError as ie:
                print(f"[YOLO] huggingface_hub import error: {ie}")
                print("[YOLO] Run: pip install huggingface_hub")

            # ── Step 3: Manual instructions ───────────────────
            print("[YOLO] Auto-download failed. See manual instructions.")
            return False

        except ImportError:
            print("[YOLO] ultralytics not installed")
            return False
        except Exception as e:
            print(f"[YOLO] Load error: {e}")
            return False
    def _warmup(self):
        """Run warmup passes for accurate timing."""
        print("[YOLO] Warming up...")
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        for _ in range(3):
            self.model.predict(
                dummy, device=self.device,
                verbose=False, conf=self.conf_threshold,
                half=(self.device == "cuda"))
        print("[YOLO] Warmup done")

    def load_async(self):
        """Load model in background thread so JARVIS doesn't block."""
        self._load_thread = threading.Thread(target=self.load, daemon=True)
        self._load_thread.start()

    def detect(self, frame):
        """
        Run YOLO detection on a frame.
        Returns list of enemy dicts with x, y, head_y, team, conf.
        """
        if not self.loaded or self.model is None:
            return []

        try:
            h, w = frame.shape[:2]
            cx, cy = w // 2, h // 2

            # Run inference
            import cv2 as _cv2
            h_orig, w_orig = frame.shape[:2]

            # For 2560x1440: resize to 1920x1080 for detection
            # YOLO trained at 640-1280, scaling to match training res
            target_w, target_h = 1280, 720
            detect_frame = _cv2.resize(frame, (target_w, target_h))

            results = self.model.predict(
                detect_frame,
                device=self.device,
                verbose=False,
                conf=self.conf_threshold,
                imgsz=1280,
                half=(self.device == "cuda"),
                augment=False,  # faster without augment
                iou=0.40,
            )

            # Scale detections back to original 2560x1440 coords
            scale_x = w_orig / target_w
            scale_y = h_orig / target_h

            enemies = []
            head_map = {}  # Map body detections to head detections

            if not results or len(results) == 0:
                return []

            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                return []

            detections = []
            for box in boxes:
                cls   = int(box.cls[0])
                conf  = float(box.conf[0])
                # Scale back to original resolution
                x1 = int(box.xyxy[0][0] * scale_x)
                y1 = int(box.xyxy[0][1] * scale_y)
                x2 = int(box.xyxy[0][2] * scale_x)
                y2 = int(box.xyxy[0][3] * scale_y)
                label = LABELS.get(cls, "unknown")
                detections.append({
                    "label": label,
                    "cls":   cls,
                    "conf":  conf,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cx": (x1+x2)//2,
                    "cy": (y1+y2)//2,
                })

            # First pass: collect head detections
            heads = {d["label"]: d for d in detections
                     if d["label"] in ("ch", "th")}

            # Second pass: build enemy list from body detections
            # Match heads to bodies by proximity
            for det in detections:
                label = det["label"]

                # Only process body detections as primary
                if label not in ("c", "t"):
                    continue

                team = "CT" if label == "c" else "T"
                bx   = det["cx"]
                by   = det["cy"]
                bw   = det["x2"] - det["x1"]
                bh   = det["y2"] - det["y1"]

                # Look for matching head detection above this body
                head_y = det["y1"] + int(bh * 0.05)  # default: top of body box
                head_label = "ch" if team == "CT" else "th"

                # Find closest head of same team above the body
                best_head = None
                best_dist = 9999
                for hdet in detections:
                    if hdet["label"] != head_label:
                        continue
                    hdx = abs(hdet["cx"] - bx)
                    hdy = by - hdet["cy"]
                    if hdx < bw * 0.8 and 0 < hdy < bh * 1.2:
                        d = math.sqrt(hdx**2 + hdy**2)
                        if d < best_dist:
                            best_dist = d
                            best_head = hdet

                if best_head:
                    # Use center of head bounding box
                    head_y = best_head["cy"]
                    det["conf"] = max(det["conf"], best_head["conf"])

                dist = math.sqrt((bx-cx)**2 + (by-cy)**2)

                enemies.append({
                    "x":      bx,
                    "y":      by,
                    "head_y": head_y,
                    "head_x": bx,    # head X = body center X (approximately)
                    "dist":   dist,
                    "conf":   det["conf"],
                    "team":   team,
                    "area":   bw * bh,
                    "method": f"yolo_{self.model_name}",
                    "box":    (det["x1"], det["y1"], det["x2"], det["y2"]),
                    "width":  bw,
                    "height": bh,
                })

            # Also add standalone head detections (no body matched)
            matched_heads = set()
            for e in enemies:
                for hdet in detections:
                    if hdet["label"] in ("ch","th"):
                        if abs(hdet["cx"] - e["x"]) < 50:
                            matched_heads.add(id(hdet))

            for hdet in detections:
                if id(hdet) in matched_heads:
                    continue
                if hdet["label"] not in ("ch", "th"):
                    continue
                team = "CT" if hdet["label"] == "ch" else "T"
                bx, by = hdet["cx"], hdet["cy"]
                bw = hdet["x2"] - hdet["x1"]
                bh = hdet["y2"] - hdet["y1"]
                dist = math.sqrt((bx-cx)**2 + (by-cy)**2)
                # Body is below head
                body_y = by + int(bh * 3)
                enemies.append({
                    "x":      bx,
                    "y":      body_y,
                    "head_y": by,
                    "head_x": bx,
                    "dist":   dist,
                    "conf":   hdet["conf"],
                    "team":   team,
                    "area":   bw*bh,
                    "method": f"yolo_head",
                    "width":  bw,
                    "height": bh,
                })

            enemies.sort(key=lambda e: e["dist"])
            return enemies

        except Exception as e:
            print(f"[YOLO] Detection error: {e}")
            return []

    def capture_and_detect(self):
        """Screenshot + detect in one call."""
        try:
            import pyautogui
            frame = np.array(pyautogui.screenshot())
            return self.detect(frame), frame
        except Exception as e:
            return [], None

    @property
    def is_ready(self):
        return self.loaded and self.model is not None


# ─────────────────────────────────────────────────────────────
# GLOBAL INSTANCE
# ─────────────────────────────────────────────────────────────

_detector = YOLODetector()

# ── Auto-load on import if model already exists locally ────────
# Runs in a background thread so JARVIS never blocks at startup.
# If no .pt file exists yet the thread exits immediately and the
# user is prompted to run "setup yolo" the first time.
def _auto_load_if_present():
    pts = list(MODEL_DIR.glob("*.pt"))
    if pts:
        # Sort largest first — prefer the best model already downloaded
        pts.sort(key=lambda p: p.stat().st_size, reverse=True)
        print(f"[YOLO] Found {len(pts)} local model(s) — auto-loading {pts[0].name}")
        _detector.load()
    else:
        print("[YOLO] No local model found — say 'setup yolo' to download one")

threading.Thread(target=_auto_load_if_present, daemon=True, name="yolo-autoload").start()

def yolo_setup():
    """Install packages, upgrade ultralytics, and download CS2 model."""
    lines = ["🤖 Setting up YOLO12 CS2 detection...\n"]

    # Step 1: Install/upgrade dependencies
    lines.append(_detector.install_dependencies())

    # Step 2: Try YOLO12 first, fall back to YOLOv8 if unavailable
    lines.append("\nDownloading CS2 detection model...")
    # Install huggingface_hub for reliable downloads
    r3 = subprocess.run("pip install huggingface_hub --quiet",
        shell=True, capture_output=True, text=True)
    lines.append(f"huggingface_hub: {'OK' if r3.returncode==0 else 'failed'}")

    lines.append("\nDownloading CS2 YOLO model from HuggingFace...")
    lines.append("Trying: yolo12n → yolov9c → yolov8s → yolov8n")
    try:
        ok = _detector.load("auto")
        if ok:
            lines.append(f"\n✅ YOLO ready: {_detector.model_name} on {_detector.device}")
            lines.append("Detects: CT body, CT head, T body, T head")
            lines.append("Works on all 63+ CS2 agent skins!")
        else:
            lines.append("\n❌ Auto-download failed. Check JARVIS server window for error details.")
            lines.append("\n── MANUAL INSTALL (fastest fix) ──")
            lines.append("1. Open Chrome, go to:")
            lines.append("   huggingface.co/Vombit/yolov8n_cs2/resolve/main/yolov8n_cs2.pt")
            lines.append("2. File downloads automatically (6MB)")
            lines.append("3. Move to: C:\\Users\\Owner\\Documents\\JARVIS\\models\\")
            lines.append("4. Restart JARVIS - loads automatically!")
    except Exception as e:
        import traceback
        lines.append(f"\n❌ Exception: {e}")
        lines.append(f"Details: {traceback.format_exc()[-300:]}")
        lines.append("\nManual: huggingface.co/Vombit/yolov8n_cs2")

    return "\n".join(lines)

def yolo_load_async():
    """Load model in background — call at startup."""
    _detector.install_dependencies()
    _detector.load_async()
    return "YOLO loading in background..."

def yolo_status():
    if _detector.loaded:
        return (f"✅ YOLO Active\n"
                f"  Model:  {_detector.model_name}\n"
                f"  Device: {_detector.device}\n"
                f"  Conf:   {_detector.conf_threshold}\n"
                f"  Ready for detection")
    elif _detector._load_thread and _detector._load_thread.is_alive():
        return "⏳ YOLO model loading in background..."
    else:
        return "❌ YOLO not loaded. Say 'setup yolo' to install."

def yolo_detect_test():
    """Test detection on current screen."""
    if not _detector.is_ready:
        return "YOLO not loaded. Say 'setup yolo' first."
    enemies, frame = _detector.capture_and_detect()
    h = frame.shape[0] if frame is not None else 0
    w = frame.shape[1] if frame is not None else 0
    lines = [
        f"🤖 YOLO Detection Test",
        f"  Model:   {_detector.model_name}",
        f"  Device:  {_detector.device}",
        f"  Screen:  {w}x{h}",
        f"  Enemies: {len(enemies)}",
        "",
    ]
    if enemies:
        for i, e in enumerate(enemies):
            lines.append(
                f"  {i+1}. [{e['team']}] pos=({e['x']},{e['y']}) "
                f"head=({e['head_x']},{e['head_y']}) "
                f"conf={e['conf']:.0%} size={e['width']}x{e['height']}")
    else:
        lines.append("  No enemies detected on screen.")
    return "\n".join(lines)

def yolo_set_confidence(conf):
    """Adjust detection confidence threshold 0.1-0.9."""
    _detector.conf_threshold = max(0.1, min(0.9, float(conf)))
    return f"YOLO confidence set to {_detector.conf_threshold:.0%}"

def get_detector():
    return _detector
