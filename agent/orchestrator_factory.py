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
    suppliers_skill,
)
from agent.tools.sandbox import (
    generate_script,
    run_in_sandbox_gcp,
    execute_inline_script,
    execute_project_script,
    list_project_scripts,
)
 
from agent.tools.mcp.sap_suppliers_tools import prepare_suppliers_query
from agent.tools.memory import retrieve_memory_context, save_interaction_memory



def build_orchestrator(llm_provider: str | None = None, model_name: str | None = None) -> LlmAgent:
    selected_model = get_llm_provider(llm_provider=llm_provider, model_name=model_name)

    intent_router = LlmAgent(
        name="intent_router",
        model=selected_model,
        instruction=intent_router_skill.instructions,
    )
  
    answer_agent = LlmAgent(
        name="answer_agent",
        model=selected_model,
        instruction=answer_agent_skill.instructions
    )

    suppliers_agent = LlmAgent(
        name="suppliers_agent",
        model=selected_model,
        instruction=suppliers_skill.instructions,
        tools=[prepare_suppliers_query],
    )

    return LlmAgent(
        name="orchestrator",
        model=selected_model,
        instruction=orchestrator_skill.instructions,
        #sub_agents=[intent_router, answer_agent, suppliers_agent]
        tools=[
            AgentTool(agent=intent_router),
            AgentTool(agent=suppliers_agent),
            AgentTool(agent=answer_agent),
        ],
    )


def build_default_orchestrator() -> LlmAgent | None:
    provider = (os.getenv("LLM_PROVIDER") or os.getenv("LLM") or "").strip()
    if not provider:
        return None
    return build_orchestrator()