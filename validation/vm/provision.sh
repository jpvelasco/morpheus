#!/usr/bin/env bash
set -euo pipefail

export LIBVIRT_DEFAULT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest="${script_dir}/ubuntu-26.04-amd64.json"
cache_dir="${XDG_CACHE_HOME:-${HOME}/.cache}/morpheus-validation"
key_path="${MORPHEUS_VALIDATION_SSH_KEY:-${HOME}/.ssh/morpheus_validation_ed25519}"

for command in cloud-localds curl jq qemu-img sha256sum ssh-keygen virsh virt-install; do
  command -v "${command}" >/dev/null || {
    echo "Missing required host command: ${command}" >&2
    exit 1
  }
done

image_url=$(jq -er '.image.url' "${manifest}")
image_sha256=$(jq -er '.image.sha256' "${manifest}")
release_build=$(jq -er '.image.release_build' "${manifest}")
guest_name=$(jq -er '.guest.name' "${manifest}")
vcpus=$(jq -er '.guest.vcpus' "${manifest}")
memory_mib=$(jq -er '.guest.memory_mib' "${manifest}")
disk_gib=$(jq -er '.guest.disk_gib' "${manifest}")
network=$(jq -er '.guest.network' "${manifest}")
pool=$(jq -er '.guest.storage_pool' "${manifest}")

image_path="${cache_dir}/ubuntu-26.04-${release_build}-${image_sha256:0:12}.img"
rendered_user_data="${cache_dir}/${guest_name}-user-data.yaml"
seed_path="${cache_dir}/${guest_name}-seed.iso"
cloud_volume="ubuntu-26.04-${release_build}-${image_sha256:0:12}-cloudimg.qcow2"
guest_volume="${guest_name}.qcow2"
seed_volume="${guest_name}-seed.iso"

mkdir -p "${cache_dir}" "$(dirname -- "${key_path}")"

if [[ ! -f "${key_path}" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C 'morpheus-validation@ubuntu-1' -f "${key_path}"
fi
if [[ ! -f "${key_path}.pub" ]]; then
  ssh-keygen -y -f "${key_path}" >"${key_path}.pub"
fi
chmod 600 "${key_path}"
chmod 644 "${key_path}.pub"

public_key=$(<"${key_path}.pub")
if [[ "${public_key}" == *'|'* || "${public_key}" == *'&'* ]]; then
  echo "The SSH public key contains an unsupported template character." >&2
  exit 1
fi
sed "s|__SSH_PUBLIC_KEY__|${public_key}|" \
  "${script_dir}/cloud-init/user-data.yaml.in" >"${rendered_user_data}"
cloud-localds "${seed_path}" "${rendered_user_data}" \
  "${script_dir}/cloud-init/meta-data.yaml"

if [[ ! -f "${image_path}" ]] || \
  ! printf '%s  %s\n' "${image_sha256}" "${image_path}" | sha256sum --check --status; then
  curl --fail --location --continue-at - --output "${image_path}" "${image_url}"
fi
printf '%s  %s\n' "${image_sha256}" "${image_path}" | sha256sum --check --status
echo "Verified Ubuntu cloud image: ${image_sha256}"

virsh net-info "${network}" >/dev/null
virsh pool-info "${pool}" >/dev/null
if virsh dominfo "${guest_name}" >/dev/null 2>&1; then
  echo "Domain already exists: ${guest_name}" >&2
  exit 2
fi
if virsh vol-info --pool "${pool}" "${guest_volume}" >/dev/null 2>&1; then
  echo "Guest volume already exists: ${guest_volume}" >&2
  exit 2
fi
if virsh vol-info --pool "${pool}" "${seed_volume}" >/dev/null 2>&1; then
  echo "Seed volume already exists: ${seed_volume}" >&2
  exit 2
fi

if ! virsh vol-info --pool "${pool}" "${cloud_volume}" >/dev/null 2>&1; then
  image_virtual_bytes=$(qemu-img info --output=json "${image_path}" | jq -er '."virtual-size"')
  virsh vol-create-as "${pool}" "${cloud_volume}" "${image_virtual_bytes}" --format qcow2
  virsh vol-upload --pool "${pool}" --sparse "${cloud_volume}" "${image_path}"
fi

virsh vol-clone --pool "${pool}" "${cloud_volume}" "${guest_volume}"
disk_bytes=$((disk_gib * 1024 * 1024 * 1024))
virsh vol-resize --pool "${pool}" "${guest_volume}" "${disk_bytes}"

seed_bytes=$(stat --format='%s' "${seed_path}")
virsh vol-create-as "${pool}" "${seed_volume}" "${seed_bytes}" --format raw
virsh vol-upload --pool "${pool}" "${seed_volume}" "${seed_path}"

virt-install \
  --name "${guest_name}" \
  --memory "${memory_mib}" \
  --vcpus "${vcpus}" \
  --cpu host-passthrough \
  --osinfo generic \
  --import \
  --disk "vol=${pool}/${guest_volume},bus=virtio,cache=none,discard=unmap" \
  --disk "vol=${pool}/${seed_volume},bus=virtio,readonly=on" \
  --network "network=${network},model=virtio" \
  --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
  --boot uefi \
  --graphics none \
  --console pty,target.type=serial \
  --rng /dev/urandom \
  --noautoconsole \
  --wait 0

echo "Started ${guest_name}. Wait for cloud-init, verify it, then shut it down before cloning."
echo "SSH key fingerprint: $(ssh-keygen -lf "${key_path}.pub" | awk '{print $2}')"
