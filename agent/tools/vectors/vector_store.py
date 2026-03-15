import os
from openai import OpenAI
from typing import Optional, Any

from agent.tools.vectors.providers.provider_wrapper import ProviderWrapper


def _get_client(api_key: Optional[str] = None) -> OpenAI:
    """Factory to lazily create an OpenAI client. Avoids creating the client
    at import time which can cause side-effects and slow imports.
    """
    return OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))


def extract_and_vectorize(
    text: str,
    provider: str = "pinecone",
    model_id: str = "gpt-4o-mini",
    api_key: Optional[str] = None
) -> Any:
    """
    Usa el ProviderWrapper con langextract para extraer entidades/relaciones
    de un texto y luego los guarda en el vector store (vía su método set).
    """
    # 1. Extraer conocimiento estructurado usando langextract
    lx_wrapper = ProviderWrapper("langextract", config={
        "model_id": model_id,
        "api_key": api_key
    })
    
    # Realizamos la extracción
    extraction = lx_wrapper.search(text)
    
    # 2. Guardar en el vector store destino (por defecto pinecone)
    # Usamos el texto original como key o un hash del mismo
    target_wrapper = ProviderWrapper(provider, config={"api_key": api_key})
    
    # Guardamos los resultados estructurados
    # Nota: El provider de Pinecone/OpenAI espera un valor que pueda convertir a texto
    target_wrapper.set(key=text[:50], value={
        "answer_summary": str(extraction),
        "source_text": text
    })
    
    return extraction


def attach(file_path: str, vector_store_id: Optional[str] = None) -> dict:
    """Upload a local file to the vector store. If vector_store_id is None,
    read it from the environment variable VECTOR_STORE_ID.

    Returns a dict with result info or raises an exception on failure.
    """
    if not vector_store_id:
        vector_store_id = os.environ.get("VECTOR_STORE_ID")

    if not vector_store_id:
        raise ValueError("vector_store_id not provided and VECTOR_STORE_ID not set in environment")

    client = _get_client()
    vector_store = client.vector_stores.retrieve(
        vector_store_id=vector_store_id
    )

    if vector_store is None:
        raise ValueError(f"Vector store with ID {vector_store_id} not found.")

    # Ensure file exists
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        resp = client.vector_stores.files.upload_and_poll(
            vector_store_id=vector_store.id,
            file=f
        )

    return {"status": "ok", "response": resp}


def search_vs(query: str, vector_store_id: Optional[str] = None, top_k: int = 3) -> dict:
    """
    Realiza una búsqueda RAG avanzada en el Vector Store de OpenAI.
    Extrae el contenido de texto de los resultados y los concatena como contexto.
    Retorna un diccionario con 'context' (string) y 'filenames' (lista).
    """
    if not vector_store_id:
        vector_store_id = os.environ.get("VECTOR_STORE_ID")

    if not vector_store_id:
        return {"context": "", "filenames": []}

    try:
        client = _get_client()
        results = client.vector_stores.search(
            vector_store_id=vector_store_id,
            query=query
        )

        context_parts = []
        filenames = []
        
        if hasattr(results, "data") and results.data:
            for entry in results.data:
                # Filtrar por score menor a 0.5
                score = getattr(entry, 'score', 0)
                if score < 0.5:
                    continue

                fname = getattr(entry, 'filename', 'Desconocido')
                if fname not in filenames:
                    filenames.append(fname)
                
                if hasattr(entry, "content") and entry.content:
                    for item in entry.content:
                        text_content = ""
                        if hasattr(item, "text") and item.text:
                            text_content = item.text
                            if isinstance(text_content, object) and hasattr(text_content, "value"):
                                text_content = text_content.value
                        elif isinstance(item, dict) and item.get("type") == "text":
                            text_content = item.get("text")
                        
                        if text_content:
                            context_parts.append(f"--- Documento: {fname} ---\n{text_content}")

        return {
            "context": "\n\n".join(context_parts),
            "filenames": filenames
        }
    except Exception as e:
        print(f"Error en search_vs RAG: {str(e)}")
        return {"context": "", "filenames": []}
    