# SQM / CAKE sur GL-E5800 — installé et réglé le 2026-08-06

## Configuration retenue : shaping en ENTRÉE seulement

```
sqm.modem.interface     = rmnet_data1
sqm.modem.enabled       = 1
sqm.modem.qdisc         = cake
sqm.modem.script        = piece_of_cake.qos
sqm.modem.linklayer     = none
sqm.modem.download      = 45000        # kbit, plafond ; autorate-ingress ajuste
sqm.modem.upload        = 0            # 0 = PAS de shaping en sortie (voir plus bas)
sqm.modem.iqdisc_opts   = nat dual-dsthost ingress autorate-ingress
sqm.modem.eqdisc_opts   = nat dual-srchost
```

Actif au démarrage (`/etc/rc.d/S50sqm`). Paquets ajoutés : `kmod-sched-cake`,
`sqm-scripts`, `luci-app-sqm` (réglable aussi dans LuCI → Network → SQM QoS).

## Résultats mesurés

Latence = temps de connexion TCP (l'ICMP est filtré par yallo), 12 échantillons,
charge = 3 téléchargements parallèles de 60 Mo.

| Configuration | médiane sous charge | moyenne | **max** | montant |
|---|---|---|---|---|
| Sans SQM | 114 ms | 390 ms | **2023 ms** | 10,4 – 16,6 Mbit/s |
| CAKE entrée + sortie | 141 / 146 ms | 186 / 165 ms | **324 / 488 ms** | 5,6 – 6,7 Mbit/s |
| **CAKE entrée seule** | **86 / 109 ms** | 167 / 186 ms | **551 / 601 ms** | **11,1 – 12,4 Mbit/s** |

À vide : 37-52 ms de médiane dans tous les cas.

**Gain retenu : le pic de latence sous charge passe de ~2 s à ~0,6 s**, sans coût sur le
débit. C'est ce qui compte pour la visio, le jeu et tout usage interactif pendant qu'un
téléchargement tourne.

## Pourquoi pas de shaping en sortie

Le shaper d'egress s'applique directement sur `rmnet_data1`, dont le qdisc racine est un
`mq` avec **32 files `rmnet_sch`** (scheduler propriétaire Qualcomm). CAKE y remplace la
racine et le rendement s'effondre.

Test A/B, alternance immédiate :

```
SQM OFF -> 16,58 Mbit/s      SQM ON -> 4,78 Mbit/s
SQM OFF -> 13,79 Mbit/s      SQM ON -> 6,43 Mbit/s
```

Le débit suit bien le réglage, mais avec ~30 % de perte constante :

```
shaper  9500 kbit -> 6,66 Mbit/s   (70 %)
shaper 20000 kbit -> 9,26 Mbit/s   (46 %)
shaper 50000 kbit -> 12,70 Mbit/s  (plafond du lien atteint)
```

Ce n'est pas un artefact de flux unique — en 3 flux parallèles : **5,59 Mbit/s avec
shaping contre 10,42 sans**. CAKE rend normalement 90-95 % du débit configuré ; ici c'est
~60 %.

L'entrée, elle, passe par `ifb4rmnet_data1`, un périphérique IFB classique sans
multi-queue propriétaire — et là CAKE fonctionne normalement. D'où la config asymétrique.

## Le réglage du débit descendant

Le lien varie énormément : **10 à 54 Mbit/s** selon les relevés, sans qu'on y touche.
Un shaper fixe serait donc soit un gaspillage, soit inefficace. D'où `autorate-ingress`,
qui laisse CAKE estimer le débit en continu (observé oscillant autour de 41 Mbit/s).
Le `download=45000` sert de plafond de départ, pas de valeur imposée.

## Réglage / annulation

```bash
SSH='ssh -i ~/.ssh/glinet_ed25519 root@192.168.8.1'

# état
$SSH 'tc -s qdisc show dev ifb4rmnet_data1 | head -3'
$SSH '/etc/init.d/sqm status'

# désactiver temporairement
$SSH '/etc/init.d/sqm stop'

# désinstaller complètement
$SSH 'uci -q delete sqm.modem; uci commit sqm; /etc/init.d/sqm stop; /etc/init.d/sqm disable'
$SSH 'opkg remove luci-app-sqm sqm-scripts kmod-sched-cake'
```

Mesure reproductible : `bash tools/bufferbloat.sh` depuis la racine du dépôt.

## Limite connue

`rmnet_data1` est le `l3_device` courant de `modem_cpu`. Si le modem re-négocie et que
le nom change (`rmnet_data0`, etc.), SQM ne s'attachera plus. À vérifier après un reset
modem :

```bash
$SSH 'ubus call network.interface.modem_cpu status | grep l3_device'
```
