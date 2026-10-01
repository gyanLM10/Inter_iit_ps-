"""
Node 3: Plan & Execute — Decide which MCP tool to call next and execute.

Looks at the weakest hypothesis or missing evidence and decides which
MCP tool call would best disambiguate the competing theories.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from agent.state import AgentState
from agent.config import Config
from agent.tools.k8s_client import K8sMCPClient
from agent.tools.prometheus_client import PrometheusMCPClient
from agent.tools.loki_client import LokiMCPClient

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are the Investigation Planner of a Root Cause Analysis agent.

You have access to THREE read-only MCP tool servers:

2. K8s-MCP (Infrastructure):
   - list_recent_events(namespace) — Warning/error K8s events
   - get_pod_status(pod_name) — Container states, restart counts, exit codes
   - get_deployment_diff(deployment_name) — Compare current vs previous ReplicaSet
   - check_network_policies(namespace) — Check network policies in a namespace

3. Prometheus-MCP (Metrics):
   - query_anomaly(metric_type, resource_name) — Pre-built metric queries
     Valid metric_types: check_cpu_saturation, check_5xx_rate, check_db_connections, check_memory_usage

3. Loki-MCP (Logs):
   - fetch_error_logs(pod_name, time_window) — Sanitized error logs

Given the current hypotheses and evidence gaps, decide which SINGLE tool call
would provide the most diagnostic value. Pick the call that best distinguishes
between competing hypotheses.

Output ONLY valid JSON:
{
    "reasoning": "Why this tool call is the best next step",
    "tool_server": "k8s|prometheus|loki",
    "tool_name": "exact function name",
    "parameters": {
        "param_name": "value"
    }
}

RULES:
- Pick ONE tool call per iteration — be strategic
- Prioritize calls that can REFUTE or CONFIRM hypotheses, not just gather more of the same
- If you suspect OOMKill, check Prometheus memory before re-checking K8s events
- If you suspect config change, check deployment_diff
- If you suspect dependency failure, check logs for connection errors
- NEVER request a tool that doesn't exist — only use the exact names listed above"""


async def plan_execute_node(state: AgentState, config: Config, llm: Any) -> AgentState:
    """
    Plan & Execute node: Choose and execute the next MCP tool call.
    """
    logger.info("=== PLAN & EXECUTE NODE (Iteration %d) ===", state["iteration"])

    # Ask LLM to plan the next tool call
    context = f"""CURRENT HYPOTHESES:
{json.dumps(state['hypotheses'], indent=2)}

EVIDENCE GAPS / NEXT STEPS:
{state['next_steps']}

OBSERVED FACTS SO FAR:
{json.dumps(state['observed_facts'], indent=2)}

TOOLS ALREADY CALLED:
{json.dumps(state['mcp_call_log'], indent=2)}

TARGET NAMESPACE: {config.target_namespace}
"""

    messages = [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]

    try:
        response = await llm.ainvoke(messages)
        plan = _parse_json(response.content)

        if not plan:
            logger.warning("Could not parse plan from LLM, using fallback")
            state["observed_facts"].append("Plan node: failed to parse LLM plan")
            return state

        tool_server = plan.get("tool_server", "")
        tool_name = plan.get("tool_name", "")
        params = plan.get("parameters", {})

        logger.info("Planned: %s::%s(%s)", tool_server, tool_name, params)

        # Execute the planned tool call
        result = await _execute_tool_call(
            tool_server, tool_name, params, config
        )

        # Log the call
        state["mcp_call_log"].append(
            f"{tool_server}-MCP::{tool_name}({json.dumps(params)}) -> "
            f"{_summarize_result(result)}"
        )

        # Extract facts from the result
        new_facts = _extract_facts(tool_server, tool_name, result)
        state["observed_facts"].extend(new_facts)

        logger.info("Execution complete: %d new facts extracted", len(new_facts))

    except Exception as e:
        logger.error("Plan & Execute error: %s", e)
        state["observed_facts"].append(f"Plan & Execute error: {e}")

    return state


async def _execute_tool_call(
    tool_server: str, tool_name: str, params: dict, config: Config
) -> dict[str, Any]:
    """Execute a tool call against the specified MCP server."""

    if tool_server == "k8s":
        client = K8sMCPClient(config)
        try:
            if tool_name == "list_recent_events":
                return await client.list_recent_events(
                    params.get("namespace", config.target_namespace)
                )
            elif tool_name == "get_pod_status":
                return await client.get_pod_status(
                    params["pod_name"],
                    params.get("namespace", config.target_namespace),
                )
            elif tool_name == "get_deployment_diff":
                return await client.get_deployment_diff(
                    params["deployment_name"],
                    params.get("namespace", config.target_namespace),
                )
            elif tool_name == "check_network_policies":
                return await client.check_network_policies(
                    params.get("namespace", config.target_namespace)
                )
            else:
                return {"error": f"Unknown K8s-MCP tool: {tool_name}"}
        finally:
            await client.close()

    elif tool_server == "prometheus":
        prom_client = PrometheusMCPClient(config)
        try:
            if tool_name == "query_anomaly":
                return await prom_client.query_anomaly(
                    params["metric_type"],
                    params["resource_name"],
                    params.get("namespace", config.target_namespace),
                )
            else:
                return {"error": f"Unknown Prometheus-MCP tool: {tool_name}"}
        finally:
            await prom_client.close()

    elif tool_server == "loki":
        loki_client = LokiMCPClient(config)
        try:
            if tool_name == "fetch_error_logs":
                return await loki_client.fetch_error_logs(
                    params["pod_name"],
                    params.get("time_window", "15m"),
                    params.get("namespace", config.target_namespace),
                )
            else:
                return {"error": f"Unknown Loki-MCP tool: {tool_name}"}
        finally:
            await loki_client.close()

    else:
        return {"error": f"Unknown tool server: {tool_server}"}


def _summarize_result(result: dict) -> str:
    """Create a brief summary of a tool result for logging."""
    if "error" in result and result["error"]:
        return f"ERROR: {result['error']}"

    summaries = []
    if "total" in result:
        summaries.append(f"total={result['total']}")
    if "summary" in result:
        summaries.append(result["summary"][:100])
    if "diff_detected" in result:
        summaries.append(f"diff_detected={result['diff_detected']}")
    if "total_lines" in result:
        summaries.append(f"log_lines={result['total_lines']}")
    if "phase" in result:
        summaries.append(f"phase={result['phase']}")

    return ", ".join(summaries) if summaries else "OK"


def _extract_facts(tool_server: str, tool_name: str, result: dict) -> list[str]:
    """Extract concrete facts from a tool call result."""
    facts = []

    if "error" in result and result["error"]:
        facts.append(f"Tool call {tool_server}::{tool_name} returned error: {result['error']}")
        return facts

    if tool_server == "k8s":
        if tool_name == "list_recent_events":
            for event in result.get("events", [])[:10]:
                facts.append(
                    f"K8s Event [{event.get('timestamp', '?')}]: "
                    f"{event.get('reason', '?')} on {event.get('involved_object', '?')} — "
                    f"{event.get('message', '?')}"
                )
        elif tool_name == "get_pod_status":
            pod = result.get("pod_name", "unknown")
            phase = result.get("phase", "unknown")
            facts.append(f"Pod '{pod}' phase: {phase}")
            for c in result.get("containers", []):
                if c.get("restart_count", 0) > 0:
                    facts.append(
                        f"Container '{c['name']}' in '{pod}': "
                        f"{c['restart_count']} restarts, state={c.get('state', '?')}, "
                        f"exit_code={c.get('exit_code')}, "
                        f"last_term_reason={c.get('last_termination_reason')}"
                    )
        elif tool_name == "get_deployment_diff":
            if result.get("diff_detected"):
                for diff in result.get("diff_summary", []):
                    facts.append(f"Deployment diff: {diff}")
            else:
                facts.append(
                    f"No configuration changes detected for deployment '{result.get('deployment_name', '?')}'"
                )
        elif tool_name == "check_network_policies":
            if result.get("policies"):
                for policy in result.get("policies"):
                    facts.append(f"NetworkPolicy: {policy}")
            else:
                facts.append(f"No NetworkPolicies found in namespace '{result.get('namespace', '?')}'")

    elif tool_server == "prometheus":
        summary = result.get("summary", "")
        if summary:
            facts.append(f"Prometheus ({result.get('metric_type', '?')}): {summary}")

    elif tool_server == "loki":
        security = result.get("security", {})
        if security.get("contains_suspicious_content"):
            facts.append(
                f"⚠️ SECURITY: {security.get('flagged_injection_count', 0)} log lines "
                f"flagged as potential prompt injection in pod '{result.get('pod_name', '?')}'"
            )
        log_count = result.get("total_lines", 0)
        facts.append(
            f"Loki logs for pod '{result.get('pod_name', '?')}': "
            f"{log_count} error log lines retrieved"
        )
        # Extract key error patterns from logs (first 10 unique)
        seen = set()
        for line in result.get("logs", [])[:20]:
            # Deduplicate similar lines
            key = line[:80] if len(line) > 80 else line
            if key not in seen:
                seen.add(key)
                facts.append(f"Log: {line[:200]}")
            if len(seen) >= 10:
                break

    return facts


def _parse_json(content: str) -> dict | None:
    """Extract JSON from LLM response."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    for marker in ("```json", "```"):
        if marker in content:
            try:
                start = content.index(marker) + len(marker)
                end = content.index("```", start)
                text = content[start:end].strip()
                if text.startswith("\n"):
                    text = text[1:]
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
    return None
