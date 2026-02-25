#!/usr/bin/env bash
# generate_agent_cert.sh — Generate a per-agent TLS client certificate for TripWire mTLS
#
# Usage:
#   ./generate_agent_cert.sh <hostname> [--dir <cert-dir>] [--ca-dir <ca-dir>] [--force]
#
# Positional arguments:
#   <hostname>     The hostname of the monitored agent (used as the certificate CN).
#                  Must be a non-empty string. Example: web-01
#
# Options:
#   --dir <path>     Directory for output cert and key (default: /etc/tripwire)
#   --ca-dir <path>  Directory containing ca.crt and ca.key (default: /etc/tripwire)
#   --force          Overwrite existing agent certificate and key
#
# Output files:
#   <dir>/agent.crt   Signed agent certificate (PEM, mode 0644)
#   <dir>/agent.key   Agent private key (PEM, mode 0600)
#
# The agent certificate is used for mTLS authentication against the TripWire
# dashboard gRPC server. The dashboard extracts agent identity from the cert CN
# and rejects connections with untrusted certificates.
#
# Prerequisites:
#   - openssl must be installed
#   - CA certificate and key must exist (generate with generate_ca.sh first)
#   - Write access to <dir> (use sudo if targeting /etc/tripwire)

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TRIPWIRE_DIR="/etc/tripwire"
CA_DIR="/etc/tripwire"
FORCE=false
HOSTNAME_ARG=""

AGENT_KEY_BITS=2048
AGENT_VALIDITY_DAYS=365   # 1 year; renew annually

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") <hostname> [--dir <cert-dir>] [--ca-dir <ca-dir>] [--force]

Positional arguments:
  <hostname>       Hostname of the monitored agent (used as certificate CN).
                   Example: web-01, db-server, 192.168.1.10

Options:
  --dir <path>     Output directory for agent.crt and agent.key (default: /etc/tripwire)
  --ca-dir <path>  Directory containing ca.crt and ca.key (default: /etc/tripwire)
  --force          Overwrite existing agent certificate and key

Examples:
  sudo $(basename "$0") web-01
  sudo $(basename "$0") db-server --dir /etc/tripwire --ca-dir /etc/tripwire/ca
  $(basename "$0") test-host --dir ./local-certs --ca-dir ./local-certs --force
EOF
    exit 1
}

# Parse positional argument first
if [[ $# -eq 0 ]]; then
    echo "ERROR: <hostname> argument is required." >&2
    usage
fi

# First argument must not start with '--'
if [[ "$1" == --* ]]; then
    echo "ERROR: <hostname> must be the first argument (got option '$1')." >&2
    usage
fi

HOSTNAME_ARG="$1"
shift

# Validate hostname is non-empty
if [[ -z "${HOSTNAME_ARG}" ]]; then
    echo "ERROR: <hostname> must not be empty." >&2
    usage
fi

# Parse remaining options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            [[ -n "${2:-}" ]] || { echo "ERROR: --dir requires a path argument." >&2; usage; }
            TRIPWIRE_DIR="$2"
            shift 2
            ;;
        --ca-dir)
            [[ -n "${2:-}" ]] || { echo "ERROR: --ca-dir requires a path argument." >&2; usage; }
            CA_DIR="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage
            ;;
    esac
done

AGENT_KEY="${TRIPWIRE_DIR}/agent.key"
AGENT_CERT="${TRIPWIRE_DIR}/agent.crt"
AGENT_CSR="${TRIPWIRE_DIR}/agent.csr"
CA_KEY="${CA_DIR}/ca.key"
CA_CERT="${CA_DIR}/ca.crt"
CERT_SUBJECT="/CN=${HOSTNAME_ARG}/O=TripWire/OU=Agent"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v openssl &>/dev/null; then
    echo "ERROR: openssl is not installed or not on PATH." >&2
    exit 1
fi

OPENSSL_VERSION=$(openssl version | awk '{print $2}')
echo "INFO: Using openssl ${OPENSSL_VERSION}"

# Check CA files exist
if [[ ! -f "${CA_CERT}" ]]; then
    echo "ERROR: CA certificate not found at ${CA_CERT}." >&2
    echo "       Run generate_ca.sh first to create the CA." >&2
    exit 1
fi

if [[ ! -f "${CA_KEY}" ]]; then
    echo "ERROR: CA private key not found at ${CA_KEY}." >&2
    echo "       Run generate_ca.sh first to create the CA." >&2
    exit 1
fi

# Check CA key is readable
if ! openssl rsa -in "${CA_KEY}" -check -noout 2>/dev/null; then
    echo "ERROR: CA private key at ${CA_KEY} is not a valid RSA key or is not readable." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------
if [[ -f "${AGENT_KEY}" && -f "${AGENT_CERT}" ]] && [[ "${FORCE}" == "false" ]]; then
    EXISTING_CN=$(openssl x509 -in "${AGENT_CERT}" -noout -subject 2>/dev/null | sed 's/.*CN\s*=\s*//' | sed 's/[,\/].*//')
    echo "INFO: Agent certificate already exists at ${TRIPWIRE_DIR} (CN=${EXISTING_CN})."
    echo "      Use --force to overwrite."
    echo "  Agent cert : ${AGENT_CERT}"
    echo "  Agent key  : ${AGENT_KEY}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Create output directory
# ---------------------------------------------------------------------------
if ! mkdir -p "${TRIPWIRE_DIR}" 2>/dev/null; then
    echo "ERROR: Cannot create directory ${TRIPWIRE_DIR}. Run with sudo or choose a writable path." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Generate agent private key
# ---------------------------------------------------------------------------
echo "INFO: Generating ${AGENT_KEY_BITS}-bit RSA agent private key for CN=${HOSTNAME_ARG} ..."
if ! openssl genrsa -out "${AGENT_KEY}" "${AGENT_KEY_BITS}" 2>/dev/null; then
    echo "ERROR: Failed to generate agent private key at ${AGENT_KEY}." >&2
    exit 1
fi

chmod 0600 "${AGENT_KEY}"
echo "INFO: Agent private key written to ${AGENT_KEY} (mode 0600)"

# ---------------------------------------------------------------------------
# Generate Certificate Signing Request (CSR)
# ---------------------------------------------------------------------------
echo "INFO: Generating CSR with CN=${HOSTNAME_ARG} ..."
if ! openssl req \
        -new \
        -key "${AGENT_KEY}" \
        -out "${AGENT_CSR}" \
        -subj "${CERT_SUBJECT}" 2>/dev/null; then
    echo "ERROR: Failed to generate CSR at ${AGENT_CSR}." >&2
    rm -f "${AGENT_KEY}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Sign the CSR with the CA
# ---------------------------------------------------------------------------
echo "INFO: Signing agent certificate with CA (validity: ${AGENT_VALIDITY_DAYS} days) ..."
if ! openssl x509 \
        -req \
        -in "${AGENT_CSR}" \
        -CA "${CA_CERT}" \
        -CAkey "${CA_KEY}" \
        -CAcreateserial \
        -out "${AGENT_CERT}" \
        -days "${AGENT_VALIDITY_DAYS}" \
        -extfile <(printf "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth") 2>/dev/null; then
    echo "ERROR: Failed to sign agent certificate at ${AGENT_CERT}." >&2
    rm -f "${AGENT_KEY}" "${AGENT_CSR}"
    exit 1
fi

chmod 0600 "${AGENT_CERT}"

# Remove temporary CSR
rm -f "${AGENT_CSR}"

# ---------------------------------------------------------------------------
# Verify the certificate chain
# ---------------------------------------------------------------------------
echo "INFO: Verifying agent certificate chain against CA ..."
if ! openssl verify -CAfile "${CA_CERT}" "${AGENT_CERT}" 2>/dev/null; then
    echo "ERROR: Certificate chain verification failed. The generated cert does not validate against the CA." >&2
    rm -f "${AGENT_KEY}" "${AGENT_CERT}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
FINGERPRINT=$(openssl x509 -in "${AGENT_CERT}" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)
EXPIRY=$(openssl x509 -in "${AGENT_CERT}" -noout -enddate 2>/dev/null | cut -d= -f2)
ISSUED_CN=$(openssl x509 -in "${AGENT_CERT}" -noout -subject 2>/dev/null | grep -oP 'CN\s*=\s*\K[^,/]+')

echo ""
echo "SUCCESS: Agent certificate generated and signed for CN=${ISSUED_CN}."
echo "  Agent cert  : ${AGENT_CERT} (mode 0600)"
echo "  Agent key   : ${AGENT_KEY} (mode 0600)"
echo "  Fingerprint : ${FINGERPRINT}"
echo "  Expires     : ${EXPIRY}"
echo ""
echo "Deploy these files to the monitored host:"
echo "  cp ${AGENT_CERT} /etc/tripwire/agent.crt"
echo "  cp ${AGENT_KEY}  /etc/tripwire/agent.key"
echo "  chown tripwire:tripwire /etc/tripwire/agent.{crt,key}"
echo "  chmod 0600 /etc/tripwire/agent.{crt,key}"
