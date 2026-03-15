import os

import vertexai
from dotenv import load_dotenv
from vertexai._genai import types

load_dotenv()

SANDBOX_DISPLAY_NAME = os.environ["SANDBOX_DISPLAY_NAME"]
AGENT_ENGINE_DISPLAY_NAME = os.environ["AGENT_ENGINE_DISPLAY_NAME"]
PROJECT_ID = os.environ["PROJECT_ID"]
LOCATION = os.environ["LOCATION"]
CLIENT = None
_CACHED_AGENT_ENGINE_NAME = None
_CACHED_SANDBOX_NAME = None


def init_client():
    """Initializes the Vertex AI client."""
    global CLIENT
    if CLIENT is None:
        CLIENT = vertexai.Client(project=PROJECT_ID, location=LOCATION)


def list_or_create_agent_engine() -> str:
    """Returns the agent engine resource name, creating one if it doesn't exist."""
    global _CACHED_AGENT_ENGINE_NAME

    if _CACHED_AGENT_ENGINE_NAME:
        return _CACHED_AGENT_ENGINE_NAME

    agent_engines = CLIENT.agent_engines.list()

    for engine in agent_engines:
        engine_display_name = getattr(getattr(engine, "api_resource", None), "display_name", None)
        engine_name = getattr(getattr(engine, "api_resource", None), "name", None)
        print(f"Checking agent engine: {engine_display_name or engine_name}")
        if engine_display_name == AGENT_ENGINE_DISPLAY_NAME and engine_name:
            print(f"Agent engine found: {engine_name}")
            _CACHED_AGENT_ENGINE_NAME = engine_name
            return engine_name

    print("Agent engine not found. Creating a new agent engine...")
    agent_engine = CLIENT.agent_engines.create(config={"display_name": AGENT_ENGINE_DISPLAY_NAME})
    agent_engine_name = agent_engine.api_resource.name
    print("Created agent engine:", agent_engine_name)
    _CACHED_AGENT_ENGINE_NAME = agent_engine_name
    return agent_engine_name


def create_sandbox(agent_engine_name: str) -> str:
    """Creates a new sandbox under the given agent engine and returns its name."""
    operation = CLIENT.agent_engines.sandboxes.create(
        name=agent_engine_name,
        spec={
            "code_execution_environment": {
                "code_language": "LANGUAGE_PYTHON",
                "machine_config": "MACHINE_CONFIG_VCPU4_RAM4GIB",
            }
        },
        config=types.CreateAgentEngineSandboxConfig(
            display_name=SANDBOX_DISPLAY_NAME,
            ttl="3600s",
        ),
    )

    operation_name = getattr(operation, "name", None)
    if operation_name:
        print("Sandbox operation:", operation_name)

    if operation.response and getattr(operation.response, "name", None):
        return operation.response.name

    raise ValueError("Sandbox creation completed without a response name.")


def list_or_create_sandbox(agent_engine_name: str) -> str:
    """Returns the sandbox name, creating one if it doesn't exist."""
    global _CACHED_SANDBOX_NAME

    if _CACHED_SANDBOX_NAME:
        return _CACHED_SANDBOX_NAME

    sandboxes = CLIENT.agent_engines.sandboxes.list(name=agent_engine_name)

    for sandbox in sandboxes:
        print(f"Checking sandbox: {sandbox.display_name}")
        if sandbox.display_name == SANDBOX_DISPLAY_NAME:
            print(f"Sandbox found: {sandbox.name}")
            _CACHED_SANDBOX_NAME = sandbox.name
            return sandbox.name

    print("Sandbox not found. Creating a new sandbox...")
    _CACHED_SANDBOX_NAME = create_sandbox(agent_engine_name)
    return _CACHED_SANDBOX_NAME


def run_in_sandbox_gcp(code: str) -> str:
    """Execute Python code in a GCP Vertex AI sandbox and return the stdout output."""
    global _CACHED_SANDBOX_NAME

    init_client()
    agent_engine_name = list_or_create_agent_engine()
    sandbox_name = list_or_create_sandbox(agent_engine_name)

    try:
        print(f"Executing code in sandbox: {code}")
        response = CLIENT.agent_engines.sandboxes.execute_code(
            name=sandbox_name,
            input_data={"code": code},
        )
    except Exception as exc:
        # Sandbox resources can expire; clear only sandbox cache and retry once.
        error_text = str(exc).lower()
        if any(token in error_text for token in ("not found", "404", "expired")):
            _CACHED_SANDBOX_NAME = None
            sandbox_name = list_or_create_sandbox(agent_engine_name)
            response = CLIENT.agent_engines.sandboxes.execute_code(
                name=sandbox_name,
                input_data={"code": code},
            )
        else:
            raise

    output_parts = []
    for chunk in (response.outputs or []):
        if chunk.data:
            output_parts.append(chunk.data.decode("utf-8", errors="replace"))

    return "\n".join(output_parts)


# if __name__ == "__main__":
#     print(run_in_sandbox("print('Hello from the sandbox!')"))