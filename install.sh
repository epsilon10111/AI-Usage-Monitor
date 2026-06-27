#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/ai-usage-monitor"
CONFIG_FILE="${CONFIG_DIR}/config.json"
COOKIE_FILE="${CONFIG_DIR}/cursor-cookie"

mkdir -p "${CONFIG_DIR}"
if [[ ! -f "${CONFIG_FILE}" ]]; then
  install -m 600 "${ROOT_DIR}/examples/config.json" "${CONFIG_FILE}"
fi
if [[ ! -f "${COOKIE_FILE}" ]]; then
  install -m 600 /dev/null "${COOKIE_FILE}"
fi

if command -v kpackagetool6 >/dev/null 2>&1; then
  kpackagetool6 --type Plasma/Applet --upgrade "${ROOT_DIR}" >/dev/null 2>&1 || \
    kpackagetool6 --type Plasma/Applet --install "${ROOT_DIR}"
else
  printf 'kpackagetool6 was not found. Install KDE Plasma development tools first.\n' >&2
  exit 1
fi

printf 'Installed AI Usage Monitor.\n'
printf 'Config: %s\n' "${CONFIG_FILE}"
printf 'Cookie file: %s\n' "${COOKIE_FILE}"
printf 'Add it from Plasma: right click desktop or panel -> Add Widgets -> AI Usage Monitor.\n'
