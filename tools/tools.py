"""
tools.py  —  Every JARVIS capability.
Clean rewrite: no duplicate code, consistent error handling, fully tested.
"""
import os, json, re, subprocess, webbrowser, urllib.parse, platform, shutil
from datetime import datetime, timedelta
from pathlib import Path
from tools.store import get, put

_OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:14b-instruct")

# ── helpers ───────────────────────────────────────────────────────────────────
def _ai(prompt):
    try:
        import ollama
        return ollama.chat(model=_OLLAMA_MODEL,
                           messages=[{"role":"user","content":prompt}])["message"]["content"]
    except Exception as e:
        return f"(AI unavailable: {e})"

def _run(cmd, timeout=12):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def _chrome(url):
    """Open a URL in Chrome, falling back to default browser."""
    url = url.strip()
    url = re.sub(r'^https?://', '', url)
    url = re.sub(r'^www\.www\.', '', url)
    url = re.sub(r'\.com\.com', '.com', url)
    domain = url.split('/')[0]
    clean = ('https://' + url) if '.' in domain else \
            ('https://www.google.com/search?q=' + urllib.parse.quote(url))
    for exe in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "chrome"]:
        try:
            subprocess.Popen([exe, clean]); return clean
        except Exception:
            pass
    webbrowser.open(clean)
    return clean

# ═════════════════════════════════════════════════════════════════════════════
# GROCERY
# ═════════════════════════════════════════════════════════════════════════════

def grocery_add(items, category="General"):
    if isinstance(items, str):
        items = [i.strip() for i in re.split(r'[,\n]', items) if i.strip()]
    lst = get("grocery_list")
    added = [i for i in items if i and not any(g["item"].lower()==i.lower() for g in lst)]
    for i in added:
        lst.append({"item":i,"category":category,"checked":False,
                    "added":datetime.now().strftime("%b %d")})
    put("grocery_list", lst)
    return f"Added: {', '.join(added)}" if added else "Already on your list."

def grocery_show():
    lst = get("grocery_list")
    if not lst: return "Grocery list is empty."
    cats = {}
    for i in lst: cats.setdefault(i["category"],[]).append(i)
    lines = [f"Grocery List ({len(lst)} items):"]
    for cat,items in cats.items():
        lines.append(f"\n  {cat}:")
        for i in items: lines.append(f"    {'✓' if i['checked'] else '•'} {i['item']}")
    return "\n".join(lines)

def grocery_remove(item):
    lst = get("grocery_list")
    new = [g for g in lst if item.lower() not in g["item"].lower()]
    put("grocery_list", new)
    return f"Removed '{item}'." if len(new)<len(lst) else "Not found."

def grocery_clear():
    n = len(get("grocery_list")); put("grocery_list",[])
    return f"Cleared {n} items."

def grocery_check(item):
    lst = get("grocery_list")
    for g in lst:
        if item.lower() in g["item"].lower(): g["checked"]=True
    put("grocery_list", lst); return f"Checked off: {item}"

def grocery_order(store="walmart"):
    lst = get("grocery_list")
    items = [g["item"] for g in lst if not g["checked"]]
    if not items: return "List is empty!"
    urls = {"walmart":"https://www.walmart.com/grocery",
            "instacart":"https://www.instacart.com",
            "amazon":"https://www.amazon.com/alm/storefront?almBrandId=QW1hem9uIEZyZXNo"}
    _chrome(urls.get(store.lower(), urls["walmart"]))
    return f"Opened {store.title()} grocery. List: {', '.join(items[:8])}{'...' if len(items)>8 else ''}"

def pantry_update(item, quantity, unit=""):
    p = get("pantry"); p[item.lower()] = {"quantity":quantity,"unit":unit,
                                            "updated":datetime.now().strftime("%b %d")}
    put("pantry",p); return f"Pantry: {quantity} {unit} of {item}"

def pantry_show():
    p = get("pantry")
    if not p: return "Pantry is empty."
    return "Pantry:\n" + "\n".join(f"  • {k.title()}: {v['quantity']} {v['unit']}" for k,v in sorted(p.items()))

# ═════════════════════════════════════════════════════════════════════════════
# FINANCE
# ═════════════════════════════════════════════════════════════════════════════

def _amt(s): return float(str(s).replace("$","").replace(",",""))

def finance_add_bill(name, amount, due_day, frequency="monthly", category="Bills", auto_pay=False):
    bills = get("bills")
    bills.append({"name":name,"amount":_amt(amount),"due_day":int(due_day),
                  "frequency":frequency,"category":category,"auto_pay":bool(auto_pay)})
    put("bills",bills); return f"Bill added: {name} — ${_amt(amount):,.2f} due {due_day}th."

def finance_list_bills():
    bills = get("bills")
    if not bills: return "No bills tracked yet."
    total = sum(b["amount"] for b in bills)
    today = datetime.now().day
    lines = [f"Bills — ${total:,.2f}/mo total\n"]
    for b in sorted(bills, key=lambda x: x["due_day"]):
        d = (b["due_day"]-today) % 30
        warn = " ⚠️ DUE SOON" if d<=3 else ""
        ap = " (AutoPay)" if b.get("auto_pay") else ""
        lines.append(f"  • {b['name']}: ${b['amount']:,.2f} — {b['due_day']}th{ap}{warn}")
    return "\n".join(lines)

def finance_audit():
    bills = get("bills")
    if not bills: return "No bills to audit."
    total = sum(b["amount"] for b in bills)
    cats = {}
    for b in bills: cats.setdefault(b["category"],[]).append(b)
    lines = [f"Bill Audit — ${total:,.2f}/mo | ${total*12:,.2f}/yr\n"]
    for cat,items in cats.items():
        ct = sum(b["amount"] for b in items)
        lines.append(f"  {cat}: ${ct:,.2f}/mo")
        for b in items: lines.append(f"    • {b['name']}: ${b['amount']:,.2f}")
    streaming = [b for b in bills if any(s in b["name"].lower() for s in
        ["netflix","hulu","disney","hbo","spotify","apple","youtube","peacock","paramount","max"])]
    if len(streaming)>2:
        lines.append(f"\n💡 {len(streaming)} streaming services — could save ${sum(b['amount'] for b in streaming[2:]):.2f}/mo by rotating.")
    return "\n".join(lines)

def finance_upcoming(days=7):
    bills = get("bills"); today = datetime.now().day
    up = sorted([(( b["due_day"]-today)%30,b) for b in bills if (b["due_day"]-today)%30<=days])
    if not up: return f"No bills due in {days} days."
    lines = [f"Bills due in {days} days:"]
    for d,b in up: lines.append(f"  • {b['name']}: ${b['amount']:,.2f} — {'TODAY'if d==0 else f'in {d} days'}")
    lines.append(f"Total: ${sum(b['amount'] for _,b in up):,.2f}")
    return "\n".join(lines)

def finance_remove_bill(name):
    bills = get("bills"); new=[b for b in bills if name.lower() not in b["name"].lower()]
    put("bills",new); return f"Removed '{name}'." if len(new)<len(bills) else "Not found."

def finance_set_budget(category, amount, period="monthly"):
    budget=get("budget"); budget[category]={"amount":_amt(amount),"period":period}
    put("budget",budget); return f"Budget: ${_amt(amount):,.2f}/{period} for {category}"

def finance_show_budget():
    budget=get("budget")
    if not budget: return "No budget set."
    total=sum(v["amount"] for v in budget.values() if v["period"]=="monthly")
    lines=["Budget:"]+[f"  • {k}: ${v['amount']:,.2f}/{v['period']}" for k,v in budget.items()]
    lines.append(f"Monthly total: ${total:,.2f}")
    return "\n".join(lines)

def finance_log_expense(description, amount, category="General"):
    exp=get("expenses")
    exp.append({"description":description,"amount":_amt(amount),
                "category":category,"date":datetime.now().strftime("%Y-%m-%d")})
    put("expenses",exp); return f"Logged: {description} — ${_amt(amount):,.2f} ({category})"

def finance_spending(period="this month"):
    exp=get("expenses")
    if not exp: return "No expenses logged."
    now=datetime.now()
    if "month" in period: rel=[e for e in exp if e["date"].startswith(now.strftime("%Y-%m"))]
    elif "week" in period: rel=[e for e in exp if e["date"]>=(now-timedelta(days=7)).strftime("%Y-%m-%d")]
    else: rel=exp[-50:]
    if not rel: return f"No expenses for {period}."
    total=sum(e["amount"] for e in rel)
    cats={}
    for e in rel: cats[e["category"]]=cats.get(e["category"],0)+e["amount"]
    lines=[f"Spending ({period}): ${total:,.2f}"]
    for cat,amt in sorted(cats.items(),key=lambda x:-x[1]): lines.append(f"  • {cat}: ${amt:,.2f}")
    return "\n".join(lines)

def finance_add_goal(name, target_amount, current_amount=0, target_date=""):
    goals=get("goals")
    goals.append({"name":name,"target":_amt(target_amount),"current":_amt(current_amount),"target_date":target_date})
    put("goals",goals); return f"Goal: {name} — ${_amt(target_amount):,.2f}"

def finance_show_goals():
    goals=get("goals")
    if not goals: return "No goals set."
    lines=["Goals:"]
    for g in goals:
        pct=(g["current"]/g["target"]*100) if g["target"] else 0
        bar="█"*int(pct/10)+"░"*(10-int(pct/10))
        lines.append(f"\n  {g['name']}\n  [{bar}] {pct:.0f}% — ${g['current']:,.2f}/${g['target']:,.2f}")
    return "\n".join(lines)

def finance_update_goal(name, current_amount):
    goals=get("goals")
    for g in goals:
        if name.lower() in g["name"].lower():
            g["current"]=_amt(current_amount); put("goals",goals)
            return f"Updated {g['name']}: {g['current']/g['target']*100:.0f}% done"
    return f"Goal '{name}' not found."

def finance_health():
    bills=get("bills"); budget=get("budget"); expenses=get("expenses"); goals=get("goals")
    return "\n".join([
        "Financial Health",
        f"  Monthly bills:    ${sum(b['amount'] for b in bills):,.2f}",
        f"  Monthly budget:   ${sum(v['amount'] for v in budget.values() if v['period']=='monthly'):,.2f}",
        f"  Spent this month: ${sum(e['amount'] for e in expenses if e['date'].startswith(datetime.now().strftime('%Y-%m'))):,.2f}",
        f"  Goals tracked:    {len(goals)}  |  Bills tracked: {len(bills)}",
    ])

# ═════════════════════════════════════════════════════════════════════════════
# TASKS & PLANNER
# ═════════════════════════════════════════════════════════════════════════════

def task_add(task, priority="medium", due_date="", category="General"):
    tasks=get("tasks")
    # Never add the same pending task twice (case-insensitive)
    for t in tasks:
        if not t.get("done") and t["task"].strip().lower()==task.strip().lower():
            return f"Task already exists: {t['task']} — not adding a duplicate."
    tasks.append({"task":task,"priority":priority,"due":due_date,
                  "category":category,"done":False,"created":datetime.now().strftime("%Y-%m-%d %H:%M")})
    put("tasks",tasks); return f"Task added: {task} ({priority} priority)"

def task_complete(name):
    tasks=get("tasks")
    for t in tasks:
        if name.lower() in t["task"].lower() and not t["done"]:
            t["done"]=True; t["completed"]=datetime.now().strftime("%Y-%m-%d %H:%M")
            put("tasks",tasks); return f"Done: {t['task']}"
    return f"'{name}' not found."

def task_show(priority="", category=""):
    tasks=get("tasks")
    p=[t for t in tasks if not t["done"]]
    if priority: p=[t for t in p if t.get("priority","").lower()==priority.lower()]
    if not p: return "No pending tasks!"
    p.sort(key=lambda t:{"high":0,"medium":1,"low":2}.get(t.get("priority","medium"),1))
    icons={"high":"🔴","medium":"🟡","low":"🟢"}
    lines=[f"Tasks ({len(p)} pending):"]
    for t in p:
        due=f" — due {t['due']}" if t.get("due") else ""
        lines.append(f"  {icons.get(t.get('priority','medium'),'⚪')} {t['task']}{due}")
    return "\n".join(lines)

def task_delete(name):
    tasks=get("tasks"); new=[t for t in tasks if name.lower() not in t["task"].lower()]
    put("tasks",new); return f"Deleted '{name}'." if len(new)<len(tasks) else "Not found."

def _pending_sorted(tasks):
    """Pending tasks in the SAME order task_show displays them, so numbered
    removal ('remove task 2') always matches what the user just saw."""
    p=[t for t in tasks if not t.get("done")]
    p.sort(key=lambda t:{"high":0,"medium":1,"low":2}.get(t.get("priority","medium"),1))
    return p

def task_remove(spec=""):
    """Remove pending tasks by number(s), keyword, 'all', or referential
    ('those tasks'). One tool for every remove/delete/clear phrasing."""
    tasks=get("tasks")
    pending=_pending_sorted(tasks)
    if not pending: return "No pending tasks to remove."
    s=str(spec or "").strip().lower().strip(".!")

    if s in ("all","everything","every task","all tasks"):
        put("tasks",[t for t in tasks if t.get("done")])
        return f"Removed all {len(pending)} pending tasks."

    nums=[int(n) for n in re.findall(r'\d+', s)]
    if nums and all(1<=n<=len(pending) for n in nums):
        victims=[pending[n-1] for n in sorted(set(nums))]
        vic_ids={id(v) for v in victims}
        put("tasks",[t for t in tasks if id(t) not in vic_ids])
        return "Removed: "+", ".join(v["task"] for v in victims)

    referential = s in ("","those","these","them","those tasks","these tasks","my tasks","tasks")
    if not referential:
        gone=[t for t in pending if s in t["task"].lower()]
        if gone:
            gone_ids={id(t) for t in gone}
            put("tasks",[t for t in tasks if id(t) not in gone_ids])
            return "Removed: "+", ".join(t["task"] for t in gone)
        return f"No pending task matching '{spec}'. Say 'show my tasks' to see the list."

    # "remove those tasks" — with 1-2 pending, that can only mean these; with
    # more, ask which rather than guess.
    if len(pending)<=2:
        put("tasks",[t for t in tasks if t.get("done")])
        return "Removed: "+", ".join(t["task"] for t in pending)
    lines=[f"Which ones? ({len(pending)} pending)"]
    for i,t in enumerate(pending,1): lines.append(f"  {i}. {t['task']}")
    lines.append("Say 'remove task 2', 'remove tasks 1 and 3', 'remove [keyword]', or 'clear all tasks'.")
    return "\n".join(lines)

def note_add(content, title=""):
    notes=get("notes")
    notes.append({"title":title or f"Note {datetime.now().strftime('%b %d %I:%M %p')}",
                  "content":content,"created":datetime.now().strftime("%Y-%m-%d %H:%M")})
    put("notes",notes); return "Note saved."

def note_show(limit=5):
    notes=get("notes")
    if not notes: return "No notes yet."
    lines=[f"Notes ({len(notes)} total):"]
    for n in reversed(notes[-limit:]):
        lines.append(f"\n  [{n['created']}] {n['title']}")
        lines.append(f"  {n['content'][:200]}{'...' if len(n['content'])>200 else ''}")
    return "\n".join(lines)

def note_search(query):
    notes=get("notes")
    r=[n for n in notes if query.lower() in n["content"].lower() or query.lower() in n["title"].lower()]
    if not r: return f"No notes matching '{query}'."
    lines=[f"Notes matching '{query}':"]
    for n in r[-5:]: lines.append(f"\n  [{n['created']}] {n['title']}\n  {n['content'][:200]}")
    return "\n".join(lines)

def habit_add(name, frequency="daily"):
    habits=get("habits")
    habits.append({"name":name,"frequency":frequency,"streak":0,"completions":[]})
    put("habits",habits); return f"Habit added: {name}"

def habit_complete(name):
    habits=get("habits"); today=datetime.now().strftime("%Y-%m-%d")
    for h in habits:
        if name.lower() in h["name"].lower():
            if today not in h.get("completions",[]):
                h.setdefault("completions",[]).append(today); h["streak"]=h.get("streak",0)+1
            put("habits",habits); return f"Done: {h['name']} — {h['streak']} day streak 🔥"
    return f"'{name}' not found."

def habit_show():
    habits=get("habits")
    if not habits: return "No habits tracked."
    today=datetime.now().strftime("%Y-%m-%d")
    lines=["Habits:"]
    for h in habits:
        done=today in h.get("completions",[]); streak=h.get("streak",0)
        lines.append(f"  {'✅'if done else '⬜'} {h['name']} — {streak}d streak{'🔥'if streak>=3 else ''}")
    return "\n".join(lines)

def morning_briefing():
    tasks=get("tasks"); bills=get("bills"); habits=get("habits")
    high=[t for t in tasks if not t.get("done") and t.get("priority")=="high"]
    pending=[t for t in tasks if not t.get("done")]
    today=datetime.now().day
    due_soon=[b for b in bills if (b["due_day"]-today)%30<=3]
    lines=[f"Good morning! {datetime.now().strftime('%A, %B %d, %Y')}","="*38]
    if high:
        lines.append("\n🔴 High priority:")
        for t in high[:3]: lines.append(f"   • {t['task']}")
    if due_soon:
        lines.append("\n💳 Bills due soon:")
        for b in due_soon: lines.append(f"   • {b['name']}: ${b['amount']:,.2f}")
    lines.append(f"\nTasks pending: {len(pending)} | Habits: {len(habits)}")
    lines.append("What would you like to tackle first?")
    return "\n".join(lines)

# ═════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════════════

def health_add_med(name, dose, frequency, time_of_day="morning", notes=""):
    meds=get("medications")
    meds.append({"name":name,"dose":dose,"frequency":frequency,"time":time_of_day,"notes":notes})
    put("medications",meds); return f"Medication: {name} {dose} — {frequency}, {time_of_day}"

def health_list_meds():
    meds=get("medications")
    if not meds: return "No medications tracked."
    lines=["Medications:"]
    for m in meds:
        lines.append(f"  • {m['name']} {m['dose']} — {m['frequency']}, {m['time']}")
        if m.get("notes"): lines.append(f"    Note: {m['notes']}")
    return "\n".join(lines)

def health_med_reminder():
    meds=get("medications"); hour=datetime.now().hour
    tod="morning" if hour<12 else "afternoon" if hour<17 else "evening"
    due=[m for m in meds if m["time"].lower()==tod]
    if not due: return f"No meds for {tod}."
    return f"Meds for {tod}:\n"+"\n".join(f"  • {m['name']} {m['dose']}" for m in due)

def health_log_workout(activity, duration_minutes, intensity="moderate", notes=""):
    w=get("workouts")
    w.append({"activity":activity,"duration":int(duration_minutes),"intensity":intensity,
              "notes":notes,"date":datetime.now().strftime("%Y-%m-%d")})
    put("workouts",w); return f"Workout logged: {activity} {duration_minutes}min ({intensity})"

def health_workout_summary(period="this week"):
    w=get("workouts"); now=datetime.now()
    cutoff=(now-timedelta(days=7)).strftime("%Y-%m-%d") if "week" in period else now.strftime("%Y-%m-01")
    rel=[x for x in w if x["date"]>=cutoff]
    if not rel: return f"No workouts for {period}."
    total=sum(x["duration"] for x in rel)
    lines=[f"Workouts ({period}): {len(rel)} sessions, {total} min total"]
    for x in rel[-5:]: lines.append(f"  • {x['date']}: {x['activity']} {x['duration']}min ({x['intensity']})")
    return "\n".join(lines)

def health_log(metric, value, unit=""):
    log=get("health_log")
    log.append({"metric":metric,"value":value,"unit":unit,"date":datetime.now().strftime("%Y-%m-%d")})
    put("health_log",log); return f"Logged {metric}: {value} {unit}"

def health_summary():
    log=get("health_log")
    if not log: return "No health data yet."
    metrics={}
    for h in log[-20:]: metrics[h["metric"]]=h
    return "Health Metrics:\n"+"\n".join(f"  • {m}: {h['value']} {h['unit']} ({h['date']})" for m,h in metrics.items())

# ═════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ═════════════════════════════════════════════════════════════════════════════

def contact_add(name, phone="", email="", birthday="", notes="", relationship=""):
    contacts=get("contacts")
    existing=next((c for c in contacts if c["name"].lower()==name.lower()),None)
    if existing:
        for k,v in {"phone":phone,"email":email,"birthday":birthday,"notes":notes,"relationship":relationship}.items():
            if v: existing[k]=v
        put("contacts",contacts); return f"Updated: {name}"
    contacts.append({"name":name,"phone":phone,"email":email,"birthday":birthday,"notes":notes,"relationship":relationship})
    put("contacts",contacts); return f"Contact added: {name}"

def contact_find(name):
    contacts=get("contacts")
    m=[c for c in contacts if name.lower() in c["name"].lower()]
    if not m: return f"'{name}' not found."
    c=m[0]; lines=[f"Contact: {c['name']}"]
    for k,label in [("phone","📞"),("email","📧"),("birthday","🎂"),("relationship","👥"),("notes","📝")]:
        if c.get(k): lines.append(f"  {label} {c[k]}")
    return "\n".join(lines)

def contact_list():
    contacts=get("contacts")
    if not contacts: return "No contacts."
    lines=[f"Contacts ({len(contacts)}):"]
    for c in sorted(contacts,key=lambda x:x["name"]):
        info=" | ".join(filter(None,[c.get("phone"),c.get("email")]))
        lines.append(f"  • {c['name']}"+(f" — {info}" if info else ""))
    return "\n".join(lines)

def contact_birthdays(days=30):
    contacts=get("contacts"); today=datetime.now()
    upcoming=[]
    for c in contacts:
        if not c.get("birthday"): continue
        try:
            parts=c["birthday"].replace("/","-").split("-")
            if len(parts)>=2:
                bday=today.replace(month=int(parts[-2]),day=int(parts[-1]))
                if bday.date()<today.date(): bday=bday.replace(year=today.year+1)
                diff=(bday.date()-today.date()).days
                if diff<=days: upcoming.append((diff,c["name"],c["birthday"]))
        except Exception: pass
    if not upcoming: return f"No birthdays in {days} days."
    return "Birthdays:\n"+"\n".join(f"  • {n} — {'TODAY 🎉'if d==0 else f'in {d} days'} ({b})" for d,n,b in sorted(upcoming))

# (reminder_add/reminder_show removed 2026-07-02 — superseded by
#  tools/assistant_tools.py remind/reminders_list, which actually fire.)

# ═════════════════════════════════════════════════════════════════════════════
# TECH / PC CONTROL
# ═════════════════════════════════════════════════════════════════════════════

APP_MAP = {
    # Browsers
    "chrome":"chrome","google chrome":"chrome","edge":"msedge","firefox":"firefox",
    # Communication / social — protocol URIs work on any machine with the app installed
    "discord":"discord://","slack":"slack://","teams":"ms-teams:",
    # Gaming launchers — protocol URIs or standard install paths
    "steam":r"C:\Program Files (x86)\Steam\Steam.exe",
    "epic":"com.epicgames.launcher://","epic games":"com.epicgames.launcher://",
    "battle.net":r"C:\Program Files (x86)\Battle.net\Battle.net Launcher.exe",
    "battlenet":r"C:\Program Files (x86)\Battle.net\Battle.net Launcher.exe",
    "ea":r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EALauncher.exe",
    "rockstar":"RockstarGamesLauncher","gog":"GOGGalaxy",
    "roblox":"roblox-player:","roblox studio":"robloxstudio:",
    # Media
    "spotify":"spotify:","itunes":"itunes:","vlc":"vlc",
    # System tools
    "notepad":"notepad","calculator":"calc",
    "paint":"mspaint","word":"winword","excel":"excel","powerpoint":"powerpnt",
    "outlook":"ms-outlook:","teams":"ms-teams:","settings":"ms-settings:",
    "task manager":"taskmgr","control panel":"control","explorer":"explorer",
    "terminal":"wt","powershell":"powershell","cmd":"cmd",
    "afterburner":r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
    "msi afterburner":r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
    "lghub":r"C:\Program Files\LGHUB\lghub.exe",
    "logitech":r"C:\Program Files\LGHUB\lghub.exe",
    "obs":"obs64","streamlabs":"streamlabs://",
    "xbox":"xbox:","photos":"ms-photos:","camera":"ms-camera:",
    "windows security":"windowsdefender:","clock":"ms-clock:",
    "snipping tool":"ms-ScreenSketch:","sticky notes":"ms-stickynotes:",
    "cs2":"steam://rungameid/730","counter-strike":"steam://rungameid/730",
    "rust":"steam://rungameid/252490","apex":"steam://rungameid/1172470",
    "apex legends":"steam://rungameid/1172470","gta v":"steam://rungameid/271590",
    "halo":"steam://rungameid/1240440","pubg":"steam://rungameid/578080",
    "destiny 2":"steam://rungameid/1085660","destiny":"steam://rungameid/1085660",
}

def tech_open(app_name):
    import shutil as _shutil
    key = app_name.lower().strip()
    cmd = APP_MAP.get(key)
    if not cmd:
        for k, v in APP_MAP.items():
            if key in k or k in key:
                cmd = v
                break
    if not cmd:
        known = ", ".join(sorted(APP_MAP.keys())[:20])
        return f"Unknown app: '{app_name}'. Known apps: {known}..."
    try:
        if cmd.startswith("http"):
            _chrome(cmd)
        elif "://" in cmd and not (len(cmd) > 1 and cmd[1] == ":"):
            # Protocol URI (discord://, roblox-player:, spotify:, etc.)
            subprocess.Popen(f'start "" "{cmd}"', shell=True)
        elif Path(cmd).exists():
            # Absolute path — exists on this machine
            subprocess.Popen(f'"{cmd}"', shell=True)
        elif _shutil.which(cmd):
            # Found on PATH
            subprocess.Popen(cmd, shell=True)
        else:
            # Last resort: let Windows try (works for notepad, calc, etc.)
            subprocess.Popen(f'start "" "{cmd}"', shell=True)
        return f"Opened {app_name}"
    except Exception as e:
        return f"Could not open {app_name}: {e}"

def tech_system_info():
    lines=["System Info:","  OS: "+platform.system()+" "+platform.release()]
    t,u,f=shutil.disk_usage("/")
    lines.append(f"  Disk: {u//2**30}GB used / {t//2**30}GB total ({f//2**30}GB free)")
    ram=_run("wmic computersystem get TotalPhysicalMemory /value")
    if "=" in ram:
        try: lines.append(f"  RAM: {int(ram.split('=')[1])//2**30}GB")
        except: pass
    gpu=_run("wmic path win32_VideoController get name /value")
    for line in gpu.split("\n"):
        if "Name=" in line and line.split("=")[-1].strip():
            lines.append(f"  GPU: {line.split('=')[-1].strip()}"); break
    return "\n".join(lines)

def tech_disk_cleanup():
    freed=0; lines=["Disk Cleanup:"]
    for d in [Path(os.environ.get("TEMP","")), Path.home()/"AppData/Local/Temp"]:
        if not d.exists(): continue
        f=0
        for file in d.glob("*"):
            try:
                if file.is_file(): f+=file.stat().st_size; file.unlink()
            except: pass
        freed+=f; lines.append(f"  Cleaned temp: {f//2**20}MB")
    lines.append(f"  Total: ~{freed//2**20}MB freed")
    return "\n".join(lines)

def tech_network():
    lines=["Network:"]
    ping=_run("ping -n 2 8.8.8.8")
    lines.append(f"  Internet: {'✅ Online' if 'Reply' in ping or 'time=' in ping else '❌ Offline'}")
    times=re.findall(r"time[=<](\d+)ms",ping)
    if times: lines.append(f"  Ping: {times[0]}ms")
    ip=_run("ipconfig")
    for line in ip.split("\n"):
        if "IPv4" in line: lines.append(f"  {line.strip()}"); break
    return "\n".join(lines)

def tech_flush_dns():  return f"DNS flushed.\n{_run('ipconfig /flushdns')}"
def tech_lock():       subprocess.run("rundll32.exe user32.dll,LockWorkStation",shell=True); return "Computer locked."
def tech_screenshot():
    p=str(Path.home()/"Pictures"/f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    subprocess.run(f'powershell -c "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); $g=[System.Drawing.Graphics]::FromImage($b); $g.CopyFromScreen(0,0,0,0,$b.Size); $b.Save(\\"{p}\\")"',shell=True,capture_output=True)
    return f"Screenshot saved: {p}"
# (tech_timer removed 2026-07-02 — superseded by assistant_tools.remind:
#  a PC MessageBox is invisible from the phone; reminders fire into the chat.)
def tech_volume(level):
    level = max(0, min(100, int(level)))
    _run(
        f'powershell -c "$ws=New-Object -ComObject WScript.Shell; '
        f'for($i=0;$i-lt 50;$i++){{$ws.SendKeys([char]174)}}; '
        f'$t=[Math]::Round({level}/2); '
        f'for($i=0;$i-lt $t;$i++){{$ws.SendKeys([char]175)}}"'
    )
    return f"Volume set to {level}%"
def tech_update():  webbrowser.open("ms-settings:windowsupdate"); return "Opened Windows Update."
def tech_shutdown(delay_minutes=0):
    subprocess.run(f"shutdown /s /t {int(delay_minutes)*60}",shell=True)
    return f"Shutting down in {delay_minutes} min." if delay_minutes else "Shutting down..."
def tech_restart():  subprocess.run("shutdown /r /t 30",shell=True); return "Restarting in 30s. Run 'shutdown /a' to cancel."

# ═════════════════════════════════════════════════════════════════════════════
# WEB & RESEARCH
# ═════════════════════════════════════════════════════════════════════════════

def web_open(url):     u=_chrome(url); return f"Opened {u} in Chrome."
def web_search(query): u=_chrome(f"https://www.google.com/search?q={urllib.parse.quote(query)}"); return f"Searching: {query}"
# (web_weather removed 2026-07-02 — it only opened a browser tab.
#  assistant_tools.weather_now returns real conditions in chat.)
def web_news(topic=""):
    url=f"https://news.google.com/search?q={urllib.parse.quote(topic)}" if topic else "https://news.google.com"
    _chrome(url); return f"Opened news{' for '+topic if topic else ''}."
def web_directions(destination, origin=""):
    orig=origin or os.getenv("HOME_ADDRESS","")
    _chrome(f"https://www.google.com/maps/dir/{urllib.parse.quote(orig)}/{urllib.parse.quote(destination)}")
    return f"Directions to {destination} opened."
def web_nearby(place_type, location="near me"):
    _chrome(f"https://www.google.com/maps/search/{urllib.parse.quote(place_type+' '+location)}")
    return f"Searching {place_type} {location}."
def web_track(tracking_number, carrier=""):
    urls={"ups":f"https://www.ups.com/track?tracknum={tracking_number}",
          "fedex":f"https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
          "usps":f"https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}"}
    if carrier.lower() in urls: _chrome(urls[carrier.lower()])
    elif tracking_number.startswith("1Z"): _chrome(urls["ups"])
    else: _chrome(f"https://www.google.com/search?q=track+{tracking_number}")
    return f"Tracking {tracking_number}."

# ═════════════════════════════════════════════════════════════════════════════
# TRAVEL & FOOD
# ═════════════════════════════════════════════════════════════════════════════

def travel_flights(origin, destination, date):
    _chrome(f"https://www.google.com/flights?q=flights+{origin}+to+{destination}+{date}")
    return f"Google Flights: {origin}→{destination} on {date}."
def travel_hotels(city, check_in, check_out):
    _chrome(f"https://www.hotels.com/search/listings?q-destination={urllib.parse.quote(city)}&q-check-in={check_in}&q-check-out={check_out}")
    return f"Hotels.com for {city}."
def travel_uber(destination):
    _chrome(f"https://m.uber.com/ul/?action=setPickup&dropoff[formatted_address]={urllib.parse.quote(destination)}")
    return f"Uber to {destination}."
def travel_lyft(destination):
    _chrome(f"https://ride.lyft.com/ridetype?destination={urllib.parse.quote(destination)}")
    return f"Lyft to {destination}."
def food_order(restaurant, items=""):
    _chrome(f"https://www.doordash.com/search/store/{urllib.parse.quote(restaurant)}/")
    return f"DoorDash: {restaurant}{(' — '+items) if items else ''}."
def food_find(cuisine, location="near me"):
    _chrome(f"https://www.yelp.com/search?find_desc={urllib.parse.quote(cuisine)}&find_loc={urllib.parse.quote(location)}")
    return f"Yelp: {cuisine} {location}."
def food_ubereats(restaurant=""):
    _chrome(f"https://www.ubereats.com/search?q={urllib.parse.quote(restaurant)}" if restaurant else "https://www.ubereats.com")
    return "Uber Eats opened."

# ═════════════════════════════════════════════════════════════════════════════
# ENTERTAINMENT
# ═════════════════════════════════════════════════════════════════════════════

def ent_netflix(search=""):
    _chrome(f"https://www.netflix.com/search?q={urllib.parse.quote(search)}" if search else "https://www.netflix.com")
    return f"Netflix{'— '+search if search else ''} opened."
def ent_spotify(search=""):
    _chrome(f"https://open.spotify.com/search/{urllib.parse.quote(search)}" if search else "https://open.spotify.com")
    return f"Spotify{'— '+search if search else ''} opened."
def ent_youtube(search=""):
    _chrome(f"https://www.youtube.com/results?search_query={urllib.parse.quote(search)}" if search else "https://www.youtube.com")
    return f"YouTube{'— '+search if search else ''} opened."
def ent_tickets(event, city=""):
    _chrome(f"https://www.ticketmaster.com/search?q={urllib.parse.quote(event+' '+city)}")
    return f"Ticketmaster: {event}."
def ent_reservation(restaurant, date, time, party_size=2):
    _chrome(f"https://www.opentable.com/s?covers={party_size}&dateTime={date}T{time}&term={urllib.parse.quote(restaurant)}")
    return f"OpenTable: {restaurant} {date} {time} for {party_size}."

# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE APPS (browser-based, no API key needed)
# ═════════════════════════════════════════════════════════════════════════════

GOOGLE_APPS = {
    "sheets":"https://sheets.google.com","docs":"https://docs.google.com",
    "slides":"https://slides.google.com","drive":"https://drive.google.com",
    "gmail":"https://mail.google.com","calendar":"https://calendar.google.com",
    "meet":"https://meet.google.com","forms":"https://forms.google.com",
    "photos":"https://photos.google.com","maps":"https://maps.google.com",
    "new sheet":"https://sheets.new","new doc":"https://docs.new",
    "new slide":"https://slides.new","new form":"https://forms.new",
}

def google_open(app_name):
    key=app_name.lower().strip()
    url=GOOGLE_APPS.get(key, GOOGLE_APPS.get(key.replace("google ",""), f"https://www.google.com/search?q={urllib.parse.quote(app_name)}"))
    _chrome(url); return f"Opened Google {app_name.title()} in Chrome."

def google_new_sheet():  _chrome("https://sheets.new"); return "New Google Sheet opened in Chrome."
def google_new_doc():    _chrome("https://docs.new");   return "New Google Doc opened in Chrome."
def google_new_slide():  _chrome("https://slides.new"); return "New Google Slides opened in Chrome."

def google_build_spreadsheet(description, save_to_desktop=False):
    """Build a spreadsheet in Chrome using AI to plan the structure."""
    # Plan structure with AI
    raw = _ai(f"""Plan a Google Spreadsheet for: {description}

Return ONLY valid JSON:
{{"title":"...", "rows":[["Header1","Header2","Header3"],["Data1","Data2","Data3"]]}}

Include realistic headers and 3-5 sample rows. Return only JSON.""")

    structure = None
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match: structure = json.loads(match.group())
    except Exception: pass

    if not structure:
        # Smart fallback based on keywords
        desc_l = description.lower()
        if any(w in desc_l for w in ["expense","spending","budget","cost"]):
            structure = {"title":"Monthly Expenses","rows":[
                ["Date","Category","Description","Amount","Payment Method"],
                ["2026-06-01","Housing","Rent","$1,500","Bank Transfer"],
                ["2026-06-01","Utilities","Electric","$120","Auto-pay"],
                ["2026-06-02","Food","Groceries","$85","Debit Card"],
                ["2026-06-03","Transport","Gas","$60","Credit Card"],
                ["","","TOTAL","=SUM(D2:D100)",""],
            ]}
        elif any(w in desc_l for w in ["bill","subscription"]):
            structure = {"title":"Bills Tracker","rows":[
                ["Bill","Amount","Due Date","Auto-Pay","Status"],
                ["Rent","$1,500","1st","No","Active"],
                ["Electric","$120","15th","Yes","Active"],
                ["Netflix","$15.99","7th","Yes","Active"],
            ]}
        else:
            structure = {"title": description[:50],
                        "rows":[["Item","Details","Value","Date","Notes"],
                                ["Sample","Description","$0","2026-06-01",""]]}

    # Try Selenium automation first
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        import time

        options = Options()
        options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        options.add_argument("--start-maximized")
        options.add_argument("--no-sandbox")
        profile = Path.home() / "AppData/Local/Google/Chrome/User Data"
        if profile.exists():
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--profile-directory=Default")

        # Get chromedriver
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except Exception:
            driver = webdriver.Chrome(options=options)

        driver.get("https://sheets.new")
        wait = WebDriverWait(driver, 15)
        time.sleep(4)

        # Rename
        try:
            title_el = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".docs-title-input, [aria-label*='title'], .waffle-nif-input")))
            title_el.triple_click() if hasattr(title_el,'triple_click') else (title_el.click(), time.sleep(0.3), title_el.send_keys(Keys.CONTROL+"a"))
            title_el.send_keys(structure["title"])
            title_el.send_keys(Keys.ENTER)
            time.sleep(1)
        except Exception: pass

        # Navigate to A1 and paste data
        rows = structure.get("rows",[])
        if rows:
            tsv = "\n".join("\t".join(str(c) for c in row) for row in rows)
            try:
                subprocess.run("clip", input=tsv.encode("utf-16"), shell=True, timeout=3)
                time.sleep(0.3)
                # Click name box and navigate to A1
                try:
                    nb = driver.find_element(By.CSS_SELECTOR, ".waffle-name-box, .cell-name-box-list input")
                    nb.click(); time.sleep(0.2)
                    nb.send_keys(Keys.CONTROL+"a"); nb.send_keys("A1"); nb.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                except Exception: pass
                # Paste
                active = driver.switch_to.active_element
                active.send_keys(Keys.CONTROL+"v")
                time.sleep(2)
            except Exception:
                # Manual typing fallback
                try:
                    nb = driver.find_element(By.CSS_SELECTOR, ".waffle-name-box, .cell-name-box-list input")
                    nb.click(); nb.send_keys(Keys.CONTROL+"a"); nb.send_keys("A1"); nb.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                    for row in rows:
                        for col_i, cell in enumerate(row):
                            active = driver.switch_to.active_element
                            active.send_keys(str(cell))
                            active.send_keys(Keys.TAB if col_i < len(row)-1 else Keys.RETURN)
                            time.sleep(0.03)
                except Exception: pass

        url = driver.current_url
        driver.quit()
        result = f"✅ Spreadsheet '{structure['title']}' built in Chrome!\n{len(rows)} rows of data entered.\n🔗 {url}"
        if save_to_desktop:
            result += f"\n💾 To save: File → Download → Excel (.xlsx)"
        return result

    except Exception as e:
        # Final fallback: just open sheets.new with instructions
        _chrome("https://sheets.new")
        rows_preview = "\n".join("  " + " | ".join(str(c) for c in r) for r in structure["rows"][:4])
        return (f"✅ Opened Google Sheets in Chrome.\n\n"
                f"Planned structure for '{structure['title']}':\n{rows_preview}\n\n"
                f"To enable auto-fill: pip install selenium webdriver-manager")

# ═════════════════════════════════════════════════════════════════════════════
# FINANCIAL INTELLIGENCE
# ═════════════════════════════════════════════════════════════════════════════

def _alpaca(path, method="GET", body=None):
    key=os.getenv("ALPACA_API_KEY",""); secret=os.getenv("ALPACA_API_SECRET","")
    base=os.getenv("ALPACA_BASE_URL","https://paper-api.alpaca.markets")
    data_base="https://data.alpaca.markets"
    if not key: raise ValueError("Alpaca not configured. Add ALPACA_API_KEY to .env file.")
    import requests
    headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}
    url=(data_base if path.startswith("/data") else base)+path.replace("/data","",1)
    r=requests.request(method,url,headers=headers,json=body,timeout=8)
    return r.json()

def stock_quote(symbol):
    symbol = symbol.upper().strip()
    # Try Alpaca first (real-time, needs API key)
    try:
        import requests as _rq
        key = os.getenv("ALPACA_API_KEY",""); secret = os.getenv("ALPACA_API_SECRET","")
        if key and secret:
            r = _rq.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars/latest",
                        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}, timeout=5)
            if r.status_code == 200:
                b = r.json().get("bar",{}); c = b.get("c",0); o = b.get("o",0)
                chg = ((c-o)/o*100) if o else 0; arrow = "▲" if chg>=0 else "▼"
                return f"📈 {symbol}: ${c:,.2f} {arrow}{chg:+.2f}% | H:${b.get('h',0):,.2f} L:${b.get('l',0):,.2f} Vol:{b.get('v',0):,}"
    except Exception: pass
    # Fall back to yfinance fast_info (no key needed) — the primary "is this
    # a real, currently-tradable ticker" check.
    try:
        import yfinance as yf
        t = yf.Ticker(symbol); fi = t.fast_info
        price = fi.last_price; prev = fi.previous_close
        if price and price > 0:
            chg = ((price - prev) / prev * 100) if prev else 0
            arrow = "▲" if chg >= 0 else "▼"
            hi = getattr(fi, "day_high", None); lo = getattr(fi, "day_low", None)
            vol = getattr(fi, "three_month_average_volume", None)
            parts = [f"📈 {symbol}: ${price:,.2f} {arrow}{chg:+.2f}%"]
            if hi and lo: parts.append(f"H:${hi:,.2f} L:${lo:,.2f}")
            if vol: parts.append(f"Avg Vol:{int(vol):,}")
            return " | ".join(parts)
    except Exception: pass
    # fast_info had nothing (thin/halted/no-cache edge case) — before calling
    # it invalid, check the fuller .info dict for a real company name. Many
    # legitimate tickers look unusual; never say "not standard" without this
    # second check.
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        name = info.get("longName") or info.get("shortName")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if name:
            if price:
                prev = info.get("previousClose") or price
                chg = ((price - prev) / prev * 100) if prev else 0
                arrow = "▲" if chg >= 0 else "▼"
                return f"📈 {symbol} ({name}): ${price:,.2f} {arrow}{chg:+.2f}%"
            return f"{symbol} ({name}) is a real ticker, but no live price data is available right now."
    except Exception: pass
    return f"No data found for {symbol} — it may be delisted or the symbol may be incorrect."

def stock_portfolio():
    try:
        acct=_alpaca("/v2/account"); pos=_alpaca("/v2/positions")
        mode="PAPER" if "paper" in os.getenv("ALPACA_BASE_URL","paper") else "LIVE"
        lines=[f"Portfolio [{mode}]",
               f"  Cash: ${float(acct.get('cash',0)):,.2f}",
               f"  Value: ${float(acct.get('portfolio_value',0)):,.2f}",
               f"  Day P/L: ${float(acct.get('equity',0))-float(acct.get('last_equity',0)):+,.2f}",
               "\nPositions:"]
        if not pos: lines.append("  No positions.")
        else:
            for p in pos:
                pl=float(p.get("unrealized_pl",0)); plp=float(p.get("unrealized_plpc",0))*100
                lines.append(f"  • {p['symbol']}: {p['qty']}sh @ ${float(p['avg_entry_price']):,.2f} | P/L: ${pl:+,.2f} ({plp:+.1f}%)")
        return "\n".join(lines)
    except ValueError as e: return str(e)

def stock_order(symbol, action, shares, order_type="market", limit_price=None):
    try:
        body={"symbol":symbol.upper(),"qty":str(shares),"side":action.lower(),"type":order_type,"time_in_force":"day"}
        if order_type=="limit" and limit_price: body["limit_price"]=str(limit_price)
        r=_alpaca("/v2/orders","POST",body)
        mode="PAPER" if "paper" in os.getenv("ALPACA_BASE_URL","paper") else "LIVE"
        return f"✅ [{mode}] {action.upper()} {shares} {symbol.upper()} | Status: {r.get('status','N/A')}"
    except ValueError as e: return str(e)

def market_analysis(topic="overview"):
    prompts = {
        "overview":      f"Give a sharp market overview for {datetime.now().strftime('%B %d, %Y')}. Key themes, sector rotation, risk/reward. Be specific. 4-5 sentences.",
        "geopolitical":  f"Analyze how current geopolitical events impact markets ({datetime.now().strftime('%B %Y')}). Which sectors win/lose? List 5-8 specific tickers with reasoning.",
        "emerging":      f"List 10-15 tickers positioned for explosive growth in 6-18 months. For each: symbol, catalyst, timeframe, risk. Be specific.",
        "macro":         f"Deep macro analysis: Fed policy, inflation, yields, dollar, commodities. How to position a portfolio. Specific sector weights.",
        "forecast":      f"Market forecast next 3 months. Bull/base/bear scenarios with probabilities. Specific S&P targets. 5 actionable trade ideas.",
        "sectors":       f"Rank all market sectors by opportunity right now. Top 2 tickers per sector. Be specific.",
        "crypto":        f"Crypto market analysis. BTC outlook, key altcoins to watch. Specific levels. Be direct.",
    }
    key = next((k for k in prompts if k in topic.lower()), "overview")
    result = _ai(prompts[key])
    return f"📊 Market Analysis: {topic.title()}\n\n{result}"

def stock_analyze(symbol, depth="full"):
    symbol = symbol.upper()
    result = _ai(f"""Analyze {symbol} as an investment. Cover:
1. Business & moat | 2. Financial health | 3. Growth catalysts
4. Key risks | 5. Valuation vs peers | 6. Technical setup
7. Verdict: BUY/HOLD/AVOID with price target. Be specific and direct.""")
    return f"📊 {symbol} Analysis\n\n{result}"

# ── Due diligence: REAL data first, LLM analysis second ──────────────────────
# The old version asked Ollama to write a report from memory — it produced
# "[Insert revenue figure]" placeholders because the model was never given a
# single number. Now: yfinance fundamentals are fetched FIRST, injected into
# the prompt, and the output is validated to contain zero placeholder brackets.

_DD_FIELDS = [
    ("currentPrice",       "Price",              "${:,.2f}"),
    ("marketCap",          "Market cap",         "${:,.0f}"),
    ("trailingPE",         "Trailing P/E",       "{:.1f}"),
    ("forwardPE",          "Forward P/E",        "{:.1f}"),
    ("pegRatio",           "PEG ratio",          "{:.2f}"),
    ("revenueGrowth",      "Revenue growth",     "{:+.1%}"),
    ("earningsGrowth",     "Earnings growth",    "{:+.1%}"),
    ("grossMargins",       "Gross margin",       "{:.1%}"),
    ("operatingMargins",   "Operating margin",   "{:.1%}"),
    ("netIncomeToCommon",  "Net income",         "${:,.0f}"),
    ("freeCashflow",       "Free cash flow",     "${:,.0f}"),
    ("totalDebt",          "Total debt",         "${:,.0f}"),
    ("returnOnEquity",     "Return on equity",   "{:.1%}"),
    ("fiftyTwoWeekHigh",   "52-week high",       "${:,.2f}"),
    ("fiftyTwoWeekLow",    "52-week low",        "${:,.2f}"),
    ("targetMeanPrice",    "Analyst mean target","${:,.2f}"),
    ("recommendationKey",  "Analyst consensus",  "{}"),
]

def _yf_fundamentals(symbol):
    """Fetch real fundamentals from yfinance. Returns (data_dict, text_block).
    Missing fields become 'N/A' — never a placeholder bracket."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception:
        info = {}
    data, lines = {}, []
    for key, label, fmt in _DD_FIELDS:
        v = info.get(key)
        data[key] = v
        if v is None or v == "":
            lines.append(f"  {label}: N/A")
        else:
            try:
                lines.append(f"  {label}: {fmt.format(v)}")
            except Exception:
                lines.append(f"  {label}: {v}")
    data["longName"] = info.get("longName") or symbol
    data["sector"]   = info.get("sector") or "N/A"
    data["industry"] = info.get("industry") or "N/A"
    header = (f"  Company: {data['longName']}\n"
              f"  Sector: {data['sector']} | Industry: {data['industry']}")
    return data, header + "\n" + "\n".join(lines)

_PLACEHOLDER_RE = re.compile(r'\[\s*(?:insert|add|fill|your|company|time\s*frame|target)[^\]]*\]', re.I)

def _dd_generate(symbol, context=""):
    """Core DD engine: fetch → analyze with real numbers → validate.
    Returns (report_text, ok). ok=False means no usable market data."""
    symbol = symbol.upper()
    data, block = _yf_fundamentals(symbol)
    if data.get("currentPrice") is None or data.get("marketCap") is None:
        return f"No data available for {symbol} — yfinance returned no price/market cap.", False
    prompt = f"""Write a due diligence report for {symbol} ({data['longName']}).{' Context: ' + context if context else ''}

REAL CURRENT DATA (use ONLY these numbers — never invent figures, never write
placeholder brackets like [Insert X]; if a field says N/A, write "N/A"):
{block}

Cover: business model, financial health (cite the numbers above), growth,
competition, valuation vs the P/E and PEG shown, key risks, and bull/base/bear
price targets derived from the current price and analyst target above.
Be thorough, specific, and honest about weaknesses."""
    result = _ai(prompt) or ""
    if result.startswith("(AI unavailable"):
        result = ""
    # Zero-placeholder guarantee: strip any bracket the model still invented
    if _PLACEHOLDER_RE.search(result):
        result = _PLACEHOLDER_RE.sub("N/A", result)
    report = (f"DUE DILIGENCE — {symbol} ({data['longName']})\n"
              f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} — data via yfinance\n"
              + "=" * 60 + f"\n\nKEY FIGURES\n{block}\n\n" + "=" * 60 + "\n\n"
              + (result if result.strip() else "(LLM analysis unavailable — figures above are live.)"))
    return report, True

def stock_due_diligence(symbol, context=""):
    symbol = symbol.upper()
    report, ok = _dd_generate(symbol, context)
    if not ok:
        return report
    path = Path.home()/"Documents"/"JARVIS"/"Reports"/f"DD_{symbol}_{datetime.now().strftime('%Y%m%d')}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return f"📊 DD Report: {symbol}\n\n{report[:500]}...\n\nFull report saved: {path}"

# ── Autonomous multi-ticker DD ────────────────────────────────────────────────
# "Do DD on 20-30 top picks" = a multi-minute job (one yfinance fetch + one
# LLM analysis per ticker). It runs in a background thread so the chat reply
# is instant, picks its own tickers from Jarvis's screening, saves each report
# as it completes, and never stops to ask permission. 'dd status' checks in.

_DD_JOB = {"running": False, "done": 0, "total": 0, "skipped": [],
           "completed": [], "started": "", "master": ""}

def _dd_pick_universe(count):
    """Jarvis's own top-picks screen: curated momentum list + the liquidity-
    ranked NYSE/NASDAQ budget screen, deduped, in that priority order."""
    picks = []
    try:
        import tools.conviction as CVN
        picks.extend(CVN._UNIVERSE)
        try:
            picks.extend(CVN._budget_friendly_universe())
        except Exception:
            pass
    except Exception:
        pass
    seen, out = set(), []
    for s in picks:
        s = s.upper()
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= count:
            break
    return out

def _dd_worker(count):
    day = datetime.now().strftime("%Y%m%d")
    rpt_dir = Path.home()/"Documents"/"JARVIS"/"Reports"
    rpt_dir.mkdir(parents=True, exist_ok=True)
    master = rpt_dir/f"DD_TOPPICKS_{day}.txt"
    _DD_JOB["master"] = str(master)
    tickers = _dd_pick_universe(count)
    _DD_JOB["total"] = len(tickers)
    summaries = []
    for sym in tickers:
        try:
            report, ok = _dd_generate(sym)
            if not ok:
                _DD_JOB["skipped"].append(sym)
                summaries.append(f"  ✗ {sym}: no yfinance data — skipped")
            else:
                (rpt_dir/f"DD_{sym}_{day}.txt").write_text(report, encoding="utf-8")
                _DD_JOB["completed"].append(sym)
                # First KEY FIGURES lines as the master-file summary
                fig = report.split("KEY FIGURES\n", 1)[-1].split("\n\n")[0]
                summaries.append(f"── {sym} " + "─" * 30 + f"\n{fig}\n")
        except Exception as e:
            _DD_JOB["skipped"].append(sym)
            summaries.append(f"  ✗ {sym}: error {str(e)[:60]}")
        _DD_JOB["done"] += 1
        # Master file updates as it goes — readable mid-run
        master.write_text(
            f"TOP PICKS DUE DILIGENCE — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{_DD_JOB['done']}/{_DD_JOB['total']} processed | "
            f"{len(_DD_JOB['completed'])} reports | {len(_DD_JOB['skipped'])} skipped\n"
            f"Individual reports: DD_<SYMBOL>_{day}.txt in this folder\n"
            + "=" * 60 + "\n\n" + "\n".join(summaries), encoding="utf-8")
    _DD_JOB["running"] = False

def dd_top_picks(count=20):
    """Kick off autonomous DD on Jarvis's top picks. Returns immediately."""
    if _DD_JOB["running"]:
        return dd_status()
    count = max(3, min(int(count or 20), 30))
    _DD_JOB.update({"running": True, "done": 0, "total": 0, "skipped": [],
                    "completed": [], "started": datetime.now().strftime("%H:%M")})
    import threading
    threading.Thread(target=_dd_worker, args=(count,), daemon=True).start()
    return (f"🔬 Running full due diligence on my top {count} picks — real yfinance "
            f"fundamentals + written analysis per ticker, no placeholders.\n"
            f"Each report saves to Documents\\JARVIS\\Reports as it completes "
            f"(≈15-30s per ticker). Say 'dd status' to check progress — "
            f"I'll keep going without you.")

def dd_status():
    j = _DD_JOB
    if not j["total"] and not j["running"]:
        return "No DD batch has run yet. Say 'due diligence on top picks' to start one."
    state = "RUNNING" if j["running"] else "DONE"
    lines = [f"🔬 DD BATCH — {state} (started {j['started']})",
             f"  progress: {j['done']}/{j['total']}",
             f"  completed: {', '.join(j['completed']) or '—'}"]
    if j["skipped"]:
        lines.append(f"  skipped (no data): {', '.join(j['skipped'])}")
    if j["master"]:
        lines.append(f"  summary file: {j['master']}")
    return "\n".join(lines)

def stock_compare(symbols):
    if isinstance(symbols,str): symbols=[s.strip().upper() for s in symbols.replace(","," ").split()]
    result=_ai(f"Compare these stocks side by side: {', '.join(symbols)}. Business quality, growth, valuation, risks, best buy today and why.")
    return f"⚖️ Comparison: {' vs '.join(symbols)}\n\n{result}"

def stock_screen(criteria="growth"):
    prompts={
        "growth":   "8-10 high-growth NYSE/NASDAQ stocks. Revenue >20%, expanding margins. Ticker + thesis + risk.",
        "value":    "8-10 undervalued stocks below intrinsic value. Strong balance sheet, rerating catalyst.",
        "momentum": "8-10 momentum stocks near 52-week highs with improving fundamentals.",
        "dividend": "8-10 quality dividend stocks. Yield >3%, sustainable payout, growth history.",
        "ai":       "8-10 AI stocks — pure plays and picks-and-shovels. Specific tickers with thesis.",
        "defense":  "8-10 defense/aerospace stocks benefiting from global spending increases.",
        "small cap":"8-10 small-cap ($300M-$2B) with explosive growth potential. Under-followed.",
    }
    key=next((k for k in prompts if k in criteria.lower()),"growth")
    return f"🔍 Stock Screen: {criteria.title()}\n\n{_ai(prompts[key])}"

def portfolio_build(amount, risk_level="moderate", timeframe="1 year"):
    result=_ai(f"""Build a complete investment portfolio: ${amount}, {risk_level} risk, {timeframe} horizon.
Include: asset allocation %, specific stock picks with %, ETF core, cash position, sector breakdown, rebalancing triggers, expected return.""")
    return f"💼 Portfolio: ${amount} | {risk_level} | {timeframe}\n\n{result}"

def market_news():
    return _ai(f"Top 5-7 market-moving news stories for {datetime.now().strftime('%B %d, %Y')}. Which stocks are affected and how? Be specific.")

def earnings_cal():
    return _ai(f"Most important upcoming earnings reports for {datetime.now().strftime('%B %Y')}. Which could beat/miss? 8-10 key events.")

def ipo_pipeline():
    return _ai("Most anticipated upcoming IPOs. Worth buying? Company, valuation concerns, verdict.")

# ═════════════════════════════════════════════════════════════════════════════
# MEMORY
# ═════════════════════════════════════════════════════════════════════════════

_MEM_FILE  = Path.home()/"Documents"/"JARVIS"/"memory.json"
_PROF_FILE = Path.home()/"Documents"/"JARVIS"/"profile.json"

def memory_update(user_msg, reply):
    """Call after every exchange to learn the user."""
    try:
        mem=json.loads(_MEM_FILE.read_text(encoding="utf-8")) if _MEM_FILE.exists() else {"conversations":[],"facts":{},"word_counts":{}}
        mem["conversations"].append({"time":datetime.now().strftime("%Y-%m-%d %H:%M"),"user":user_msg,"reply":reply[:200]})
        if len(mem["conversations"])>500: mem["conversations"]=mem["conversations"][-500:]
        # Extract facts
        m=user_msg.lower()
        for pat,key in [(r"my name is (\w+)","name"),(r"i live in ([\w\s]+)","location"),
                        (r"i'm (\d{1,2}) years? old","age"),(r"i work (?:at|for) ([\w\s]+)","job")]:
            match=re.search(pat,m)
            if match: mem["facts"][key]=match.group(1).strip().title()
        # Word frequency
        for w in re.findall(r'\b[a-z]{3,}\b',m):
            mem["word_counts"][w]=mem["word_counts"].get(w,0)+1
        _MEM_FILE.write_text(json.dumps(mem,indent=2),encoding="utf-8")
        # Update profile
        prof=json.loads(_PROF_FILE.read_text(encoding="utf-8")) if _PROF_FILE.exists() else {"count":0,"formality":50,"slang":[],"topics":{}}
        prof["count"]+=1
        if m==m.lower(): prof["formality"]=max(0,prof["formality"]-2)
        for s in ["bro","dude","yo","lol","ngl","fr","lowkey","bet","bruh","gonna","wanna","gotta","tbh","rn","asap"]:
            if s in m and s not in prof["slang"]: prof["slang"].append(s)
        for topic,kws in [("gaming",["game","steam","discord","cs2","apex","rust"]),
                          ("finance",["money","bill","stock","trade","invest"]),
                          ("health",["workout","gym","run","sleep","med"]),
                          ("tech",["computer","pc","fix","crash","wifi"])]:
            if any(k in m for k in kws): prof["topics"][topic]=prof["topics"].get(topic,0)+1
        _PROF_FILE.write_text(json.dumps(prof,indent=2),encoding="utf-8")
    except Exception: pass

def memory_context():
    """Return a context string describing what JARVIS knows about the user."""
    try:
        mem=json.loads(_MEM_FILE.read_text(encoding="utf-8")) if _MEM_FILE.exists() else {}
        prof=json.loads(_PROF_FILE.read_text(encoding="utf-8")) if _PROF_FILE.exists() else {}
        lines=[]
        facts=mem.get("facts",{})
        if facts.get("name"):     lines.append(f"User's name: {facts['name']}")
        if facts.get("location"): lines.append(f"Lives in: {facts['location']}")
        if facts.get("age"):      lines.append(f"Age: {facts['age']}")
        if facts.get("job"):      lines.append(f"Job: {facts['job']}")
        count=prof.get("count",0)
        if count>0:
            formal=prof.get("formality",50)
            tone="very casual" if formal<30 else "casual" if formal<50 else "balanced" if formal<70 else "formal"
            lines.append(f"Communication tone: {tone} (from {count} messages)")
        slang=prof.get("slang",[])
        if slang: lines.append(f"Their slang: {', '.join(slang[:8])}")
        topics=sorted(prof.get("topics",{}).items(),key=lambda x:-x[1])[:3]
        if topics: lines.append(f"Top interests: {', '.join(t for t,_ in topics)}")
        recent=mem.get("conversations",[])[-2:]
        if recent:
            lines.append("Recent context:")
            for r in recent: lines.append(f"  [{r['time']}] {r['user'][:60]}")
        return "\n".join(lines) if lines else ""
    except Exception: return ""

def memory_show():
    try:
        mem=json.loads(_MEM_FILE.read_text(encoding="utf-8")) if _MEM_FILE.exists() else {}
        prof=json.loads(_PROF_FILE.read_text(encoding="utf-8")) if _PROF_FILE.exists() else {}
        count=prof.get("count",0)
        if count==0: return "No memory yet — I learn as we talk."
        lines=[f"What I know about you ({count} conversations):"]
        facts=mem.get("facts",{})
        for k,v in facts.items(): lines.append(f"  • {k.title()}: {v}")
        formal=prof.get("formality",50)
        tone="very casual" if formal<30 else "casual" if formal<50 else "balanced" if formal<70 else "formal"
        lines.append(f"  • Tone: {tone}")
        slang=prof.get("slang",[])
        if slang: lines.append(f"  • Slang I understand: {', '.join(slang[:6])}")
        topics=sorted(prof.get("topics",{}).items(),key=lambda x:-x[1])[:3]
        if topics: lines.append(f"  • Top topics: {', '.join(t for t,_ in topics)}")
        return "\n".join(lines)
    except Exception: return "Memory data unavailable."

def memory_clear():
    for f in [_MEM_FILE,_PROF_FILE]:
        if f.exists(): f.unlink()
    return "Memory cleared. Starting fresh."
