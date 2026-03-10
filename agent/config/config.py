import os
import pathlib

from dotenv import load_dotenv
from google.adk.skills import load_skill_from_dir
from google.adk.models.lite_llm import LiteLlm
from tools.sandbox_gcp_tool import LOCATION, PROJECT_ID

load_dotenv()

_SKILLS_DIR = pathlib.Path(__file__).parent.parent.parent / "skills"


def _configure_vertex_backend() -> None:
    """Configure ADK/GenAI clients to use Vertex AI instead of API key mode."""
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", LOCATION)


_configure_vertex_backend()

# ─── Load skills ──────────────────────────────────────────────────────────────
code_programmer_skill = load_skill_from_dir(_SKILLS_DIR / "code-programmer")
code_reviewer_skill = load_skill_from_dir(_SKILLS_DIR / "code-reviewer")
answer_agent_skill = load_skill_from_dir(_SKILLS_DIR / "answer-agent")
orchestrator_skill = load_skill_from_dir(_SKILLS_DIR / "orchestrator")
generic_scripts_skill = load_skill_from_dir(_SKILLS_DIR / "script-execution")
script_generator_skill = load_skill_from_dir(_SKILLS_DIR / "script-generator")
memory_agent_skill = load_skill_from_dir(_SKILLS_DIR / "memory-agent")


def get_llm_provider() -> LiteLlm:
    provider = os.getenv("LLM_PROVIDER").lower()
    if provider not in {"google", "azure", "openai"}:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    if provider == "google":
        os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
        model = LiteLlm(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    elif provider == "openai":
        os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
        model = LiteLlm(model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"))
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    return model


MODEL = get_llm_provider()
