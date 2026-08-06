#!/bin/sh
# Verrouille l'ancrage LTE sur la bande 20, avec restauration automatique.
# Le garde-fou restaure les bandes d'origine a T+240s SAUF si /tmp/band-lock-ok existe.
# C'est moi qui cree ce fichier, et seulement apres avoir verifie que le lien est revenu.

ORIG='1:3:5:7:8:20:28:32:38:40:41:42:43'

at() {
    esc=$(printf '%s' "$1" | sed 's/"/\\"/g')
    ubus call modem.CPU.AT get_result_AT "{\"cmd\":\"$esc\",\"timeout\":15}" \
        | sed -n 's/.*"data": "\(.*\)",*$/\1/p' \
        | sed 's/\\r\\n/\n/g; s/\\"/"/g' | grep -v '^$'
}

# --- garde-fou, arme AVANT toute modification -------------------------------
rm -f /tmp/band-lock-ok
cat > /tmp/band-watchdog.sh <<EOF
#!/bin/sh
sleep 240
[ -f /tmp/band-lock-ok ] && exit 0
ubus call modem.CPU.AT get_result_AT '{"cmd":"AT+QNWPREFCFG=\\"lte_band\\",$ORIG","timeout":15}' >/dev/null 2>&1
sleep 5
ifup modem_cpu >/dev/null 2>&1
logger -t band-watchdog "RESTAURATION AUTO: bandes LTE d origine remises ($ORIG)"
EOF
chmod +x /tmp/band-watchdog.sh
start-stop-daemon -S -b -x /tmp/band-watchdog.sh 2>/dev/null || nohup /tmp/band-watchdog.sh >/dev/null 2>&1 &
echo "[garde-fou] arme : restauration auto a T+240s sauf validation explicite"

# --- application ------------------------------------------------------------
echo "[lock] bandes avant : $(at 'AT+QNWPREFCFG="lte_band"' | grep lte_band)"
at 'AT+QNWPREFCFG="lte_band",20' | grep -E 'OK|ERROR'
echo "[lock] bandes apres : $(at 'AT+QNWPREFCFG="lte_band"' | grep lte_band)"

# --- attente de re-attachement ---------------------------------------------
echo "[attente] re-attachement..."
i=0
while [ $i -lt 30 ]; do
    sleep 5
    i=$((i + 1))
    ip=$(at 'AT+CGPADDR' | grep -o '"[0-9.]*"' | head -1 | tr -d '"')
    case "$ip" in
        ""|"0.0.0.0") continue ;;
        *) echo "[attente] IP obtenue apres $((i * 5))s : $ip"; break ;;
    esac
done

echo "--- servingcell ---"
at 'AT+QENG="servingcell"'
echo "--- CA ---"
at 'AT+QCAINFO'
