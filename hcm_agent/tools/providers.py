"""Semantic LangChain/Chroma retrieval over Clara's fictional provider directory."""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

PROVIDER_DIRECTORY_ID = "clara-fictional-provider-directory"
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "provider_directory.json"
VECTOR_DIR = Path(os.environ.get(
    "CLARA_PROVIDER_VECTOR_DIR",
    str(Path(__file__).resolve().parents[2] / "data" / "vectorstore" / "provider-directory"),
))


def _directory(path: Path) -> dict[str, Any] | None:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(source, dict) or source.get("source_status") != "active":
        return None
    return source


def load_provider_documents(path: Path = DEFAULT_DIRECTORY) -> list:
    """Make one richly described LangChain document per fictional directory record."""
    from langchain_core.documents import Document

    source = _directory(path)
    providers = source.get("providers", []) if source else []
    documents = []
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("active") is not True:
            continue
        specialties = provider.get("specialties", [])
        specialties = specialties if isinstance(specialties, list) else []
        content = "\n".join((
            f"Provider name: {provider.get('display_name', '')}",
            f"Specialties: {', '.join(str(item) for item in specialties)}",
            f"Area: {provider.get('area', '')}",
            f"City and state: {provider.get('city', '')}, {provider.get('state', '')}",
            f"Address: {provider.get('address', '')}",
            f"Accepting new patients: {provider.get('accepting_new_patients')}",
            f"Directory note: {source.get('directory_note', '')}",
        ))
        documents.append(Document(page_content=content, metadata={
            "provider_id": str(provider.get("provider_id", "")),
            "display_name": str(provider.get("display_name", "")),
            "specialties": "; ".join(str(item) for item in specialties),
            "area": str(provider.get("area", "")), "city": str(provider.get("city", "")),
            "state": str(provider.get("state", "")), "address": str(provider.get("address", "")),
            "rating": float(provider.get("rating", 0)),
            "rating_context": str(provider.get("rating_context", "")),
            "phone": str(provider.get("phone", "")),
            "accepting_new_patients": provider.get("accepting_new_patients") is True,
            "is_fictional_demo": provider.get("is_fictional_demo") is True,
            "directory_as_of": str(source.get("as_of", "")),
        }))
    return documents


def _dependencies():
    try:
        from fastembed import TextEmbedding  # noqa: F401
        from langchain_chroma import Chroma
        from langchain_community.embeddings import FastEmbedEmbeddings
    except ImportError as error:
        raise RuntimeError("Provider RAG dependencies are missing; install requirements.txt") from error
    return Chroma, FastEmbedEmbeddings


def build_provider_index(*, rebuild: bool = False):
    """Build/open the local Chroma collection for the fictional provider directory."""
    documents = load_provider_documents()
    if not documents:
        raise ValueError(f"No active providers found at {DEFAULT_DIRECTORY}")
    Chroma, FastEmbedEmbeddings = _dependencies()
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    if (VECTOR_DIR / "chroma.sqlite3").exists():
        store = Chroma(collection_name=PROVIDER_DIRECTORY_ID, embedding_function=embeddings,
                       persist_directory=str(VECTOR_DIR))
        if not rebuild and store._collection.count():
            return store
        store.delete_collection()
    return Chroma.from_documents(documents, embeddings, collection_name=PROVIDER_DIRECTORY_ID,
                                 persist_directory=str(VECTOR_DIR))


@lru_cache(maxsize=1)
def get_provider_vector_store():
    """Open or lazily build the local provider Chroma index."""
    return build_provider_index()


def _semantic_query(arguments: dict[str, Any]) -> str:
    parts = [
        f"Provider name requested: {arguments.get('provider_name', '')}",
        f"Specialty requested: {arguments.get('specialty', '')}",
        f"City requested: {arguments.get('city', '')}",
        f"Area requested: {arguments.get('area', '')}",
        f"State requested: {arguments.get('state', '')}",
    ]
    accepting = arguments.get("accepting_new_patients")
    if isinstance(accepting, bool):
        parts.append(f"Accepting new patients: {accepting}")
    return "\n".join(parts)


def _option(metadata: dict[str, Any]) -> dict[str, Any]:
    option = {key: metadata.get(key) for key in (
        "provider_id", "display_name", "area", "city", "state", "address", "rating", "rating_context",
        "is_fictional_demo", "phone", "accepting_new_patients",
    ) if metadata.get(key) not in (None, "")}
    specialties = str(metadata.get("specialties", ""))
    option["specialties"] = [item.strip() for item in specialties.split(";") if item.strip()]
    if option.get("is_fictional_demo") is True and option.get("accepting_new_patients") is True:
        from .scheduling import next_available_demo_slots
        option["next_available_slots"] = next_available_demo_slots(option["provider_id"])
        option["availability_note"] = "Fictional demo weekday slots; not real clinic availability."
    return option


def _trusted_provider_id_lookup(provider_id: str) -> list[dict[str, Any]]:
    """Resolve only an ID previously emitted by this server, for demo-slot validation."""
    source = _directory(Path(os.environ.get("CLARA_PROVIDER_DIRECTORY_PATH", str(DEFAULT_DIRECTORY))))
    for provider in (source or {}).get("providers", []):
        if isinstance(provider, dict) and provider.get("active") is True and provider.get("provider_id") == provider_id:
            return [_option({**provider, "specialties": "; ".join(provider.get("specialties", []))})]
    return []


def search_provider_directory(arguments: dict[str, Any]) -> dict[str, Any]:
    """Retrieve fictional providers with semantic embeddings, not literal name matching."""
    directory = Path(os.environ.get("CLARA_PROVIDER_DIRECTORY_PATH", str(DEFAULT_DIRECTORY)))
    source = _directory(directory)
    if source is None:
        return {"status": "not_configured", "options": [], "source": "provider_directory"}
    provider_id = str(arguments.get("provider_id", "")).strip()
    if provider_id:
        options = _trusted_provider_id_lookup(provider_id)
    elif not any(str(arguments.get(key, "")).strip()
                 for key in ("provider_name", "specialty", "city", "area", "state")):
        return {"status": "search_criteria_required", "options": [], "source": "provider_directory"}
    else:
        ranked = get_provider_vector_store().similarity_search_with_relevance_scores(_semantic_query(arguments), k=4)
        # Keep a semantic peer group, rather than presenting weakly related providers merely because this
        # small demo corpus has four records. A named or localized result normally becomes one choice.
        best_score = ranked[0][1] if ranked else 0.0
        threshold = max(0.35, best_score - 0.08)
        options = [_option(document.metadata) for document, score in ranked if score >= threshold]
    return {"status": "results_found" if options else "no_matches", "options": options,
            "source": "provider_directory", "directory_note": source.get("directory_note"),
            "as_of": source.get("as_of")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Clara's local provider-directory vector index")
    parser.add_argument("--rebuild", action="store_true", help="replace the provider-directory collection")
    args = parser.parse_args()
    get_provider_vector_store.cache_clear()
    store = build_provider_index(rebuild=args.rebuild)
    print(f"Provider vector index ready at {VECTOR_DIR} ({store._collection.count()} providers)")


if __name__ == "__main__":
    main()
