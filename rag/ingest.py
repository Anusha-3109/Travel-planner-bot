"""Turn the catalog's places into documents and index them in Chroma.

Chunking strategy: every attraction, restaurant and accommodation becomes one
chunk. The records are short, and splitting them would separate a place's name
from its price, cuisines or house rules. Record-level chunks keep each fact
whole, and their metadata (category, city, country, price, rating) drives the
structured filters in rag/retriever.py.

Each document's id is a hash of its source, so the index can be updated
incrementally: ensure_index() adds new places (for example newly fetched
cities) and removes places that are no longer in the data.

Run directly to rebuild the index:  python -m rag.ingest
"""

import hashlib
from collections.abc import Callable, Iterable

from langchain_core.documents import Document

import config
from rag.vectorstore import get_vectorstore, reset_vectorstore
from travel_data.catalog import TravelCatalog, load_catalog

ProgressCallback = Callable[[int, int], None]


def _source(category: str, name: str, city: str) -> str:
    return f"{category}: {name}, {city}"


def document_id(document: Document) -> str:
    return hashlib.sha1(document.metadata["source"].encode("utf-8")).hexdigest()[:20]


def _rating(value: float | None) -> str:
    return f" Rating {value}/5." if value is not None else ""


def place_documents(catalog: TravelCatalog | None = None, cities: Iterable[str] | None = None) -> list[Document]:
    catalog = catalog or load_catalog()
    keys = sorted({c.lower() for c in cities} if cities is not None else catalog.cities)
    documents = []

    def add(category: str, place, text: str, **extra) -> None:
        country = catalog.city_info[place.city.lower()].country
        metadata = {"category": category, "city": place.city, "country": country, "name": place.name,
                    "source": _source(category, place.name, place.city)}
        metadata.update({key: value for key, value in extra.items() if value is not None})
        documents.append(Document(text, metadata=metadata))

    for key in keys:
        info = catalog.city_info.get(key)
        where = f"{info.name}, {info.country}" if info else key
        for place in catalog.attractions.get(key, []):
            kind = place.kind or "attraction"
            text = f"{place.name} is a {kind} in {where}. Address: {place.address or 'unknown'}."
            if place.website:
                text += f" Website: {place.website}."
            add("attraction", place, text)
        for place in catalog.restaurants.get(key, []):
            cuisines = ", ".join(place.cuisines) or "not listed"
            cost = (f"Average cost ${place.average_cost:.0f} per person." if place.average_cost is not None
                    else "Price not available.")
            text = f"{place.name} is a restaurant in {where}. Cuisines: {cuisines}. {cost}{_rating(place.rating)}"
            add("restaurant", place, text, cuisines=cuisines, average_cost=place.average_cost, rating=place.rating)
        for place in catalog.accommodations.get(key, []):
            rules = (", ".join(place.house_rules) or "none") if place.house_rules is not None else "not published"
            price = f"${place.price:.0f} per night" if place.price is not None else "No price listed (search live)"
            sleeps = f", sleeps up to {place.maximum_occupancy}" if place.maximum_occupancy else ""
            text = (f"{place.name} is a {place.room_type.lower()} to stay in {where}. {price}{sleeps}, "
                    f"minimum stay {place.minimum_nights} nights. House rules: {rules}.{_rating(place.rating)}")
            add("accommodation", place, text, price=place.price, room_type=place.room_type, house_rules=rules,
                maximum_occupancy=place.maximum_occupancy, minimum_nights=place.minimum_nights, rating=place.rating)
    return documents


def _add(documents: list[Document], on_progress: ProgressCallback | None) -> None:
    vectorstore = get_vectorstore()
    for start in range(0, len(documents), config.INDEX_BATCH_SIZE):
        batch = documents[start:start + config.INDEX_BATCH_SIZE]
        vectorstore.add_documents(batch, ids=[document_id(d) for d in batch])
        if on_progress:
            on_progress(start + len(batch), len(documents))


def build_index(cities: Iterable[str] | None = None, on_progress: ProgressCallback | None = None) -> int:
    """Rebuild the vector index from scratch. Returns the number of documents indexed.
    Embedding every place takes a while, so progress is reported per batch."""
    documents = place_documents(cities=cities)
    if not documents:
        raise RuntimeError("No places found in the travel data to index.")
    reset_vectorstore()
    _add(documents, on_progress)
    return len(documents)


def ensure_index(on_progress: ProgressCallback | None = None) -> int:
    """Bring the index in line with the data: add places that are missing and
    remove places that are gone. Returns the number of documents indexed."""
    documents = {document_id(d): d for d in place_documents()}
    vectorstore = get_vectorstore()
    existing = set(vectorstore.get(include=[])["ids"])
    stale = sorted(existing - documents.keys())
    for start in range(0, len(stale), config.INDEX_BATCH_SIZE):
        vectorstore.delete(ids=stale[start:start + config.INDEX_BATCH_SIZE])
    missing = [document for doc_id, document in documents.items() if doc_id not in existing]
    if missing:
        _add(missing, on_progress)
    return len(documents)


if __name__ == "__main__":
    count = ensure_index(on_progress=lambda done, total: print(f"\rIndexed {done}/{total} new places", end="", flush=True))
    print(f"\nThe index holds {count} places in {config.CHROMA_DIR}")
