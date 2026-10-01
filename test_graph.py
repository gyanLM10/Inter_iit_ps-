import asyncio
from agent.graph import build_graph
from agent.config import get_config
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    config = get_config()
    config.llm_provider = "openai"
    config.max_iterations = 5
    graph = build_graph(config)
    app = graph.compile()
    
    initial_state = {
        "incident": "API pod crashing",
        "timeline": [],
        "hypotheses": [],
        "observed_facts": [],
        "next_steps": "",
        "is_confident": False,
        "iteration": 0,
        "max_iterations": 5,
        "mcp_call_log": [],
    }
    
    final_state = await app.ainvoke(initial_state)
    print("FINAL FACTS LENGTH:", len(final_state.get("observed_facts", [])))
    print("FINAL FACTS:", final_state.get("observed_facts"))

asyncio.run(main())
