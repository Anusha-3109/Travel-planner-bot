"""Part 4: the embedding probe, comparing the app's local embeddings with two OpenAI models.

Run:  python -m evaluation.embeddings

Two checks, for each embedding model:
1. Sentence groups: hand-written sentence pairs in five groups (same request in other words, in
   another language, with another city, about another kind of place, and unrelated). Each pair is
   scored with cosine similarity and the scores are averaged per group. Each model has its own
   scale, so the order of the groups within a model matters, above all the gap between paraphrase
   and city_differs: a negative gap means two wordings of one request look less alike to the model
   than the same words with another city.
2. Retrieval: a small test index (every place in TEST_CITIES) per model, searched with plain vector
   search and no filters. Place questions (an attraction's name) count when that attraction comes
   first; city questions count when the first result is in the asked city. The margin is how far
   the right place's score is ahead of the best other place (negative when it isn't first).
3. Languages: city questions asked in English and in German, in two sets: the 10 US test cities
   (whose names are the same in German) and EUROPE_CITIES, whose German names differ (Wien for
   Vienna), in an index of their own. The German questions are searched in the English index two ways: directly, and as the app searches (backend/rag/retriever.py keeps the question
   and adds 2-3 searches the model writes in English, fused with reciprocal rank fusion; filters are
   left out here, so only the embeddings are compared). Each counts whether the
   first result is in the asked city and of the asked kind (museum, restaurant or stay), and the
   share of the asked kind among the first RESULTS_PER_SEARCH results.

The app keeps using all-MiniLM-L6-v2; the OpenAI models are called through OpenRouter.
"""

import json
import math
import random
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

import numpy as np
from openai import OpenAI

from backend import config
from backend.rag.ingest import place_documents
from backend.travel_data.catalog import TravelCatalog, load_catalog
from evaluation import RESULTS_DIR

LOCAL_MODEL = "all-MiniLM-L6-v2"
MODELS = (LOCAL_MODEL, "openai/text-embedding-3-small", "openai/text-embedding-3-large")
TEST_CITIES = ("Tulsa", "Memphis", "Albuquerque", "Cleveland", "Omaha",
               "Tucson", "Louisville", "Pittsburgh", "Atlanta", "Baltimore")
SEED = 2026
BATCH_SIZE = 256
RESULTS_PER_SEARCH = 6  # as config.RETRIEVAL_K
RRF_K = 60  # as backend/rag/retriever.py
KIND_CATEGORY = {"museum": "attraction", "restaurant": "restaurant", "stay": "accommodation"}
GERMAN_CUISINES = {"American": "amerikanische", "Mexican": "mexikanische", "Italian": "italienische",
                   "Chinese": "chinesische", "Japanese": "japanische", "Indian": "indische", "Thai": "thailändische",
                   "French": "französische", "Mediterranean": "mediterrane", "Spanish": "spanische"}
# European cities with a German name of their own (English name: German name), for the language check.
EUROPE_CITIES = {"Vienna": "Wien", "Rome": "Rom", "Prague": "Prag", "Lisbon": "Lissabon", "Athens": "Athen"}
LANGUAGE_SETS = {"us": "10 US cities (same name in German)", "europe": "5 European cities with German names"}
LANGUAGE_SEARCHES = {"english": "English question", "german": "German question, searched directly",
                     "german_translated": "German question plus its English searches, fused (the app)"}

Embed = Callable[[list[str]], list[list[float]]]

GROUPS: dict[str, list[tuple[str, str]]] = {
    "paraphrase": [
        ("museums to visit in Lisbon", "which Lisbon museums are worth seeing"),
        ("cheap places to stay in Prague", "budget accommodation in Prague"),
        ("vegetarian restaurants in Vienna", "where to eat meat-free food in Vienna"),
        ("things to do with kids in Chicago", "family-friendly activities in Chicago"),
        ("a quiet hotel near the beach in Miami", "a peaceful place to sleep close to Miami's beach"),
        ("the best pizza in New York", "top-rated pizzerias in New York"),
        ("how to get from the airport to central London", "transport from London's airport into the city centre"),
        ("art galleries in Paris", "where to see paintings in Paris"),
        ("a romantic dinner spot in Rome", "a restaurant in Rome for a date night"),
        ("hiking trails near Denver", "places to go walking in the hills around Denver"),
    ],
    "cross_lingual": [
        ("Restaurants mit vegetarischem Essen in Wien", "vegetarian restaurants in Vienna"),
        ("pigūs viešbučiai Paryžiuje", "cheap hotels in Paris"),
        ("Museen in Berlin für Kinder", "museums in Berlin for children"),
        ("geriausi restoranai Romoje", "the best restaurants in Rome"),
        ("ein Zimmer in Amsterdam für zwei Nächte", "a room in Amsterdam for two nights"),
        ("ką pamatyti Londone", "what to see in London"),
        ("Sehenswürdigkeiten in Prag", "sights to see in Prague"),
        ("kambarys su vaizdu į jūrą Barselonoje", "a room with a sea view in Barcelona"),
        ("italienische Restaurants in Madrid", "Italian restaurants in Madrid"),
        ("muziejai Atėnuose", "museums in Athens"),
    ],
    "city_differs": [
        ("a private room to stay in Boston", "a private room to stay in Seattle"),
        ("museums for kids in Chicago", "museums for kids in Denver"),
        ("vegetarian restaurants in Vienna", "vegetarian restaurants in Lisbon"),
        ("cheap hotels in Paris", "cheap hotels in Tokyo"),
        ("art galleries in Madrid", "art galleries in Berlin"),
        ("the best pizza in New York", "the best pizza in Nashville"),
        ("a quiet hotel near the beach in Miami", "a quiet hotel near the beach in San Diego"),
        ("things to do in Rome", "things to do in Bangkok"),
        ("seafood restaurants in Boston", "seafood restaurants in Singapore"),
        ("a room for two nights in Amsterdam", "a room for two nights in Istanbul"),
    ],
    "category_differs": [
        ("Italian restaurants in Rome", "Italian-style guest houses in Rome"),
        ("a museum near the old town of Prague", "a hotel near the old town of Prague"),
        ("a cheap restaurant in Lisbon", "a cheap room in Lisbon"),
        ("a park to visit in London", "a pub to visit in London"),
        ("a family hotel in Orlando", "a family restaurant in Orlando"),
        ("a sushi bar in Tokyo", "a capsule hotel in Tokyo"),
        ("an art museum in Chicago", "an art supply shop in Chicago"),
        ("a rooftop bar in Bangkok", "a rooftop pool hotel in Bangkok"),
        ("a historic castle in Edinburgh", "a historic inn in Edinburgh"),
        ("a seafood market in Barcelona", "a seafood restaurant in Barcelona"),
    ],
    "unrelated": [
        ("museums in Paris", "how to reset a router password"),
        ("seafood in Boston", "the rules of chess"),
        ("a private room in Berlin", "how photosynthesis works"),
        ("vegetarian restaurants in Vienna", "the price of a used bicycle"),
        ("cheap hotels in Tokyo", "how to write a cover letter"),
        ("things to do with kids in Chicago", "a recipe for sourdough bread"),
        ("art galleries in Madrid", "the history of the printing press"),
        ("a beach hotel in Miami", "how to change a car tyre"),
        ("the best pizza in New York", "the symptoms of the flu"),
        ("hiking near Denver", "how to fill in a tax return"),
    ],
}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _unit(vectors: list[list[float]]) -> np.ndarray:
    """Vectors scaled to length 1, so a dot product is their cosine similarity."""
    array = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.where(norms == 0, 1, norms)


def group_scores(embed: Embed) -> dict:
    """Mean cosine similarity per sentence group, every pair's score, and the paraphrase gap."""
    texts = sorted({text for pairs in GROUPS.values() for pair in pairs for text in pair})
    vectors = dict(zip(texts, embed(texts)))
    pairs = {group: [round(cosine(vectors[a], vectors[b]), 4) for a, b in items] for group, items in GROUPS.items()}
    means = {group: round(sum(scores) / len(scores), 3) for group, scores in pairs.items()}
    return {"means": means, "gap": round(means["paraphrase"] - means["city_differs"], 3), "pairs": pairs}


def _main_cuisine(catalog: TravelCatalog, key: str) -> str | None:
    counts = Counter(c for r in catalog.restaurants.get(key, []) for c in r.cuisines if c.isalpha())
    return counts.most_common(1)[0][0] if counts else None


def _german(kind: str, city: str, cuisine: str | None) -> str:
    """The city question in German, as a German traveller might ask it."""
    if kind == "museum":
        return f"Welche Museen gibt es in {city}?"
    if kind == "stay":
        return f"Wo kann ich in {city} übernachten?"
    if cuisine == "Pizza":
        return f"Gute Pizzerien in {city}"
    adjective = GERMAN_CUISINES.get(cuisine or "")
    return f"Gute {adjective} Restaurants in {city}" if adjective else f"Gute Restaurants in {city}"


def europe_questions() -> list[dict]:
    """Two questions per European city (the kinds in turn), in English and with the German city name."""
    questions = []
    for number, (city, german) in enumerate((c, g) for c, g in EUROPE_CITIES.items() for _ in range(2)):
        kind = ("museum", "restaurant", "stay")[number % 3]
        english = {"museum": f"museums in {city}", "restaurant": f"restaurants in {city}",
                   "stay": f"a place to stay in {city}"}[kind]
        questions.append({"question": english, "city": city, "kind": kind,
                          "german": _german(kind, german, None)})
    return questions


def build_questions(catalog: TravelCatalog, cities=TEST_CITIES, seed: int = SEED) -> dict[str, list[dict]]:
    """One place question and one city question per test city, with a fixed seed. City questions
    also carry their kind of place and the same question in German."""
    rng = random.Random(seed)
    place, city_questions = [], []
    for number, city in enumerate(cities):
        key = city.lower()
        named = sorted({a.name for a in catalog.attractions.get(key, [])
                        if len(a.name.split()) >= 3 and city.lower() not in a.name.lower()})
        if named:
            name = rng.choice(named)
            place.append({"question": name, "city": city, "source": f"attraction: {name}, {city}"})
        cuisine = _main_cuisine(catalog, key)
        kind = ("museum", "restaurant", "stay")[number % 3]
        if kind == "restaurant" and not cuisine:
            kind = "museum"
        text = {"museum": f"museums in {city}", "restaurant": f"{cuisine} restaurants in {city}",
                "stay": f"a place to stay in {city}"}[kind]
        city_questions.append({"question": text, "city": city, "kind": kind,
                               "german": _german(kind, city, cuisine)})
    return {"place": place, "city": city_questions}


def retrieval_scores(embed: Embed, documents: list[dict], questions: dict[str, list[dict]],
                     doc_vectors: np.ndarray | None = None) -> dict:
    """Plain vector search over the test index: place hits, right-city hits and the mean margin.
    doc_vectors: the documents already embedded by this model (embedded here when not given)."""
    if doc_vectors is None:
        doc_vectors = _unit(embed([d["text"] for d in documents]))
    all_questions = questions["place"] + questions["city"]
    similarity = _unit(embed([q["question"] for q in all_questions])) @ doc_vectors.T  # cosine, one row per question
    rows, margins, place_hits, city_hits = [], [], 0, 0
    for question, scores in zip(questions["place"], similarity[:len(questions["place"])]):
        first = documents[int(scores.argmax())]
        right = np.array([d["source"] == question["source"] for d in documents])
        margin = float(scores[right].max() - scores[~right].max()) if right.any() else -1.0
        hit = first["source"] == question["source"]
        place_hits += hit
        margins.append(margin)
        rows.append({"kind": "place", "question": question["question"], "first": first["source"], "hit": hit,
                     "margin": round(margin, 4)})
    for question, scores in zip(questions["city"], similarity[len(questions["place"]):]):
        first = documents[int(scores.argmax())]
        hit = first["city"] == question["city"]
        city_hits += hit
        rows.append({"kind": "city", "question": question["question"], "first": first["source"], "hit": hit})
    return {"place_hits": place_hits, "place_questions": len(questions["place"]),
            "city_hits": city_hits, "city_questions": len(questions["city"]),
            "mean_margin": round(sum(margins) / len(margins), 4) if margins else None, "rows": rows}


def _fused(rankings: list[np.ndarray]) -> list[int]:
    """Reciprocal rank fusion of each search's first RESULTS_PER_SEARCH results, as the app does."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking[:RESULTS_PER_SEARCH]):
            scores[int(index)] = scores.get(int(index), 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])[:RESULTS_PER_SEARCH]


def language_scores(embed: Embed, documents: list[dict], doc_vectors: np.ndarray, questions: list[dict],
                    searches: list[list[str]]) -> dict:
    """The city questions searched with the given searches (one list per question, fused when there are
    several): right city first, right kind first, and the share of the right kind among the results."""
    texts = [text for group in searches for text in group]
    similarity = dict(zip(texts, _unit(embed(texts)) @ doc_vectors.T))
    rows, city_hits, kind_hits, shares = [], 0, 0, []
    for question, group in zip(questions, searches):
        top = [documents[i] for i in _fused([np.argsort(-similarity[text]) for text in group])]
        category = KIND_CATEGORY[question["kind"]]
        city_hit, kind_hit = top[0]["city"] == question["city"], top[0]["category"] == category
        city_hits += city_hit
        kind_hits += kind_hit
        shares.append(sum(d["category"] == category for d in top) / len(top))
        rows.append({"searches": group, "first": top[0]["source"], "right_city": city_hit, "right_kind": kind_hit})
    return {"city_hits": city_hits, "kind_hits": kind_hits, "questions": len(questions),
            "kind_share": round(sum(shares) / len(shares), 3) if shares else None, "rows": rows}


def translate(texts: list[str]) -> tuple[list[list[str]], float]:
    """The app's searches for each text (the text itself and the model's English searches), and the cost."""
    from backend.agent.llm import get_llm, message_usage
    from backend.rag.retriever import plan_search
    llm, queries, cost = get_llm(), [], 0.0
    for text in texts:
        replies: list = []
        queries.append(plan_search(text, llm, replies).queries)
        cost += sum(message_usage(config.OPENROUTER_MODEL, reply).get("cost_usd") or 0 for reply in replies)
    return queries, cost


class _Embedder:
    """Embeds texts in batches with one model and adds up the cost OpenRouter reports."""

    def __init__(self, model: str) -> None:
        self.model, self.cost_usd, self.tokens = model, 0.0, 0
        if model == LOCAL_MODEL:
            from backend.rag.vectorstore import _embeddings
            self._local = _embeddings()
        else:
            self._client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)

    def __call__(self, texts: list[str]) -> list[list[float]]:
        if self.model == LOCAL_MODEL:
            return self._local.embed_documents(texts)
        vectors = []
        for start in range(0, len(texts), BATCH_SIZE):
            reply = self._client.embeddings.create(model=self.model, input=texts[start:start + BATCH_SIZE])
            vectors += [item.embedding for item in sorted(reply.data, key=lambda item: item.index)]
            usage = reply.usage
            self.tokens += usage.total_tokens or 0
            self.cost_usd += getattr(usage, "cost", 0) or 0
        return vectors


def run(models=MODELS) -> dict:
    catalog = load_catalog()
    def docs(cities) -> list[dict]:
        return [{"text": d.page_content, "source": d.metadata["source"], "city": d.metadata["city"],
                 "category": d.metadata["category"]} for d in place_documents(catalog, cities)]

    documents, europe_documents = docs(TEST_CITIES), docs(EUROPE_CITIES)
    questions = build_questions(catalog)
    sets = {"us": questions["city"], "europe": europe_questions()}
    translation_cost, searches = 0.0, {}
    for name, items in sets.items():
        translated, cost = translate([q["german"] for q in items])
        translation_cost += cost
        searches[name] = {"english": [[q["question"]] for q in items], "german": [[q["german"]] for q in items],
                          "german_translated": translated}
    results = {}
    for model in models:
        print(f"{model}: sentence groups, then {len(documents)} + {len(europe_documents)} places", flush=True)
        embed = _Embedder(model)
        doc_vectors = _unit(embed([d["text"] for d in documents]))
        europe_vectors = _unit(embed([d["text"] for d in europe_documents]))
        indexes = {"us": (documents, doc_vectors), "europe": (europe_documents, europe_vectors)}
        results[model] = {**group_scores(embed),
                          "retrieval": retrieval_scores(embed, documents, questions, doc_vectors),
                          "languages": {name: {search: language_scores(embed, *indexes[name], sets[name], texts)
                                               for search, texts in searches[name].items()} for name in sets},
                          "tokens": embed.tokens, "cost_usd": round(embed.cost_usd, 6)}
    return {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "test_cities": list(TEST_CITIES),
            "places": len(documents), "europe_cities": EUROPE_CITIES, "europe_places": len(europe_documents),
            "pairs_per_group": {g: len(p) for g, p in GROUPS.items()}, "questions": questions,
            "language_questions": sets, "app_searches": {name: s["german_translated"] for name, s in searches.items()},
            "translation_cost_usd": round(translation_cost, 6), "models": results}


def main() -> None:
    result = run()
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "embeddings.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {path}.")
    for model, scores in result["models"].items():
        r = scores["retrieval"]
        print(f"  {model}: {scores['means']} gap {scores['gap']} | place {r['place_hits']}/{r['place_questions']}"
              f" city {r['city_hits']}/{r['city_questions']} margin {r['mean_margin']} | ${scores['cost_usd']:.4f}")
        for name, checks in scores["languages"].items():
            for search, check in checks.items():
                print(f"    {name} {search}: city {check['city_hits']}/{check['questions']} kind {check['kind_hits']}/"
                      f"{check['questions']} kind share {check['kind_share']}")
    print(f"  query translation cost ${result['translation_cost_usd']:.4f}")


if __name__ == "__main__":
    main()
