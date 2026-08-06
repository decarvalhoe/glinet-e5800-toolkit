# GL-E5800 — ce qu'on peut réellement en faire

Tu avais raison : ma conclusion « il n'y a plus rien à gratter » était fausse, et elle
venait d'une mauvaise méthode. Ce document remplace cette conclusion.

## L'erreur de méthode

Je testais les noms de méthodes de l'index public de 2023. Quand `modem.get_status` a
renvoyé `-32601 Method not found`, j'en ai conclu que **le module** `modem` n'existait
pas. Faux : `-32601` signifie *méthode* introuvable. Le module existe, avec 24 méthodes
— dont aucune ne s'appelle `get_status`.

**La bonne méthode** : lire le code de l'interface web du routeur. Elle appelle la vraie
API, elle est forcément à jour, et elle est sur l'appareil.

```bash
SSH='ssh -i ~/.ssh/glinet_ed25519 root@192.168.8.1'
$SSH 'mkdir -p /tmp/ui; for f in /www/views/*.gz; do zcat "$f" > "/tmp/ui/$(basename $f .gz)"; done'
$SSH 'grep -ohE "\[\"sid\",\"[a-z_0-9-]+\",\"[a-z_0-9]+\"" /tmp/ui/*' | sed 's/\["sid",//; s/"//g' | sort -u
```

Résultat : **48 modules, 304 méthodes**. **157 étaient absentes** de l'index 2023, et
**19 modules entiers** manquaient. Index à jour : `glinet-api-live.json`.

## Modules qui manquaient complètement

`tailscale` · `zerotier` · `tor` · `mptun` · `parental-control` · `timer` · `screen` ·
`lpm` · `otg` · `sms-forward` · `bark` · `black_white_list` · `kmwan` · `mvas` ·
`local-access` · `luci` · `vpn-client` · `wg_client` · `ovpn_client`

Quelques signatures utiles :

```
tailscale        get_auth_url, get_config, get_exit_node_list, get_status, logout, set_config
zerotier         get_config, get_status, set_config
tor              get_config, get_status, set_config
mptun            get_config, get_token, set_config          <- tunnel multipath
kmwan            get_config, get_status, set_config, set_interface, set_sensitivity, get_sensitivity
                                                            <- multi-WAN / failover
parental-control add_group, add_rule, get_app_list, set_mode, ...  (15 méthodes)
timer            get/set_led, get/set_reboot, get/set_screen, get/set_wifi
lpm              get_config, get_status, set_config         <- gestion batterie / veille
screen           get_config, get_screen_parameter, get_unlock_attempts, reset_unlock_attempts
mvas             switch_sim_slot, set_connect_slot_net, disconnect_slot_net, get_connect_info
sms-forward      get_config, set_email, set_phone_number
bark             get_config, get_status, logout, set_config <- notifications push
```

## Le verrouillage de tour existe bien sur ce modèle

La doc GL.iNet affirme que Lock Tower n'existe que sur X3000/XE3000/X2000. **C'est faux
pour ce firmware** : `system.get_info` déclare `supports_feature: [..., "lock_tower",
"lock_carrier", ...]`, l'UI contient `lock_tower_title` / `lock_tower_tips`, et les
méthodes répondent :

```
modem.get_cell_tower  {bus}                       -> {slot1:[], slot2:[]}   (rien de verrouillé)
modem.scan_cell_tower {bus, slot}                 -> {towers:[...]}  timeout 600 s, coupe le lien
modem.set_cell_tower  {bus, slot, lock, ...tour}  -> verrouille
modem.get_operator_config / set_operator_config   -> verrouillage opérateur
modem.set_3gpp_rel    {bus, rel_version}          -> version 3GPP (reboot)
```

`bus` = `"cpu"`. Testé en lecture, fonctionne.

C'est **la** voie à utiliser — pas `AT+QNWPREFCFG`, que `/usr/bin/modem_AT` écrase à
chaque init du modem (voir `DIAGNOSTIC.md`). Le firmware passe par sa propre couche, qui
persiste ses réglages ; les commandes AT brutes sont systématiquement écrasées.

## Paquets : la vraie surface

```
/overlay          2,7 Go libres        <- très confortable pour un routeur
architecture      aarch64_cortex-a53   <- architecture OpenWrt standard
paquets installés 1065
paquets dispo     9667                 (dépôts GL.iNet seuls)
```

Dépôts configurés :
```
https://fw.gl-inet.com/releases/sdx72_v1.2/rg650v/kmod-5.15.170/aarch64_cortex-a53/kmod
https://fw.gl-inet.com/releases/sdx72_v1.2/rg650v/packages/aarch64_cortex-a53/glinet
https://fw.gl-inet.com/releases/sdx72_v1.2/rg650v/packages/aarch64_cortex-a53/packages
```

Les dépôts **officiels OpenWrt 23.05.4** pour `aarch64_cortex-a53` répondent HTTP 200 —
donc compatibles et ajoutables si un paquet manque.

Disponible immédiatement, vérifié via `opkg list` :

| Paquet | Version | Intérêt |
|---|---|---|
| `dockerd` / `docker` | 27.0.3 | conteneurs — 2,7 Go d'espace le permettent |
| `podman` | 4.8.0 | alternative sans démon |
| `tailscale` | 1.80.3 | mesh VPN (module RPC natif en plus) |
| `zerotier` | 1.14.1 | réseau virtuel |
| `crowdsec` | 1.6.0 | détection/blocage comportemental |
| `banip` | 1.0.0 | blocklists IP via nftables |
| `sqm-scripts` + `luci-app-sqm` | 1.6.0 | CAKE/SQM — latence sous charge |
| `netdata` | 1.33.1 | métriques temps réel |
| `collectd` + `luci-app-statistics` | | graphes historiques |
| `smartdns` | | DNS parallèle, DoT/DoH, retourne l'IP la plus rapide |
| `nginx`, `python3`, `socat`, `tcpdump`, `iperf3`, `nmap`, `irqbalance` | | outillage |

Absents des dépôts GL.iNet (à prendre chez OpenWrt si besoin) : `frp`, `mosquitto`,
`node`, `mptcp`.

## Pistes non explorées

- **LuCI** est présent (`/www/luci-static`, module RPC `luci`) → `System > Advanced Settings`
- **`container`** apparaît dans `ubus list` → support conteneur déjà côté firmware
- **blue-merle** (randomisation IMEI/MAC, SRLabs) : conçu pour le Mudi GL-E750, le
  portage vers le E5800 est une [issue ouverte](https://github.com/srlabs/blue-merle/issues/86)
- **OpenWrt amont** : [fil de suivi](https://forum.openwrt.org/t/support-for-mudi-7-gl-e5800-from-gl-inet-hotspot/249760)
- **[SDK GL.iNet](https://github.com/gl-inet/sdk)** pour compiler ses propres paquets

## Sources

- [Plug-ins — doc GL.iNet 4](https://docs.gl-inet.com/router/en/4/interface_guide/plugins/)
- [Lock Onto That Cell Tower — GL.iNet](https://www.gl-inet.com/en-us/blogs/blog/lock-onto-that-cell-tower)
- [Cellular — doc GL.iNet 4](https://docs.gl-inet.com/router/en/4/interface_guide/internet_cellular/)
- [Advanced Settings / LuCI](https://docs.gl-inet.com/router/en/4/faq/what_is_luci/)
- [SDK OpenWrt GL.iNet](https://github.com/gl-inet/sdk/)
- [blue-merle](https://github.com/srlabs/blue-merle) · [issue E5800](https://github.com/srlabs/blue-merle/issues/86)
- [OpenWrt — support GL-E5800](https://forum.openwrt.org/t/support-for-mudi-7-gl-e5800-from-gl-inet-hotspot/249760)
- [install kmod-nft-tproxy sur E5800](https://forum.gl-inet.com/t/install-kmod-nft-tproxy-on-mudi-7-gl-e5800/68641)
