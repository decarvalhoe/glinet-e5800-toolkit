#!/bin/sh
# Collecte indépendante et NON DISRUPTIVE pour GL-E5800.
# Lecture seule uniquement : aucun uci set/commit, ifup/ifdown, service restart,
# opkg install, écriture disque routeur, changement radio/modem ou pare-feu.
set -eu

HOST="${GLINET_HOST:-192.168.8.1}"
USER="${GLINET_USER:-root}"
KEY="${GLINET_SSH_KEY:-$HOME/.ssh/glinet_ed25519}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-.evidence-private/$STAMP}"
mkdir -p "$OUT"

run_ssh() {
  ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 "$USER@$HOST" "$@"
}

{
  date -u '+collected_at=%Y-%m-%dT%H:%M:%SZ'
  printf 'collector=tools/collect-safe-baseline.sh\n'
  printf 'host=%s\n' "$HOST"
  printf 'safety=read-only; sole-uplink protected\n'
} > "$OUT/metadata.txt"

{
  echo '=== route to public IP ==='
  ip route get 1.1.1.1
  echo '=== default routes ==='
  ip route show default
  echo '=== router ping ==='
  ping -c 3 -W 2 "$HOST"
  echo '=== low-volume HTTPS probe ==='
  curl -fsS --max-time 10 -o /dev/null \
    -w 'http=%{http_code} connect=%{time_connect} total=%{time_total}\n' \
    https://github.com/
} > "$OUT/local-connectivity.txt" 2>&1

run_ssh 'sh -s' > "$OUT/router-system.txt" 2>&1 <<'ROUTER'
echo '=== board ==='
ubus call system board
echo '=== GL version ==='
cat /etc/glversion 2>/dev/null || true
echo '=== uptime ==='
uptime
echo '=== memory ==='
free -m
echo '=== memory pressure ==='
cat /proc/pressure/memory 2>/dev/null || true
vmstat 1 5 2>/dev/null || true
logread 2>/dev/null | grep -Ei 'out of memory|oom-killer|killed process' | tail -n 50 || true
echo '=== storage ==='
df -h / /overlay /tmp /tmp/mountd/disk1_part1 2>/dev/null || true
echo '=== mounts ==='
mount | grep -E '/overlay|/dev/sd|/tmp/mountd' || true
echo '=== block info ==='
block info 2>/dev/null || true
echo '=== storage warnings ==='
dmesg 2>/dev/null | grep -Ei 'FAT|not properly unmounted|corrupt|I/O error|reset.*USB|sdc' | tail -n 100 || true
logread 2>/dev/null | grep -Ei 'FAT|not properly unmounted|corrupt|I/O error|reset.*USB|sdc' | tail -n 100 || true
echo '=== partitions ==='
cat /proc/partitions
echo '=== block devices via sysfs ==='
for d in /sys/block/sd*; do
  [ -e "$d" ] || continue
  n=${d##*/}
  printf '%s vendor=' "$n"; cat "$d/device/vendor" 2>/dev/null || true
  printf '%s model=' "$n"; cat "$d/device/model" 2>/dev/null || true
  printf '%s size_sectors=' "$n"; cat "$d/size" 2>/dev/null || true
  printf '%s removable=' "$n"; cat "$d/removable" 2>/dev/null || true
  printf '%s logical_block=' "$n"; cat "$d/queue/logical_block_size" 2>/dev/null || true
  printf '%s scheduler=' "$n"; cat "$d/queue/scheduler" 2>/dev/null || true
done
ROUTER

run_ssh 'sh -s' > "$OUT/router-hardware.txt" 2>&1 <<'ROUTER'
echo '=== CPU ==='
cat /proc/cpuinfo
echo '=== cpufreq ==='
for c in /sys/devices/system/cpu/cpu[0-9]*; do
  [ -d "$c/cpufreq" ] || continue
  printf '%s governor=' "${c##*/}"; cat "$c/cpufreq/scaling_governor" 2>/dev/null || true
  printf '%s current_khz=' "${c##*/}"; cat "$c/cpufreq/scaling_cur_freq" 2>/dev/null || true
  printf '%s available_governors=' "${c##*/}"; cat "$c/cpufreq/scaling_available_governors" 2>/dev/null || true
done
for f in /sys/devices/system/cpu/cpufreq/policy0/scaling_driver \
         /sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq \
         /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq \
         /sys/devices/system/cpu/cpufreq/policy0/affected_cpus; do
  [ -r "$f" ] && printf '%s=' "$f" && cat "$f"
done
echo '=== irq balancing ==='
ps w | grep -E 'msm-irqbalance|irqbalance' | grep -v grep || true
echo '=== USB ==='
lsusb 2>/dev/null || true
lsusb -t 2>/dev/null || true
echo '=== USB Ethernet driver ==='
ethtool -i eth1 2>/dev/null || true
ethtool eth1 2>/dev/null || true
echo '=== USB Ethernet offloads/statistics ==='
ethtool -k eth1 2>/dev/null || true
ethtool -S eth1 2>/dev/null || true
bridge link show dev eth1 2>/dev/null || true
for f in /sys/class/net/eth1/device/power/control /sys/class/net/eth1/device/power/runtime_status; do
  [ -r "$f" ] && printf '%s=' "$f" && cat "$f"
done
echo '=== kernel capability subset ==='
zcat /proc/config.gz 2>/dev/null | grep -E 'CONFIG_(POSIX_MQUEUE|CGROUPS|CGROUP_PIDS|CGROUP_DEVICE|MEMCG|BLK_CGROUP|SWAP|ZSWAP|ZRAM|ZSMALLOC|OVERLAY_FS|EXT4_FS|F2FS_FS|USB_STORAGE|NET_SCH_CAKE|IFB|BPF|BPF_SYSCALL|NFT_TPROXY|NETFILTER_XT_TARGET_TPROXY|WIREGUARD|RPS|RFS_ACCEL|KVM)(=| is not set)' || true
echo '=== cgroups ==='
mount | grep cgroup || true
ROUTER

run_ssh 'sh -s' > "$OUT/router-network.txt" 2>&1 <<'ROUTER'
echo '=== links ==='
ip -details -statistics link show
echo '=== addresses ==='
ip address show
echo '=== routes ==='
ip route show table all
echo '=== modem interface status ==='
ubus call network.interface.modem_cpu status
echo '=== qdisc ==='
tc -s qdisc show
echo '=== fastpath signals ==='
nft list flowtable inet fw4 ft 2>/dev/null || true
conntrack -L 2>/dev/null | grep -m 20 -E '\[OFFLOAD\]|\[HW_OFFLOAD\]' || true
echo '=== Qualcomm IPA bounded counters ==='
for f in /sys/kernel/debug/ipa/stats \
         /sys/kernel/debug/ipa/hw_stats/tethering \
         /sys/kernel/debug/ipa/ipa_clk_scaling_bw_threshold; do
  [ -r "$f" ] || continue
  echo "--- $f ---"
  head -n 200 "$f" 2>/dev/null || true
done
ps w | grep -E 'ipa_lnx_agent|ipacmdiag|QCMAP_ConnectionManager|ethagent' | grep -v grep || true
echo '=== interrupts ==='
cat /proc/interrupts
echo '=== softnet ==='
cat /proc/net/softnet_stat
echo '=== RPS/XPS masks ==='
for d in rmnet_data1 eth1 wlan0 wlan1; do
  [ -d "/sys/class/net/$d/queues" ] || continue
  for f in /sys/class/net/$d/queues/*/rps_cpus \
           /sys/class/net/$d/queues/*/rps_flow_cnt \
           /sys/class/net/$d/queues/*/xps_cpus; do
    if [ -r "$f" ]; then
      value=$(cat "$f" 2>/dev/null || true)
      printf '%s=%s\n' "$f" "$value"
    fi
  done
done
echo '=== conntrack count/max ==='
cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || true
cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || true
echo '=== firewall zone policies only ==='
uci -q show firewall | grep -E '=zone$|\.name=|\.network=|\.input=|\.output=|\.forward=' || true
ROUTER

run_ssh 'sh -s' > "$OUT/router-software.txt" 2>&1 <<'ROUTER'
echo '=== all installed packages ==='
opkg list-installed
echo '=== relevant available packages ==='
for p in block-mount swap-utils zram-swap kmod-zram kmod-fs-ext4 kmod-fs-f2fs kmod-usb-storage e2fsprogs f2fs-tools losetup resize2fs dockerd podman sqm-scripts kmod-sched-cake irqbalance; do
  opkg list "$p" 2>/dev/null | head -n 1
done
echo '=== services, status only ==='
for s in sqm tailscale zerotier tor adguardhome samba4; do
  [ -x "/etc/init.d/$s" ] || continue
  printf '%s: ' "$s"
  /etc/init.d/$s status 2>&1 || true
done
ROUTER

(
  cd "$OUT"
  sha256sum ./*.txt > SHA256SUMS
)
printf 'Baseline privée collectée dans %s\n' "$OUT"
