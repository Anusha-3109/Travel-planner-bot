"""Retrieval tests. They use the local embedding model and a two-city index, so no API key is needed."""

from rag.ingest import place_documents
from rag.retriever import _build_filter, plan_search, retrieve


def test_one_document_per_place_with_metadata():
    documents = place_documents(cities=["Myrtle Beach"])
    assert {d.metadata["category"] for d in documents} == {"attraction", "restaurant", "accommodation"}
    assert all(d.metadata["city"] == "Myrtle Beach" for d in documents)
    assert len({d.metadata["source"] for d in documents}) == len(documents)
    restaurant = next(d for d in documents if d.metadata["category"] == "restaurant")
    assert "average_cost" in restaurant.metadata and "Cuisines:" in restaurant.page_content


def test_filter_building():
    assert _build_filter(None, None) is None
    assert _build_filter("restaurant", None) == {"category": "restaurant"}
    assert _build_filter("restaurant", "myrtle beach") == {"$and": [{"category": "restaurant"}, {"city": "Myrtle Beach"}]}
    # Unknown cities are ignored rather than filtering out everything.
    assert _build_filter("attraction", "Atlantis") == {"category": "attraction"}


def test_plan_search_without_llm_uses_question():
    assert plan_search("museums for kids").queries == ["museums for kids"]


def test_retrieves_with_category_and_city_filter(small_index):
    result = retrieve("Indian food", category="restaurant", city="Rockford")
    assert result.documents
    assert all(d.metadata["category"] == "restaurant" and d.metadata["city"] == "Rockford" for d in result.documents)


def test_retrieves_named_attraction(small_index):
    result = retrieve("SkyWheel ferris wheel", city="Myrtle Beach")
    assert "attraction: SkyWheel Myrtle Beach, Myrtle Beach" in [d.metadata["source"] for d in result.documents]
