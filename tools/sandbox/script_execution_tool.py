import json
import pathlib
import re
from difflib import SequenceMatcher
from tools.sandbox.sandbox_gcp_tool import run_in_sandbox_gcp

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"


def list_project_scripts() -> str:
    """List python scripts available under skills/*/scripts for script-first execution."""
    scripts = sorted(SKILLS_DIR.glob("*/scripts/*.py"))
    if not scripts:
        return "No scripts found under skills/*/scripts"

    lines = []
    for script in scripts:
        rel_path = script.relative_to(PROJECT_ROOT).as_posix()
        lines.append(rel_path)
    return "\n".join(lines)


def _run_script_source(script_source: str, script_label: str, args_json: str = "{}") -> str:
    try:
        parsed_args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as exc:
        return f"Invalid args_json: {exc}"

    if not isinstance(parsed_args, dict):
        return "args_json must decode to a JSON object"

    wrapped_code = f"""
import json
import sys

script_path = {script_label!r}
script_source = {script_source!r}
parsed_args = json.loads({json.dumps(json.dumps(parsed_args))})

argv = [script_path]
for key, value in parsed_args.items():
    flag = f"--{{str(key).replace('_', '-')}}"
    argv.append(flag)
    argv.append(str(value))

sys.argv = argv
namespace = {{"__name__": "__main__", "__file__": script_path}}
exec(compile(script_source, script_path, "exec"), namespace)
"""
    raw_output = run_in_sandbox_gcp(wrapped_code)
    try:
        payload = json.loads(raw_output)
        if isinstance(payload, dict) and "msg_out" in payload:
            return str(payload.get("msg_out", "")).strip()
    except json.JSONDecodeError:
        pass
    return raw_output.strip()


def execute_inline_script(script_source: str, args_json: str = "{}") -> str:
    """Execute Python source code directly in sandbox as __main__ without writing files."""
    if not script_source or not script_source.strip():
        return "script_source cannot be empty."
    return _run_script_source(script_source=script_source, script_label="inline_generated_script.py", args_json=args_json)


def execute_project_script(script_path: str, args_json: str = "{}") -> str:
    """Read and execute a project script in the sandbox as __main__ with CLI-style args."""
    target = (PROJECT_ROOT / script_path).resolve()

    try:
        target.relative_to(PROJECT_ROOT)
    except ValueError:
        return "Invalid script_path. It must be inside the project directory."

    if not target.exists() or target.suffix != ".py":
        return f"Script not found or not a Python file: {script_path}"

    script_source = target.read_text(encoding="utf-8")
    return _run_script_source(script_source=script_source, script_label=target.as_posix(), args_json=args_json)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_À-ÿ]+", text.lower()) if len(t) >= 3]


def _parse_script_tokens(script_path: pathlib.Path) -> list[str]:
    source = script_path.read_text(encoding="utf-8")
    path_tokens = _tokenize(script_path.stem.replace("_", " "))
    source_tokens = _tokenize(source)
    return sorted(set(path_tokens + source_tokens))


def _script_similarity(question: str, script_tokens: list[str]) -> tuple[float, float]:
    question_tokens = _tokenize(question)
    if not question_tokens or not script_tokens:
        return 0.0, 0.0

    best_scores = []
    for qtoken in question_tokens:
        best = max(SequenceMatcher(None, qtoken, stoken).ratio() for stoken in script_tokens)
        best_scores.append(best)

    max_score = max(best_scores)
    top_count = min(5, len(best_scores))
    mean_top = sum(sorted(best_scores, reverse=True)[:top_count]) / top_count
    return max_score, mean_top


def _extract_cli_arg_names(script_source: str) -> list[str]:
    matches = re.findall(r"add_argument\(\s*['\"]--([a-zA-Z0-9_-]+)['\"]", script_source)
    seen = set()
    ordered = []
    for item in matches:
        key = item.replace("-", "_")
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _extract_free_text_value(question: str) -> str | None:
    quoted = re.search(r"['\"]([^'\"]{2,})['\"]", question)
    if quoted:
        return quoted.group(1).strip()

    phrase = re.search(r"\b(?:en|in|for|de)\s+([A-Za-zÀ-ÿ0-9'\-\s]+?)(?:\?|\.|,|$)", question, flags=re.IGNORECASE)
    if phrase:
        value = phrase.group(1).strip()
        if value:
            return value
    return None


def _infer_args_from_question(question: str, arg_names: list[str]) -> dict[str, str]:
    if not arg_names:
        return {}

    inferred: dict[str, str] = {}
    numbers = re.findall(r"-?\d+(?:\.\d+)?", question)
    text_value = _extract_free_text_value(question)

    if len(arg_names) == 1:
        only_arg = arg_names[0]
        if text_value is not None:
            inferred[only_arg] = text_value
        elif numbers:
            inferred[only_arg] = numbers[0]
        return inferred

    numeric_hints = ("count", "num", "number", "size", "limit", "n")
    num_idx = 0
    for arg in arg_names:
        if num_idx < len(numbers) and any(h in arg.lower() for h in numeric_hints):
            inferred[arg] = numbers[num_idx]
            num_idx += 1

    if text_value is not None:
        for arg in arg_names:
            if arg not in inferred:
                inferred[arg] = text_value
                break

    return inferred


def maybe_execute_matching_script(question: str) -> str | None:
    scripts = sorted(SKILLS_DIR.glob("*/scripts/*.py"))
    if not scripts:
        return None

    best_script = None
    best_max = 0.0
    best_mean = 0.0

    for script in scripts:
        tokens = _parse_script_tokens(script)
        max_score, mean_top = _script_similarity(question, tokens)
        if (max_score, mean_top) > (best_max, best_mean):
            best_script = script
            best_max = max_score
            best_mean = mean_top

    # Require strong lexical affinity to avoid accidental matches.
    if best_script is None or best_max < 0.88:
        return None

    script_source = best_script.read_text(encoding="utf-8")
    arg_names = _extract_cli_arg_names(script_source)
    inferred_args = _infer_args_from_question(question, arg_names)
    rel = best_script.relative_to(PROJECT_ROOT).as_posix()
    return execute_project_script(rel, json.dumps(inferred_args))

    return None