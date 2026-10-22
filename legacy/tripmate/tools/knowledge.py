"""Knowledge base search tool (the RAG entry point for the agent)."""

from langchain_core.tools import tool

from rag.retriever import RetrievalResult, format_documents, retrieve
from security.validation import InputValidationError, validate_city, validate_topic


def search_knowledge(query: str, topic: str | None = None, city: str | None = None, llm=None) -> RetrievalResult:
    topic = validate_topic(topic)
    city = validate_city(city) if city else None
    return retrieve(query, topic=topic, city=city, llm=llm)


@tool
def search_travel_knowledge(query: str, topic: str | None = None, city: str | None = None) -> str:
    """Search the travel knowledge base: city guides (airports, transport, sights,
    weather, entry rules, safety), travel insurance guides (coverage, exclusions,
    claims) and flight planning tips. topic is optional: 'cities', 'insurance' or
    'flights'. city is optional and narrows city guide results."""
    try:
        return format_documents(search_knowledge(query, topic, city).documents)
    except InputValidationError as error:
        return f"Error: {error}"
