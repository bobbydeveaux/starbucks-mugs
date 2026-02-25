# FileGuard Helm Chart

Production-grade Helm chart for deploying **FileGuard** — a security-focused file processing gateway providing antivirus scanning, PII detection, and automated redaction — on Kubernetes.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- A running PostgreSQL instance (managed RDS / Cloud SQL recommended for production)
- A running Redis instance (managed ElastiCache / Memorystore recommended for production)

## Installing the Chart

```bash
helm install fileguard ./helm \
  --namespace fileguard \
  --create-namespace \
  --set secrets.databaseUrl="postgresql+asyncpg://user:password@postgres-host:5432/fileguard" \
  --set secrets.redisUrl="redis://redis-host:6379/0" \
  --set secrets.secretKey="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

## Required Value Overrides

The following values **must** be provided before deploying. The chart will render successfully with empty strings (for `helm template` / `helm lint`), but the application will fail to start without them.

| Value | Description | Example |
|---|---|---|
| `secrets.databaseUrl` | PostgreSQL async connection string | `postgresql+asyncpg://user:pass@host:5432/fileguard` |
| `secrets.redisUrl` | Redis connection string | `redis://redis-host:6379/0` |
| `secrets.secretKey` | 32-byte hex key for HMAC-SHA256 audit log signing | `$(python -c 'import secrets; print(secrets.token_hex(32))')` |

> **Security note:** Never store real secret values in `values.yaml` or commit them to version control. Use `--set` at deploy time, or integrate with [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) / [Vault Agent](https://developer.hashicorp.com/vault/docs/platform/k8s/injector) for GitOps workflows.

## Configuration Reference

### Image

| Parameter | Description | Default |
|---|---|---|
| `image.repository` | Container image repository | `fileguard/api` |
| `image.tag` | Image tag (defaults to chart appVersion) | `""` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### Scaling

| Parameter | Description | Default |
|---|---|---|
| `replicaCount` | Number of replicas (used when HPA is disabled) | `2` |
| `autoscaling.enabled` | Enable HorizontalPodAutoscaler | `true` |
| `autoscaling.minReplicas` | Minimum replica count | `2` |
| `autoscaling.maxReplicas` | Maximum replica count | `20` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU utilisation for HPA | `60` |

### Resources

| Parameter | Description | Default |
|---|---|---|
| `resources.limits.cpu` | CPU limit | `1000m` |
| `resources.limits.memory` | Memory limit | `512Mi` |
| `resources.requests.cpu` | CPU request | `250m` |
| `resources.requests.memory` | Memory request | `256Mi` |

### Probes

| Parameter | Description | Default |
|---|---|---|
| `livenessProbe.httpGet.path` | Liveness probe HTTP path | `/healthz` |
| `livenessProbe.initialDelaySeconds` | Liveness probe initial delay | `10` |
| `readinessProbe.httpGet.path` | Readiness probe HTTP path | `/healthz` |
| `readinessProbe.initialDelaySeconds` | Readiness probe initial delay | `5` |

### Application Configuration (non-sensitive)

| Parameter | Description | Default |
|---|---|---|
| `config.logLevel` | Application log level | `INFO` |
| `config.maxFileSizeMb` | Maximum file size in MB for real-time scan | `50` |
| `config.workerConcurrency` | Number of concurrent scan workers | `4` |
| `config.allowedMimeTypes` | Comma-separated list of accepted MIME types | PDF, DOCX, CSV, JSON, TXT, ZIP |

### Service

| Parameter | Description | Default |
|---|---|---|
| `service.type` | Kubernetes service type | `ClusterIP` |
| `service.port` | Service port | `80` |
| `service.targetPort` | Container port | `8000` |

### Ingress

| Parameter | Description | Default |
|---|---|---|
| `ingress.enabled` | Enable Ingress | `false` |
| `ingress.className` | IngressClass name | `""` |
| `ingress.hosts` | Ingress host rules | see `values.yaml` |
| `ingress.tls` | TLS configuration | `[]` |

## Security Architecture

The Helm chart enforces the following security controls:

- **Secrets isolation:** `DATABASE_URL`, `REDIS_URL`, and `SECRET_KEY` are stored in a Kubernetes `Secret`, never in a `ConfigMap`.
- **Non-root execution:** Pods run as UID 1000 (`runAsNonRoot: true`).
- **Read-only root filesystem:** Container filesystem is read-only; a `tmpfs` emptyDir volume is mounted at `/tmp/scans` for ephemeral scan file processing.
- **Capability drop:** All Linux capabilities are dropped from the container.
- **No privilege escalation:** `allowPrivilegeEscalation: false`.

## Horizontal Pod Autoscaler

When `autoscaling.enabled: true` (default), the chart deploys an HPA targeting 60% CPU utilisation with a range of 2–20 replicas. This matches the HLD scalability strategy for stateless scan workers.

To disable the HPA and use a fixed replica count:

```bash
helm upgrade fileguard ./helm \
  --set autoscaling.enabled=false \
  --set replicaCount=4
```

## Upgrading

```bash
helm upgrade fileguard ./helm \
  --set image.tag=1.2.0 \
  --reuse-values
```

## Uninstalling

```bash
helm uninstall fileguard --namespace fileguard
```

> **Note:** The Secret is annotated with `helm.sh/resource-policy: keep` to prevent accidental deletion of credentials on `helm uninstall`. Delete it manually when decommissioning:
> ```bash
> kubectl delete secret fileguard-secrets --namespace fileguard
> ```
