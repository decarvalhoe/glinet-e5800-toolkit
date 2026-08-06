# GL-E5800 (Mudi 7) — outils et rétro-ingénierie

Notes de terrain, outils et résultats mesurés sur un **GL.iNet GL-E5800 (Mudi 7)**,
firmware **4.8.5**, OpenWrt 23.05.4, modem Quectel RG650V.

Tout ce qui est ici a été **exécuté et vérifié sur l'appareil**, pas recopié de la
documentation. Les résultats négatifs sont documentés au même titre que les positifs :
ce sont eux qui font gagner du temps.

---

**English TL;DR** — Field notes and tooling for the GL.iNet GL-E5800 (Mudi 7), firmware 4.8.5.
Contains: a **dependency-free Python client** for the GL.iNet JSON-RPC API (pure-stdlib
sha256-crypt, works on Windows); a **live API index of 304 methods across 48 modules**
extracted from the router's own web UI — the public index is 3 years stale and misses 157
of them; the full `ubus -v list` dump; and measured findings, including several
**negative results** that save others the trouble. Docs are in French, but the JSON
indexes, scripts and log excerpts are language-neutral.

---

## Ce que ça contient

```
api/
  glinet-api-live.json     304 méthodes / 48 modules — l'API RÉELLE du firmware 4.8.5
  glinet-api-index.json    l'index public (~2023) — périmé, gardé pour comparaison
  ubus-list.txt            73 services ubus avec signatures (dump `ubus -v list`)
tools/
  glinet.py                client CLI JSON-RPC, zéro dépendance
  at-probe.sh              relevé radio complet (serving cell, CA, bandes, températures)
  bufferbloat.sh           mesure de latence à vide / sous charge
  band-lock-b20.sh         tentative de lock de bande (échoue — voir docs)
etc/hotplug.d/iface/
  99-sqm-modem             réattache SQM quand le l3_device du modem change
docs/
  DIAGNOSTIC.md            relevés radio/Wi-Fi + résultats négatifs
  CUSTOM.md                surface de personnalisation réelle, paquets, méthode
  SQM.md                   installation et réglage CAKE, avec mesures A/B
```

## Le point le plus utile : l'index API public est faux

L'index de référence qui circule (extrait de `python-glinet`) date de ~2023. Sur le
firmware 4.8.5, il manque **157 méthodes sur 304** et **19 modules entiers**.

Le piège qui fait perdre des heures : un appel à une méthode inexistante renvoie
`-32601 Method not found`. On en déduit naturellement que **le module** n'existe pas.
C'est faux — c'est la *méthode* qui n'existe pas. Le module `modem` est bien là, avec
24 méthodes, dont aucune ne s'appelle `get_status`.

**La bonne méthode** : lire le JavaScript de l'interface web du routeur. Elle appelle la
vraie API, elle est forcément à jour, elle est sur l'appareil.

```bash
SSH='ssh root@192.168.8.1'
$SSH 'mkdir -p /tmp/ui; for f in /www/views/*.gz; do zcat "$f" > "/tmp/ui/$(basename $f .gz)"; done'
$SSH 'grep -ohE "\[\"sid\",\"[a-z_0-9-]+\",\"[a-z_0-9]+\"" /tmp/ui/*' \
  | sed 's/\["sid",//; s/"//g' | sort -u
```

Modules absents de l'index public : `tailscale`, `zerotier`, `tor`, `mptun`, `kmwan`,
`parental-control`, `timer`, `lpm`, `screen`, `otg`, `sms-forward`, `bark`,
`black_white_list`, `mvas`, `local-access`, `luci`, `vpn-client`, `wg_client`,
`ovpn_client`.

## Résultats négatifs (testés, pas supposés)

| Piste | Résultat |
|---|---|
| Activer la radio 6 GHz | **casse le 5 GHz** — un seul `phy0` (`qcacld32`), une seule ACS à la fois. GL.iNet la livre désactivée volontairement. |
| Canaux DFS en 5 GHz | l'ACS du driver retourne channel 0, hostapd échoue |
| EHT160 en 5 GHz | `Hardware does not support configured channel` — le 160 MHz n'existe qu'en 6 GHz |
| Lock de bande via `AT+QNWPREFCFG` | accepté puis **écrasé** : `/usr/bin/modem_AT` réimpose sa liste à chaque init du modem |
| IPv6 | contexte PDP `IPV4V6` mais l'opérateur n'alloue aucun préfixe v6 — rien à corriger côté routeur |
| CAKE en egress | **~40 % de débit montant perdu** sur `rmnet_data1` (qdisc `mq` à 32 files `rmnet_sch`) |

Le verrouillage de tour, lui, **existe** sur ce modèle malgré ce qu'affirme la
documentation officielle (`modem.set_cell_tower`) — voir [`docs/CUSTOM.md`](docs/CUSTOM.md).

## Résultat positif : SQM/CAKE en entrée seule

Latence mesurée par temps de connexion TCP (l'ICMP est filtré par l'opérateur),
12 échantillons, charge = 3 téléchargements parallèles de 60 Mo :

| Configuration | médiane | moyenne | **max** | montant |
|---|---|---|---|---|
| Sans SQM | 114 ms | 390 ms | **2023 ms** | 10,4 – 16,6 Mbit/s |
| CAKE entrée + sortie | 141 ms | 186 ms | **324 ms** | 5,6 – 6,7 Mbit/s |
| **CAKE entrée seule** | **86 ms** | 167 ms | **551 ms** | **11,1 – 12,4 Mbit/s** |

La configuration asymétrique n'est pas la recommandation standard, mais c'est ce que le
matériel impose : l'entrée passe par un IFB classique où CAKE fonctionne normalement,
la sortie s'applique directement sur le multi-queue propriétaire Qualcomm où il
s'effondre. Détails et test A/B dans [`docs/SQM.md`](docs/SQM.md).

## Le client CLI

Aucune dépendance — `sha256-crypt` est réimplémenté en stdlib pur, parce que Python n'a
pas de module `crypt` sur Windows. Vérifié bit pour bit contre `openssl passwd -1/-5/-6`.

```bash
export GLINET_PASSWORD='...'          # ou saisie interactive
python tools/glinet.py login
python tools/glinet.py call system get_info
python tools/glinet.py call modem get_cell_tower '{"bus":"cpu"}'
python tools/glinet.py api wg          # recherche dans l'index
```

Protocole d'authentification :

```
POST http://192.168.8.1/rpc
1) {"jsonrpc":"2.0","id":1,"method":"challenge","params":{"username":"root"}}
   -> {"salt":"...","hash-method":"sha256","alg":5,"nonce":"..."}
2) cipher = crypt(password, "$5$" + salt)           # sha256-crypt, 5000 rounds
   hash   = sha256("root:" + cipher + ":" + nonce)  # algo = champ hash-method
3) {"method":"login","params":{"username":"root","hash":hash}} -> {"sid":"..."}
4) {"method":"call","params":[sid, "<module>", "<method>", {args}]}
```

Attention : les noms de modules RPC utilisent des **tirets** (`wg-client`, `custom-dns`,
`nas-web`), pas des underscores.

## Surface de personnalisation

```
/overlay          2,7 Go libres
architecture      aarch64_cortex-a53   (architecture OpenWrt standard)
paquets dispo     9667                 (dépôts GL.iNet seuls)
```

Les dépôts **officiels OpenWrt 23.05.4** pour cette architecture répondent HTTP 200, donc
ajoutables. Disponibles immédiatement et vérifiés : `dockerd` 27.0.3, `podman`,
`tailscale`, `zerotier`, `crowdsec`, `banip`, `sqm-scripts`, `netdata`, `smartdns`,
`collectd`, et 103 paquets `luci-app-*`. LuCI est déjà installé, sur les ports 8080/8443.

## Avertissement

Ces manipulations touchent la connectivité d'un appareil réel. Plusieurs des tests
documentés ici **ont coupé le Wi-Fi ou le WAN**. Sauvegardez avant :

```bash
mkdir -p /root/cfg-backup
for f in wireless network kmwan sqm; do uci export $f > /root/cfg-backup/$f.uci; done
```

Leçon apprise à mes dépens : un garde-fou d'auto-restauration mal conçu s'est déclenché
pendant un CAC DFS encore en cours et a écrasé une configuration qui fonctionnait. Si
l'accès administrateur passe par un lien que le changement ne peut pas couper (Ethernet
pour un changement Wi-Fi), l'auto-revert **ajoute** du risque. Restaurez à la main.

## Licence

MIT — voir [LICENSE](LICENSE).

Aucune affiliation avec GL.iNet. `glinet-api-index.json` provient de
[python-glinet](https://github.com/tomtana/python-glinet) (MIT), conservé uniquement pour
mesurer l'écart avec la réalité du firmware.
