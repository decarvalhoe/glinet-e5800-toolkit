#!/bin/sh
# Moniteur radio temps reel GL-E5800 (LTE + 5G NR)
# Usage: ssh glinet 'sh -s' < monitor-radio.sh

# Format des reponses Quectel RG650V, verifie sur firmware 4.8.5 :
#   +QENG: "LTE","FDD",MCC,MNC,cellID,PCI,EARFCN,band,ULbw,DLbw,TAC,RSRP,RSRQ,RSSI,SINR,CQI,txpwr
#          $1        $2   $3  $4  $5     $6  $7     $8   $9   $10  $11 $12  $13  $14  $15  $16
#   +QENG: "NR5G-NSA",MCC,MNC,PCI,RSRP,SINR,RSRQ,ARFCN,band,DLbw,scs
#          $1         $2  $3  $4  $5   $6   $7   $8    $9   $10  $11
# Recoupe avec AT+QCAINFO (PCC/SCC) : memes RSRP, RSRQ et PCI.

at_cmd() {
    esc=$(printf "%s" "$1" | sed 's/"/\\"/g')
    ubus call modem.CPU.AT get_result_AT "{\"cmd\":\"$esc\",\"timeout\":8}" 2>/dev/null \
        | sed -n 's/.*"data": "\(.*\)",*$/\1/p' \
        | sed 's/\\r\\n/\n/g; s/\\"/"/g' | grep -v '^$'
}

printf "\033[2J\033[H"
echo "================================================================="
echo "   GL-E5800 (Mudi 7) — Moniteur Radio Temps Reel (LTE & 5G NR)   "
echo "   Appuyez sur Ctrl+C pour quitter                               "
echo "================================================================="

while true; do
    raw=$(at_cmd 'AT+QENG="servingcell"')
    cainfo=$(at_cmd 'AT+QCAINFO')
    ts=$(date +"%T")

    printf "\033[5;1H"
    echo "--- Releve a $ts ---"
    echo ""

    if echo "$raw" | grep -q 'NR5G-NSA'; then
        lte_line=$(echo "$raw" | grep '^+\?QENG: "LTE"')
        nr_line=$(echo "$raw" | grep '^+\?QENG: "NR5G-NSA"')

        # Extraction LTE
        lte_band=$(echo "$lte_line" | awk -F, '{print $8}')
        lte_earfcn=$(echo "$lte_line" | awk -F, '{print $7}')
        lte_pci=$(echo "$lte_line" | awk -F, '{print $6}')
        lte_rsrp=$(echo "$lte_line" | awk -F, '{print $12}')
        lte_rsrq=$(echo "$lte_line" | awk -F, '{print $13}')
        lte_sinr=$(echo "$lte_line" | awk -F, '{print $15}')

        # Extraction 5G NR
        nr_pci=$(echo "$nr_line" | awk -F, '{print $4}')
        nr_rsrp=$(echo "$nr_line" | awk -F, '{print $5}')
        nr_sinr=$(echo "$nr_line" | awk -F, '{print $6}')
        nr_rsrq=$(echo "$nr_line" | awk -F, '{print $7}')
        nr_arfcn=$(echo "$nr_line" | awk -F, '{print $8}')
        nr_band=$(echo "$nr_line" | awk -F, '{print $9}')

        echo "[Mode Actif] : 5G NSA (Non-Standalone EN-DC)"
        echo "  - Ancrage 4G LTE  : Bande $lte_band (EARFCN $lte_earfcn, PCI $lte_pci) | RSRP: ${lte_rsrp} dBm | RSRQ: ${lte_rsrq} dB | SINR: ${lte_sinr} dB"
        echo "  - Porteuse 5G NR  : Bande n$nr_band (ARFCN $nr_arfcn, PCI $nr_pci) | RSRP: ${nr_rsrp} dBm | RSRQ: ${nr_rsrq} dB | SINR: ${nr_sinr} dB"

        if [ "$nr_sinr" -lt 0 ] 2>/dev/null; then
            printf "  - Qualite 5G NR   : \033[1;31mCRITIQUE (SINR negatif = bruit excessif, risque eleve de deco)\033[0m\n"
        elif [ "$nr_sinr" -lt 5 ] 2>/dev/null; then
            printf "  - Qualite 5G NR   : \033[1;33mFAIBLE (SINR < 5 dB, stabilite precaire)\033[0m\n"
        elif [ "$nr_sinr" -lt 12 ] 2>/dev/null; then
            printf "  - Qualite 5G NR   : \033[1;32mBONNE (SINR 5-12 dB, stable)\033[0m\n"
        else
            printf "  - Qualite 5G NR   : \033[1;34mEXCELLENTE (SINR > 12 dB, debit max)\033[0m\n"
        fi
    elif echo "$raw" | grep -q 'LTE'; then
        lte_line=$(echo "$raw" | grep '^+\?QENG: "LTE"')
        lte_band=$(echo "$lte_line" | awk -F, '{print $8}')
        lte_earfcn=$(echo "$lte_line" | awk -F, '{print $7}')
        lte_pci=$(echo "$lte_line" | awk -F, '{print $6}')
        lte_rsrp=$(echo "$lte_line" | awk -F, '{print $12}')
        lte_rsrq=$(echo "$lte_line" | awk -F, '{print $13}')
        lte_sinr=$(echo "$lte_line" | awk -F, '{print $15}')
        echo "[Mode Actif] : LTE Uniquement (4G+ Multi-porteuses)"
        echo "  - Cellule LTE : Bande $lte_band (EARFCN $lte_earfcn, PCI $lte_pci) | RSRP: ${lte_rsrp} dBm | RSRQ: ${lte_rsrq} dB | SINR: ${lte_sinr} dB"
    else
        echo "[Mode Actif] : Recherche de reseau (SEARCH)..."
    fi

    echo ""
    echo "--- Agregation de porteuses (CA) ---"
    if [ -n "$cainfo" ] && [ "$cainfo" != "OK" ]; then
        echo "$cainfo" | grep -E 'PCC|SCC' | sed 's/+QCAINFO: //g'
    else
        echo "Aucune agregation active."
    fi

    sleep 2
done
