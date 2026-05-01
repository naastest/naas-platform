PROFILE        ?= naas-local
SKAFFOLD_PROFILE ?= local

# ── colours ──────────────────────────────────────────────────────────────────
CYAN  := \033[36m
RESET := \033[0m

.PHONY: up down reset hosts bootstrap fix-ca coredns-patch fix-kubeconfig tunnel \
        apply-namespace-blueprint status logs kyverno-test validate-ns \
        ns-add help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "$(CYAN)%-28s$(RESET) %s\n", $$1, $$2}'

# ── Cluster lifecycle ─────────────────────────────────────────────────────────

up: ## Start minikube + deploy full platform stack
	@./bootstrap/00-minikube-start.sh
	@skaffold run -p $(SKAFFOLD_PROFILE)
	@$(MAKE) post-start
	@echo ""
	@echo "==> Platform up. Run 'make bootstrap' to hand control to ArgoCD."

down: ## Tear down Skaffold deployments (keep minikube running)
	skaffold delete -p $(SKAFFOLD_PROFILE)

reset: ## Full wipe — delete minikube profile and rebuild from scratch
	minikube delete --profile $(PROFILE) || true
	@$(MAKE) up

# ── Post-start fixups (run automatically after up, or manually after restart) ─

post-start: fix-kubeconfig hosts fix-ca coredns-patch ## Run all post-start fixups (kubeconfig, hosts, CA, CoreDNS)

fix-kubeconfig: ## Fix naas-local kubeconfig user credentials (minikube update-context blanks them)
	@echo "==> Fixing naas-local kubeconfig credentials..."
	@minikube update-context --profile $(PROFILE) 2>/dev/null || true
	@kubectl config set-credentials $(PROFILE) \
	  --client-certificate=$(HOME)/.minikube/profiles/$(PROFILE)/client.crt \
	  --client-key=$(HOME)/.minikube/profiles/$(PROFILE)/client.key
	@kubectl config set-cluster $(PROFILE) \
	  --certificate-authority=$(HOME)/.minikube/ca.crt
	@echo "    naas-local kubeconfig credentials restored."

hosts: ## Configure /etc/resolver/naas.local for *.naas.local DNS (macOS)
	@./bootstrap/configure-hosts.sh

fix-ca: ## Inject naas-local CA cert into minikube + ~/.kube for OIDC TLS
	@./bootstrap/fix-ca.sh

coredns-patch: ## Patch CoreDNS to resolve *.naas.local to ingress-nginx inside cluster
	@./bootstrap/coredns-patch.sh

tunnel: ## Start minikube tunnel (required for OIDC login from macOS host)
	@echo "==> Starting minikube tunnel (keep this terminal open)..."
	@echo "    This exposes ingress-nginx on 127.0.0.1:443 so browsers can reach authentik.naas.local"
	minikube tunnel --profile $(PROFILE)

# ── ArgoCD handover ───────────────────────────────────────────────────────────

bootstrap: ## Apply ArgoCD root app-of-apps (hands GitOps control to ArgoCD)
	@echo "==> Waiting for ArgoCD server to be ready..."
	@kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=120s
	@echo "==> Applying root App-of-Apps..."
	kubectl apply -f platform/app-of-apps.yaml
	@echo ""
	@echo "==> ArgoCD is now managing the platform."
	@echo "    ArgoCD UI : https://argocd.naas.local"
	@echo "    Password  : $$(kubectl -n argocd get secret argocd-initial-admin-secret \
	                          -o jsonpath='{.data.password}' 2>/dev/null | base64 -d \
	                          || echo '[not found — OIDC already active]')"

# ── Namespace management ──────────────────────────────────────────────────────

ns-add: ## Scaffold new namespace (TEAM= TIER= ENV= APP= COMPLIANCE= COST_CENTER=)
	@[ -n "$(TEAM)" ] || (echo "Usage: make ns-add TEAM=<team> TIER=<tier> ENV=<env> APP=<app> COMPLIANCE=standard COST_CENTER=<cc>"; exit 1)
	@DIR=namespaces/$(TEAM)-$(TIER)-$(ENV); \
	 if [ -d "$$DIR" ]; then echo "ERROR: $$DIR already exists"; exit 1; fi; \
	 cp -r namespaces/_template "$$DIR"; \
	 sed -i.bak \
	   -e 's/TEAM_PLACEHOLDER/$(TEAM)/g' \
	   -e 's/ENV_PLACEHOLDER/$(ENV)/g' \
	   -e 's/TIER_PLACEHOLDER/$(TIER)/g' \
	   -e 's/COMPLIANCE_PLACEHOLDER/$(COMPLIANCE)/g' \
	   -e 's/COST_CENTER_PLACEHOLDER/$(COST_CENTER)/g' \
	   -e 's/APP_PLACEHOLDER/$(APP)/g' \
	   "$$DIR/namespace.yaml" && rm -f "$$DIR/namespace.yaml.bak"; \
	 echo "Created $$DIR/namespace.yaml — review labels then run:"; \
	 echo "  make apply-namespace-blueprint NS=$$DIR"

apply-namespace-blueprint: ## Apply Authentik groups + delegation for a namespace (NS=namespaces/...)
	@[ -n "$(NS)" ] || (echo "Usage: make apply-namespace-blueprint NS=namespaces/<name>"; exit 1)
	@[ -n "$(AUTHENTIK_TOKEN)" ] || (echo "Error: AUTHENTIK_TOKEN is not set"; exit 1)
	uv run scripts/apply-namespace-blueprint.py $(NS)/namespace.yaml

# ── Observability ─────────────────────────────────────────────────────────────

status: ## Show ArgoCD application sync status
	kubectl get applications -n argocd

logs: ## Stream ArgoCD application-controller logs
	kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# ── Validation ────────────────────────────────────────────────────────────────

kyverno-test: ## Run Kyverno policy tests
	kyverno test policies/

validate-ns: ## Validate all namespace YAML files against label schema
	uv run scripts/validate-namespace-labels.py namespaces/
