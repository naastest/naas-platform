#!/usr/bin/env bash
# Injects the naas-local CA certificate into the minikube container's trust
# store so the kube-apiserver can validate Authentik's TLS cert for OIDC.
# Must be re-run after every `minikube stop && minikube start`.
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-naas-local}"

echo "==> Waiting for cert-manager to have naas-local-ca secret..."
kubectl wait secret naas-local-ca -n cert-manager --for=jsonpath='{.data.tls\.crt}' --timeout=120s 2>/dev/null || \
  kubectl wait secret naas-local-ca -n cert-manager --for=condition=exists 2>/dev/null || true

echo "==> Extracting CA certificate..."
kubectl get secret naas-local-ca -n cert-manager -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/naas-local-ca.crt

echo "==> Injecting CA into minikube container trust store..."
docker cp /tmp/naas-local-ca.crt "${PROFILE}:/etc/ssl/certs/naas-local-ca.crt"

# Append to the system bundle so openssl and Go's crypto/tls both pick it up
docker exec "$PROFILE" /bin/sh -c '
  if ! grep -q "naas-local-ca" /etc/ssl/certs/ca-certificates.crt 2>/dev/null; then
    cat /etc/ssl/certs/naas-local-ca.crt >> /etc/ssl/certs/ca-certificates.crt
    echo "  appended to ca-certificates.crt"
  else
    echo "  already present in ca-certificates.crt"
  fi
'

echo "==> Saving CA to ~/.kube/naas-local-ca.crt for kubelogin..."
cp /tmp/naas-local-ca.crt ~/.kube/naas-local-ca.crt

echo "==> CA injection complete."
