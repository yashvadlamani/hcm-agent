"""LangChain ingestion and retrieval for Clara's diabetes support playbook."""

from __future__ import annotations

import argparse
import os
import re
from functools import lru_cache
from pathlib import Path

PLAYBOOK_ID = "clara-diabetes-quick-care"
PLAYBOOK_STATUS = "draft_pending_clinical_owner_review"
PLAYBOOK_PATH = Path(__file__).resolve().parents[2] / "data" / "playbooks" / "diabetes_quick_care_playbook.md"
VECTOR_DIR = Path(os.environ.get(
    "CLARA_PLAYBOOK_VECTOR_DIR",
    str(Path(__file__).resolve().parents[2] / "data" / "vectorstore" / "diabetes-playbook"),
))
SOURCE_IDS = re.compile(r"(?m)^\*\*Sources:\*\*\s*(.+)$")
PAGE = re.compile(r"^PAGE (\d+) \| (.+)$")
SOURCES = {
    "CDC-DSMES": {
        "title": "CDC: About Diabetes Self-Management Education and Support",
        "url": "https://www.cdc.gov/diabetes/education-support-programs/",
    },
    "CDC-DSMES-STANDARDS": {
        "title": "CDC: National Standards for DSMES",
        "url": "https://www.cdc.gov/diabetes-toolkit/php/become-provider/dsmes-national-standards.html",
    },
    "CDC-FIND-DSMES": {
        "title": "CDC: Find a DSMES Program",
        "url": "https://www.cdc.gov/diabetes/education-support-programs/find-a-dsmes-program.html",
    },
}


def load_playbook_documents(path: Path = PLAYBOOK_PATH) -> list:
    """Load Markdown and use LangChain's Markdown-aware splitter plus overlap splitting."""
    from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

    markdown = path.read_text(encoding="utf-8")
    sections = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "section")],
        strip_headers=False,
    ).split_text(markdown)
    for section in sections:
        source_match = SOURCE_IDS.search(section.page_content)
        source_ids = [value.strip() for value in source_match.group(1).split(";")] if source_match else []
        section.metadata["source_ids"] = ";".join(source_ids)
    splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=200)
    documents = splitter.split_documents(sections)

    for index, document in enumerate(documents):
        match = PAGE.match(document.metadata.get("section", ""))
        document.metadata.update({
            "playbook_id": PLAYBOOK_ID,
            "chunk_id": f"diabetes-{index + 1}",
            "page": int(match.group(1)) if match else 0,
            "title": match.group(2).strip() if match else document.metadata.get("section", "Playbook overview"),
            # Chroma metadata is scalar-valued; source IDs are inherited from the page.
        })
    return documents


def _dependencies():
    """Load optional vector integrations only when the care tool is actually used."""
    try:
        from fastembed import TextEmbedding  # noqa: F401
        from langchain_chroma import Chroma
        from langchain_community.embeddings import FastEmbedEmbeddings
    except ImportError as error:
        raise RuntimeError(
            "Playbook RAG dependencies are missing; install the project's requirements.txt"
        ) from error
    return Chroma, FastEmbedEmbeddings


def build_playbook_index(*, rebuild: bool = False):
    """Ingest the Markdown corpus into Chroma; ``rebuild`` replaces only this collection."""
    Chroma, FastEmbedEmbeddings = _dependencies()
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    if (VECTOR_DIR / "chroma.sqlite3").exists():
        store = Chroma(
            collection_name=PLAYBOOK_ID, embedding_function=embeddings,
            persist_directory=str(VECTOR_DIR),
        )
        if not rebuild:
            return store
        store.delete_collection()

    documents = load_playbook_documents()
    if not documents:
        raise ValueError(f"No playbook sections found at {PLAYBOOK_PATH}")
    return Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=PLAYBOOK_ID,
        persist_directory=str(VECTOR_DIR),
    )


@lru_cache(maxsize=1)
def get_playbook_vector_store():
    """Open the persistent local Chroma index, creating it from Markdown on first use."""
    return build_playbook_index()


def retrieve_playbook(query: str, *, llm=None, limit: int = 3) -> list[dict]:
    """Use the LLM-selected query for semantic Chroma search, with optional expansion."""
    if not query.strip():
        return []

    vector_store = get_playbook_vector_store()
    base_retriever = vector_store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"k": max(1, limit), "score_threshold": 0.25},
    )
    # Query expansion adds a second model call and made live phone turns needlessly slow. The
    # graph's model still selects the retrieval tool and forms its query; expansion is opt-in.
    if llm is not None and os.environ.get("CLARA_RAG_QUERY_EXPANSION") == "1":
        from langchain_classic.retrievers.multi_query import MultiQueryRetriever

        retriever = MultiQueryRetriever.from_llm(
            retriever=base_retriever, llm=llm, include_original=True,
        )
    else:
        retriever = base_retriever
    documents = retriever.invoke(query)

    results = []
    seen = set()
    for document in documents:
        metadata = document.metadata
        chunk_id = metadata.get("chunk_id", "")
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        results.append({
            "id": chunk_id,
            "title": metadata.get("title", "Diabetes playbook"),
            "page": metadata.get("page", 0),
            "content": document.page_content,
            "sources": [SOURCES[source_id] | {"id": source_id}
                        for source_id in metadata.get("source_ids", "").split(";") if source_id in SOURCES],
        })
        if len(results) >= max(1, limit):
            break
    return results


def main():
    parser = argparse.ArgumentParser(description="Build Clara's local diabetes playbook vector index")
    parser.add_argument("--rebuild", action="store_true", help="replace the diabetes playbook collection")
    options = parser.parse_args()
    build_playbook_index(rebuild=options.rebuild)
    print(f"Playbook vector index ready at {VECTOR_DIR}")


if __name__ == "__main__":
    main()
