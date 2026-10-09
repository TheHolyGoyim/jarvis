"""
tools/assistant_tools.py — everyday personal-assistant tools.

All free and keyless (Open-Meteo, frankfurter.app, dictionaryapi.dev,
date.nager.at) or fully local — consistent with Jarvis's decentralized rule.

Fixes two long-standing stubs: web_weather only opened a Chrome tab (Jarvis
could never SAY the weather), and tech_timer popped a PC MessageBox that a
phone user never sees. Real weather data + reminders that fire into the chat.
"""

import os
import re
import json
import math
import time
import secrets
import threading
from pathlib import Path
from datetime import datetime, timedelta

import requests

_RULE = "━" * 30
_DIR = Path.home() / "Documents" / "JARVIS"
_DIR.mkdir(parents=True, exist_ok=True)
_REM_FILE = _DIR / "reminders.json"
_REM_LOCK = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# WEATHER — Open-Meteo (free, keyless, real data in chat)
# ══════════════════════════════════════════════════════════════════════════════

_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm w/ hail", 99: "thunderstorm w/ hail",
}


def weather_now(location: str = "", **_) -> str:
    """Current conditions + 3-day outlook for any place, real data."""
    loc = (location or os.getenv("HOME_CITY", "Myrtle Beach")).strip()
    loc = re.sub(r'\s+(?:sc|nc|ca|ny|tx|fl)$', '', loc, flags=re.I) or loc
    try:
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": loc, "count": 1}, timeout=8).json()
        hits = g.get("results") or []
        if not hits:
            return f"Couldn't find a place called '{loc}'."
        place = hits[0]
        name = place["name"] + (f", {place.get('admin1')}" if place.get("admin1") else "")
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"], "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                "timezone": "auto", "forecast_days": 3,
            }, timeout=8).json()
        c, d = r["current"], r["daily"]
        out = [f"🌤 WEATHER — {name}", _RULE,
               f"  now: {round(c['temperature_2m'])}°F "
               f"(feels {round(c['apparent_temperature'])}°F), "
               f"{_WMO.get(c['weather_code'], '—')}",
               f"  humidity {c['relative_humidity_2m']}% | "
               f"wind {round(c['wind_speed_10m'])} mph", ""]
        labels = ["today", "tomorrow", d["time"][2] if len(d["time"]) > 2 else ""]
        for i, lab in enumerate(labels[:len(d["time"])]):
            out.append(f"  {lab}: {round(d['temperature_2m_min'][i])}–"
                       f"{round(d['temperature_2m_max'][i])}°F, "
                       f"{_WMO.get(d['weather_code'][i], '—')}, "
                       f"rain {d['precipitation_probability_max'][i] or 0}%")
        return "\n".join(out)
    except Exception as e:
        return f"Weather lookup failed ({type(e).__name__}) — is the internet up?"


# ══════════════════════════════════════════════════════════════════════════════
# REMINDERS & TIMERS — persisted, fire into the chat via /reminders/due polling
# ══════════════════════════════════════════════════════════════════════════════

def _rem_load() -> list:
    try:
        return json.loads(_REM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _rem_save(items: list):
    _REM_FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def _parse_when(s: str):
    """Extract (due_epoch, cleaned_text) from natural phrasing. None if no time found."""
    now = datetime.now()
    txt = s

    # "in 1 hour and 30 minutes" / "in 20 min" / "in 90 seconds"
    m = re.search(r'\bin\s+((?:\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b\s*(?:and\s+)?)+)', txt)
    if m:
        total = 0
        for qty, unit in re.findall(r'(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b', m.group(1)):
            mult = 3600 if unit[0] == "h" else (1 if unit[0] == "s" else 60)
            total += int(qty) * mult
        if total:
            return now.timestamp() + total, (txt[:m.start()] + txt[m.end():]).strip()

    # "[tomorrow] at 5[:30] [pm]" / "tonight" / bare "tomorrow"
    tomorrow = bool(re.search(r'\btomorrow\b', txt))
    m = re.search(r'\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', txt)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        ap = m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        due = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if tomorrow:
            due += timedelta(days=1)
        elif due <= now:
            due += timedelta(days=1) if (ap or h > 12) else timedelta(hours=12)
            if due <= now:
                due += timedelta(days=1)
        clean = re.sub(r'\btomorrow\b', '', txt[:m.start()] + txt[m.end():]).strip()
        return due.timestamp(), clean
    if re.search(r'\btonight\b', txt):
        due = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due.timestamp(), re.sub(r'\btonight\b', '', txt).strip()
    if tomorrow:
        due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return due.timestamp(), re.sub(r'\btomorrow\b', '', txt).strip()
    return None


def remind(text: str = "", **_) -> str:
    """'remind me in 20 minutes to check the oven' / 'set a timer for 10 minutes'."""
    s = str(text or "").strip()
    if not s:
        return "What should I remind you about, and when? e.g. 'remind me in 20 minutes to check the oven'"
    low = s.lower()
    is_timer = bool(re.search(r'\b(?:set\s+a\s+)?timer\b', low))
    low = re.sub(r'^(?:hey\s+)?jarvis[,!\s]+', '', low)
    low = re.sub(r'^(?:please\s+)?(?:(?:set|start)\s+a\s+timer\s+(?:for\s+)?|timer\s+(?:for\s+)?|remind\s+me\s+(?:to\s+)?|reminder\s*:?\s*)', '', low)
    # "timer for 10 minutes" → duration with no "in" — treat as "in 10 minutes"
    if is_timer and re.match(r'^\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b', low):
        low = "in " + low
    parsed = _parse_when(low)
    if not parsed:
        # No time given — don't lecture, capture it as a task instead.
        task = re.sub(r'^(?:to|that)\s+', '', low).strip(" ,.-")
        if task and not is_timer:
            try:
                import tools.tools as T
                T.task_add(task)
                return (f"No time given, so I added it to your tasks: \"{task}\". "
                        "Want it timed? Say e.g. 'remind me at 5pm to ...'")
            except Exception:
                pass
        return ("When? Say it with a time — 'in 20 minutes', 'at 5:30pm', "
                "'tomorrow at 9am', or 'tonight'.")
    due, task = parsed
    task = re.sub(r'^(?:to|that)\s+', '', task).strip(" ,.-") or ("Timer done!" if is_timer else "Reminder!")
    with _REM_LOCK:
        items = _rem_load()
        rid = (max((x["id"] for x in items), default=0) + 1)
        items.append({"id": rid, "text": task, "due": due,
                      "created": time.time()})
        _rem_save(items)
    when = datetime.fromtimestamp(due)
    delta = due - time.time()
    human = (f"in {round(delta / 60)} min" if delta < 5400 else
             f"in {delta / 3600:.1f}h" if when.date() == datetime.now().date() else
             when.strftime("%a %I:%M %p"))
    return f"⏰ Got it — \"{task}\" {human} ({when.strftime('%I:%M %p')}). [#{rid}]"


def reminders_list(**_) -> str:
    items = sorted(_rem_load(), key=lambda x: x["due"])
    if not items:
        return "No reminders set. Say 'remind me in 20 minutes to ...' to add one."
    out = ["⏰ REMINDERS", _RULE]
    for x in items:
        out.append(f"  #{x['id']} {datetime.fromtimestamp(x['due']).strftime('%a %I:%M %p')} — {x['text']}")
    return "\n".join(out)


def reminder_cancel(which: str = "", **_) -> str:
    w = str(which).strip().lstrip("#")
    with _REM_LOCK:
        items = _rem_load()
        if not items:
            return "No reminders to cancel."
        if w.isdigit():
            keep = [x for x in items if x["id"] != int(w)]
        elif w in ("all", ""):
            keep = [] if w == "all" else items
        else:
            keep = [x for x in items if w.lower() not in x["text"].lower()]
        gone = len(items) - len(keep)
        if not gone:
            return f"No reminder matching '{which}'. Say 'show reminders' to see them."
        _rem_save(keep)
    return f"Cancelled {gone} reminder{'s' if gone != 1 else ''}."


def reminders_due(**_) -> list:
    """Pop and return reminders that are due — called by the UI poller + chat."""
    now = time.time()
    with _REM_LOCK:
        items = _rem_load()
        due = [x for x in items if x["due"] <= now]
        if due:
            _rem_save([x for x in items if x["due"] > now])
    return [f"⏰ REMINDER: {x['text']}" for x in sorted(due, key=lambda x: x["due"])]


# ══════════════════════════════════════════════════════════════════════════════
# UNIT + CURRENCY CONVERSION
# ══════════════════════════════════════════════════════════════════════════════

_UNITS = {  # canonical-per-unit factors, grouped by dimension
    "length": {"mm": .001, "cm": .01, "m": 1, "km": 1000, "in": .0254, "inch": .0254,
               "inches": .0254, "ft": .3048, "foot": .3048, "feet": .3048,
               "yd": .9144, "yard": .9144, "yards": .9144, "mi": 1609.344,
               "mile": 1609.344, "miles": 1609.344},
    "mass": {"mg": 1e-6, "g": .001, "kg": 1, "oz": .0283495, "ounce": .0283495,
             "ounces": .0283495, "lb": .453592, "lbs": .453592, "pound": .453592,
             "pounds": .453592, "ton": 907.185, "tons": 907.185, "tonne": 1000},
    "volume": {"ml": .001, "l": 1, "liter": 1, "liters": 1, "litre": 1, "litres": 1,
               "tsp": .00492892, "teaspoon": .00492892, "teaspoons": .00492892,
               "tbsp": .0147868, "tablespoon": .0147868, "tablespoons": .0147868,
               "cup": .236588, "cups": .236588, "pint": .473176, "pints": .473176,
               "quart": .946353, "quarts": .946353, "gal": 3.78541,
               "gallon": 3.78541, "gallons": 3.78541, "floz": .0295735},
    "speed": {"mph": .44704, "kph": .277778, "kmh": .277778, "knots": .514444,
              "knot": .514444, "mps": 1},
    "data": {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15,
             "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4},
    "area": {"sqft": .092903, "sqm": 1, "acre": 4046.86, "acres": 4046.86,
             "hectare": 10000, "hectares": 10000, "sqkm": 1e6, "sqmi": 2.59e6},
}
_CCY = {"usd": "USD", "$": "USD", "dollar": "USD", "dollars": "USD", "bucks": "USD",
        "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR",
        "gbp": "GBP", "£": "GBP", "pound sterling": "GBP", "quid": "GBP",
        "jpy": "JPY", "¥": "JPY", "yen": "JPY", "cad": "CAD", "aud": "AUD",
        "chf": "CHF", "cny": "CNY", "yuan": "CNY", "inr": "INR", "rupees": "INR",
        "mxn": "MXN", "pesos": "MXN", "krw": "KRW", "brl": "BRL", "sek": "SEK",
        "nok": "NOK", "dkk": "DKK", "pln": "PLN", "sgd": "SGD", "hkd": "HKD",
        "nzd": "NZD", "try": "TRY", "zar": "ZAR"}


def _temp_convert(val, frm, to):
    frm, to = frm[0], to[0]   # f/c/k
    c = {"f": lambda v: (v - 32) * 5 / 9, "c": lambda v: v,
         "k": lambda v: v - 273.15}[frm](val)
    return {"f": c * 9 / 5 + 32, "c": c, "k": c + 273.15}[to]


def unit_convert(query: str = "", **_) -> str:
    """'convert 5 miles to km', '350 f to c', '2 cups in ml', '100 usd to eur'."""
    s = str(query or "").lower().strip().rstrip("?")
    s = re.sub(r'^(?:convert|change|turn)\s+', '', s)
    s = re.sub(r'\bhow\s+(?:many|much)\s+(\w+)\s+(?:is|are|in)\s+([\d.]+)\s*(\w+)$',
               r'\2 \3 to \1', s)   # "how many km in 5 miles" → "5 miles to km"
    m = re.match(r'^\$?([\d.,]+)\s*([a-z°$€£¥ ]+?)\s+(?:to|in|into|as)\s+([a-z°$€£¥ ]+)$', s)
    if not m:
        return ("Say it like: 'convert 5 miles to km', '350 F to C', "
                "'2 cups in ml', or '100 usd to eur'.")
    val = float(m.group(1).replace(",", ""))
    frm, to = m.group(2).strip(), m.group(3).strip()

    # Currency?
    if frm in _CCY and to in _CCY:
        return currency_convert(f"{val} {frm} to {to}")

    # Temperature?
    tf = re.fullmatch(r'°?\s*(f|c|k|fahrenheit|celsius|centigrade|kelvin)', frm)
    tt = re.fullmatch(r'°?\s*(f|c|k|fahrenheit|celsius|centigrade|kelvin)', to)
    if tf and tt:
        r = _temp_convert(val, tf.group(1), tt.group(1))
        return f"🌡 {val:g}°{tf.group(1)[0].upper()} = {r:.1f}°{tt.group(1)[0].upper()}"

    for dim, table in _UNITS.items():
        f_key = frm.replace(" ", "") if frm.replace(" ", "") in table else frm
        t_key = to.replace(" ", "") if to.replace(" ", "") in table else to
        if f_key in table and t_key in table:
            r = val * table[f_key] / table[t_key]
            r_s = f"{r:,.4f}".rstrip("0").rstrip(".")
            return f"📐 {val:g} {frm} = {r_s} {to}"
    return (f"Don't know how to convert '{frm}' → '{to}'. I handle length, mass, "
            "volume/cooking, temperature, speed, data sizes, area, and currencies.")


def currency_convert(query: str = "", **_) -> str:
    """'100 usd to eur' — live ECB rates via frankfurter.app (free, keyless)."""
    s = str(query or "").lower().strip().rstrip("?")
    m = re.search(r'([\d.,]+)\s*([a-z$€£¥]+)\s+(?:to|in|into|as)\s+([a-z$€£¥]+)', s)
    if not m:
        return "Say it like: 'convert 100 usd to eur'."
    val = float(m.group(1).replace(",", ""))
    frm = _CCY.get(m.group(2), m.group(2).upper())
    to = _CCY.get(m.group(3), m.group(3).upper())
    try:
        r = requests.get("https://api.frankfurter.app/latest",
                         params={"amount": val, "from": frm, "to": to},
                         timeout=8).json()
        rate = r["rates"][to]
        return (f"💱 {val:,.2f} {frm} = {rate:,.2f} {to}\n"
                f"  (ECB reference rate, {r.get('date', 'today')})")
    except Exception:
        return (f"Couldn't get a live {frm}→{to} rate — check the codes "
                "(e.g. USD, EUR, GBP, JPY) or the internet connection.")


# ══════════════════════════════════════════════════════════════════════════════
# WORLD TIME — local zoneinfo, no API
# ══════════════════════════════════════════════════════════════════════════════

_CITY_TZ = {
    "new york": "America/New_York", "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "chicago": "America/Chicago", "denver": "America/Denver",
    "phoenix": "America/Phoenix", "anchorage": "America/Anchorage",
    "honolulu": "Pacific/Honolulu", "toronto": "America/Toronto",
    "vancouver": "America/Vancouver", "mexico city": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid", "rome": "Europe/Rome", "amsterdam": "Europe/Amsterdam",
    "zurich": "Europe/Zurich", "stockholm": "Europe/Stockholm",
    "moscow": "Europe/Moscow", "istanbul": "Europe/Istanbul",
    "athens": "Europe/Athens", "kyiv": "Europe/Kyiv", "kiev": "Europe/Kyiv",
    "dubai": "Asia/Dubai", "tel aviv": "Asia/Jerusalem", "jerusalem": "Asia/Jerusalem",
    "riyadh": "Asia/Riyadh", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "india": "Asia/Kolkata", "bangkok": "Asia/Bangkok", "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong", "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai", "china": "Asia/Shanghai", "seoul": "Asia/Seoul",
    "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo", "taipei": "Asia/Taipei",
    "manila": "Asia/Manila", "jakarta": "Asia/Jakarta",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "perth": "Australia/Perth", "auckland": "Pacific/Auckland",
    "cairo": "Africa/Cairo", "lagos": "Africa/Lagos",
    "johannesburg": "Africa/Johannesburg", "nairobi": "Africa/Nairobi",
    "utc": "UTC", "gmt": "UTC",
}


def world_time(place: str = "", **_) -> str:
    """'what time is it in Tokyo' — local zoneinfo database, offline."""
    from zoneinfo import ZoneInfo
    p = str(place or "").lower().strip().rstrip("?")
    p = re.sub(r'^(?:what\s+time\s+is\s+it\s+in|time\s+in)\s+', '', p).strip()
    if not p:
        return f"🕐 Local time: {datetime.now().strftime('%I:%M %p — %A, %b %d')}"
    tz_name = _CITY_TZ.get(p)
    if not tz_name:
        # Fuzzy only for real names — short keys like "la"/"nyc" must match
        # exactly or they hide inside unrelated words ("la" in "atlantis").
        for city, tz in _CITY_TZ.items():
            if len(city) >= 4 and (city in p or p in city):
                tz_name = tz
                break
    if not tz_name and "/" in p:
        tz_name = p.title().replace(" ", "_")
    if not tz_name:
        return (f"Don't know the timezone for '{place}'. Try a major city "
                "(Tokyo, London, Sydney...) or an IANA zone like Europe/Paris.")
    try:
        t = datetime.now(ZoneInfo(tz_name))
        here = datetime.now()
        diff = round((t.replace(tzinfo=None) - here).total_seconds() / 3600)
        return (f"🕐 {place.title()}: {t.strftime('%I:%M %p — %A, %b %d')}"
                f"  ({diff:+d}h vs here)")
    except Exception:
        return f"Couldn't resolve timezone '{tz_name}'."


# ══════════════════════════════════════════════════════════════════════════════
# DICTIONARY — dictionaryapi.dev (free, keyless)
# ══════════════════════════════════════════════════════════════════════════════

def define_word(word: str = "", **_) -> str:
    w = str(word or "").strip().strip("\"'").lower()
    if not w:
        return "Define what? e.g. 'define serendipity'"
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{w}",
                         timeout=8)
        if r.status_code == 404:
            return f"No dictionary entry found for '{w}'."
        data = r.json()[0]
        out = [f"📖 {data.get('word', w).upper()}"]
        phon = next((p["text"] for p in data.get("phonetics", []) if p.get("text")), "")
        if phon:
            out[0] += f"  {phon}"
        out.append(_RULE)
        n = 0
        syns = set()
        for meaning in data.get("meanings", []):
            pos = meaning.get("partOfSpeech", "")
            for d in meaning.get("definitions", []):
                n += 1
                out.append(f"  {n}. ({pos}) {d.get('definition', '')}")
                if d.get("example"):
                    out.append(f"     e.g. \"{d['example']}\"")
                syns |= set(d.get("synonyms", [])[:4])
                if n >= 4:
                    break
            if n >= 4:
                break
        if syns:
            out.append(f"  synonyms: {', '.join(sorted(syns)[:6])}")
        return "\n".join(out)
    except Exception:
        return f"Dictionary lookup for '{w}' failed — is the internet up?"


# ══════════════════════════════════════════════════════════════════════════════
# RANDOM — coin / dice / number / pick (local, secrets-based)
# ══════════════════════════════════════════════════════════════════════════════

def roll_random(query: str = "", **_) -> str:
    s = str(query or "").lower().strip().rstrip("?!.")
    if re.search(r'\bcoin\b', s):
        return f"🪙 {secrets.choice(['HEADS', 'TAILS'])}"
    m = re.search(r'\b(\d*)d(\d+)\b', s)          # "roll 3d6"
    if m or re.search(r'\broll\b.*\b(?:die|dice)\b', s):
        n = min(int(m.group(1) or 1), 100) if m else 1
        sides = int(m.group(2)) if m else 6
        rolls = [secrets.randbelow(sides) + 1 for _ in range(n)]
        tail = f"  (total {sum(rolls)})" if n > 1 else ""
        return f"🎲 {' + '.join(map(str, rolls))}{tail}"
    m = re.search(r'(?:between|from)\s+(-?\d+)\s+(?:and|to)\s+(-?\d+)', s)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return f"🎲 {a + secrets.randbelow(b - a + 1)}  (range {a}–{b})"
    m = re.search(r'(?:pick|choose|decide)\s+(?:between|from|one\s+of)?\s*(.+)$', s)
    if m:
        opts = [o.strip(" ,.") for o in re.split(r',|\bor\b|\band\b', m.group(1)) if o.strip(" ,.")]
        if len(opts) >= 2:
            return f"👉 {secrets.choice(opts).upper()}"
    if re.search(r'random\s+number', s):
        return f"🎲 {secrets.randbelow(100) + 1}  (1–100 default)"
    return ("Try: 'flip a coin', 'roll 2d6', 'random number between 1 and 50', "
            "or 'pick between pizza, sushi and tacos'.")


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD GENERATOR — local, cryptographic
# ══════════════════════════════════════════════════════════════════════════════

def password_gen(length: int = 16, count: int = 3, **_) -> str:
    length = max(8, min(int(length or 16), 64))
    count = max(1, min(int(count or 3), 5))
    # No ambiguous chars (0/O, 1/l/I) — these get typed by hand.
    alpha = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    symb = "!@#$%^&*-_=+"
    out = [f"🔐 PASSWORDS ({length} chars — pick one, don't reuse)", _RULE]
    for _i in range(count):
        core = [secrets.choice(alpha) for _ in range(length - 2)]
        core += [secrets.choice(symb), secrets.choice("23456789")]
        pw = list(core)
        for j in range(len(pw) - 1, 0, -1):          # secrets-based shuffle
            k = secrets.randbelow(j + 1)
            pw[j], pw[k] = pw[k], pw[j]
        out.append("  " + "".join(pw))
    out.append("  (generated locally, never sent anywhere, not stored)")
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC HOLIDAYS — date.nager.at (free, keyless)
# ══════════════════════════════════════════════════════════════════════════════

def next_holidays(country: str = "US", **_) -> str:
    cc = (str(country or "US").strip().upper()[:2]) or "US"
    try:
        r = requests.get(f"https://date.nager.at/api/v3/NextPublicHolidays/{cc}",
                         timeout=8).json()
        if not r:
            return f"No upcoming holidays found for {cc}."
        out = [f"📅 NEXT HOLIDAYS — {cc}", _RULE]
        today = datetime.now().date()
        for h in r[:8]:
            d = datetime.strptime(h["date"], "%Y-%m-%d").date()
            days = (d - today).days
            out.append(f"  {d.strftime('%b %d %a')} — {h['name']}"
                       f"  ({'today' if days == 0 else f'in {days}d'})")
        return "\n".join(out)
    except Exception:
        return f"Holiday lookup failed for '{cc}' — try a 2-letter country code (US, GB, DE...)."


# ══════════════════════════════════════════════════════════════════════════════
# FILE FINDER — local disk search with a hard time budget
# ══════════════════════════════════════════════════════════════════════════════

_SEARCH_ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "AppData", "venv", ".venv",
              "site-packages", "$RECYCLE.BIN"}


def file_find(name: str = "", where: str = "", **_) -> str:
    """Find files by name under the common user folders. 4s budget, 15 hits max."""
    q = str(name or "").strip().strip("\"'").lower()
    if len(q) < 2:
        return "Find which file? e.g. 'find file tax return'"
    roots = ([Path.home() / where] if where and (Path.home() / where).exists()
             else [Path.home() / r for r in _SEARCH_ROOTS])
    hits, deadline = [], time.time() + 4.0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if q in f.lower():
                    p = Path(dirpath) / f
                    try:
                        st = p.stat()
                        hits.append((st.st_mtime, st.st_size, str(p)))
                    except Exception:
                        pass
                    if len(hits) >= 60:
                        break
            if time.time() > deadline or len(hits) >= 60:
                break
        if time.time() > deadline:
            break
    if not hits:
        return f"No files matching '{q}' under {', '.join(r.name for r in roots)}."
    hits.sort(reverse=True)
    out = [f"📁 FILES matching '{q}' ({min(len(hits), 15)} of {len(hits)})", _RULE]
    for mt, sz, p in hits[:15]:
        size = (f"{sz / 1e9:.1f}GB" if sz > 1e9 else
                f"{sz / 1e6:.1f}MB" if sz > 1e6 else f"{sz / 1e3:.0f}KB")
        short = p.replace(str(Path.home()), "~")
        out.append(f"  {short}")
        out.append(f"    {size} — {datetime.fromtimestamp(mt).strftime('%Y-%m-%d')}")
    return "\n".join(out)
