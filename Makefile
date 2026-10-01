.PHONY: help setup-cluster deploy-observability deploy-workload deploy-rbac \
       deploy-network build-mcp deploy-mcp setup-agent \
       trigger-bad-deploy trigger-oom trigger-cascade reset-workload \
       investigate test-security teardown clean

SHELL := /bin/bash
PROJECT_ROOT := $(shell pwd)

# ─── Help ─────────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Environment & Sandbox
# ═══════════════════════════════════════════════════════════════════════════════

setup-cluster: ## Create the kind cluster
	@echo "==> Creating kind cluster 'rca-lab'..."
	kind create cluster --config infra/kind-config.yaml --wait 60s
	@echo "==> Cluster ready!"
	kubectl cluster-info --context kind-rca-lab

deploy-observability: ## Install Prometheus, Loki, Promtail, metrics-server
	@echo "==> Deploying observability stack..."
	chmod +x infra/observability/install.sh
	bash infra/observability/install.sh

deploy-workload: ## Deploy the target microservices (frontend → API → PostgreSQL)
	@echo "==> Creating namespaces..."
	kubectl apply -f infra/workload/namespace.yaml
	@echo "==> Building and loading API image into kind..."
	docker build -t rca-lab/api:latest infra/workload/api-app/
	kind load docker-image rca-lab/api:latest --name rca-lab
	@echo "==> Deploying workload..."
	kubectl apply -f infra/workload/postgres.yaml
	@echo "Waiting for PostgreSQL..."
	kubectl wait --for=condition=ready pod -l app=postgres -n workload --timeout=120s
	kubectl apply -f infra/workload/api.yaml
	kubectl apply -f infra/workload/frontend.yaml
	@echo "Waiting for all pods..."
	kubectl wait --for=condition=ready pod -l tier=backend -n workload --timeout=120s || true
	kubectl wait --for=condition=ready pod -l tier=frontend -n workload --timeout=60s || true
	@echo "==> Workload deployed!"
	kubectl get pods -n workload

deploy-rbac: ## Apply RBAC (read-only ServiceAccount)
	@echo "==> Applying RBAC..."
	kubectl apply -f infra/rbac/rbac.yaml
	@echo "==> Verifying RBAC..."
	@echo -n "  can-i get pods: "; kubectl auth can-i get pods --as=system:serviceaccount:rca-agent:rca-agent-sa || true
	@echo -n "  can-i delete pods: "; kubectl auth can-i delete pods --as=system:serviceaccount:rca-agent:rca-agent-sa || true
	@echo -n "  can-i exec pods: "; kubectl auth can-i create pods/exec --as=system:serviceaccount:rca-agent:rca-agent-sa || true

deploy-network: ## Apply NetworkPolicies for agent isolation
	@echo "==> Applying NetworkPolicies..."
	kubectl apply -f infra/network-policies/policies.yaml

setup-infra: setup-cluster deploy-observability deploy-workload deploy-rbac deploy-network ## Full infrastructure setup (all Phase 1)
	@echo ""
	@echo "═══════════════════════════════════════════════════════════"
	@echo " Phase 1 Complete: Infrastructure is ready"
	@echo "═══════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: MCP Servers
# ═══════════════════════════════════════════════════════════════════════════════

build-mcp: ## Build all Rust MCP server Docker images
	@echo "==> Building MCP servers..."
	docker build -t rca-lab/k8s-mcp:latest -f mcp-servers/k8s-mcp/Dockerfile mcp-servers/
	docker build -t rca-lab/prometheus-mcp:latest -f mcp-servers/prometheus-mcp/Dockerfile mcp-servers/
	docker build -t rca-lab/loki-mcp:latest -f mcp-servers/loki-mcp/Dockerfile mcp-servers/
	@echo "==> MCP images built!"

deploy-mcp: build-mcp ## Build and deploy MCP servers to the kind cluster
	@echo "==> Loading MCP images into kind..."
	kind load docker-image rca-lab/k8s-mcp:latest --name rca-lab
	kind load docker-image rca-lab/prometheus-mcp:latest --name rca-lab
	kind load docker-image rca-lab/loki-mcp:latest --name rca-lab
	@echo "==> Deploying MCP servers..."
	kubectl apply -f infra/mcp-deployments.yaml
	kubectl wait --for=condition=ready pod -l role=mcp-server -n rca-agent --timeout=120s || true
	@echo "==> MCP servers deployed!"
	kubectl get pods -n rca-agent

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Agent
# ═══════════════════════════════════════════════════════════════════════════════

setup-agent: ## Install Python dependencies for the agent
	@echo "==> Installing agent dependencies..."
	pip install -r agent/requirements.txt
	@echo "==> Agent dependencies installed!"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Failure Scenarios
# ═══════════════════════════════════════════════════════════════════════════════

trigger-bad-deploy: ## Scenario 1: Deploy a broken API image
	chmod +x scenarios/scenario_bad_deploy.sh
	bash scenarios/scenario_bad_deploy.sh

trigger-oom: ## Scenario 2: Trigger OOMKilled via memory pressure
	chmod +x scenarios/scenario_oom.sh
	bash scenarios/scenario_oom.sh

trigger-cascade: ## Scenario 3: Sever API→DB connection (cascading failure)
	chmod +x scenarios/scenario_cascade.sh
	bash scenarios/scenario_cascade.sh

reset-workload: ## Reset workload to clean state
	chmod +x scenarios/reset_workload.sh
	bash scenarios/reset_workload.sh

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5: Investigation & Testing
# ═══════════════════════════════════════════════════════════════════════════════

investigate: ## Run the RCA agent to investigate the current incident
	@echo "==> Starting RCA investigation..."
	cd agent && python -m agent.graph \
		"Multiple errors detected in the workload namespace. Users are reporting service degradation."

investigate-custom: ## Run the RCA agent with a custom incident description (use INCIDENT="...")
	@echo "==> Starting RCA investigation..."
	cd agent && python -m agent.graph "$(INCIDENT)"

test-security: ## Run the prompt injection security test
	chmod +x tests/test_prompt_injection.sh
	bash tests/test_prompt_injection.sh

test-rust: ## Run Rust unit tests for MCP servers
	cd mcp-servers && cargo test --all

# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════════

teardown: ## Destroy the kind cluster and clean up
	@echo "==> Tearing down kind cluster..."
	kind delete cluster --name rca-lab
	@echo "==> Cluster destroyed!"

clean: ## Remove build artifacts
	cd mcp-servers && cargo clean 2>/dev/null || true
	find agent -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
