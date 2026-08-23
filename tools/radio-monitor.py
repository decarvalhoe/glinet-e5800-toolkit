#!/usr/bin/env python3
"""
radio-monitor.py - agent de télémétrie radio passif pour GL.iNet E5800 (firmware 4.x).

Interroge périodiquement `modem get_signals` (JSON-RPC, via glinet.py) et accumule
l'historique horodaté du signal cellulaire : RSRP, RSRQ, SINR, type réseau, force.
Calcule des statistiques glissantes et sert un petit tableau de bord (stdlib).

Objectif : le point « historique radio passif corrélé au débit » de la feuille de route
Niveau 3 de docs/COUNTER-EXPERTISE.md. Le signal chute souvent AVANT une coupure ; en
garder la trace permet de dater/quantifier l'instabilité d'un lien cellulaire.

SÛRETÉ (phase 1) : STRICTEMENT LECTURE SEULE. La seule méthode RPC appelée est
`modem get_signals`, qui lit un buffer maintenu par le modem. Aucune écriture, aucun
changement de bande/cellule/SIM/APN, aucun redémarrage de service. Rien ne peut couper
le WAN. Voir docs/COUNTER-EXPERTISE.md § « Contrainte de sûreté déterminante ».

Zéro dépendance (stdlib uniquement). Réutilise le client revalidé tools/glinet.py.

  export GLINET_PASSWORD='...'
  python3 tools/radio-monitor.py --once            # un relevé, résumé, puis quitte
  python3 tools/radio-monitor.py                   # démon : collecte en continu
  python3 tools/radio-monitor.py --serve           # démon + dashboard http://<hôte>:8090
  python3 tools/radio-monitor.py --json            # un relevé, sortie JSON brute (pipeline)

État runtime (non versionné) : $RM_STATE ou ~/.radio-monitor/
  history.jsonl   un échantillon unique par ligne (dédupliqué par timestamp)
  state.json      dernier instantané + stats + historique récent (pour le dashboard)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# --- réutilise le client JSON-RPC revalidé (zéro dépendance) ---------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from glinet import Glinet, GlinetError  # noqa: E402

BUS = os.environ.get("RM_BUS", "cpu")
INTERVAL = float(os.environ.get("RM_INTERVAL", "30"))     # s entre deux relevés
PORT = int(os.environ.get("RM_PORT", "8090"))
STATE_DIR = Path(os.environ.get("RM_STATE", Path.home() / ".radio-monitor"))
RECENT_MAX = 240                                          # points gardés pour le graphe

# Seuils de qualité (dBm / dB). SOURCE EXTERNE : ordres de grandeur usuels LTE/NR.
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


def poll(g):
    """Retourne la liste d'échantillons de signal (lecture seule)."""
    res = g.call("modem", "get_signals", {"bus": BUS})
    sig = res.get("signals", []) if isinstance(res, dict) else []
    out = []
    for s in sig:
        ts = s.get("timestamp")
        rsrp = s.get("rsrp")
        if not ts or rsrp in (None, 0):      # rsrp==0 => pas de mesure valable
            continue
        out.append({
            "ts": int(ts),
            "rsrp": rsrp,
            "rsrq": s.get("rsrq"),
            "sinr": s.get("sinr"),
            "net": s.get("network_type"),
            "slot": s.get("slot"),
            "strength": s.get("strength"),
        })
    return out


class History:
    def __init__(self, state_dir):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "history.jsonl"
        self.state = self.dir / "state.json"
        self.seen = set()
        self.recent = []
        self._load_seen()

    def _load_seen(self):
        if not self.jsonl.exists():
            return
        try:
            with self.jsonl.open() as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        self.seen.add(r["ts"])
                        self.recent.append(r)
                    except (ValueError, KeyError):
                        continue
        except OSError:
            pass
        self.recent = self.recent[-RECENT_MAX:]

    def add(self, samples):
        added = 0
        with self.jsonl.open("a") as f:
            for s in sorted(samples, key=lambda x: x["ts"]):
                if s["ts"] in self.seen:
                    continue
                self.seen.add(s["ts"])
                f.write(json.dumps(s) + "\n")
                self.recent.append(s)
                added += 1
        self.recent = self.recent[-RECENT_MAX:]
        return added

    def summary(self):
        if not self.recent:
            return {"count": 0, "updated": _now_iso()}
        def stat(key):
            vals = [r[key] for r in self.recent if isinstance(r.get(key), (int, float))]
            if not vals:
                return None
            return {"min": min(vals), "max": max(vals),
                    "avg": round(sum(vals) / len(vals), 1), "last": self.recent[-1].get(key)}
        cur = self.recent[-1]
        nets = {}
        strg = {}
        for r in self.recent:
            nets[r.get("net")] = nets.get(r.get("net"), 0) + 1
            strg[r.get("strength")] = strg.get(r.get("strength"), 0) + 1
        span = self.recent[-1]["ts"] - self.recent[0]["ts"]
        return {
            "updated": _now_iso(),
            "count_total": len(self.seen),
            "count_recent": len(self.recent),
            "span_recent_s": span,
            "network_types": nets,
            "strength_hist": {str(k): v for k, v in strg.items()},
            "current": {
                "rsrp": cur.get("rsrp"), "rsrq": cur.get("rsrq"), "sinr": cur.get("sinr"),
                "net": cur.get("net"), "slot": cur.get("slot"), "strength": cur.get("strength"),
                "quality": quality(cur.get("rsrp"), cur.get("sinr")),
                "ts": cur.get("ts"),
            },
            "rsrp": stat("rsrp"), "rsrq": stat("rsrq"), "sinr": stat("sinr"),
        }

    def write_state(self):
        s = self.summary()
        s["recent"] = self.recent
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=1))
        tmp.replace(self.state)
        return s


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- dashboard (stdlib) -----------------------------------------------------
def _svg_spark(vals, lo, hi, w=480, h=48, color="#58a6ff"):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    n = len(vals)
    def x(i): return round(i * (w - 2) / (n - 1) + 1, 1)
    def y(v):
        t = max(0.0, min(1.0, (v - lo) / (hi - lo)))
        return round(h - 1 - t * (h - 2), 1)
    pts = " ".join("%s,%s" % (x(i), y(v)) for i, v in enumerate(vals))
    return ('<svg width="%d" height="%d" viewBox="0 0 %d %d">'
            '<polyline fill="none" stroke="%s" stroke-width="1.5" points="%s"/></svg>'
            % (w, h, w, h, color, pts))


def dashboard_html(state):
    c = state.get("current", {})
    qual = c.get("quality", "inconnu")
    qcolor = {"excellent": "#3fb950", "bon": "#57ab5a", "moyen": "#d29922",
              "faible": "#f85149", "inconnu": "#8b949e"}.get(qual, "#8b949e")
    recent = state.get("recent", [])
    rsrp_svg = _svg_spark([r.get("rsrp") for r in recent], -120, -70, color="#58a6ff")
    sinr_svg = _svg_spark([r.get("sinr") for r in recent], -5, 30, color="#3fb950")
    def stat_line(name, st, unit):
        if not st:
            return "<tr><td>%s</td><td>—</td></tr>" % name
        return ("<tr><td>%s</td><td><b>%s %s</b> <small>(min %s · moy %s · max %s)</small></td></tr>"
                % (name, st.get("last"), unit, st.get("min"), st.get("avg"), st.get("max")))
    nets = " · ".join("%s:%s" % (k, v) for k, v in (state.get("network_types") or {}).items())
    return """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=10><title>radio-monitor</title>
<style>body{{background:#0d1117;color:#c9d1d9;font:15px/1.5 system-ui,sans-serif;margin:0;padding:20px}}
h1{{font-size:19px;margin:0 0 2px}}.q{{color:{qcolor};font-weight:700}}
table{{border-collapse:collapse;width:100%;max-width:560px;margin-top:12px}}
td{{padding:6px 10px;border-bottom:1px solid #21262d}}td:first-child{{color:#8b949e;white-space:nowrap}}
small{{color:#6e7681}}svg{{background:#010409;border-radius:4px}}</style></head><body>
<h1>📡 radio-monitor — signal <span class=q>{qual}</span></h1>
<small>{net} · {count} pts · maj {updated} · lecture seule (modem get_signals)</small>
<table>
<tr><td>RSRP</td><td>{svg1}</td></tr>
{rsrp}
<tr><td>SINR</td><td>{svg2}</td></tr>
{sinr}
{rsrq}
<tr><td>Types réseau</td><td>{nets}</td></tr>
<tr><td>Échantillons</td><td>{count} récents / {total} au total</td></tr>
</table></body></html>""".format(
        qcolor=qcolor, qual=qual, net=c.get("net", "—"),
        count=state.get("count_recent", 0), total=state.get("count_total", 0),
        updated=state.get("updated", ""), svg1=rsrp_svg, svg2=sinr_svg, nets=nets,
        rsrp=stat_line("RSRP", state.get("rsrp"), "dBm"),
        sinr=stat_line("SINR", state.get("sinr"), "dB"),
        rsrq=stat_line("RSRQ", state.get("rsrq"), "dB"),
    )


def serve(hist, port):
    import http.server
    import socketserver
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            try:
                state = json.loads(hist.state.read_text())
            except (OSError, ValueError):
                state = {}
            if self.path.startswith("/state"):
                body = json.dumps(state).encode()
                ctype = "application/json"
            else:
                body = dashboard_html(state).encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = socketserver.ThreadingTCPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("radio-monitor : dashboard http://0.0.0.0:%d (LAN)" % port)


def main():
    ap = argparse.ArgumentParser(description="Agent de télémétrie radio passif (lecture seule).")
    ap.add_argument("--once", action="store_true", help="un seul relevé puis quitte")
    ap.add_argument("--json", action="store_true", help="un relevé, JSON brut (implique --once)")
    ap.add_argument("--serve", action="store_true", help="démon + dashboard HTTP")
    ap.add_argument("--interval", type=float, default=INTERVAL, help="secondes entre relevés")
    ap.add_argument("--host", default=os.environ.get("GLINET_HOST", "192.168.8.1"))
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    g = Glinet(host=args.host)
    try:
        g.ensure_session()
    except (GlinetError, SystemExit) as e:
        sys.exit("Auth échouée : %s" % e)

    hist = History(STATE_DIR)

    def one():
        try:
            samples = poll(g)
        except GlinetError:
            g.ensure_session()          # session expirée -> relogin
            samples = poll(g)
        hist.add(samples)
        return hist.write_state()

    if args.json:
        print(json.dumps(one(), indent=2, ensure_ascii=False))
        return
    if args.once:
        s = one()
        cur = s.get("current", {})
        print("=== radio-monitor (relevé) ===")
        print("Réseau   :", cur.get("net"), "· slot", cur.get("slot"))
        print("Signal   : RSRP", cur.get("rsrp"), "dBm · RSRQ", cur.get("rsrq"),
              "dB · SINR", cur.get("sinr"), "dB =>", cur.get("quality", "").upper())
        print("Historique:", s.get("count_total"), "échantillons ·",
              "fenêtre récente", s.get("span_recent_s"), "s")
        return

    if args.serve:
        serve(hist, args.port)
    print("radio-monitor : collecte toutes les %gs (Ctrl-C pour arrêter)" % args.interval)
    while True:
        try:
            s = one()
            cur = s.get("current", {})
            print("%s  RSRP %s dBm  SINR %s dB  %s  (%s pts)" % (
                s.get("updated"), cur.get("rsrp"), cur.get("sinr"),
                cur.get("quality"), s.get("count_total")))
        except Exception as e:      # ne jamais mourir sur une erreur transitoire
            print("warn:", e, file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
