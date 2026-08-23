#!/usr/bin/env python3
"""
gps-fix.py — lit un fix GNSS du modem (Quectel RG650) en LECTURE SEULE, cherche les
satellites en vue, et tague éventuellement les échantillons de signal avec la position.

Le fix vient d'une requête AT de position (`AT+QGPSLOC=2`) et les satellites d'une trame
`GSV`, via `ubus modem.CPU.AT get_result_AT`. AUCUNE écriture AT (le GNSS doit être déjà
activé : AT+QGPS=1). Gère proprement l'état « no fix / 0 satellite ».

  python3 tools/gps-fix.py --once           # un relevé de position
  python3 tools/gps-fix.py --json            # un relevé, JSON
  python3 tools/gps-fix.py --sats            # CHERCHEUR : satellites en vue + SNR, en boucle
  python3 tools/gps-fix.py --watch --tag     # GUETTEUR : boucle, tague heatmap.jsonl si fix

SÛRETÉ : seulement des requêtes AT de lecture (QGPSLOC/QGPSGNMEA). Ne touche pas au WAN.
Zéro dépendance (stdlib). Sur l'appareil, appelle le host via `chroot $GPS_HOSTROOT ubus`.

État runtime (sous RM_STATE, défaut ~/.radio-monitor/) :
  gps.jsonl       un relevé par FIX (les no-fix ne sont pas journalisés)
  heatmap.jsonl   (si --tag et fix) position + signal courant, pour la heatmap
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
HOSTROOT = os.environ.get("GPS_HOSTROOT", "/proc/1/root")
DIRECT = os.environ.get("GPS_UBUS_DIRECT")

TALKERS = {"GP": "GPS", "GL": "GLONASS", "GA": "Galileo", "GB": "BeiDou",
           "BD": "BeiDou", "QZ": "QZSS", "GN": "multi"}


def at_query(cmd, timeout=5):
    """Requête AT de LECTURE via ubus modem.CPU.AT. Retourne la chaîne 'data' (ou '')."""
    payload = json.dumps({"cmd": cmd, "timeout": timeout})
    argv = (["ubus"] if DIRECT else ["chroot", HOSTROOT, "ubus"]) + \
        ["call", "modem.CPU.AT", "get_result_AT", payload]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 6)
        return (json.loads(out.stdout or "{}")).get("data", "")
    except Exception as e:
        return "ERR " + str(e)


def parse_qgpsloc(data):
    """+QGPSLOC: utc,lat,lon,hdop,alt,fix,cog,spkm,spkn,date,nsat (mode 2 = degrés décimaux)."""
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
    return {"utc": f[0] or None, "lat": num(f[1]), "lon": num(f[2]), "hdop": num(f[3]),
            "alt": num(f[4]), "fix_type": f[5] or None, "date": f[9] or None,
            "sats": int(f[10]) if f[10].isdigit() else None}


def parse_gsv(data):
    """Parse les trames GSV → ({talker: sats_en_vue}, [(prn, snr), ...])."""
    talkers, snrs = {}, []
    for line in data.replace("\r", "\n").split("\n"):
        idx = line.find("GSV,")
        if idx < 2:
            continue
        talker = line[idx - 2:idx]
        f = line[idx + 4:].split("*")[0].split(",")
        if len(f) < 3:
            continue
        try:
            talkers[talker] = int(f[2]) if f[2] else 0
        except ValueError:
            talkers[talker] = 0
        rest = f[3:]
        for i in range(0, len(rest) - 3, 4):
            prn, snr = rest[i], rest[i + 3]
            try:
                s = int(snr) if snr else 0
            except ValueError:
                s = 0
            if prn:
                snrs.append((prn, s))
    return talkers, snrs


def read_fix():
    data = at_query("AT+QGPSLOC=2")
    return parse_qgpsloc(data), data


def read_sats():
    data = at_query('AT+QGPSGNMEA="GSV"')
    talkers, snrs = parse_gsv(data)
    tracked = [s for (_p, s) in snrs if s > 0]
    return {"in_view": sum(talkers.values()),
            "by_constellation": {TALKERS.get(k, k): v for k, v in talkers.items() if v},
            "tracked": len(tracked), "max_snr": max(tracked) if tracked else 0,
            "snrs": sorted((s for (_p, s) in snrs), reverse=True)}


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
        log_line(GPS_LOG, rec)                     # journalise seulement les fixes
        if tag and fix.get("lat") is not None:
            hm = {"t": rec["t"], "lat": fix["lat"], "lon": fix["lon"], "alt": fix.get("alt"),
                  "sats": fix.get("sats"), "hdop": fix.get("hdop"), **current_signal()}
            log_line(HEATMAP, hm)
            rec["tagged"] = True
    return rec, raw


def main():
    ap = argparse.ArgumentParser(description="Fix GNSS + chercheur de satellites (lecture seule).")
    ap.add_argument("--once", action="store_true", help="un relevé de position puis quitte")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    ap.add_argument("--sats", action="store_true", help="chercheur : satellites en vue + SNR, en boucle")
    ap.add_argument("--watch", action="store_true", help="guetteur : boucle de relevés")
    ap.add_argument("--tag", action="store_true", help="tague heatmap.jsonl quand fixé (avec --watch)")
    ap.add_argument("--interval", type=float, default=None, help="secondes entre relevés")
    args = ap.parse_args()

    if args.sats:
        iv = args.interval or 3
        print("gps-fix --sats : satellites en vue (Ctrl-C pour arrêter). 0 = aucun ciel capté.")
        while True:
            try:
                s = read_sats()
                fix, _ = read_fix()
                cons = " ".join("%s:%d" % (k, v) for k, v in s["by_constellation"].items()) or "—"
                print("%s  en vue:%2d [%s]  suivis:%2d  SNR max:%2d dB  %s"
                      % (_iso(), s["in_view"], cons, s["tracked"], s["max_snr"],
                         "FIX ✅" if fix else "…recherche"))
            except Exception as e:
                print("warn:", e)
            time.sleep(iv)
        return

    if args.watch:
        iv = args.interval or float(os.environ.get("GPS_INTERVAL", 15))
        print("gps-fix --watch : relevé toutes les %gs%s (Ctrl-C pour arrêter)"
              % (iv, " + tagging heatmap" if args.tag else ""))
        while True:
            try:
                rec, _ = one(tag=args.tag)
                if rec["fix"]:
                    print("%s  FIX  %.6f, %.6f  alt %s  sats %s%s"
                          % (rec["t"], rec["lat"], rec["lon"], rec.get("alt"), rec.get("sats"),
                             "  [taggé]" if rec.get("tagged") else ""))
                else:
                    print("%s  no fix" % rec["t"])
            except Exception as e:
                print("warn:", e)
            time.sleep(iv)
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
