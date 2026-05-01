#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-naas-local}"
CPUS="${MINIKUBE_CPUS:-4}"
MEMORY="${MINIKUBE_MEMORY:-7000}"
DISK="${MINIKUBE_DISK:-40g}"
K8S_VERSION="${MINIKUBE_K8S_VERSION:-v1.31.0}"

echo "==> Starting Minikube profile: $PROFILE"
minikube start \
  --profile "$PROFILE" \
  --driver=docker \
  --cpus="$CPUS" \
  --memory="$MEMORY" \
  --disk-size="$DISK" \
  --kubernetes-version="$K8S_VERSION" \
  --addons=ingress,ingress-dns,metrics-server \
  --extra-config=apiserver.oidc-issuer-url=https://authentik.naas.local/ \
  --extra-config=apiserver.oidc-client-id=kubernetes \
  --extra-config=apiserver.oidc-username-claim=email \
  --extra-config=apiserver.oidc-groups-claim=groups \
  --extra-config=apiserver.oidc-groups-prefix=""

echo "==> Minikube started. IP: $(minikube ip --profile "$PROFILE")"
echo ""
echo "Next: run 'make hosts' to configure DNS resolution for *.naas.local"
