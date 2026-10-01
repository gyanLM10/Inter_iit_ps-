#!/usr/bin/env bash
# Reset workload — restore all scenarios to clean state
set -euo pipefail

echo "=== RESETTING WORKLOAD TO CLEAN STATE ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Remove any blocking NetworkPolicies
echo "Removing blocking NetworkPolicies..."
kubectl delete networkpolicy block-api-to-db -n workload 2>/dev/null || true

# Restore the original API deployment
echo "Restoring original API deployment..."
kubectl apply -f "${PROJECT_ROOT}/infra/workload/api.yaml"

# Wait for rollout
echo "Waiting for rollout..."
kubectl rollout status deployment/api -n workload --timeout=120s || true
kubectl rollout status deployment/frontend -n workload --timeout=60s || true
kubectl rollout status deployment/postgres -n workload --timeout=60s || true

echo ""
echo "=== Workload reset complete ==="
kubectl get pods -n workload
