#!/usr/bin/env python3
"""
gps-heatmap.py — agrège le dataset position+signal (heatmap.jsonl de gps-fix --tag)
en une carte de couverture : résumé texte + export GeoJSON (visualisable hors-ligne
dans geojson.io, QGIS, Leaflet, etc. — aucun service externe requis).

Regroupe les relevés par cellule géographique (arrondi lat/lon) et calcule le RSRP/SINR
moyen par cellule. Utile pour repérer où le signal est bon/mauvais avec ce routeur nomade.

  python3 tools/gps-heatmap.py                       # résumé texte
  python3 tools/gps-heatmap.py --geojson cover.json  # + export GeoJSON (cellules)
  python3 tools/gps-heatmap.py --points pts.json     # export des points bruts
  python3 tools/gps-heatmap.py --precision 3         # taille de cellule (décimales lat/lon)

SÛRETÉ : lecture seule de fichiers locaux. Aucune action réseau/routeur. Zéro dépendance.
Entrée : heatmap.jsonl sous RM_STATE (défaut ~/.radio-monitor/).
"""
import argparse
import json
import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("RM_STATE", Path.home() / ".radio-monitor"))
HEATMAP = STATE_DIR / "heatmap.jsonl"


def load():
    rows = []
    if not HEATMAP.exists():
        return rows
    with HEATMAP.open() as f:
        for line in f:
            try:
                r = json.loads(line)
                if isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lon"), (int, float)):
                    rows.append(r)
            except ValueError:
                continue
    return rows


def rsrp_color(v):
    if v is None:
        return "#8b949e"
    if v >= -90:
        return "#3fb950"   # excellent
    if v >= -100:
        return "#d29922"   # moyen
    return "#f85149"       # faible


def avg(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def aggregate(rows, prec):
    cells = {}
    for r in rows:
        key = (round(r["lat"], prec), round(r["lon"], prec))
        cells.setdefault(key, []).append(r)
    out = []
    for (lat, lon), rs in cells.items():
        out.append({
            "lat": lat, "lon": lon, "n": len(rs),
            "rsrp_avg": avg([x.get("rsrp") for x in rs]),
            "rsrp_min": min([x["rsrp"] for x in rs if isinstance(x.get("rsrp"), (int, float))], default=None),
            "sinr_avg": avg([x.get("sinr") for x in rs]),
        })
    return out


def geojson_cells(cells):
    feats = []
    for c in cells:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
            "properties": {
                "n": c["n"], "rsrp_avg": c["rsrp_avg"], "rsrp_min": c["rsrp_min"],
                "sinr_avg": c["sinr_avg"], "marker-color": rsrp_color(c["rsrp_avg"]),
                "title": "RSRP %s dBm / SINR %s dB (%s pts)" % (c["rsrp_avg"], c["sinr_avg"], c["n"]),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def geojson_points(rows):
    feats = []
    for r in rows:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {"t": r.get("t"), "rsrp": r.get("rsrp"), "sinr": r.get("sinr"),
                           "net": r.get("net"), "marker-color": rsrp_color(r.get("rsrp"))},
        })
    return {"type": "FeatureCollection", "features": feats}


def main():
    ap = argparse.ArgumentParser(description="Agrège position+signal en carte de couverture (GeoJSON).")
    ap.add_argument("--precision", type=int, default=4, help="décimales lat/lon pour la cellule (4≈11m)")
    ap.add_argument("--geojson", metavar="FICHIER", help="écrit le GeoJSON agrégé (cellules)")
    ap.add_argument("--points", metavar="FICHIER", help="écrit le GeoJSON des points bruts")
    ap.add_argument("--json", action="store_true", help="résumé structuré sur stdout")
    args = ap.parse_args()

    rows = load()
    cells = aggregate(rows, args.precision)

    if args.geojson:
        Path(args.geojson).write_text(json.dumps(geojson_cells(cells), indent=1))
    if args.points:
        Path(args.points).write_text(json.dumps(geojson_points(rows), indent=1))

    if not rows:
        print("Aucune donnée position+signal (heatmap.jsonl vide). Lance `gps-fix.py --watch --tag` avec un fix.")
        return

    lats = [r["lat"] for r in rows]
    lons = [r["lon"] for r in rows]
    best = max(cells, key=lambda c: (c["rsrp_avg"] is not None, c["rsrp_avg"] or -999))
    worst = min(cells, key=lambda c: (c["rsrp_avg"] is None, c["rsrp_avg"] or 999))
    summary = {
        "points": len(rows), "cells": len(cells),
        "bbox": {"lat_min": min(lats), "lat_max": max(lats), "lon_min": min(lons), "lon_max": max(lons)},
        "rsrp_avg_global": avg([r.get("rsrp") for r in rows]),
        "best_cell": best, "worst_cell": worst,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("=== gps-heatmap ===")
        print("Points : %d · cellules : %d (précision %d déc.)" % (len(rows), len(cells), args.precision))
        print("Zone   : lat %.5f→%.5f · lon %.5f→%.5f" % (min(lats), max(lats), min(lons), max(lons)))
        print("RSRP moyen global : %s dBm" % summary["rsrp_avg_global"])
        print("Meilleure cellule : %.5f,%.5f — RSRP %s (%s pts)" % (best["lat"], best["lon"], best["rsrp_avg"], best["n"]))
        print("Pire cellule      : %.5f,%.5f — RSRP %s (%s pts)" % (worst["lat"], worst["lon"], worst["rsrp_avg"], worst["n"]))
    if args.geojson:
        print("GeoJSON écrit -> %s (ouvrable dans geojson.io / QGIS / Leaflet)" % args.geojson)


if __name__ == "__main__":
    main()
