# -*- coding: utf-8 -*-
"""
PS5 LED — v2 (DualSense SVG Edition)
=======================================
- رسم DualSense دقيق من أصل SVG مرخّص، بشريطي إضاءة يحضنان التاتشباد كما في اليد الحقيقية
- تتزامن إضاءة اليد المعروضة مع اللون الحقيقي على اليد الفعلية بنسبة 100%
- كشف تلقائي لنوع اليد (PS5/PS4) وعرض النموذج الصحيح
- كل المزايا السابقة محفوظة: ملفات تعريف، خمول تلقائي، تأثيرات، إلخ
التشغيل (ويندوز):
    pip install -U pydualsense hidapi
    python "V9 - Copy.py"
"""

import os, re, sys, atexit, platform, math, random, json, time, threading, colorsys, argparse, traceback, datetime, hashlib, queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# --------------------------- Paths / Config ---------------------------
APP_NAME = "DualLED_Pro"
def app_config_dir() -> Path:
    sysname = platform.system()
    if sysname == "Windows":
        return Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
    elif sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        return Path.home() / ".config" / APP_NAME

CONFIG_DIR = app_config_dir(); CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE   = CONFIG_DIR / "config.json"
LOG_FILE   = CONFIG_DIR / "app.log"

def log(*a):
    s = " ".join(str(x) for x in a)
    try:
        # Rotate at ~1 MB so a stuck backend can't grow the log unbounded and fill the disk.
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_048_576:
                bak = LOG_FILE.with_suffix(".log.1")
                try: bak.unlink(missing_ok=True)
                except Exception: pass
                LOG_FILE.replace(bak)
        except Exception:
            pass
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {s}\n")
    except Exception:
        pass

DEFAULT_CFG = {
    "language": "ar",
    "fullscreen_on_start": True,
    "last_mode": "Manual",
    "speed": 1.0,                        # 0.1 .. 5.0
    "rainbow_brightness": 0.9,           # 0.2 .. 1.0
    "flash_duty": 0.5,                   # 0.1 .. 0.9
    "color": "#00aaff",
    "alerts": { "low": True, "plug": True, "full": True, "threshold": 15, "rate": 0.6 },
    "backend": "auto",
    "pds_batt_field": None,
    "pds_charge_field": None,
    "bgr_swap": False,
    "max_instances": 1,                  # السماح بـ 5 نسخ كحد أقصى
    "minimize_to_tray": True,            # تصغير للشريط السفلي بدلاً من الإغلاق
    "shell_color": "white",              # طقم ألوان اليد المعروضة
    "profiles": {
        "Default":  {"mode":"Manual","speed":1.0,"rainbow_brightness":0.9,"flash_duty":0.5,"color":"#00aaff"},
        "Fortnite": {"mode":"Manual","speed":1.0,"rainbow_brightness":0.9,"flash_duty":0.5,"color":"#3b82f6"},
        "COD":      {"mode":"Manual","speed":1.0,"rainbow_brightness":0.9,"flash_duty":0.5,"color":"#ff3434"},
        "FIFA":     {"mode":"Manual","speed":1.0,"rainbow_brightness":0.9,"flash_duty":0.5,"color":"#22c55e"}
    },
    "auto_sleep": {"enabled": False, "minutes": 30, "action": "off"},  # off / solid
    "bg_starfield": True
}

def load_cfg():
    d = json.loads(json.dumps(DEFAULT_CFG))
    try:
        if CFG_FILE.exists():
            on_disk = json.loads(CFG_FILE.read_text(encoding="utf-8"))
            def merge(dst, src):
                for k, v in src.items():
                    if isinstance(v, dict) and isinstance(dst.get(k), dict):
                        merge(dst[k], v)
                    else:
                        dst[k] = v
            merge(d, on_disk)
    except Exception as e:
        log("cfg read err:", e)
    return d

def save_cfg(cfg):
    try:
        CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log("cfg save err:", e)

# خنق الحفظ للمسارات الساخنة (سحب المنتقي/المنزلقات): كتابة واحدة كحد أقصى بالثانية،
# مع flush لاحق يضمن عدم ضياع آخر قيمة.
_CFG_SAVE = {"last": 0.0, "dirty": False}

def save_cfg_throttled(cfg):
    now = time.time()
    if now - _CFG_SAVE["last"] >= 1.0:
        _CFG_SAVE["last"] = now; _CFG_SAVE["dirty"] = False
        save_cfg(cfg)
    else:
        _CFG_SAVE["dirty"] = True

def flush_cfg():
    if _CFG_SAVE["dirty"]:
        _CFG_SAVE["dirty"] = False; _CFG_SAVE["last"] = time.time()
        save_cfg(CFG)

CFG = load_cfg()

# --------------------------- Single Instance (N slots) ---------------------------
# ===== Single-instance & restore via Win32 (ctypes only) =====
_MUTEX_NAME  = "Global\\DualSenseLED_SingleInstance"
_EVENT_NAME1 = "Global\\DualSenseLED_Restore"
_EVENT_NAME2 = "Local\\DualSenseLED_Restore"   # fallback

_win_handles = {"event": None, "mutex": None}

def _create_or_open_event():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateEventW = kernel32.CreateEventW
    CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    CreateEventW.restype  = wintypes.HANDLE
    h = CreateEventW(None, False, False, _EVENT_NAME1)
    if not h and ctypes.get_last_error() != 0:
        h = CreateEventW(None, False, False, _EVENT_NAME2)
    return h

def _open_event_for_set():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    OpenEventW = kernel32.OpenEventW
    OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    OpenEventW.restype  = wintypes.HANDLE
    EVENT_MODIFY_STATE = 0x0002
    h = OpenEventW(EVENT_MODIFY_STATE, False, _EVENT_NAME1)
    if not h and ctypes.get_last_error() != 0:
        h = OpenEventW(EVENT_MODIFY_STATE, False, _EVENT_NAME2)
    return h

def _set_event(h):
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SetEvent = kernel32.SetEvent
    SetEvent.argtypes = [ctypes.c_void_p]
    SetEvent.restype  = ctypes.c_bool
    try:
        SetEvent(h)
    except Exception:
        pass

def _wait_event_loop(cb_restore):
    import ctypes, time
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype  = wintypes.DWORD
    _win_handles["event"] = _create_or_open_event()
    if not _win_handles["event"]:
        return
    INFINITE = 0xFFFFFFFF
    while True:
        r = WaitForSingleObject(_win_handles["event"], INFINITE)
        try:
            cb_restore()
        except Exception:
            pass
        time.sleep(0.05)

def _secondary_instance_restore_and_exit():
    # Belt-and-suspenders: ping the kernel restore event AND drop the restore.signal
    # file. The running instance restores on either path, so if its event-wait
    # thread is wedged the 1s file poll still brings the window back — this is what
    # fixes "I had to double-click the shortcut several times before it appeared".
    h = _open_event_for_set()
    if h:
        _set_event(h)
    _signal_restore_request()

def _acquire_global_mutex():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype  = wintypes.HANDLE
    h = CreateMutexW(None, False, _MUTEX_NAME)
    _win_handles["mutex"] = h
    # ERROR_ALREADY_EXISTS = 183
    return ctypes.get_last_error() != 183

# -- Signal the running instance to restore (file-based ping)
def _signal_restore_request():
    try:
        (CONFIG_DIR / "restore.signal").write_text("1", encoding="utf-8")
    except Exception as e:
        log("signal restore err:", e)

# -- Strong Windows single-instance guard (keyed by EXE path so different copies don't conflict)

def _instance_already_running() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    exe_path = os.path.abspath(sys.argv[0]).lower()
    key = hashlib.sha1(exe_path.encode("utf-8")).hexdigest()[:8]
    name = f"Global\\{APP_NAME}_SingleInstance_{key}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype  = wintypes.HANDLE
    handle = CreateMutexW(None, False, name)
    # ERROR_ALREADY_EXISTS = 183
    return ctypes.get_last_error() == 183
    exe_path = os.path.abspath(sys.argv[0]).lower()
    key = hashlib.sha1(exe_path.encode("utf-8")).hexdigest()[:8]
    name = f"Global\\{APP_NAME}_SingleInstance_{key}"
    # Try with pywin32 if available
    try:
        import win32event, win32api, winerror
        h = win32event.CreateMutex(None, False, name)
        return win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    except Exception:
        pass
    # Fallback to ctypes
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype  = wintypes.HANDLE
        handle = CreateMutexW(None, False, name)
        # ERROR_ALREADY_EXISTS = 183
        return ctypes.get_last_error() == 183
    except Exception:
        return False

# -- Strong Windows single-instance guard (works even after packaging to EXE)
def _win_mutex_already_running() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        GetLastError = kernel32.GetLastError
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype  = wintypes.HANDLE
        handle = CreateMutexW(None, False, f"Global\\{APP_NAME}_SingleInstance")
        # ERROR_ALREADY_EXISTS = 183
        return ctypes.get_last_error() == 183
    except Exception:
        return False

_lock_fp = None; _lock_path = None
def acquire_slot_lock(max_instances:int) -> bool:
    global _lock_fp, _lock_path
    for i in range(1, max_instances+1):
        path = CONFIG_DIR / f"app.slot{i}.lock"
        try:
            fp = open(path, "w")
            if os.name == "nt":
                import msvcrt; msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl; fcntl.flock(fp, fcntl.LOCK_EX|fcntl.LOCK_NB)
            fp.write(str(os.getpid())); fp.flush()
            _lock_fp, _lock_path = fp, path
            return True
        except Exception:
            try: fp.close()
            except Exception: pass
            continue
    print(f"{APP_NAME}: already {max_instances} instance(s) running. Exiting.")
    return False

def release_slot_lock():
    global _lock_fp, _lock_path
    try:
        if _lock_fp:
            if os.name == "nt":
                import msvcrt; msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl; fcntl.flock(_lock_fp, fcntl.LOCK_UN)
            _lock_fp.close()
        if _lock_path:
            try: _lock_path.unlink(missing_ok=True)
            except Exception: pass
    except Exception:
        pass

# --------------------------- Utils ---------------------------
def clamp(x, a=0, b=255): return max(a, min(b, int(x)))
def clamp01(x): return 0.0 if x<0 else 1.0 if x>1 else x
def hex_to_rgb(hx):
    hx = hx.strip().lstrip("#")
    if len(hx)==3: hx="".join(c*2 for c in hx)
    return int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
def rgb_to_hex(rgb): r,g,b=[clamp(v) for v in rgb]; return f"#{r:02x}{g:02x}{b:02x}"


# --------------------------- Backend ---------------------------
class Backend:
    """PS5 (dualsense-controller/pydualsense) + PS4 USB (hidapi) — auto-detect"""
    def __init__(self, prefer="auto"):
        self.prefer=prefer; self.kind=None; self.dev=None; self.ds4=None

    def _connect_ds4_usb(self):
        try:
            import hid
        except Exception as e:
            log(f"hidapi not available: {e}"); return False
        try:
            VID = 0x054C
            PIDs = [0x05C4, 0x09CC, 0x0BA0]
            for d in hid.enumerate(VID, 0):
                if d.get('product_id') in PIDs:
                    self.ds4 = hid.device()
                    self.ds4.open_path(d['path'])
                    self.ds4.set_nonblocking(True)
                    self.kind = 'ds4'
                    log(f"DS4 connected: PID={hex(d.get('product_id'))}")
                    return True
        except Exception as e:
            log(f"ds4 connect fail: {e}")
        return False

    def connect(self)->bool:
        if self.prefer in ("auto","dualsense-controller"):
            try:
                import dualsense_controller as dsc
                self.dev=dsc.DualSenseController(); self.dev.connect()
                self.kind="dsc"; return True
            except Exception as e: log(f"dsc connect fail: {e}")
            if self.prefer=="dualsense-controller": return False
        if self.prefer in ("auto","pydualsense"):
            try:
                from pydualsense import pydualsense as PDS
                self.dev=PDS(); self.dev.init(); self.kind="pds"; return True
            except Exception as e: log(f"pds connect fail: {e}")
        if self.prefer in ("auto","ds4"):
            if self._connect_ds4_usb():
                return True
        return False

    def set_color(self, r,g,b):
        r=int(max(0,min(255,r))); g=int(max(0,min(255,g))); b=int(max(0,min(255,b)))
        if CFG.get("bgr_swap"): r,g,b = b,g,r
        try:
            if self.kind=="ds4":
                try:
                    buf = bytearray(32); buf[0]=0x05; buf[1]=0xFF; buf[6]=r; buf[7]=g; buf[8]=b
                    self.ds4.write(bytes(buf))
                except Exception:
                    try:
                        buf = bytearray(33); buf[0]=0x00; buf[1]=0x05; buf[2]=0xFF; buf[7]=r; buf[8]=g; buf[9]=b
                        self.ds4.write(bytes(buf))
                    except Exception as e:
                        log(f"ds4 set_color fail: {e}")
                return
            if self.kind=="dsc":
                for payload in [(r,g,b),(r/255.0,g/255.0,b/255.0)]:
                    try: self.dev.set_light_color(*payload); return
                    except Exception: pass
                try: self.dev.lightbar.set_color(r,g,b); return
                except Exception: pass
            elif self.kind=="pds":
                try: self.dev.light.setColorI(r,g,b); return
                except Exception: pass
        except Exception as e: log(f"set_color err: {e}")

    # ---- battery
    @staticmethod
    def _norm_batt(v):
        try:
            if v is None or isinstance(v,bool): return None
            if isinstance(v,(int,float)):
                x=float(v)
                if 0<=x<=1: return int(round(x*100))
                if 0<=x<=10: return int(round(x*10))
                return int(max(0,min(100,round(x))))
            if isinstance(v,str):
                s=v.strip().rstrip("%").strip(); return Backend._norm_batt(float(s))
        except Exception: pass
        return None

    @staticmethod
    def _scan_props(obj):
        out = []
        import inspect
        for n in dir(obj):
            if n.startswith("_"): continue
            try:
                v = getattr(obj, n)
                if callable(v) and len(inspect.signature(v).parameters)==0:
                    try: v=v()
                    except Exception: continue
                if isinstance(v,(int,float,bool,str)): out.append((n,v))
            except Exception: continue
        return out

    def get_battery(self):
        if self.kind=="ds4" or not self.dev: return None, False
        if self.kind=="pds":
            try:
                batt = getattr(self.dev, "battery", None)
                if batt is not None:
                    bf = CFG.get("pds_batt_field"); cf = CFG.get("pds_charge_field")
                    if bf:
                        try:
                            v = getattr(batt, bf); v=v() if callable(v) else v
                            p = Backend._norm_batt(v)
                        except Exception: p=None
                    else: p=None
                    ch=False
                    if cf:
                        try:
                            c=getattr(batt,cf); ch=bool(c() if callable(c) else c)
                        except Exception: ch=False
                    if p is None:
                        best=None; chname=None
                        for n,val in Backend._scan_props(batt):
                            if Backend._norm_batt(val) is not None: best=n; break
                        for n,val in Backend._scan_props(batt):
                            if isinstance(val,bool): chname=n; break
                        if best:
                            CFG["pds_batt_field"]=best
                            if chname: CFG["pds_charge_field"]=chname
                            save_cfg(CFG)
                            vv=getattr(batt,best); vv=vv() if callable(vv) else vv
                            p=Backend._norm_batt(vv)
                            ch=bool(getattr(batt,chname)) if chname else False
                    return p, ch
            except Exception as e:
                log("pds batt err:", e)
        # dualsense-controller أو أخرى
        try:
            cand=["state.battery","state.Battery","state.get_battery()","battery","get_battery()",
                  "get_battery_level()","battery_level","battery_percentage","get_battery_percent()"]
            ch_cand=["state.charging","state.is_charging","state.is_charging()","is_charging","charging"]
            def _safe_get(obj, names):
                for name in names:
                    try:
                        cur=obj
                        for seg in name.split("."):
                            if seg.endswith("()"): cur=getattr(cur, seg[:-2])()
                            else: cur=getattr(cur, seg)
                        return cur
                    except Exception: continue
                return None
            b=_safe_get(self.dev,cand); ch=_safe_get(self.dev,ch_cand)
            return Backend._norm_batt(b), bool(ch)
        except Exception as e:
            log("batt read err:", e); return None, False

    def close(self):
        try:
            if self.kind=="pds": self.dev.close()
        except Exception: pass

# --------------------------- EMA ---------------------------
class EMA:
    def __init__(self, alpha=0.35): self.a=alpha; self.v=None
    def update(self, x):
        if x is None: return None
        self.v = float(x) if self.v is None else self.a*float(x)+(1-self.a)*self.v
        return int(self.v+0.5)

# --------------------------- Engine ---------------------------
class Engine(threading.Thread):
    def __init__(self, backend: Backend):
        super().__init__(daemon=True)
        self.b=backend; self.stop_evt=threading.Event()
        self.mode=CFG.get("last_mode","Manual")
        if self.mode not in MODE_CODE: self.mode="Manual"
        self._seq_i=None
        self.speed=float(CFG.get("speed",1.0))
        self.rb=float(CFG.get("rainbow_brightness",0.9))
        self.duty=float(CFG.get("flash_duty",0.5))
        self.color_hex=CFG.get("color","#00aaff")
        self.color=hex_to_rgb(self.color_hex)
        self._ol = threading.Lock(); self.out = self.color
        self._last_apply = 0.0   # 0 = أول إرسال يتم فورًا

    # ---- profiles helpers
    def snapshot(self):
        return {"mode":self.mode,"speed":self.speed,"rainbow_brightness":self.rb,"flash_duty":self.duty,"color":rgb_to_hex(self.color)}
    def load_from(self, snap:dict):
        try:
            self.set_mode(snap.get("mode", self.mode))
            self.set_speed(snap.get("speed", self.speed))
            self.set_rb(snap.get("rainbow_brightness", self.rb))
            self.set_duty(snap.get("flash_duty", self.duty))
            self.set_color(hex_to_rgb(snap.get("color", rgb_to_hex(self.color))))
        except Exception: pass

    def _send(self, rgb):
        try:
            r,g,b = rgb
            self.b.set_color(r,g,b)
            with self._ol:
                self.out = (int(r),int(g),int(b))
            self._last_apply = time.time()
        except Exception as e:
            log("engine send err:", e)

    def set_mode(self,m):
        # وضع غير معروف (config محرَّر يدويًا/تالف) → Manual، وإلا حلقة التشغيل تدور بلا نوم
        self.mode = m if m in MODE_CODE else "Manual"
        self._seq_i = None
        CFG["last_mode"]=self.mode; save_cfg(CFG)
    def set_speed(self,v): self.speed=float(v); CFG["speed"]=self.speed; save_cfg_throttled(CFG)
    def set_rb(self,v): self.rb=float(v); CFG["rainbow_brightness"]=self.rb; save_cfg_throttled(CFG)
    def set_duty(self,v): self.duty=float(v); CFG["flash_duty"]=self.duty; save_cfg_throttled(CFG)
    def set_color(self,rgb):
        self.color=tuple(int(c) for c in rgb); CFG["color"]=rgb_to_hex(self.color); save_cfg_throttled(CFG)
        if self.mode=="Manual": self._send(self.color)



    # ---- run loop
    def run(self):
        t0=time.time(); i=0
        while not self.stop_evt.is_set():
            try:
                m=self.mode; s=self.speed; rb=self.rb; c=self.color; duty=self.duty

                if m=="Manual":
                    # اللون ثابت → أرسل فقط عند التغيّر + نبضة تثبيت كل ثانيتين
                    # (set_color يرسل فورًا عند التغيير، فالحلقة هنا للتثبيت فقط → نوم أطول)
                    with self._ol: cur = self.out
                    if tuple(c) != tuple(cur) or (time.time() - self._last_apply) > 2.0:
                        self._send(c)
                    time.sleep(0.25)

                elif m=="Battery":
                    # لون تلقائي حسب الشحن: أخضر ≥60، برتقالي ≥30، أحمر أقل — ونبض أثناء الشحن
                    now=time.time()
                    if now - getattr(self,"_batt_t",0.0) > 5.0:
                        try: bp,bch = self.b.get_battery()
                        except Exception: bp,bch = None,False
                        self._batt_t=now; self._batt_p=bp; self._batt_ch=bch
                    bp = getattr(self,"_batt_p",None)
                    if bp is None:  col=(180,180,180)
                    elif bp>=60:    col=(34,197,94)
                    elif bp>=30:    col=(245,158,11)
                    else:           col=(239,68,68)
                    if getattr(self,"_batt_ch",False):
                        k=0.55+0.45*(0.5+0.5*math.sin(time.time()*2.2))
                        col=tuple(int(x*k) for x in col)
                    self._send(col); time.sleep(0.5)

                elif m=="Sequence":
                    pal=[(255,40,40),(40,200,90),(40,130,255),(160,60,255),(255,255,255),(0,0,0)]
                    idx=int((time.time()-t0)//max(0.1,s))%len(pal)
                    if idx != self._seq_i:
                        self._send(pal[idx]); self._seq_i=idx
                    time.sleep(1/30)

                elif m=="Random":
                    if i%int(max(1,s*30))==0:
                        self._send((random.randint(0,255),random.randint(0,255),random.randint(0,255)))
                    time.sleep(1/30)

                elif m=="Rainbow":
                    cyc=max(0.2,s); u=((time.time()-t0)%cyc)/cyc
                    r,g,b=[int(255*x) for x in colorsys.hsv_to_rgb(u,1.0,clamp01(rb))]
                    self._send((r,g,b)); time.sleep(1/60)

                elif m=="Pulse":  # sinus on current color
                    per=max(0.2,s); u=((time.time()-t0)%per)/per; k=0.5-0.5*math.cos(2*math.pi*u)
                    r=int(c[0]*k); g=int(c[1]*k); b=int(c[2]*k); self._send((r,g,b)); time.sleep(1/60)

                elif m=="Flash":
                    per=max(0.2,s); u=((time.time()-t0)%per)/per
                    base=c if u<duty else (0,0,0); self._send(base); time.sleep(1/60)

                elif m=="Breathing":
                    per=max(0.8,s); u=((time.time()-t0)%per)/per; k=(1-math.cos(2*math.pi*u))*0.5
                    r=int(c[0]*k); g=int(c[1]*k); b=int(c[2]*k); self._send((r,g,b)); time.sleep(1/60)

                elif m=="Heartbeat":  # double pulse
                    per=max(0.8,s); u=((time.time()-t0)%per)/per
                    k = (1 if u<0.05 else 0.6 if u<0.1 else 1 if 0.3<u<0.35 else 0)  # نبضتان سريعتان
                    r=int(c[0]*k); g=int(c[1]*k); b=int(c[2]*k); self._send((r,g,b)); time.sleep(1/60)

                elif m=="Wave":  # موجة لونية عبر Hue
                    cyc=max(0.8,s); u=((time.time()-t0)%cyc)/cyc
                    r,g,b=[int(255*x) for x in colorsys.hsv_to_rgb(u,0.8,clamp01(rb))]
                    self._send((r,g,b)); time.sleep(1/60)

                elif m=="Gradient":  # بين لون ثابت وأبيض
                    cyc=max(0.8,s); u=((time.time()-t0)%cyc)/cyc; k=0.5-0.5*math.cos(2*math.pi*u)
                    r=int(c[0]*(1-k)+255*k); g=int(c[1]*(1-k)+255*k); b=int(c[2]*(1-k)+255*k)
                    self._send((r,g,b)); time.sleep(1/60)

                else:
                    # حزام أمان: وضع غير معروف لا يجوز أن يدوّر الحلقة بلا نوم
                    time.sleep(0.1)

                # Auto Sleep
                if CFG.get("auto_sleep",{}).get("enabled", False):
                    idle = time.time() - self._last_apply
                    mins = max(1, int(CFG["auto_sleep"].get("minutes",30)))
                    if idle > mins*60:
                        act = CFG["auto_sleep"].get("action","off")
                        if act=="off": self._send((0,0,0))
                        else: self._send(self.color)
                        # بعدها ننتظر ثانية لئلا نستهلك CPU
                        time.sleep(1.0)

                i+=1

            except Exception as e:
                log("engine loop err:", e); time.sleep(0.2)

# --------------------------- Background (headless) ---------------------------
STOP_SIGNAL = CONFIG_DIR / "stop.signal"

def run_background(off_on_exit=False, stop_after_min=None):
    log("BG: start")
    backend = Backend(prefer=CFG.get("backend","auto"))
    if not backend.connect():
        log("BG: controller not found"); return
    engine = Engine(backend); engine.start()
    engine.set_color(hex_to_rgb(CFG.get("color","#00aaff")))
    stop_evt = threading.Event()

    # Clear any stale stop signal so the new instance doesn't exit immediately.
    try: STOP_SIGNAL.unlink(missing_ok=True)
    except Exception: pass

    # Graceful shutdown on taskkill (no /F), logoff, Ctrl+Break — exits through
    # the finally block so the lightbar is cleaned up.
    def _on_signal(*_a):
        stop_evt.set()
    for _sig in ("SIGTERM", "SIGINT", "SIGBREAK"):
        try:
            import signal as _signal
            s = getattr(_signal, _sig, None)
            if s is not None: _signal.signal(s, _on_signal)
        except Exception:
            pass

    def battery_logger():
        ema = EMA(0.35)
        while not stop_evt.is_set():
            p,ch = backend.get_battery(); p2 = ema.update(p)
            if p2 is not None: log(f"BG: battery={p2}% charging={ch}")
            time.sleep(60)

    def timer():
        if stop_after_min is None: return
        time.sleep(max(0,float(stop_after_min))*60); stop_evt.set()

    threading.Thread(target=battery_logger, daemon=True).start()
    threading.Thread(target=timer, daemon=True).start()

    try:
        while not stop_evt.is_set():
            # Stop channel: a companion '--stop' launch (or the Stop shortcut)
            # drops this file so a non-technical user can halt the hidden process.
            if STOP_SIGNAL.exists():
                try: STOP_SIGNAL.unlink(missing_ok=True)
                except Exception: pass
                log("BG: stop signal received")
                break
            time.sleep(0.5)
    finally:
        try: engine.stop_evt.set()
        except Exception: pass
        if off_on_exit:
            try: backend.set_color(0,0,0)
            except Exception: pass
        try: backend.close()
        except Exception: pass
        log("BG: stop")

# --------------------------- Starfield ---------------------------
class Starfield(tk.Canvas):
    def __init__(self, master, count=110, **kw):
        super().__init__(master, highlightthickness=0, bd=0, **kw)
        self.count=count; self.stars=[]; self.running=False; self._after=None
    def start(self):
        if self.running: return
        self.running=True; self._schedule()
    def _schedule(self, delay=40):
        if not self.running or not self.winfo_exists(): return
        self._after=self.after(delay, self._tick)  # ~25 FPS وهو ظاهر، ~2Hz وهو خامل
    def _idle(self):
        try:
            if not self.winfo_viewable(): return True
            return self.winfo_toplevel().focus_displayof() is None
        except Exception:
            return False
    def _tick(self):
        if not self.running or not self.winfo_exists(): return
        idle = False
        try:
            # مخفي أو التطبيق بلا تركيز (داخل لعبة)؟ لا رسم — صفر استهلاك
            idle = self._idle()
            if idle:
                return
            w=self.winfo_width(); h=self.winfo_height()
            if not self.stars:
                for _ in range(self.count):
                    x=random.random()*w; y=random.random()*h; r=random.random()*1.8+0.5; sp=random.random()*0.8+0.2
                    self.stars.append([x,y,r,sp])
            self.delete("all")
            for s in self.stars:
                s[1]+=s[3]
                if s[1]>h: s[1]=0
                x,y,r,_=s; self.create_oval(x-r,y-r,x+r,y+r, fill="#6f7aa7", outline="")
        finally:
            self._schedule(500 if idle else 40)
    def stop(self):
        self.running=False
        try:
            if self._after is not None: self.after_cancel(self._after)
        except Exception: pass

# --------------------------- DualSense SVG asset (accurate 2D view) ---------------------------
# يُحمَّل من assets/dualsense-svgrepo.svg (أيقونة line-art مرخّصة من SVG Repo، viewBox 128x128).
# التحليل: 23 مسارًا، أوامر M/L/C/H/V/Z كبيرة فقط. لو الملف مفقود/تغيّر → نرجع للعرض 3D تلقائيًا.

def _flatten_cubic(p0, c1, c2, p1, steps=12):
    """تحويل منحنى Bezier تكعيبي إلى نقاط مستقيمة."""
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        a = mt * mt * mt; b = 3 * mt * mt * t; c = 3 * mt * t * t; d = t * t * t
        pts.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0],
                    a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1]))
    return pts

def _parse_svg_path_d(d):
    """يفكّك خاصية d (أوامر مطلقة M/L/C/H/V/Z فقط) إلى قائمة subpaths من النقاط."""
    toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    subs, cur = [], []
    x = y = 0.0
    i = 0
    cmd = None
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            if t not in "MLCHVZ":
                return None            # أمر غير مدعوم (نسبي/قوس) → فشل آمن
            cmd = t; i += 1
            if cmd == "Z":
                if cur: subs.append(cur)
                cur = []
            continue
        if cmd == "M":
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            if cur: subs.append(cur)
            cur = [(x, y)]
            cmd = "L"                  # إحداثيات لاحقة بعد M تُعامل كـ L
        elif cmd == "L":
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            cur.append((x, y))
        elif cmd == "H":
            x = float(toks[i]); i += 1
            cur.append((x, y))
        elif cmd == "V":
            y = float(toks[i]); i += 1
            cur.append((x, y))
        elif cmd == "C":
            c1 = (float(toks[i]), float(toks[i + 1]))
            c2 = (float(toks[i + 2]), float(toks[i + 3]))
            p1 = (float(toks[i + 4]), float(toks[i + 5])); i += 6
            cur.extend(_flatten_cubic((x, y), c1, c2, p1))
            x, y = p1
        else:
            return None
    if cur: subs.append(cur)
    return subs

# فهرسة مكوّنات الأيقونة (ثابتة لهذا الأصل تحديدًا — تحقّق منها محلّل مسارات مستقل)
_DS_IDX = {
    "touch": 0, "body": 1, "btn_tri": 2, "btn_cross": 3, "btn_sq": 4,
    "well_r": 5, "well_l": 6, "cap_l": 7, "cap_r": 8, "r1": 9, "l1": 10,
    "wing_r": 11, "wing_l": 12, "btn_circ": 13, "mute": 14,
    "dp_down": 15, "dp_up": 16, "dp_left": 17, "dp_right": 18,
    "opts": 19, "create": 20, "grille2": 21, "grille1": 22,
}

# محور شريط الإضاءة الأيسر — يحضن حافة التاتشباد اليسرى من زاويتها العلوية حتى السفلية
# ثم يلتف قليلًا للداخل حول الزاوية (مطابق لليد الحقيقية: الضوء لا يتجاوز التاتشباد للأسفل).
_DS_LB_LEFT = [((43.4, 28.8), (42.0, 31.0), (41.3, 34.0), (41.4, 37.5)),
               ((41.4, 37.5), (41.9, 41.0), (42.7, 44.5), (43.4, 47.5)),
               ((43.4, 47.5), (43.9, 49.8), (44.6, 51.7), (45.8, 52.9)),
               ((45.8, 52.9), (46.4, 53.5), (47.0, 53.8), (47.8, 53.9))]

def _ds_lightbar_polylines():
    left = []
    for seg in _DS_LB_LEFT:
        if not left: left.append(seg[0])
        left.extend(_flatten_cubic(*seg, steps=8))
    right = [(128.0 - x, y) for (x, y) in left]
    return left, right

_DS_SVG = {"tried": False, "geo": None}

def _load_dualsense_svg():
    """تحميل وتفكيك الأيقونة مرة واحدة. None لو الأصل مفقود أو بنيته غير متوقعة."""
    if _DS_SVG["tried"]:
        return _DS_SVG["geo"]
    _DS_SVG["tried"] = True
    try:
        here = Path(__file__).resolve().parent
        p = here / "assets" / "dualsense-svgrepo.svg"
        if not p.exists():
            log("dualsense svg asset missing:", p)
            return None
        txt = p.read_text(encoding="utf-8")
        ds = re.findall(r'\bd="([^"]+)"', txt)
        paths = [_parse_svg_path_d(d) for d in ds]
        if len(paths) != 23 or any(sp is None or not sp for sp in paths):
            log("dualsense svg asset unexpected structure; falling back to 3D")
            return None
        lb_l, lb_r = _ds_lightbar_polylines()
        _DS_SVG["geo"] = {"paths": paths, "lb": (lb_l, lb_r)}
        log("dualsense svg asset loaded:", len(paths), "paths")
    except Exception as e:
        log("dualsense svg parse err:", e)
        _DS_SVG["geo"] = None
    return _DS_SVG["geo"]

# ألوان أطقم DualSense الرسمية الشهيرة — تُطبَّق على رسم اليد
_DS_SHELLS = {
    "white":  {"shell": (223,226,233), "line": (72,78,92),   "touch": (232,234,239), "dpad": (211,215,224), "bump": (58,62,72),   "btn": (52,56,66),   "glyph": (158,164,176), "inset": (31,34,41)},
    "black":  {"shell": (45,47,54),    "line": (118,124,136),"touch": (56,58,66),    "dpad": (58,61,70),    "bump": (28,30,36),   "btn": (38,41,49),   "glyph": (172,177,187), "inset": (22,24,29)},
    "red":    {"shell": (158,34,48),   "line": (232,196,200),"touch": (176,52,66),   "dpad": (146,30,44),   "bump": (72,16,24),   "btn": (84,22,32),   "glyph": (240,214,218), "inset": (34,18,22)},
    "blue":   {"shell": (70,118,205),  "line": (214,226,246),"touch": (92,138,218),  "dpad": (62,106,188),  "bump": (30,48,86),   "btn": (38,58,100),  "glyph": (222,232,248), "inset": (22,30,48)},
    "purple": {"shell": (112,92,168),  "line": (226,220,242),"touch": (128,108,184), "dpad": (102,84,156),  "bump": (48,38,76),   "btn": (60,48,94),   "glyph": (230,224,244), "inset": (30,26,46)},
}

# --------------------------- Controller Widget ---------------------------
class Controller3D(tk.Canvas):
    """عرض يد DualSense دقيق من أصل SVG مرخّص — شريطا الإضاءة يتزامنان مع اللون الفعلي 100%."""
    def __init__(self, master, controller_type="ps5", width=680, height=260, **kw):
        bg = kw.pop("bg", "#0b0f14")
        super().__init__(master, width=width, height=height, bg=bg, highlightthickness=0, bd=0, **kw)
        self.ctrl_type = controller_type  # "ps5" or "ps4"
        self._led_color = (0, 170, 255)   # RGB tuple — synced with engine output
        self._glow_layers = 8             # عدد طبقات التوهج
        self._width = width
        self._height = height
        self._bg = bg
        self._draw_id = None
        self._mode = "Manual"             # active lighting mode (drives glow signature)
        self._anim = 0                    # free-running phase, advanced once per redraw
        self.on_click = None              # يضبطه App: نقرة = منتقي الألوان
        self._shell = "white"             # طقم ألوان اليد (أبيض/أسود/أحمر/أزرق/بنفسجي)
        self.configure(cursor="hand2")
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)

    def _on_resize(self, event=None):
        self._width = self.winfo_width()
        self._height = self.winfo_height()
        self.redraw()

    def _on_click(self, ev):
        if callable(self.on_click):
            self.on_click(ev)

    def set_led_color(self, r, g, b):
        """تحديث لون LED — يُستدعى كل 33ms من sync loop."""
        rgb = (int(r), int(g), int(b))
        # لون ثابت + وضع بلا توقيع متحرك → لا داعي لإعادة الرسم (توفير CPU)
        if rgb == self._led_color and self._mode not in ("Rainbow", "Wave", "Sequence"):
            return
        self._led_color = rgb
        self.redraw()

    def set_controller_type(self, ctype):
        """توافق خلفي — العرض DualSense دائمًا (اليد الفعلية PS4 تبقى مدعومة بالتحكم)."""
        self.ctrl_type = ctype

    def set_mode(self, code):
        """تحديث وضع الإضاءة — يغيّر شكل/توقيع توهّج الشريط حسب الوضع المختار"""
        self._mode = code or "Manual"
        self.redraw()

    def set_shell(self, key):
        """تبديل طقم ألوان اليد المعروضة (أطقم DualSense الرسمية)."""
        if key in _DS_SHELLS and key != self._shell:
            self._shell = key
            self.redraw()

    def _blend(self, c1, c2, t):
        """خلط لونين بنسبة t (0=c1, 1=c2)"""
        return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

    def _hex(self, rgb):
        return f"#{max(0,min(255,rgb[0])):02x}{max(0,min(255,rgb[1])):02x}{max(0,min(255,rgb[2])):02x}"

    def _parse_bg(self):
        bg = self._bg
        if isinstance(bg, str) and bg.startswith("#"):
            bg = bg.lstrip("#")
            if len(bg) == 3:
                bg = "".join(c*2 for c in bg)
            return (int(bg[0:2],16), int(bg[2:4],16), int(bg[4:6],16))
        return (11, 15, 20)

    def redraw(self):
        """يمسح ويعيد رسم يد DualSense مع شريطي الإضاءة."""
        self._anim = (self._anim + 1) % 360   # phase advances once per frame
        self.delete("all")
        bg = self._parse_bg()
        geo = _load_dualsense_svg()
        if geo is not None:
            self._draw_ps5_svg(geo, bg)
        else:
            self._draw_fallback(bg)

    def _draw_fallback(self, bg):
        """احتياط نادر (أصل SVG مفقود): كبسولة LED بسيطة بلون المحرك."""
        W, H = max(1, self._width), max(1, self._height)
        led = self._led_color
        y = H // 2; x0, x1 = int(W * 0.25), int(W * 0.75)
        th = max(8, int(H * 0.08))
        for i in range(4, 0, -1):
            self.create_line(x0, y, x1, y, fill=self._hex(self._blend(bg, led, 0.06 + 0.05 * (4 - i))),
                             width=th + i * th, capstyle=tk.ROUND)
        self.create_line(x0, y, x1, y, fill=self._hex(led), width=th, capstyle=tk.ROUND)

    # ==================== نظرة SVG الدقيقة (PS5) ====================
    def _svg_tx(self):
        """معامل التحويل من فضاء الأيقونة 128 إلى فضاء الكانفس: (scale, ox, oy)."""
        W, H = max(1, self._width), max(1, self._height)
        s = min(W * 0.86 / 113.0, H * 0.86 / 75.0)
        return s, W / 2.0 - 64.0 * s, H / 2.0 - 64.0 * s

    def _poly(self, pts, s, ox, oy):
        out = []
        for (x, y) in pts:
            out.append(ox + x * s); out.append(oy + y * s)
        return out

    def _draw_ps5_svg(self, geo, bg):
        led = self._led_color
        s, ox, oy = self._svg_tx()
        P = geo["paths"]; I = _DS_IDX
        lw = max(1, round(s * 0.5))                     # سماكة خطوط الأيقونة
        pal = _DS_SHELLS.get(self._shell, _DS_SHELLS["white"])
        LINE = self._hex(pal["line"])
        SHELL = pal["shell"]
        body = P[I["body"]][0]

        # ملاحظة: مسار الجسم يعبر جسرًا مزدوجًا في المنتصف → قاعدة even-odd تُفرغ المقبضين،
        # لذا نكمل التعبئة بمخططي الجناحين (wing_l/wing_r) اللذين يغطيان المقبضين بالكامل.
        wing_l = P[I["wing_l"]][0]; wing_r = P[I["wing_r"]][0]
        # (1) ظل خفيف تحت الجسم
        SHC = self._hex(self._blend(bg, (0, 0, 0), 0.5))
        for part in (body, wing_l, wing_r):
            sh = self._poly([(x + 1.6, y + 2.2) for (x, y) in part], s, ox, oy)
            self.create_polygon(sh, fill=SHC, outline="")
        # (2) الهيكل الأبيض (سيلويت الجسم + الجناحان/المقبضان)
        for part in (body, wing_l, wing_r):
            self.create_polygon(self._poly(part, s, ox, oy), fill=self._hex(SHELL), outline="")
        # (3) القسم الداكن الأوسط حول العصوين (سمة DualSense المميزة)
        self._ps5_center_inset(s, ox, oy, pal["inset"])
        # (4) سطح التاتشباد — أبيض مع غسلة خفيفة من لون LED
        touch = P[I["touch"]][0]
        self.create_polygon(self._poly(touch, s, ox, oy),
                            fill=self._hex(self._blend(pal["touch"], led, 0.08)), outline="")
        # (5) شريطا الإضاءة يحضنان حافتي التاتشباد + خط الانتشار على حافته السفلية (البطل)
        lb_l, lb_r = geo["lb"]
        th = max(3, round(s * 1.2))
        self._draw_lightbar_strip(self._poly(lb_l, s, ox, oy), led, bg, th, 0)
        self._draw_lightbar_strip(self._poly(lb_r, s, ox, oy), led, bg, th, 1)
        # خط انتشار الضوء أسفل التاتشباد (يظهر أبيض متوهّج بلمسة من لون LED كما في العتاد)
        dy0 = oy + 54.15 * s
        dx0, dx1 = ox + 48.6 * s, ox + 79.4 * s
        self.create_line(dx0, dy0, dx1, dy0, fill=self._hex(self._blend(SHELL, led, 0.35)),
                         width=max(2, round(s * 0.7)), capstyle=tk.ROUND)
        self.create_line(dx0, dy0, dx1, dy0, fill=self._hex(self._blend(led, (255, 255, 255), 0.72)),
                         width=max(1, round(s * 0.3)), capstyle=tk.ROUND)
        # (6) خطوط الأيقونة (الحدود الأصلية من الأصل المرخّص)
        for key in ("body", "wing_l", "wing_r", "touch"):
            self.create_line(self._poly(P[I[key]][0] + P[I[key]][0][:1], s, ox, oy),
                             fill=LINE, width=lw, joinstyle=tk.ROUND)
        # (7) أكتاف L1/R1 — بلاستيك داكن أعلى الحافة
        for key in ("l1", "r1"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex(pal["bump"]), outline=LINE, width=1)
        # (8) أذرع D-Pad — فاتحة فوق الجناح الأبيض
        for key in ("dp_up", "dp_down", "dp_left", "dp_right"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex(pal["dpad"]), outline=LINE, width=1)
        # (9) بئرا العصوين + الغطاءان — أسود مطفي كما في اليد الحقيقية
        for key in ("well_l", "well_r"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex((24, 26, 31)), outline=self._hex((60, 64, 76)), width=1)
        for key in ("cap_l", "cap_r"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex((17, 19, 23)), outline=self._hex((74, 80, 92)), width=1)
        # (10) الأزرار الأربعة — أغطية داكنة شفافة برموز رمادية أحادية (سمة DualSense)
        for key in ("btn_tri", "btn_circ", "btn_cross", "btn_sq"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex(pal["btn"]), outline=LINE, width=1)
        self._ps5_button_glyphs(s, ox, oy, pal["glyph"])
        # (11) أزرار Create/Options + زر كتم المايك
        for key in ("create", "opts"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex((70, 75, 86)), outline="")
        self.create_polygon(self._poly(P[I["mute"]][0], s, ox, oy),
                            fill=self._hex((30, 33, 40)), outline=LINE, width=1)
        # (12) مؤشرات اللاعب — 5 نقاط بيضاء أسفل التاتشباد (بيضاء في العتاد الحقيقي)
        for k in (-2, -1, 0, 1, 2):
            cxp = ox + (64.0 + k * 2.2) * s
            cyp = oy + 56.0 * s
            r = max(1.2, 0.5 * s)
            bright = 0.62 if k == 0 else 0.38
            self.create_oval(cxp - r, cyp - r, cxp + r, cyp + r,
                             fill=self._hex(self._blend(bg, (255, 255, 255), bright)), outline="")
        # (13) فتحات المايك السفلية من الأيقونة
        for key in ("grille1", "grille2"):
            self.create_polygon(self._poly(P[I[key]][0], s, ox, oy),
                                fill=self._hex((96, 102, 114)), outline="")

    def _ps5_center_inset(self, s, ox, oy, inset_rgb=(31, 34, 41)):
        """كبسولة داكنة بين العصوين — القسم الأسود في وجه DualSense.
        حدّها السفلي يبقى فوق خط الالتحام (y≈75) كي لا يندمج مع الفراغ بين المقبضين."""
        pts = []
        cl, cr, cy0, rr = 46.5, 81.5, 64.9, 9.0
        for i in range(13):                              # قوس يسار (أعلى→أسفل)
            a = math.pi / 2 + math.pi * (i / 12)
            pts.append((cl + rr * math.cos(a), cy0 - rr * math.sin(a)))
        pts += [(56.5, 72.6), (60.0, 74.3), (64.0, 74.8), (68.0, 74.3), (71.5, 72.6)]
        for i in range(13):                              # قوس يمين (أسفل→أعلى)
            a = -math.pi / 2 + math.pi * (i / 12)
            pts.append((cr + rr * math.cos(a), cy0 - rr * math.sin(a)))
        self.create_polygon(self._poly(pts, s, ox, oy),
                            fill=self._hex(inset_rgb), outline="", smooth=True)

    def _ps5_button_glyphs(self, s, ox, oy, glyph_rgb=(158, 164, 176)):
        """رموز △ ○ ✕ □ أحادية اللون (DualSense بلا ألوان رموز)."""
        g = self._hex(glyph_rgb)
        w = max(1, round(s * 0.38))
        def T(x, y): return (ox + x * s, oy + y * s)
        # △ at (99, 39.96)
        p1 = T(99, 38.35); p2 = T(100.65, 41.25); p3 = T(97.35, 41.25)
        self.create_line(*p1, *p2, *p3, *p1, fill=g, width=w, joinstyle=tk.ROUND)
        # ○ at (107, 47.96)
        a0 = T(107 - 1.55, 47.96 - 1.55); a1 = T(107 + 1.55, 47.96 + 1.55)
        self.create_oval(*a0, *a1, outline=g, width=w)
        # ✕ at (99, 55.96)
        self.create_line(*T(97.65, 54.6), *T(100.35, 57.3), fill=g, width=w, capstyle=tk.ROUND)
        self.create_line(*T(100.35, 54.6), *T(97.65, 57.3), fill=g, width=w, capstyle=tk.ROUND)
        # □ at (91, 47.96)
        b0 = T(91 - 1.4, 47.96 - 1.4); b1 = T(91 + 1.4, 47.96 + 1.4)
        self.create_rectangle(*b0, *b1, outline=g, width=w)

    def _draw_lightbar_strip(self, flat, led, bg, th, side):
        """شريط إضاءة واحد (polyline مسطّح) بتوهّج طبقي وتوقيع حسب الوضع."""
        mode = self._mode
        phase = self._anim
        white = (255, 255, 255)
        n = len(flat) // 2 - 1
        # توهّج خارجي مضبوط — طبقات قليلة قريبة من الشريط (بدون زيادة)
        for i in range(3, 0, -1):
            self.create_line(*flat, fill=self._hex(self._blend(bg, led, 0.07 + 0.06 * (3 - i))),
                             width=th + i * max(2, th // 2) * 2, capstyle=tk.ROUND, joinstyle=tk.ROUND)

        def seg_color(k):
            if mode == "Rainbow":
                h = (phase / 360.0 + k / max(1, n) * 0.5 + side * 0.5) % 1.0
                r_, g_, b_ = colorsys.hsv_to_rgb(h, 1.0, 1.0)
                return (int(r_ * 255), int(g_ * 255), int(b_ * 255))
            if mode == "Wave":
                br = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(phase * 0.15 - k * 0.55))
                return self._blend(bg, led, br)
            if mode == "Sequence":
                comet = (phase // 5) % max(1, n)
                d = abs(k - comet)
                return self._blend(led, white, 0.55) if d == 0 else self._blend(bg, led, max(0.15, 1.0 - d * 0.3))
            if mode == "Random":
                tbl = (0.4, 0.7, 1.0)
                return self._blend(bg, led, tbl[((k * 73 + 29 + side * 41) % 100) % 3])
            return None

        if mode in ("Rainbow", "Wave", "Sequence", "Random"):
            for k in range(n):
                self.create_line(flat[k * 2], flat[k * 2 + 1], flat[k * 2 + 2], flat[k * 2 + 3],
                                 fill=self._hex(seg_color(k)), width=th, capstyle=tk.ROUND)
        else:
            self.create_line(*flat, fill=self._hex(led), width=th,
                             capstyle=tk.ROUND, joinstyle=tk.ROUND)
            self.create_line(*flat, fill=self._hex(self._blend(led, white, 0.5)),
                             width=max(1, th // 3), capstyle=tk.ROUND, joinstyle=tk.ROUND)


# --------------------------- i18n ---------------------------
STR = {
 "ar": {
   "title":"🎮 PS5 LED",
   "subtitle":"التغييرات تُطبّق فورًا — زر الإيقاف يثبت اللون.",
   "lang":"اللغة","fullscreen":"ملء الشاشة","windowed":"نافذة",
   "battery":"البطارية",
   "mode":"الوضع","interval":"السرعة/الفاصل","rainbow_brightness":"سطوع قوس قزح","flash_duty":"نسبة الوميض",
   "pick_color":"اختيار لون","stop":"إيقاف","quick":"ألوان سريعة",
   "background":"تشغيل في الخلفية","close":"إغلاق",
   "rgb_fix":"تصحيح RGB/BGR",
   "profiles":"ملفات التعريف","save_profile":"حفظ","delete_profile":"حذف",
   "auto_sleep":"خمول تلقائي","as_minutes":"دقائق","as_action":"الإجراء","as_off":"إطفاء","as_solid":"تثبيت",
   "status_manual":"الحالة: يدوي","status_sequence":"الحالة: تتابع (فاصل {v:.1f}s)",
   "status_random":"الحالة: عشوائي (فاصل {v:.1f}s)","status_rainbow":"الحالة: قوس قزح (دورة {v:.1f}s، سطوع {b:.2f})",
   "status_pulse":"الحالة: نبض (فترة {v:.1f}s)","status_breath":"الحالة: تنفس","status_wave":"الحالة: موجة",
   "status_grad":"الحالة: تدرّج","status_batt":"الحالة: لون حسب البطارية",
   "shell_color":"لون اليد",
   "ctrl_not_found":"لم يتم العثور على يد التحكم."
 },
 "en": {
   "title":"🎮 PS5 LED",
   "subtitle":"Instant apply — Stop restores last solid color.",
   "lang":"Language","fullscreen":"Fullscreen","windowed":"Windowed",
   "battery":"Battery",
   "mode":"Mode","interval":"Speed / Interval","rainbow_brightness":"Rainbow Brightness","flash_duty":"Flash Duty",
   "pick_color":"Pick Color","stop":"Stop","quick":"Quick Colors",
   "background":"Run in background","close":"Close",
   "rgb_fix":"RGB/BGR mapping fix",
   "profiles":"Profiles","save_profile":"Save","delete_profile":"Delete",
   "auto_sleep":"Auto Sleep","as_minutes":"Minutes","as_action":"Action","as_off":"Off","as_solid":"Solid",
   "status_manual":"Status: Manual","status_sequence":"Status: Sequence (interval {v:.1f}s)",
   "status_random":"Status: Random (interval {v:.1f}s)","status_rainbow":"Status: Rainbow (cycle {v:.1f}s, brightness {b:.2f})",
   "status_pulse":"Status: Pulse (period {v:.1f}s)","status_breath":"Status: Breathing","status_wave":"Status: Wave",
   "status_grad":"Status: Gradient","status_batt":"Status: Battery color",
   "shell_color":"Shell Color",
   "ctrl_not_found":"Controller not found."
 }
}

MODE_DISPLAY = {"ar": ["يدوي","تتابع","عشوائي","قوس قزح","نبض","وميض","تنفس","نبض قلب","موجة","تدرّج","البطارية"],
                "en": ["Manual","Sequence","Random","Rainbow","Pulse","Flash","Breathing","Heartbeat","Wave","Gradient","Battery"]}
MODE_CODE =     ["Manual","Sequence","Random","Rainbow","Pulse","Flash","Breathing","Heartbeat","Wave","Gradient","Battery"]

def code_to_display(lang, code):
    opts = MODE_DISPLAY.get(lang, MODE_DISPLAY["en"])
    return opts[MODE_CODE.index(code)] if code in MODE_CODE else opts[0]
def display_to_code(lang, disp):
    opts = MODE_DISPLAY.get(lang, MODE_DISPLAY["en"])
    return MODE_CODE[opts.index(disp)] if disp in opts else "Manual"


# --------------------------- Tray icon (Win32, stdlib only) ---------------------------
class TrayIcon:
    """أيقونة بجانب الساعة عبر Shell_NotifyIcon مباشرة — بدون أي مكتبات إضافية.
    كليك يسار = فتح البرنامج. كليك يمين = قائمة: بروفايلات + إطفاء + خروج.
    on_action(key) يُستدعى من خيط الأيقونة — لا يلمس Tk، فقط يضع بالطابور."""
    WM_TRAY = 0x8001  # WM_APP + 1

    def __init__(self, tooltip, icon_path, menu_provider, on_action):
        self._tip = tooltip
        self._icon_path = icon_path
        self._menu_provider = menu_provider   # callable -> [(key, label) | ("sep", None)]
        self._on_action = on_action
        self._hwnd = None
        self._ids = {}
        self._alive = False
        if platform.system() != "Windows":
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def destroy(self):
        try:
            if self._hwnd:
                import ctypes
                ctypes.windll.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            sh = ctypes.windll.shell32
            k32 = ctypes.windll.kernel32

            class NID(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                            ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                            ("dwInfoFlags", wintypes.DWORD)]

            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM)

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == TrayIcon.WM_TRAY:
                    if lparam == 0x0202:      # WM_LBUTTONUP
                        self._on_action("open")
                    elif lparam == 0x0205:    # WM_RBUTTONUP
                        self._popup(u32, hwnd)
                    return 0
                if msg == 0x0002:             # WM_DESTROY
                    try:
                        nid = NID(); nid.cbSize = ctypes.sizeof(NID)
                        nid.hWnd = hwnd; nid.uID = 1
                        sh.Shell_NotifyIconW(2, ctypes.byref(nid))  # NIM_DELETE
                    except Exception:
                        pass
                    u32.PostQuitMessage(0)
                    return 0
                return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._proc = WNDPROC(wnd_proc)    # مرجع حي — وإلا يجمعه GC وينهار
            hinst = k32.GetModuleHandleW(None)

            class WNDCLASS(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

            wc = WNDCLASS()
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = "DualLEDTray"
            u32.RegisterClassW(ctypes.byref(wc))
            self._hwnd = u32.CreateWindowExW(0, "DualLEDTray", None, 0, 0, 0, 0, 0,
                                             None, None, hinst, None)

            hicon = None
            try:
                if self._icon_path and os.path.exists(self._icon_path):
                    hicon = u32.LoadImageW(None, self._icon_path, 1, 0, 0, 0x0010 | 0x0040)
            except Exception:
                hicon = None
            if not hicon:
                hicon = u32.LoadIconW(None, 32512)  # IDI_APPLICATION

            nid = NID(); nid.cbSize = ctypes.sizeof(NID)
            nid.hWnd = self._hwnd; nid.uID = 1
            nid.uFlags = 0x1 | 0x2 | 0x4      # NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = TrayIcon.WM_TRAY
            nid.hIcon = hicon
            nid.szTip = self._tip[:127]
            sh.Shell_NotifyIconW(0, ctypes.byref(nid))  # NIM_ADD
            self._alive = True

            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log("tray err:", e)

    def _popup(self, u32, hwnd):
        try:
            import ctypes
            from ctypes import wintypes
            menu = u32.CreatePopupMenu()
            self._ids = {}
            next_id = 1000
            for key, label in self._menu_provider():
                if key == "sep":
                    u32.AppendMenuW(menu, 0x800, 0, None)          # MF_SEPARATOR
                else:
                    self._ids[next_id] = key
                    u32.AppendMenuW(menu, 0x0, next_id, label)     # MF_STRING
                    next_id += 1
            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            u32.SetForegroundWindow(hwnd)
            cmd = u32.TrackPopupMenu(menu, 0x0100 | 0x0002, pt.x, pt.y, 0, hwnd, None)
            u32.DestroyMenu(menu)
            if cmd and cmd in self._ids:
                self._on_action(self._ids[cmd])
        except Exception as e:
            log("tray menu err:", e)


# --------------------------- UI ---------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # إظهار سريع دفعة واحدة بعد البناء
        self.minimized_to_tray = False

        # blending 80% لنص أنعم (يقارب طلب 20% شفافية فوق الخلفية)
        BG="#0b0f14"; CARD="#131923"
        TEXT_BASE="#e6edf3"; SUB_BASE="#9fb0c0"
        def _blend_hex(fg, bg, alpha_fg=0.8):
            def _hex2rgb(h):
                h=h.strip().lstrip("#")
                if len(h)==3: h="".join(c*2 for c in h)
                return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))
            fr,fg_,fb=_hex2rgb(fg); br,bg_,bb=_hex2rgb(bg)
            r=int(alpha_fg*fr+(1-alpha_fg)*br); g=int(alpha_fg*fg_+(1-alpha_fg)*bg_); b=int(alpha_fg*fb+(1-alpha_fg)*bb)
            return f"#{r:02x}{g:02x}{b:02x}"
        TEXT=_blend_hex(TEXT_BASE, BG, 0.8); SUB=_blend_hex(SUB_BASE, BG, 0.8)

        self.lang = CFG.get("language","ar") if CFG.get("language") in ("ar","en") else "ar"
        self.s = STR[self.lang]
        self.configure(bg=BG); self.title(self.s["title"])
        self.geometry("1200x900");
        # Window/taskbar icon — app.ico ships next to the script (installed) or under assets/ (dev).
        try:
            _here = Path(__file__).resolve().parent
            for _ico in (_here / "app.ico", _here / "assets" / "app.ico"):
                if _ico.exists():
                    self.iconbitmap(default=str(_ico))
                    break
        except Exception:
            pass
        if CFG.get("fullscreen_on_start", True): self.attributes("-fullscreen", True)

        # خلفية النجوم
        self.bg = Starfield(self, bg=BG); self.bg.place(relx=0,rely=0,relwidth=1,relheight=1)
        self.tk.call('lower', self.bg._w)
        self.bg.bind("<Map>", lambda e: self.tk.call('lower', self.bg._w))
        self.bg.bind("<Configure>", lambda e: self.tk.call('lower', self.bg._w))

        # Styles
        style=ttk.Style(self)
        try: style.theme_use("clam")
        except: pass
        style.configure("Root.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 12))
        style.configure("Sub.TLabel", background=BG, foreground=SUB, font=("Segoe UI", 11))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 12))
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
        style.configure("Btn.TButton", background="#1d2633", foreground=TEXT, padding=10, borderwidth=0)
        style.map("Btn.TButton", background=[("active","#273245")])
        style.configure("Danger.TButton", background="#e34d4d", foreground="#230b0b", padding=10, borderwidth=0)
        style.map("Danger.TButton", background=[("active","#ff6d6d")])
        # Close/quit — neutral dark, distinct from the red Stop.
        style.configure("Close.TButton", background="#2a3340", foreground=TEXT, padding=10, borderwidth=0)
        style.map("Close.TButton", background=[("active","#3a4658")])
        # Compact window-control buttons for the top-right corner.
        style.configure("WinBg.TButton", background="#1d2633", foreground=TEXT,
                        padding=(10,4), borderwidth=0, font=("Segoe UI", 13))
        style.map("WinBg.TButton", background=[("active","#273245")])
        style.configure("WinClose.TButton", background="#7a2230", foreground="#ffe9ec",
                        padding=(12,4), borderwidth=0, font=("Segoe UI", 13, "bold"))
        style.map("WinClose.TButton", background=[("active","#e34d4d")])

        # ===== Modern dark theming for the remaining native-looking controls =====
        # accent + neutral surfaces used by sliders / combos / checks / entries
        ACCENT="#3b82f6"; ACCENT_HOVER="#60a5fa"; FIELD="#1b2330"; FIELD_BORDER="#2a3547"; TROUGH="#0e141d"
        # Sliders — flat dark trough + round accent knob (no more grey 90s scale)
        style.configure("DL.Horizontal.TScale", background=CARD, troughcolor=TROUGH,
                        bordercolor=CARD, lightcolor=ACCENT, darkcolor=ACCENT, borderwidth=0)
        style.map("DL.Horizontal.TScale",
                  background=[("active",CARD)],
                  troughcolor=[("active",TROUGH)],
                  lightcolor=[("active",ACCENT_HOVER)], darkcolor=[("active",ACCENT_HOVER)])
        # Comboboxes — dark field instead of the default white box
        style.configure("DL.TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=SUB, bordercolor=FIELD_BORDER, lightcolor=FIELD_BORDER,
                        darkcolor=FIELD_BORDER, borderwidth=1, padding=6, relief="flat")
        style.map("DL.TCombobox",
                  fieldbackground=[("readonly",FIELD),("focus",FIELD)],
                  foreground=[("readonly",TEXT)],
                  bordercolor=[("focus",ACCENT)], lightcolor=[("focus",ACCENT)], darkcolor=[("focus",ACCENT)],
                  arrowcolor=[("active",TEXT)])
        # the dropdown listbox is a classic Tk widget — color it via the option DB
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#0b0f14")
        self.option_add("*TCombobox*Listbox.borderWidth", 0)
        # Check buttons — dark, accent indicator
        style.configure("DL.TCheckbutton", background=CARD, foreground=TEXT, focuscolor=CARD,
                        indicatorcolor=FIELD, indicatorbackground=FIELD, padding=(2,4))
        style.map("DL.TCheckbutton",
                  background=[("active",CARD)],
                  foreground=[("active",TEXT)],
                  indicatorcolor=[("selected",ACCENT),("active",FIELD_BORDER)])
        # Entries — dark field
        style.configure("DL.TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=FIELD_BORDER, lightcolor=FIELD_BORDER, darkcolor=FIELD_BORDER,
                        borderwidth=1, padding=6, relief="flat")
        style.map("DL.TEntry", bordercolor=[("focus",ACCENT)], lightcolor=[("focus",ACCENT)],
                  darkcolor=[("focus",ACCENT)])
        # value-readout label that rides next to each slider
        style.configure("Val.Card.TLabel", background=CARD, foreground=ACCENT_HOVER,
                        font=("Segoe UI Semibold", 11))

        # هيكل
        self.outer=ttk.Frame(self, style="Root.TFrame"); self.outer.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.94, relheight=0.9)
        header=ttk.Frame(self.outer, style="Root.TFrame"); header.pack(fill="x", pady=(8,6))
        self.title_var = tk.StringVar(value=self.s["title"])
        ttk.Label(header, textvariable=self.title_var, style="Header.TLabel").pack(side="left", padx=12, pady=6)
        right=ttk.Frame(header, style="Root.TFrame"); right.pack(side="right")

        # أزرار التحكم بالنافذة في الزاوية العلوية اليمنى: إغلاق (✕) + الخلفية (▁)
        # Close is the rightmost corner control; background sits just left of it.
        self.close_btn = ttk.Button(right, text="✕", style="WinClose.TButton", command=self.quit_app)
        self.close_btn.pack(side="right", padx=(6,10))
        self.bg_btn = ttk.Button(right, text="▁", style="WinBg.TButton", command=self.go_background)
        self.bg_btn.pack(side="right", padx=(6,0))

        # عرض/نافذة
        self.view_var = tk.StringVar(value=("⛶ "+(self.s["windowed"] if self.attributes("-fullscreen") else self.s["fullscreen"])))
        ttk.Button(right, textvariable=self.view_var, style="Btn.TButton", command=self.toggle_view).pack(side="right", padx=(6,8))

        # اللغة
        box_lang=ttk.Frame(right, style="Root.TFrame"); box_lang.pack(side="right")
        ttk.Label(box_lang, text=self.s["lang"]+":", style="Sub.TLabel").pack(side="left", padx=(0,6))
        self.lang_cmb=ttk.Combobox(box_lang, values=["العربية","English"], state="readonly", width=9,
                                    style="DL.TCombobox")
        self.lang_cmb.set("العربية" if self.lang=="ar" else "English")
        self.lang_cmb.pack(side="left"); self.lang_cmb.bind("<<ComboboxSelected>>", self.on_lang)

        # البطارية
        box_batt=ttk.Frame(right, style="Root.TFrame"); box_batt.pack(side="right", padx=(8,12))
        ttk.Label(box_batt, text=self.s["battery"]+":", style="Sub.TLabel").pack(side="left", padx=(0,6))
        self.batt_canvas=tk.Canvas(box_batt, width=72, height=24, bg=BG, bd=0, highlightthickness=0); self.batt_canvas.pack(side="left")
        self.batt_txt=tk.StringVar(value="--%"); ttk.Label(box_batt, textvariable=self.batt_txt, style="Sub.TLabel").pack(side="left", padx=(6,0))

        # سطر فرعي
        self.subtitle_var = tk.StringVar(value=self.s["subtitle"])
        ttk.Label(self.outer, textvariable=self.subtitle_var, style="Sub.TLabel").pack(fill="x", padx=10, pady=(4,8))

        # بطاقة رئيسية
        self.card=ttk.Frame(self.outer, style="Card.TFrame"); self.card.pack(fill="both", expand=True, padx=20, pady=10)
        # ===== يد التحكم 3D + شريط المعاينة =====
        preview_frame = ttk.Frame(self.card, style="Card.TFrame")
        preview_frame.pack(padx=20, pady=(16, 8), fill="x")

        # يد 3D
        self.ctrl3d = Controller3D(preview_frame, controller_type="ps5", width=680, height=260, bg=CARD)
        self.ctrl3d.pack(fill="x", expand=True)
        # نقرة على اليد = منتقي الألوان الحي
        self.ctrl3d.on_click = self.pick_color
        _sc = CFG.get("shell_color", "white")
        if _sc not in ("white", "black", "red", "blue", "purple"): _sc = "white"
        if _sc != "white": self.ctrl3d.set_shell(_sc)

        # ===== لون اليد — فوق، بجانب اليد مباشرة =====
        self._shell_keys = ["white", "black", "red", "blue", "purple"]
        shell_names = {"ar": ["أبيض", "أسود", "أحمر", "أزرق", "بنفسجي"],
                       "en": ["White", "Midnight Black", "Cosmic Red", "Starlight Blue", "Galactic Purple"]}
        self._shell_names = shell_names
        shellbox = ttk.Frame(preview_frame, style="Card.TFrame")
        shellbox.place(relx=1.0, x=-14, y=10, anchor="ne")
        ttk.Label(shellbox, text=self.s["shell_color"], style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.shell_cmb = ttk.Combobox(shellbox, values=shell_names[self.lang], state="readonly",
                                      width=13, style="DL.TCombobox")
        self.shell_cmb.set(shell_names[self.lang][self._shell_keys.index(_sc)])
        self.shell_cmb.pack(side="left")
        self.shell_cmb.bind("<<ComboboxSelected>>", self._on_shell_change)

        # شريط المعاينة الصغير (لون فقط) — يعكس اللون المُطبّق فعليًا
        self.preview = tk.Frame(self.card, bg=CFG.get("color","#00aaff"), height=20, bd=0, highlightthickness=0, cursor="hand2")
        self.preview.pack(padx=20, pady=(0, 6), fill="x"); self.preview.pack_propagate(False)
        self.preview.bind("<Button-1>", self.pick_color)

        grid=ttk.Frame(self.card, style="Card.TFrame"); grid.pack(fill="x", padx=20, pady=6)
        ttk.Label(grid, text=self.s["mode"], style="Card.TLabel").grid(row=0,column=0,sticky="w",padx=(0,8))
        self.mode_disp=ttk.Combobox(grid, values=MODE_DISPLAY[self.lang], state="readonly", width=18, style="DL.TCombobox")
        self.mode_disp.set(code_to_display(self.lang, CFG.get("last_mode","Manual"))); self.mode_disp.grid(row=0,column=1,sticky="w")

        # Modern ttk sliders: ttk.Scale has no resolution/value-display, so we snap
        # to a step in the command and show the live value in an accent label.
        def _mk_slider(row, label_key, lo, hi, step, init):
            ttk.Label(grid, text=self.s[label_key], style="Card.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0,12), pady=(8,0))
            val = ttk.Label(grid, text=f"{init:.2f}".rstrip("0").rstrip("."), style="Val.Card.TLabel")
            val.grid(row=row, column=2, sticky="w", padx=(12,0), pady=(8,0))
            sc = ttk.Scale(grid, from_=lo, to=hi, orient="horizontal",
                           length=520, style="DL.Horizontal.TScale")
            sc.set(init); sc.grid(row=row, column=1, sticky="w", pady=(8,0))
            sc._step = step; sc._vlabel = val
            return sc
        self.sp   = _mk_slider(1, "interval",          0.1, 5.0, 0.1,  float(CFG.get("speed",1.0)))
        self.rb   = _mk_slider(2, "rainbow_brightness",0.2, 1.0, 0.05, float(CFG.get("rainbow_brightness",0.9)))
        self.duty = _mk_slider(3, "flash_duty",        0.1, 0.9, 0.05, float(CFG.get("flash_duty",0.5)))

        # ===== المنتقي الحي مدمج بجانب المنزلقات — لا نوافذ منبثقة =====
        self._build_live_picker(grid).grid(row=0, column=3, rowspan=4,
                                           sticky="ne", padx=(36, 0), pady=(0, 4))

        # ألوان سريعة + RGB/BGR
        qrow=ttk.Frame(self.card, style="Card.TFrame"); qrow.pack(anchor="w", padx=20, pady=(8,8))
        ttk.Label(qrow, text=self.s["quick"], style="Card.TLabel").pack(side="left", padx=(0,10))
        for hx in ["#ff3434","#22c55e","#3b82f6","#a855f7","#ffffff","#000000"]:
            c=tk.Canvas(qrow, width=30, height=20, bg=CARD, bd=0, highlightthickness=0); c.pack(side="left", padx=4)
            c.create_rectangle(2,2,28,18, fill=hx, outline=hx)
            c.bind("<Button-1>", lambda e, hx=hx: self.set_color_hex(hx))
        tk.Button(qrow, text=self.s["rgb_fix"], bd=0, highlightthickness=0, bg="#1d2633", fg=TEXT,
                  activebackground="#273245", activeforeground=TEXT,
                  command=self.toggle_bgr).pack(side="left", padx=10)

        # ملفات التعريف
        prow=ttk.Frame(self.card, style="Card.TFrame"); prow.pack(fill="x", padx=20, pady=(6,8))
        ttk.Label(prow, text=self.s["profiles"], style="Card.TLabel").pack(side="left", padx=(0,8))
        self.prof_var=tk.StringVar(value="Default")
        self.prof_cb=ttk.Combobox(prow, values=list(CFG.get("profiles",{}).keys()), state="normal", width=18, textvariable=self.prof_var, style="DL.TCombobox")
        self.prof_cb.pack(side="left")
        ttk.Button(prow, text=self.s["save_profile"], style="Btn.TButton", command=self.save_profile).pack(side="left", padx=8)
        ttk.Button(prow, text=self.s["delete_profile"], style="Btn.TButton", command=self.delete_profile).pack(side="left", padx=8)
        self.prof_cb.bind("<<ComboboxSelected>>", lambda e: self.load_profile(self.prof_var.get()))

        # خمول تلقائي
        opt=ttk.Frame(self.card, style="Card.TFrame"); opt.pack(fill="x", padx=20, pady=(6,10))
        self.as_var=tk.BooleanVar(value=bool(CFG.get("auto_sleep",{}).get("enabled", False)))
        ttk.Checkbutton(opt, text=self.s["auto_sleep"], variable=self.as_var, command=self.on_options, style="DL.TCheckbutton").grid(row=0,column=0,sticky="w",padx=(0,8))
        ttk.Label(opt, text=self.s["as_minutes"], style="Card.TLabel").grid(row=0,column=1, sticky="e")
        self.as_min=ttk.Entry(opt, width=5, style="DL.TEntry"); self.as_min.insert(0, CFG.get("auto_sleep",{}).get("minutes",30)); self.as_min.grid(row=0,column=2, padx=6)
        ttk.Label(opt, text=self.s["as_action"], style="Card.TLabel").grid(row=0,column=3, sticky="e")
        self.as_action=ttk.Combobox(opt, values=[self.s["as_off"], self.s["as_solid"]], state="readonly", width=8, style="DL.TCombobox")
        self.as_action.set(self.s["as_off"] if CFG.get("auto_sleep",{}).get("action","off")=="off" else self.s["as_solid"])
        self.as_action.grid(row=0,column=4, padx=6)


        # أزرار أساسية (الإغلاق والخلفية انتقلوا للزاوية العلوية اليمنى)
        btns=ttk.Frame(self.card, style="Card.TFrame"); btns.pack(fill="x", padx=20, pady=(6,14))
        ttk.Button(btns, text=self.s["stop"],  style="Danger.TButton", command=self.on_stop).pack(side="left", padx=6)
        ttk.Button(btns, text=self.s["pick_color"], style="Btn.TButton", command=self.pick_color).pack(side="left", padx=6)

        # حالة
        self.status_var=tk.StringVar(value=self.s["status_manual"])
        ttk.Label(self.outer, textvariable=self.status_var, style="Sub.TLabel").pack(fill="x", padx=14, pady=(6,0))

        # backend/engine
        self.backend=None; self.engine=None; self._ema=EMA(0.35)

        # Bind
        self.mode_disp.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())
        # ttk.Scale is continuous — snap to each slider's step, update its value label,
        # then feed the engine. Snapping keeps the persisted/displayed value clean.
        def _snap(sc, v):
            step = getattr(sc, "_step", 0.01)
            sv = round(round(float(v)/step)*step, 4)
            lbl = getattr(sc, "_vlabel", None)
            if lbl is not None:
                lbl.configure(text=f"{sv:.2f}".rstrip("0").rstrip("."))
            return sv
        self.sp.configure(command=lambda v: self.engine and self.engine.set_speed(_snap(self.sp, v)))
        self.rb.configure(command=lambda v: self.engine and self.engine.set_rb(_snap(self.rb, v)))
        self.duty.configure(command=lambda v: self.engine and self.engine.set_duty(_snap(self.duty, v)))

        # مفاتيح
        # Escape hides to background (recoverable by relaunching the shortcut),
        # not a silent quit — X is the real-quit affordance now.
        self.bind("<Escape>", lambda e: self.go_background())
        self.bind("<F11>", lambda e: self.toggle_view())
        
        # تعامل مع إغلاق النافذة
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # عرض فوري بعد الإعداد
        self.update_idletasks(); self.deiconify()
        self.bg.start()

        # رسم يد التحكم 3D بعد ظهور النافذة
        self.after(100, lambda: self.ctrl3d.redraw() if hasattr(self, 'ctrl3d') else None)

        # ===== أيقونة شريط النظام (تحت يمين): بروفايلات سريعة + إطفاء + خروج =====
        self._tray_q = queue.Queue()
        def _tray_menu():
            ar = self.lang == "ar"
            items = [("open", "فتح البرنامج" if ar else "Open"), ("sep", None)]
            for name in list(CFG.get("profiles", {}).keys())[:8]:
                items.append(("profile:" + name, ("🎮 " + name)))
            items += [("sep", None),
                      ("off", "إطفاء الإضاءة" if ar else "Lightbar off"),
                      ("quit", "خروج" if ar else "Quit")]
            return items
        _ico = None
        try:
            _here = Path(__file__).resolve().parent
            for _p in (_here / "app.ico", _here / "assets" / "app.ico"):
                if _p.exists(): _ico = str(_p); break
        except Exception: pass
        self.tray = TrayIcon("PS5 LED", _ico, _tray_menu, self._tray_q.put)

        # ابدأ الاتصال
        self.after(50, self.post_init)

        # تحديث البطارية دوريًا
        self.after(600, self.poll_batt)
        self.after(800, self._check_restore_signal)

        def _restore_cb():
            try:
                self.after(0, self.restore_from_tray)
            except Exception:
                try:
                    self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))
                except Exception:
                    pass
        threading.Thread(target=lambda: _wait_event_loop(_restore_cb), daemon=True).start()


    # ---- helpers ----
    def post_init(self):
        try:
            self.backend=Backend(prefer=CFG.get("backend","auto"))
            ok=self.backend.connect()
            if not ok:
                messagebox.showerror("DualLED", self.s["ctrl_not_found"]); return
            self.engine=Engine(self.backend); self.engine.start()
            log("controller detected:", self.backend.kind)
            # مزامنة فورية
            self.engine.set_color(hex_to_rgb(CFG.get("color","#00aaff")))
            self.after(50, self.sync_preview_tick)
        except Exception as e:
            log("post_init err:", e)

    def _handle_tray_action(self, key):
        try:
            if key == "open":
                self.deiconify(); self.lift(); self.focus_force()
                self.minimized_to_tray = False
            elif key == "off":
                if self.engine:
                    self.engine.set_mode("Manual")
                    self.engine.set_color((0, 0, 0))
                self.mode_disp.set(code_to_display(self.lang, "Manual"))
                self.preview.configure(bg="#000000")
            elif key == "quit":
                self.quit_app()
            elif key.startswith("profile:"):
                name = key.split(":", 1)[1]
                if name in CFG.get("profiles", {}):
                    self.prof_var.set(name)
                    self.load_profile(name)
                    if self.engine:
                        self.mode_disp.set(code_to_display(self.lang, self.engine.mode))
        except Exception as e:
            log("tray action err:", e)

    def _ui_idle(self):
        """True = لا ترسم: النافذة مخفية/مصغّرة أو التطبيق كامل فاقد تركيز الإدخال
        (مثال: داخل لعبة ملء الشاشة والنافذة خلفها) — المحرك يواصل عمله في خيطه."""
        try:
            if self.state() in ("withdrawn", "iconic"):
                return True
            return self.focus_displayof() is None
        except Exception:
            return False

    def sync_preview_tick(self):
        hidden = False
        try:
            try:
                while True:
                    self._handle_tray_action(self._tray_q.get_nowait())
            except queue.Empty:
                pass
            flush_cfg()   # يلتقط آخر قيمة من الحفظ المخنوق
            hidden = self._ui_idle()
            if self.engine and not hidden:
                with self.engine._ol:
                    out = self.engine.out
                hx = rgb_to_hex(out)
                if self.preview.cget('bg') != hx:
                    self.preview.configure(bg=hx)
                # --- تزامن 100% مع يد التحكم المعروضة ---
                if hasattr(self, 'ctrl3d'):
                    self.ctrl3d.set_led_color(*out)
        except Exception: pass
        self.after(400 if hidden else 33, self.sync_preview_tick)

    def _on_shell_change(self, event=None):
        idx = self.shell_cmb.current()
        if idx < 0: return
        key = self._shell_keys[idx]
        CFG["shell_color"] = key; save_cfg(CFG)
        if hasattr(self, 'ctrl3d'): self.ctrl3d.set_shell(key)

    def set_color_hex(self, hx):
        self.preview.configure(bg=hx)
        rgb = hex_to_rgb(hx)
        if self.engine:
            # اختيار لون = قصدك لون ثابت → تحويل تلقائي لوضع "يدوي" لو كان وضع متحرك
            if self.engine.mode != "Manual":
                self.engine.set_mode("Manual")
                self.mode_disp.set(code_to_display(self.lang, "Manual"))
                if hasattr(self, 'ctrl3d'): self.ctrl3d.set_mode("Manual")
                self.status_var.set(self.s["status_manual"])
            self.engine.set_color(rgb)
        # recolor the controller widget IMMEDIATELY (don't wait for the 33ms poll)
        if hasattr(self, 'ctrl3d'): self.ctrl3d.set_led_color(*rgb)

    def pick_color(self, e=None):
        """المنتقي مدمج في النافذة — النقر يومض إطاره للفت النظر إليه."""
        self._flash_picker()

    def _flash_picker(self, n=4):
        f = getattr(self, "_picker_frame", None)
        if not f: return
        def step(i):
            try:
                f.configure(highlightbackground="#3b82f6" if i % 2 == 0 else "#2a3547")
                if i < n: self.after(160, lambda: step(i + 1))
            except Exception: pass
        step(0)

    def _build_live_picker(self, parent):
        """لوحة ألوان حية داخل الواجهة — أي حركة تُطبَّق على اليد فورًا (بدون OK)."""
        CARD = "#131923"
        frame = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground="#2a3547")
        self._picker_frame = frame

        orig = CFG.get("color", "#00aaff")
        r0, g0, b0 = hex_to_rgb(orig)
        h0, s0, v0 = colorsys.rgb_to_hsv(r0 / 255, g0 / 255, b0 / 255)
        st = {"h": h0, "s": s0, "v": v0}
        GW, GH, Z = 60, 44, 4                    # شبكة التدرج × التكبير = 240×176
        SVW, SVH, HW = GW * Z, GH * Z, 26

        sv = tk.Canvas(frame, width=SVW, height=SVH, bg="#000000", bd=0,
                       highlightthickness=1, highlightbackground="#2a3547", cursor="crosshair")
        sv.grid(row=0, column=0, padx=(10, 6), pady=10)
        hue = tk.Canvas(frame, width=HW, height=SVH, bd=0,
                        highlightthickness=1, highlightbackground="#2a3547", cursor="sb_v_double_arrow")
        hue.grid(row=0, column=1, padx=(0, 10), pady=10)

        for y in range(SVH):
            r_, g_, b_ = colorsys.hsv_to_rgb(y / max(1, SVH - 1), 1.0, 1.0)
            hue.create_line(0, y, HW, y, fill=f"#{int(r_*255):02x}{int(g_*255):02x}{int(b_*255):02x}")
        hue_mark = hue.create_rectangle(0, 0, HW, 3, outline="#ffffff", width=2)

        holder = {"img": None}
        def render_sv():
            base = tk.PhotoImage(width=GW, height=GH)
            h = st["h"]
            for y in range(GH):
                v = 1.0 - y / (GH - 1)
                row = "{" + " ".join(
                    "#%02x%02x%02x" % tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, x / (GW - 1), v))
                    for x in range(GW)) + "}"
                base.put(row, to=(0, y))
            big = base.zoom(Z, Z)
            holder["img"] = big                   # مرجع حي وإلا يمسحه جامع القمامة
            sv.delete("grad")
            sv.create_image(0, 0, anchor="nw", image=big, tags="grad")
            sv.tag_raise("mark")

        sv.create_oval(0, 0, 0, 0, outline="#ffffff", width=2, tags="mark")

        cur_hex = tk.StringVar(value=orig)
        bar = tk.Frame(frame, bg=CARD); bar.grid(row=1, column=0, columnspan=2, sticky="we", padx=10, pady=(0, 10))
        swatch = tk.Canvas(bar, width=40, height=22, bd=0, highlightthickness=1, highlightbackground="#2a3547")
        swatch.pack(side="left")
        sw_rect = swatch.create_rectangle(0, 0, 40, 22, fill=orig, outline="")
        tk.Label(bar, textvariable=cur_hex, bg=CARD, fg="#9fb0c0",
                 font=("Consolas", 10)).pack(side="left", padx=8)

        def sync_marks():
            x = st["s"] * (SVW - 1); y = (1.0 - st["v"]) * (SVH - 1)
            sv.coords("mark", x - 6, y - 6, x + 6, y + 6)
            hy = st["h"] * (SVH - 1)
            hue.coords(hue_mark, 0, hy - 1, HW, hy + 2)

        def apply_live():
            r_, g_, b_ = (int(c * 255) for c in colorsys.hsv_to_rgb(st["h"], st["s"], st["v"]))
            hx = f"#{r_:02x}{g_:02x}{b_:02x}"
            cur_hex.set(hx)
            swatch.itemconfigure(sw_rect, fill=hx)
            self.set_color_hex(hx)                # ← مباشر: المحرك + اليد الفعلية + الرسم
            sync_marks()

        def on_sv(ev):
            st["s"] = min(1.0, max(0.0, ev.x / (SVW - 1)))
            st["v"] = min(1.0, max(0.0, 1.0 - ev.y / (SVH - 1)))
            apply_live()

        def on_hue(ev):
            st["h"] = min(1.0, max(0.0, ev.y / (SVH - 1)))
            render_sv(); apply_live()

        sv.bind("<Button-1>", on_sv); sv.bind("<B1-Motion>", on_sv)
        hue.bind("<Button-1>", on_hue); hue.bind("<B1-Motion>", on_hue)

        render_sv(); sync_marks()
        return frame

    def toggle_bgr(self):
        CFG["bgr_swap"]=not bool(CFG.get("bgr_swap", False)); save_cfg(CFG)
        if self.engine: self.backend.set_color(*self.engine.color)

    def on_stop(self):
        if self.engine:
            self.engine.set_mode("Manual")
            self.backend.set_color(*self.engine.color)
            self.status_var.set(self.s["status_manual"])

    def on_mode_change(self):
        if not self.engine: return
        disp = self.mode_disp.get()
        code = display_to_code(self.lang, disp)
        self.engine.set_mode(code)
        if hasattr(self, 'ctrl3d'): self.ctrl3d.set_mode(code)  # widget glow signature follows mode
        v=float(self.sp.get()); b=float(self.rb.get())
        if code=="Manual": self.status_var.set(self.s["status_manual"])
        elif code=="Sequence": self.status_var.set(self.s["status_sequence"].format(v=v))
        elif code=="Random": self.status_var.set(self.s["status_random"].format(v=v))
        elif code=="Rainbow": self.status_var.set(self.s["status_rainbow"].format(v=v,b=b))
        elif code=="Pulse": self.status_var.set(self.s["status_pulse"].format(v=v))
        elif code=="Breathing": self.status_var.set(self.s["status_breath"])
        elif code=="Heartbeat": self.status_var.set("Heartbeat")
        elif code=="Wave": self.status_var.set(self.s["status_wave"])
        elif code=="Gradient": self.status_var.set(self.s["status_grad"])
        elif code=="Battery": self.status_var.set(self.s["status_batt"])

    def toggle_view(self):
        new = not self.attributes("-fullscreen")
        self.attributes("-fullscreen", new); CFG["fullscreen_on_start"]=new; save_cfg(CFG)
        self.view_var.set("⛶ "+(self.s["windowed"] if new else self.s["fullscreen"]))

    def on_lang(self, e=None):
        new_lang = "ar" if self.lang_cmb.get().startswith("الع") else "en"
        CFG["language"]=new_lang; save_cfg(CFG)
        
        # حفظ الوضع الحالي قبل تغيير اللغة
        cur_code = display_to_code(self.lang, self.mode_disp.get()) if self.mode_disp.get() in MODE_DISPLAY[self.lang] else CFG.get("last_mode","Manual")
        
        self.lang=new_lang; self.s=STR[new_lang]
        
        # تحديث كافة النصوص والعناصر
        self.title(self.s["title"])
        self.title_var.set(self.s["title"])
        self.subtitle_var.set(self.s["subtitle"])
        self.view_var.set("⛶ "+(self.s["windowed"] if self.attributes("-fullscreen") else self.s["fullscreen"]))
        
        # تحديث قائمة الأوضاع
        self.mode_disp.configure(values=MODE_DISPLAY[self.lang])
        self.mode_disp.set(code_to_display(self.lang, cur_code))
        
        # تحديث جميع العناوين والنصوص
        self.update_all_labels()

        # قائمة لون اليد: القيم بلغة جديدة مع الإبقاء على الاختيار الحالي
        if hasattr(self, "shell_cmb"):
            cur = CFG.get("shell_color", "white")
            if cur not in self._shell_keys: cur = "white"
            self.shell_cmb.configure(values=self._shell_names[self.lang])
            self.shell_cmb.set(self._shell_names[self.lang][self._shell_keys.index(cur)])
        # سطر الحالة بلغة جديدة
        try: self.on_mode_change()
        except Exception: pass
        
    def update_all_labels(self):
        """تحديث جميع النصوص في الواجهة بعد تغيير اللغة"""
        try:
            # تحديث النصوص في الإطار الرئيسي
            self._update_widget_tree(self.outer)
            
            # تحديث عناصر خاصة
            if hasattr(self, 'as_action'):
                self.as_action.configure(values=[self.s["as_off"], self.s["as_solid"]])
                current = self.as_action.get()
                if "Off" in current or "إطفاء" in current:
                    self.as_action.set(self.s["as_off"])
                else:
                    self.as_action.set(self.s["as_solid"])
                    
        except Exception as e:
            log("update_all_labels err:", e)
    
    def _update_widget_tree(self, widget):
        """تحديث شجرة العناصر بشكل متكرر"""
        try:
            # تحديث العنصر الحالي
            if isinstance(widget, ttk.Label):
                text = widget.cget("text")
                # قاموس للترجمات
                translations = {
                    ("الوضع", "Mode"): self.s["mode"],
                    ("السرعة", "Speed", "Interval"): self.s["interval"], 
                    ("سطوع قوس قزح", "Rainbow Brightness"): self.s["rainbow_brightness"],
                    ("نسبة الوميض", "Flash Duty"): self.s["flash_duty"],
                    ("ألوان سريعة", "Quick Colors"): self.s["quick"],
                    ("ملفات التعريف", "Profiles"): self.s["profiles"],
                    ("خمول تلقائي", "Auto Sleep"): self.s["auto_sleep"],
                    ("دقائق", "Minutes"): self.s["as_minutes"],
                    ("الإجراء", "Action"): self.s["as_action"],
                    ("اللغة", "Language"): self.s["lang"],
                    ("البطارية", "Battery"): self.s["battery"],
                    ("لون اليد", "Shell Color"): self.s["shell_color"]
                }
                
                for keys, value in translations.items():
                    if any(key in text for key in keys):
                        # إضافة النقطتين إذا كانت موجودة
                        if ":" in text:
                            widget.configure(text=value + ":")
                        else:
                            widget.configure(text=value)
                        break
                        
            elif isinstance(widget, tk.Button):
                text = widget.cget("text")
                if "تصحيح RGB" in text or "RGB" in text or "BGR" in text:
                    widget.configure(text=self.s["rgb_fix"])
                    
            elif isinstance(widget, ttk.Button):
                text = widget.cget("text")
                button_translations = {
                    ("حفظ", "Save"): self.s["save_profile"],
                    ("حذف", "Delete"): self.s["delete_profile"],
                    ("إيقاف", "Stop"): self.s["stop"],
                    ("اختيار لون", "Pick Color"): self.s["pick_color"],
                    ("تشغيل في الخلفية", "Run in background"): self.s["background"],
                    ("إغلاق", "Close"): self.s["close"]
                }
                
                for keys, value in button_translations.items():
                    if any(key in text for key in keys):
                        widget.configure(text=value)
                        break
                        
            elif isinstance(widget, (tk.Checkbutton, ttk.Checkbutton)):
                text = widget.cget("text")
                checkbutton_translations = {
                    ("خمول تلقائي", "Auto Sleep"): self.s["auto_sleep"]
                }
                
                for keys, value in checkbutton_translations.items():
                    if any(key in text for key in keys):
                        widget.configure(text=value)
                        break
            
            # معالجة العناصر الفرعية
            try:
                for child in widget.winfo_children():
                    self._update_widget_tree(child)
            except Exception:
                pass
                
        except Exception as e:
            log(f"_update_widget_tree err for {type(widget)}: {e}")

    # ---- Profiles ----
    def _after_profile_load(self):
        if self.engine and hasattr(self, "ctrl3d"):
            self.ctrl3d.set_mode(self.engine.mode)
            self.mode_disp.set(code_to_display(self.lang, self.engine.mode))

    def load_profile(self, name):
        profs = CFG.get("profiles",{})
        snap = profs.get(name)
        if not snap or not self.engine: return
        self.engine.load_from(snap)
        self.sp.set(self.engine.speed); self.rb.set(self.engine.rb); self.duty.set(self.engine.duty)
        self.preview.configure(bg=rgb_to_hex(self.engine.color))
        self._after_profile_load()

    def save_profile(self):
        name = self.prof_var.get().strip() or "Custom"
        CFG.setdefault("profiles", {})
        if not self.engine: return
        CFG["profiles"][name] = self.engine.snapshot()
        save_cfg(CFG)
        self.prof_cb.configure(values=list(CFG["profiles"].keys()))
        self.prof_cb.set(name)

    def delete_profile(self):
        name = self.prof_var.get().strip()
        if name and name in CFG.get("profiles",{}) and name!="Default":
            CFG["profiles"].pop(name, None); save_cfg(CFG)
            self.prof_cb.configure(values=list(CFG.get("profiles",{}).keys()))
            self.prof_cb.set("Default")

    # ---- Options ----
    def on_options(self):
        CFG["auto_sleep"]={"enabled": bool(self.as_var.get()),
                           "minutes": int(self.as_min.get() or 30),
                           "action": "off" if self.as_action.get() in (self.s["as_off"], "Off") else "solid"}
        save_cfg(CFG)

    # ---- Battery ----
    def draw_batt(self, p, ch):
        if self._ui_idle():
            return   # لا رسم أثناء الخمول — التنبيهات (poll) مستمرة
        W,H=64,18; x0,y0=2,3
        self.batt_canvas.delete("all")
        self.batt_canvas.create_rectangle(x0,y0,x0+W,y0+H, outline="#e6edf3", width=2)
        self.batt_canvas.create_rectangle(x0+W,y0+H*0.35,x0+W+6,y0+H*0.65, fill="#e6edf3", outline="#e6edf3")
        p = 0 if p is None else max(0,min(100,int(p)))
        w = int((W-4)*(p/100.0))
        col="#22c55e" if p>=60 else ("#f59e0b" if p>=30 else "#ef4444")
        self.batt_canvas.create_rectangle(x0+2,y0+2,x0+2+w,y0+H-2, outline=col, fill=col)
        if ch:
            cx,cy=x0+W//2,y0+H//2
            pts=[cx-8,cy-4,cx-2,cy-4,cx-6,cy+4,cx+8,cy-2,cx+2,cy-2,cx+6,cy-10]
            self.batt_canvas.create_polygon(pts, fill="#ffffff", outline="")

    def poll_batt(self):
        # تحديث كل ثانيتين
        try:
            if not hasattr(self, "_bema"): self._bema=EMA(0.35)
            if self.backend:
                p,ch = self.backend.get_battery()
                p2 = self._bema.update(p)
                self.batt_txt.set("--%" if p2 is None else f"{p2}%")
                self.draw_batt(p2, ch)
        except Exception as e:
            log("battery ui err:", e)
        self.after(2000, self.poll_batt)
    
    # ---- Minimize to Tray ----
    def on_closing(self):
        """زر X يغلق البرنامج نهائيًا. للخلفية، استخدم زر 'تشغيل في الخلفية'."""
        # The window X is a real quit now — no hidden ghost process. Hiding to the
        # background is an explicit, opt-in action via the dedicated button. This
        # removes the invisible-tray zombie that forced re-launching the shortcut.
        self.quit_app()
    
    def go_background(self):
        """إخفاء النافذة مع إبقاء المحرك يقود الإضاءة — بديل اختصار الخلفية المنفصل."""
        # status hint, then hide to tray. The engine thread keeps running.
        try:
            self.status_var.set(self.s.get("background", "Run in background"))
        except Exception:
            pass
        self.minimize_to_tray()

    def quit_app(self):
        """إغلاق فعلي: إيقاف المحرك وإغلاق الاتصال ثم الخروج (يتجاوز التصغير للـtray)."""
        # Stop the engine thread, then close the HID backend, then destroy the
        # window. Each step is best-effort so a failing one can't trap the app.
        try:
            if self.engine is not None:
                self.engine.stop_evt.set()
        except Exception as e:
            log("quit: engine stop err:", e)
        try:
            if self.backend is not None:
                self.backend.close()
        except Exception as e:
            log("quit: backend close err:", e)
        try:
            release_slot_lock()
        except Exception:
            pass
        try:
            if getattr(self, "tray", None): self.tray.destroy()
        except Exception:
            pass
        try: flush_cfg()
        except Exception: pass
        log("App quit by user")
        self.destroy()

    def minimize_to_tray(self):
        """تصغير النافذة للشريط السفلي (مخفية)"""
        self.withdraw()
        self.minimized_to_tray = True
        # يمكن إضافة أيقونة في الشريط السفلي هنا إذا لزم الأمر
        log("App minimized to tray")
    
    def restore_from_tray(self):
        """استعادة النافذة من الشريط السفلي"""
        if self.minimized_to_tray:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.minimized_to_tray = False
            log("App restored from tray")

    def _check_restore_signal(self):
        try:
            sig = CONFIG_DIR / "restore.signal"
            if sig.exists():
                try:
                    sig.unlink()
                except Exception:
                    pass
                # حتى لو النافذة مخفية، نحاول إظهارها
                try:
                    self.restore_from_tray()
                except Exception:
                    try:
                        self.deiconify(); self.lift(); self.focus_force()
                    except Exception:
                        pass
        finally:
            # فحص كل ثانية
            try:
                self.after(1000, self._check_restore_signal)
            except Exception:
                pass

# --------------------------- Main ---------------------------

def main():
    # منع تعدد النسخ (Mutex ثابت يمنع أي نسخة ثانية)
    first = True
    try:
        if os.name == 'nt':
            first = _acquire_global_mutex()
    except Exception:
        first = True
    if not first:
        _secondary_instance_restore_and_exit()
        return False
    # طبقة إضافية بالقفل على الملفات
    if _instance_already_running():
        _signal_restore_request()
        return False
    # Clamp config-supplied count so a tampered/corrupt config can't flood the
    # lock dir with thousands of slot files (config.json is treated as untrusted).
    try:
        max_instances = max(1, min(8, int(CFG.get("max_instances", 1) or 1)))
    except (TypeError, ValueError):
        max_instances = 1
    if not acquire_slot_lock(max_instances):
        _secondary_instance_restore_and_exit()
        return False
    atexit.register(release_slot_lock)
    return True

def run_main():
    """تشغيل التطبيق مع معالجة المعاملات (سياق أصلي)"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true", help="run without UI (uses last settings)")
    parser.add_argument("--stop-after", type=float, default=None, help="auto stop after N minutes (background)")
    parser.add_argument("--off-on-exit", action="store_true", help="turn off lightbar when exiting (background)")
    parser.add_argument("--keep-on-exit", action="store_true", help="keep the lightbar color when the background process exits")
    parser.add_argument("--stop", action="store_true", help="signal a running --background instance to stop, then exit")
    args = parser.parse_args()

    if args.stop:
        # Tell a running background instance to shut down (used by the Stop shortcut).
        try:
            STOP_SIGNAL.write_text("1", encoding="utf-8")
            log("CLI: stop signal written")
        except Exception as e:
            log("CLI: stop signal failed:", e)
        return

    if args.background:
        # Background is invisible, so default to cleaning up the lightbar on exit
        # unless the user explicitly asks to keep it.
        off = not args.keep_on_exit if not args.off_on_exit else True
        run_background(off_on_exit=off, stop_after_min=args.stop_after)
        return

    try:
        App().mainloop()
    except Exception as e:
        log("FATAL:", e)

if __name__ == "__main__":
    if main():
        run_main()
