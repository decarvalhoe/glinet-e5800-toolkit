# Contre-expertise indépendante — phase 1

Date de collecte : 2026-08-06

Cible : GL.iNet GL-E5800, firmware GL.iNet 4.8.5

Preuves publiques expurgées :
[`evidence/20260806T180259Z`](../evidence/20260806T180259Z/) et
[`evidence/20260806T184026Z`](../evidence/20260806T184026Z/), puis contrôle correctif
[`evidence/20260806T190420Z`](../evidence/20260806T190420Z/)

Ces dossiers sont des lots d'audit, pas des runs atomiques. Leur nom correspond à l'heure
de leur baseline ; `usb-benchmark.txt` et `zram-test.txt` conservent leurs propres
horodatages. La limite du collecteur v1 est explicitée en fin de document.

Collecteur : [`tools/collect-safe-baseline.sh`](../tools/collect-safe-baseline.sh)

Le protocole normatif pour les phases suivantes est
[`EXPERIMENT-PROTOCOL.md`](EXPERIMENT-PROTOCOL.md).

## Portée et règle de confiance

Cette contre-expertise repart de zéro. **Aucune conclusion antérieure de ce dépôt n'est
reprise comme fait**, y compris les tableaux de débit, les conclusions radio, Wi-Fi,
IPv6, SQM, API et paquets.

Les documents historiques sont conservés pour traçabilité, mais placés en quarantaine
jusqu'à reproduction avec données brutes.

Niveaux de preuve employés :

- **OBSERVÉ** : sortie brute horodatée de l'appareil présent dans `evidence/` ;
- **REPRODUIT** : expérience répétée, protocole et résultat brut publiés ;
- **INFÉRÉ** : conclusion compatible avec les observations, mais non démontrée ;
- **SOURCE EXTERNE** : affirmation d'un constructeur ou projet tiers ;
- **NON TESTÉ** : hypothèse ou piste de travail.

## Contrainte de sûreté déterminante

Le GL-E5800 est l'unique source Internet de la machine de test. La phase 1 interdit donc :

- reboot ou reset du routeur/modem ;
- `ifup`, `ifdown`, changement d'APN, de SIM, de bande ou de cellule ;
- changement de radio, canal, largeur Wi-Fi ou puissance ;
- arrêt/redémarrage de `netifd`, `firewall`, `sqm`, `kmwan` ou service modem ;
- changement de routes, règles nftables, DNS ou VPN ;
- installation/suppression de paquet ;
- benchmark WAN saturant ou test de bufferbloat ;
- montage `extroot`, activation permanente de swap ou écriture UCI.

Les deux instantanés publics de connectivité montrent chacun 3/3 réponses ICMP vers le
routeur et HTTP 200 vers GitHub. Cela prouve ces instants, pas une disponibilité parfaite
pendant toute la phase. Aucune configuration du routeur n'a été modifiée.

## Baseline indépendante

### Système

| Élément | Résultat | Preuve | Statut |
|---|---|---|---|
| Modèle | GL.iNet E5800 / SDXPINN IDP MBB | `router-system.txt` | OBSERVÉ |
| Firmware | GL.iNet 4.8.5 | `router-system.txt` | OBSERVÉ |
| Base | OpenWrt 23.05.4, cible `sdx75/generic` | `router-system.txt` | OBSERVÉ |
| Noyau | `5.15.170-perf` | `router-system.txt` | OBSERVÉ |
| CPU | 4 cœurs ARMv8 Cortex-A55 | `router-hardware.txt` | OBSERVÉ |
| Gouverneur | `schedutil` | `router-hardware.txt` | OBSERVÉ |
| Fréquences instantanées | 1 516 800 kHz (première) ; 1 324 800 à 1 651 200 kHz (récente) | `router-hardware.txt` | OBSERVÉ |
| Plage de la politique CPU | 691 200 à 2 208 000 kHz | `router-hardware.txt` | OBSERVÉ |
| RAM | 1 598 MiB, environ 1 097 MiB disponibles | `router-system.txt` | OBSERVÉ |
| Swap | aucune | `router-system.txt` | OBSERVÉ |
| Overlay interne | ext4, 2,7 GiB libres | `router-system.txt` | OBSERVÉ |

La pression mémoire PSI était nulle (`some=0`, `full=0`) et aucun événement OOM n'a été
trouvé lors du relevé. Avec environ 1,1 GiB encore disponible, **aucun déploiement zram
ou swap USB n'est actuellement justifié**. Le test zram décrit plus bas valide seulement
la faisabilité technique d'un cycle temporaire.

La charge moyenne observée ne démontre pas une saturation CPU. Les interruptions Wi-Fi et xHCI étaient réparties sur les
quatre cœurs, tandis que l'interruption `gsi` était plus concentrée sur CPU0. Cet unique
instantané ne prouve pas qu'`irqbalance` apporterait un gain. Changer le gouverneur en
`performance` ou l'affinité IRQ sans mesure corrélée à une charge n'est donc pas justifié
et pourrait augmenter consommation, température ou latence sans gain prouvé.

### Chemin Internet et SQM

- le WAN actif est `rmnet_data1` ;
- le lien cellulaire est la route par défaut ;
- un IFB `ifb4rmnet_data1` porte CAKE en entrée ;
- la sortie `rmnet_data1` conserve la racine multi-queue et ses files `pfifo_fast` ;
- la première collecte publie 4 206 kbit/s et une estimation de 4 486 kbit/s ;
- la plus récente publie 791 696 bit/s et une estimation de 844 480 bit/s.

Ces éléments prouvent seulement **l'état du qdisc aux deux instants publiés**. Ils ne
prouvent ni gain de latence, ni perte de débit, ni valeur optimale. Ils montrent une
variation importante et identifient `autorate-ingress` comme le premier levier à observer :
si son estimation reste durablement inférieure à la capacité radio réellement obtenue,
il pourrait constituer un bridage majeur. Les conclusions A/B historiques de
`docs/SQM.md` sont donc suspendues.

Une observation sans modification peut relever toutes les trois secondes la bande passante,
l'estimation, les délais et les drops de CAKE pendant un téléchargement normal déjà en
cours. Un véritable test A/B nécessiterait plusieurs répétitions alternées, état radio
consigné, serveur et taille identiques, échantillons bruts, contrôle de l'ordre des essais
et saturation du WAN. Cet A/B reste interdit tant qu'un accès de secours n'est pas disponible.

### Qualcomm IPA et fastpath

La collecte publique montre des IRQ/processus IPA actifs, `hw_tx=3766019` contre
`sw_tx=172431`, ainsi que des compteurs de tethering Qualcomm. Elle montre aussi une
flowtable nftables sans drapeau `offload` matériel et des entrées conntrack marquées
`[OFFLOAD]`, pas `[HW_OFFLOAD]`.

Statut : **OBSERVÉ** pour l'activité IPA et le fastpath logiciel ; **INFÉRÉ** seulement
pour la part exacte de NAT LAN↔cellulaire accélérée par IPA. Des compteurs absolus ne
prouvent pas le chemin d'un flux particulier. Le test futur sûr consiste à corréler les
deltas IPA, `rmnet_data1` et CPU pendant un flux normal connu. Désactiver IPA, QCMAP,
`ipacm` ou l'échelonnage d'horloge est interdit : ces composants appartiennent à la pile
de l'unique WAN.

## Adaptateur USB/Ethernet

| Élément | Résultat | Statut |
|---|---|---|
| Contrôleur | Realtek RTL8153, USB 3, identifiant `0bda:8153` | OBSERVÉ |
| Pilote | `r8152` v1.12.13 | OBSERVÉ |
| Capacité annoncée | 10/100/1000BASE-T | OBSERVÉ |
| Offloads | checksum RX/TX, scatter-gather, TSO, GSO et GRO actifs | OBSERVÉ |
| Interface | `eth1`, membre de `br-lan` | OBSERVÉ |
| État | `NO-CARRIER`, aucun lien physique | OBSERVÉ |

L'adaptateur peut vraisemblablement devenir un second port LAN Gigabit dès qu'un câble
est connecté. Il ne constitue **pas encore** une voie de secours et sa fonction WAN n'a
pas été testée. Aucune bascule WAN ne sera tentée avant validation d'un lien filaire LAN,
d'une adresse de gestion et d'une session SSH indépendante du Wi-Fi.

Il ne faut pas connecter `eth1` à un autre LAN possédant son propre DHCP : l'interface est
actuellement dans `br-lan`, ce qui fusionnerait les deux domaines de niveau 2. Le firmware
possède une voie native `usbwan`, mais la conversion LAN→WAN recharge réseau et pare-feu ;
elle reste donc interdite sans second accès de gestion.

Tests futurs non disruptifs après branchement physique :

1. vérifier `Link detected: yes` et la négociation à 1000/full ;
2. confirmer que le client reçoit une adresse LAN sans modifier UCI ;
3. maintenir simultanément SSH et ping via ce lien ;
4. exécuter un `iperf3` LAN limité, jamais un test WAN ;
5. mesurer erreurs, drops, débit et charge CPU ;
6. seulement ensuite considérer l'adaptateur comme accès de secours.

## Clé USB et extension de mémoire

### Matériel observé

- SanDisk Ultra 32 Go, USB 3 à 5 Gbit/s ;
- `/dev/sdc1`, 28,6 GiB, environ 28,4 GiB libres ;
- format actuel FAT32/vfat ;
- deux lecteurs de cartes supplémentaires sans média ;
- noyau avec `CONFIG_SWAP`, `CONFIG_ZRAM`, ext4, F2FS, USB storage et overlayfs ;
- `CONFIG_MEMCG` et `CONFIG_POSIX_MQUEUE` absents.

### Benchmark reproductible, limité à 64 MiB

Le benchmark écrit un unique fichier temporaire, utilise `O_DIRECT`, relit deux fois et
vérifie la connexion avant/après. Sa version durcie borne chaque `dd`, `dmesg`, `ls` et
suppression côté routeur ; elle refuse les traversées `..`, les chemins imbriqués et tout
chemin canonique sortant de `/tmp/mountd`, puis échoue avec le code 90 si l'absence
finale du fichier ne peut pas être prouvée. Cette version durcie a été vérifiée par
simulation locale du script distant, mais **n'a pas été relancée sur la clé** en raison du
gel des écritures. Les mesures publiées ci-dessous proviennent de la version antérieure.
Ses artefacts montrent un `df`
final inchangé, mais ne prouvent pas directement l'absence du fichier temporaire ; cette
postcondition historique reste donc **NON TESTÉ** dans les preuves publiées.

Mesure du second passage indépendant :

- écriture directe synchronisée : **1,9 MB/s** ;
- lecture directe : **114,7 puis 121,2 MB/s** ;
- espace libre affiché inchangé dans le `df` final ;
- connexion Internet observée fonctionnelle au contrôle après le passage.

Un premier passage avait donné 13,6 MB/s en écriture. L'écart 1,9–13,6 MB/s démontre une
forte variabilité ; deux passages ne suffisent pas pour caractériser la clé. La lecture
est nettement supérieure à l'écriture, mais aucune conclusion d'endurance ne peut être
tirée.

Une revue indépendante a signalé un message FAT historique « volume not properly
unmounted ». La nouvelle lecture de `dmesg` et `logread` ne l'a pas reproduit, et le
volume reste monté en lecture-écriture. Cette absence actuelle ne prouve pas l'intégrité
du FAT : **aucune nouvelle écriture de benchmark n'est autorisée avant sauvegarde et
vérification hors ligne sur une autre machine**. Ne pas lancer `fsck` sur le volume monté.

### Options réalistes

| Option | Gain | Risque | Verdict phase 1 |
|---|---|---|---|
| ZRAM | évite certains OOM par compression de RAM | consomme CPU et une partie de la RAM | cycle temporaire OBSERVÉ une fois ; déploiement non justifié par PSI |
| Swap USB 256–512 MiB, priorité basse | mémoire de secours réelle | latence, usure, gel sous forte pression | possible mais pas une optimisation de vitesse |
| Répertoire `/opt` sur ext4 USB | espace pour outils, métriques et services maison | service indisponible si retrait USB | meilleure exploitation durable |
| Bind mounts de données applicatives | évite d'user/remplir l'overlay interne | dépendance USB limitée aux applications ciblées | recommandé après sauvegarde/reformatage |
| Image ext4 de moins de 4 GiB sur FAT32 | essai sans repartitionnement | double couche FS, corruption possible, limite FAT32 | utile seulement comme prototype |
| `extroot` complet | grand overlay | dépendance de boot au support amovible | à éviter : 2,7 GiB libres et pas de récupération U-Boot documentée |
| Conteneurs OCI | isolation applicative | `POSIX_MQUEUE` et `MEMCG` absents | non viable sur ce noyau sans reconstruction |

**Important :** la swap USB augmente la capacité disponible, pas la RAM physique. Avec
les écritures observées, elle doit être un filet de sécurité à faible priorité, jamais une
zone de travail intensive.

### Essai zram temporaire

[`tools/test-zram-safe.sh`](../tools/test-zram-safe.sh) a créé une fois un périphérique zram de
64 MiB avec LZ4, l'a activé comme swap, puis a désactivé la swap et remis `disksize` à zéro :

- avant : aucune swap, `disksize=0` ;
- pendant : 64 MiB disponibles, 0 MiB utilisés ;
- après : aucune swap, `disksize=0` ;
- WAN observé `up` lors d'une collecte ultérieure et ping du routeur 3/3 dans les
  contrôles échantillonnés ; aucun journal continu ne prouve une disponibilité sans coupure.

Une revue ultérieure a découvert que le script initial avait laissé l'algorithme sélectionné
sur `lz4`, alors que l'état initial était `lzo-rle`. Il n'y avait ni swap active ni espace
zram alloué, mais le rollback runtime n'était donc pas complet. `lzo-rle` a été restauré
après vérification de `disksize=0` et de l'absence de swap. Le contrôle correctif publié
confirme ensuite `lzo-rle`, `disksize=0`, aucune swap, WAN `up`, ICMP 3/3 et HTTP 200.

Le script a été renforcé pour restaurer et vérifier également `comp_algorithm`, avec des
timeouts individuels sur `swapoff`, reset, `mkswap` et `swapon`. L'expérience rend
l'activation zram **OBSERVÉE** ; le nettoyage initial est **OBSERVÉ comme incomplet** et
seul le contrôle correctif démontre le retour complet à l'état initial. Elle ne mesure ni
ratio de compression, ni impact CPU, ni comportement sous pression mémoire.

## Plan d'optimisation gradué

### Niveau 0 — terminé, aucun changement réseau ou persistant

- baseline brute et expurgée ;
- inventaire noyau, CPU, RAM, réseau, stockage et paquets ;
- benchmark USB temporaire ;
- validation post-test de la connectivité.

### Niveau 1 — sans toucher au réseau, en cours

1. suspendre les écritures USB et vérifier le FAT hors ligne après sauvegarde ;
2. ~~tester un zram temporaire de taille bornée, sans activation au boot~~ — cycle 64 MiB observé une fois ;
3. observer PSI/OOM pendant plusieurs jours et sous les charges réelles ;
4. ne provoquer aucune pression synthétique tant que la RAM disponible reste élevée ;
5. reporter l'image ext4 temporaire jusqu'à validation du support et d'une sauvegarde ;
6. conserver le routage entièrement indépendant de la clé USB.

### Niveau 2 — après sauvegarde du contenu USB

Schéma recommandé pour une personnalisation durable :

- partition ext4 principale pour `/opt`, métriques, logiciels maison et données ;
- petite partition swap dédiée, facultative, 256–512 MiB et priorité basse ;
- montage par UUID avec `nofail` ;
- les services dépendants de l'USB doivent échouer sans affecter le WAN ;
- ne pas déplacer `/overlay`, `/etc/config`, le pare-feu ou la pile modem.

### Niveau 3 — customs maison

Pistes compatibles avec les observations actuelles :

- agent de télémétrie local léger vers `/opt` ;
- dashboard écran/modem isolé des écritures NV ;
- collecteur Prometheus ou export JSON ;
- historique radio passif corrélé au débit, sans lock de bande/cellule ;
- service d'alerte batterie/température/espace ;
- stockage SMB/WebDAV/DLNA sur ext4 ;
- sauvegarde chiffrée vers la clé USB ;
- scripts procd avec limites CPU/mémoire et dépendance explicite au montage USB ;
- compilations natives OpenWrt userspace, sans module noyau tiers.

Les fonctions modem, Wi-Fi, routage, VPN transparent et SQM restent hors périmètre tant
que l'adaptateur Ethernet n'est pas validé comme accès de secours.

## Ce qui n'est pas démontré

La phase 1 ne valide pas :

- les résultats radio ou les verrous de bande/cellule historiques ;
- les conclusions 5/6 GHz et DFS ;
- l'absence ou la disponibilité IPv6 opérateur ;
- le gain attribué à CAKE ;
- l'exhaustivité de l'index RPC extrait de l'interface ;
- la compatibilité de tous les paquets listés par `opkg` ;
- la possibilité de Docker/Podman simplement parce que les paquets existent ;
- la stabilité de l'adaptateur Ethernet sous charge ;
- l'endurance ou la fiabilité de la clé USB.

## Reproduction

```bash
# Collecte brute privée, strictement en lecture seule
./tools/collect-safe-baseline.sh

# Benchmark USB : script conservé pour audit, exécution suspendue tant que
# le FAT n'a pas été sauvegardé et vérifié hors ligne.
# ./tools/benchmark-safe.sh

# Expurgation avant publication
python3 tools/sanitize-evidence.py \
  .evidence-private/<horodatage> evidence/<horodatage>

# Vérification des preuves publiées
(cd evidence/<horodatage> && sha256sum -c SHA256SUMS)
```

Les preuves privées sont exclues par `.gitignore`. Seules les sorties expurgées et leurs
hashes sont destinés au dépôt public.

Limite du collecteur v1 : les fichiers et le run global sont hashés, mais le code retour
n'est pas encore enregistré séparément pour chaque sous-commande. Une version ultérieure
devra produire un manifeste et un journal de commandes JSONL avant de pouvoir qualifier
la chaîne de preuve d'immuable.

## Sources primaires utilisées pour cadrer les hypothèses

- Linux 5.15 — ZRAM : https://www.kernel.org/doc/html/v5.15/admin-guide/blockdev/zram.html
- Linux 5.15 — EXT4 : https://www.kernel.org/doc/html/v5.15/admin-guide/ext4.html
- Linux 5.15 — VFAT : https://www.kernel.org/doc/html/v5.15/filesystems/vfat.html
- Linux — RPS/RFS/XPS : https://docs.kernel.org/networking/scaling.html
- Linux — flowtable Netfilter : https://docs.kernel.org/networking/nf_flowtable.html
- OpenWrt 23.05 — `zram-swap` : https://github.com/openwrt/openwrt/tree/openwrt-23.05/package/system/zram-swap
- OpenWrt `fstools` — extroot/swap : https://github.com/openwrt/fstools/tree/bfe882d5ff4eeebb8f57c8a0f9b9e767a57870d8
- GL.iNet — stockage réseau : https://docs.gl-inet.com/router/en/4/interface_guide/network_storage/
- GL.iNet — Multi-WAN : https://docs.gl-inet.com/router/en/4/interface_guide/multi-wan/
- GL.iNet — récupération ; absence de flash U-Boot E5800 : https://docs.gl-inet.com/router/en/4/faq/debrick/
- Cibles OpenWrt 23.05.4 ; absence de cible SDX75 : https://downloads.openwrt.org/releases/23.05.4/targets/

Ces sources sont classées `SOURCE EXTERNE`, jamais `OBSERVÉ`, tant que leur conséquence
n'est pas reproduite sur l'appareil exact.
