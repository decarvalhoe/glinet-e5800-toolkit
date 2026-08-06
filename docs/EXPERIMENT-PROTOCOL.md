# Protocole d'expérimentation sûr

Ce protocole est normatif pour les prochaines phases de la contre-expertise.

## 1. Barrière de sûreté

Une expérience est refusée si elle peut interrompre l'unique accès Internet et qu'aucun
chemin de secours n'est démontré.

### Tests autorisés actuellement

- lecture de `/proc`, `/sys`, ubus, UCI et état réseau ;
- collecte de versions et capacités ;
- ping faible volume et requête HTTPS courte ;
- benchmark LAN plafonné après validation du lien Ethernet ;
- observation PSI/OOM, RAM, swap et zram sans nouvelle activation.

### Tests bloqués actuellement

- reboot ou reset ;
- changement WAN, modem, SIM, APN, bande, cellule ou TTL ;
- changement Wi-Fi, pare-feu, route, DNS, VPN ou SQM ;
- benchmark Internet saturant ;
- mise à jour firmware/noyau ;
- `extroot` ;
- installation/suppression de paquet ;
- activation d'un service qui intercepte le trafic.
- écriture de benchmark USB tant que le FAT n'a pas été vérifié hors ligne ;
- retrait à chaud de la clé ou reset du hub USB partagé avec le RTL8153 ;
- pression mémoire synthétique sans besoin démontré par PSI/OOM.

## 2. Conditions minimales avant un changement réseau

Les cinq conditions suivantes doivent être satisfaites :

1. adaptateur Ethernet `eth1` avec `Link detected: yes` ;
2. session SSH maintenue via ce lien, indépendamment du Wi-Fi ;
3. sauvegarde expurgée et copie privée complète des fichiers concernés ;
4. commande de retour arrière testée sans dépendance Internet ;
5. critère d'arrêt écrit avant l'expérience.

Un minuteur de restauration automatique n'est pas considéré comme un accès de secours :
il peut restaurer au mauvais moment et empirer l'incident.

## 3. Format d'une expérience

Chaque expérience possède un identifiant et un dossier :

```text
evidence/YYYYMMDDTHHMMSSZ-<id>/
  metadata.txt
  precondition.txt
  run-01.txt
  run-02.txt
  run-03.txt
  postcondition.txt
  SHA256SUMS
```

`metadata.txt` contient au minimum :

- heure UTC ;
- commit Git ;
- firmware et uptime ;
- objet et hypothèse falsifiable ;
- variable modifiée ;
- variables maintenues constantes ;
- taille et durée maximales ;
- critères d'arrêt ;
- méthode de rollback.

## 4. Règles de mesure

Statuts de preuve :

- `OBSERVÉ` : observation directe avec sortie horodatée et hash ;
- `REPRODUIT` : même résultat lors d'un second run distinct ;
- `INFÉRÉ` : déduction explicitant ses hypothèses ;
- `SOURCE EXTERNE` : constructeur ou projet tiers, jamais assimilé à une observation ;
- `NON TESTÉ` : non vérifié sur cet appareil et ce firmware.

La présence d'un paquet doit être distinguée de son installation, activation, exécution
et fonctionnement. Une expurgation crée un nouvel artefact ; elle ne remplace pas le brut
privé. Chaque future commande doit enregistrer début/fin UTC, code retour, stdout, stderr
et hash de sortie.

- au moins cinq répétitions pour une affirmation de performance ;
- alternance A/B/B/A ou ordre randomisé ;
- médiane, dispersion et valeurs brutes, pas seulement une moyenne ;
- même serveur, même protocole, même nombre de flux et même taille ;
- charge CPU, mémoire, température et état radio consignés ;
- résultat négatif conservé ;
- absence de différence qualifiée « non démontrée », jamais « identique » ;
- disponibilité dans `opkg list` qualifiée « disponible », jamais « compatible » sans test.

## 5. Critères d'arrêt communs

Arrêt immédiat si l'un des événements suivants apparaît :

- deux pings consécutifs perdus vers le routeur ;
- échec de la sonde HTTPS ;
- disparition de l'interface WAN ou de la route par défaut ;
- erreur USB/xHCI nouvelle ;
- espace libre inférieur au double de la taille de test ;
- mémoire disponible inférieure à 256 MiB ;
- load average supérieur à 8 pendant plus de 30 secondes ;
- température sortant de la plage normale observée ;
- erreur d'écriture, remontage USB en lecture seule ou OOM.

## 6. Séquence USB/mémoire

1. observer PSI mémoire et journaux OOM pendant plusieurs jours ;
2. lire les erreurs USB/FAT et confirmer le nettoyage des anciens fichiers temporaires ;
3. sauvegarder la clé sur une autre machine ;
4. vérifier/réparer le FAT hors ligne, jamais monté sur le routeur ;
5. ne reprendre un benchmark d'écriture qu'après contrôle favorable ; imposer des timeouts
   côté routeur et traiter l'absence non prouvée du fichier temporaire comme un échec ;
6. préférer ensuite une seconde clé/SSD EXT4 pour les données applicatives ;
7. n'envisager zram que si PSI/OOM démontre une pression réelle ; tout essai doit
   restaurer et vérifier swap, `disksize` et `comp_algorithm` avec timeouts indépendants ;
8. ne considérer swap USB qu'après zram, avec priorité inférieure et sans retrait à chaud.

Le routeur doit continuer à router sans la clé. `extroot` reste exclu : l'overlay interne
dispose déjà d'espace et le GL-E5800 n'a pas de récupération U-Boot documentée.

## 7. Séquence adaptateur Ethernet

1. brancher un câble entre l'adaptateur RTL8153 et une machine de test isolée, sans autre DHCP ;
2. observer la négociation sans modifier UCI ;
3. vérifier DHCP/LAN et SSH ;
4. exécuter `iperf3` LAN à 5 puis 10 Mbit/s, 10 secondes maximum et un seul flux ;
5. relever erreurs, drops, IRQ et CPU ;
6. valider le lien comme accès de secours seulement après trois essais sans perte.
