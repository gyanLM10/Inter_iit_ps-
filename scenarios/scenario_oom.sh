#!/usr/bin/env bash
# Scenario 2: OOMKilled (Resource Saturation)
# Sends high traffic to a pod with tight memory limits to trigger OOM
set -euo pipefail

echo "=== SCENARIO 2: OOMKilled (Resource Saturation) ==="

# First, ensure the API deployment has very tight memory limits
echo "Setting tight memory limits (64Mi) on API deployment..."
kubectl patch deployment api -n workload --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources/limits/memory",
    "value": "64Mi"
  },
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources/requests/memory",
    "value": "32Mi"
  }
]'

echo "Waiting for rollout..."
kubectl rollout status deployment/api -n workload --timeout=60s || true

echo "Sending memory-intensive requests to trigger OOM..."

# Use kubectl port-forward in background
kubectl port-forward svc/api -n workload 18000:8000 &
PF_PID=$!
sleep 2

# Send requests that allocate memory via the /api/stress endpoint
for i in $(seq 1 20); do
    curl -s -X POST "http://localhost:18000/api/stress?size_mb=30" &
done

# Wait for requests and OOM to occur
sleep 15

# Cleanup port-forward
kill $PF_PID 2>/dev/null || true

echo ""
echo "=== Scenario triggered! ==="
echo "The API pods should be OOMKilled due to tight memory limits under load."
echo "Expected symptoms: OOMKilled exit codes, pod restarts, memory spike in Prometheus."
echo ""
echo "Check pod status: kubectl get pods -n workload"
echo "Run the agent with: make investigate"
