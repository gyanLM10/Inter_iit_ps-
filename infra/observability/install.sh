#!/usr/bin/env bash
# Install observability stack into the kind cluster
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Creating monitoring namespace..."
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

echo "==> Adding Helm repos..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
helm repo update

echo "==> Installing kube-prometheus-stack..."
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values "${SCRIPT_DIR}/prometheus-values.yaml" \
  --wait --timeout 5m

echo "==> Installing Loki..."
helm upgrade --install loki grafana/loki \
  --namespace monitoring \
  --values "${SCRIPT_DIR}/loki-values.yaml" \
  --wait --timeout 5m

echo "==> Installing Promtail..."
helm upgrade --install promtail grafana/promtail \
  --namespace monitoring \
  --values "${SCRIPT_DIR}/promtail-values.yaml" \
  --wait --timeout 3m

echo "==> Installing metrics-server..."
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null || true
# Patch metrics-server for kind (insecure kubelet TLS)
kubectl patch deployment metrics-server -n kube-system \
  --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]' 2>/dev/null || true

echo "==> Observability stack installed successfully!"
echo "    Prometheus: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"
echo "    Loki:       kubectl port-forward -n monitoring svc/loki 3100:3100"
