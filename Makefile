PROFILE ?= naas-local
SKAFFOLD_PROFILE ?= local

.PHONY: up down reset hosts bootstrap proxy proxy-stop status logs ns-add help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start minikube + deploy full platform stack
	@./bootstrap/00-minikube-start.sh
	@skaffold run -p $(SKAFFOLD_PROFILE)
	@$(MAKE) hosts
	@echo ""
	@echo "==> Platform up. Run 'make bootstrap' to hand control to ArgoCD."

down: ## Tear down Skaffold deployments (keep minikube)
	skaffold delete -p $(SKAFFOLD_PROFILE)

reset: ## Full wipe: delete minikube profile and rebuild
	minikube delete --profile $(PROFILE) || true
	@$(MAKE) up

hosts: ## Configure /etc/resolver/naas.local for *.naas.local DNS (macOS)
	@./bootstrap/configure-hosts.sh

bootstrap: ## Apply ArgoCD root app (hands over GitOps control to ArgoCD)
	@echo "==> Waiting for ArgoCD server to be ready..."
	@kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=120s
	@echo "==> Applying root App-of-Apps..."
	kubectl apply -f platform/app-of-apps.yaml
	@echo ""
	@echo "==> ArgoCD is now managing the platform."
	@echo "    ArgoCD UI: https://argocd.naas.local"
	@echo "    Initial password: $$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo '[not found - OIDC already active]')"

status: ## Show ArgoCD application sync status
	kubectl get applications -n argocd

logs: ## Stream ArgoCD application controller logs
	kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

kyverno-test: ## Run Kyverno policy tests
	kyverno test policies/

validate-ns: ## Validate all namespace YAML files against label schema
	python3 scripts/validate-namespace-labels.py namespaces/

ns-add: ## Scaffold a new namespace (usage: make ns-add TEAM=payments TIER=backend ENV=dev COMPLIANCE=standard COST_CENTER=fin-123 APP=checkout)
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
	 echo "Created $$DIR/namespace.yaml — review labels and open a PR"
