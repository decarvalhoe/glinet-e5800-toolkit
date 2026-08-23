#!/usr/bin/env python3
"""
radio-alert.py - moteur d'alertes/anomalies au-dessus de radio-monitor.

Consomme l'historique produit par tools/radio-monitor.py (`history.jsonl`) et lève des
alertes sur :
  - seuils      : RSRP / SINR sous un plancher (WARN puis CRIT) ;
  - anomalie    : chute rapide vs baseline glissante (alerte AVANT la coupure franche) ;
  - péremption  : plus aucun échantillon récent => buffer figé, coupure probable.

Anti-spam : hystérésis via un fichier d'état ; on n'émet qu'aux transitions (montée
d'alerte, changement de conditions, ou rétablissement).

SÛRETÉ : n'appelle PAS le routeur. Lecture seule de fichiers locaux. Aucune action réseau.
Le seul effet sortant possible est une commande de notification que VOUS fournissez
explicitement (`--notify-cmd` / RA_NOTIFY_CMD) ; par défaut, rien n'est envoyé (log seul).
Y brancher `sendsms`/push/webhook est un choix opt-in (action sortante) — voir docs.

Zéro dépendance (stdlib). À lancer à côté de radio-monitor (qui alimente l'historique).

  python3 tools/radio-alert.py --check        # évalue une fois, imprime, quitte (cron)
  python3 tools/radio-alert.py --watch         # démon : évalue en boucle
  python3 tools/radio-alert.py --check --json  # état structuré en JSON

État runtime (non versionné), partagé avec radio-monitor via RM_STATE / RA_STATE :
  history.jsonl      (lu) échantillons de radio-monitor
  alerts.jsonl       (écrit) journal des évènements d'alerte
  alert-state.json   (écrit) dernier état, pour l'hystérésis
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("RA_STATE", os.environ.get("RM_STATE", Path.home() / ".radio-monitor")))
HISTORY = STATE_DIR / "history.jsonl"
ALERTS = STATE_DIR / "alerts.jsonl"
ALERT_STATE = STATE_DIR / "alert-state.json"

SEV_ORDER = {"OK": 0, "WARN": 1, "CRIT": 2}


def cfg_from(args):
    e = os.environ.get
    return {
        "rsrp_warn": float(args.rsrp_warn if args.rsrp_warn is not None else e("RA_RSRP_WARN", -105)),
        "rsrp_crit": float(args.rsrp_crit if args.rsrp_crit is not None else e("RA_RSRP_CRIT", -113)),
        "sinr_warn": float(e("RA_SINR_WARN", 3)),
        "sinr_crit": float(e("RA_SINR_CRIT", 0)),
        "drop_db": float(e("RA_DROP_DB", 8)),        # chute RSRP vs baseline => anomalie
        "sinr_drop": float(e("RA_SINR_DROP", 6)),
        "zscore": float(e("RA_ZSCORE", 2.5)),
        "window": int(e("RA_WINDOW", 60)),           # taille baseline (échantillons)
        "stale_s": float(e("RA_STALE_S", 120)),      # péremption max_ts (s de temps réel)
        "interval": float(e("RA_INTERVAL", 30)),
        "notify_cmd": args.notify_cmd or e("RA_NOTIFY_CMD"),
    }


def load_history(limit=400):
    if not HISTORY.exists():
        return []
    rows = []
    try:
        with HISTORY.open() as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows[-limit:]


def _median(v):
    v = sorted(x for x in v if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _mean_std(v):
    v = [x for x in v if isinstance(x, (int, float))]
    if len(v) < 2:
        return (v[0] if v else None), 0.0
    m = sum(v) / len(v)
    var = sum((x - m) ** 2 for x in v) / len(v)
    return m, var ** 0.5


def quality(rsrp, sinr):
    if rsrp is None or sinr is None:
        return "inconnu"
    if rsrp >= -90 and sinr >= 13:
        return "excellent"
    if rsrp >= -100 and sinr >= 5:
        return "bon"
    if rsrp >= -110 and sinr >= 0:
        return "moyen"
    return "faible"


def evaluate(rows, cfg, prev):
    """Retourne (severity, conditions[], metrics, max_ts_info)."""
    now = time.time()
    conds = []
    if not rows:
        return "OK", [], {}, {"max_ts": prev.get("max_ts", 0), "max_ts_seen_at": prev.get("max_ts_seen_at", now)}

    last3 = rows[-3:]
    rsrp = _median([r.get("rsrp") for r in last3])
    sinr = _median([r.get("sinr") for r in last3])
    net = rows[-1].get("net")
    q = quality(rsrp, sinr)

    # -- seuils --
    if rsrp is not None:
        if rsrp <= cfg["rsrp_crit"]:
            conds.append(("rsrp_crit", "CRIT", "RSRP %s dBm ≤ %s (critique)" % (rsrp, cfg["rsrp_crit"])))
        elif rsrp <= cfg["rsrp_warn"]:
            conds.append(("rsrp_warn", "WARN", "RSRP %s dBm ≤ %s (faible)" % (rsrp, cfg["rsrp_warn"])))
    if sinr is not None:
        if sinr <= cfg["sinr_crit"]:
            conds.append(("sinr_crit", "CRIT", "SINR %s dB ≤ %s (critique)" % (sinr, cfg["sinr_crit"])))
        elif sinr <= cfg["sinr_warn"]:
            conds.append(("sinr_warn", "WARN", "SINR %s dB ≤ %s (faible)" % (sinr, cfg["sinr_warn"])))

    # -- anomalie : chute rapide vs baseline (fenêtre hors 3 derniers points) --
    base = rows[-(cfg["window"] + 3):-3] if len(rows) > cfg["window"] + 3 else rows[:-3]
    if len(base) >= 10:
        bm_r, bs_r = _mean_std([r.get("rsrp") for r in base])
        bm_s, _ = _mean_std([r.get("sinr") for r in base])
        if rsrp is not None and bm_r is not None:
            drop = bm_r - rsrp
            z = (rsrp - bm_r) / bs_r if bs_r > 1 else 0
            if drop >= cfg["drop_db"] or z <= -cfg["zscore"]:
                conds.append(("anomaly_rsrp", "WARN",
                              "chute RSRP %.0f dB vs baseline %.0f (z=%.1f)" % (drop, bm_r, z)))
        if sinr is not None and bm_s is not None and (bm_s - sinr) >= cfg["sinr_drop"]:
            conds.append(("anomaly_sinr", "WARN", "chute SINR %.0f dB vs baseline %.0f" % (bm_s - sinr, bm_s)))

    # -- péremption : max_ts n'avance plus (buffer figé => coupure probable) --
    max_ts = max((r.get("ts", 0) for r in rows), default=0)
    prev_max = prev.get("max_ts", 0)
    seen_at = now if max_ts > prev_max else prev.get("max_ts_seen_at", now)
    stale_for = now - seen_at
    if stale_for >= cfg["stale_s"]:
        sev = "CRIT" if stale_for >= cfg["stale_s"] * 2 else "WARN"
        conds.append(("stale", sev, "aucun nouvel échantillon depuis %ds (coupure probable)" % int(stale_for)))

    severity = "OK"
    for _, sev, _m in conds:
        if SEV_ORDER[sev] > SEV_ORDER[severity]:
            severity = sev
    metrics = {"rsrp": rsrp, "sinr": sinr, "net": net, "quality": q, "stale_for_s": int(stale_for)}
    return severity, conds, metrics, {"max_ts": max_ts, "max_ts_seen_at": seen_at}


def load_prev():
    try:
        return json.loads(ALERT_STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = ALERT_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(ALERT_STATE)


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def notify(event, cfg):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    icon = {"alert": "🔴", "resolve": "🟢"}.get(event["kind"], "•")
    line = "%s [%s] %s — %s" % (icon, event["severity"], event["summary"],
                                "; ".join(c[2] for c in event.get("conditions", [])) or "rétabli")
    print(line, file=sys.stderr)   # stdout reste propre (table/JSON) ; l'alerte va en stderr + alerts.jsonl
    if cfg["notify_cmd"]:
        try:
            subprocess.run(cfg["notify_cmd"], shell=True, input=line, text=True, timeout=15)
        except Exception as e:                       # une notif ratée ne casse pas le moteur
            print("warn notify_cmd:", e, file=sys.stderr)


def tick(cfg):
    prev = load_prev()
    rows = load_history()
    severity, conds, metrics, tsinfo = evaluate(rows, cfg, prev)
    codes = sorted(c[0] for c in conds)
    prev_sev = prev.get("severity", "OK")
    prev_codes = prev.get("codes", [])

    changed = severity != prev_sev or codes != prev_codes
    if changed:
        if severity == "OK":
            ev = {"t": _iso(), "kind": "resolve", "severity": "OK",
                  "summary": "signal rétabli (%s)" % metrics.get("quality"),
                  "conditions": [], "metrics": metrics}
        else:
            ev = {"t": _iso(), "kind": "alert", "severity": severity,
                  "summary": "%s — RSRP %s / SINR %s (%s)" % (
                      severity, metrics.get("rsrp"), metrics.get("sinr"), metrics.get("quality")),
                  "conditions": conds, "metrics": metrics}
        notify(ev, cfg)

    save_state({"severity": severity, "codes": codes, "metrics": metrics,
                "max_ts": tsinfo["max_ts"], "max_ts_seen_at": tsinfo["max_ts_seen_at"],
                "updated": _iso()})
    return severity, conds, metrics, changed


def main():
    ap = argparse.ArgumentParser(description="Moteur d'alertes/anomalies signal (lecture seule).")
    ap.add_argument("--check", action="store_true", help="évalue une fois puis quitte")
    ap.add_argument("--watch", action="store_true", help="démon : évalue en boucle")
    ap.add_argument("--json", action="store_true", help="sortie JSON structurée (--check)")
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--rsrp-warn", type=float, default=None)
    ap.add_argument("--rsrp-crit", type=float, default=None)
    ap.add_argument("--notify-cmd", default=None,
                    help="commande shell recevant l'alerte sur stdin (opt-in ; ex: un script SMS)")
    args = ap.parse_args()
    cfg = cfg_from(args)
    if args.interval is not None:
        cfg["interval"] = args.interval

    if args.watch:
        print("radio-alert : surveillance toutes les %gs (Ctrl-C pour arrêter)" % cfg["interval"])
        while True:
            try:
                sev, conds, m, _ = tick(cfg)
                if sev == "OK":
                    print("%s  OK  RSRP %s SINR %s (%s)" % (_iso(), m.get("rsrp"), m.get("sinr"), m.get("quality")))
            except Exception as e:
                print("warn:", e, file=sys.stderr)
            time.sleep(cfg["interval"])
        return

    # défaut = --check
    sev, conds, m, changed = tick(cfg)
    if args.json:
        print(json.dumps({"severity": sev, "conditions": [
            {"code": c[0], "severity": c[1], "message": c[2]} for c in conds],
            "metrics": m, "emitted": changed}, ensure_ascii=False, indent=2))
    else:
        print("=== radio-alert ===")
        print("Sévérité :", sev, "|", "RSRP", m.get("rsrp"), "SINR", m.get("sinr"), "(%s)" % m.get("quality"))
        for code, s, msg in conds:
            print("  - [%s] %s" % (s, msg))
        if not conds:
            print("  (aucune condition active)")
    sys.exit(2 if sev == "CRIT" else (1 if sev == "WARN" else 0))


if __name__ == "__main__":
    main()
