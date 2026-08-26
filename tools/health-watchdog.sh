#!/bin/sh
# Watchdog sante GL-E5800 - non intrusif, aucune action reseau (log only)
LOG=/root/health-watchdog.log
TS=$(date "+%Y-%m-%d %H:%M:%S")

MEM=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{if(t>0)printf "%d",100*(t-a)/t; else print 0}' /proc/meminfo)
LOAD=$(cut -d" " -f1 /proc/loadavg)
DISK=$(df -P / | awk 'NR==2{gsub(/%/,"",$5);print $5}')

if ping -c1 -W5 1.1.1.1 >/dev/null 2>&1; then NET=up; else NET=DOWN; fi

if [ "$MEM" -gt 80 ] || [ "$NET" = "DOWN" ] || [ "$DISK" -gt 90 ]; then
    echo "$TS ALERT mem=${MEM}% load=$LOAD disk=${DISK}% net=$NET" >> "$LOG"
else
    echo "$TS OK mem=${MEM}% load=$LOAD disk=${DISK}% net=$NET" >> "$LOG"
fi

# rotation simple
LINES=$(wc -l < "$LOG" 2>/dev/null)
if [ "${LINES:-0}" -gt 500 ]; then
    tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exit 0
