import json
from pathlib import Path

DATA_DIR = Path.home() / "Documents" / "JARVIS"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FILE = DATA_DIR / "data.json"

DEFAULTS = {
    "grocery_list":[], "pantry":{}, "bills":[], "budget":{},
    "expenses":[], "goals":[], "tasks":[], "habits":[],
    "notes":[], "medications":[], "workouts":[], "health_log":[],
    "contacts":[], "reminders":[],
}

def load():
    try:
        if FILE.exists():
            return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return dict(DEFAULTS)

def save(data):
    FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def get(key):
    return load().get(key, DEFAULTS.get(key))

def put(key, value):
    d = load(); d[key] = value; save(d)