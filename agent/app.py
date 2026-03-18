import asyncio
import sys
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from agent.runner import run_agent
from agent.config.config import (
    get_llm_provider,
    code_programmer_skill,
    answer_agent_skill,
    orchestrator_skill,
    generic_scripts_skill,
    script_generator_skill,
    memory_agent_skill,
    intent_router_skill,
    sd_agent_skill,
    fi_agent_skill,
    sap_technical_skill,
    cloudification_skill,
)
from agent.tools.sandbox import (
    generate_script,
    run_in_sandbox_gcp,
    execute_inline_script,
    execute_project_script,
    list_project_scripts,
)
from agent.tools.mcp.sap_cloudification_tools import build_cloudification_agent
from agent.tools.memory import retrieve_memory_context, save_interaction_memory


def build_orchestrator(llm_provider: str | None = None, model_name: str | None = None) -> LlmAgent:
    selected_model = get_llm_provider(llm_provider=llm_provider, model_name=model_name)

    intent_router = LlmAgent(
        name="intent_router",
        model=selected_model,
        instruction=intent_router_skill.instructions,
    )

    # ─── Code Programmer Agent ───────────────────────────────────────────────────
    script_executor_agent = LlmAgent(
        name="generic_scripts_agent",
        model=selected_model,
        instruction=generic_scripts_skill.instructions,
        tools=[list_project_scripts, execute_project_script, execute_inline_script],
    )
    script_executor = AgentTool(agent=script_executor_agent)

    script_generator = AgentTool(agent=LlmAgent(
        name="script_generator_agent",
        model=selected_model,
        instruction=script_generator_skill.instructions,
        tools=[list_project_scripts, generate_script, execute_inline_script, script_executor],
    ))

    code_programmer = LlmAgent(
        name="code_programmer",
        model=selected_model,
        instruction=code_programmer_skill.instructions,
        tools=[
            run_in_sandbox_gcp,
            list_project_scripts,
            execute_project_script,
            execute_inline_script,
            script_executor,
            script_generator,
        ],
    )

    # ─── Specialist Functional / Technical Agents ──────────────────────────────
    sd_agent = LlmAgent(
        name="sd_agent",
        model=selected_model,
        instruction=sd_agent_skill.instructions,
    )

    fi_agent = LlmAgent(
        name="fi_agent",
        model=selected_model,
        instruction=fi_agent_skill.instructions,
    )

    sap_technical_agent = LlmAgent(
        name="sap_technical_agent",
        model=selected_model,
        instruction=sap_technical_skill.instructions,
    )

    cloudification_agent = build_cloudification_agent(model=selected_model, skill=cloudification_skill)

    # ─── Answer Agent ────────────────────────────────────────────────────────────
    answer_agent = LlmAgent(
        name="answer_agent",
        model=selected_model,
        instruction=answer_agent_skill.instructions
    )

    memory_agent = LlmAgent(
        name="memory_agent",
        model=selected_model,
        instruction=memory_agent_skill.instructions,
        tools=[retrieve_memory_context, save_interaction_memory],
    )



    # ─── Orchestrator ─────────────────────────────────────────────────────────────
    return LlmAgent(
    name="orchestrator",
    model=selected_model,
    instruction=orchestrator_skill.instructions,
    tools=[
        AgentTool(agent=intent_router),
        AgentTool(agent=code_programmer),
        AgentTool(agent=sd_agent),          # ← directo al orchestrator
        AgentTool(agent=fi_agent),          # ← directo al orchestrator
        AgentTool(agent=sap_technical_agent), # ← directo al orchestrator
        AgentTool(agent=cloudification_agent), # ← directo al orchestrator
        AgentTool(agent=answer_agent),      # solo para respuestas generales
    ],
    )


# Keep a default orchestrator for existing imports/CLI usage.
orchestrator = build_orchestrator()

async def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Calculate and print the first 10 Fibonacci numbers"
    result = await run_agent(question, orchestrator)
 

if __name__ == "__main__":
    asyncio.run(main())