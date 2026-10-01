"""
LangGraph — Cyclic investigation graph assembly.

Implements the Triage → Hypothesize → Plan & Execute → Evaluate loop
with conditional edges for iterative investigation.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.state import AgentState
from agent.config import Config, get_config
from agent.nodes.triage import triage_node
from agent.nodes.hypothesize import hypothesize_node
from agent.nodes.plan_execute import plan_execute_node
from agent.nodes.evaluate import evaluate_node
from agent.formatter import format_rca_output, format_rca_json

logger = logging.getLogger(__name__)


def _get_llm(config: Config) -> Any:
    """Initialize the LLM based on configuration."""
    if config.llm_provider == "google":
        return ChatGoogleGenerativeAI(
            model=config.llm_model,
            google_api_key=config.google_api_key,
            temperature=0.1,
        )
    elif config.llm_provider == "openai":
        return ChatOpenAI(
            model=config.llm_model,
            api_key=config.openai_api_key,  # type: ignore
            temperature=0.1,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {config.llm_provider}")


def build_graph(config: Config | None = None) -> StateGraph:
    """
    Build the LangGraph investigation graph.

    Graph structure:
        triage → hypothesize → plan_execute → evaluate
                      ↑                            |
                      └────── (loop if not confident)
    """
    if config is None:
        config = get_config()

    llm = _get_llm(config)

    # ── Define node wrappers (bind config and llm) ──────────────────────

    async def _triage(state: AgentState) -> AgentState:
        return await triage_node(state, config, llm)

    async def _hypothesize(state: AgentState) -> AgentState:
        return await hypothesize_node(state, llm)

    async def _plan_execute(state: AgentState) -> AgentState:
        return await plan_execute_node(state, config, llm)

    async def _evaluate(state: AgentState) -> AgentState:
        return await evaluate_node(state, llm)

    # ── Build the graph ─────────────────────────────────────────────────

    graph = StateGraph(cast(Any, AgentState))

    graph.add_node("triage", _triage)
    graph.add_node("hypothesize", _hypothesize)
    graph.add_node("plan_execute", _plan_execute)
    graph.add_node("evaluate", _evaluate)

    # ── Define edges ────────────────────────────────────────────────────

    # Entry point
    graph.set_entry_point("triage")

    # Linear: triage → hypothesize → plan_execute → evaluate
    graph.add_edge("triage", "hypothesize")
    graph.add_edge("hypothesize", "plan_execute")
    graph.add_edge("plan_execute", "evaluate")

    # Conditional: evaluate → hypothesize (loop) OR END
    def should_continue(state: AgentState) -> str:
        if state["is_confident"]:
            logger.info("Investigation complete — agent is confident")
            return "end"
        if state["iteration"] >= state["max_iterations"]:
            logger.warning("Max iterations reached — forcing termination")
            return "end"
        logger.info(
            "Continuing investigation (iteration %d/%d)",
            state["iteration"],
            state["max_iterations"],
        )
        return "continue"

    graph.add_conditional_edges(
        "evaluate",
        should_continue,
        {
            "continue": "hypothesize",
            "end": END,
        },
    )

    return graph


async def investigate(incident: str, config: Config | None = None) -> str:
    """
    Run a full RCA investigation for the given incident.

    Args:
        incident: Description of the incident to investigate
        config: Optional configuration (uses defaults if not provided)

    Returns:
        Formatted RCA report string
    """
    if config is None:
        config = get_config()

    graph = build_graph(config)
    app = graph.compile()

    # Initialize state
    initial_state: AgentState = {
        "incident": incident,
        "timeline": [],
        "hypotheses": [],
        "observed_facts": [],
        "next_steps": "",
        "is_confident": False,
        "iteration": 0,
        "max_iterations": config.max_iterations,
        "mcp_call_log": [],
    }

    logger.info("Starting RCA investigation: %s", incident[:100])

    # Run the graph
    final_state = cast(AgentState, await app.ainvoke(initial_state))

    # Format the output
    report = format_rca_output(final_state)
    json_report = format_rca_json(final_state)

    logger.info("Investigation complete after %d iterations", final_state["iteration"])

    # Emit the JSON report as well
    import json as _json
    json_block = _json.dumps(json_report, indent=2, default=str)
    report += "\n\n## Structured JSON Report\n\n```json\n" + json_block + "\n```\n"

    return report


def run_investigation(incident: str, config: Config | None = None) -> str:
    """Synchronous wrapper for investigate()."""
    return asyncio.run(investigate(incident, config))


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    incident_desc = sys.argv[1] if len(sys.argv) > 1 else (
        "Multiple 5xx errors detected on the frontend service. "
        "Users are reporting the application is unavailable."
    )

    report = run_investigation(incident_desc)
    print(report)
