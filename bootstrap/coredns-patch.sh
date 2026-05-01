#!/usr/bin/env bash
# Patches the CoreDNS ConfigMap to resolve *.naas.local hostnames to the
# ingress-nginx LoadBalancer IP. Must be re-run after cluster recreate.
set -euo pipefail

echo "==> Detecting ingress-nginx ClusterIP..."
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.spec.clusterIP}')
echo "    ingress-nginx ClusterIP: ${INGRESS_IP}"

echo "==> Patching CoreDNS ConfigMap..."
kubectl patch configmap coredns -n kube-system --type merge -p "$(cat <<EOF
{
  "data": {
    "Corefile": ".:53 {\n    log\n    errors\n    health {\n       lameduck 5s\n    }\n    ready\n    kubernetes cluster.local in-addr.arpa ip6.arpa {\n       pods insecure\n       fallthrough in-addr.arpa ip6.arpa\n       ttl 30\n    }\n    prometheus :9153\n    hosts {\n       192.168.65.254 host.minikube.internal\n       ${INGRESS_IP} authentik.naas.local\n       ${INGRESS_IP} argocd.naas.local\n       ${INGRESS_IP} capsule-proxy.naas.local\n       fallthrough\n    }\n    forward . /etc/resolv.conf {\n       max_concurrent 1000\n    }\n    cache 30\n    loop\n    reload\n    loadbalance\n}\n"
  }
}
EOF
)"

echo "==> Restarting CoreDNS pods to pick up change..."
kubectl rollout restart deployment/coredns -n kube-system
kubectl rollout status deployment/coredns -n kube-system --timeout=60s

echo "==> CoreDNS patch applied. naas.local hostnames now resolve inside the cluster."
