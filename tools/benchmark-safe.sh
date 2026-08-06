#!/bin/sh
# Benchmarks non disruptifs: connectivité faible volume + I/O temporaire USB.
# Ne modifie aucune configuration et ne redémarre aucun service/interface.
set -eu

HOST="${GLINET_HOST:-192.168.8.1}"
USER="${GLINET_USER:-root}"
KEY="${GLINET_SSH_KEY:-$HOME/.ssh/glinet_ed25519}"
MOUNT="${GLINET_USB_MOUNT:-/tmp/mountd/disk1_part1}"
SIZE_MB="${GLINET_BENCH_MB:-64}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-.evidence-private/$STAMP-safe-benchmarks.txt}"
mkdir -p "$(dirname "$OUT")"

case "$SIZE_MB" in
  ''|*[!0-9]*) echo "REFUS: GLINET_BENCH_MB doit etre un entier de 1 a 64" >&2; exit 2 ;;
esac
[ "$SIZE_MB" -ge 1 ] && [ "$SIZE_MB" -le 64 ] || {
  echo "REFUS: GLINET_BENCH_MB doit rester entre 1 et 64 MiB" >&2
  exit 2
}
validate_mount_path() {
  path=$1
  case "$path" in
    /tmp/mountd/*) rel=${path#/tmp/mountd/} ;;
    *) return 1 ;;
  esac
  case "$rel" in
    ''|.|..|*/*|*[!A-Za-z0-9_.-]*) return 1 ;;
  esac
  return 0
}
validate_mount_path "$MOUNT" || {
  echo "REFUS: mountpoint non canonique ou hors /tmp/mountd: $MOUNT" >&2
  exit 2
}

check_connectivity() {
  ping -c 2 -W 2 "$HOST" >/dev/null
  curl -fsS --max-time 10 -o /dev/null https://github.com/
}

check_connectivity

timeout 120 ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 \
  "$USER@$HOST" sh -s -- "$MOUNT" "$SIZE_MB" > "$OUT" 2>&1 <<'ROUTER'
set -eu
MOUNT=$1
SIZE_MB=$2
validate_mount_path() {
  path=$1
  case "$path" in
    /tmp/mountd/*) rel=${path#/tmp/mountd/} ;;
    *) return 1 ;;
  esac
  case "$rel" in
    ''|.|..|*/*|*[!A-Za-z0-9_.-]*) return 1 ;;
  esac
  return 0
}
validate_mount_path "$MOUNT" || {
  echo "REFUS: mountpoint non canonique ou hors /tmp/mountd: $MOUNT" >&2
  exit 2
}
CANON=$(cd "$MOUNT" 2>/dev/null && pwd -P) || {
  echo "REFUS: mountpoint inaccessible" >&2
  exit 2
}
case "$CANON" in
  /tmp/mountd/*) MOUNT=$CANON ;;
  *) echo "REFUS: mountpoint canonique hors /tmp/mountd: $CANON" >&2; exit 2 ;;
esac
mountpoint -q "$MOUNT" 2>/dev/null || grep -qs " $MOUNT " /proc/mounts || {
  echo "REFUS: support USB non monte" >&2
  exit 3
}
FREE_KB=$(df -k "$MOUNT" | awk 'NR==2 {print $4}')
NEED_KB=$((SIZE_MB * 1024 * 2))
[ "$FREE_KB" -gt "$NEED_KB" ] || {
  echo "REFUS: espace libre insuffisant" >&2
  exit 4
}
T="$MOUNT/.counter-expertise-io-test.$$"
cleanup() {
  rc=$?
  trap - EXIT INT TERM HUP
  failed=0
  timeout 10 rm -f "$T" 2>/dev/null || failed=1
  [ ! -e "$T" ] || failed=1
  if [ "$failed" -ne 0 ]; then
    echo "ERREUR CRITIQUE: fichier temporaire non nettoye: $T" >&2
    exit 90
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

echo '=== benchmark metadata ==='
date -u '+collected_at=%Y-%m-%dT%H:%M:%SZ'
printf 'mount=%s size_mb=%s filesystem=' "$MOUNT" "$SIZE_MB"
awk -v m="$MOUNT" '$2==m {print $3}' /proc/mounts

echo '=== precondition ==='
df -h "$MOUNT"
free -m

echo '=== direct sequential write ==='
timeout 30 dd if=/dev/zero of="$T" bs=1M count="$SIZE_MB" oflag=direct conv=fsync 2>&1

echo '=== direct sequential read, pass 1 ==='
timeout 20 dd if="$T" of=/dev/null bs=1M iflag=direct 2>&1

echo '=== direct sequential read, pass 2 ==='
timeout 20 dd if="$T" of=/dev/null bs=1M iflag=direct 2>&1

echo '=== allocation and errors ==='
timeout 5 ls -l "$T"
(timeout 10 dmesg || true) | grep -Ei 'usb|xhci|r8152|sd[a-z]' | tail -n 80 || true

timeout 10 rm -f "$T"
[ ! -e "$T" ] || {
  echo "ERREUR CRITIQUE: fichier temporaire toujours present: $T" >&2
  exit 90
}
trap - EXIT INT TERM HUP
echo '=== postcondition ==='
echo 'temporary_file_absent=yes'
df -h "$MOUNT"
ROUTER

check_connectivity
printf 'Benchmarks termines, connexion preservee. Resultats: %s\n' "$OUT"
