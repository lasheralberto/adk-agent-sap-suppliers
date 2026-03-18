import asyncio
import sys

from agent.runner import run_agent
from agent.orchestrator_factory import build_orchestrator, build_default_orchestrator


# Keep a best-effort default orchestrator for imports/CLI usage.
# In Cloud Run, requests provide provider/model per payload, so import-time
# initialization must not fail when env vars are missing.
orchestrator = build_default_orchestrator()

async def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Calculate and print the first 10 Fibonacci numbers"
    active_orchestrator = orchestrator or build_orchestrator()
    result = await run_agent(question, active_orchestrator)
 

if __name__ == "__main__":
    asyncio.run(main())