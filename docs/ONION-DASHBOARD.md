# Dashboard en service caché Tor (.onion)

Expose le dashboard de [`radio-monitor`](../tools/radio-monitor.py) (`127.0.0.1:8090`) en
**service caché Tor v3 avec client-auth**, joignable **de partout malgré le CGNAT** (WAN
cellulaire sans IP publique), sans port forwarding ni DDNS.

## Pourquoi

Le WAN cellulaire n'a pas d'IP publique entrante → le routeur est injoignable de l'extérieur.
Un onion service se connecte **en sortant** au réseau Tor : pas d'entrée, pas d'IP publique.
L'adresse `.onion` est auto-authentifiée (chiffrement de bout en bout, sans certificat), et
le **client-auth** la rend accessible **uniquement** aux appareils possédant la clé.

## Sûreté

Instance Tor **autonome** : `SocksPort 0`, **pas de `TransPort`** → ne touche NI au routage
NI au firewall du routeur, n'affecte pas le trafic des clients LAN. Sortant seulement.
Service procd [`etc/init.d/onion-dashboard`](../etc/init.d/onion-dashboard), persistant
(`S96`), réversible (`disable` + `rm` + `rm -rf /root/tor-onion`).

## Mise en place (runtime, hors dépôt — la clé de service est secrète)

`torrc` (`/root/tor-onion/torrc`) :

```
DataDirectory /root/tor-onion/data
SocksPort 0
HiddenServiceDir /root/tor-onion/hs
HiddenServiceVersion 3
HiddenServicePort 80 127.0.0.1:8090
Log notice file /root/tor-onion/notice.log
```

Au premier lancement, Tor génère l'adresse dans `/root/tor-onion/hs/hostname`.

### Client-auth (verrouiller à tes appareils)

Générer une paire x25519 et autoriser la clé publique côté service :

```sh
openssl genpkey -algorithm x25519 -out cli.pem
# clé publique (base32) -> autorisée côté service
PUB=$(openssl pkey -in cli.pem -pubout | grep -v KEY | base64 -d | tail -c32 | base32 | tr -d =)
mkdir -p /root/tor-onion/hs/authorized_clients
printf 'descriptor:x25519:%s\n' "$PUB" > /root/tor-onion/hs/authorized_clients/phone.auth
# clé privée (base32) -> à mettre côté client
PRV=$(cat cli.pem | grep -v KEY | base64 -d | tail -c32 | base32 | tr -d =)
echo "<onion-sans-.onion>:descriptor:x25519:$PRV"
```

Redémarrer : `/etc/init.d/onion-dashboard restart`.

## Côté client

- **Tor Browser (PC)** : déposer un fichier `nom.auth_private` dans
  `TorBrowser/Data/Tor/onion-auth/` contenant `‹onion56›:descriptor:x25519:‹CLE_PRIVEE›`,
  puis relancer. (Tor Browser récent propose aussi de coller la clé au 1er accès.)
- **Orbot (Android)** : réglages → *v3 Onion Service Client Auth* → ajouter l'adresse + la clé privée.

Puis ouvrir `http://‹onion56›.onion`.

## Installation du service

```sh
cp etc/init.d/onion-dashboard /etc/init.d/ && chmod +x /etc/init.d/onion-dashboard
/etc/init.d/onion-dashboard enable && /etc/init.d/onion-dashboard start
```
