#!/usr/bin/env bash
# Scenario 3: Cascading Dependency Failure
# Applies a NetworkPolicy that severs the API → PostgreSQL connection
set -euo pipefail

echo "=== SCENARIO 3: Cascading Dependency Failure ==="
echo "Severing the connection between API and PostgreSQL..."

# Apply a NetworkPolicy that blocks API pods from reaching PostgreSQL
cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: block-api-to-db
  namespace: workload
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
    - Egress
  egress:
    # Allow DNS
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Allow everything EXCEPT PostgreSQL port
    - to:
        - podSelector:
            matchExpressions:
              - key: app
                operator: NotIn
                values: ["postgres"]
      ports:
        - protocol: TCP
EOF

echo "NetworkPolicy applied. API pods can no longer reach PostgreSQL."
echo ""

# Generate some traffic to trigger the errors
echo "Generating traffic to trigger cascading errors..."
kubectl port-forward svc/frontend -n workload 18080:80 &
PF_PID=$!
sleep 2

for i in $(seq 1 10); do
    curl -s "http://localhost:18080/api/items" > /dev/null 2>&1 || true
    sleep 0.5
done

kill $PF_PID 2>/dev/null || true

echo ""
echo "=== Scenario triggered! ==="
echo "The API can no longer reach PostgreSQL."
echo "Expected symptoms: Frontend returns 5xx, API logs show DB connection timeouts."
echo "The cascading failure chain: Frontend 5xx → API errors → DB connection refused."
echo ""
echo "Run the agent with: make investigate"
