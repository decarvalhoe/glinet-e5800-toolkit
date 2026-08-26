# Session 2026-08-26 — écran tactile, Bluetooth WCN7850 et LuCI

## But de ce document

Ce document permet de reprendre le travail sans dépendre du transcript de la session.
Il distingue les fonctions **vérifiées sur le routeur**, les sources sauvegardées dans ce
dépôt et le gestionnaire Bluetooth générique **encore inachevé**.

> **État de fin de session : accès routeur perdu.** Windows a quitté le réseau
> `192.168.8.0/24` et a rejoint un réseau `192.168.1.0/24`. Le GL-E5800 à
> `192.168.8.1` ne répondait plus depuis la machine de travail. Ne déduire ni panne ni
> état runtime final du routeur avant d'avoir rétabli le lien local.

## Séquence de reprise obligatoire

1. Reconnecter Windows au Wi-Fi du GL-E5800 ou relier son port Ethernet.
2. Vérifier `ping 192.168.8.1`, puis `ssh -o BatchMode=yes glinet 'echo OK'`.
3. Vérifier les processus avant toute installation :

   ```sh
   ssh glinet 'ps w | grep -E "[b]tapp|[q]cbtdaemon|[g]l-bluetooth-run"'
   ```

4. La perte d'accès s'est produite après l'arrêt du service permanent et le lancement
   d'un `btapp` interactif pour inventorier les menus A2DP/PAN. Nettoyer cet éventuel
   processus interactif, puis repartir à froid :

   ```sh
   ssh glinet '
     /etc/init.d/gl-bluetooth stop 2>/dev/null
     killall btapp qcbtdaemon 2>/dev/null
     rm -f /var/run/gl-bluetooth.in \
           /data/misc/bluetooth/btappsocket \
           /data/misc/bluetooth/qcbtdaemon.pid
     /etc/init.d/gl-bluetooth start
     sleep 15
     /usr/bin/gl-bluetooth-web status
   '
   ```

5. Vérifier ensuite Internet, le rfkill Wi-Fi et l'écran. Ne pas redémarrer le routeur
   tant qu'un chemin d'administration indépendant n'est pas disponible.

## 1. Application graphique embarquée — vérifié

Le framebuffer de l'écran est `/dev/fb0`, 240×320, RGB565. La build SDL d'Alpine ne
fournit pas `fbcon`; le rendu fonctionnel utilise Pillow puis convertit l'image en
RGB565 avant écriture directe dans le framebuffer.

Sources sauvegardées :

- `screenapps/app.py` — dashboard réseau + horloge analogique ;
- `screenapps/screenapps` — start/stop/status et changement de mode ;
- `tools/health-watchdog.sh` — journal de santé non intrusif.

Runtime observé sur le routeur :

- sources hôte : `/opt/screenapps` ;
- copie chroot : `/opt/alpine/opt/screenapps` ;
- Python 3.12, Pillow et pygame installés dans le chroot ; pygame n'est finalement pas
  utilisé pour la sortie vidéo ;
- police copiée depuis le firmware vers
  `/opt/alpine/opt/screenapps/fonts/default_mono_medium.ttf` ;
- commande installée : `/usr/bin/screenapps` ;
- service `/etc/init.d/screenapps` créé mais laissé désactivé au boot.

Tactile vérifié sur `/dev/input/event0`, protocole multitouch type B :

- tap court : bascule dashboard ↔ horloge ;
- appui long (~1,2 s) : quitte l'application et laisse l'UI native reprendre l'écran ;
- lectures simultanées possibles avec `gl_screen` ;
- coordonnées natives déjà en 240×320.

## 2. Activation Bluetooth WCN7850 — vérifié

Matériel observé :

- contrôleur Qualcomm WCN7850 ;
- UART `/dev/ttyHS0` ;
- driver `bt_power` et rfkill dédié ;
- pile fonctionnelle : QTI `btapp` + `qcbtdaemon`, pas BlueZ.

BlueZ 5.66 a été installé pour diagnostic, mais son daemon a été désactivé car il entre
en conflit avec la pile QTI.

### Firmware

La partition `/firmware` est une VFAT montée en lecture seule. Les firmwares ont été
placés dans le chemin alternatif supporté par QTI :

- `/vendor/bt_firmware/image/hmtbtfw20.tlv` ;
- `/vendor/bt_firmware/image/hmtnv20.bin` ;
- `/vendor/bt_firmware/image/htmbtfw20.tlv`.

Le troisième fichier est un alias indispensable : la bibliothèque du firmware contient
une faute (`htm...` au lieu de `hmt...`) dans son chemin de repli.

Sources officielles redistribuables :

- `https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/qca/hmtbtfw20.tlv`
- `https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/qca/hmtnv20.bin`

SHA-256 vérifiés :

```text
f1c00f4640a5c4e5dc36a2574d3d1d0afcfd1ab58a84f217dce4b1bb73cba981  hmtbtfw20.tlv
c26b340bbc8b617304610c774627ac4879194705eea7a7c7b13e3593903befd9  hmtnv20.bin
```

Les blobs ne sont volontairement pas versionnés dans ce dépôt.

### Service persistant

Sources sauvegardées :

- `etc/init.d/gl-bluetooth` ;
- `usr/bin/gl-bluetooth-run` ;
- `usr/bin/gl-bt-keyboard-connect` ;
- `etc/bluetooth/gl-bluetooth-device.conf.example`.

Le runner ouvre `/var/run/gl-bluetooth.in` (FIFO mode 0600), puis fait **exec** de
`btapp`. Ce `exec` est essentiel : une version précédente lançait `btapp` comme enfant,
laissait un processus orphelin après Stop et le démarrage suivant échouait sur l'UART.

Le service :

- tue les vieux `btapp`/`qcbtdaemon` ;
- supprime sockets et FIFO obsolètes ;
- bascule uniquement le rfkill dont le nom vaut exactement `bt_power` ;
- ne touche jamais au rfkill Wi-Fi ;
- attend l'initialisation QTI avant de déclarer le service actif.

Cycle vérifié : zéro processus après Stop, puis exactement `btapp` + `qcbtdaemon` après
Start, toujours actifs après un second contrôle différé. Internet est resté fonctionnel.

## 3. Appairage HID BLE — vérifié

Un clavier BLE réel a été détecté, appairé et connecté. Son adresse n'est pas publiée
dans le dépôt.

La commande GAP `pair <MAC>` seule retourne immédiatement `BOND NONE`. Le chemin
fonctionnel est :

1. mettre le périphérique en mode pairing ;
2. `gattctest_menu` ;
3. `gattctest_init` ;
4. `gattctest_connect <MAC> 2` (`2` = transport LE) ;
5. attendre `Please enter yes / no`, répondre immédiatement `yes` ;
6. vérifier `Pairing state ... BONDED` ;
7. `hid_menu`, puis `connect <MAC>` ;
8. vérifier `hid_list` : une entrée, état 4.

Des frappes réelles ont produit des callbacks `KEYPRESS RELEASE`, preuve que le profil
HID QTI reçoit les rapports. La pile QTI ne crée toutefois pas de nouveau
`/dev/input/event*`. Un pont vers Linux `uinput` reste à développer pour piloter les
applications écran.

Le bond est stocké dans `/data/misc/bluetooth/bt_config.conf`; un cache par périphérique
`gatt_cache_*` est également créé. Ne pas chercher les bonds dans `bt_profile.conf`.

Le fichier local `/etc/bluetooth/gl-bluetooth-device.conf` contient l'adresse du
périphérique et ne doit pas être versionné. Voir l'exemple fourni.

## 4. Interface LuCI installée — version spécialisée vérifiée

Fichiers sauvegardés :

- `usr/bin/gl-bluetooth-web` ;
- `www/luci-static/resources/view/system/bluetooth.js` ;
- `usr/share/luci/menu.d/luci-app-gl-bluetooth.json` ;
- `usr/share/rpcd/acl.d/luci-app-gl-bluetooth.json`.

Route : **Système → Bluetooth**

```text
https://192.168.8.1:8443/cgi-bin/luci/admin/system/bluetooth
```

Vérifications réalisées avant perte d'accès :

- JSON menu et ACL valides avec `jsonfilter` ;
- JavaScript valide avec `node --check` ;
- vue statique HTTP 200 ;
- route HTTP 403 avec `x-luci-login-required: yes` avant authentification (attendu) ;
- entrée présente dans le cache d'index LuCI ;
- backend limité à une allowlist d'actions ;
- ACL conforme au modèle LuCI officiel : l'autorisation de méthode
  `ubus.file.exec` est nécessaire à `fs.exec`, tandis que la section `file` limite
  l'exécution aux commandes complètes `/usr/bin/gl-bluetooth-web <action>` ; aucune
  entrée générique `/usr/bin/gl-bluetooth-web` n'est accordée ;
- le snapshot du dépôt propage désormais les échecs init/FIFO/helper en JSON
  `ok:false` et vérifie les processus après Start/Stop/Restart ; cette correction
  post-session n'a pas pu être redéployée après la perte d'accès ;
- Stop/Start et Scan exercés réellement ;
- correction du bug de processus `btapp` orphelin validée.

La source versionnée est assainie : aucune MAC locale. Elle lit
`/etc/bluetooth/gl-bluetooth-device.conf`.

## 5. Gestionnaire Bluetooth générique — à poursuivre

La demande finale est une vraie interface capable de gérer plusieurs périphériques,
pas seulement un clavier connu. Cette évolution a été conçue mais **pas implémentée ni
déployée** avant la perte d'accès.

Profils QTI inventoriés :

| Profil | État de config observé | Commandes de connexion |
|---|---:|---|
| BLE / GATT | activé | `gattctest_init`, `gattctest_connect <MAC> 2`, `gattctest_disconnect <MAC>` |
| HID | activé | `hid_menu`, `connect <MAC>`, `disconnect <MAC>` |
| PAN | activé | `pan_menu`, `connect <MAC>`, `disconnect <MAC>` |
| A2DP source | désactivé | `a2dp_source_menu`, `connect <MAC>`, `disconnect <MAC>` |
| A2DP sink | désactivé | `a2dp_sink_menu`, `connect <MAC>`, `disconnect <MAC>` |
| HFP/PBAP/OPP | désactivés | ne pas exposer avant tests dédiés |

Prochaine implémentation :

1. étendre `gl-bluetooth-web` avec validation stricte des MAC
   (`XX:XX:XX:XX:XX:XX`) et allowlist des profils ;
2. lancer un scan borné, parser après un marqueur syslog les lignes
   `Found device Addr`, `Found device Name`, `Device Type` ;
3. retourner une liste JSON sans publier les MAC dans les logs du dépôt ;
4. afficher une table LuCI : nom, adresse, type, bond, profil choisi, actions
   Pair/Unpair/Connect/Disconnect ;
5. pour BLE : établir GATT LE avant le bond et attendre la confirmation ;
6. ne présenter A2DP/HFP que si le profil est activé et testé ;
7. ajouter tests adversariaux : MAC invalide, profil non allowlisté, injection shell,
   FIFO absente, service arrêté, timeout pairing, périphérique endormi ;
8. vérifier après chaque action : processus, rfkill Wi-Fi, Internet et espace `/tmp`.

## 6. Pièges observés

- `scp` moderne échoue car le routeur n'a pas `sftp-server`; utiliser `scp -O`.
- Ne jamais rediriger sans limite la sortie de `btapp` dans `/tmp` : un essai a rempli le
  tmpfs (~805 Mo). Utiliser syslog ou une capture bornée et vérifier `df -P /tmp`.
- Le nom alternatif du rampatch est inversé dans la bibliothèque QTI.
- Une réponse Start trop rapide peut masquer un crash dix secondes plus tard : attendre
  au moins 15 secondes avant de retourner l'état.
- Le wrapper procd doit `exec` le vrai processus, sinon l'UART reste possédé par un
  orphelin.
- La perte d'accès finale correspond à un changement de réseau Windows, mais l'état exact
  du routeur doit être recollecté avant de reprendre.

## 7. Fichiers de cette livraison

```text
screenapps/app.py
screenapps/screenapps
tools/health-watchdog.sh
etc/init.d/gl-bluetooth
etc/bluetooth/gl-bluetooth-device.conf.example
usr/bin/gl-bluetooth-run
usr/bin/gl-bt-keyboard-connect
usr/bin/gl-bluetooth-web
www/luci-static/resources/view/system/bluetooth.js
usr/share/luci/menu.d/luci-app-gl-bluetooth.json
usr/share/rpcd/acl.d/luci-app-gl-bluetooth.json
```

Ce snapshot est une base de reprise. Comparer les fichiers du dépôt aux fichiers live
avant toute réinstallation, car le routeur est devenu inaccessible avant la dernière
lecture de contrôle.

Deux corrections issues de l'auto-revue sont présentes dans le dépôt mais n'ont pas pu
être redéployées sur le routeur après la perte d'accès :

- `screenapps/screenapps` écrit désormais `screenapp.mode` et `screenapp.quit` dans
  `/opt/alpine/tmp`, qui correspond réellement à `/tmp` vu depuis le chroot ;
- `tools/health-watchdog.sh` retourne explicitement 0 lorsqu'aucune rotation n'est
  nécessaire ;
- `usr/bin/gl-bluetooth-web` échoue maintenant explicitement si init/FIFO/helper
  échoue, au lieu de retourner un statut apparemment réussi.
