# kubectl Access via Authentik OIDC

Team members authenticate to the Kubernetes API using their Authentik credentials.
RBAC is automatic — your Authentik group determines what you can do and where.

## Group → Access Matrix

| Authentik group | ClusterRole in namespace | Can do |
|----------------|--------------------------|--------|
| `naas-{team}-admin` | `namespace-admin` | Full RBAC within all `{team}-*` namespaces |
| `naas-{team}-dev` | `namespace-developer` | Deploy, scale, logs, exec — no secrets |
| `naas-{team}-viewer` | `namespace-viewer` | Read-only across all `{team}-*` namespaces |

Access is **namespace-scoped**: a `payments` dev has zero access to `platform-infra-dev`.

## Prerequisites

Install [kubelogin](https://github.com/int128/kubelogin) (the `kubectl` OIDC plugin):

```bash
brew install int128/kubelogin/kubelogin
# verify:
kubectl oidc-login version
```

## kubeconfig Setup

Add the following to `~/.kube/config` (replace `{team}` with your team name, e.g. `payments`):

```yaml
clusters:
- cluster:
    server: https://192.168.49.2:8443   # minikube IP — adjust per environment
  name: naas-local

users:
- name: naas-oidc
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: kubectl
      args:
        - oidc-login
        - get-token
        - --oidc-issuer-url=https://authentik.naas.local/
        - --oidc-client-id=kubernetes
        - --oidc-extra-scope=groups
        - --oidc-extra-scope=email
        - --oidc-extra-scope=profile
        - --listen-address=localhost:8000
        - --certificate-authority=/Users/joris/.kube/naas-local-ca.crt

contexts:
- context:
    cluster: naas-local
    user: naas-oidc
    namespace: payments-backend-dev   # default namespace for this context
  name: naas-payments-dev

current-context: naas-payments-dev
```

## First Login

```bash
# Triggers browser-based login via Authentik
kubectl get pods -n payments-backend-dev

# Browser opens at http://authentik.naas.local — log in with your credentials
# Token is cached locally; re-auth happens automatically when it expires (1h)
```

## What Each Role Can Do

### `namespace-developer` (naas-{team}-dev group)
```bash
# Allowed:
kubectl get pods,deploy,svc,configmap,ingress -n payments-backend-dev
kubectl logs deploy/checkout-service -n payments-backend-dev
kubectl exec -it deploy/checkout-service -n payments-backend-dev -- sh
kubectl rollout restart deploy/checkout-service -n payments-backend-dev
kubectl scale deploy/checkout-service --replicas=3 -n payments-backend-dev

# Denied:
kubectl get secrets -n payments-backend-dev          # no secret access
kubectl get pods -n platform-infra-dev               # wrong team
kubectl create namespace payments-backend-staging    # namespace creation blocked
```

### `namespace-admin` (naas-{team}-admin group)
```bash
# Everything the developer can do, plus:
kubectl create rolebinding ... -n payments-backend-dev
kubectl delete pods --all -n payments-backend-dev
kubectl get secrets -n payments-backend-dev
```

### `namespace-viewer` (naas-{team}-viewer group)
```bash
# Read-only:
kubectl get pods,deploy,svc -n payments-backend-dev
kubectl describe pod checkout-service-xxx -n payments-backend-dev
# No logs, no exec, no changes
```

## Verify Your Access

```bash
# Shows what you can do in a namespace
kubectl auth can-i --list -n payments-backend-dev

# Quick check: can I get pods?
kubectl auth can-i get pods -n payments-backend-dev
```
