# Local Development Guide

## Prerequisites

Install these tools before starting:

```bash
brew install minikube skaffold kubectl argocd kyverno helm
brew install --cask docker
```

## Quick Start

```bash
# 1. Start the full stack (minikube + platform components)
make up

# 2. Open a tunnel — REQUIRED for browser and OIDC access (keep this terminal open)
make tunnel

# 3. Fix DNS, CA cert, and CoreDNS (in a separate terminal)
make post-start

# 4. Hand over control to ArgoCD
make bootstrap
```

> **The tunnel is the most common cause of "things are unreachable".** It must stay running
> in a dedicated terminal. Without it the ingress-nginx LoadBalancer stays `<pending>` and
> `*.naas.local` returns connection refused.

After `make bootstrap`:
- **ArgoCD UI**: https://argocd.naas.local
  - Initial password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`
- **Authentik UI**: https://authentik.naas.local
  - Initial credentials: set in `bootstrap/06-authentik/values.yaml`

## Resuming after a machine restart

After `minikube stop` / machine sleep / reboot, the cluster state is preserved but three things reset:

```bash
# 1. Start the cluster
minikube start --profile naas-local

# 2. Re-inject CA cert + re-patch CoreDNS (both reset on stop/start)
make post-start

# 3. Start the tunnel again (separate terminal)
make tunnel
```

The CA cert in the Minikube container and the CoreDNS patch are both ephemeral — they must be re-applied after every start.

## Teardown

```bash
make down      # Remove all Helm releases, keep minikube
make reset     # Full wipe: delete minikube profile and rebuild
```

## Minikube Details

Started with:
- 4 CPUs, 8GB RAM, 40GB disk
- Addons: `ingress`, `ingress-dns`, `metrics-server`
- OIDC flags pre-configured for Authentik integration

Profile name: `naas-local` (so it doesn't conflict with other minikube profiles)

```bash
minikube profile naas-local   # switch to this profile
minikube status --profile naas-local
minikube ip --profile naas-local
```

## DNS Resolution

The `ingress-dns` addon provides DNS for `*.naas.local` via a local DNS server.
`make hosts` writes `/etc/resolver/naas.local` pointing to minikube's DNS.

If DNS stops working after a minikube restart (IP changes):
```bash
make hosts   # re-runs configure-hosts.sh to update the resolver IP
```

## Testing Kyverno Policies

```bash
# Run all policy tests
make kyverno-test

# Dry-run a specific namespace file
kyverno apply policies/baseline/ --resource namespaces/dev/payments-backend/namespace.yaml

# Test a bad pod (should be denied)
kubectl run badpod --image=nginx --namespace=payments-backend-dev \
  --overrides='{"spec":{"containers":[{"name":"c","image":"nginx","securityContext":{"runAsUser":0}}]}}'
```

## Validating Namespace Labels

```bash
make validate-ns
# or
python3 scripts/validate-namespace-labels.py namespaces/
```

## Adding a New Namespace Locally

```bash
make ns-add TEAM=myteam TIER=backend ENV=dev APP=my-app COMPLIANCE=standard COST_CENTER=eng-001
# Review the generated file, then commit and push
```

## SCM Provider Token (Required for ApplicationSets)

The namespace ApplicationSets use GitHub's SCM provider to auto-discover `naastest/team-*` repos. ArgoCD needs a GitHub PAT with `repo` (read) + `read:org` scope stored as:

```bash
kubectl create secret generic argocd-scm-token \
  --from-literal=token=ghp_YOUR_TOKEN \
  -n argocd
```

For local Minikube, create the secret after `make bootstrap`. In production, seal it with `kubeseal` and commit the SealedSecret.

## ArgoCD OIDC Secret (Required for Authentik login)

ArgoCD reads the Authentik OIDC client secret from a Kubernetes secret. It must have the label `app.kubernetes.io/part-of=argocd` so ArgoCD's informer watches it; without this label ArgoCD silently ignores the key and sends an empty secret to the token endpoint.

```bash
kubectl create secret generic argocd-authentik-secret \
  --from-literal=oidc.clientSecret=YOUR_CLIENT_SECRET \
  -n argocd \
  --dry-run=client -o yaml \
  | kubectl label --local -f - app.kubernetes.io/part-of=argocd -o yaml \
  | kubectl apply -f -
```

The client secret must match what is configured in Authentik's ArgoCD OAuth2 provider.

## Simulating DTAP Locally

For full DTAP simulation on a single minikube, register it as all 4 cluster targets in ArgoCD:

```bash
# dev cluster is in-cluster (already registered)
# Register the same cluster with different names for test/acceptance/production
argocd cluster add naas-local --name test     --kubeconfig ~/.kube/config --server https://kubernetes.default.svc
argocd cluster add naas-local --name acceptance --kubeconfig ~/.kube/config --server https://kubernetes.default.svc
argocd cluster add naas-local --name production --kubeconfig ~/.kube/config --server https://kubernetes.default.svc

# Patch labels on the cluster secrets
for env in dev test acceptance production; do
  kubectl label secret cluster-$env naas.io/managed=true naas.io/env=$env -n argocd --overwrite
done
```

This routes all 4 DTAP namespaces to the same minikube cluster. Namespaces will coexist with env-suffixed names.
