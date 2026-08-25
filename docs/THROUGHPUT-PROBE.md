# Sonde de débit périodique — et deux artefacts de mesure du modem

Outil : [`tools/throughput-probe.sh`](../tools/throughput-probe.sh) ·
service : [`etc/init.d/throughput-probe`](../etc/init.d/throughput-probe)

Mesure le débit descendant **depuis le routeur** (donc sans Wi-Fi ni poste dans la boucle) et
relève la radio **dans la même fenêtre**, pour répondre à une seule question : quand le débit
s'effondre, est-ce que la radio s'est dégradée ?

Une ligne JSON par échantillon dans `/opt/throughput-probe/throughput.jsonl` :

```json
{"ts":"2026-08-25T12:09:08Z","mbps":7.692,"carriers":4,
 "bands":"LTE BAND 7+LTE BAND 3+LTE BAND 20+NR5G BAND 8","rrc":"connected",
 "lte":{"band":7,"rsrp":-92,"rsrq":-12,"sinr":12},
 "nr":{"band":8,"arfcn":188450,"bw":2,"rsrp":-82,"sinr":17},"load":4.33}
```

Lecture seule côté modem : aucune commande AT de réglage, aucune écriture UCI, aucune action
WAN. Coût : une fenêtre de `--dur` secondes toutes les `--interval` secondes — 1,7 % du temps
aux valeurs par défaut (10 s / 600 s).

## Les deux artefacts que la sonde contourne — `OBSERVÉ` le 2026-08-25

Ils ont produit, le même jour, **deux conclusions fausses** avant d'être identifiés.

### 1. `AT+QCAINFO` vide ne signifie pas « agrégation perdue »

Il ne liste les porteuses que sous connexion RRC. Interrogé au repos — `+QENG:
"servingcell","NOCONN"` le signalait à chaque fois — il renvoie `OK` et rien d'autre.

Conclusion fausse qui en a été tirée : « l'agrégation de porteuses a disparu ». Sondé sous
charge, le même modem donne `PCC B7 20 MHz + SCC B3 20 MHz + SCC B20 10 MHz + SCC NR`, soit
exactement la combinaison relevée le 17 août.

La sonde interroge donc `QCAINFO` **pendant** le téléchargement, avant `QENG`.

### 2. Le pont `ubus call modem.CPU.AT` tronque et rate des réponses

Vérifié en rafale sur **la même commande**, huit fois de suite :

| `AT+QNWPREFCFG="nsa_nr5g_band"` | occurrences |
|---|---|
| `1:3:5:7:8:20:26:28:38:40:41:75:76:77:78` | 5 / 8 |
| `1:3:5:7:8:20:26:28:38:40:41` (coupée) | 3 / 8 |

Conclusion fausse qui en a été tirée : « n78 a été retirée du masque de bandes ». Il n'en est
rien — la réponse était tronquée. Des lectures entrelacées de commandes différentes donnent en
plus des réponses qui ne correspondent pas à la question posée.

**Règle** : sur ce pont, une lecture AT unique ne vaut pas preuve. Répéter jusqu'à obtenir une
réponse contenant le motif attendu. La sonde le fait (jusqu'à 6 essais pour `QENG`) et écrit
`null` plutôt qu'une valeur inventée quand elle échoue.

Précision ajoutée le même jour : le pont ne fait pas que tronquer, **il rend parfois une
valeur périmée**. Après écriture d'un masque, 8 lectures sur 10 donnaient la nouvelle valeur et
2 sur 10 l'ancienne. La bonne règle de dépouillement est donc le **vote majoritaire**, pas
« garder la réponse la plus longue » — cette dernière retient précisément la vieille valeur
quand celle-ci est plus longue.

### 3. Le point de mesure répond `429`

Après une série de mesures, `speed.cloudflare.com` limite le client et renvoie `HTTP 429` avec
un débit quasi nul. Consigné sans vérification, cela ressemble à un effondrement du lien.
Le même test a donné 12-19 Mbit/s sur Cloudflare bridé et **46-48 Mbit/s sur `cachefly` dans
la minute suivante**.

La sonde alterne donc plusieurs sources et **enregistre le code HTTP** (`"http":200`) ; un code
différent de 200 écrit `mbps: null` au lieu d'un faux zéro.

## Ce que la sonde a établi — `OBSERVÉ`

Dix mesures en 90 secondes, depuis le routeur :

```text
11,85  0,94  2,59  1,87  2,14  2,81  0,60  2,42  0,74  6,03   Mbit/s
```

Pendant toute la série : NR RSRP −81 à −83 dBm, SINR 16 à 18 dB ; LTE stable ; les quatre
porteuses présentes sous charge. **Facteur 20 sur le débit à radio constante.**

`INFÉRÉ` : la cause est côté réseau — ordonnancement ou congestion de la cellule — et non côté
matériel, routeur ou Wi-Fi. Écartés par relevé : SQM (`bandwidth 45Mbit`, `backlog 0b`),
conntrack (155/65536), Wi-Fi (1297 Mbit/s négociés en 6 GHz), routage (route par défaut unique).

`INFÉRÉ` : **une mesure de débit isolée sur ce lien n'a aucune valeur.** Comparer deux chemins
exige de les mesurer en alternance rapprochée. Deux comparaisons décalées de quelques minutes
ont produit le même jour deux conclusions contradictoires, toutes deux fausses.
