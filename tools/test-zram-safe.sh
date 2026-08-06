#!/bin/sh
# Vérifie temporairement zram sans pression mémoire et sans persistance.
set -eu

HOST="${GLINET_HOST:-192.168.8.1}"
USER="${GLINET_USER:-root}"
KEY="${GLINET_SSH_KEY:-$HOME/.ssh/glinet_ed25519}"
SIZE_MB="${GLINET_ZRAM_MB:-64}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-.evidence-private/$STAMP-zram-test.txt}"
mkdir -p "$(dirname "$OUT")"

case "$SIZE_MB" in
  ''|*[!0-9]*) echo 'Taille zram invalide' >&2; exit 2 ;;
esac
[ "$SIZE_MB" -ge 16 ] && [ "$SIZE_MB" -le 128 ] || {
  echo 'Taille zram autorisée: 16..128 MiB' >&2
  exit 2
}

check_connectivity() {
  ping -c 2 -W 2 "$HOST" >/dev/null
  curl -fsS --max-time 10 -o /dev/null https://github.com/
}
check_connectivity

timeout 120 ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 \
  "$USER@$HOST" sh -s -- "$SIZE_MB" > "$OUT" 2>&1 <<'ROUTER'
set -eu
SIZE_MB=$1
Z=/dev/zram0
S=/sys/block/zram0
selected_algorithm() {
  sed -n 's/.*\[\([^]]*\)\].*/\1/p' "$S/comp_algorithm"
}
[ -b "$Z" ] && [ -w "$S/disksize" ] && [ -w "$S/reset" ] || {
  echo 'REFUS: zram0 indisponible' >&2; exit 3
}
[ "$(cat "$S/disksize")" = 0 ] || {
  echo 'REFUS: zram0 déjà configuré' >&2; exit 4
}
[ ! -s /proc/swaps ] || ! grep -q "$Z" /proc/swaps || {
  echo 'REFUS: zram0 déjà utilisé' >&2; exit 5
}
ALGO_BEFORE=$(selected_algorithm)
[ -n "$ALGO_BEFORE" ] || {
  echo 'REFUS: algorithme zram initial indéterminé' >&2; exit 6
}
restore_initial_state() {
  failed=0
  if grep -q "$Z" /proc/swaps; then
    timeout 20 swapoff "$Z" 2>/dev/null || failed=1
  fi
  if ! grep -q "$Z" /proc/swaps; then
    current=$(cat "$S/disksize" 2>/dev/null || printf unknown)
    if [ "$current" != 0 ]; then
      timeout 5 sh -c 'echo 1 > "$1"' sh "$S/reset" 2>/dev/null || failed=1
    fi
  fi
  if ! grep -q "$Z" /proc/swaps && [ "$(cat "$S/disksize" 2>/dev/null || printf unknown)" = 0 ]; then
    current_algo=$(selected_algorithm)
    if [ "$current_algo" != "$ALGO_BEFORE" ]; then
      timeout 5 sh -c 'printf "%s\n" "$1" > "$2"' sh \
        "$ALGO_BEFORE" "$S/comp_algorithm" 2>/dev/null || failed=1
    fi
  fi
  if grep -q "$Z" /proc/swaps || \
     [ "$(cat "$S/disksize" 2>/dev/null || printf unknown)" != 0 ] || \
     [ "$(selected_algorithm)" != "$ALGO_BEFORE" ]; then
    failed=1
  fi
  [ "$failed" -eq 0 ] || {
    echo 'ERREUR CRITIQUE: état zram initial non restauré' >&2
    cat /proc/swaps >&2 || true
    printf 'disksize=' >&2
    cat "$S/disksize" >&2 2>/dev/null || true
    return 1
  }
}
cleanup_on_exit() {
  rc=$?
  trap - EXIT INT TERM HUP
  restore_initial_state || exit 90
  exit "$rc"
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT TERM HUP

echo '=== metadata ==='
date -u '+collected_at=%Y-%m-%dT%H:%M:%SZ'
printf 'size_mb=%s\n' "$SIZE_MB"
echo '=== precondition ==='
free -m
cat /proc/swaps
printf 'algorithm_before='; cat "$S/comp_algorithm"

timeout 5 sh -c 'echo lz4 > "$1"' sh "$S/comp_algorithm"
timeout 5 sh -c 'echo "$1" > "$2"' sh \
  "$((SIZE_MB * 1024 * 1024))" "$S/disksize"
timeout 10 mkswap "$Z"
timeout 10 swapon -p 100 "$Z"

echo '=== active ==='
free -m
cat /proc/swaps
printf 'algorithm_active='; cat "$S/comp_algorithm"
printf 'disksize='; cat "$S/disksize"
printf 'mm_stat='; cat "$S/mm_stat"
sleep 5

restore_initial_state || exit 90
trap - EXIT INT TERM HUP

echo '=== postcondition ==='
free -m
cat /proc/swaps
printf 'disksize='; cat "$S/disksize"
ROUTER

check_connectivity
printf 'Test zram temporaire terminé et nettoyé. Résultats: %s\n' "$OUT"
