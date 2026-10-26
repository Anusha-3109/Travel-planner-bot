"""Part 2: answer quality with RAGAS (faithfulness, answer relevancy, context precision).

Run in the evaluation environment (RAGAS needs an older openai package than the app):
    uv venv .venv-eval --python 3.12
    uv pip install --python .venv-eval/Scripts/python.exe -r requirements.txt -r requirements-eval.txt
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval                         (the default model)
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna

The agent answers 15 knowledge-base questions (museums, cuisines and private rooms
in random cities, from the same generator as part 1) with only its knowledge-base
search tool, so every answer is built on retrieved places. RAGAS then judges each
answer against the places it was given, with the app's default model as judge:
- faithfulness: the share of the answer's claims supported by the retrieved places
- answer relevancy: how well the answer addresses the question (it generates
  questions back from the answer and compares them with the real one, using the
  app's local embeddings)
- context precision: whether the retrieved places that matter are ranked first
"""

import argparse
import asyncio
import json
import random
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from openai import AsyncOpenAI
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerRelevancy, ContextPrecisionWithoutReference, Faithfulness

from backend import config
from backend.agent import agent as agent_module
from backend.rag.vectorstore import _embeddings
from backend.travel_data.catalog import load_catalog
from evaluation import ragas_results_path
from evaluation.retrieval import SEED, build_questions

PER_KIND = 5
KINDS = {"museums": "What museums can I visit in {city}?",
         "cuisine": "Which {text} can I try?",
         "private room": "Where can I book {text}?"}


class LocalEmbeddings(BaseRagasEmbedding):
    """The app's local all-MiniLM-L6-v2 embeddings, for RAGAS's answer relevancy."""

    def embed_text(self, text: str, **kwargs) -> list[float]:
        return _embeddings().embed_query(text)

    async def aembed_text(self, text: str, **kwargs) -> list[float]:
        return self.embed_text(text)


@contextmanager
def rag_only():
    """The agent with only its knowledge-base search tool, so answers come from retrieval."""
    tools, by_name = agent_module.TOOLS, agent_module.TOOLS_BY_NAME
    agent_module.TOOLS = [t for t in tools if t.name == "search_destination_options"]
    agent_module.TOOLS_BY_NAME = {t.name: t for t in agent_module.TOOLS}
    try:
        yield
    finally:
        agent_module.TOOLS, agent_module.TOOLS_BY_NAME = tools, by_name


def questions(per_kind: int = PER_KIND) -> list[dict]:
    pool = build_questions(load_catalog())
    rng = random.Random(SEED)
    picked = []
    for kind, template in KINDS.items():
        for question in rng.sample([q for q in pool if q.kind == kind], per_kind):
            picked.append({"kind": kind, "city": question.city,
                           "question": template.format(city=question.city, text=question.text)})
    return picked


async def judge(rows: list[dict]) -> None:
    client = AsyncOpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)
    llm = llm_factory(config.OPENROUTER_MODEL, client=client)
    metrics = {"faithfulness": Faithfulness(llm=llm),
               "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=LocalEmbeddings()),
               "context_precision": ContextPrecisionWithoutReference(llm=llm)}
    for row in rows:
        if not row["contexts"]:
            continue
        inputs = {"user_input": row["question"], "response": row["answer"], "retrieved_contexts": row["contexts"]}
        for name, metric in metrics.items():
            arguments = {k: v for k, v in inputs.items() if k != "retrieved_contexts"} if name == "answer_relevancy" \
                else inputs
            try:
                row[name] = round(float((await metric.ascore(**arguments)).value), 3)
            except Exception as error:  # one failed judgement shouldn't stop the run
                row[name] = None
                row.setdefault("errors", []).append(f"{name}: {error}")


def run(model: str = config.OPENROUTER_MODEL, per_kind: int = PER_KIND) -> dict:
    rows = []
    with rag_only():
        for number, item in enumerate(questions(per_kind), 1):
            print(f"{number}/{per_kind * len(KINDS)} {item['question']}", flush=True)
            started = time.monotonic()
            result = agent_module.run_agent(item["question"], currency="USD", model=model)
            rows.append({**item, "answer": result.answer, "contexts": [s["content"] for s in result.sources],
                         "agent_cost_usd": result.token_usage.get("cost_usd"),
                         "seconds": round(time.monotonic() - started, 1)})
    print("Judging with RAGAS...", flush=True)
    asyncio.run(judge(rows))
    names = ("faithfulness", "answer_relevancy", "context_precision")

    def mean(items: list[dict], name: str) -> float | None:
        values = [r[name] for r in items if r.get(name) is not None]
        return round(sum(values) / len(values), 3) if values else None
    summary = {"overall": {name: mean(rows, name) for name in names}}
    summary.update({kind: {name: mean([r for r in rows if r["kind"] == kind], name) for name in names}
                    for kind in KINDS})
    seconds = sorted(r["seconds"] for r in rows)
    return {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
            "judge": config.OPENROUTER_MODEL, "questions": len(rows),
            "answered_from_retrieval": sum(bool(r["contexts"]) for r in rows),
            "agent_cost_usd": round(sum(r["agent_cost_usd"] or 0 for r in rows), 4),
            "median_seconds": seconds[len(seconds) // 2] if seconds else None,
            "summary": summary, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Score knowledge-base answers with RAGAS.")
    parser.add_argument("--model", default=config.OPENROUTER_MODEL, choices=list(config.MODELS),
                        help="The model that writes the answers (the judge is always the default model)")
    model = parser.parse_args().model
    result = run(model)
    path = ragas_results_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {path}.")
    print(json.dumps(result["summary"], indent=1))


if __name__ == "__main__":
    main()
