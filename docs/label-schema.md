# NaaS Label Schema

All namespaces managed by this platform must carry the following labels. They are the single source of truth for everything downstream: RBAC, network policies, resource quotas, IAM groups, and ArgoCD project membership.

## Required Labels

| Label | Allowed values | Purpose |
|-------|---------------|---------|
| `naas.io/team` | `[a-z][a-z0-9-]{1,30}` | Team owner → Capsule Tenant, Authentik groups, ArgoCD AppProject |
| `naas.io/env` | `dev \| test \| acceptance \| production` | Target DTAP cluster + ResourceQuota tier |
| `naas.io/tier` | `backend \| frontend \| data \| infra` | LimitRange profile |
| `naas.io/app` | `[a-z][a-z0-9-]{1,60}` | Application/service name |
| `naas.io/cost-center` | any string | Finance billing code (propagated to all generated resources) |
| `naas.io/compliance` | `standard \| pci \| hipaa` | Extra Kyverno policies applied |
| `naas.io/owner-email` (**annotation**) | valid email | Alert routing and escalation contact |

## What Each Label Generates

### `naas.io/team`
- Capsule `Tenant` object groups all team namespaces under one quota umbrella
- Authentik groups: `naas-{team}-admin`, `naas-{team}-dev`, `naas-{team}-viewer`
- RoleBindings in every namespace:
  - `naas-{team}-admin` → `ClusterRole/namespace-admin`
  - `naas-{team}-dev` → `ClusterRole/namespace-developer`
  - `naas-{team}-viewer` → `ClusterRole/namespace-viewer`
- ArgoCD `AppProject/{team}` scoping deployments to `{team}-*` namespaces

## Tenant Aggregate Quotas

Capsule enforces a **combined ceiling across all namespaces a team owns**. Both the per-namespace quota (from `naas.io/env`, set by Kyverno) and the tenant aggregate quota (from the Tenant CR) apply simultaneously — the more restrictive one wins at any point.

The platform team assigns a tier when onboarding a team. See `tenants/tiers.yaml` for details.

| Tier | Max namespaces | CPU req total | Memory req total | PVCs total |
|------|---------------|---------------|-----------------|-----------|
| `small` | 5 | 50 | 100 Gi | 20 |
| `medium` | 10 | 100 | 200 Gi | 50 |
| `large` | 20 | 200 | 400 Gi | 100 |
| `xlarge` | 40 | 400 | 800 Gi | 200 |

Example (payments team, medium tier, 2×dev + 1×test + 1×acceptance + 1×production):
- Per-namespace usage: 2×4 + 8 + 16 + 32 = **68 CPU** → within 100 CPU ceiling ✓
- If they try to add a 5th production namespace: 68 + 32 = 100 CPU → hits ceiling, blocked ✓

### `naas.io/env` → DTAP cluster + per-namespace quota

| env | Cluster | CPU req/limit | Memory req/limit | Pods |
|-----|---------|---------------|-----------------|------|
| `dev` | dev cluster | 4 / 8 | 8Gi / 16Gi | 50 |
| `test` | test cluster | 8 / 16 | 16Gi / 32Gi | 80 |
| `acceptance` | acceptance cluster | 16 / 32 | 32Gi / 64Gi | 100 |
| `production` | production cluster | 32 / 64 | 64Gi / 128Gi | 200 |

### `naas.io/tier` → LimitRange

| tier | CPU default/max | Memory default/max |
|------|-----------------|--------------------|
| `backend` | 500m / 2 | 512Mi / 4Gi |
| `frontend` | 100m / 500m | 128Mi / 1Gi |
| `data` | 1 / 8 | 2Gi / 32Gi |
| `infra` | 1 / 8 | 1Gi / 16Gi |

### `naas.io/compliance`

| value | Extra policies |
|-------|---------------|
| `standard` | Baseline only (no-root, no-privilege-escalation, require-limits, restrict-hostpath) |
| `pci` | + Pod Security Admission: restricted, strict egress NetworkPolicy, no hostNetwork/hostPID |
| `hipaa` | + Pod Security Admission: restricted, audit annotations |

## Namespace Naming Convention

Namespace names follow the pattern: **`{team}-{tier}-{env}`**

Examples:
- `payments-backend-dev`
- `payments-backend-production`
- `fraud-data-acceptance`
- `identity-frontend-test`

The directory structure mirrors this:
```
namespaces/
└── {env}/
    └── {team}-{tier}/
        └── namespace.yaml
```
