"""
Output Formatter — Produces the rigid RCA report structure.

Transforms the final AgentState into the exact output format specified
in the project requirements.  The output MUST include:
  1. Root cause
  2. Supporting evidence
  3. Relevant timeline
  4. Confidence level
  5. Alternative explanations (where applicable)
"""
from __future__ import annotations

from typing import Any

from agent.state import AgentState


def format_rca_output(state: AgentState) -> str:
    """
    Format the final investigation state into the required RCA report structure.

    Format:
        ROOT CAUSE ANALYSIS
        ├── Observed Facts
        ├── Hypotheses Considered
        ├── Evidence
        │   ├── Supporting Evidence
        │   └── Contradicting Evidence / Dead Ends
        ├── Conclusion (Root Cause)
        ├── Relevant Timeline
        ├── Alternative Explanations
        └── Uncertainty & Confidence
    """
    sections = []

    # ── Header ──────────────────────────────────────────────────────────
    sections.append("=" * 72)
    sections.append("ROOT CAUSE ANALYSIS")
    sections.append("=" * 72)
    sections.append("")

    # ── Observed Facts ──────────────────────────────────────────────────
    sections.append("## Observed Facts")
    sections.append("")
    fact_count = 0
    for fact in state["observed_facts"]:
        # Clean up facts — remove internal error messages and empty strings
        if fact and fact.strip() and not fact.startswith(("Triage error:", "Hypothesize error:", "Plan & Execute error:")):
            fact_count += 1
            sections.append(f"  {fact_count}. {fact.strip()}")
    
    if fact_count == 0:
        sections.append("  - No verifiable facts were explicitly extracted.")
    sections.append("")

    # ── Hypotheses Considered ───────────────────────────────────────────
    sections.append("## Hypotheses Considered")
    sections.append("")
    for hyp in state["hypotheses"]:
        theory = hyp.get("theory", "Unknown")
        status = hyp.get("status", "unknown").upper()
        confidence = hyp.get("confidence", 0)
        sections.append(f"  [{status}] {theory}")
        sections.append(f"    Confidence: {confidence:.0%}")
        evidence_list = hyp.get("evidence", [])
        if evidence_list:
            for ev in evidence_list:
                sections.append(f"    - {ev}")
        sections.append("")

    # ── Evidence ────────────────────────────────────────────────────────
    sections.append("## Evidence")
    sections.append("")

    # Supporting evidence = facts that support the highest-confidence hypothesis
    confirmed = [h for h in state["hypotheses"] if h.get("status") in ("confirmed", "active")]
    confirmed.sort(key=lambda h: h.get("confidence", 0), reverse=True)

    sections.append("### Supporting Evidence for Root Cause")
    if confirmed:
        top = confirmed[0]
        for ev in top.get("evidence", []):
            sections.append(f"  - {ev}")
    else:
        sections.append("  - Insufficient evidence to confirm a root cause")
    sections.append("")

    sections.append("### Contradicting Evidence / Dead Ends")
    refuted = [h for h in state["hypotheses"] if h.get("status") == "refuted"]
    if refuted:
        for hyp in refuted:
            sections.append(f"  - REFUTED: {hyp.get('theory', '?')}")
            for ev in hyp.get("evidence", []):
                sections.append(f"    - {ev}")
    else:
        sections.append("  - No hypotheses were explicitly refuted")
    sections.append("")

    # ── Conclusion ──────────────────────────────────────────────────────
    sections.append("## Conclusion (Root Cause)")
    sections.append("")
    if confirmed:
        top = confirmed[0]
        sections.append(f"  {top.get('theory', 'Unable to determine root cause')}")
    else:
        sections.append("  Unable to determine root cause with sufficient confidence.")
        sections.append("  The investigation was inconclusive.")
    sections.append("")

    # ── Relevant Timeline ──────────────────────────────────────────────
    sections.append("## Relevant Timeline")
    sections.append("")
    if state["timeline"]:
        for i, entry in enumerate(state["timeline"], 1):
            sections.append(f"  {i}. {entry}")
    else:
        sections.append("  - No chronological events were captured")
    sections.append("")

    # ── Alternative Explanations ───────────────────────────────────────
    sections.append("## Alternative Explanations")
    sections.append("")
    # Alternatives = all hypotheses that are NOT the top confirmed one
    top_hyp = confirmed[0] if confirmed else None
    alt_hypotheses = [
        h for h in state["hypotheses"]
        if h.get("status") in ("active", "plausible", "refuted")
        and h is not top_hyp
    ]
    if alt_hypotheses:
        for hyp in alt_hypotheses:
            status = hyp.get("status", "unknown").upper()
            theory = hyp.get("theory", "?")
            confidence = hyp.get("confidence", 0)
            sections.append(f"  [{status}] {theory} (confidence: {confidence:.0%})")
            evidence_list = hyp.get("evidence", [])
            if evidence_list:
                for ev in evidence_list:
                    sections.append(f"    - {ev}")
            sections.append("")
    else:
        sections.append("  - No alternative explanations were generated")
        sections.append("")

    # ── Uncertainty & Confidence ────────────────────────────────────────
    sections.append("## Uncertainty & Confidence")
    sections.append("")

    max_confidence = max(
        (h.get("confidence", 0) for h in state["hypotheses"]),
        default=0,
    )
    if max_confidence >= 0.9:
        level = "High"
    elif max_confidence >= 0.6:
        level = "Medium"
    else:
        level = "Low"

    sections.append(f"  Confidence Level: {level} ({max_confidence:.0%})")
    sections.append(f"  Iterations Used: {state['iteration']} / {state['max_iterations']}")
    sections.append("")

    # ── Investigation Log ───────────────────────────────────────────────
    sections.append("## Investigation Log (MCP Tool Calls)")
    sections.append("")
    for i, call in enumerate(state["mcp_call_log"], 1):
        sections.append(f"  {i}. {call}")
    sections.append("")
    sections.append("=" * 72)

    return "\n".join(sections)


def format_rca_json(state: AgentState) -> dict[str, Any]:
    """Return the RCA report as a structured JSON object.

    The schema satisfies the problem-statement rubric:
      root_cause, supporting_evidence, timeline,
      confidence, alternative_explanations.
    """
    confirmed = [h for h in state["hypotheses"] if h.get("status") in ("confirmed", "active")]
    confirmed.sort(key=lambda h: h.get("confidence", 0), reverse=True)
    refuted = [h for h in state["hypotheses"] if h.get("status") == "refuted"]

    max_confidence = max(
        (h.get("confidence", 0) for h in state["hypotheses"]),
        default=0,
    )

    # Build alternative explanations from non-primary hypotheses
    top = confirmed[0] if confirmed else None
    alt_explanations = []
    for h in state["hypotheses"]:
        if h is top:
            continue
        alt_explanations.append({
            "theory": h.get("theory", "?"),
            "status": h.get("status", "unknown"),
            "confidence": h.get("confidence", 0),
            "evidence": h.get("evidence", []),
        })

    return {
        "root_cause": top.get("theory", "Inconclusive") if top else "Inconclusive",
        "supporting_evidence": top.get("evidence", []) if top else [],
        "timeline": state["timeline"],
        "confidence": {
            "level": "high" if max_confidence >= 0.9 else "medium" if max_confidence >= 0.6 else "low",
            "score": max_confidence,
        },
        "alternative_explanations": alt_explanations,
        "recommended_action": _infer_action(top) if top else "Further investigation required.",
        "observed_facts": [
            f for f in state["observed_facts"]
            if not f.startswith(("Triage error:", "Hypothesize error:"))
        ],
        "contradicting_evidence": [
            {"theory": h.get("theory"), "evidence": h.get("evidence", [])}
            for h in refuted
        ],
        "iterations_used": state["iteration"],
        "mcp_call_log": state["mcp_call_log"],
    }


def _infer_action(hypothesis: dict[str, Any]) -> str:
    """Infer a recommended remediation from the top hypothesis."""
    theory = hypothesis.get("theory", "").lower()
    if "oom" in theory or "memory" in theory:
        return "Increase memory limits in the Deployment spec or profile the application for memory leaks."
    if "networkpolicy" in theory or "network policy" in theory or "egress" in theory:
        return "Review and update the offending NetworkPolicy to restore required connectivity."
    if "crashloop" in theory or "broken image" in theory or "config" in theory:
        return "Roll back the deployment to the previous known-good image/configuration."
    return "Investigate the identified root cause and apply appropriate remediation."
