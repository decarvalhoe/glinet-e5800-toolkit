#!/bin/sh
# Sonde de debit periodique, a executer SUR le routeur GL-E5800.
#
# Mesure le debit descendant et releve la radio DANS LA MEME FENETRE, pour pouvoir
# repondre a la seule question qui compte : quand le debit s'effondre, est-ce que la
# radio s'est degradee ? (Le 2026-08-25, la reponse etait non : facteur 20 sur le debit
# a SINR constant.)
#
# Deux pieges que ce script contourne, tous deux constates le 2026-08-25 :
#   - AT+QCAINFO ne liste les porteuses QUE sous connexion RRC : on le sonde PENDANT
#     le telechargement, jamais apres.
#   - le pont ubus/AT tronque par intermittence les reponses longues : chaque lecture
#     est repetee et on garde la plus longue.
#
# Sortie : une ligne JSON par echantillon, appendue a $DIR/throughput.jsonl
#
# Usage : throughput-probe.sh [--interval 600] [--dur 10] [--dir /opt/throughput-probe] [--once]

INTERVAL=600
DUR=10
DIR=/opt/throughput-probe
ONCE=0
URL="https://speed.cloudflare.com/__down?bytes=50000000"

while [ $# -gt 0 ]; do
    case "$1" in
        --interval) INTERVAL=$2; shift 2 ;;
        --dur)      DUR=$2; shift 2 ;;
        --dir)      DIR=$2; shift 2 ;;
        --url)      URL=$2; shift 2 ;;
        --once)     ONCE=1; shift ;;
        *) echo "option inconnue : $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$DIR" || exit 1
OUT="$DIR/throughput.jsonl"

# Une lecture AT, tolerante au pont ubus/AT : celui-ci tronque les reponses longues et
# en rate parfois completement (constate le 2026-08-25). On reessaie jusqu'a obtenir une
# reponse contenant le motif attendu ($3) ; a defaut on garde la plus longue obtenue.
#   at <commande> [essais] [motif_attendu]
at() {
    cmd=$1; tries=${2:-3}; want=${3:-}; best=""
    esc=$(printf '%s' "$cmd" | sed 's/"/\\"/g')
    i=1
    while [ "$i" -le "$tries" ]; do
        r=$(ubus call modem.CPU.AT get_result_AT "{\"cmd\":\"$esc\",\"timeout\":8}" 2>/dev/null \
            | sed -n 's/.*"data": "\(.*\)",*$/\1/p' | sed 's/\\r\\n/\n/g; s/\\"/"/g')
        [ ${#r} -gt ${#best} ] && best=$r
        if [ -n "$want" ]; then
            printf '%s' "$r" | grep -q "$want" && { printf '%s' "$r"; return 0; }
        elif [ -n "$r" ]; then
            printf '%s' "$r"; return 0
        fi
        i=$((i+1))
    done
    printf '%s' "$best"
}

jnum() { # $1 = valeur ; vide ou non numerique -> null
    case "$1" in
        ''|*[!0-9.+-]*) printf 'null' ;;
        *) printf '%s' "$1" ;;
    esac
}

sample() {
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Telechargement en fond, sonde radio pendant la charge.
    spd_file=$(mktemp 2>/dev/null || echo /tmp/tp-spd.$$)
    curl -s --max-time "$DUR" -o /dev/null -w '%{speed_download}' "$URL" > "$spd_file" 2>/dev/null &
    dl_pid=$!
    # QCAINFO d'abord : il ne liste les porteuses que sous connexion RRC, donc il doit
    # imperativement tomber DANS la fenetre de charge. QENG, lui, repond aussi au repos.
    sleep 2
    ca=$(at 'AT+QCAINFO' 3 'QCAINFO')
    eng=$(at 'AT+QENG="servingcell"' 6 '"LTE"')
    wait "$dl_pid" 2>/dev/null
    bps=$(cat "$spd_file" 2>/dev/null); rm -f "$spd_file"
    mbps=$(awk -v b="$bps" 'BEGIN{ if (b=="") print ""; else printf "%.3f", b*8/1000000 }')

    lte=$(printf '%s' "$eng" | grep '"LTE"' | head -1)
    nr=$(printf '%s'  "$eng" | grep 'NR5G'  | head -1)

    lte_band=$(printf '%s' "$lte" | awk -F, '{print $8}')
    lte_rsrp=$(printf '%s' "$lte" | awk -F, '{print $12}')
    lte_rsrq=$(printf '%s' "$lte" | awk -F, '{print $13}')
    lte_sinr=$(printf '%s' "$lte" | awk -F, '{print $15}')
    nr_rsrp=$(printf  '%s' "$nr"  | awk -F, '{print $5}')
    nr_sinr=$(printf  '%s' "$nr"  | awk -F, '{print $6}')
    nr_arfcn=$(printf '%s' "$nr"  | awk -F, '{print $8}')
    nr_band=$(printf  '%s' "$nr"  | awk -F, '{print $9}')
    nr_bw=$(printf    '%s' "$nr"  | awk -F, '{print $10}')

    carriers=$(printf '%s' "$ca" | grep -c 'QCAINFO')
    bands=$(printf '%s' "$ca" | sed -n 's/.*"\(LTE BAND [0-9]*\|NR5G BAND [0-9]*\)".*/\1/p' \
            | tr '\n' '+' | sed 's/+$//')
    if   [ -z "$eng" ];                                    then conn=unknown
    elif printf '%s' "$eng" | grep -q 'NOCONN';            then conn=idle
    else                                                        conn=connected
    fi
    load=$(awk '{print $1}' /proc/loadavg)

    printf '{"ts":"%s","mbps":%s,"carriers":%s,"bands":"%s","rrc":"%s",' \
        "$ts" "$(jnum "$mbps")" "$(jnum "$carriers")" "$bands" "$conn" >> "$OUT"
    printf '"lte":{"band":%s,"rsrp":%s,"rsrq":%s,"sinr":%s},' \
        "$(jnum "$lte_band")" "$(jnum "$lte_rsrp")" "$(jnum "$lte_rsrq")" "$(jnum "$lte_sinr")" >> "$OUT"
    printf '"nr":{"band":%s,"arfcn":%s,"bw":%s,"rsrp":%s,"sinr":%s},"load":%s}\n' \
        "$(jnum "$nr_band")" "$(jnum "$nr_arfcn")" "$(jnum "$nr_bw")" \
        "$(jnum "$nr_rsrp")" "$(jnum "$nr_sinr")" "$(jnum "$load")" >> "$OUT"

    echo "$ts  ${mbps:-?} Mbit/s  porteuses=$carriers ($bands)  NR ${nr_rsrp:-?}/${nr_sinr:-?}  LTE ${lte_rsrp:-?}/${lte_sinr:-?}"
}

if [ "$ONCE" = "1" ]; then
    sample
    exit 0
fi

echo "[throughput-probe] intervalle ${INTERVAL}s, fenetre ${DUR}s, sortie $OUT"
while :; do
    sample
    sleep "$INTERVAL"
done
