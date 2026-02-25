# TripWire PKI Setup and Certificate Management

This directory contains scripts and documentation for setting up the x509 Public Key Infrastructure (PKI) that secures all communication between TripWire agents and the dashboard server using mutual TLS (mTLS).

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Quick Start](#quick-start)
4. [Step-by-Step Operator Workflow](#step-by-step-operator-workflow)
   - [Step 1: Generate the CA](#step-1-generate-the-ca)
   - [Step 2: Generate a Per-Agent Certificate](#step-2-generate-a-per-agent-certificate)
   - [Step 3: Verify the Certificate Chain](#step-3-verify-the-certificate-chain)
   - [Step 4: Deploy Certificates to the Agent Host](#step-4-deploy-certificates-to-the-agent-host)
   - [Step 5: Configure the Dashboard Server](#step-5-configure-the-dashboard-server)
5. [File Paths and Permissions](#file-paths-and-permissions)
6. [Script Reference](#script-reference)
7. [gRPC mTLS Validation Behaviour](#grpc-mtls-validation-behaviour)
8. [Certificate Renewal](#certificate-renewal)
9. [Troubleshooting](#troubleshooting)
10. [Security Notes](#security-notes)

---

## Prerequisites

| Tool    | Minimum Version | Notes                                               |
|---------|----------------|-----------------------------------------------------|
| openssl | 1.1.1 or 3.x   | Check with `openssl version`. LibreSSL is **not** recommended due to ECDSA padding differences. |
| bash    | 4.0+           | Scripts use associative arrays and `[[ ]]` conditionals. |

On Debian/Ubuntu:
```sh
sudo apt-get install openssl
```

On RHEL/Rocky/AlmaLinux:
```sh
sudo dnf install openssl
```

On macOS (Homebrew):
```sh
brew install openssl@3
export PATH="$(brew --prefix openssl@3)/bin:$PATH"
```

---

## Architecture Overview

TripWire uses **mutual TLS (mTLS)** for all gRPC traffic between agents and the dashboard. Both sides authenticate with x509 certificates:

```
Monitored Host                          Dashboard Server
┌────────────────────────────┐          ┌────────────────────────────┐
│ Agent                      │          │ gRPC Server                │
│                            │  mTLS    │                            │
│ /etc/tripwire/agent.crt ───┼──────────┼─── validates against ca.crt│
│ /etc/tripwire/agent.key    │          │                            │
│                            │◀─────────┼─── server.crt (dashboard)  │
│  validates against ca.crt  │          │    server.key              │
└────────────────────────────┘          └────────────────────────────┘
              Both sides share the same CA trust root
```

**Key design decisions:**

- A **single operator-managed CA** is the root of trust. The CA private key should be stored offline (air-gapped) after initial setup.
- **Per-agent certificates** have `CN=<hostname>`. The dashboard extracts the agent's hostname identity from the certificate's Common Name on every connection.
- Certificates are **never rotated automatically** by TripWire; renewal is an operator responsibility (see [Certificate Renewal](#certificate-renewal)).

---

## Quick Start

This sequence bootstraps a CA and issues a certificate for a single agent host named `web-01`.

```sh
# 1. Generate the CA (run once per deployment)
./generate_ca.sh

# 2. Issue a certificate for the agent on host "web-01"
./generate_agent_cert.sh web-01

# 3. Verify the chain
openssl verify -CAfile /etc/tripwire/ca.crt /etc/tripwire/web-01.crt

# 4. Copy the cert and key to the agent host
scp /etc/tripwire/web-01.crt  tripwire@web-01:/etc/tripwire/agent.crt
scp /etc/tripwire/web-01.key  tripwire@web-01:/etc/tripwire/agent.key

# 5. Confirm permissions on the agent host
ssh web-01 "ls -la /etc/tripwire/agent.{crt,key}"
# Expected: -rw------- (0600) owned by tripwire
```

---

## Step-by-Step Operator Workflow

### Step 1: Generate the CA

Run `generate_ca.sh` **once** for your entire deployment. This creates:

- `/etc/tripwire/ca.crt` — The CA certificate (distribute to all agents and the dashboard)
- `/etc/tripwire/ca.key` — The CA private key (**keep this secret**)

```sh
sudo ./generate_ca.sh
```

The script creates a 4096-bit RSA CA with a 10-year validity period. Re-running the script is **idempotent**: it will refuse to overwrite an existing `ca.crt`/`ca.key` pair and exit non-zero.

**After running:**
```
/etc/tripwire/
├── ca.crt    (0644, root:root) — share with dashboard and all agents
└── ca.key    (0600, root:root) — KEEP OFFLINE after initial setup
```

> **Security**: After generating all required agent certificates, move `ca.key` to offline, encrypted storage. The CA key is only needed to sign new agent certificates.

---

### Step 2: Generate a Per-Agent Certificate

Run `generate_agent_cert.sh <hostname>` for **each monitored host**. The `<hostname>` argument must exactly match the hostname that the agent will report — it becomes the certificate's `CN` field.

```sh
sudo ./generate_agent_cert.sh web-01
sudo ./generate_agent_cert.sh db-primary
sudo ./generate_agent_cert.sh bastion-host
```

Each invocation produces:

- `/etc/tripwire/<hostname>.crt` — The signed agent certificate
- `/etc/tripwire/<hostname>.key` — The agent's private key (0600)

Example for `web-01`:
```
/etc/tripwire/
├── ca.crt
├── ca.key
├── web-01.crt    (0644, root:root)
└── web-01.key    (0600, root:root)
```

**Script arguments:**

| Argument     | Required | Description                                                                |
|--------------|----------|----------------------------------------------------------------------------|
| `<hostname>` | Yes      | Hostname of the monitored server. Sets `CN=<hostname>` in the certificate. |

The script exits non-zero and prints a usage message if the hostname argument is omitted or if the CA key is not present at `/etc/tripwire/ca.key`.

**Key parameters used by the script:**

| Parameter          | Value                        | Notes                                    |
|--------------------|------------------------------|------------------------------------------|
| Key algorithm      | RSA 2048-bit                 | Suitable for agent leaf certs            |
| Validity           | 2 years (730 days)           | Plan renewal before expiry               |
| Subject            | `CN=<hostname>,O=TripWire`   | Dashboard reads CN for agent identity    |
| Extended Key Usage | `clientAuth`                 | Required for mTLS client authentication  |
| File permissions   | 0600 for `.key`, 0644 for `.crt` | Set by the script automatically      |

---

### Step 3: Verify the Certificate Chain

Before deploying, confirm the agent certificate validates against the CA:

```sh
openssl verify -CAfile /etc/tripwire/ca.crt /etc/tripwire/web-01.crt
# Expected output: /etc/tripwire/web-01.crt: OK
```

Inspect the certificate content:

```sh
openssl x509 -in /etc/tripwire/web-01.crt -noout -text | grep -E "CN|Not (Before|After)|Extended Key"
```

Example output:
```
        Subject: CN = web-01, O = TripWire
        Not Before: Feb 25 19:00:00 2026 GMT
        Not After : Feb 25 19:00:00 2028 GMT
                X509v3 Extended Key Usage:
                    TLS Web Client Authentication
```

---

### Step 4: Deploy Certificates to the Agent Host

Copy the agent's certificate and key to the monitored host. The agent reads them from fixed paths — do **not** rename them on the destination.

```sh
# Ensure the target directory exists with correct ownership
ssh web-01 "sudo mkdir -p /etc/tripwire && sudo chown tripwire:tripwire /etc/tripwire"

# Copy cert (public — SCP is fine)
scp /etc/tripwire/web-01.crt web-01:/tmp/agent.crt
ssh web-01 "sudo mv /tmp/agent.crt /etc/tripwire/agent.crt && sudo chown tripwire:tripwire /etc/tripwire/agent.crt && sudo chmod 0644 /etc/tripwire/agent.crt"

# Copy key (private — pipe through SSH to avoid writing to /tmp)
ssh web-01 "sudo tee /etc/tripwire/agent.key > /dev/null && sudo chown tripwire:tripwire /etc/tripwire/agent.key && sudo chmod 0600 /etc/tripwire/agent.key" < /etc/tripwire/web-01.key

# Copy CA cert (required for the agent to verify the dashboard's server cert)
scp /etc/tripwire/ca.crt web-01:/tmp/ca.crt
ssh web-01 "sudo mv /tmp/ca.crt /etc/tripwire/ca.crt && sudo chmod 0644 /etc/tripwire/ca.crt"
```

Verify on the agent host:

```sh
ssh web-01 "ls -la /etc/tripwire/"
```

Expected output:
```
total 20
drwxr-xr-x 2 tripwire tripwire 4096 Feb 25 19:00 .
drwxr-xr-x 88 root    root     4096 Feb 25 19:00 ..
-rw-r--r-- 1 tripwire tripwire 1765 Feb 25 19:00 ca.crt
-rw------- 1 tripwire tripwire 1743 Feb 25 19:00 agent.crt
-rw------- 1 tripwire tripwire 1679 Feb 25 19:00 agent.key
```

---

### Step 5: Configure the Dashboard Server

The dashboard needs the CA certificate to validate incoming agent connections, and its own server certificate/key for the TLS handshake. Place dashboard certificates at:

```
/etc/tripwire/dashboard/
├── ca.crt         (0644) — same CA cert as used for agents
├── server.crt     (0644) — dashboard server certificate (CN=dashboard or FQDN)
└── server.key     (0600) — dashboard server private key
```

Generate a server certificate (same script, different hostname convention):

```sh
sudo ./generate_agent_cert.sh dashboard.internal
```

Then set environment variables in the dashboard's deployment configuration:

```yaml
# docker-compose.yml excerpt
environment:
  - TLS_CA_CERT=/etc/tripwire/dashboard/ca.crt
  - TLS_SERVER_CERT=/etc/tripwire/dashboard/server.crt
  - TLS_SERVER_KEY=/etc/tripwire/dashboard/server.key
```

---

## File Paths and Permissions

### Agent Host

| Path                         | Owner              | Mode  | Content                                  |
|------------------------------|--------------------|-------|------------------------------------------|
| `/etc/tripwire/ca.crt`       | `tripwire:tripwire` | 0644  | CA certificate (public)                  |
| `/etc/tripwire/agent.crt`    | `tripwire:tripwire` | 0600  | Agent leaf certificate (public, but restricted) |
| `/etc/tripwire/agent.key`    | `tripwire:tripwire` | 0600  | Agent private key — **never share**      |
| `/etc/tripwire/config.yaml`  | `tripwire:tripwire` | 0600  | Agent YAML config (contains cert paths)  |

> **Why 0600 on agent.crt?** While a certificate is technically public, restricting it to 0600 follows the principle of least privilege: no other process on the host needs to read TripWire's cert, and restricting access reduces information disclosure in a compromised environment.

### Dashboard Host / Container

| Path                                  | Owner   | Mode  | Content                         |
|---------------------------------------|---------|-------|---------------------------------|
| `/etc/tripwire/dashboard/ca.crt`      | `root`  | 0644  | CA certificate                  |
| `/etc/tripwire/dashboard/server.crt`  | `root`  | 0644  | Dashboard server certificate    |
| `/etc/tripwire/dashboard/server.key`  | `root`  | 0600  | Dashboard server private key    |

In Docker deployments, mount the certs directory as a read-only volume:

```yaml
volumes:
  - /etc/tripwire/dashboard:/etc/tripwire/dashboard:ro
```

### CA Operator Machine

| Path                    | Owner  | Mode  | Content                                                  |
|-------------------------|--------|-------|----------------------------------------------------------|
| `/etc/tripwire/ca.crt`  | `root` | 0644  | CA certificate — distribute to all hosts                 |
| `/etc/tripwire/ca.key`  | `root` | 0400  | CA private key — **store offline after initial setup**   |

---

## Script Reference

### `generate_ca.sh`

Creates a self-signed CA certificate and private key.

**Usage:**
```sh
sudo ./generate_ca.sh
```

**Outputs:**

| File                    | Description                          |
|-------------------------|--------------------------------------|
| `/etc/tripwire/ca.crt`  | CA certificate (PEM, 4096-bit RSA)   |
| `/etc/tripwire/ca.key`  | CA private key (PEM, mode 0600)      |

**Behaviour:**
- Idempotent: exits non-zero without overwriting if `ca.crt` already exists.
- Creates `/etc/tripwire/` with mode 0755 if it does not exist.
- Prints an error and exits non-zero if run without root privileges.

**Exit codes:**

| Code | Meaning                                  |
|------|------------------------------------------|
| 0    | Success                                  |
| 1    | CA already exists, filesystem error, or insufficient privileges |

---

### `generate_agent_cert.sh`

Generates a per-agent RSA key pair, creates a CSR with `CN=<hostname>`, and signs it against the CA.

**Usage:**
```sh
sudo ./generate_agent_cert.sh <hostname>
```

**Arguments:**

| Argument     | Required | Description                                                          |
|--------------|----------|----------------------------------------------------------------------|
| `<hostname>` | Yes      | Fully-qualified or short hostname of the monitored server.           |

**Outputs:**

| File                              | Description                              |
|-----------------------------------|------------------------------------------|
| `/etc/tripwire/<hostname>.crt`    | Signed agent certificate (PEM)           |
| `/etc/tripwire/<hostname>.key`    | Agent private key (PEM, mode 0600)       |

**Behaviour:**
- Exits non-zero and prints usage if `<hostname>` argument is missing.
- Exits non-zero if `/etc/tripwire/ca.key` is not present (CA must be generated first).
- Sets file permissions: 0600 on `.key`, 0644 on `.crt`.
- CSR is created in a temporary directory and deleted after signing.

**Exit codes:**

| Code | Meaning                                                                  |
|------|--------------------------------------------------------------------------|
| 0    | Success                                                                  |
| 1    | Missing hostname argument, CA not found, or filesystem/openssl error     |

---

## gRPC mTLS Validation Behaviour

### TLS Handshake Sequence

Every gRPC connection from an agent to the dashboard performs the following mTLS handshake:

```
Agent                                    Dashboard gRPC Server
  │                                              │
  │──── ClientHello ────────────────────────────▶│
  │◀─── ServerHello + server.crt ───────────────│
  │     (agent validates server cert             │
  │      against ca.crt)                         │
  │──── agent.crt (client certificate) ─────────▶│
  │                                              │ validate agent.crt
  │                                              │   against ca.crt
  │                                              │ extract CN from Subject
  │◀─── Finished (mTLS established) ────────────│
  │                                              │
  │──── gRPC StreamAlerts / RegisterAgent ──────▶│
```

### Agent Identity Extraction

After the TLS handshake, the dashboard's gRPC server extracts the agent's identity from the client certificate using Go's `tls` and `crypto/x509` packages:

```go
// Pseudo-code — actual implementation in internal/server/grpc/server.go
func agentIdentityFromContext(ctx context.Context) (string, error) {
    p, ok := peer.FromContext(ctx)
    if !ok {
        return "", errors.New("no peer in context")
    }
    tlsInfo, ok := p.AuthInfo.(credentials.TLSInfo)
    if !ok {
        return "", errors.New("not a TLS connection")
    }
    certs := tlsInfo.State.PeerCertificates
    if len(certs) == 0 {
        return "", errors.New("no client certificate presented")
    }
    // CN must equal the agent's registered hostname
    return certs[0].Subject.CommonName, nil
}
```

### Chain Verification

The dashboard configures its gRPC server with `tls.RequireAndVerifyClientCert`:

```go
// internal/server/grpc/server.go
tlsCfg := &tls.Config{
    ClientAuth: tls.RequireAndVerifyClientCert,
    ClientCAs:  caCertPool,    // loaded from /etc/tripwire/dashboard/ca.crt
    Certificates: []tls.Certificate{serverCert},
}
```

**What this means for operators:**

| Scenario                                          | Outcome                                                |
|---------------------------------------------------|--------------------------------------------------------|
| Agent presents valid cert signed by the CA        | Connection accepted; CN used as agent hostname          |
| Agent presents cert signed by a different CA      | Handshake rejected at TLS layer (certificate verify failed) |
| Agent presents expired cert                        | Handshake rejected at TLS layer                        |
| Agent presents no cert                            | Handshake rejected at TLS layer                        |
| Cert CN does not match registered hostname        | Connection accepted at TLS layer; application layer may reject the `RegisterAgent` RPC if hostname mismatch is detected |

### gRPC Error on Failed mTLS

When the handshake fails, the agent receives a gRPC status error and falls back to local alert queuing:

```
rpc error: code = Unavailable desc = connection closed before server preface received
```

This error always indicates a TLS/mTLS misconfiguration. Check:
1. CA cert is the same on both agent and dashboard.
2. Agent cert has not expired.
3. Agent cert is signed by the operator CA (run `openssl verify`).
4. Clock skew between agent and dashboard is under 5 minutes (TLS is sensitive to time).

---

## Certificate Renewal

Agent certificates are valid for **2 years**. Plan renewal before the `Not After` date.

### Check expiry dates

```sh
# On the operator machine — check all agent certs
for cert in /etc/tripwire/*.crt; do
  echo -n "$cert: "
  openssl x509 -in "$cert" -noout -enddate
done
```

### Renew a certificate

```sh
# Generate a new cert for web-01 (overwrites the old one)
sudo ./generate_agent_cert.sh web-01

# Deploy to the host (same as initial deployment)
ssh web-01 "sudo tee /etc/tripwire/agent.key > /dev/null && sudo chmod 0600 /etc/tripwire/agent.key" < /etc/tripwire/web-01.key
scp /etc/tripwire/web-01.crt web-01:/tmp/agent.crt
ssh web-01 "sudo mv /tmp/agent.crt /etc/tripwire/agent.crt"

# Restart the agent to load the new cert
ssh web-01 "sudo systemctl restart tripwire-agent"
```

The agent reconnects immediately after restart using the renewed certificate. No dashboard restart is required.

---

## Troubleshooting

### `openssl verify` fails

```
error 20 at 0 depth lookup: unable to get local issuer certificate
```

The CA cert used for verification does not match the CA that signed the agent cert. Ensure you are using the correct `ca.crt`.

### Agent cannot connect — `certificate has expired or is not yet valid`

The agent cert has expired or the system clock on the agent/dashboard is skewed. Either renew the cert or synchronise NTP.

### Agent cannot connect — `certificate signed by unknown authority`

The agent's `ca.crt` does not match the dashboard's `ca.crt`. Redistribute the correct `ca.crt` from the operator machine.

### `generate_agent_cert.sh: CA not found`

The script cannot find `/etc/tripwire/ca.key`. Run `generate_ca.sh` first, or copy the CA key from offline storage.

### Permission denied on `/etc/tripwire/agent.key`

The agent process is not running as the `tripwire` user, or the file ownership is wrong. Verify:

```sh
ls -la /etc/tripwire/agent.key
# Must be: -rw------- 1 tripwire tripwire ...

ps aux | grep tripwire
# Must show the agent running as 'tripwire'
```

---

## Security Notes

1. **Protect the CA private key.** Anyone with `ca.key` can issue certificates that the dashboard will accept. Store it in an encrypted offline volume (e.g., VeraCrypt, LUKS, or an HSM) after initial setup.

2. **Do not share agent keys.** Each host must have its own key pair. Never copy `agent.key` from one host to another.

3. **Revocation is manual.** TripWire does not implement CRL or OCSP. To revoke a compromised agent certificate, remove or replace the CA entirely and re-issue all agent certificates. For large deployments, consider using an intermediate CA per environment so revocation scope is limited.

4. **Restrict CA operations to the operator machine.** The scripts should only run on a dedicated, hardened machine that is not a monitored host.

5. **Use separate CAs per environment.** Issue separate CA certs for production, staging, and development so a compromised staging key cannot authenticate to production agents.
