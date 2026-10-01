#!/usr/bin/env bash
# Scenario 1: Bad Deployment (Config Change)
# Applies a broken API image that crashes immediately (exit 1)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== SCENARIO 1: Bad Deployment ==="
echo "Deploying a broken API image that exits immediately..."

# Build the broken API image
cat > /tmp/bad-api-app.py << 'PYEOF'
"""Broken API — exits immediately to simulate a bad deployment."""
import sys
import logging

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger('api-service')
logger.error("FATAL: Configuration validation failed — missing required DATABASE_ENCRYPTION_KEY")
logger.error("Shutting down due to startup error")
sys.exit(1)
PYEOF

cat > /tmp/bad-api-Dockerfile << 'DEOF'
FROM python:3.12-slim
WORKDIR /app
COPY bad-api-app.py app.py
CMD ["python", "app.py"]
DEOF

echo "Building broken image..."
docker build -t rca-lab/api:broken -f /tmp/bad-api-Dockerfile /tmp/

echo "Loading broken image into kind cluster..."
kind load docker-image rca-lab/api:broken --name rca-lab

echo "Applying broken deployment..."
kubectl set image deployment/api api=rca-lab/api:broken -n workload

echo ""
echo "=== Scenario triggered! ==="
echo "The API deployment now uses a broken image that exits on startup."
echo "Expected symptoms: CrashLoopBackOff, 5xx errors from frontend."
echo ""
echo "Run the agent with: make investigate"
