#!/usr/bin/env bash
# install-agent-macos.sh — Install and enable the TripWire agent on macOS
#
# Usage:
#   sudo ./install-agent-macos.sh [OPTIONS] <tripwire-binary>
#
# Options:
#   -c, --config <path>   Path to an existing config.yaml to install
#                         (default: installs the example template and prompts
#                          you to edit it)
#   --no-enable           Install but do not load the LaunchDaemon
#   -h, --help            Show this help message
#
# The script:
#   1. Creates required directories with correct ownership and permissions.
#   2. Copies the agent binary to /usr/local/bin/tripwire.
#   3. Installs /etc/tripwire/config.yaml (template or supplied config).
#   4. Installs the launchd plist to /Library/LaunchDaemons/.
#   5. Bootstraps (loads) the LaunchDaemon (unless --no-enable).
#
# Requirements:
#   - macOS 13 Ventura or later (launchctl bootstrap domain).
#   - Root privileges (run with sudo).
#   - Full Disk Access granted to /usr/local/bin/tripwire in
#     System Settings → Privacy & Security → Full Disk Access (macOS 14+).
#   - Gatekeeper: the binary must be signed or you must explicitly allow it.

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
BINARY_DST="/usr/local/bin/tripwire"
CONFIG_DIR="/etc/tripwire"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
CERTS_DIR="${CONFIG_DIR}/certs"
DATA_DIR="/var/lib/tripwire"
LOG_DIR="/var/log/tripwire"
PLIST_LABEL="com.tripwire.agent"
PLIST_DST="/Library/LaunchDaemons/${PLIST_LABEL}.plist"

NO_ENABLE=false
SUPPLIED_CONFIG=""
BINARY_SRC=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
CYN='\033[0;36m'
RST='\033[0m'

info()  { echo -e "${GRN}[INFO]${RST}  $*"; }
warn()  { echo -e "${YLW}[WARN]${RST}  $*"; }
error() { echo -e "${RED}[ERROR]${RST} $*" >&2; }
step()  { echo -e "${CYN}[STEP]${RST}  $*"; }

# ── Argument parsing ─────────────────────────────────────────────────────────
usage() {
  sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed 's/^# \{0,2\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--config)  SUPPLIED_CONFIG="$2"; shift 2 ;;
    --no-enable)  NO_ENABLE=true;        shift   ;;
    -h|--help)    usage 0 ;;
    -*)           error "Unknown option: $1"; usage 1 ;;
    *)            BINARY_SRC="$1";       shift   ;;
  esac
done

# ── Pre-flight checks ────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  error "This script must be run as root (use sudo)."
  exit 1
fi

if [[ -z "${BINARY_SRC}" ]]; then
  error "No agent binary specified."
  usage 1
fi

if [[ ! -f "${BINARY_SRC}" ]]; then
  error "Binary not found: ${BINARY_SRC}"
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  error "This script is for macOS only. For Linux use install-agent-linux.sh."
  exit 1
fi

# Verify macOS version ≥ 13 (launchctl bootstrap domain target).
OS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
if [[ "${OS_MAJOR}" -lt 13 ]]; then
  warn "macOS ${OS_MAJOR} detected. This script targets macOS 13+."
  warn "The launchctl bootstrap command may not work on older releases."
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         TripWire Agent — macOS Installer             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1 — Directories ─────────────────────────────────────────────────────
step "1/6  Creating directories"

for dir in "${CONFIG_DIR}" "${CERTS_DIR}" "${DATA_DIR}" "${LOG_DIR}"; do
  mkdir -p "${dir}"
done

# Config: root-owned, world-readable for the daemon (which runs as root).
chown -R root:wheel "${CONFIG_DIR}"
chmod 750 "${CONFIG_DIR}"
chmod 750 "${CERTS_DIR}"

# Data and log: root-owned (daemon runs as root on macOS).
chown root:wheel "${DATA_DIR}"
chmod 750 "${DATA_DIR}"

chown root:wheel "${LOG_DIR}"
chmod 750 "${LOG_DIR}"

info "Directories created with correct permissions."

# ── Step 2 — Binary ──────────────────────────────────────────────────────────
step "2/6  Installing binary to ${BINARY_DST}"

# Ensure /usr/local/bin exists (absent on a fresh macOS install without Xcode).
mkdir -p /usr/local/bin

install -m 0755 -o root -g wheel "${BINARY_SRC}" "${BINARY_DST}"

# Remove the quarantine attribute that Gatekeeper sets on downloaded files.
xattr -d com.apple.quarantine "${BINARY_DST}" 2>/dev/null || true

info "Binary installed: ${BINARY_DST}"

# ── Step 3 — Configuration ───────────────────────────────────────────────────
step "3/6  Installing configuration"

if [[ -n "${SUPPLIED_CONFIG}" ]]; then
  if [[ ! -f "${SUPPLIED_CONFIG}" ]]; then
    error "Supplied config file not found: ${SUPPLIED_CONFIG}"
    exit 1
  fi
  install -m 0640 -o root -g wheel "${SUPPLIED_CONFIG}" "${CONFIG_FILE}"
  info "Configuration installed from ${SUPPLIED_CONFIG}"
elif [[ ! -f "${CONFIG_FILE}" ]]; then
  EXAMPLE="${REPO_ROOT}/agent/config.example.yaml"
  if [[ -f "${EXAMPLE}" ]]; then
    install -m 0640 -o root -g wheel "${EXAMPLE}" "${CONFIG_FILE}"
    warn "Example configuration installed at ${CONFIG_FILE}."
    warn "Edit it before starting the agent!"
  else
    warn "No config.yaml found at ${CONFIG_FILE}."
    warn "Create one before starting the agent."
    warn "See: agent/config.example.yaml in the source tree."
  fi
else
  info "Existing configuration preserved at ${CONFIG_FILE}."
fi

# ── Step 4 — PKI reminder ────────────────────────────────────────────────────
step "4/6  PKI reminder"

if [[ -z "$(ls -A "${CERTS_DIR}" 2>/dev/null)" ]]; then
  warn "No certificates found in ${CERTS_DIR}."
  warn "The agent cannot connect to the dashboard without mTLS certificates."
  warn "Generate them with:"
  warn "  deployments/certs/generate_ca.sh"
  warn "  deployments/certs/generate_agent_cert.sh <hostname>"
  warn "Then copy ca.crt, agent.crt, and agent.key to ${CERTS_DIR}/."
  warn "Ensure agent.key has mode 0600:"
  warn "  chmod 0600 ${CERTS_DIR}/agent.key"
fi

# ── Step 5 — launchd plist ───────────────────────────────────────────────────
step "5/6  Installing launchd plist"

PLIST_SRC="${REPO_ROOT}/deployments/launchd/${PLIST_LABEL}.plist"
if [[ ! -f "${PLIST_SRC}" ]]; then
  error "Plist not found at ${PLIST_SRC}"
  exit 1
fi

# Unload an existing daemon before replacing the plist.
if launchctl list "${PLIST_LABEL}" &>/dev/null; then
  warn "Stopping existing daemon before reinstall."
  launchctl bootout "system/${PLIST_LABEL}" 2>/dev/null || true
fi

install -m 0644 -o root -g wheel "${PLIST_SRC}" "${PLIST_DST}"
info "Plist installed: ${PLIST_DST}"

# ── Step 6 — Bootstrap the daemon ────────────────────────────────────────────
step "6/6  Loading the LaunchDaemon"

if [[ "${NO_ENABLE}" == true ]]; then
  warn "Skipping load (--no-enable specified)."
  warn "When ready, run:"
  warn "  sudo launchctl bootstrap system ${PLIST_DST}"
else
  launchctl bootstrap "system" "${PLIST_DST}"
  info "LaunchDaemon loaded."

  # Brief pause so launchd can stabilise.
  sleep 2

  if launchctl list "${PLIST_LABEL}" &>/dev/null; then
    info "Daemon is running."
    launchctl list "${PLIST_LABEL}"
  else
    warn "Daemon may not have started. Check logs:"
    warn "  tail -f ${LOG_DIR}/agent.err"
  fi
fi

# ── macOS Full Disk Access reminder ──────────────────────────────────────────
echo ""
warn "IMPORTANT — macOS Full Disk Access"
warn "On macOS 14+ (Sonoma) and later, the agent requires Full Disk Access to"
warn "monitor system paths (/etc, /private, /var, ...)."
warn ""
warn "Grant access in:"
warn "  System Settings → Privacy & Security → Full Disk Access"
warn "  Add: /usr/local/bin/tripwire"
warn ""
warn "Without this, file-watch rules targeting system paths will silently"
warn "fail.  After granting access, restart the daemon:"
warn "  sudo launchctl kickstart -k system/${PLIST_LABEL}"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   TripWire Agent installed successfully              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
info "Binary:        ${BINARY_DST}"
info "Config:        ${CONFIG_FILE}"
info "Certificates:  ${CERTS_DIR}/"
info "Queue:         ${DATA_DIR}/queue.db"
info "Audit log:     ${LOG_DIR}/audit.log"
info "LaunchDaemon:  ${PLIST_DST}"
echo ""
info "Useful commands:"
info "  sudo launchctl list    ${PLIST_LABEL}"
info "  sudo launchctl kickstart -k system/${PLIST_LABEL}   # restart"
info "  sudo launchctl bootout   system/${PLIST_LABEL}      # stop"
info "  tail -f ${LOG_DIR}/agent.log"
info "  sudo ${BINARY_DST} validate --config ${CONFIG_FILE}"
echo ""
