# Team Onboarding — How to Request a Namespace

This document explains how a team requests a new namespace in the NaaS platform.

## Prerequisites

Before requesting a namespace, your team needs:
1. A **Tenant** in the platform repo (`naastest/naas-platform`). Contact the platform team to add `tenants/{team}.yaml` — they use `tenants/_template.yaml` as the starting point. This is a one-time step.
2. A **team repo** (`naastest/team-{yourteam}`). Ask the platform team to create it — this is also one-time and takes ~5 minutes.

## Step 1: Work in Your Team Repo

Each team has their own repo in the `naastest` org: `naastest/team-{yourteam}`.
Namespace definitions live in that repo, not in `naas-platform`. This means you can
PR, review, and merge dev/test changes without involving the platform team.

```bash
git clone git@github.com:naastest/team-myteam.git
cd team-myteam
mkdir -p namespaces/dev
cp /path/to/naas-platform/namespaces/_template/namespace.yaml namespaces/dev/namespace.yaml
# Edit the file
```

## Step 2: Fill in the Labels

Required labels — see [label-schema.md](label-schema.md) for allowed values:

```yaml
naas.io/team: "myteam"                # your team slug
naas.io/env: "dev"                    # dev | test | acceptance | production
naas.io/tier: "backend"               # backend | frontend | data | infra
naas.io/app: "my-service"             # your application name
naas.io/cost-center: "eng-123"        # finance cost center code
naas.io/compliance: "standard"        # standard | pci | hipaa
naas.io/owner-email: "team@co.com"    # distribution list for alerts
```

Also fill in the annotations:
```yaml
naas.io/requested-by: "your-github-username"
naas.io/jira-ticket: "PLAT-1234"
naas.io/description: "Description of what runs here"
```

## Step 3: Open a Pull Request

```bash
git checkout -b ns/myteam-backend-dev
git add namespaces/dev/myteam-backend/
git commit -m "feat(ns): add myteam-backend-dev namespace"
git push origin ns/myteam-backend-dev
# Open PR on GitHub targeting main
```

## Step 4: CI Validation

The PR automatically runs:
1. **Label schema validation** — checks all required labels have valid values
2. **Kyverno dry-run** — verifies the namespace would pass all baseline policies
3. **PR summary comment** — lists exactly what will be provisioned

Fix any CI failures before requesting review.

## Step 5: Platform Team Review

The platform team reviews and approves via CODEOWNERS. Typical SLA: 1 business day.

## Step 6: Merge and Provisioning (~3 minutes)

After merge:
1. ArgoCD detects the new directory and creates an Application
2. The Namespace is synced to the target DTAP cluster
3. Kyverno generates: ResourceQuota, LimitRange, NetworkPolicies, RoleBindings
4. Capsule assigns the namespace to your team's Tenant
5. Authentik groups `naas-{team}-admin/dev/viewer` are created (if not already existing)

## Step 7: Access Your Namespace

**kubectl access** (via OIDC with Authentik):
```bash
# Install kubectl oidc-login plugin
brew install int128/kubelogin/kubelogin

# Configure your kubeconfig
kubectl config set-credentials oidc \
  --exec-api-version=client.authentication.k8s.io/v1beta1 \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://authentik.naas.local/application/o/kubernetes/ \
  --exec-arg=--oidc-client-id=kubernetes \
  --exec-arg=--oidc-extra-scope=groups
```

**ArgoCD access** (https://argocd.naas.local):
- Log in with your Authentik credentials
- You will see your team's AppProject and can create Applications targeting your namespaces

## Requesting Additional Environments

For each additional DTAP environment (test, acceptance, production), open a separate PR adding:
- `namespaces/test/myteam-backend/namespace.yaml` (with `naas.io/env: test`)
- `namespaces/acceptance/myteam-backend/namespace.yaml`
- `namespaces/production/myteam-backend/namespace.yaml`

Production namespaces require an additional approver sign-off.
