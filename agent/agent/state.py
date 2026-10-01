"""
AgentState — The stateful data structure for the RCA investigation loop.
"""
from __future__ import annotations

from typing import Any, TypedDict


class Hypothesis(TypedDict):
    """A single hypothesis about the root cause."""
    theory: str
    confidence: float  # 0.0 to 1.0
    evidence: list[str]
    status: str  # "active", "confirmed", "refuted", "plausible"


class AgentState(TypedDict):
    """
    The state object passed through the LangGraph investigation loop.

    Fields:
        incident: Description of the incident being investigated.
        timeline: Chronological list of observed events.
        hypotheses: Competing theories about the root cause.
        observed_facts: Concrete, verified observations from MCP tools.
        next_steps: What the agent plans to investigate next.
        is_confident: True when root cause is identified with high confidence.
        iteration: Current iteration count.
        max_iterations: Maximum allowed iterations before forced termination.
        mcp_call_log: Log of all MCP tool calls made during investigation.
    """
    incident: str
    timeline: list[str]
    hypotheses: list[dict[str, Any]]
    observed_facts: list[str]
    next_steps: str
    is_confident: bool
    iteration: int
    max_iterations: int
    mcp_call_log: list[str]
