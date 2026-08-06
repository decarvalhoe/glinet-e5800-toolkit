#!/bin/sh
# Sonde AT sur le modem Quectel RG650V du GL-E5800.
at() {
    printf '\n--- %s\n' "$1"
    esc=$(printf '%s' "$1" | sed 's/"/\\"/g')
    ubus call modem.CPU.AT get_result_AT "{\"cmd\":\"$esc\",\"timeout\":10}" \
        | sed -n 's/.*"data": "\(.*\)",*$/\1/p' \
        | sed 's/\\r\\n/\n/g; s/\\"/"/g' | grep -v '^$'
}

at 'AT+QENG="servingcell"'
at 'AT+QCAINFO'
at 'AT+QNWPREFCFG="mode_pref"'
at 'AT+QNWPREFCFG="nr5g_disable_mode"'
at 'AT+QNWPREFCFG="lte_band"'
at 'AT+QNWPREFCFG="nr5g_band"'
at 'AT+QTEMP'
at 'AT+CSQ'
