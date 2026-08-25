#!/bin/bash
# Mesure du bufferbloat : latence a vide, puis sous charge de telechargement.
# Utilise le temps de connexion TCP (l'ICMP est filtre par l'operateur).
TARGET="${1:-https://www.google.com}"
N="${2:-12}"

lat() {
    for _ in $(seq 1 "$N"); do
        curl -s -o /dev/null -w "%{time_connect}\n" --max-time 8 "$TARGET" 2>/dev/null
    done | awk '
        {v[NR]=$1*1000; s+=$1*1000}
        END{
            if(NR==0){print "  aucune mesure"; exit}
            n=asort(v)
            printf "  n=%d  min=%.0fms  median=%.0fms  moy=%.0fms  max=%.0fms\n", n, v[1], v[int((n+1)/2)], s/n, v[n]
        }'
}

echo "--- latence A VIDE"
lat

echo "--- lancement de la charge (3 telechargements paralleles)"
for _ in 1 2 3; do
    curl -s -o /dev/null --max-time 45 "https://speed.cloudflare.com/__down?bytes=60000000" &
done
sleep 4

echo "--- latence SOUS CHARGE"
lat

wait 2>/dev/null
echo "--- fin"
