#!/usr/bin/env bash
# generate_ca.sh — Create a self-signed Certificate Authority for TripWire mTLS
#
# Usage:
#   ./generate_ca.sh [--dir <output-dir>] [--force]
#
# Options:
#   --dir <path>   Directory for CA output files (default: /etc/tripwire)
#   --force        Overwrite existing CA certificate and key
#
# Output files:
#   <dir>/ca.crt   Self-signed CA certificate (PEM)
#   <dir>/ca.key   CA private key (PEM, mode 0600)
#
# The generated CA is used to sign per-agent client certificates via
# generate_agent_cert.sh. The dashboard validates the full mTLS chain on
# every gRPC connection.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TRIPWIRE_DIR="/etc/tripwire"
FORCE=false

CA_KEY_BITS=4096
CA_VALIDITY_DAYS=3650   # 10 years
CA_SUBJECT="/CN=TripWire-CA/O=TripWire/OU=PKI"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") [--dir <output-dir>] [--force]

Options:
  --dir <path>   Directory for CA output files (default: /etc/tripwire)
  --force        Overwrite existing CA certificate and key

Example:
  sudo $(basename "$0") --dir /etc/tripwire
  sudo $(basename "$0") --dir ./local-certs --force
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            [[ -n "${2:-}" ]] || { echo "ERROR: --dir requires a path argument." >&2; usage; }
            TRIPWIRE_DIR="$2"
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

CA_KEY="${TRIPWIRE_DIR}/ca.key"
CA_CERT="${TRIPWIRE_DIR}/ca.crt"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v openssl &>/dev/null; then
    echo "ERROR: openssl is not installed or not on PATH." >&2
    exit 1
fi

# Check openssl version is at least 1.1.1
OPENSSL_VERSION=$(openssl version | awk '{print $2}')
echo "INFO: Using openssl ${OPENSSL_VERSION}"

# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------
if [[ -f "${CA_KEY}" && -f "${CA_CERT}" ]] && [[ "${FORCE}" == "false" ]]; then
    echo "INFO: CA already exists at ${TRIPWIRE_DIR}. Use --force to overwrite."
    echo "  CA cert : ${CA_CERT}"
    echo "  CA key  : ${CA_KEY}"
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
# Generate CA private key
# ---------------------------------------------------------------------------
echo "INFO: Generating ${CA_KEY_BITS}-bit RSA CA private key ..."
if ! openssl genrsa -out "${CA_KEY}" "${CA_KEY_BITS}" 2>/dev/null; then
    echo "ERROR: Failed to generate CA private key at ${CA_KEY}." >&2
    exit 1
fi

chmod 0600 "${CA_KEY}"
echo "INFO: CA private key written to ${CA_KEY} (mode 0600)"

# ---------------------------------------------------------------------------
# Generate self-signed CA certificate
# ---------------------------------------------------------------------------
echo "INFO: Generating self-signed CA certificate (validity: ${CA_VALIDITY_DAYS} days) ..."
if ! openssl req \
        -new \
        -x509 \
        -key "${CA_KEY}" \
        -out "${CA_CERT}" \
        -days "${CA_VALIDITY_DAYS}" \
        -subj "${CA_SUBJECT}" \
        -extensions v3_ca \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash" 2>/dev/null; then
    echo "ERROR: Failed to generate CA certificate at ${CA_CERT}." >&2
    # Remove partial key if cert generation fails
    rm -f "${CA_KEY}"
    exit 1
fi

chmod 0644 "${CA_CERT}"
echo "INFO: CA certificate written to ${CA_CERT}"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
FINGERPRINT=$(openssl x509 -in "${CA_CERT}" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)
EXPIRY=$(openssl x509 -in "${CA_CERT}" -noout -enddate 2>/dev/null | cut -d= -f2)

echo ""
echo "SUCCESS: TripWire CA generated successfully."
echo "  CA cert       : ${CA_CERT}"
echo "  CA key        : ${CA_KEY} (mode 0600)"
echo "  Fingerprint   : ${FINGERPRINT}"
echo "  Expires       : ${EXPIRY}"
echo ""
echo "Next step: generate per-agent certificates with:"
echo "  ./generate_agent_cert.sh <hostname>"
