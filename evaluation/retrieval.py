"""Part 1: retrieval quality, comparing four RAG strategies on the same questions.

Run:  python -m evaluation.retrieval

The test questions are built from the catalog, so the right answers are known
from the data, with no hand labelling:
- "museums in {city}": every museum in that city (OpenStreetMap's tourism=museum)
- "{cuisine} restaurants in {city}": every restaurant there with that cuisine
- "a private room to stay in {city}": every private room there
- "{attraction name}": that one attraction (finding a named place)

Strategies (each adds one RAG technique; all retrieve config.RETRIEVAL_K places):
1. vector: the question alone, plain similarity search
2. + filters: the LLM's category and city filters (structured retrieval)
3. + multi-query: the LLM's rewritten queries fused with RRF, without filters
4. full: queries, filters and RRF, which is what the app uses

The LLM's search plan is made once per question and shared by strategies 2-4,
so they differ only in how the plan is used. Scores per strategy: hit rate (at
least one right place), precision (share of right places), MRR (1 / rank of the
first right place) and wrong-city rate (share of places from another city).
"""

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import config
from agent.llm import add_usage, get_llm, message_usage
from evaluation import RESULTS_DIR
from rag.ingest import _source
from rag.retriever import SearchPlan, plan_search, retrieve
from travel_data.catalog import TravelCatalog, load_catalog

QUESTIONS_PER_KIND = 15
SEED = 2026
STRATEGIES = ("vector", "+ filters", "+ multi-query", "full")


@dataclass(frozen=True)
class Question:
    kind: str
    text: str
    city: str
    relevant: frozenset[str]  # document sources that count as right answers


def build_questions(catalog: TravelCatalog, per_kind: int = QUESTIONS_PER_KIND, seed: int = SEED) -> list[Question]:
    """Questions with known answers, drawn at random (with a fixed seed) from the catalog."""
    rng = random.Random(seed)
    questions: list[Question] = []

    def pick(candidates: list[Question]) -> None:
        questions.extend(rng.sample(candidates, min(per_kind, len(candidates))))

    museums, cuisines, rooms, named = [], [], [], []
    for key in sorted(catalog.cities):
        city = catalog.cities[key]
        found = [a for a in catalog.attractions.get(key, []) if a.kind == "museum"]
        if len(found) >= 2:
            museums.append(Question("museums", f"museums in {city}", city,
                                    frozenset(_source("attraction", a.name, city) for a in found)))
        by_cuisine: dict[str, list[str]] = {}
        for r in catalog.restaurants.get(key, []):
            for cuisine in r.cuisines:
                by_cuisine.setdefault(cuisine, []).append(_source("restaurant", r.name, city))
        for cuisine, sources in sorted(by_cuisine.items()):
            if len(sources) >= 3 and cuisine.isalpha():
                cuisines.append(Question("cuisine", f"{cuisine} restaurants in {city}", city, frozenset(sources)))
        private = [s for s in catalog.accommodations.get(key, []) if s.room_type == "Private room"]
        if len(private) >= 3:
            rooms.append(Question("private room", f"a private room to stay in {city}", city,
                                  frozenset(_source("accommodation", s.name, city) for s in private)))
        for a in catalog.attractions.get(key, []):
            if len(a.name.split()) >= 3:
                named.append(Question("named place", a.name, city, frozenset({_source("attraction", a.name, city)})))
    for group in (museums, rng.sample(cuisines, min(len(cuisines), 200)), rooms, named):
        pick(group)
    return questions


def score(sources: list[str], cities: list[str], question: Question) -> dict:
    """Hit, precision, reciprocal rank and wrong-city share for one ranked result list."""
    right = [source in question.relevant for source in sources]
    first = next((rank for rank, ok in enumerate(right, 1) if ok), None)
    return {
        "hit": float(any(right)),
        "precision": sum(right) / len(sources) if sources else 0.0,
        "reciprocal_rank": 1 / first if first else 0.0,
        "wrong_city": sum(c != question.city for c in cities) / len(cities) if cities else 0.0,
    }


def strategy_plans(question: str, plan: SearchPlan) -> dict[str, SearchPlan]:
    """The four strategies as search plans, all from one LLM plan."""
    return {
        "vector": SearchPlan(queries=[question]),
        "+ filters": SearchPlan(queries=[question], category=plan.category, city=plan.city),
        "+ multi-query": SearchPlan(queries=plan.queries),
        "full": plan,
    }


def summarise(rows: list[dict]) -> dict:
    """Mean scores per strategy, overall and per question kind."""
    def mean(items: list[dict]) -> dict:
        keys = ("hit", "precision", "reciprocal_rank", "wrong_city")
        return {key: round(sum(i[key] for i in items) / len(items), 3) for key in keys} if items else {}
    kinds = sorted({row["kind"] for row in rows})
    return {
        strategy: {"overall": mean([r[strategy] for r in rows]),
                   **{kind: mean([r[strategy] for r in rows if r["kind"] == kind]) for kind in kinds}}
        for strategy in STRATEGIES
    }


def run(per_kind: int = QUESTIONS_PER_KIND) -> dict:
    catalog = load_catalog()
    questions = build_questions(catalog, per_kind)
    llm = get_llm()
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    rows = []
    for number, question in enumerate(questions, 1):
        replies: list = []
        plan = plan_search(question.text, llm, replies)
        for reply in replies:
            add_usage(usage, message_usage(config.OPENROUTER_MODEL, reply))
        row = {"kind": question.kind, "question": question.text, "city": question.city,
               "right_answers": len(question.relevant),
               "plan": {"queries": plan.queries, "category": plan.category, "city": plan.city}}
        for strategy, strategy_plan in strategy_plans(question.text, plan).items():
            documents = retrieve(question.text, plan=strategy_plan).documents
            row[strategy] = score([d.metadata["source"] for d in documents],
                                  [d.metadata["city"] for d in documents], question)
        rows.append(row)
        print(f"{number}/{len(questions)} {question.kind}: {question.text}", flush=True)
    return {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": config.OPENROUTER_MODEL,
            "k": config.RETRIEVAL_K, "questions": len(rows), "usage": usage, "summary": summarise(rows), "rows": rows}


def main() -> None:
    result = run()
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "retrieval.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {path}. Overall scores (k={result['k']}):")
    for strategy, scores in result["summary"].items():
        print(f"  {strategy:<14} {scores['overall']}")
    print(f"Model cost: ${result['usage']['cost_usd']:.4f}")


if __name__ == "__main__":
    main()
