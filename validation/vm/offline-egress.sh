#!/usr/bin/env bash
set -euo pipefail

table=morpheus_validation_offline
probe_url="${MORPHEUS_OFFLINE_PROBE_URL:-https://registry-1.docker.io/v2/}"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 COMMAND [ARG ...]" >&2
  exit 64
fi

for command in curl nft sudo; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done
sudo -n true
if sudo nft list table inet "${table}" >/dev/null 2>&1; then
  echo "Refusing to replace existing nftables table: ${table}" >&2
  exit 2
fi

# A reachable preflight prevents an already-offline guest from producing a
# false-positive isolation result. HTTP status is irrelevant to this probe.
curl --silent --show-error --output /dev/null \
  --connect-timeout 3 --max-time 5 "${probe_url}"
echo "egress_before=reachable"

sudo nft add table inet "${table}"
cleanup() {
  sudo nft delete table inet "${table}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

sudo nft add chain inet "${table}" output \
  '{ type filter hook output priority -50; policy drop; }'
sudo nft add rule inet "${table}" output oifname lo accept
sudo nft add rule inet "${table}" output ct state established,related accept
sudo nft add chain inet "${table}" forward \
  '{ type filter hook forward priority -50; policy drop; }'
sudo nft add rule inet "${table}" forward ct state established,related accept

if curl --silent --show-error --output /dev/null \
  --connect-timeout 2 --max-time 3 "${probe_url}" >/dev/null 2>&1; then
  echo "Egress probe unexpectedly succeeded after isolation." >&2
  exit 1
fi
echo "egress_during=blocked"

"$@"
