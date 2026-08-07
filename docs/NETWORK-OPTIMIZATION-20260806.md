# Optimisation réseau bornée — 2026-08-06

## Résumé

Une optimisation persistante et limitée à l'ingress SQM du modem a été appliquée au
GL-E5800 après validation d'un accès Internet indépendant par partage USB du téléphone.

État final observé :

- `sqm.modem.download='5000'` ;
- `sqm.modem.iqdisc_opts='nat dual-dsthost ingress'` ;
- CAKE actif sur `ifb4rmnet_data1` à `5Mbit`, sans `autorate-ingress` ;
- interface modem observée `up` ;
- accès HTTPS par le routeur : HTTP 200 ;
- accès HTTPS par le téléphone : HTTP 200 ;
- accès SSH/LAN au routeur conservé.

Aucun changement n'a été apporté au modem, à l'APN, aux bandes radio, au Wi-Fi, au
pare-feu, au DNS, au bridge, à Qualcomm IPA, aux masques RPS/XPS ou aux affinités IRQ.

## 1. Téléphone de secours

### OBSERVÉ

Windows expose le téléphone comme `Remote NDIS based Internet Sharing Device #2` et le
routeur par l'interface Wi-Fi. Des requêtes HTTPS liées explicitement à chaque interface
ont retourné HTTP 200. Les empreintes des adresses publiques de sortie sont différentes :
le téléphone ne retransmettait donc pas la connexion publique du GL-E5800 au moment du
test.

Les deux passerelles étaient joignables. Le téléphone fournit ainsi un accès Internet
physiquement indépendant pour le poste de travail.

### Limite importante

Le téléphone est branché au poste Windows, pas au GL-E5800. Il n'est donc ni une interface
`usb0` du routeur, ni un membre `mwan3`. Cela protège l'accès Internet du poste en cas de
perte du lien Wi-Fi ou de sélection de la route téléphone, mais ne constitue pas une preuve
de basculement automatique lorsque le Wi-Fi reste associé et que seul l'amont du routeur
tombe.

Lors du dernier relevé, la métrique Windows était `25` pour le téléphone et `30` pour le
Wi-Fi : le téléphone était donc la route préférée du poste, et non une route secondaire.
Ce choix a garanti un accès Internet indépendant durant l'expérimentation, mais peut
consommer le forfait mobile. Aucune métrique Windows n'a été modifiée par cette session.

Preuve : `evidence/20260806T210801Z-phone-secondary/`.

## 2. Baseline SQM

### Configuration initiale

- interface : `rmnet_data1` ;
- qdisc : CAKE, script `piece_of_cake.qos` ;
- download UCI maximal : `45000` kbit/s ;
- upload : `0` ;
- options ingress : `nat dual-dsthost ingress autorate-ingress`.

Après une période d'activité, l'estimateur CAKE avait réduit la bande passante observée à
environ `0,42 Mbit/s`. La capture ping simultanée à un essai de charge montre 0 % de
perte, une moyenne de `22,55 ms` et un maximum de `102,27 ms`.

Les sorties réussies `curl.exe` des premiers essais n'avaient pas été redirigées vers les
artefacts publiés. Leurs valeurs de débit vues pendant la session ne sont donc pas
reproductibles depuis le snapshot et sont classées **NON PROUVÉES**. La seule sortie curl
du premier lot est un échec avant connexion (`http=000`, 0 octet) ; son artefact ne prouve
pas à quelle interface la requête était liée.

## 3. Expériences A/B

Chaque essai a utilisé uniquement un changement runtime du qdisc ingress. Un rollback SQM
temporisé était armé avant l'essai. Le WAN, le LAN, le téléphone et SSH ont été contrôlés.
Les pertes et latences ci-dessous sont publiées ; les débits historiques ne le sont pas.

| Réglage | Débit publié | Perte ping | Ping moyen | Ping max | Verdict |
|---|---:|---:|---:|---:|---|
| autorate observé | NON PROUVÉ | 0 % | 22,55 ms | 102,27 ms | estimateur observé à ~0,42 Mbit/s |
| fixe 5 Mbit/s | NON PROUVÉ | 0 % | 18,60 ms | 56,41 ms | candidat prudent |
| fixe 10 Mbit/s | NON PROUVÉ | 2,14 % | 18,90 ms | 40,55 ms | rejeté par critère de perte |
| fixe 8 Mbit/s, essai 1 | NON PROUVÉ | 0 % | 22,06 ms | 50,37 ms | prometteur |
| fixe 8 Mbit/s, essai 2 | NON PROUVÉ | 2,5 % | 18,95 ms | 37,98 ms | rejeté par critère de perte |
| fixe 5 Mbit/s avant revue | NON PROUVÉ | 0 % | 19,40 ms | 40,30 ms | candidat prudent |

Après le premier verdict indépendant, une nouvelle validation autoportante a enregistré la
sortie réussie de `curl.exe`, le ping et l'état SQM dans le même lot. À 5 Mbit/s :

- HTTP 200 et exactement 1 000 000 octets reçus ;
- `474626` octets/s, soit `3,797 Mbit/s`, pendant `2,106930 s` ;
- ping : 100 envoyés, 98 reçus, 2 % de perte, moyenne `19,04 ms`, maximum `39,44 ms` ;
- UCI `download=5000`, CAKE `5Mbit`, WAN observé `up`.

Cette perte de 2 % sur un passage impose une surveillance. Elle ne constitue pas encore le
critère de pertes **répétées** défini plus bas, mais interdit de présenter 5 Mbit/s comme
universellement sans perte. Aucun ratio d'amélioration par rapport à la baseline n'est
revendiqué, faute de sortie curl baseline publiée.

## 4. Changement persistant appliqué

```sh
uci set sqm.modem.download='5000'
uci set sqm.modem.iqdisc_opts='nat dual-dsthost ingress'
uci commit sqm
/etc/init.d/sqm restart
```

Postconditions observées :

```text
download=5000
iqdisc_opts=nat dual-dsthost ingress
qdisc cake ... bandwidth 5Mbit ... ingress ...
wan_up=true
rollback_timer_absent=yes
```

Empreinte finale de `/etc/config/sqm` :

```text
ebca1000b6f3b4f26a8d15785aef46d3fc22c601a19b7ec73d07e81f0e978265
```

Le service SQM a signalé une tentative de suppression d'un qdisc root absent sur
`rmnet_data1`, puis a explicitement confirmé le démarrage réussi de
`piece_of_cake.qos`. Cette anomalie non bloquante est conservée dans les preuves. Un
timeout HTTPS immédiatement après un redémarrage SQM a été vu dans la sortie de session,
mais n'avait pas été enregistré dans le lot ; il est donc classé **NON PROUVÉ** par le
snapshot. Les HTTP 200 ultérieurs sont, eux, publiés.

Le premier timer de rollback persistant de 90 secondes a expiré avant son annulation. Le
qdisc revient à `45Mbit autorate-ingress` exactement 90 secondes après l'application à
8 Mbit/s, ce qui prouve l'exécution du rollback runtime. En revanche, le hash initial
`1719…` publié dans `after-ab-rollback.txt` est antérieur à ce timer : la restauration de
ce hash précis par ce timer est donc **NON TESTÉE**. Le réglage final à 5 Mbit/s a ensuite
été réappliqué avec un timer de 180 secondes. Après les postconditions, le processus de
rollback et son processus `sleep` enfant ont été arrêtés, son artefact temporaire supprimé
et leur absence vérifiée.

La persistance UCI et le redémarrage du service ont été vérifiés. Aucun redémarrage complet
du routeur n'a été effectué.

## 5. Rollback exact

Pour revenir à la configuration observée avant cette session :

```sh
uci set sqm.modem.download='45000'
uci set sqm.modem.iqdisc_opts='nat dual-dsthost ingress autorate-ingress'
uci commit sqm
/etc/init.d/sqm restart
```

Empreinte de la configuration initiale :

```text
1719d16aedaa0c54ee37420f0576fddf9c312f9b9cd768ebab3a7b23a1b040c3
```

## 6. Optimisations non appliquées

- **Qualcomm IPA** : déjà actif ; aucune preuve que sa désactivation améliorerait le lien.
- **RPS/XPS et IRQ** : à 5 Mbit/s, aucun goulot CPU démontré ; une modification serait
  spéculative et pourrait dégrader le fastpath.
- **Upload CAKE** : `upload=0` et aucun protocole de mesure fiable de l'upload n'a été
  exécuté ; aucune valeur n'a été inventée.
- **Diffserv** : `piece_of_cake.qos` reste en `besteffort` ; changer la politique de classes
  demanderait un protocole distinct portant sur plusieurs types de trafic.
- **Modem/radio** : hors périmètre de cette optimisation et inchangé.

## 7. Surveillance recommandée

Le réglage fixe protège mieux la session observée contre l'effondrement de
`autorate-ingress`, mais une liaison cellulaire peut descendre sous 5 Mbit/s. Il faut
surveiller pendant les périodes faibles :

- débit utile ;
- pertes ;
- ping sous charge ;
- backlog et drops CAKE ;
- qualité et technologie radio.

Critère de rollback conseillé : pertes répétées supérieures à 1 %, hausse durable de la
latence sous charge, ou débit réel fréquemment inférieur au plafond de 5 Mbit/s.

## 8. Preuves

- expérimentation et incidents : `evidence/20260806T203442Z-network-opt/` ;
- baseline read-only après changement : `evidence/20260806T210306Z-post-network-opt/` ;
- indépendance du téléphone : `evidence/20260806T210801Z-phone-secondary/` ;
- validation autoportante finale à 5 Mbit/s :
  `evidence/20260806T211923Z-final-fixed5-validation/`.

Chaque dossier contient un manifeste `SHA256SUMS`. Les éléments privés non expurgés restent
sous `.evidence-private/`, hors Git.
