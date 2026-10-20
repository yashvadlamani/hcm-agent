"""Focused checks for fictional-provider semantic retrieval."""

import hcm_agent.tools.providers as providers


def test_directory_uses_embedding_retrieval_for_spoken_provider_request(monkeypatch):
    documents = providers.load_provider_documents()
    queries = []

    class FakeVectorStore:
        def similarity_search_with_relevance_scores(self, query, k):
            queries.append((query, k))
            return [(documents[0], 0.9)]

    monkeypatch.setattr(providers, "get_provider_vector_store", lambda: FakeVectorStore())
    result = providers.search_provider_directory({"provider_name": "Doctor Every Sample", "area": "Schaumburg"})

    assert result["status"] == "results_found"
    assert result["options"][0]["provider_id"] == "demo-chi-schaumburg-001"
    assert "Doctor Every Sample" in queries[0][0] and queries[0][1] == 4
    assert "Dr. Avery Sample" in documents[0].page_content and "Schaumburg" in documents[0].page_content
