#!/usr/bin/env bash
set -euo pipefail

export LIBVIRT_DEFAULT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest="${script_dir}/ubuntu-26.04-amd64.json"
cache_root="${XDG_CACHE_HOME:-${HOME}/.cache}/morpheus-validation/clones"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 morpheus-validation-<scenario>" >&2
  exit 64
fi

scenario=$1
base="morpheus-validation-base"
if [[ ! "${scenario}" =~ ^morpheus-validation-[a-z0-9][a-z0-9-]{0,42}$ ]] || \
  [[ "${scenario}" == "${base}" ]]; then
  echo "Scenario name must use the morpheus-validation- prefix and must not name the base." >&2
  exit 64
fi

for command in cloud-localds jq sed virsh virt-clone virt-xml; do
  command -v "${command}" >/dev/null || {
    echo "Missing required host command: ${command}" >&2
    exit 1
  }
done

pool=$(jq -er '.guest.storage_pool' "${manifest}")
seed_volume="${scenario}-seed.iso"
scenario_cache="${cache_root}/${scenario}"
metadata="${scenario_cache}/meta-data.yaml"
user_data="${script_dir}/cloud-init/clone-user-data.yaml"
seed_image="${scenario_cache}/seed.iso"

mkdir -p "${scenario_cache}"
sed "s|__SCENARIO_NAME__|${scenario}|g" \
  "${script_dir}/cloud-init/clone-meta-data.yaml.in" >"${metadata}"
cloud-localds "${seed_image}" "${user_data}" "${metadata}"

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
if virsh vol-info --pool "${pool}" "${seed_volume}" >/dev/null 2>&1; then
  echo "Scenario seed volume already exists: ${seed_volume}" >&2
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

seed_bytes=$(stat --format='%s' "${seed_image}")
virsh vol-create-as "${pool}" "${seed_volume}" "${seed_bytes}" --format raw
virsh vol-upload --pool "${pool}" "${seed_volume}" "${seed_image}"
seed_path=$(virsh vol-path --pool "${pool}" "${seed_volume}")
virsh attach-disk \
  "${scenario}" \
  "${seed_path}" \
  vdb \
  --config \
  --targetbus virtio \
  --subdriver raw \
  --mode readonly

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
echo "Started ${scenario} with independent writable disk ${clone_path} and seed ${seed_path}."
