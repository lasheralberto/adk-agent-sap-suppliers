from llm_sandbox import SandboxSession


def run_in_sandbox(code: str) -> str:
    """Execute Python code in an isolated Docker sandbox and return the stdout output."""
    with SandboxSession(image="python:3.9.19-bullseye", keep_template=True, lang="python") as session:
        result = session.run(code)
        print("Sandbox execution code:", code)
        return str(result)
