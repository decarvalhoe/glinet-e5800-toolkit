#!/usr/bin/env python3
"""
gps-fix.py — lit un fix GNSS du modem (Quectel RG650) en LECTURE SEULE, et tague
éventuellement les échantillons de signal de radio-monitor avec la position (heatmap).

Le fix est obtenu par une requête AT de position (`AT+QGPSLOC=2`, degrés décimaux) via
`ubus modem.CPU.AT get_result_AT`. AUCUNE écriture AT (pas d'activation modem) : le GNSS
doit être déjà activé (AT+QGPS=1) — voir docs. Gère proprement l'état « no fix ».

  python3 tools/gps-fix.py --once           # un relevé, résumé
  python3 tools/gps-fix.py --json            # un relevé, JSON
  python3 tools/gps-fix.py --watch --tag     # boucle: log + tague heatmap (position+signal)

SÛRETÉ : n'envoie que des requêtes AT de lecture (QGPSLOC/QGPSGNMEA). Ne touche pas au WAN.
Zéro dépendance (stdlib). Sur l'appareil, appelle le host via `chroot $GPS_HOSTROOT ubus`.

État runtime (partagé, non versionné) sous RM_STATE (défaut ~/.radio-monitor/) :
  gps.jsonl       un relevé GPS par ligne (fix ou no-fix, horodaté)
  heatmap.jsonl   (si --tag et fix) position + signal courant, pour la heatmap
Lit le signal courant depuis state.json de radio-monitor.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("RM_STATE", Path.home() / ".radio-monitor"))
GPS_LOG = STATE_DIR / "gps.jsonl"
HEATMAP = STATE_DIR / "heatmap.jsonl"
SIGNAL_STATE = STATE_DIR / "state.json"
HOSTROOT = os.environ.get("GPS_HOSTROOT", "/proc/1/root")   # racine host vue du chroot
DIRECT = os.environ.get("GPS_UBUS_DIRECT")                   # =1 si on tourne déjà sur le host


def at_query(cmd, timeout=5):
    """Envoie une requête AT de LECTURE et renvoie la chaîne 'data' brute (ou '')."""
    payload = json.dumps({"cmd": cmd, "timeout": timeout})
    argv = (["ubus"] if DIRECT else ["chroot", HOSTROOT, "ubus"]) + \
        ["call", "modem.CPU.AT", "get_result_AT", payload]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 6)
        return (json.loads(out.stdout or "{}")).get("data", "")
    except Exception as e:
        return "ERR " + str(e)


def parse_qgpsloc(data):
    """+QGPSLOC: utc,lat,lon,hdop,alt,fix,cog,spkm,spkn,date,nsat  (mode 2 = degrés décimaux)."""
    if not data or "+CME ERROR" in data or "+QGPSLOC:" not in data:
        return None
    body = data.split("+QGPSLOC:", 1)[1].replace("\r", "\n").split("\n")[0].strip()
    f = body.split(",")
    if len(f) < 11:
        return None
    def num(x):
        try:
            return float(x)
        except ValueError:
            return None
    return {
        "utc": f[0] or None, "lat": num(f[1]), "lon": num(f[2]), "hdop": num(f[3]),
        "alt": num(f[4]), "fix_type": f[5] or None, "date": f[9] or None,
        "sats": int(f[10]) if f[10].isdigit() else None,
    }


def read_fix():
    data = at_query("AT+QGPSLOC=2")
    return parse_qgpsloc(data), data


def current_signal():
    try:
        cur = json.loads(SIGNAL_STATE.read_text()).get("current", {})
        return {"rsrp": cur.get("rsrp"), "sinr": cur.get("sinr"),
                "net": cur.get("net"), "quality": cur.get("quality")}
    except Exception:
        return {}


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log_line(path, obj):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def one(tag=False):
    fix, raw = read_fix()
    rec = {"t": _iso(), "fix": bool(fix)}
    if fix:
        rec.update(fix)
    log_line(GPS_LOG, rec)
    if tag and fix and fix.get("lat") is not None:
        sig = current_signal()
        hm = {"t": rec["t"], "lat": fix["lat"], "lon": fix["lon"], "alt": fix.get("alt"),
              "sats": fix.get("sats"), "hdop": fix.get("hdop"), **sig}
        log_line(HEATMAP, hm)
        rec["tagged"] = True
    return rec, raw


def main():
    ap = argparse.ArgumentParser(description="Lecture d'un fix GNSS (lecture seule) + tagging heatmap.")
    ap.add_argument("--once", action="store_true", help="un relevé puis quitte")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    ap.add_argument("--watch", action="store_true", help="boucle de relevés")
    ap.add_argument("--tag", action="store_true", help="tague heatmap.jsonl (position+signal) quand fixé")
    ap.add_argument("--interval", type=float, default=float(os.environ.get("GPS_INTERVAL", 10)))
    args = ap.parse_args()

    if args.watch:
        print("gps-fix : relevé toutes les %gs (Ctrl-C pour arrêter)%s"
              % (args.interval, " + tagging heatmap" if args.tag else ""))
        while True:
            try:
                rec, _ = one(tag=args.tag)
                if rec["fix"]:
                    print("%s  FIX  %.6f, %.6f  alt %s m  sats %s%s"
                          % (rec["t"], rec["lat"], rec["lon"], rec.get("alt"), rec.get("sats"),
                             "  [taggé]" if rec.get("tagged") else ""))
                else:
                    print("%s  no fix" % rec["t"])
            except Exception as e:
                print("warn:", e)
            time.sleep(args.interval)
        return

    rec, raw = one(tag=args.tag)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    elif rec["fix"]:
        print("=== gps-fix ===")
        print("Position : %.6f, %.6f" % (rec["lat"], rec["lon"]))
        print("Altitude : %s m · HDOP %s · satellites %s" % (rec.get("alt"), rec.get("hdop"), rec.get("sats")))
        print("UTC      : %s  date %s" % (rec.get("utc"), rec.get("date")))
    else:
        print("=== gps-fix ===")
        print("Pas de fix (0 satellite). GNSS activé mais sans accroche — vue du ciel requise.")
        print("Détail AT :", raw.strip().replace("\r", " ").replace("\n", " "))


if __name__ == "__main__":
    main()
