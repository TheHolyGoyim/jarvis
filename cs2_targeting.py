"""
cs2_targeting.py — CS2 Perfect Aim Engine
2560x1440, FOV 106° horizontal, sens 0.52, 1600 DPI

Rules:
- NEVER fire unless crosshair is confirmed on head
- NEVER look above 20° or below 20° from horizon
- After kill: strafe to find next target, then engage
- Smooth aim within 15°, instant flick beyond
- CrosshairTracker maintains exact aim position
"""
import ctypes, time, math, threading, random, tempfile, os, subprocess
import numpy as np
from collections import deque

# ── Constants ─────────────────────────────────────────────────
SENS       = 0.52
DPI        = 1600
FOV_H      = 106.0
SW, SH     = 2560, 1440
FOCAL      = (SW/2.0)/math.tan(math.radians(FOV_H/2.0))
DEG_PER_C  = SENS * 0.022
SMOOTH_DEG = 15.0
SMOOTH_PX  = FOCAL * math.tan(math.radians(SMOOTH_DEG))  # 258px
ON_HEAD_PX = 5       # Fire only when within 5px of head
MAX_AIM_MS = 250     # Max time to spend centering before giving up
# Vertical constraints — never look to sky or floor
MAX_UP_PX  = FOCAL * math.tan(math.radians(20.0))   # 351px above center
MAX_DN_PX  = FOCAL * math.tan(math.radians(20.0))   # 351px below center
# Valid enemy zone
VALID_Y1   = int(SH * 0.10)   # 144px — min enemy head Y
VALID_Y2   = int(SH * 0.82)   # 1180px — max enemy head Y

def _to_mouse(dx, dy, focal=FOCAL):
    d = DEG_PER_C
    return (int(round(math.degrees(math.atan2(dx, focal))/d)),
            int(round(math.degrees(math.atan2(dy, focal))/d)))

def _from_mouse(mx, my, focal=FOCAL):
    d = DEG_PER_C
    return (focal * math.tan(math.radians(mx * d)),
            focal * math.tan(math.radians(my * d)))

# ── Input (all ctypes at module level) ───────────────────────
class _MI(ctypes.Structure):
    _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),
                ("mouseData",ctypes.c_ulong),("dwFlags",ctypes.c_ulong),
                ("time",ctypes.c_ulong),
                ("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
class _MU(ctypes.Union):
    _fields_ = [("mi",_MI)]
class _MINPUT(ctypes.Structure):
    _fields_ = [("type",ctypes.c_ulong),("_input",_MU)]
class _KI(ctypes.Structure):
    _fields_ = [("wVk",ctypes.c_ushort),("wScan",ctypes.c_ushort),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),
                ("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
class _KU(ctypes.Union):
    _fields_ = [("ki",_KI)]
class _KINPUT(ctypes.Structure):
    _fields_ = [("type",ctypes.c_ulong),("_input",_KU)]

def _mov(dx, dy):
    if dx == 0 and dy == 0: return
    try:
        i = _MINPUT(); i.type = 0
        i._input.mi.dx = int(dx); i._input.mi.dy = int(dy)
        i._input.mi.dwFlags = 0x0001
        ctypes.windll.user32.SendInput(
            1, ctypes.byref(i), ctypes.sizeof(_MINPUT))
    except Exception:
        try: ctypes.windll.user32.mouse_event(0x0001,int(dx),int(dy),0,0)
        except: pass

def _clk(down=True):
    try: ctypes.windll.user32.mouse_event(
            0x0002 if down else 0x0004, 0,0,0,0)
    except: pass

def _key(sc, up=False):
    try:
        i = _KINPUT(); i.type = 1
        i._input.ki.wScan = sc
        i._input.ki.dwFlags = 0x0008|(0x0002 if up else 0)
        ctypes.windll.user32.SendInput(
            1, ctypes.byref(i), ctypes.sizeof(_KINPUT))
    except: pass

SC_D=0x20; SC_A=0x1E; SC_W=0x11; SC_S=0x1F

# ── Capture / focus ───────────────────────────────────────────
def _cap():
    try:
        import mss
        with mss.mss() as s:
            m = s.monitors[1]
            return np.array(s.grab(m))[:,:,:3]
    except:
        try:
            import pyautogui
            return np.array(pyautogui.screenshot())
        except: return None

def _res():
    try:
        import mss
        with mss.mss() as s:
            m=s.monitors[1]; return m["width"],m["height"]
    except:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            u=ctypes.windll.user32
            return u.GetSystemMetrics(0),u.GetSystemMetrics(1)
        except: return SW,SH

def _focus():
    ps=('$p=Get-Process|Where-Object{$_.MainWindowTitle -match '
        '"Counter|cs2"}|Select-Object -First 1\n'
        'if($p){\n'
        '$c=\'using System;using System.Runtime.InteropServices;\n'
        'public class WF{\n'
        '[DllImport("user32.dll")]'
        'public static extern bool ShowWindow(IntPtr h,int n);\n'
        '[DllImport("user32.dll")]'
        'public static extern bool SetForegroundWindow(IntPtr h);\n'
        '}\'\n'
        'Add-Type -TypeDefinition $c -ErrorAction SilentlyContinue\n'
        '[WF]::ShowWindow($p.MainWindowHandle,9)\n'
        '[WF]::SetForegroundWindow($p.MainWindowHandle)\n'
        'Write-Output "focused"\n}')
    try:
        tf=tempfile.NamedTemporaryFile(
            mode='w',suffix='.ps1',delete=False,encoding='utf-8')
        tf.write(ps); tf.close()
        r=subprocess.run(
            ["powershell","-NonInteractive","-ExecutionPolicy",
             "Bypass","-File",tf.name],
            capture_output=True,text=True,timeout=5)
        os.unlink(tf.name)
        ok="focused" in r.stdout.lower()
        print(f"[TGT] Focus: {'OK' if ok else 'FAILED'}")
        return ok
    except Exception as e:
        print(f"[TGT] Focus error: {e}"); return False

# ── CrosshairTracker ──────────────────────────────────────────
class CrosshairTracker:
    """
    Tracks exact crosshair screen position.
    Critical: CS2 raw input can't be read back.
    Every _mov call must go through here.
    Clamps vertical movement to prevent looking at sky/floor.
    """
    def __init__(self, sw=SW, sh=SH, focal=FOCAL):
        self.sw=sw; self.sh=sh; self.focal=focal
        self.ox=0.0; self.oy=0.0  # offset from screen center

    def reset(self):
        self.ox=0.0; self.oy=0.0

    def apply_move(self, mx, my):
        px,py = _from_mouse(mx,my,self.focal)
        self.ox += px; self.oy += py

    def _clamp_y(self, dy):
        """Clamp vertical movement to ±20° from horizon."""
        new_oy = self.oy + dy
        if new_oy < -MAX_UP_PX: dy = -MAX_UP_PX - self.oy
        if new_oy >  MAX_DN_PX: dy =  MAX_DN_PX - self.oy
        return dy

    def delta_to(self, sx, sy):
        """Delta from current crosshair position to screen (sx,sy)."""
        cx = self.sw//2 + self.ox
        cy = self.sh//2 + self.oy
        dx = sx - cx; dy = sy - cy
        # Clamp vertical
        dy = self._clamp_y(dy)
        mx,my = _to_mouse(dx,dy,self.focal)
        return dx,dy,mx,my

    def dist_to(self, sx, sy):
        cx=self.sw//2+self.ox; cy=self.sh//2+self.oy
        return math.sqrt((sx-cx)**2+(sy-cy)**2)

    def send_move(self, mx, my):
        """Send mouse move and update tracker."""
        _mov(mx, my)
        self.apply_move(mx, my)

    def move_to(self, sx, sy):
        """
        Move crosshair to screen position (sx,sy).
        Smooth if within 15°, instant flick if beyond.
        Always clamps vertical to prevent sky/floor.
        """
        # Validate target is in valid enemy zone
        sy = max(VALID_Y1, min(VALID_Y2, sy))
        dx,dy,mx,my = self.delta_to(sx, sy)
        dist = math.sqrt(dx*dx+dy*dy)

        if dist <= SMOOTH_PX:
            # Smooth ease-out over several steps
            steps = max(3, min(8, int(dist/25)))
            sx_sent=0; sy_sent=0
            for i in range(steps):
                t = (i+1)/steps
                ease = t*(2-t)          # ease-out
                tx=int(mx*ease)-sx_sent
                ty=int(my*ease)-sy_sent
                if tx!=0 or ty!=0:
                    self.send_move(tx,ty)
                    sx_sent+=tx; sy_sent+=ty
                time.sleep(0.0015)
        else:
            # Instant flick
            self.send_move(mx, my)

        return mx, my

    @property
    def pos(self):
        return (self.sw//2+self.ox, self.sh//2+self.oy)


# ── Target ────────────────────────────────────────────────────
class Tgt:
    _id=0
    def __init__(self,d,fid):
        Tgt._id+=1; self.id=Tgt._id
        self.x=float(d["x"]); self.y=float(d["y"])
        self.hx=float(d.get("head_x",d["x"]))
        self.hy=float(d["head_y"])
        self.team=d.get("team","?"); self.conf=d["conf"]
        self.lost=0; self.hp=100; self.shots=0; self.hits=0
        self._h=deque(maxlen=8)
        self._h.append((self.x,self.y,time.time()))
        self.vx=0.0; self.vy=0.0; self._lf=0.0

    def upd(self,d,fid):
        now=time.time()
        if self._h:
            px,py,pt=self._h[-1]; dt=max(now-pt,0.001)
            self.vx=(d["x"]-px)/dt*0.25+self.vx*0.75
            self.vy=(d["y"]-py)/dt*0.25+self.vy*0.75
        self.x=float(d["x"]); self.y=float(d["y"])
        self.hx=float(d.get("head_x",d["x"])); self.hy=float(d["head_y"])
        self.conf=d["conf"]; self.lost=0
        self._h.append((self.x,self.y,now))

    def pred(self,ms=8):
        dt=ms/1000.0
        return self.hx+self.vx*dt, self.hy+self.vy*dt

    @property
    def dead(self): return self.hp<=0


class Tracker:
    def __init__(self): self.ts=[]; self.f=0
    def upd(self,ds):
        self.f+=1; um=list(ds)
        for t in self.ts:
            b,bd=None,120
            for d in um:
                v=math.sqrt((t.x-d["x"])**2+(t.y-d["y"])**2)
                if v<bd: bd,b=v,d
            if b: t.upd(b,self.f); um.remove(b)
            else: t.lost+=1
        for d in um: self.ts.append(Tgt(d,self.f))
        self.ts=[t for t in self.ts if t.lost<8]
    def live(self):
        return [t for t in self.ts if t.lost==0 and not t.dead]
    def pri(self,xhair):
        lv=self.live()
        if not lv: return []
        fu=[t for t in lv if t.hits>0]
        fr=[t for t in lv if not t.hits>0]
        k=lambda t: xhair.dist_to(t.hx,t.hy)
        return sorted(fu,key=k)+sorted(fr,key=k)


# ── Combat Engine ─────────────────────────────────────────────
class CE:
    def __init__(self):
        self.sw,self.sh=_res()
        self.focal=(self.sw/2)/math.tan(math.radians(FOV_H/2))
        self.sens=SENS
        self.xhair=CrosshairTracker(self.sw,self.sh,self.focal)
        self.trk=Tracker()
        self.active=False; self.paused=False
        self._t=None; self._log=[]
        self.stats=dict(frames=0,det=0,shots=0,hits=0,misses=0,kills=0)
        self.react=15
        self.weapon="ak47"
        self.spray=None   # wired to SprayController after init
        print(f"[TGT] Init: FOV={FOV_H} focal={self.focal:.0f} "
              f"res={self.sw}x{self.sh}")

    def _L(self,m):
        e=f"[{time.strftime('%H:%M:%S')}] {m}"
        self._log.append(e); print(f"[CS2] {m}")
        if len(self._log)>300: self._log=self._log[-300:]

    def recal(self):
        self.sw,self.sh=_res()
        self.focal=(self.sw/2)/math.tan(math.radians(FOV_H/2))
        self.xhair=CrosshairTracker(self.sw,self.sh,self.focal)
        self._L(f"Calibrated: FOV={FOV_H} focal={self.focal:.0f} "
               f"res={self.sw}x{self.sh}")

    def _stop_movement(self, last_key=None):
        """
        Counter-strafe to full stop.
        Taps the opposite of last movement key.
        Waits for physics to settle (3 frames at 64hz = 47ms).
        """
        opp = {SC_D: SC_A, SC_A: SC_D, SC_W: SC_S, SC_S: SC_W}
        stop_key = opp.get(last_key, SC_D)  # default counter is D
        _key(stop_key)
        time.sleep(0.050)       # 3.2 frames at 64hz — full stop
        _key(stop_key, up=True)
        time.sleep(0.031)       # 2 more frames to let physics settle

    def _strafe_peek(self, target_screen_x):
        """
        Short strafe toward target to create peek angle.
        Returns the strafe key used (for counter-strafe).
        Crosshair tracks target head during strafe.
        """
        cx = self.sw // 2
        # Strafe toward target
        if target_screen_x > cx:
            strafe_key = SC_D   # target right → strafe right
        else:
            strafe_key = SC_A   # target left → strafe left

        _key(strafe_key)
        return strafe_key

    def _aim_and_confirm(self, t, det_engine):
        """
        Aim at target head and CONFIRM crosshair is on head.
        Will keep adjusting until on-head or MAX_AIM_MS exceeded.
        Returns (confirmed: bool, hx: float, hy: float)
        """
        deadline = time.time() + MAX_AIM_MS/1000.0
        attempt  = 0

        while time.time() < deadline:
            attempt += 1

            # Always get fresh YOLO position
            if det_engine and det_engine.is_ready:
                fresh = _cap()
                if fresh is not None:
                    dets = det_engine.detect(fresh)
                    if dets:
                        # Find detection matching our target
                        best = min(dets, key=lambda d:
                            math.sqrt((d["x"]-t.x)**2+(d["y"]-t.y)**2))
                        if math.sqrt((best["x"]-t.x)**2+
                                     (best["y"]-t.y)**2) < 150:
                            t.upd(best, 0)

            # Predict head
            hx,hy = t.pred(self.react+3)

            # Clamp head Y to valid zone
            hy = max(VALID_Y1, min(VALID_Y2, hy))

            # Check current distance
            dist = self.xhair.dist_to(hx, hy)

            if dist <= ON_HEAD_PX:
                return True, hx, hy  # Confirmed on head

            # Aim toward head
            self.xhair.move_to(hx, hy)
            time.sleep(0.005)

        # Timed out — check one more time
        hx,hy = t.pred(2)
        hy = max(VALID_Y1, min(VALID_Y2, hy))
        final_dist = self.xhair.dist_to(hx,hy)
        confirmed  = final_dist <= ON_HEAD_PX * 2  # slightly relaxed
        self._L(f"Aim {'confirmed' if confirmed else 'FAILED'} "
               f"dist={final_dist:.1f}px after {attempt} attempts")
        return confirmed, hx, hy

    def _fire_one(self, t, det_engine):
        """
        Full pro shot sequence:
        1. Short strafe toward target (creates peek angle)
        2. Aim tracks head during strafe
        3. Counter-strafe (full stop)
        4. Physics settle
        5. Final aim confirmation on head
        6. Fire ONLY when confirmed on head
        """
        # Get current head position
        hx, hy = t.pred(self.react + 5)
        hy = max(VALID_Y1, min(VALID_Y2, hy))

        # Step 1: Strafe toward target
        strafe_key = self._strafe_peek(t.x)
        strafe_start = time.time()

        # Step 2: Track head while strafing (80-120ms strafe)
        STRAFE_MS = random.randint(80, 120)
        while (time.time() - strafe_start) * 1000 < STRAFE_MS:
            # Refresh target position and track head
            if det_engine and det_engine.is_ready:
                f = _cap()
                if f is not None:
                    dets = det_engine.detect(f)
                    if dets:
                        best = min(dets, key=lambda d:
                            math.sqrt((d["x"]-t.x)**2+(d["y"]-t.y)**2))
                        if math.sqrt((best["x"]-t.x)**2+
                                     (best["y"]-t.y)**2) < 150:
                            t.upd(best, 0)

            # Keep crosshair on head during strafe
            hx, hy = t.pred(self.react + 3)
            hy = max(VALID_Y1, min(VALID_Y2, hy))
            self.xhair.move_to(hx, hy)
            time.sleep(0.008)   # ~64hz tick

        # Step 3: Counter-strafe — full stop
        _key(strafe_key, up=True)  # release strafe key
        self._stop_movement(strafe_key)

        # Step 4: Final aim — re-center on head after stop
        # Get fresh head position now we're stationary
        hx, hy = t.pred(self.react + 2)
        hy = max(VALID_Y1, min(VALID_Y2, hy))
        self.xhair.move_to(hx, hy)
        time.sleep(0.005)

        # Step 5: Confirm crosshair is ON head before firing
        confirmed, hx, hy = self._aim_and_confirm(t, det_engine)

        if not confirmed:
            self._L("NOT FIRING — crosshair not confirmed on head")
            return False, False, hx, hy

        # Step 6: Reaction delay then fire
        time.sleep(self.react / 1000.0)

        pre = _cap()
        if self.spray is not None:
            self.spray.burst(self.weapon, shots=1)
        else:
            _clk(True); time.sleep(0.013); _clk(False)
        t.shots += 1; self.stats["shots"] += 1
        t._lf = time.time()

        time.sleep(0.045)
        post = _cap()
        hit = self._hit_check(t, pre, post)
        return True, hit, hx, hy

    def _hit_check(self,t,pre,post):
        if pre is None or post is None: return False
        try:
            x,y=int(t.x),int(t.y)
            r=max(25,int(math.sqrt(t.conf*2000)))
            x1=max(0,x-r); x2=min(pre.shape[1],x+r)
            y1=max(0,y-r*2); y2=min(pre.shape[0],y+r)
            if x2<=x1 or y2<=y1: return False
            diff=np.abs(pre[y1:y2,x1:x2].astype(float)-
                       post[y1:y2,x1:x2].astype(float))
            return float(np.mean(diff))>10.0
        except: return False

    def _search_for_target(self, det_engine, timeout=3.0):
        """
        Strafe and look around to find next target.
        Stays within ±20° vertical.
        Returns list of detections or [] if none found.
        """
        self._L("Searching for next target...")
        t0 = time.time()

        # Search pattern: strafe + horizontal sweeps
        # Never look up or down more than 20 degrees
        pattern = [
            # (action, value_px, duration_s)
            ("strafe_right", 0,   0.30),
            ("look_right",   200, 0),
            ("strafe_right", 0,   0.20),
            ("look_right",   200, 0),
            ("look_left",    500, 0),
            ("strafe_left",  0,   0.30),
            ("look_left",    200, 0),
            ("move_fwd",     0,   0.35),
            ("look_right",   400, 0),
        ]

        for action, px, dur in pattern:
            if not self.active: break
            if time.time()-t0 > timeout: break

            # Check for enemies after each move
            f = _cap()
            if f is not None and det_engine and det_engine.is_ready:
                dets = det_engine.detect(f)
                if dets:
                    self._L(f"Found {len(dets)} target(s) during search")
                    return dets

            if action == "look_right":
                # Horizontal sweep right — clamped
                steps = 8
                per_step = px // steps
                for _ in range(steps):
                    if not self.active: break
                    self.xhair.move_to(
                        self.xhair.pos[0] + per_step,
                        self.xhair.pos[1])  # keep Y same
                    time.sleep(0.025)

            elif action == "look_left":
                steps = 10
                per_step = px // steps
                for _ in range(steps):
                    if not self.active: break
                    self.xhair.move_to(
                        self.xhair.pos[0] - per_step,
                        self.xhair.pos[1])
                    time.sleep(0.025)

            elif action == "strafe_right":
                _key(SC_D); time.sleep(dur); _key(SC_D,up=True)

            elif action == "strafe_left":
                _key(SC_A); time.sleep(dur); _key(SC_A,up=True)

            elif action == "move_fwd":
                _key(SC_W); time.sleep(dur); _key(SC_W,up=True)

            time.sleep(0.05)

        return []

    def engage(self, t, frame=None):
        """
        Engage one target: confirm aim → fire → check hit.
        Repeat up to 7 shots. Never fires unless confirmed on head.
        """
        if time.time()-t._lf < 0.08: return "cd"

        det_engine = None
        try:
            import cs2_yolo as YM
            det_engine = YM.get_detector()
        except: pass

        # Reset crosshair tracking for fresh engagement
        self.xhair.reset()

        for shot_num in range(7):
            if not self.active or t.dead: break

            fired, hit, hx, hy = self._fire_one(t, det_engine)

            if not fired:
                # Could not get on head — skip this target
                break

            if hit:
                t.hits+=1
                dmg = 105 if shot_num==0 else 35
                t.hp = max(0, t.hp-dmg)
                self.stats["hits"]+=1

                if t.dead:
                    self.stats["kills"]+=1
                    self._L(f"KILL [{t.team}] "
                           f"shot={shot_num+1} "
                           f"head=({hx:.0f},{hy:.0f})")
                    # Reset xhair — next target starts clean
                    self.xhair.reset()
                    return "kill"

                self._L(f"HIT [{t.team}] shot={shot_num+1} hp≈{t.hp}")
                time.sleep(0.10)  # AK fire rate gap
            else:
                self.stats["misses"]+=1
                self._L(f"MISS [{t.team}] shot={shot_num+1}")
                time.sleep(0.06)

        self.xhair.reset()
        return "engaged"

    def run_frame(self, ds, frame=None):
        if not self.active or self.paused: return
        self.stats["frames"]+=1
        self.trk.upd(ds)
        tgts = self.trk.pri(self.xhair)
        if not tgts: return
        self.stats["det"]+=len(tgts)

        for t in tgts:
            if not self.active: break
            result = self.engage(t, frame)
            if result == "kill":
                # After kill: search for next target
                if self.active:
                    import cs2_yolo as YM
                    det = YM.get_detector()
                    new_dets = self._search_for_target(det)
                    if new_dets:
                        self.trk.upd(new_dets)

    def start(self, secs=60):
        self.active=True; self.paused=False
        def _lp():
            try:
                _focus(); time.sleep(0.5); self.recal()
                import cs2_yolo as YM
                det=YM.get_detector(); t0=time.time()
                while self.active and time.time()-t0<secs:
                    if self.paused: time.sleep(0.05); continue
                    f=_cap()
                    if f is None: time.sleep(0.01); continue
                    h,w=f.shape[:2]
                    if w!=self.sw:
                        self.sw=w; self.sh=h
                        self.focal=(w/2)/math.tan(math.radians(FOV_H/2))
                        self.xhair=CrosshairTracker(w,h,self.focal)
                    ds=det.detect(f) if det and det.is_ready else []
                    self.run_frame(ds,f)
                    time.sleep(0.001)
            except Exception as e:
                self._L(f"Error: {e}")
                import traceback; traceback.print_exc()
            finally:
                self.active=False; _clk(False)
        self._t=threading.Thread(target=_lp,daemon=True)
        self._t.start()

    def stop(self):
        self.active=False; _clk(False)
        a=self.stats; acc=a["hits"]/max(a["shots"],1)*100
        return (f"Stopped\n"
                f"shots={a['shots']} hits={a['hits']} "
                f"kills={a['kills']} acc={acc:.0f}%")

    def pause(self):
        self.paused=not self.paused
        if self.paused: _clk(False)
        return "Paused" if self.paused else "Resumed"

    def status(self):
        a=self.stats; acc=a["hits"]/max(a["shots"],1)*100
        cx,cy=self.xhair.pos
        return (f"Active:{self.active} targets:{len(self.trk.live())}\n"
                f"FOV:{FOV_H} focal:{self.focal:.0f} "
                f"res:{self.sw}x{self.sh}\n"
                f"xhair:({cx:.0f},{cy:.0f})\n"
                f"shots:{a['shots']} kills:{a['kills']} acc:{acc:.0f}%\n"
                +"\n".join(self._log[-5:]))

    def test_shot(self):
        try:
            import cs2_yolo as YM
            det=YM.get_detector()
            if not det or not det.is_ready:
                return "YOLO not ready"
            self.recal()
            f=_cap()
            if f is None: return "Capture failed"
            h,w=f.shape[:2]
            if w!=self.sw:
                self.sw=w; self.sh=h
                self.focal=(w/2)/math.tan(math.radians(FOV_H/2))
                self.xhair=CrosshairTracker(w,h,self.focal)
            es=det.detect(f)
            if not es:
                return (f"No enemies\nscreen={w}x{h} "
                        f"model={det.model_name}")
            self.xhair.reset()
            es.sort(key=lambda e:
                self.xhair.dist_to(e.get("head_x",e["x"]),e["head_y"]))
            e=es[0]; t=Tgt(e,1)
            hx,hy=t.pred(self.react+5)
            dx,dy,mx,my=self.xhair.delta_to(hx,hy)
            self._L(f"TEST [{t.team}] h=({hx:.0f},{hy:.0f}) "
                   f"d=({dx:.0f},{dy:.0f}) m=({mx},{my})")
            self.active=True
            result=self.engage(t,f)
            self.active=False
            return (f"Result: {result.upper()}\n"
                    f"screen={w}x{h} focal={self.focal:.0f}\n"
                    f"head=({hx:.0f},{hy:.0f})\n"
                    f"delta=({dx:.0f},{dy:.0f}) mouse=({mx},{my})\n"
                    f"enemies={len(es)}")
        except Exception as e:
            import traceback
            return f"Error: {e}\n{traceback.format_exc()[-400:]}"


# ── Public API ────────────────────────────────────────────────
_ce=CE()
try:
    import cs2_pro as _cs2p
    _ce.spray = _cs2p._donk.spray
except Exception:
    pass

def combat_configure(sens=SENS,dpi=DPI,fov=FOV_H,weapon="ak47"):
    _ce.sens=float(sens); _ce.weapon=weapon; _ce.recal()
    return (f"Configured: sens={sens} fov={fov} weapon={weapon} "
            f"focal={_ce.focal:.0f}")

def combat_start(duration_seconds=60):
    _ce.start(int(duration_seconds))
    return (f"Combat started ({duration_seconds}s)\n"
            f"FOV={FOV_H} focal={_ce.focal:.0f} "
            f"res={_ce.sw}x{_ce.sh}\n"
            f"Rule: NEVER fires unless crosshair confirmed on head\n"
            f"Say 'stop combat' to stop")

def combat_stop():              return _ce.stop()
def combat_pause():             return _ce.pause()
def combat_status():            return _ce.status()
def combat_set_reaction(ms=15): _ce.react=float(ms); return f"React={ms}ms"
def combat_set_weapon(w="ak47"):
    _ce.weapon=w
    return f"Weapon={w}"
def get_combat_engine():        return _ce

def combat_test_shot():
    _focus(); time.sleep(0.6)
    return _ce.test_shot()
