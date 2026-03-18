import os

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

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
 
    cloudification_agent = build_cloudification_agent(model=selected_model, skill=cloudification_skill)

    answer_agent = LlmAgent(
        name="answer_agent",
        model=selected_model,
        instruction=answer_agent_skill.instructions
    )

    return LlmAgent(
        name="orchestrator",
        model=selected_model,
        instruction=orchestrator_skill.instructions,
        tools=[
            AgentTool(agent=intent_router),
            # AgentTool(agent=code_programmer),
            AgentTool(agent=cloudification_agent),
            AgentTool(agent=answer_agent),
        ],
    )


def build_default_orchestrator() -> LlmAgent | None:
    provider = (os.getenv("LLM_PROVIDER") or os.getenv("LLM") or "").strip()
    if not provider:
        return None
    return build_orchestrator()