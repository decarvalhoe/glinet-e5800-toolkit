#!/usr/bin/env python3
"""
onion-watchdog.py — garantit que le service caché Tor (.onion) revient seul après coupure.

Le WAN cellulaire est auto-redialé par le routeur (carrier-monitor/kmwan). Mais après une
coupure, l'IP cellulaire change et Tor peut tarder à re-publier son descripteur. Ce
watchdog détecte le rétablissement de la connectivité et **redémarre proprement**
`onion-dashboard` pour que l'adresse `.onion` soit à nouveau joignable rapidement.

  python3 tools/onion-watchdog.py --watch          # démon
  python3 tools/onion-watchdog.py --dry-run --watch # n'exécute pas le restart (test)

SÛRETÉ : ne gère QUE l'instance Tor autonome (restart `onion-dashboard`). Ne touche NI au
WAN, NI au modem, NI au firewall. Sonde HTTPS generate_204 (≈0 octet). Zéro dépendance.

Debounce : il faut DOWN_THRESHOLD sondes ratées d'affilée pour déclarer une coupure, ce qui
évite de redémarrer sur un simple micro-blip.
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("RM_STATE", Path.home() / ".radio-monitor"))
WD_LOG = STATE_DIR / "watchdog.jsonl"
PROBE_URL = os.environ.get("WD_PROBE_URL", "https://www.google.com/generate_204")
INTERVAL = float(os.environ.get("WD_INTERVAL", 20))
DOWN_THRESHOLD = int(os.environ.get("WD_DOWN_THRESHOLD", 3))
HOSTROOT = os.environ.get("WD_HOSTROOT", "/proc/1/root")
SERVICE = os.environ.get("WD_SERVICE", "onion-dashboard")


def probe():
    try:
        urllib.request.urlopen(PROBE_URL, timeout=4).read(1)
        return True
    except Exception:
        return False


def step(state, up):
    """Machine à états pure. state = {'down': int, 'outage': bool}.
    Retourne (state, action) avec action ∈ {None, 'outage', 'restore'}."""
    down, outage = state.get("down", 0), state.get("outage", False)
    action = None
    if up:
        if outage:
            action = "restore"        # connectivité revenue après une vraie coupure
        state = {"down": 0, "outage": False}
    else:
        down += 1
        if down >= DOWN_THRESHOLD and not outage:
            outage, action = True, "outage"
        state = {"down": down, "outage": outage}
    return state, action


def restart_service(dry):
    if dry:
        return "dry-run"
    try:
        subprocess.run(["chroot", HOSTROOT, "/etc/init.d/" + SERVICE, "restart"],
                       capture_output=True, text=True, timeout=30)
        return "restarted"
    except Exception as e:
        return "err:" + str(e)


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(obj):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with WD_LOG.open("a") as f:
        f.write(json.dumps({"t": _iso(), **obj}, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Watchdog de reconnexion du service .onion.")
    ap.add_argument("--watch", action="store_true", help="démon (défaut)")
    ap.add_argument("--dry-run", action="store_true", help="ne pas exécuter le restart (test)")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    args = ap.parse_args()

    print("onion-watchdog : sonde toutes les %gs · coupure après %d échecs · service %s%s"
          % (args.interval, DOWN_THRESHOLD, SERVICE, " [dry-run]" if args.dry_run else ""))
    state = {"down": 0, "outage": False}
    while True:
        try:
            up = probe()
            state, action = step(state, up)
            if action == "outage":
                log({"event": "outage", "msg": "connectivité perdue"})
                print("%s  ⚠️  coupure détectée" % _iso())
            elif action == "restore":
                res = restart_service(args.dry_run)
                log({"event": "restore", "action": "restart_" + SERVICE, "result": res})
                print("%s  🟢  connectivité revenue → %s (%s)" % (_iso(), SERVICE, res))
        except Exception as e:
            print("warn:", e)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
