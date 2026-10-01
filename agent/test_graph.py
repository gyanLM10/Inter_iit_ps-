import asyncio
from agent.graph import build_graph
from agent.config import Config

async def main():
    config = Config(google_api_key="dummy")
    graph = build_graph(config)
    print("Graph built.")
    app = graph.compile()
    print("Graph compiled.")

if __name__ == "__main__":
    asyncio.run(main())
