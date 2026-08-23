# Runtime : chroot Alpine sur le routeur

Comment le tooling « riche » (Node, Python, agents) tourne **sur le routeur** malgré un
firmware OpenWrt minimal : un **chroot Alpine** posé sur l'overlay de l'appareil.

## Architecture — `OBSERVÉ` 2026-08-23

- Rootfs **Alpine v3.20 aarch64** dans **`/opt/alpine`** (~788 Mo) sur l'overlay ext4
  (2,7 Go libres). Contient `git`, `node`, `python3.12`.
- Bootstrap : `/root/bootstrap-alpine.sh` télécharge la `alpine-minirootfs` v3.20 aarch64
  depuis le CDN Alpine et la dépose dans `/opt/alpine`.
- Lanceur : `/usr/bin/claude-code` — bind-monte `proc`, `sys`, `dev`, `dev/pts` dans le
  chroot puis `chroot /opt/alpine … node …`. Les montages ne survivent pas au reboot ; le
  lanceur les rétablit.

Conséquence : le userland Alpine partage le **noyau, le namespace réseau et le namespace PID**
de l'hôte OpenWrt. Il voit donc `rmnet_data0`, tout `/proc/net/dev`, et peut joindre le
routeur en local.

## Accès direct au système de fichiers hôte : `/proc/1/root`

Le chroot n'expose pas `/` de l'hôte… **mais** `/proc` est bind-monté et le namespace PID
est partagé, donc **`/proc/1/root/` est la racine réelle de l'hôte** (PID 1 = init OpenWrt).
Avec les droits root (mêmes uid), on lit/écrit directement l'hôte :

```sh
ls   /proc/1/root/etc/init.d/           # voir les services hôte
cp   monfichier /proc/1/root/etc/…      # écrire sur l'hôte, sans SFTP/base64
```

Pourquoi c'est la bonne méthode ici : le busybox de l'hôte **n'a pas `base64`** et son
dropbear **n'a pas SFTP** (`exit 127`). `/proc/1/root` contourne tout ça.

## Exécuter des commandes hôte sans SSH

Le shebang OpenWrt (`#!/bin/sh /etc/rc.common`, `ubus`, `uci`) doit tourner **en contexte
hôte**. Depuis le chroot :

```sh
chroot /proc/1/root ubus call system board          # ubus hôte
chroot /proc/1/root /etc/init.d/<svc> status         # init hôte
chroot /proc/1/root uci show network                 # uci hôte
```

C'est l'équivalent d'un SSH `root@192.168.8.1`, sans réseau ni client SSH. **Règle adoptée :
toute commande qui peut éviter SSH le fait via `chroot /proc/1/root …`.**

## Persistance au boot

Le monitoring vit dans le chroot (`/opt/alpine/opt/radio-monitor/`, persistant sur
l'overlay). Pour l'auto-démarrer, un service **procd côté hôte**
([`etc/init.d/radio-monitor`](../etc/init.d/radio-monitor)) rétablit les montages puis
`chroot /opt/alpine /usr/bin/python3 …` pour chaque instance. Activé (`S95`), réversible
(`disable` + `rm`).

## Sûreté

Depuis ce chroot j'ai **root dans le chroot ET root sur l'hôte** (via `/proc/1/root` et
`chroot`). La règle « ne jamais risquer le WAN cellulaire » (unique lien, cf.
COUNTER-EXPERTISE.md) est donc une **discipline**, pas une barrière technique : tout ce qui
mute le réseau/modem est fait explicitement et validé, jamais en automatique.

## Reproduction

```sh
# depuis le chroot Alpine
ls /proc/1/root/etc/openwrt_release        # confirme : racine hôte OpenWrt 23.05.4
cat /opt/alpine/etc/os-release             # confirme : Alpine v3.20
head /usr/bin/claude-code                  # (hôte) le lanceur chroot
```
