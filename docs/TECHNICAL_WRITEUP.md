# Technical Write-up: AI Agent for Kubernetes Root-Cause Analysis

## 1. Architecture Overview

The system implements a **hypothesis-driven cyclic investigation loop** using LangGraph, backed by three domain-specific MCP (Model Context Protocol) servers that provide read-only access to a Kubernetes cluster's infrastructure, metrics, and logs.

```
                ┌─────────────────────────────────────────────┐
                │            LangGraph Agent (Python)           │
                │                                               │
                │   Triage → Hypothesize → Plan/Exec → Evaluate│
                │       ▲                                 │     │
                │       └───────── loop if !confident ────┘     │
                │                                               │
                │   Tool Calls (HTTP/JSON)                      │
                └────────┬──────────┬──────────┬────────────────┘
                         │          │          │
                    ┌────▼────┐ ┌───▼───┐ ┌───▼───┐
                    │ K8s-MCP │ │Prom-  │ │Loki-  │
                    │ (Rust)  │ │MCP    │ │MCP    │
                    └────┬────┘ └───┬───┘ └───┬───┘
                         │          │          │
                    K8s API    Prometheus     Loki
```

### Agent Nodes

| Node | Responsibility |
|------|---------------|
| **Triage** | Connects to K8s-MCP for initial event scan; identifies affected resources and error patterns |
| **Hypothesize** | Generates competing theories (e.g., OOM, bad deploy, network partition); assigns initial confidence |
| **Plan & Execute** | Selects the single highest-value MCP tool call to disambiguate hypotheses; executes and extracts facts |
| **Evaluate** | Assesses evidence sufficiency; decides to terminate (confident) or loop (more data needed) |

### MCP Servers (Rust / Axum)

All three servers are stateless HTTP/JSON APIs deployed as Kubernetes pods in the `rca-agent` namespace:

- **K8s-MCP (port 3000):** `list_recent_events`, `get_pod_status`, `get_deployment_diff`, `check_network_policies`
- **Prometheus-MCP (port 3001):** `query_anomaly` with pre-built PromQL templates for CPU, memory, 5xx rate, DB connections
- **Loki-MCP (port 3002):** `fetch_error_logs` with built-in prompt-injection sanitization and security flagging

### Why Rust for MCP Servers?

- **Security:** No runtime code execution; compiled binaries with minimal attack surface
- **Deterministic queries:** PromQL and LogQL are pre-templated — the LLM cannot craft arbitrary queries
- **Performance:** Sub-millisecond response times; no garbage collection pauses

## 2. Tooling Design

### Pre-built Query Templates (Prometheus-MCP)

Rather than allowing free-form PromQL, the Prometheus-MCP exposes four pre-built metric types:

| Metric Type | PromQL Template | Purpose |
|------------|----------------|---------|
| `check_cpu_saturation` | `rate(container_cpu_usage_seconds_total{...}[5m]) / limits` | Detect CPU throttling |
| `check_memory_usage` | `container_memory_working_set_bytes{...} / limits * 100` | Detect OOM risk |
| `check_5xx_rate` | `rate(http_requests_total{status=~"5.."}[5m])` | Detect service errors |
| `check_db_connections` | `pg_stat_activity_count{...}` | Detect connection pool exhaustion |

Label matchers use regex (`=~`) for resilience against pod name variation.

### Name Sanitization (K8s-MCP & Loki-MCP)

The LLM sometimes extracts resource names with kind prefixes (e.g., `Pod/api-644ddc8555-5j47j`). All MCP clients strip these prefixes using regex before querying:

```python
clean_name = re.sub(r'^(?i)(pod|service|deployment|replicaset|statefulset)/', '', pod_name)
```

This prevents the `phase=unknown` failure mode where Kubernetes returns `None` for a pod literally named `Pod/api-...`.

### NetworkPolicy Inspection

The `check_network_policies` endpoint was added to enable the agent to distinguish between **symptom** (timeout) and **cause** (egress blocked by a NetworkPolicy). This is critical for Scenario 3 (Cascading Dependency Failure).

## 3. Causal Reasoning Design

### The "Symptom as Cause" Safeguard

The evaluation node's system prompt includes a **Causal Depth Mandate**:

> Never accept "network connectivity issue", "probe failure", or "timeout" as a final Root Cause. If a dependency fails readiness or times out, you MUST inspect:
> 1. That dependency's container status and exit code
> 2. Whether a NetworkPolicy was applied
> 3. Whether EndpointSlices for the service exist and have ready IPs

### Confidence Scoring

- High confidence (≥ 0.9) requires evidence from ≥ 2 different MCP sources
- Competing hypotheses must be explicitly refuted or have confidence ≥ 30% lower
- If competing hypotheses remain > 60% confident, the agent MUST report Medium/Low confidence

## 4. Security Model (Defense-in-Depth)

### Layer 1: RBAC

The `rca-agent-sa` ServiceAccount has **only** `get`, `list`, `watch` verbs. Zero write access, zero exec access.

```yaml
rules:
  - apiGroups: ["", "apps", "networking.k8s.io"]
    resources: [pods, events, deployments, replicasets, services,
                endpoints, configmaps, networkpolicies, endpointslices]
    verbs: ["get", "list", "watch"]
```

### Layer 2: Log Sanitization (Loki-MCP)

The Rust-based Loki-MCP server:
- Strips control characters (ASCII 0x00-0x1F)
- Truncates lines > 2048 characters
- Detects prompt injection patterns (e.g., `IGNORE PREVIOUS INSTRUCTIONS`, `kubectl delete`)
- Encapsulates logs in `---RAW LOG START---` / `---RAW LOG END---` delimiters
- Reports flagged injection attempts in a `security` metadata block

### Layer 3: Agent System Prompt

The agent's system prompt instructs it to treat all log content as **untrusted sensor data** and never execute embedded instructions.

### Layer 4: Network Isolation

MCP servers are deployed with NetworkPolicies restricting egress to only the K8s API, Prometheus, and Loki endpoints. No public internet access.

## 5. Reproducible Failure Scenarios

| # | Scenario | Trigger | Ground-Truth Root Cause | Multi-Source? |
|---|----------|---------|------------------------|--------------|
| 1 | Bad Deployment | `make trigger-bad-deploy` | Broken image exits (missing `DATABASE_ENCRYPTION_KEY`) | K8s events + Loki logs |
| 2 | OOMKilled | `make trigger-oom` | Memory limit (64Mi) exceeded under load | K8s exit codes + Prometheus memory |
| 3 | Cascading Failure | `make trigger-cascade` | NetworkPolicy blocks API→Postgres egress | Loki logs + K8s pod status + NetworkPolicy check |

Scenario 3 requires correlating **three** data sources: Loki logs show connection timeouts, K8s shows Postgres is healthy, and the NetworkPolicy check reveals the blocking rule.

## 6. Output Format

The RCA output includes all rubric-required fields:

| Field | Description |
|-------|-------------|
| `root_cause` | The identified root cause |
| `supporting_evidence` | Evidence supporting the conclusion |
| `timeline` | Chronological events observed during investigation |
| `confidence` | Level (high/medium/low) and numerical score |
| `alternative_explanations` | Competing hypotheses with their status and evidence |
| `recommended_action` | Suggested remediation |

## 7. Limitations

1. **No application-level instrumentation:** The workload pods don't export custom Prometheus metrics (e.g., `http_requests_total`), so 5xx rate detection relies on infrastructure-level signals.
2. **Single-tool-per-iteration:** The agent makes one MCP call per loop iteration for reasoning clarity, which increases investigation time.
3. **No distributed tracing:** The system does not integrate with Jaeger/Zipkin for trace-level analysis.
4. **LLM dependency:** Reasoning quality depends on the underlying LLM's ability to reason about infrastructure concepts.
5. **Static PromQL templates:** The Prometheus-MCP uses pre-built queries; novel metric patterns require code changes.

## 8. Future Work

- **Adaptive tool selection:** Use a learned policy to select MCP tools rather than LLM-based planning
- **Distributed tracing integration:** Add a Jaeger-MCP server for trace-level root cause analysis
- **Multi-cluster support:** Extend K8s-MCP to support federated cluster investigation
- **Automated remediation:** After RCA, propose and optionally execute remediation steps (with human approval)
- **Fine-tuned model:** Train a smaller model on historical RCA data to reduce latency and cost
- **Streaming output:** Stream investigation progress in real-time rather than batch at the end
