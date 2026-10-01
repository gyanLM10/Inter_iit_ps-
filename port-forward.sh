#!/bin/bash
echo "Port forwarding MCP servers..."
kubectl port-forward svc/k8s-mcp -n rca-agent 3000:3000 >/dev/null 2>&1 &
PF1=$!
kubectl port-forward svc/prometheus-mcp -n rca-agent 3001:3001 >/dev/null 2>&1 &
PF2=$!
kubectl port-forward svc/loki-mcp -n rca-agent 3002:3002 >/dev/null 2>&1 &
PF3=$!
echo "Port forwards started (PIDs: $PF1, $PF2, $PF3)"
