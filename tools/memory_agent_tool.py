from tools.memory.memory_store import retrieve_similar_memories, save_memory


def retrieve_memory_context(question: str, top_k: int = 3) -> str:
    """Fetch relevant memories and return a prompt-safe memory block."""
    if not question or not question.strip():
        return ""

    safe_top_k = top_k if isinstance(top_k, int) and top_k > 0 else 3
    memories = retrieve_similar_memories(question, top_k=safe_top_k)
    if not memories:
        return ""

    lines = ["[Memorias similares de conversaciones anteriores]"]
    for index, memory in enumerate(memories, start=1):
        lines.append(f"{index}. {memory}")

    lines.extend(
        [
            "",
            "[Instrucciones de continuidad]",
            "- Usa estas memorias solo si aportan valor a la pregunta actual.",
            "- Si son relevantes, integra continuidad de forma natural.",
            "- Si no aplican, ignorarlas por completo.",
        ]
    )
    print(f"Constructed memory context for question: {question}\nContext:\n{lines}")
    return "\n".join(lines)


def save_interaction_memory(question: str, final_answer: str) -> str:
    """Persist a concise conversation memory using the configured memory provider."""
    if not question or not question.strip() or not final_answer or not final_answer.strip():
        return "memory_saved=false reason=empty_input"

    saved = save_memory(question, final_answer)
    if saved:
        return "memory_saved=true"
    return "memory_saved=false reason=backend_unavailable"
