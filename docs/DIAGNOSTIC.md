# GL-E5800 — état relevé le 2026-08-06

> **ARCHIVE NON VALIDÉE.** Les mesures et conclusions ci-dessous sont des hypothèses à
> reproduire. Elles ne sont pas utilisées comme preuves dans la nouvelle contre-expertise.
> Voir [`COUNTER-EXPERTISE.md`](COUNTER-EXPERTISE.md).

Matériel : GL-E5800, firmware 4.8.5 (2026-06-01), OpenWrt 23.05.4, ARMv8 4 cœurs, région DE.
Modem : **Quectel RG650V** (bus `cpu`, port AT `/dev/smd9`, 2 slots + eSIM slot 2).
SIM active : **slot 2**, MCC 228 / MNC 02, opérateur **yallo**, APN `internet`. Slot 1 vide.
Trafic cumulé : ~245 Go.

## Radio — c'est là que ça coince

```
LTE  band 7  (2600 MHz) PCC   RSRP -110  RSRQ -13  SINR 10   <- ancrage, 20 MHz
LTE  band 3  (1800 MHz) SCC   RSRP -108  RSRQ -18
LTE  band 20 (800 MHz)  SCC   RSRP  -86  RSRQ -15            <- 25 dB de mieux
NR   band n8 (900 MHz)  NSA   RSRP -104  SINR  3             <- SINR très faible
```

Mode `AUTO`, NR non désactivé, EN-DC actif (AcT 13 = 5G NSA).
Températures 48-54 °C, normales.

**Le problème** : l'ancrage LTE est sur la bande 7 à **-110 dBm** (mauvais), alors que la
bande 20 agrégée en secondaire est à **-86 dBm** (bon). Le modem a choisi comme primaire
la bande la plus faible. Et le NR est tombé sur **n8 (900 MHz)** avec un SINR de 3 dB —
n8 c'est du 5G basse bande, à peine mieux que du LTE.

`n78` (3,5 GHz), là où sont les vrais débits, est **autorisé** dans la config
(`nr5g_band` inclut 78) mais non utilisé — soit pas de couverture ici, soit l'ancrage
faible empêche l'appairage.

Bandes autorisées actuellement :
- LTE : 1,3,5,7,8,20,28,32,38,40,41,42,43
- NR : 1,3,5,7,8,20,26,28,38,40,41,75,76,77,78

## Wi-Fi

| Radio | Bande | Mode | Canaux | SSID | État |
|---|---|---|---|---|---|
| wifi0 | 2.4 GHz | EHT40 | auto | MY-SSID | actif |
| wifi1 | 5 GHz | EHT80 | 36,40,44,48 | MY-SSID | actif |
| wifi2 | 6 GHz | EHT160 | 5,21,37,53 | MY-SSID | **désactivé** |

- Le **6 GHz est éteint** (`wireless.wifi6g.disabled='1'`) alors que c'est la radio la plus
  rapide de l'appareil (EHT160). Sur un tri-bande Wi-Fi 7, c'est le levier le plus direct.
- Le 5 GHz est bridé sur **UNII-1 uniquement** (36-48), donc EHT80 au lieu d'EHT160.
  Les canaux DFS (52-140) doubleraient la largeur disponible.
- **MLO n'est pas disponible** sur ce build : `software_feature.mlo = false` et aucune
  section MLD dans `uci show wireless`. Ce n'est pas un réglage à activer.

## IPv6 — désactivé côté routeur, pas côté réseau

```
network.modem_cpu.ipv6   = 0      <- OpenWrt ne demande pas d'IPv6
kmwan.modem_cpu_6.disabled = 1
AT+CGDCONT? -> contexte 1 = "IPV4V6"    <- le modem, lui, est prêt
```

Le contexte PDP est en IPv4v6 : l'opérateur peut fournir de l'IPv6, c'est la conf
OpenWrt qui ne le demande pas.

## Leviers, par rapport gain/risque

| Action | Gain attendu | Risque |
|---|---|---|
| ~~Activer la radio 6 GHz~~ | — | **testé : casse le 5 GHz** |
| ~~Débrider les canaux DFS en 5 GHz~~ | — | **testé : casse le 5 GHz** |
| ~~Activer IPv6 sur `modem_cpu`~~ | — | **testé : l'opérateur ne fournit pas d'IPv6** |
| Verrouiller l'ancrage LTE sur b20 ou b3 | ancrage +25 dB, meilleur appairage NR | **coupe le WAN pendant la bascule** |
| Forcer n78 si couverture | débit 5G réel | peut faire perdre le NR si pas de couverture |

## Résultats des tests du 2026-08-06 — les trois pistes Wi-Fi/IPv6 sont mortes

Testé en réel, puis intégralement restauré (md5 des configs `wireless`, `network`,
`kmwan` identiques aux sauvegardes de `/root/cfg-backup/`).

**1. 6 GHz — exclusif avec le 5 GHz sur ce matériel.**
La radio monte correctement (canal 5, 5.975 GHz, HE160). Mais dès qu'elle est active,
hostapd n'arrive plus à démarrer le 5 GHz :
```
wlan1: IEEE 802.11 Configured channel (0) or frequency (0) not found from the
       channel list of the current mode (2) IEEE 802.11a
wlan1: IEEE 802.11 Hardware does not support configured channel
```
Un seul `phy0` (driver `qcacld32`) porte les trois bandes, et l'ACS ne sert qu'une
bande à la fois. Le SSID invité 5 GHz (`wlan4`) tombe avec. C'est pour ça que GL.iNet
livre le 6 GHz désactivé — ce n'est pas un oubli.

Figer le canal 5 GHz au lieu de `auto` ne sauve rien : le mapping interface↔radio
se réarrange (deux interfaces en 2,4 GHz, deux en 5 GHz, plus de 6 GHz du tout).

**2. Canaux DFS en 5 GHz — l'ACS du driver ne sait pas les gérer.**
Avec `channels='36,40,44,48,52,56,60,64'`, l'ACS retourne channel 0 et hostapd échoue,
en EHT160 comme en EHT80. Le driver n'effectue pas de CAC utilisable.

**3. EHT160 en 5 GHz — non supporté par la puce.**
`Hardware does not support configured channel`. Le 160 MHz n'existe que sur la radio
6 GHz. La config d'usine (EHT80 en 5 GHz, EHT160 en 6 GHz) reflète le matériel.

**4. IPv6 — c'est l'opérateur, pas le routeur.**
Après `network.modem_cpu.ipv6=1` + `network.modem_cpu_6.disabled=0` :
```
ifup modem_cpu_6  ->  ACTION=ifup-failed  eipv6=   (vide)
AT+CGPADDR        ->  +CGPADDR: 1,"10.x.x.x"    (v4 seule)
```
Le contexte PDP est bien déclaré `IPV4V6`, mais yallo n'alloue aucun préfixe v6 sur
ce bearer. Rien à corriger côté routeur. Accessoirement `10.x.x.x` confirme le CGNAT.

**Piège rencontré** : un garde-fou d'auto-restauration à T+90 s s'est déclenché à tort
pendant le CAC DFS (encore en cours) et a écrasé une config qui fonctionnait. Sur un
accès LAN par Ethernet, un changement Wi-Fi ne peut pas enfermer dehors — l'auto-revert
ajoute du risque au lieu d'en retirer. Restaurer à la main depuis `/root/cfg-backup/`.

## Test du lock LTE bande 20 — le firmware écrase la configuration

**Résultat : le verrouillage de bande est impossible sur cet appareil.**

Référence mesurée avant (7 échantillons, 10 Mo via Cloudflare) : **22 à 54 Mbit/s**,
médiane ~29 Mbit/s. Variance naturelle très élevée.

Déroulé :

| Étape | Commande | Résultat |
|---|---|---|
| Écriture du lock | `AT+QNWPREFCFG="lte_band",20` | `OK`, relecture confirme `lte_band,20` |
| Vérif cellule | `AT+QENG="servingcell"` | **toujours bande 7** (EARFCN 2850) |
| Débit sous lock | 3 échantillons | 26,6 / 28,8 / 29,8 Mbit/s — inchangé |
| Cycle radio | `AT+CFUN=0` puis `AT+CFUN=1` | réglage conservé, **toujours bande 7** |
| Reset modem | `AT+CFUN=1,1` | **`lte_band` revenu seul à la liste complète** |

Le réglage NV est bien accepté, mais la radio ne s'y conforme jamais, et un reset du
modem le remet à `1:3:5:7:8:20:28:32:38:40:41:42:43`. Le binaire propriétaire
**`/usr/bin/modem_AT`** réimpose la liste de bandes à chaque initialisation.

Conséquence pratique : ni `lte_band` ni `nr5g_band` ne sont exploitables pour figer une
bande. Pas de rollback nécessaire — la config se restaure d'elle-même.

Note : les conditions radio varient beaucoup d'un relevé à l'autre (le NR est passé de
n8 SINR 3 à n78 SINR 0 en une heure, les cellules changent). Toute mesure sur un seul
échantillon n'a aucune valeur ici.

**Ce qui reste réellement actionnable** : rien côté radio. Le Wi-Fi est à son optimum
matériel, et le cellulaire est verrouillé par le firmware. Les vrais leviers restants
sont applicatifs : QoS/CAKE, politiques VPN, DNS, AdGuard — pas la couche physique.

## Commandes utiles

```bash
SSH='ssh -i ~/.ssh/glinet_ed25519 root@192.168.8.1'

# relevé radio complet
$SSH 'sh -s' < at-probe.sh

# surface RPC réelle du firmware (73 services)
$SSH 'ubus -v list'          # -> ubus-list.txt

# AT arbitraire
$SSH 'ubus call modem.CPU.AT get_result_AT "{\"cmd\":\"AT+CSQ\",\"timeout\":8}"'
```
