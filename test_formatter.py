import json
from agent.formatter import format_rca_output

state = {
    "incident": "Test",
    "timeline": ["t1"],
    "hypotheses": [],
    "observed_facts": ["fact 1", "fact 2"],
    "next_steps": "",
    "is_confident": False,
    "iteration": 1,
    "max_iterations": 5,
    "mcp_call_log": ["call 1"]
}
print(format_rca_output(state))
