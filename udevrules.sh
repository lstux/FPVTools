#!/bin/bash
BF_USER="$(id -un)"
BF_GROUPS="dialout"
BF_UDEVRULE="45-stdfu-permissions.rules"

udevrule_ubuntu() {
  local group="${1:-plugdev}" vid
  echo "# DFU (Internal bootloader for STM32 and AT32 MCUs)"
  for vid in "2e3c" "0483"; do
    echo "SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"${vid}\", ATTRS{idProduct}==\"df11\", MODE=\"0664\", GROUP=\"${group}\""
  done
}

udevrule_fedora() {
  echo "# DFU (Internal bootloader for STM32 and AT32 MCUs)"
  for vid in "2e3c" "0483"; do
    echo "SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"${vid}\", ATTRS{idProduct}==\"df11\", MODE=\"0664\", TAG+=\"uaccess\""
  done
}

udevrule() {
  local dist="${1}"
  shift
  case "${dist}" in
    ubuntu|fedora) true;;
    *) return;;
  esac
  eval "udevrule_${dist} \"\$@\"" | sudo tee "/etc/udev/rules.d/${BF_UDEVRULE}" >/dev/null && \
    printf "New udev rule '${BF_UDEVRULE}' created\n"
}

if [ -e /etc/debian_version ]; then
  BF_GROUPS="${BF_GORUPS} plugdev"
  udevrule ubuntu
elif [ -e /etc/fedora_version ]; then
  udevrule fedora
fi

for group in ${BF_GROUPS}; do
  echo " $(id -Gn "${BF_USER}") " | grep -q " ${group} " && continue
  echo "Adding ${BF_USER} to ${group} group"
  sudo usermod -aG "${group}" "${BF_USER}"
done
