# Diagnostic de stabilité du lien cellulaire — 2026-08-17

Preuves expurgées : [`evidence/20260817T142318Z-stability-diagnosis/`](../evidence/20260817T142318Z-stability-diagnosis/)
(baseline, fenêtre live 14:30Z–14:44Z, `metadata.txt`).

Les estampilles des captures mélangent deux horloges : `logread`, `dmesg` et la
surveillance modem sont en heure locale (CEST, UTC+2), la boucle AT et le guet de
reconnexion sont en UTC. Les heures sont reprises ici telles qu'elles figurent dans les
fichiers.

Session **strictement en lecture seule**, conforme aux tests autorisés de
[`EXPERIMENT-PROTOCOL.md`](EXPERIMENT-PROTOCOL.md) §1. Aucune écriture, aucun redémarrage
de service, aucune commande AT de configuration. Aucun écart au protocole à signaler.

## Ce que cherchait la session

Des coupures du lien cellulaire étaient ressenties. Hypothèse falsifiable posée avant la
collecte : *une coupure récente a laissé une trace exploitable dans `logread`/`dmesg`, ou
se lit dans une dégradation radio concomitante.*

**L'hypothèse n'est pas vérifiée, et le résultat le plus utile de la session est négatif** :
sur cet appareil, les journaux embarqués ne permettent pas le post-mortem d'une coupure.

## 1. Le journal ne remonte pas assez loin — `OBSERVÉ`

C'est le constat déterminant.

| Capture | Lignes | Fenêtre couverte |
|---|---:|---|
| `logread-raw.txt` | 421 | 16:17:33 → 16:23:56 (6 min 23 s) |
| `logread-4000.txt` | 523 | 16:26:07 → 16:26:49 (**42 s**) |
| `live-.../logread-tail.txt` | 486 | 16:29:48 → 16:44:19 (14 min 31 s) |

Le tampon circulaire plafonne autour de **420–520 lignes**. La demande explicite de 4000
lignes en rend 523 : le reste n'existe plus. Ce que couvrent ces 523 lignes dépend
entièrement du débit d'écriture du moment — ici **42 secondes**.

Ce qui remplit le tampon, sur ces mêmes 42 s :

| Émetteur | Lignes | Part |
|---|---:|---:|
| `QCMAP` (scripts `backhaulCommonConfig.sh`, `nat_alg_vpn_config.sh`) | 227 | 43 % |
| `root` | 82 | 16 % |
| `procd` | 42 | 8 % |
| `dnsmasq`, `tftp_server`, `Diag-Router`, `Diag_Lib`, kernel | 99 | 19 % |

`QCMAP` écrit à lui seul **~5,4 lignes par seconde**, en boucle, des traces de niveau
`uci -q get qcmap_wlan.@stamodeconfig[0].bridge_mode`.

`dmesg` ne sauve pas la mise : **510 des 778 lignes (66 %)** sont deux messages du pilote
Wi-Fi — `lim_drop_unprotected_action_frame` (259) et `wma_process_rmf_frame` (251) — et le
tampon ne couvre qu'environ 20 minutes (16:04:00 → 16:23:55).

`INFÉRÉ` : une coupure WAN survenue ne serait-ce que trois minutes plus tôt ne laisse
aucune trace lisible. Toute recherche de cause *après coup* sur cet appareil est vaine ;
il faut une collecte **externe et continue**. C'est ce qui a motivé
[`radio-monitor.py`](RADIO-MONITOR.md), écrit ensuite.

## 2. Le `ping` depuis le routeur ne mesure pas la disponibilité — `OBSERVÉ`

`live-.../modem-ping-watch-60x5s.txt` : 60 relevés à 5 s d'intervalle, de 16:48:55 à
16:53:55.

```text
16:48:55 modem=UP ping=FAIL -
...  (60 relevés identiques)
16:53:55 modem=UP ping=FAIL -
```

**100 % d'échec ICMP pendant 5 minutes**, alors que l'interface modem reste `UP` et que le
trafic passe : les 20 sondes depuis le poste, de 16:47:46 à 16:48:45, aboutissent toutes —
soit jusqu'à dix secondes avant le premier `ping=FAIL`. Plus tôt dans la session, la sonde
HTTPS de la baseline répondait `http=200` en 1,09 s.

Ceci **reproduit** le filtrage ICMP déjà consigné dans [`SQM.md`](SQM.md) : `REPRODUIT`.
Conséquence pratique — un garde-fou ou un watchdog qui conclurait à la coupure sur l'échec
d'un `ping` depuis le routeur se déclencherait en permanence sur un lien parfaitement
fonctionnel.

## 3. Aucune coupure ne s'est produite pendant l'observation — `OBSERVÉ`

- `live-.../reconnect-hunt-6m.txt` : 12 fenêtres de 30 s, **toutes vides**. Aucun
  événement de reconnexion.
- `modem-interface-status.json` : interface `rmnet_data1` `up`, `uptime` **845 s** au
  moment de la capture — l'interface avait donc été établie ~14 min plus tôt, et n'a pas
  bougé de la session.
- Latence depuis le poste, 20 sondes sur 60 s : **médiane 63,4 ms, min 15,6 ms, max
  296,3 ms**. Aucune perte, mais une gigue franche (facteur 19 entre extrêmes).

Le lien était donc **instable en latence, jamais interrompu**, sur la fenêtre observée.

## 4. État radio pendant la fenêtre — `OBSERVÉ`

Boucle AT de 16 échantillons à 10 s (`live-.../at-loop.txt`) :

| Grandeur | Valeurs |
|---|---|
| `AT+CSQ` | 17 à 24 (RSSI ≈ −79 à −65 dBm), médiane 22 |
| Ancrage | `FDD LTE` bande 7, EARFCN 2850 — 15 échantillons sur 16 |
| Porteuse NR | `TDD NR5G` bande n78 — 14 échantillons sur 16 |
| Anomalies | **1 × `No Service`** à 14:32:05Z, puis **1 × bascule `NR5G BAND 8`** à 14:32:15Z |

Agrégation relevée par `AT+QCAINFO` : PCC LTE B7 + SCC B3 + SCC B20 + SCC NR n78, soit
quatre porteuses. Signal médiocre côté NR : RSRP −106 dBm, SINR 8 dB.

Températures (`AT+QTEMP`) : `sdr0` 36 °C, `cpuss-*` 47 °C, `mdmss-*` 44–46 °C. Rien qui
approche un seuil de throttling.

Charge système : uptime 10 j 13 h 54, `load average` 1,47, mémoire 429 Mo utilisés sur
1598, pression mémoire PSI nulle sur les trois fenêtres. `INFÉRÉ` : ni la thermique ni la
saturation de l'appareil ne sont des pistes pour les coupures ressenties.

Le `No Service` isolé de 14:32:05Z est le seul candidat sérieux de la session. `NON
TESTÉ` : rien ne permet de le relier à une coupure ressentie — un seul échantillon, pas de
corrélation possible faute de journal (§1), et aucun impact visible sur l'interface, qui
n'a pas redémarré.

## 5. Résultat négatif conservé

`live-.../ping-to-1.1.1.1-120s.txt` est **vide** : la sonde de 120 s n'a produit aucune
ligne. Défaillance de collecte, non analysée. Fichier conservé tel quel conformément à
§4 du protocole.

## 6. Ce que la session ne dit pas

- **La cause des coupures ressenties reste `NON TESTÉE`.** Aucune coupure ne s'est
  produite pendant les ~21 minutes d'observation ; on ne peut pas diagnostiquer ce qui ne
  se manifeste pas.
- Une seule session, une seule cellule, une seule heure. Aucune répétition.
- Le débit n'a pas été mesuré : la session est en lecture seule et ne charge pas le lien.
- La taille du tampon syslog (`system.@system[0].log_size`) n'a pas été relevée ; le
  plafond de 420–520 lignes est constaté sur les sorties, pas lu dans la configuration.
  `NON TESTÉ`.

## 7. Suite

1. Collecte externe continue plutôt que post-mortem embarqué — fait, voir
   [`RADIO-MONITOR.md`](RADIO-MONITOR.md).
2. `NON TESTÉ` : relever `log_size` et évaluer si l'augmenter, ou faire taire les traces
   `QCMAP`, rendrait le journal exploitable. À traiter comme un changement de
   configuration, avec les préconditions de §2 du protocole.
3. `NON TESTÉ` : le bruit `wma_process_rmf_frame` du pilote Wi-Fi mérite d'être qualifié
   pour lui-même — il sature `dmesg` indépendamment du lien cellulaire.
