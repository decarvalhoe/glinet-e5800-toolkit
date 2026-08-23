#!/usr/bin/env python3
"""
radio-digest.py - synthèse (quotidienne) du signal cellulaire.

Agrège l'historique de radio-monitor (`history.jsonl`) et le journal d'alertes
(`alerts.jsonl`) sur une fenêtre donnée et produit un rapport lisible : disponibilité
estimée, RSRP/SINR min/moy/max, pire créneau, distribution de qualité, types réseau,
et bilan des alertes.

SÛRETÉ : lecture seule de fichiers locaux. N'appelle PAS le routeur. Aucune action réseau.
Notification opt-in (`--notify-cmd` / RD_NOTIFY_CMD) pour l'envoyer (mail/SMS/push).

Zéro dépendance (stdlib).

  python3 tools/radio-digest.py                 # 24 dernières heures, texte
  python3 tools/radio-digest.py --since 7d       # 7 jours
  python3 tools/radio-digest.py --day 2026-08-23 # une journée (UTC)
  python3 tools/radio-digest.py --json           # sortie structurée

État runtime lu (partagé, non versionné) : RM_STATE / RD_STATE (défaut ~/.radio-monitor/).
"""
import argparse
import calendar
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("RD_STATE", os.environ.get("RM_STATE", Path.home() / ".radio-monitor")))
HISTORY = STATE_DIR / "history.jsonl"
ALERTS = STATE_DIR / "alerts.jsonl"


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


def parse_since(s):
    units = {"h": 3600, "d": 86400, "m": 60, "w": 604800}
    try:
        return float(s[:-1]) * units[s[-1]] if s[-1] in units else float(s)
    except (ValueError, KeyError, IndexError):
        return 86400.0


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    try:
        with path.open() as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def pct(vals, p):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
    return vals[k]


def stats(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return {"min": min(vals), "avg": round(sum(vals) / len(vals), 1), "max": max(vals),
            "p10": pct(vals, 10), "n": len(vals)}


def iso_to_epoch(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def build(rows, alerts, t0, t1):
    win = [r for r in rows if t0 <= r.get("ts", 0) < t1]
    out = {
        "window_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
        "window_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t1)),
        "samples": len(win),
    }
    if not win:
        return out

    rsrp = [r.get("rsrp") for r in win]
    sinr = [r.get("sinr") for r in win]
    out["rsrp"] = stats(rsrp)
    out["sinr"] = stats(sinr)

    # distribution de qualité (par échantillon)
    qd = {"excellent": 0, "bon": 0, "moyen": 0, "faible": 0, "inconnu": 0}
    for r in win:
        qd[quality(r.get("rsrp"), r.get("sinr"))] += 1
    n = len(win)
    out["quality_pct"] = {k: round(100.0 * v / n, 1) for k, v in qd.items() if v}
    # « disponibilité » = part des échantillons de qualité au moins moyenne
    good = qd["excellent"] + qd["bon"] + qd["moyen"]
    out["availability_pct"] = round(100.0 * good / n, 1)

    # types réseau
    nets = {}
    for r in win:
        nets[r.get("net")] = nets.get(r.get("net"), 0) + 1
    out["network_types"] = nets

    # pire créneau de 10 min (par RSRP moyen)
    buckets = {}
    for r in win:
        b = int(r.get("ts", 0)) // 600
        buckets.setdefault(b, []).append(r.get("rsrp"))
    worst = None
    for b, vals in buckets.items():
        vv = [v for v in vals if isinstance(v, (int, float))]
        if not vv:
            continue
        avg = sum(vv) / len(vv)
        if worst is None or avg < worst[1]:
            worst = (b, avg, len(vv))
    if worst:
        out["worst_window"] = {
            "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(worst[0] * 600)),
            "rsrp_avg": round(worst[1], 1), "samples": worst[2]}

    # bilan alertes (paires alert -> resolve)
    aw = [a for a in alerts if (iso_to_epoch(a.get("t")) or 0) >= t0 and (iso_to_epoch(a.get("t")) or 0) < t1]
    n_alert = sum(1 for a in aw if a.get("kind") == "alert")
    n_resolve = sum(1 for a in aw if a.get("kind") == "resolve")
    degraded_s, longest_s, open_at = 0, 0, None
    for a in sorted(aw, key=lambda x: iso_to_epoch(x.get("t")) or 0):
        e = iso_to_epoch(a.get("t"))
        if a.get("kind") == "alert" and open_at is None:
            open_at = e
        elif a.get("kind") == "resolve" and open_at is not None:
            d = (e or open_at) - open_at
            degraded_s += d
            longest_s = max(longest_s, d)
            open_at = None
    out["alerts"] = {"raised": n_alert, "resolved": n_resolve,
                     "degraded_s": degraded_s, "longest_degradation_s": longest_s,
                     "by_severity": _count(aw, "severity")}
    return out


def _count(rows, key):
    d = {}
    for r in rows:
        if r.get("kind") != "alert":
            continue
        d[r.get(key)] = d.get(r.get(key), 0) + 1
    return d


def render(d):
    L = []
    L.append("=== Digest radio — %s → %s ===" % (d["window_start"], d["window_end"]))
    if not d.get("samples"):
        L.append("Aucun échantillon sur la fenêtre.")
        return "\n".join(L)
    L.append("Échantillons     : %d" % d["samples"])
    L.append("Disponibilité    : %s %% (qualité ≥ moyenne)" % d["availability_pct"])
    r, s = d.get("rsrp"), d.get("sinr")
    if r:
        L.append("RSRP dBm         : min %s · p10 %s · moy %s · max %s" % (r["min"], r["p10"], r["avg"], r["max"]))
    if s:
        L.append("SINR dB          : min %s · p10 %s · moy %s · max %s" % (s["min"], s["p10"], s["avg"], s["max"]))
    qp = d.get("quality_pct", {})
    L.append("Qualité (%% temps): " + " · ".join("%s %s%%" % (k, v) for k, v in qp.items()))
    nt = d.get("network_types", {})
    L.append("Types réseau     : " + " · ".join("%s:%s" % (k, v) for k, v in nt.items()))
    w = d.get("worst_window")
    if w:
        L.append("Pire créneau     : %s — RSRP moy %s dBm (%d pts)" % (w["start"], w["rsrp_avg"], w["samples"]))
    a = d.get("alerts", {})
    deg = a.get("degraded_s", 0)
    L.append("Alertes          : %d levée(s), %d rétablie(s) · dégradé %d min %02d s · pire %d s"
             % (a.get("raised", 0), a.get("resolved", 0), deg // 60, deg % 60, a.get("longest_degradation_s", 0)))
    bs = a.get("by_severity", {})
    if bs:
        L.append("  par sévérité   : " + " · ".join("%s:%s" % (k, v) for k, v in bs.items()))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Synthèse quotidienne du signal (lecture seule).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--since", default="24h", help="fenêtre glissante: 24h, 7d, 60m…")
    g.add_argument("--day", help="journée UTC précise: AAAA-MM-JJ")
    ap.add_argument("--json", action="store_true", help="sortie structurée")
    ap.add_argument("--notify-cmd", default=os.environ.get("RD_NOTIFY_CMD"),
                    help="commande recevant le digest sur stdin (opt-in)")
    args = ap.parse_args()

    rows = load_jsonl(HISTORY)
    alerts = load_jsonl(ALERTS)

    if args.day:
        try:
            t0 = calendar.timegm(time.strptime(args.day, "%Y-%m-%d"))
        except ValueError:
            sys.exit("date invalide (attendu AAAA-MM-JJ)")
        t1 = t0 + 86400
    else:
        # « maintenant » = dernier ts connu (robuste au décalage d'horloge modem)
        now = max((r.get("ts", 0) for r in rows), default=int(time.time()))
        t1 = now + 1
        t0 = now - parse_since(args.since)

    d = build(rows, alerts, t0, t1)
    text = render(d)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(text)
    if args.notify_cmd:
        try:
            subprocess.run(args.notify_cmd, shell=True, input=text, text=True, timeout=15)
        except Exception as e:
            print("warn notify_cmd:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
