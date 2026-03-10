import asyncio
import sys

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.planners import PlanReActPlanner

from agent.runner import run_agent
from agent.config.config import (
    MODEL as _MODEL,
    code_programmer_skill,
    code_reviewer_skill,
    answer_agent_skill,
    orchestrator_skill,
    generic_scripts_skill,
    script_generator_skill,
    memory_agent_skill,
)
from tools.generate_tool import generate_script_with_genai
from tools.memory_agent_tool import retrieve_memory_context, save_interaction_memory
from tools.sandbox_gcp_tool import run_in_sandbox_gcp
from tools.script_execution_tool import execute_inline_script, execute_project_script, list_project_scripts



# ─── Code Programmer Agent ───────────────────────────────────────────────────
code_reviewer = AgentTool(agent=LlmAgent(name="code_reviewer",
                                        model=_MODEL,
                                        instruction=code_reviewer_skill.instructions) )

                                        
script_executor_agent = LlmAgent(
    name="generic_scripts_agent",
    model=_MODEL,
    instruction=generic_scripts_skill.instructions,
    tools=[list_project_scripts, execute_project_script, execute_inline_script],
)
script_executor = AgentTool(agent=script_executor_agent)

script_generator = AgentTool(agent=LlmAgent(
    name="script_generator_agent",
    model=_MODEL,
    instruction=script_generator_skill.instructions,
    tools=[list_project_scripts, generate_script_with_genai, execute_inline_script, script_executor],
))
                                        
code_programmer = LlmAgent(
    name="code_programmer",
    model=_MODEL,
    instruction=code_programmer_skill.instructions,
    planner=PlanReActPlanner(
         
    ),
    #code_executor=BuiltInCodeExecutor(),
    tools=[run_in_sandbox_gcp, 
           list_project_scripts, 
           execute_project_script, 
           execute_inline_script,
           code_reviewer, 
           script_executor,
            script_generator
           ],
    )

# ─── Answer Agent ────────────────────────────────────────────────────────────
answer_agent = LlmAgent(
    name="answer_agent",
    model=_MODEL,
    instruction=answer_agent_skill.instructions,
)

memory_agent = LlmAgent(
    name="memory_agent",
    model=_MODEL,
    instruction=memory_agent_skill.instructions,
    tools=[retrieve_memory_context, save_interaction_memory],
)


# ─── Orchestrator ─────────────────────────────────────────────────────────────
orchestrator = LlmAgent(
    name="orchestrator",
    model=_MODEL,
    instruction=orchestrator_skill.instructions,
    tools=[
        AgentTool(agent=memory_agent),
        AgentTool(agent=code_programmer),
        AgentTool(agent=answer_agent),
    ],
    # planner=BuiltInPlanner(
    #     thinking_config=types.ThinkingConfig(
    #         include_thoughts=False  # Show reasoning to user
    #     )
    # ),
)

async def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Calculate and print the first 10 Fibonacci numbers"
    print(f"Question: {question}\n")
    result = await run_agent(question, orchestrator)
    print(f"Answer:\n{result.get('response', '')}")
    print(f"Tool calls:\n{result.get('tool_calls', [])}")


if __name__ == "__main__":
    asyncio.run(main())