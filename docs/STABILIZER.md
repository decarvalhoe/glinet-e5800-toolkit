# Stabilisateur : empêcher la configuration de dériver

Outil : [`tools/stabilizer.sh`](../tools/stabilizer.sh) ·
service : [`etc/init.d/stabilizer`](../etc/init.d/stabilizer)

Les réglages qui ont fait passer le débit de 3,9 à ~20-49 Mbit/s le 2026-08-25 peuvent être
défaits **sans intervention humaine** :

- l'UI GL.iNet réécrit `kmwan` et le Wi-Fi ;
- le hotplug `99-sqm-modem` réattache SQM quand le `l3_device` du modem change ;
- les masques de bandes vivent dans la NV du modem, qu'une reprovision opérateur ou un
  firmware peut réinitialiser — **et c'est arrivé le jour même** : le masque `nsa_nr5g_band`
  posé à 16h05 lisait de nouveau la liste d'usine à 16h43.

Le stabilisateur vérifie l'état désiré toutes les 5 minutes, corrige les écarts et **journalise
chacun d'eux** dans `/opt/throughput-probe/stabilizer.jsonl` :

```json
{"ts":"2026-08-25T14:44:06Z","objet":"nsa_nr5g_band",
 "attendu":"38:41:75:76:77:78","trouve":"1:3:5:7:8:20:26:28:38:40:41:75:76:77:78",
 "action":"réappliqué"}
```

Le journal est le vrai produit : il dit **ce qui bouge tout seul** sur cet appareil.

## Ce qu'il maintient

| objet | valeur | pourquoi |
|---|---|---|
| `nsa_nr5g_band`, `nr5g_band` | `38:41:75:76:77:78` | bandes NR larges — voir [`NR-BAND-20260825.md`](NR-BAND-20260825.md) |
| `sqm.modem.enabled` | `0` | CAKE casse l'IPA — voir [`SQM-VS-IPA-20260825.md`](SQM-VS-IPA-20260825.md) |
| qdisc du `l3_device` WAN | aucun `cake` | rattrape une réattache par hotplug |
| `kmwan.wwan.disabled` | `1` | le répéteur hors du pool WAN, pas d'ECMP silencieux |
| `wireless.wifi6g` | actif, SSID `GORKINOO6` | radio dédiée au poste, séparée du répéteur |

## Sûreté

Il ne fait **jamais** de `wifi reload` global — cela couperait tous les clients. La seule
action Wi-Fi possible est `wifi up wifi2`, et uniquement si l'AP 6 GHz est **absent**, donc
quand personne ne peut y être connecté.

Inspecter sans rien écrire :

```sh
/opt/stabilizer/stabilizer.sh --check     # signale les écarts, ne corrige rien
```

## Un défaut de lecture qu'il a fallu corriger

La lecture AT se fait par **vote majoritaire** sur 7 essais, car le pont `ubus`/AT tronque et
rend parfois une valeur périmée (voir [`THROUGHPUT-PROBE.md`](THROUGHPUT-PROBE.md)).

Piège supplémentaire : le motif de recherche doit être **ancré sur le guillemet ouvrant**.
Sans cela `nr5g_band` matche aussi les réponses `nsa_nr5g_band`, et une réponse périmée de l'un
se fait passer pour la valeur de l'autre — ce qui a produit une fausse alerte de dérive avant
correction.
