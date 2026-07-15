#!/usr/bin/env bash
set -euo pipefail

export LIBVIRT_DEFAULT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 morpheus-validation-<scenario>" >&2
  exit 64
fi

scenario=$1
base="morpheus-validation-base"
if [[ ! "${scenario}" =~ ^morpheus-validation-[a-z0-9][a-z0-9-]{0,47}$ ]] || \
  [[ "${scenario}" == "${base}" ]]; then
  echo "Scenario name must use the morpheus-validation- prefix and must not name the base." >&2
  exit 64
fi

for command in virsh virt-clone virt-xml; do
  command -v "${command}" >/dev/null || {
    echo "Missing required host command: ${command}" >&2
    exit 1
  }
done

base_state=$(virsh domstate "${base}")
if ! [[ "${base_state}" == "shut off" ]]; then
  echo "The sealed base must be shut off before cloning; state is ${base_state}." >&2
  exit 1
fi
if ! virsh dumpxml "${base}" | sed -n "/<disk type='file' device='disk'>/,/<\/disk>/p" \
  | grep -q '<readonly/>'; then
  echo "The base disk is not sealed read-only in its domain definition." >&2
  exit 1
fi
if virsh dominfo "${scenario}" >/dev/null 2>&1; then
  echo "Scenario domain already exists: ${scenario}" >&2
  exit 2
fi

virt-clone \
  --connect "${LIBVIRT_DEFAULT_URI}" \
  --original "${base}" \
  --name "${scenario}" \
  --auto-clone \
  --force-copy vda
virt-xml \
  --connect "${LIBVIRT_DEFAULT_URI}" \
  "${scenario}" \
  --edit target=vda \
  --disk readonly=off

base_path=$(virsh domblklist "${base}" --details \
  | awk '$2 == "disk" && $3 == "vda" {print $4; exit}')
clone_path=$(virsh domblklist "${scenario}" --details \
  | awk '$2 == "disk" && $3 == "vda" {print $4; exit}')
if [[ -z "${base_path}" || -z "${clone_path}" ]] || \
  ! [[ "${base_path}" != "${clone_path}" ]]; then
  echo "Clone disk independence check failed." >&2
  exit 1
fi

virsh start "${scenario}"
echo "Started ${scenario} with independent writable disk ${clone_path}."
