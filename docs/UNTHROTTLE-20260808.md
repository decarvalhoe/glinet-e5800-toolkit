# Retrait du plafond SQM fixe — 2026-08-08

Preuves expurgées : [`evidence/20260808T064135Z-unthrottle/`](../evidence/20260808T064135Z-unthrottle/)
(état `uci` et `tc` avant/après, copie de `/etc/config/sqm` avant changement, `metadata.txt`).

## Résumé

Le plafond ingress fixe de 5 Mbit/s posé le 2026-08-06 sur `sqm.modem` a été relevé à
45 Mbit/s à la demande explicite de l'opérateur humain. `autorate-ingress` n'a
délibérément **pas** été restauré.

État final `OBSERVÉ` :

- `sqm.modem.download='45000'` ;
- `sqm.modem.iqdisc_opts='nat dual-dsthost ingress'` (inchangé, sans `autorate-ingress`) ;
- CAKE actif sur `ifb4rmnet_data1` à `45Mbit` ;
- WAN `rmnet_data1` up, route par défaut présente ;
- empreinte `/etc/config/sqm` : `c286fc35a9653122a8e6ccb293d10e281e2dbe684d66b0d2c020abafcee7c6ca`.

## 1. Écart au protocole — à consigner

`EXPERIMENT-PROTOCOL.md` §1 classe le changement SQM et le benchmark Internet saturant
parmi les **tests bloqués**, et §2 exige un lien Ethernet de secours.

Les préconditions 1 et 2 n'étaient **pas** satisfaites : aucune interface `eth1` sur le
routeur, aucun RTL8153 détecté. L'unique chemin d'accès restait le Wi-Fi servi par le
routeur lui-même. Le blocage a été signalé et l'opérateur humain a demandé de procéder
malgré tout. Préconditions 3 (sauvegarde) et 5 (critère d'arrêt) satisfaites ;
précondition 4 satisfaite par une copie locale du fichier, sans dépendance Internet.

Aucun minuteur de rollback n'a été armé, conformément à la mise en garde de §2.

## 2. Contexte : ce qui écroulait réellement le débit

Le plafond de 5 Mbit/s n'était pas la cause de l'incident du jour. Le débit était tombé à
**~273 o/s – 1 Ko/s avec un TTFB de 24 à 31 s**, soit très en dessous du plafond.

Cause identifiée `OBSERVÉ` : le démon Soulseek **slskd** sur le poste WSL2 maintenait
~400 sockets P2P, saturant le suivi de connexions du GL-E5800.

**Piège de diagnostic, à retenir.** Une mesure prise 12 s après `systemctl --user stop
slskd` donnait encore 273 o/s, ce qui a conduit à innocenter slskd à tort. La table met
plusieurs minutes à se purger. Après arrêt **et** désactivation du service, le débit est
remonté seul à 3,6 Mbit/s, valeur cohérente avec le plafond CAKE de 5 Mbit/s alors actif.
Tout diagnostic ultérieur doit laisser au moins 5 minutes après l'arrêt d'un démon P2P
avant de conclure.

Corollaire : la signature « latence excellente + 0 % de perte + débit quasi nul » ne
suffit pas à conclure à un lissage opérateur. Cette hypothèse avait été formulée puis
réfutée.

## 3. État radio avant changement

Sonde `OBSERVÉ` via `ubus call modem.CPU.AT` (lecture seule, autorisée par §1) :

```text
+QENG: "LTE","FDD",228,02,4E9E09,107,2850,7,5,5,A474,-90,-8,-61,16,15,20
+QENG: "NR5G-NSA",228,02,983,-111,11,-10,647424,78,12,1
+QCAINFO: (vide)
+QTEMP: sdr0 27 °C, cpuss 40 °C
```

Lecture : LTE FDD bande 7, 20 MHz, RSRP -90 dBm, RSRQ -8, SINR 16 dB, CQI 15. NR5G-NSA
n78 faible à -111 dBm. Aucune agrégation de porteuses active. `INFÉRÉ` : une porteuse
LTE B7 de 20 MHz à ce SINR porte couramment plusieurs dizaines de Mbit/s, très au-dessus
du plafond de 5 Mbit/s alors appliqué.

## 4. Changement appliqué

```sh
uci set sqm.modem.download='45000'
uci commit sqm
/etc/init.d/sqm restart
```

`iqdisc_opts` n'a pas été touché. Motif : le document du 2026-08-06 enregistre que
l'estimateur `autorate-ingress` s'était effondré à ~0,42 Mbit/s. Le restaurer aurait
reproduit un bridage, à l'opposé de l'objectif.

Le service a de nouveau signalé l'anomalie non bloquante déjà connue
(`tc qdisc del dev rmnet_data1 root` sur un qdisc root absent) avant de confirmer le
démarrage de `piece_of_cake.qos`.

## 5. Mesures après changement

Débit descendant, 5 essais, même serveur, même taille (25 Mo), flux unique :

| Essai | Débit |
|---:|---:|
| 1 | 38,80 Mbit/s |
| 2 | 39,58 Mbit/s |
| 3 | 39,27 Mbit/s |
| 4 | 39,31 Mbit/s |
| 5 | 37,15 Mbit/s |

Médiane **39,27 Mbit/s**, dispersion 37,15–39,58. À comparer aux 3,6 Mbit/s mesurés sous
le plafond de 5 Mbit/s : facteur ~11.

Latence et pertes, charge réelle vérifiée (2 flux, 124,5 Mo effectivement passés dans le
shaper pendant la fenêtre de mesure) :

| Condition | Perte ICMP | Moyenne | Max |
|---|---:|---:|---:|
| à vide | 0 % | 21,4 ms | 31,0 ms |
| sous charge | 0 % | 34,1 ms | 107,0 ms |

CAKE : 6 273 drops sur ~83 000 paquets pendant la charge, `backlog 0b`. Ces drops sont le
signal AQM normal vers TCP, à ne pas confondre avec de la perte subie — la perte ICMP
mesurée est nulle.

Le critère qui avait motivé le plafond le 2026-08-06 (2,14 % de perte à 10 Mbit/s) n'est
**pas reproduit** à 39 Mbit/s dans les conditions radio du 2026-08-08. Aucun ratio
d'amélioration par rapport à la session du 6 n'est revendiqué : serveur, heure, cellule et
charge diffèrent.

Un premier essai de mesure sous charge a été **écarté comme invalide** : les compteurs
CAKE n'avaient bougé que de 45 Ko, le téléchargement d'arrière-plan n'ayant pas démarré.
Résultat négatif conservé ici conformément à §4.

## 6. Rollback exact

```sh
cp /etc/config/sqm.bak-before-unthrottle /etc/config/sqm
/etc/init.d/sqm restart
```

La sauvegarde est aussi hors routeur, dans
`.evidence-private/20260808T064135Z-unthrottle/`. Empreinte de la configuration
antérieure : `ebca1000b6f3b4f26a8d15785aef46d3fc22c601a19b7ec73d07e81f0e978265`.

## 7. Limites et suite

- **Réglage non optimal.** Le plafond de 45 Mbit/s est au-dessus de la capacité réelle
  observée (~39 Mbit/s). CAKE ne peut donc pas tenir le goulot : la file se forme chez
  l'opérateur, ce qui explique le maximum à 107 ms sous charge. Un plafond légèrement
  **sous** la capacité réelle (piste : 35000) rendrait le contrôle du bufferbloat à CAKE.
  `NON TESTÉ`.
- **Une seule session de mesure**, sur une seule cellule, à une seule heure. §4 exige cinq
  répétitions pour une affirmation de performance : le débit médian ci-dessus est
  `OBSERVÉ` sur cinq essais, mais sa stabilité dans le temps est `NON TESTÉE`.
- **Upload jamais mesuré** : `upload=0`, aucun protocole fiable exécuté. Inchangé.
- Le plafond peut redevenir contraignant si les conditions radio se dégradent. Critère de
  retour arrière inchangé : pertes répétées supérieures à 1 % ou hausse durable de la
  latence sous charge.
- Avant tout redémarrage de slskd, limiter ses connexions simultanées, faute de quoi
  l'effondrement de la §2 se reproduira quel que soit le réglage SQM.
