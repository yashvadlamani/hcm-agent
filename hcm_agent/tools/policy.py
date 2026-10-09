"""LangChain PDF ingestion and retrieval for Clara's plan-policy source."""

from __future__ import annotations

import argparse
import os
import re
from functools import lru_cache
from pathlib import Path

POLICY_ID = "clara-plan-policy"
POLICY_CONTEXT = (
    "Source document: Blue Cross and Blue Shield of Illinois Summary of Benefits and Coverage "
    "for Blue Choice Preferred Gold PPO 901; coverage period 2025-01-01 through 2025-12-31. "
    "This document does not establish coverage after 2025 or confirm that a caller is enrolled in this plan."
)
POLICY_PATH = Path(__file__).resolve().parents[2] / "data" / "policies" / "sbc-gpsd69bceiilo-il-2025.pdf"
VECTOR_DIR = Path(os.environ.get(
    "CLARA_POLICY_VECTOR_DIR",
    str(Path(__file__).resolve().parents[2] / "data" / "vectorstore" / "plan-policy"),
))


def policy_document_available() -> bool:
    """Whether the configured source PDF exists and is nonempty."""
    return POLICY_PATH.is_file() and POLICY_PATH.stat().st_size > 0


def load_policy_documents(path: Path = POLICY_PATH) -> list:
    """Load the policy PDF with LangChain and split pages using playbook-sized overlap chunks."""
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Policy PDF is missing or empty: {path}")
    documents = PyPDFLoader(str(path)).load()
    for document in documents:
        document.metadata.update({
            "policy_id": POLICY_ID,
            "title": path.stem,
            "source_file": path.name,
        })
        # PyPDFLoader stores a zero-based page index; expose human-readable page numbers.
        if isinstance(document.metadata.get("page"), int):
            document.metadata["page"] += 1
    chunks = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=200).split_documents(documents)
    for index, chunk in enumerate(chunks, start=1):
        chunk.metadata["chunk_id"] = f"policy-{index}"
    return chunks


def _dependencies():
    try:
        from fastembed import TextEmbedding  # noqa: F401
        from langchain_chroma import Chroma
        from langchain_community.embeddings import FastEmbedEmbeddings
    except ImportError as error:
        raise RuntimeError("Policy RAG dependencies are missing; install the project's requirements.txt") from error
    return Chroma, FastEmbedEmbeddings


def build_policy_index(*, rebuild: bool = False):
    """Build/open the persistent policy PDF Chroma collection."""
    documents = load_policy_documents()
    if not documents:
        raise ValueError(f"No text extracted from the policy PDF at {POLICY_PATH}")
    Chroma, FastEmbedEmbeddings = _dependencies()
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    if (VECTOR_DIR / "chroma.sqlite3").exists():
        store = Chroma(collection_name=POLICY_ID, embedding_function=embeddings,
                       persist_directory=str(VECTOR_DIR))
        if not rebuild and store._collection.count():
            return store
        store.delete_collection()
    return Chroma.from_documents(documents, embeddings, collection_name=POLICY_ID,
                                 persist_directory=str(VECTOR_DIR))


@lru_cache(maxsize=1)
def get_policy_vector_store():
    return build_policy_index()


def retrieve_policy(query: str, *, llm=None, limit: int = 3) -> list[dict]:
    """Search the uploaded policy PDF using the LLM-selected query and local semantic retrieval."""
    if not query.strip() or not policy_document_available():
        return []
    store = get_policy_vector_store()
    base_retriever = store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"k": max(1, limit), "score_threshold": 0.25},
    )
    # The care model already formulates the tool query. Avoid a second paid model round-trip in
    # the live call by default; deployments can opt in to MultiQueryRetriever when latency permits.
    if llm is not None and os.environ.get("CLARA_RAG_QUERY_EXPANSION") == "1":
        from langchain_classic.retrievers.multi_query import MultiQueryRetriever
        retriever = MultiQueryRetriever.from_llm(retriever=base_retriever, llm=llm, include_original=True)
    else:
        retriever = base_retriever

    results = []
    seen = set()
    for document in retriever.invoke(query):
        metadata = document.metadata
        chunk_id = metadata.get("chunk_id", "")
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        results.append({
            "policy_id": metadata.get("policy_id", POLICY_ID),
            "title": metadata.get("title", "Plan policy PDF"),
            "page": metadata.get("page"),
            "source_file": metadata.get("source_file", POLICY_PATH.name),
            "coverage_period": "2025-01-01 through 2025-12-31",
            "content": document.page_content,
        })
        if len(results) >= max(1, limit):
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Clara's local policy-PDF vector index")
    parser.add_argument("--rebuild", action="store_true", help="replace the policy PDF collection")
    args = parser.parse_args()
    get_policy_vector_store.cache_clear()
    store = build_policy_index(rebuild=args.rebuild)
    print(f"Policy vector index ready at {VECTOR_DIR} ({store._collection.count()} chunks)")


if __name__ == "__main__":
    main()
