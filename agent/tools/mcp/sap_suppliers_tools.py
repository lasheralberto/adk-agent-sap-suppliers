import json
import os
import re
from typing import Any

from openai import OpenAI

DEFAULT_OPTION = "EQ"
DEFAULT_SIGN = "I"
NUMBER_WORDS_ES = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}

# Supported supplier fields from SAP LFA1 general data.
SUPPLIER_FIELDS = {
    "LIFNR": "Numero de cuenta del proveedor",
    "LAND1": "Clave de pais o region",
    "NAME1": "Nombre 1",
    "NAME2": "Nombre 2",
    "NAME3": "Nombre 3",
    "NAME4": "Nombre 4",
    "ORT01": "Poblacion",
    "ORT02": "Distrito",
    "PFACH": "Apartado",
    "PSTL2": "Codigo postal del apartado",
    "PSTLZ": "Codigo postal",
    "REGIO": "Region",
    "SORTL": "Campo de clasificacion",
    "STRAS": "Calle y numero",
    "ADRNR": "Direccion",
    "MCOD1": "Criterio de busqueda 1",
    "MCOD2": "Criterio de busqueda 2",
    "MCOD3": "Criterio de busqueda 3",
}
OPENAI_SUPPLIERS_MODEL = os.getenv("OPENAI_SUPPLIERS_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4"
OPENAI_SUPPLIERS_TIMEOUT_SECONDS = float(os.getenv("OPENAI_SUPPLIERS_TIMEOUT_SECONDS", "20"))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _resolve_provider(llm_provider: str | None = None) -> str:
    provider_raw = llm_provider if llm_provider else (os.getenv("LLM_PROVIDER") or os.getenv("LLM") or "")
    if not provider_raw:
        return ""
    return provider_raw.split("/", 1)[0].strip().lower()


def _infer_with_openai(question: str) -> dict[str, Any]:
    client = OpenAI(timeout=OPENAI_SUPPLIERS_TIMEOUT_SECONDS)
    fields = ", ".join(sorted(SUPPLIER_FIELDS.keys()))
    response = client.responses.create(
        model=OPENAI_SUPPLIERS_MODEL,
        input=(
            "Devuelve SOLO un JSON valido con las claves field, low, option, sign y limit para filtrar proveedores SAP LFA1. "
            f"field debe ser uno de: {fields}. "
            "option usa operadores SAP como EQ, CP, BT. "
            "sign debe ser I o E. "
            "limit debe ser un entero positivo cuando el usuario pida cantidad de registros (por ejemplo, 2 proveedores). Si no se pide cantidad explícitamente, devuelve null en limit."
            f"Pregunta del usuario: {question}"
        ),
    )

    raw = (response.output_text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI did not return valid JSON for suppliers query inference: {exc}") from exc

    inferred_field = _clean_text(str(parsed.get("field", ""))).upper()
    inferred_low = _clean_text(str(parsed.get("low", "")))
    inferred_option = _normalize_option(str(parsed.get("option", DEFAULT_OPTION)))
    inferred_sign = _normalize_sign(str(parsed.get("sign", DEFAULT_SIGN)))
    inferred_limit = _normalize_limit(parsed.get("limit"))

    if inferred_field and inferred_field not in SUPPLIER_FIELDS:
        raise ValueError(
            f"OpenAI returned invalid field '{inferred_field}'. Allowed fields: {', '.join(sorted(SUPPLIER_FIELDS.keys()))}"
        )

    return {
        "field": inferred_field,
        "low": inferred_low,
        "option": inferred_option,
        "sign": inferred_sign,
        "limit": inferred_limit,
    }


def _normalize_option(option: str | None) -> str:
    opt = (option or DEFAULT_OPTION).strip().upper()
    return opt if opt else DEFAULT_OPTION


def _normalize_sign(sign: str | None) -> str:
    normalized = (sign or DEFAULT_SIGN).strip().upper()
    return normalized if normalized in {"I", "E"} else DEFAULT_SIGN


def _normalize_limit(limit: Any) -> int | None:
    if limit is None:
        return None

    if isinstance(limit, bool):
        return None

    if isinstance(limit, int):
        return limit if limit > 0 else None

    text = _clean_text(str(limit))
    if not text:
        return None

    if text.isdigit():
        parsed = int(text)
        return parsed if parsed > 0 else None

    return NUMBER_WORDS_ES.get(text.lower())


def _extract_limit_from_question(question: str) -> int | None:
    clean_question = _clean_text(question).lower()
    if not clean_question:
        return None

    match = re.search(r"\b(\d+)\b", clean_question)
    if match:
        return _normalize_limit(match.group(1))

    for word, value in NUMBER_WORDS_ES.items():
        if re.search(rf"\b{word}\b", clean_question):
            return value

    return None


def build_suppliers_query_payload(
    question: str,
    low: str | None = None,
    field: str | None = None,
    option: str | None = None,
    sign: str | None = None,
    limit: int | str | None = None,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    clean_question = _clean_text(question)
    selected_field = (field or "").strip().upper()
    selected_low = _clean_text(low or "")

    inferred_option = _normalize_option(option)
    inferred_sign = _normalize_sign(sign)
    selected_limit = _normalize_limit(limit) or _extract_limit_from_question(clean_question)

    provider = _resolve_provider(llm_provider)
    if provider == "openai" and (not selected_field or not selected_low):
        inferred = _infer_with_openai(clean_question)
        if not selected_field:
            selected_field = inferred["field"] or "NAME1"
        if not selected_low:
            selected_low = inferred["low"]
        if not option:
            inferred_option = inferred["option"]
        if not sign:
            inferred_sign = inferred["sign"]
        if selected_limit is None:
            selected_limit = inferred.get("limit")


    if not selected_field:
        selected_field = "NAME1"

    if selected_field not in SUPPLIER_FIELDS:
        raise ValueError(f"Invalid field '{selected_field}'. Allowed fields: {', '.join(sorted(SUPPLIER_FIELDS.keys()))}")

    if not selected_low:
        if selected_limit is not None:
            selected_low = "*"
            if not option:
                inferred_option = "CP"
        elif provider == "openai":
            raise ValueError("OpenAI could not infer a filter value (low) from question. Provide low explicitly.")
        else:
            raise ValueError("Missing filter value (low). Provide low explicitly.")

    query_arg = {
        "low": selected_low,
        "option": inferred_option,
        "sign": inferred_sign,
    }
    if selected_limit is not None:
        query_arg["limit"] = selected_limit

    payload = {
        "question": clean_question,
        "query": {
            "field": selected_field,
            "args": [query_arg],
        },
    }
    return payload


def prepare_suppliers_query(
    question: str,
    low: str = "",
    field: str = "",
    option: str = DEFAULT_OPTION,
    sign: str = DEFAULT_SIGN,
    limit: str = "",
    llm_provider: str = "",
) -> str:
    """Build a structured SAP suppliers query from natural language input."""
    try:
        payload = build_suppliers_query_payload(
            question=question,
            low=low,
            field=field,
            option=option,
            sign=sign,
            limit=limit,
            llm_provider=llm_provider,
        )
        return json.dumps(payload, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
