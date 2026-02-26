#!/usr/bin/env bash
# install-agent-linux.sh — Install and enable the TripWire agent on Linux
#
# Usage:
#   sudo ./install-agent-linux.sh [OPTIONS] <tripwire-binary>
#
# Options:
#   -c, --config <path>   Path to an existing config.yaml to install
#                         (default: installs the example template and prompts
#                          you to edit it)
#   -u, --user  <name>    System user to run the agent as (default: tripwire)
#   -g, --group <name>    System group                    (default: tripwire)
#   --no-enable           Install but do not enable/start the service
#   -h, --help            Show this help message
#
# The script:
#   1. Creates a dedicated system user and group.
#   2. Creates required directories with correct ownership and permissions.
#   3. Copies the agent binary to /usr/local/bin/tripwire.
#   4. Installs /etc/tripwire/config.yaml (template or supplied config).
#   5. Installs the systemd service unit.
#   6. Enables and starts the service (unless --no-enable).
#
# Requirements:
#   - systemd-based Linux distribution (Debian/Ubuntu/RHEL/Fedora/Arch …)
#   - Kernel ≥ 5.8 recommended for eBPF process monitoring
#   - Root privileges (run with sudo)

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
AGENT_USER="tripwire"
AGENT_GROUP="tripwire"
BINARY_DST="/usr/local/bin/tripwire"
CONFIG_DIR="/etc/tripwire"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
CERTS_DIR="${CONFIG_DIR}/certs"
DATA_DIR="/var/lib/tripwire"
LOG_DIR="/var/log/tripwire"
UNIT_FILE="/etc/systemd/system/tripwire-agent.service"
ENV_FILE="${CONFIG_DIR}/agent.env"

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
    -c|--config)    SUPPLIED_CONFIG="$2"; shift 2 ;;
    -u|--user)      AGENT_USER="$2";      shift 2 ;;
    -g|--group)     AGENT_GROUP="$2";     shift 2 ;;
    --no-enable)    NO_ENABLE=true;        shift   ;;
    -h|--help)      usage 0 ;;
    -*)             error "Unknown option: $1"; usage 1 ;;
    *)              BINARY_SRC="$1";       shift   ;;
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

if ! command -v systemctl &>/dev/null; then
  error "systemctl not found — is this a systemd-based system?"
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         TripWire Agent — Linux Installer             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1 — System user and group ──────────────────────────────────────────
step "1/7  Creating system user '${AGENT_USER}' and group '${AGENT_GROUP}'"

if ! getent group "${AGENT_GROUP}" &>/dev/null; then
  groupadd --system "${AGENT_GROUP}"
  info "Group '${AGENT_GROUP}' created."
else
  info "Group '${AGENT_GROUP}' already exists."
fi

if ! id -u "${AGENT_USER}" &>/dev/null; then
  useradd \
    --system \
    --gid "${AGENT_GROUP}" \
    --no-create-home \
    --home-dir "${DATA_DIR}" \
    --shell /sbin/nologin \
    --comment "TripWire Security Agent" \
    "${AGENT_USER}"
  info "User '${AGENT_USER}' created."
else
  info "User '${AGENT_USER}' already exists."
fi

# ── Step 2 — Directories ─────────────────────────────────────────────────────
step "2/7  Creating directories"

for dir in "${CONFIG_DIR}" "${CERTS_DIR}" "${DATA_DIR}" "${LOG_DIR}"; do
  mkdir -p "${dir}"
done

# Config: root-owned, tripwire-readable
chown -R root:"${AGENT_GROUP}" "${CONFIG_DIR}"
chmod 750 "${CONFIG_DIR}"
chmod 750 "${CERTS_DIR}"

# Data and log: tripwire-owned
chown "${AGENT_USER}:${AGENT_GROUP}" "${DATA_DIR}"
chmod 750 "${DATA_DIR}"

chown "${AGENT_USER}:${AGENT_GROUP}" "${LOG_DIR}"
chmod 750 "${LOG_DIR}"

info "Directories created with correct permissions."

# ── Step 3 — Binary ──────────────────────────────────────────────────────────
step "3/7  Installing binary to ${BINARY_DST}"

install -m 0755 -o root -g root "${BINARY_SRC}" "${BINARY_DST}"
info "Binary installed: ${BINARY_DST}"

# ── Step 4 — Configuration ───────────────────────────────────────────────────
step "4/7  Installing configuration"

if [[ -n "${SUPPLIED_CONFIG}" ]]; then
  if [[ ! -f "${SUPPLIED_CONFIG}" ]]; then
    error "Supplied config file not found: ${SUPPLIED_CONFIG}"
    exit 1
  fi
  install -m 0640 -o root -g "${AGENT_GROUP}" "${SUPPLIED_CONFIG}" "${CONFIG_FILE}"
  info "Configuration installed from ${SUPPLIED_CONFIG}"
elif [[ ! -f "${CONFIG_FILE}" ]]; then
  EXAMPLE="${REPO_ROOT}/agent/config.example.yaml"
  if [[ -f "${EXAMPLE}" ]]; then
    install -m 0640 -o root -g "${AGENT_GROUP}" "${EXAMPLE}" "${CONFIG_FILE}"
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

# Environment file (non-overwriting).
if [[ ! -f "${ENV_FILE}" ]]; then
  ENV_EXAMPLE="${REPO_ROOT}/deployments/systemd/tripwire-agent.env"
  if [[ -f "${ENV_EXAMPLE}" ]]; then
    install -m 0640 -o root -g "${AGENT_GROUP}" "${ENV_EXAMPLE}" "${ENV_FILE}"
    info "Environment file template installed at ${ENV_FILE}."
  fi
fi

# ── Step 5 — PKI reminder ────────────────────────────────────────────────────
step "5/7  PKI reminder"

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

# ── Step 6 — systemd unit file ───────────────────────────────────────────────
step "6/7  Installing systemd unit file"

UNIT_SRC="${REPO_ROOT}/deployments/systemd/tripwire-agent.service"
if [[ ! -f "${UNIT_SRC}" ]]; then
  error "Unit file not found at ${UNIT_SRC}"
  exit 1
fi

install -m 0644 -o root -g root "${UNIT_SRC}" "${UNIT_FILE}"
systemctl daemon-reload
info "Unit file installed: ${UNIT_FILE}"

# ── Step 7 — Enable and start ────────────────────────────────────────────────
step "7/7  Enabling and starting the service"

if [[ "${NO_ENABLE}" == true ]]; then
  warn "Skipping enable/start (--no-enable specified)."
  warn "When ready, run:"
  warn "  sudo systemctl enable --now tripwire-agent"
else
  systemctl enable tripwire-agent
  systemctl start  tripwire-agent

  # Brief pause so systemd can report a stable status.
  sleep 2

  echo ""
  systemctl status tripwire-agent --no-pager || true
fi

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
info "Service:       tripwire-agent (systemd)"
echo ""
info "Useful commands:"
info "  sudo systemctl status  tripwire-agent"
info "  sudo systemctl restart tripwire-agent"
info "  sudo journalctl -u tripwire-agent -f"
info "  sudo ${BINARY_DST} validate --config ${CONFIG_FILE}"
echo ""
