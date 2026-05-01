#!/usr/bin/env bash
# Adds *.naas.local hostnames to /etc/hosts pointing to 127.0.0.1.
# Works with `minikube tunnel` which assigns 127.0.0.1 to the ingress LoadBalancer.
set -euo pipefail

DOMAIN="naas.local"
HOSTS=(
  "argocd.$DOMAIN"
  "authentik.$DOMAIN"
  "capsule-proxy.$DOMAIN"
  "gangplank.$DOMAIN"
)

MARKER="# naas-local"

echo "==> Adding $DOMAIN hostnames to /etc/hosts (requires sudo)"

for host in "${HOSTS[@]}"; do
  if grep -qF "$host" /etc/hosts; then
    echo "    already present: $host"
  else
    echo "127.0.0.1 $host $MARKER" | sudo tee -a /etc/hosts > /dev/null
    echo "    added: $host"
  fi
done

echo ""
echo "Hostnames configured (requires 'minikube tunnel --profile naas-local' to be running):"
for host in "${HOSTS[@]}"; do
  echo "  http://$host"
done
