#!/bin/sh
# stabilizer — maintient en place les réglages qui ont fait gagner du débit le 2026-08-25,
# et journalise toute dérive. À exécuter SUR le routeur GL-E5800.
#
# Pourquoi : chacun de ces réglages peut être défait sans intervention humaine —
#   - l'UI GL.iNet réécrit kmwan et le Wi-Fi ;
#   - le hotplug 99-sqm-modem réattache SQM quand le l3_device du modem change ;
#   - les masques de bandes vivent dans la NV du modem, qu'un firmware ou une
#     reprovision opérateur peut réinitialiser.
# Chaque écart est corrigé ET consigné, pour qu'on sache après coup ce qui a bougé.
#
# Usage : stabilizer.sh [--interval 300] [--once] [--check] [--dir /opt/throughput-probe]
#   --check  n'écrit rien, se contente de signaler les écarts (pour inspection)
#
# SÛRETÉ : ne redémarre jamais toutes les radios. La seule action Wi-Fi possible est
# `wifi up wifi2`, et uniquement si l'AP 6 GHz est ABSENT — donc si personne ne peut y être.

INTERVAL=300
ONCE=0
CHECK=0
DIR=/opt/throughput-probe

# --- état désiré ---------------------------------------------------------------
WANT_NSA_BAND="38:41:75:76:77:78"   # bandes NR larges : n78 ici, n38/41/75/77 ailleurs
WANT_SA_BAND="38:41:75:76:77:78"    # idem pour la 5G SA
WANT_SQM_ENABLED="0"                # CAKE casse l'accélération IPA (voir SQM-VS-IPA)
WANT_KMWAN_WWAN_DISABLED="1"        # le répéteur hors du pool WAN : pas d'ECMP silencieux
WANT_6G_IFACE="wifi6g"              # AP 6 GHz dédié au poste
WANT_6G_SSID="GORKINOO6"
# -------------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --interval) INTERVAL=$2; shift 2 ;;
        --dir)      DIR=$2; shift 2 ;;
        --once)     ONCE=1; shift ;;
        --check)    CHECK=1; shift ;;
        *) echo "option inconnue : $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$DIR" || exit 1
LOG="$DIR/stabilizer.jsonl"

log() { # log <objet> <attendu> <trouve> <action>
    printf '{"ts":"%s","objet":"%s","attendu":"%s","trouve":"%s","action":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" >> "$LOG"
    echo "[$(date -u +%H:%M:%SZ)] $1 : attendu '$2', trouvé '$3' -> $4"
}

# Le motif est ancré sur le guillemet ouvrant : sans cela "nr5g_band" matcherait aussi
# les réponses "nsa_nr5g_band", et une réponse périmée de l'un contaminerait l'autre.
# Lecture AT par VOTE MAJORITAIRE : le pont ubus/AT tronque et rend parfois une valeur
# périmée (voir THROUGHPUT-PROBE.md). Prendre la plus longue retiendrait justement
# l'ancienne valeur quand elle est plus longue — d'où le vote.
at_get() { # at_get <parametre>
    param=$1
    i=1
    while [ $i -le 7 ]; do
        ubus call modem.CPU.AT get_result_AT \
            "{\"cmd\":\"AT+QNWPREFCFG=\\\"$param\\\"\",\"timeout\":8}" 2>/dev/null \
            | sed -n "s/.*\\\\\"$param\\\\\",\\([0-9:]*\\).*/\\1/p"
        i=$((i+1))
    done | sort | uniq -c | sort -rn | head -1 | awk '{print $2}'
}

at_set() { # at_set <parametre> <valeur>
    ubus call modem.CPU.AT get_result_AT \
        "{\"cmd\":\"AT+QNWPREFCFG=\\\"$1\\\",$2\",\"timeout\":10}" >/dev/null 2>&1
}

verifier() {
    # 1. masques de bandes NR
    for pair in "nsa_nr5g_band $WANT_NSA_BAND" "nr5g_band $WANT_SA_BAND"; do
        param=${pair%% *}; want=${pair##* }
        cur=$(at_get "$param")
        [ -z "$cur" ] && { log "$param" "$want" "(illisible)" "ignoré"; continue; }
        [ "$cur" = "$want" ] && continue
        if [ "$CHECK" = "1" ]; then log "$param" "$want" "$cur" "SIGNALÉ (--check)"
        else at_set "$param" "$want"; log "$param" "$want" "$cur" "réappliqué"; fi
    done

    # 2. SQM doit rester éteint, et aucun qdisc CAKE ne doit apparaître sur le WAN.
    cur=$(uci -q get sqm.modem.enabled)
    if [ "$cur" != "$WANT_SQM_ENABLED" ]; then
        if [ "$CHECK" = "1" ]; then log "sqm.modem.enabled" "$WANT_SQM_ENABLED" "$cur" "SIGNALÉ (--check)"
        else
            uci set sqm.modem.enabled="$WANT_SQM_ENABLED"; uci commit sqm
            /etc/init.d/sqm stop >/dev/null 2>&1
            log "sqm.modem.enabled" "$WANT_SQM_ENABLED" "$cur" "remis à 0 + sqm stop"
        fi
    fi
    l3=$(ubus call network.interface.modem_cpu status 2>/dev/null \
         | sed -n 's/.*"l3_device": "\([^"]*\)".*/\1/p' | head -1)
    if [ -n "$l3" ] && tc qdisc show dev "$l3" 2>/dev/null | head -1 | grep -q cake; then
        if [ "$CHECK" = "1" ]; then log "qdisc $l3" "pas de cake" "cake présent" "SIGNALÉ (--check)"
        else /etc/init.d/sqm stop >/dev/null 2>&1; log "qdisc $l3" "pas de cake" "cake présent" "sqm stop"; fi
    fi

    # 3. le répéteur doit rester hors du pool WAN (sinon ECMP silencieux 50/50)
    cur=$(uci -q get kmwan.wwan.disabled)
    if [ "$cur" != "$WANT_KMWAN_WWAN_DISABLED" ]; then
        if [ "$CHECK" = "1" ]; then log "kmwan.wwan.disabled" "$WANT_KMWAN_WWAN_DISABLED" "$cur" "SIGNALÉ (--check)"
        else
            uci set kmwan.wwan.disabled="$WANT_KMWAN_WWAN_DISABLED"; uci commit kmwan
            /etc/init.d/kmwan reload >/dev/null 2>&1
            log "kmwan.wwan.disabled" "$WANT_KMWAN_WWAN_DISABLED" "$cur" "réappliqué"
        fi
    fi

    # 4. l'AP 6 GHz doit exister. On ne recharge QUE la radio wifi2, jamais toutes :
    #    un `wifi reload` global coupe tous les clients.
    cur=$(uci -q get wireless.$WANT_6G_IFACE.disabled)
    ssid=$(uci -q get wireless.$WANT_6G_IFACE.ssid)
    besoin=0
    [ "$cur" = "1" ] && { log "wireless.$WANT_6G_IFACE.disabled" "0" "1" "à réactiver"; besoin=1; }
    [ "$ssid" != "$WANT_6G_SSID" ] && { log "wireless.$WANT_6G_IFACE.ssid" "$WANT_6G_SSID" "$ssid" "à corriger"; besoin=1; }
    if [ "$besoin" = "1" ] && [ "$CHECK" != "1" ]; then
        uci set wireless.$WANT_6G_IFACE.disabled=0
        uci set wireless.$WANT_6G_IFACE.ssid="$WANT_6G_SSID"
        uci commit wireless
        wifi up wifi2 >/dev/null 2>&1 || wifi reload wifi2 >/dev/null 2>&1
        log "radio wifi2" "AP $WANT_6G_SSID actif" "corrigé" "wifi up wifi2"
    elif ! iw dev wlan2 info >/dev/null 2>&1; then
        if [ "$CHECK" = "1" ]; then log "wlan2" "AP présent" "absent" "SIGNALÉ (--check)"
        else wifi up wifi2 >/dev/null 2>&1; log "wlan2" "AP présent" "absent" "wifi up wifi2"; fi
    fi
}

if [ "$ONCE" = "1" ] || [ "$CHECK" = "1" ]; then
    verifier
    exit 0
fi

echo "[stabilizer] intervalle ${INTERVAL}s, journal $LOG"
while :; do
    verifier
    sleep "$INTERVAL"
done
