#!/usr/bin/python3
# GL-E5800 screen apps v3 — rendu Pillow -> RGB565 -> /dev/fb0 + tactile
# Tap = bascule dashboard/clock ; appui long (>1.2s) = quitte
import os, sys, time, subprocess, math, datetime, mmap, signal, threading, struct

W, H = 240, 320
FB = "/dev/fb0"
FONT_MONO = "/opt/screenapps/fonts/default_mono_medium.ttf"

from PIL import Image, ImageDraw, ImageFont

_fonts = {}
def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_MONO, size)
    return _fonts[size]

def run_command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return None

_prev = {"rx": None, "tx": None, "t": time.time()}
_rates = [0.0, 0.0]

def get_stats():
    s = {}
    route = run_command(["ip", "route", "show", "default"])
    route_fields = route.stdout.split() if route and route.returncode == 0 else []
    s["wan"] = route_fields[2] if len(route_fields) >= 3 else "?"

    ping = run_command(["ping", "-c", "1", "-W", "2", "1.1.1.1"])
    s["net"] = "UP" if ping and ping.returncode == 0 else "DOWN"

    rx = tx = 0
    try:
        netdev_lines = open("/proc/net/dev", encoding="ascii").read().splitlines()
    except OSError:
        netdev_lines = []
    for line in netdev_lines:
        if ":" not in line:
            continue
        iface, data = line.split(":", 1)
        if iface.strip().startswith(("eth", "wwan", "usb", "rmnet")):
            fields = data.split()
            try:
                rx += int(fields[0]); tx += int(fields[8])
            except (ValueError, IndexError):
                pass

    now = time.time()
    dt = max(now - _prev["t"], 0.001)
    if _prev["rx"] is not None:
        _rates[0] = max(rx - _prev["rx"], 0) / dt
        _rates[1] = max(tx - _prev["tx"], 0) / dt
    _prev["rx"], _prev["tx"], _prev["t"] = rx, tx, now
    s["rate"] = _rates

    mem_total = mem_available = 0
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    s["mem"] = str(int(100 * (mem_total - mem_available) / mem_total)) if mem_total else "0"
    s["load"] = open("/proc/loadavg", encoding="ascii").read().split()[0]
    return s

def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.1f}TB"

class FBOut:
    def __init__(self):
        self.fd = os.open(FB, os.O_RDWR)
        self.mm = mmap.mmap(self.fd, W * H * 2)

    def show(self, img):
        rgb = img.convert("RGB").tobytes()
        out = bytearray(W * H * 2)
        j = 0
        for i in range(0, len(rgb), 3):
            v = ((rgb[i] & 0xF8) << 8) | ((rgb[i+1] & 0xFC) << 3) | (rgb[i+2] >> 3)
            out[j] = v & 0xFF
            out[j+1] = v >> 8
            j += 2
        self.mm.seek(0)
        self.mm.write(bytes(out))

    def close(self):
        self.mm.close()
        os.close(self.fd)

BG = (10, 12, 24)
PANEL = (28, 32, 54)
HEAD = (0, 200, 255)
TXT = (235, 235, 245)
DIM = (120, 125, 145)
GREEN = (60, 220, 90)
RED = (230, 60, 60)
CYAN = (80, 200, 255)
ORANGE = (255, 170, 80)
YELLOW = (255, 190, 60)

class Touch:
    """Multitouch type B sur /dev/input/event0.
       callbacks: tap(x,y), longpress(x,y)"""
    def __init__(self, on_tap, on_long):
        self.on_tap = on_tap
        self.on_long = on_long
        self.daemon = True
        self.stop = False
        self.x = self.y = 0
        self.down = False
        self.t_down = 0
        threading.Thread(target=self.loop).start()

    def loop(self):
        try:
            fd = os.open("/dev/input/event0", os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return
        tracking = None
        while not self.stop:
            try:
                data = os.read(fd, 24)
            except BlockingIOError:
                # timeout appui long
                if self.down and time.time() - self.t_down > 1.2:
                    self.down = False
                    self.on_long(self.x, self.y)
                time.sleep(0.03)
                continue
            if not data or len(data) < 24:
                if self.down and time.time() - self.t_down > 1.2:
                    self.down = False
                    self.on_long(self.x, self.y)
                time.sleep(0.03)
                continue
            _, _, typ, code, val = struct.unpack("llHHi", data)
            if typ == 3 and code == 57:      # ABS_MT_TRACKING_ID
                tracking = val
            elif typ == 3 and code == 53:    # ABS_MT_POSITION_X
                self.x = max(0, min(W-1, val))
            elif typ == 3 and code == 54:    # ABS_MT_POSITION_Y
                self.y = max(0, min(H-1, val))
            elif typ == 1 and code == 330:   # BTN_TOUCH
                if val == 1:
                    self.down = True
                    self.t_down = time.time()
                elif val == 0:
                    dur = time.time() - self.t_down
                    self.down = False
                    if dur <= 1.2:
                        self.on_tap(self.x, self.y)

BG2 = (8, 10, 20)
class App:
    def __init__(self):
        self.fb = FBOut()
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.mode = "dashboard"
        self.running = True
        self.flash_until = 0
        self.touch = Touch(self.tap, self.longpress)
        signal.signal(signal.SIGTERM, lambda *_: self.quit())

    def quit(self):
        self.running = False

    def tap(self, x, y):
        self.mode = "clock" if self.mode == "dashboard" else "dashboard"
        self.flash_until = time.time() + 0.4

    def longpress(self, x, y):
        self.running = False

    def panel(self, y, h=44):
        self.d.rounded_rectangle((12, y, W-12, y+h), radius=8, fill=PANEL)

    def txt(self, s, x, y, size=16, col=TXT):
        self.d.text((x, y), s, font=font(size), fill=col)

    def dashboard(self):
        st = get_stats()
        d = self.d
        d.rectangle((0, 0, W, H), fill=BG)
        self.txt("GL-E5800 DASHBOARD", 14, 10, 18, HEAD)
        d.line((12, 34, W-12, 34), fill=HEAD)

        self.panel(46)
        netcol = GREEN if st["net"] == "UP" else RED
        self.txt("Internet", 22, 52, 14, DIM)
        self.txt(st["net"], 150, 48, 26, netcol)
        self.txt(f"GW {st['wan']}", 22, 74, 13, DIM)

        self.panel(100)
        dn, up = st["rate"]
        self.txt("DOWN", 22, 108, 14, DIM)
        self.txt(human(dn) + "/s", 90, 104, 18, CYAN)
        self.txt("UP", 22, 130, 14, DIM)
        self.txt(human(up) + "/s", 90, 126, 18, ORANGE)

        self.panel(154, h=56)
        mem = int(st["mem"])
        self.txt(f"MEM {mem}%", 22, 162, 18)
        self.txt(f"LOAD {st['load']}", 130, 162, 18)
        d.rounded_rectangle((22, 186, W-34, 192), radius=3, fill=(40, 45, 70))
        mw = min(int((W-56) * mem / 100), W-56)
        d.rounded_rectangle((22, 186, 22+mw, 192), radius=3, fill=YELLOW)
        self.txt(f"TOTAL {human(_prev['tx']+_prev['rx'])}", 22, 196, 13, DIM)

        now = datetime.datetime.now()
        t = now.strftime("%H:%M:%S")
        f = font(30)
        tw = d.textlength(t, font=f)
        d.text(((W-tw)//2, 222), t, font=f, fill=(200, 205, 230))
        dd = now.strftime("%d/%m %a")
        dw = d.textlength(dd, font=font(14))
        d.text(((W-dw)//2, 258), dd, font=font(14), fill=DIM)

        d.line((12, H-38, W-12, H-38), fill=(40, 45, 70))
        self.txt("TAP: mode | HOLD: quitter", 30, H-28, 13, (90, 95, 115))

    def clock(self):
        d = self.d
        d.rectangle((0, 0, W, H), fill=BG2)
        now = datetime.datetime.now()
        cx, cy = W // 2, 140
        d.ellipse((cx-92, cy-92, cx+92, cy+92), outline=(35, 40, 65), width=2)
        for i in range(12):
            a = math.radians(i * 30 - 90)
            x1, y1 = cx + 84*math.cos(a), cy + 84*math.sin(a)
            x2, y2 = cx + 78*math.cos(a), cy + 78*math.sin(a)
            d.line((x1, y1, x2, y2), fill=(110, 160, 220), width=2)
        def hand(deg, ln, w, col):
            a = math.radians(deg - 90)
            d.line((cx, cy, cx + ln*math.cos(a), cy + ln*math.sin(a)), fill=col, width=w)
        hand((now.hour % 12 + now.minute/60) * 30, 45, 4, TXT)
        hand(now.minute * 6, 68, 3, HEAD)
        hand(now.second * 6, 76, 1, ORANGE)
        d.ellipse((cx-3, cy-3, cx+3, cy+3), fill=HEAD)
        t = now.strftime("%H:%M:%S")
        f = font(20)
        tw = d.textlength(t, font=f)
        d.text(((W-tw)//2, 250), t, font=f, fill=(200, 205, 230))
        dd = now.strftime("%A %d %B")
        fw = font(14)
        dw = d.textlength(dd, font=fw)
        d.text(((W-dw)//2, 278), dd, font=fw, fill=DIM)

    def run(self):
        while self.running:
            if os.path.exists("/tmp/screenapp.mode"):
                try:
                    with open("/tmp/screenapp.mode") as f:
                        m = f.read().strip()
                    if m in ("dashboard", "clock"):
                        self.mode = m
                except OSError:
                    pass
            if os.path.exists("/tmp/screenapp.quit"):
                break
            if self.mode == "dashboard":
                self.dashboard()
            else:
                self.clock()
            if time.time() < self.flash_until:
                self.d.rectangle((W-40, 0, W, 24), fill=GREEN)
            self.fb.show(self.img)
            time.sleep(1 if self.mode == "clock" else 2)
        try:
            os.unlink("/tmp/screenapp.quit")
        except OSError:
            pass
        self.touch.stop = True
        self.fb.close()

if __name__ == "__main__":
    App().run()
