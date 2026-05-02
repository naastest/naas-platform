# PR Preview Environments

When you open a pull request on your team repo, ArgoCD automatically creates a temporary
preview environment scoped to that PR. It is torn down the moment the PR closes or merges.

## How it works

1. You open PR #42 on `naastest/team-payments`
2. ArgoCD detects it (polls every 2 minutes)
3. Creates Application `preview-team-payments-pr-42`
4. Deploys `apps/dev/` from your PR branch into namespace `payments-preview-pr-42`
5. Kyverno generates quota, limits, network policies, and role bindings for the namespace
6. PR closes → Application deleted → namespace garbage-collected

## Namespace structure requirement

**Resources in `apps/dev/` must not hardcode a namespace.**

ArgoCD deploys your preview into `{team}-preview-pr-{number}`. Resources with a hardcoded
namespace (e.g. `namespace: payments-backend-dev`) bypass the preview namespace and land in
your live dev namespace instead — colliding with the Application already managing it there.

Use **Kustomize** so the namespace can be set at deploy time:

```
apps/
  dev/
    base/
      kustomization.yaml     # lists all resources, no namespace set here
      payment-api.yaml       # no namespace field in metadata
      checkout-service.yaml  # no namespace field in metadata
    overlays/
      live/
        kustomization.yaml   # namespace: payments-backend-dev
      preview/
        kustomization.yaml   # namespace: set by ArgoCD via managedNamespaceMetadata
```

`apps/dev/base/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - payment-api.yaml
  - checkout-service.yaml
```

`apps/dev/overlays/live/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: payments-backend-dev
resources:
  - ../../base
```

`apps/dev/overlays/preview/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# No namespace set — ArgoCD injects payments-preview-pr-{N} via managedNamespaceMetadata
resources:
  - ../../base
```

The `tenant-apps-dev` ApplicationSet points at `apps/dev` (the live overlay).
The `pr-preview-team-payments` ApplicationSet points at `apps/dev/overlays/preview`.

Update `platform/applicationsets/pr-previews.yaml` for your team to use the preview overlay:

```yaml
source:
  path: apps/dev/overlays/preview   # was: apps/dev
```

## What the preview namespace gets

The preview namespace is created with the same labels as your dev namespace, plus
`naas.io/preview: "true"`. Kyverno generates the full set of resources automatically:

| Resource | Value |
|----------|-------|
| `ResourceQuota` | dev tier (4 CPU / 8 Gi) |
| `LimitRange` | matches your `naas.io/tier` |
| `NetworkPolicy` | default-deny + allow within tenant |
| `RoleBinding/naas-admin` | `naas-{team}-admin` → `namespace-admin` |
| `RoleBinding/naas-developer` | `naas-{team}-dev` → `namespace-developer` |
| `RoleBinding/naas-viewer` | `naas-{team}-viewer` → `namespace-viewer` |

## What the preview namespace cannot do

The preview Application runs under your team's AppProject, which enforces the same
boundaries as your live environments:

| Attempted resource | Blocked by |
|--------------------|-----------|
| `Tenant` | `clusterResourceWhitelist` — only `Namespace` is allowed |
| `AppProject` | `clusterResourceWhitelist` |
| `ClusterRoleBinding` | `clusterResourceWhitelist` |
| `NetworkPolicy` | `namespaceResourceBlacklist` |
| `ResourceQuota` | `namespaceResourceBlacklist` |
| `kyverno.io/*` | `namespaceResourceBlacklist` |
| Deploy to another team's namespace | `destinations` — only `{team}-*` allowed |
| Privileged / root container | Kyverno admission (`no-root-containers`, `disallow-privilege-escalation`) |

## Cleanup

Preview namespaces are pruned automatically when the PR closes. If you need to force-delete:

```bash
kubectl delete namespace payments-preview-pr-42
```

Capsule will honour the deletion — the namespace is not protected beyond normal RBAC.
