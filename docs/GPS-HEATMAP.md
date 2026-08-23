# GPS & heatmap de couverture

Outils : [`tools/gps-fix.py`](../tools/gps-fix.py) et [`tools/gps-heatmap.py`](../tools/gps-heatmap.py)
Date : 2026-08-23

Corrèle le signal cellulaire (RSRP/SINR de radio-monitor) avec la **position GNSS** du modem
(Quectel RG650) pour cartographier la couverture — utile pour un routeur nomade.

## Pré-requis : activer le GNSS (action modem)

Le moteur GNSS doit être démarré une fois. C'est une **écriture AT sur le modem** (classe
d'action sensible : le modem porte l'unique WAN), donc à faire **explicitement** :

```sh
# activer (une commande) — indépendant de la session data, mais c'est une écriture modem
ubus call modem.CPU.AT get_result_AT '{"cmd":"AT+QGPS=1"}'
# désactiver (économise la batterie)
ubus call modem.CPU.AT get_result_AT '{"cmd":"AT+QGPS=0"}'
```

Sur cet appareil, `edgnss-daemon` existe mais ne remplit pas `/dev/gps` de façon fiable ;
les outils lisent donc le fix **directement par AT** (`AT+QGPSLOC`), ce qui est robuste.

## `gps-fix.py` — lire le fix (LECTURE SEULE)

N'envoie que des **requêtes AT de lecture** (`AT+QGPSLOC=2`, degrés décimaux). Ne touche pas
au WAN, n'active pas le modem. Gère l'état « no fix ».

```sh
python3 tools/gps-fix.py --once           # un relevé (position, ou "no fix")
python3 tools/gps-fix.py --json            # JSON
python3 tools/gps-fix.py --watch --tag     # boucle : log + tague heatmap.jsonl (position+signal)
```

`--tag` lit le signal courant dans le `state.json` de radio-monitor et écrit un enregistrement
`{lat, lon, alt, sats, hdop, rsrp, sinr, net}` dans `heatmap.jsonl` à chaque fix.

## `gps-heatmap.py` — carte de couverture

Agrège `heatmap.jsonl` par cellule géographique (arrondi lat/lon) → RSRP/SINR moyen par
cellule, meilleure/pire zone, et **export GeoJSON** ouvrable hors-ligne (geojson.io, QGIS,
Leaflet) — aucun service externe.

```sh
python3 tools/gps-heatmap.py                       # résumé texte
python3 tools/gps-heatmap.py --geojson cover.json  # + GeoJSON (cellules, couleur = RSRP)
python3 tools/gps-heatmap.py --points pts.json     # points bruts
python3 tools/gps-heatmap.py --precision 3         # taille de cellule (déc. lat/lon)
```

## Preuves — `OBSERVÉ` 2026-08-23

- `AT+QGPS?` → `+QGPS: 0`, puis après `AT+QGPS=1` → `+QGPS: 1` (bascule confirmée).
- `AT+QGPSGNMEA="GGA"` → `$GPGGA,,,,,,0,,,...*66` : NMEA produit, **fix quality = 0**
  (pipeline OK, aucun satellite — relevé en intérieur).
- `AT+QGPSLOC?` → `+CME ERROR: 516` (« not fixed now »).
- Parsing `gps-fix` validé sur un fix simulé (lat/lon/alt/HDOP/sats corrects) ; agrégation
  et export GeoJSON de `gps-heatmap` validés sur dataset synthétique.

Statut : activation GNSS et voie AT `OBSERVÉ` ; **fix réel non obtenu** (vue du ciel requise).
Les seuils de couleur RSRP sont `SOURCE EXTERNE`.

## Limite

`/dev/gps` reste vide via `edgnss-daemon` sur cet appareil (voie AT utilisée à la place).
Un vrai point nécessite une vue dégagée ; en intérieur, le GNSS n'accroche pas.
