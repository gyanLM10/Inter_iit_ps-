"""
Node 4: Evaluate — Assess evidence and decide whether to terminate.

Evaluates whether the accumulated evidence is sufficient to identify the
root cause with high confidence, or whether the loop should continue.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from agent.state import AgentState

logger = logging.getLogger(__name__)

EVALUATE_SYSTEM_PROMPT = """You are the Evaluation module of a Root Cause Analysis agent.

You will receive the full investigation state including all observed facts,
hypotheses, and the MCP tool call log.

Your job is to:
1. Assess whether the evidence is SUFFICIENT to identify the root cause
2. Check if a hypothesis has reached HIGH CONFIDENCE (>= 0.9)
3. Verify that high-confidence conclusions are backed by AT LEAST 2 different data sources
   (e.g., K8s events + Prometheus metrics, or K8s events + Loki logs)
4. Check if competing hypotheses have been adequately addressed

Output ONLY valid JSON:
{
    "is_confident": true/false,
    "confidence_level": "high|medium|low",
    "root_cause_hypothesis": "the theory you're most confident about (or null)",
    "reasoning": "Explain why you are/aren't confident",
    "data_sources_used": ["list of distinct MCP sources that support the conclusion"],
    "remaining_ambiguity": "What's still unclear, if anything",
    "should_continue": true/false,
    "next_investigation_focus": "What to investigate next if continuing"
}

TERMINATION CRITERIA:
- Set is_confident=true ONLY when:
  a) A hypothesis has confidence >= 0.9
  b) Evidence comes from at least 2 different MCP sources
  c) Competing hypotheses are explicitly refuted or have a confidence score AT LEAST 30% lower than the primary hypothesis. If competing hypotheses remain >60% confident, you MUST conclude with Medium or Low confidence and state the root cause as "Ambiguous pending further inspection".
- RULE: Never accept "network connectivity issue", "probe failure", or "timeout" as a final Root Cause. 
  If a dependency (e.g. Postgres) fails readiness or times out, you MUST inspect:
  1. That dependency's container status and exit code.
  2. Whether a NetworkPolicy was applied.
  3. Whether EndpointSlices for the service exist and have ready IPs.
- Set should_continue=false when confident OR when further investigation won't help
- Always set should_continue=false if this is the last allowed iteration"""


async def evaluate_node(state: AgentState, llm: Any) -> AgentState:
    """
    Evaluate node: Assess evidence sufficiency and termination.
    """
    logger.info("=== EVALUATE NODE (Iteration %d) ===", state["iteration"])

    is_last_iteration = state["iteration"] >= state["max_iterations"]

    context = f"""INCIDENT:
{state['incident']}

OBSERVED FACTS ({len(state['observed_facts'])} total):
{json.dumps(state['observed_facts'], indent=2)}

CURRENT HYPOTHESES:
{json.dumps(state['hypotheses'], indent=2)}

TIMELINE:
{json.dumps(state['timeline'], indent=2)}

MCP TOOL CALLS ({len(state['mcp_call_log'])} total):
{json.dumps(state['mcp_call_log'], indent=2)}

ITERATION: {state['iteration']} / {state['max_iterations']}
{'⚠️ THIS IS THE LAST ITERATION — you MUST provide your best conclusion.' if is_last_iteration else ''}
"""

    messages = [
        SystemMessage(content=EVALUATE_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]

    try:
        response = await llm.ainvoke(messages)
        evaluation = _parse_json(response.content)

        if evaluation:
            is_confident = evaluation.get("is_confident", False)
            should_continue = evaluation.get("should_continue", True)

            # Force termination on last iteration
            if is_last_iteration:
                should_continue = False
                if not is_confident:
                    logger.warning("Max iterations reached — forcing conclusion")

            state["is_confident"] = is_confident or not should_continue
            state["next_steps"] = evaluation.get(
                "next_investigation_focus",
                "No further investigation planned"
            )

            logger.info(
                "Evaluation: confident=%s, should_continue=%s, level=%s",
                is_confident,
                should_continue,
                evaluation.get("confidence_level", "unknown"),
            )
        else:
            # If we can't parse the evaluation, check if we should force-stop
            if is_last_iteration:
                state["is_confident"] = True
                logger.warning("Max iterations reached and eval failed — force terminating")

    except Exception as e:
        logger.error("Evaluate node error: %s", e)
        if is_last_iteration:
            state["is_confident"] = True

    # Always increment the iteration counter at the end of each loop
    state["iteration"] += 1

    return state


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
