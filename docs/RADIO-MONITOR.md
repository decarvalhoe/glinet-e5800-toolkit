# radio-monitor — télémétrie radio passive

Outil : [`tools/radio-monitor.py`](../tools/radio-monitor.py)
Date de rédaction : 2026-08-23

Répond au point Niveau 3 de [`COUNTER-EXPERTISE.md`](COUNTER-EXPERTISE.md) :
« historique radio passif corrélé au débit, sans lock de bande/cellule ».

## Ce que ça fait

Interroge périodiquement `modem get_signals` (JSON-RPC, via `glinet.py`) et accumule
l'historique horodaté du signal cellulaire : RSRP, RSRQ, SINR, type réseau, force, slot.
Déduplique par `timestamp`, calcule des statistiques glissantes (min/moy/max) et sert un
petit tableau de bord (bibliothèque standard, SVG en ligne, aucun asset externe).

Le signal se dégrade souvent **avant** une coupure ; en conserver la trace permet de dater
et quantifier l'instabilité d'un lien cellulaire, sans rien changer sur le routeur.

## Sûreté

**STRICTEMENT LECTURE SEULE.** La seule méthode RPC appelée est `modem get_signals`, qui
lit un buffer maintenu par le modem. Aucune écriture, aucun changement de bande / cellule /
SIM / APN, aucun redémarrage de service. Conforme à la contrainte de sûreté phase 1
(§ « Contrainte de sûreté déterminante » de COUNTER-EXPERTISE.md) : rien ne peut couper le WAN.

## Usage

```bash
export GLINET_PASSWORD='...'
python3 tools/radio-monitor.py --once      # un relevé + résumé
python3 tools/radio-monitor.py --json      # un relevé, JSON brut (pipeline)
python3 tools/radio-monitor.py             # démon : collecte en continu
python3 tools/radio-monitor.py --serve     # démon + dashboard http://<hôte>:8090
```

Variables : `GLINET_PASSWORD`, `GLINET_HOST` (défaut `192.168.8.1`), `RM_INTERVAL` (30 s),
`RM_PORT` (8090), `RM_BUS` (`cpu`), `RM_STATE` (défaut `~/.radio-monitor/`).

État runtime, **non versionné** (`~/.radio-monitor/` par défaut, hors du dépôt) :
- `history.jsonl` — un échantillon unique par ligne, dédupliqué par `timestamp` ;
- `state.json` — dernier instantané + stats + historique récent (lu par le dashboard).

## Seuils de qualité

`SOURCE EXTERNE` (ordres de grandeur usuels LTE/NR, non spécifiques à ce modem) :

| Qualité | RSRP | SINR |
|---|---|---|
| excellent | ≥ −90 dBm | ≥ 13 dB |
| bon | ≥ −100 | ≥ 5 |
| moyen | ≥ −110 | ≥ 0 |
| faible | < −110 | < 0 |

## Revalidation de `glinet.py` — `OBSERVÉ` 2026-08-23

Le client CLI (marqué « à revalider » dans le README) a été rejoué contre l'appareil réel :

- `login` : challenge → `alg:5` (sha256-crypt) → `sid` obtenu ; **succès**.
- `call modem get_signals {"bus":"cpu"}` : renvoie un **buffer horodaté** d'environ 180
  échantillons (~30 min à un pas de 10 s), chacun avec `network_type`, `rsrp`, `rsrq`,
  `sinr`, `strength`, `slot`, `timestamp`.
- `call modem get_cell_tower {"bus":"cpu"}` : `slot1`/`slot2` **vides** sur cet appareil —
  ce n'est donc pas une source de signal live ici ; `get_signals` l'est.

Échantillon observé (SIM slot 2) : `NR5G-NSA`, RSRP ≈ −80 dBm, RSRQ −10 dB, SINR ≈ 22 dB.

Statut des affirmations : l'exactitude du hash `glinet.py` et l'accès aux méthodes ci-dessus
sont `OBSERVÉ`. Les seuils de qualité restent `SOURCE EXTERNE`. Aucune corrélation débit
n'est encore mesurée (voir ci-dessous).

## Limites et suites

- Pas encore de corrélation avec le **débit** : il faudrait une source de trafic
  (`/proc/net/dev` du modem, ou une méthode RPC de compteurs) échantillonnée en parallèle.
- Pas d'alerte encore (seuil / anomalie). Prévu comme couche au-dessus de `state.json`.
- `get_signals` expose un horodatage modem ; l'agent ne corrige pas de dérive d'horloge.
