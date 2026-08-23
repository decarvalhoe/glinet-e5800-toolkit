# Survey de l'appareil — GL-E5800 (Mudi 7)

Inventaire des capacités « fancy » et du matériel, relevé sur l'appareil. Niveaux de preuve
comme dans [`COUNTER-EXPERTISE.md`](COUNTER-EXPERTISE.md).

## Plateforme — `OBSERVÉ`

| Élément | Valeur |
|---|---|
| Modèle / firmware | GL.iNet **E5800 (Mudi 7)** · GL 4.8.5 · OpenWrt 23.05.4 (sdx75) |
| Noyau / CPU | 5.15.170-perf · ARMv8 (aarch64), 4 cœurs · ~1,6 Gio RAM |
| Modem | **Quectel RG650V-EU** (5G NR), **double SIM** |
| Runtime outils | chroot Alpine v3.20 en `/opt/alpine` — voir [`ALPINE-CHROOT.md`](ALPINE-CHROOT.md) |

## Logiciels notables (1072 paquets opkg) — `OBSERVÉ`

- **Privacy / VPN** : Tor (0.4.8.9, désactivé), Tailscale (1.80.3), ZeroTier (1.14.1,
  désactivé), WireGuard, OpenVPN, strongSwan/IPsec (full).
- **Partage / média** : Samba4 (server), miniDLNA.
- **Réseau** : AdGuard Home (DNS anti-pub) + conntrack, hostapd, kmwan (multi-WAN).
- **Cellulaire** : carrier-monitor (démon actif), smstools3 / sms-forward, edgnss-daemon.

## Matériel « portable » — `OBSERVÉ`

| Élément | Détail | Accès |
|---|---|---|
| **Batterie** | jauge CW2215, %, temp, cycles, charge rapide | `ubus call mcu status` → [`device-monitor.py`](../tools/device-monitor.py) |
| **Thermique** | ~15 zones (cpuss, mdmss, sdr…) | `/sys/class/thermal` |
| **Écran** | `/dev/fb0`, PIN, auto-lock, luminosité | `uci show gl_screen`, ubus `gl_screen` |
| **MCU** | boutons, thermique, batterie ; canal `cmd_string` (⚠️ écriture) | ubus `mcu` |
| **OTG** | gadget USB (`/sys/class/android_usb/android0`, `g1`) | — |
| **Cellulaire** | RG650 5G, signal RSRP/RSRQ/SINR | `modem get_signals` → [`radio-monitor.py`](../tools/radio-monitor.py) |

## GPS / GNSS — conclusion `OBSERVÉ` + `SOURCE EXTERNE`

Le modem RG650 **supporte le GNSS** (répond à `AT+QGPS`, `AT+QGPSLOC`, `AT+QGPSCFG`…).
Activé (`AT+QGPS=1`), multi-constellation (`gnssconfig=5`), autostart possible (`autogps`).
**Mais** : après activation, dehors, un bon moment → **0 satellite** (`GSV` vide,
`GSA` fix-1, `RMC` void, `QGPSLOC` → CME 516) de façon persistante.

Explication (`SOURCE EXTERNE`, doc GL.iNet) : le E5800 n'expose que **deux ports TS-9
cellulaires** ; **aucun connecteur d'antenne GNSS** n'est documenté (l'antenne GPS n'existe
que sur le modèle Collie GL-X300B). Donc **la carte ne fournit pas d'antenne GNSS** → pas de
fix possible en l'état, quel que soit le logiciel. Les outils GPS
([`gps-fix.py`](../tools/gps-fix.py), [`gps-heatmap.py`](../tools/gps-heatmap.py)) restent
prêts si un jour un signal apparaît. Détails : [`GPS-HEATMAP.md`](GPS-HEATMAP.md).

## Services ubus utiles (dump `ubus list`)

`cellular.{status,modem,sim,network,failover,collect}` · `modem.CPU.AT` (envoi AT) ·
`mcu` · `gl_screen` · `gl-clients` · `sms_manager` · `network.*` · `iwinfo` · `system` ·
`uci` · `service`. Surface d'action (méthodes d'écriture) : voir l'analyse RPC du dépôt.

## Outils maison ajoutés

Suite de monitoring (Python zéro-dép, lecture seule, persistante via procd) :
[`radio-monitor`](../tools/radio-monitor.py) (signal + dashboard) ·
[`radio-alert`](../tools/radio-alert.py) (seuils/anomalie/péremption) ·
[`radio-digest`](../tools/radio-digest.py) (synthèse) ·
[`gps-fix`](../tools/gps-fix.py) / [`gps-heatmap`](../tools/gps-heatmap.py) ·
[`device-monitor`](../tools/device-monitor.py) (batterie/température).
