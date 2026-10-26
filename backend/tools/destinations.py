"""Semantic place search over the snapshot places (the RAG entry point for the agent)."""

from langchain_core.tools import tool

from backend.rag.retriever import RetrievalResult, format_documents, retrieve
from backend.security.validation import InputValidationError, validate_category
from backend.travel_data.catalog import load_catalog


def search_places(query: str, city: str | None = None, category: str | None = None, llm=None) -> RetrievalResult:
    category = validate_category(category)
    city = load_catalog().require_city(city) if city else None
    return retrieve(query, category=category, city=city, llm=llm)


@tool
def search_destination_options(query: str, city: str | None = None, category: str | None = None) -> str:
    """Search attractions, restaurants and accommodations by meaning, for open
    questions such as "museums for kids in Chicago" or "a cheap place to stay
    near the beach". city narrows results to one city. category is optional:
    'attraction', 'restaurant' or 'accommodation'. For exact filters (cuisine,
    price, house rules, room type) use search_restaurants or search_accommodations."""
    try:
        return format_documents(search_places(query, city, category).documents)
    except InputValidationError as error:
        return f"Error: {error}"
