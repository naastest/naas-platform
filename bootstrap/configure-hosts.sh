#!/usr/bin/env bash
# Configures *.naas.local DNS resolution on macOS via minikube ingress-dns.
# Uses /etc/resolver/naas.local instead of /etc/hosts to avoid mDNS conflicts.
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-naas-local}"
DOMAIN="naas.local"

MINIKUBE_IP=$(minikube ip --profile "$PROFILE" 2>/dev/null)
if [ -z "$MINIKUBE_IP" ]; then
  echo "ERROR: Could not get minikube IP. Is minikube running?"
  exit 1
fi

echo "==> Configuring DNS resolver for .$DOMAIN -> $MINIKUBE_IP"

sudo mkdir -p /etc/resolver
cat <<EOF | sudo tee /etc/resolver/"$DOMAIN" > /dev/null
domain $DOMAIN
nameserver $MINIKUBE_IP
search_order 1
timeout 5
EOF

echo "==> DNS resolver written to /etc/resolver/$DOMAIN"
echo ""
echo "Hostnames now accessible:"
echo "  https://argocd.$DOMAIN"
echo "  https://authentik.$DOMAIN"
echo ""
echo "NOTE: If DNS doesn't resolve immediately, try: sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder"
