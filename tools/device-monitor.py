#!/usr/bin/env python3
"""
device-monitor.py — télémétrie matérielle du routeur nomade (batterie + thermique).

Lit l'état batterie via le MCU (`ubus call mcu status`) et les capteurs thermiques via
`/sys/class/thermal`. Journalise, résume, et alerte sur seuils (batterie faible, surchauffe,
anomalie batterie). Idéal pour un appareil sur batterie/portable.

  python3 tools/device-monitor.py --once      # un relevé
  python3 tools/device-monitor.py --json       # JSON
  python3 tools/device-monitor.py --watch       # boucle + alertes

SÛRETÉ : LECTURE SEULE (ubus mcu status = lecture ; /sys en lecture). Aucune action réseau.
Zéro dépendance. Sur l'appareil, MCU via `chroot $DM_HOSTROOT ubus`.

État runtime (sous RM_STATE, défaut ~/.radio-monitor/) :
  device-state.json   dernier instantané
  device.jsonl        historique (en --watch)
  device-alerts.jsonl évènements d'alerte
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("RM_STATE", Path.home() / ".radio-monitor"))
DEVICE_STATE = STATE_DIR / "device-state.json"
DEVICE_LOG = STATE_DIR / "device.jsonl"
DEVICE_ALERTS = STATE_DIR / "device-alerts.jsonl"
THERMAL = Path(os.environ.get("DM_THERMAL", "/sys/class/thermal"))
HOSTROOT = os.environ.get("DM_HOSTROOT", "/proc/1/root")
DIRECT = os.environ.get("DM_UBUS_DIRECT")

BAT_LOW = float(os.environ.get("DM_BAT_LOW", 20))       # % batterie (en décharge) → alerte
TEMP_HIGH = float(os.environ.get("DM_TEMP_HIGH", 85))   # °C → alerte surchauffe
INTERVAL = float(os.environ.get("DM_INTERVAL", 30))


def mcu_status():
    argv = (["ubus"] if DIRECT else ["chroot", HOSTROOT, "ubus"]) + ["call", "mcu", "status", "{}"]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=8)
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def thermals():
    out = {}
    try:
        for z in THERMAL.glob("thermal_zone*"):
            try:
                label = (z / "type").read_text().strip()
                milli = int((z / "temp").read_text().strip())
            except (OSError, ValueError):
                continue
            c = milli / 1000.0
            if label and -50 < c < 200:      # ignore capteurs désactivés (-273 / 0)
                out[label] = round(c, 1)
    except OSError:
        pass
    return out


def _grp_max(th, *keys):
    vals = [v for k, v in th.items() if any(x in k for x in keys)]
    return max(vals) if vals else None


def snapshot():
    m = mcu_status()
    th = thermals()
    charging = m.get("charging_status")
    snap = {
        "battery_pct": m.get("charge_percent"),
        "charging": bool(charging) if charging is not None else None,
        "fastcharge": m.get("fastcharge"),
        "battery_temp_c": float(m["temperature"]) if m.get("temperature") not in (None, "") else None,
        "charge_cycles": m.get("charge_cnt"),
        "battery_abnormal": m.get("abnormal"),
        "cpu_temp_c": _grp_max(th, "cpuss", "cpu"),
        "modem_temp_c": _grp_max(th, "mdm", "sdr", "mmw"),
        "max_temp_c": max(th.values()) if th else None,
        "zones": th,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return snap


def evaluate(s):
    conds = []
    b, ch = s.get("battery_pct"), s.get("charging")
    if isinstance(b, (int, float)) and ch is False and b <= BAT_LOW:
        conds.append(("battery_low", "batterie %d%% (en décharge) ≤ %d%%" % (b, BAT_LOW)))
    mx = s.get("max_temp_c")
    if isinstance(mx, (int, float)) and mx >= TEMP_HIGH:
        conds.append(("overheat", "température %.1f°C ≥ %d°C" % (mx, TEMP_HIGH)))
    if s.get("battery_abnormal"):
        conds.append(("battery_abnormal", "anomalie batterie signalée par le MCU"))
    return conds


def log_line(path, obj):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def render(s):
    L = ["=== device-monitor ==="]
    bat = "%s%%" % s["battery_pct"] if s["battery_pct"] is not None else "?"
    st = "charge" if s["charging"] else ("décharge" if s["charging"] is False else "?")
    fc = " (charge rapide)" if s.get("fastcharge") else ""
    L.append("Batterie   : %s · %s%s · %s°C · %s cycles" % (bat, st, fc, s.get("battery_temp_c"), s.get("charge_cycles")))
    L.append("Température : CPU %s°C · modem %s°C · max %s°C" % (s.get("cpu_temp_c"), s.get("modem_temp_c"), s.get("max_temp_c")))
    if s.get("battery_abnormal"):
        L.append("⚠️  anomalie batterie (MCU)")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Télémétrie batterie/température (lecture seule).")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    ap.add_argument("--notify-cmd", default=os.environ.get("DM_NOTIFY_CMD"))
    args = ap.parse_args()

    def one():
        s = snapshot()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        DEVICE_STATE.write_text(json.dumps(s, indent=1))
        return s

    if args.watch:
        print("device-monitor : relevé toutes les %gs (Ctrl-C pour arrêter)" % args.interval)
        prev = set()
        while True:
            try:
                s = one()
                log_line(DEVICE_LOG, {"t": s["updated"], "bat": s["battery_pct"], "chg": s["charging"],
                                      "cpu": s["cpu_temp_c"], "max": s["max_temp_c"]})
                conds = evaluate(s)
                codes = {c[0] for c in conds}
                for code, msg in conds:
                    if code not in prev:
                        ev = {"t": s["updated"], "code": code, "msg": msg}
                        log_line(DEVICE_ALERTS, ev)
                        line = "🔴 [device] " + msg
                        print(line)
                        if args.notify_cmd:
                            try:
                                subprocess.run(args.notify_cmd, shell=True, input=line, text=True, timeout=15)
                            except Exception:
                                pass
                prev = codes
                print("%s  bat %s%% %s  max %s°C" % (s["updated"], s["battery_pct"],
                      "⚡" if s["charging"] else "🔋", s["max_temp_c"]))
            except Exception as e:
                print("warn:", e)
            time.sleep(args.interval)
        return

    s = one()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(render(s))
        for code, msg in evaluate(s):
            print("  ⚠️  " + msg)


if __name__ == "__main__":
    main()
