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
python3 tools/radio-monitor.py --serve     # démon + dashboard http://127.0.0.1:8090
python3 tools/radio-monitor.py --serve --bind 192.168.8.1   # exposer au LAN (voir ci-dessous)
```

Variables : `GLINET_PASSWORD`, `GLINET_HOST` (défaut `192.168.8.1`), `RM_INTERVAL` (30 s),
`RM_PORT` (8090), `RM_BIND` (`127.0.0.1`), `RM_BUS` (`cpu`), `RM_STATE` (défaut
`~/.radio-monitor/`).

### Adresse d'écoute

Le dashboard **n'a aucune authentification**. Il écoute donc sur `127.0.0.1` par défaut :
seuls les processus locaux — dont le service caché Tor, qui se connecte à
`127.0.0.1:8090` — y accèdent. L'exposer au LAN est un choix explicite
(`--bind 192.168.8.1` ou `RM_BIND`), et l'agent affiche alors un avertissement au
démarrage. Ne jamais binder `0.0.0.0` sur un routeur : la restriction ne reposerait
plus que sur le pare-feu.

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

## Alertes — `radio-alert.py`

Couche d'alerte au-dessus de l'historique. **Lecture seule et découplée** : elle n'appelle
jamais le routeur, elle analyse `history.jsonl`. Conditions :

- **seuils** RSRP / SINR (WARN puis CRIT) ;
- **anomalie** : chute rapide vs baseline glissante (écart en dB ou z-score) — alerte
  *avant* la coupure franche ;
- **péremption** : plus aucun nouvel échantillon depuis `RA_STALE_S` s ⇒ buffer figé,
  coupure probable.

Hystérésis : émission uniquement aux transitions (montée d'alerte, changement de
conditions, rétablissement), via `alert-state.json`. Journal dans `alerts.jsonl`. Codes de
sortie `0/1/2` = OK/WARN/CRIT (pratique en cron).

```bash
python3 tools/radio-alert.py --check          # une évaluation puis quitte (cron)
python3 tools/radio-alert.py --watch          # démon : évalue en boucle
python3 tools/radio-alert.py --check --json   # sortie structurée (stdout JSON pur)
```

**Notification opt-in.** Par défaut : log seul (`alerts.jsonl` + stderr). Pour *envoyer*
réellement (SMS via `sendsms`, push, webhook), fournir une commande qui reçoit la ligne
d'alerte sur stdin : `--notify-cmd '…'` ou `RA_NOTIFY_CMD`. C'est une **action sortante** :
la brancher est un choix explicite, hors du périmètre lecture seule.

Réglages (env) : `RA_RSRP_WARN` (−105), `RA_RSRP_CRIT` (−113), `RA_SINR_WARN` (3),
`RA_SINR_CRIT` (0), `RA_DROP_DB` (8), `RA_ZSCORE` (2.5), `RA_WINDOW` (60), `RA_STALE_S` (120).

## Synthèse — `radio-digest.py`

Agrège `history.jsonl` + `alerts.jsonl` sur une fenêtre et produit un rapport lisible
(lecture seule, n'appelle pas le routeur) : disponibilité estimée (part d'échantillons de
qualité ≥ moyenne), RSRP/SINR min/p10/moy/max, distribution de qualité, types réseau,
**pire créneau de 10 min** (RSRP moyen le plus bas), et bilan des alertes (levées/rétablies,
temps dégradé cumulé, pire dégradation).

```bash
python3 tools/radio-digest.py                  # 24 dernières heures
python3 tools/radio-digest.py --since 7d        # fenêtre glissante
python3 tools/radio-digest.py --day 2026-08-23  # une journée UTC
python3 tools/radio-digest.py --json            # sortie structurée
```

La fenêtre glissante prend « maintenant » = dernier `ts` de l'historique (robuste au décalage
d'horloge modem). Notification opt-in : `--notify-cmd` / `RD_NOTIFY_CMD` (envoi mail/SMS/push).

## Limites et suites

- Pas encore de corrélation avec le **débit** : il faudrait une source de trafic
  (`/proc/net/dev` du modem, ou une méthode RPC de compteurs) échantillonnée en parallèle.
- `get_signals` expose un horodatage modem ; l'agent ne corrige pas de dérive d'horloge.
- La péremption s'appuie sur l'avancée de `max_ts` en temps réel : robuste au décalage
  d'horloge modem, mais suppose que `radio-monitor` tourne pour alimenter l'historique.
