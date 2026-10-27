"""Part 2: answer quality with RAGAS (faithfulness, answer relevancy, context precision).

Run in the evaluation environment (RAGAS needs an older openai package than the app):
    uv venv .venv-eval --python 3.12
    uv pip install --python .venv-eval/Scripts/python.exe -r requirements.txt -r requirements-eval.txt
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval                         (the default model)
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna --rejudge   (score the saved answers again)
    .venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna --rejudge --judge openai/gpt-6.1-sol
        (score the saved answers with another judge, saved in results/ragas/judges/, to compare judges)

The agent answers 15 knowledge-base questions (museums, cuisines and private rooms
in random cities, from the same generator as part 1) with only its knowledge-base
search tool, so every answer is built on retrieved places. RAGAS then judges each
answer against the places it was given, with the app's default model as judge
(or the model given with --judge):
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

import httpx
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
# Faithfulness lists every claim in an answer, which doesn't fit RAGAS's default reply length.
JUDGE_MAX_TOKENS = 8192
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


async def judge(rows: list[dict], judge_model: str = config.OPENROUTER_MODEL) -> float:
    """Scores each row in place. Returns what the judge's calls cost (OpenRouter's reported cost)."""
    cost = 0.0

    async def add_cost(response: httpx.Response) -> None:
        nonlocal cost
        await response.aread()
        try:
            cost += float((response.json().get("usage") or {}).get("cost") or 0)
        except ValueError:  # not JSON, for example an error page
            pass

    client = AsyncOpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL,
                         http_client=httpx.AsyncClient(timeout=120, event_hooks={"response": [add_cost]}))
    llm = llm_factory(judge_model, client=client, max_tokens=JUDGE_MAX_TOKENS)
    metrics = {"faithfulness": Faithfulness(llm=llm),
               "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=LocalEmbeddings()),
               "context_precision": ContextPrecisionWithoutReference(llm=llm)}
    for row in rows:
        if not row["contexts"]:
            continue
        inputs = {"user_input": row["question"], "response": row["answer"], "retrieved_contexts": row["contexts"]}
        row.pop("errors", None)
        for name, metric in metrics.items():
            arguments = {k: v for k, v in inputs.items() if k != "retrieved_contexts"} if name == "answer_relevancy" \
                else inputs
            try:
                row[name] = round(float((await metric.ascore(**arguments)).value), 3)
            except Exception as error:  # one failed judgement shouldn't stop the run
                row[name] = None
                row.setdefault("errors", []).append(f"{name}: {error}")
    return round(cost, 4)


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
    judge_cost = asyncio.run(judge(rows))
    seconds = sorted(r["seconds"] for r in rows)
    return {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
            "judge": config.OPENROUTER_MODEL, "judge_cost_usd": judge_cost, "questions": len(rows),
            "answered_from_retrieval": sum(bool(r["contexts"]) for r in rows),
            "agent_cost_usd": round(sum(r["agent_cost_usd"] or 0 for r in rows), 4),
            "median_seconds": seconds[len(seconds) // 2] if seconds else None,
            "summary": summarise(rows), "rows": rows}


def rejudge(result: dict, judge_model: str = config.OPENROUTER_MODEL) -> dict:
    """Score saved answers again (after changing the judge, or with another judge), without asking the
    model again. The saved scores are left out first, so a failed judgement can't keep an old score."""
    names = ("faithfulness", "answer_relevancy", "context_precision", "errors")
    rows = [{k: v for k, v in row.items() if k not in names} for row in result["rows"]]
    print(f"Judging with RAGAS ({judge_model})...", flush=True)
    judge_cost = asyncio.run(judge(rows, judge_model))
    return {**result, "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "judge": judge_model, "judge_cost_usd": judge_cost, "summary": summarise(rows), "rows": rows}


def summarise(rows: list[dict]) -> dict:
    names = ("faithfulness", "answer_relevancy", "context_precision")

    def mean(items: list[dict], name: str) -> float | None:
        values = [r[name] for r in items if r.get(name) is not None]
        return round(sum(values) / len(values), 3) if values else None
    summary = {"overall": {name: mean(rows, name) for name in names}}
    summary.update({kind: {name: mean([r for r in rows if r["kind"] == kind], name) for name in names}
                    for kind in KINDS})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Score knowledge-base answers with RAGAS.")
    parser.add_argument("--model", default=config.OPENROUTER_MODEL, choices=list(config.MODELS),
                        help="The model that writes the answers (the judge is always the default model)")
    parser.add_argument("--rejudge", action="store_true",
                        help="Score the saved answers for this model again instead of asking the model")
    parser.add_argument("--judge", help="Another judge model for --rejudge (default: the app's default model); "
                                         "its scores are saved separately, so the judges can be compared")
    args = parser.parse_args()
    if args.judge and not args.rejudge:
        parser.error("--judge scores saved answers, so it needs --rejudge")
    other_judge = args.judge if args.judge and args.judge != config.OPENROUTER_MODEL else None
    path = ragas_results_path(args.model, other_judge)
    if args.rejudge:
        saved = json.loads(ragas_results_path(args.model).read_text(encoding="utf-8"))
        result = rejudge(saved, other_judge or config.OPENROUTER_MODEL)
    else:
        result = run(args.model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {path}.")
    print(json.dumps(result["summary"], indent=1))


if __name__ == "__main__":
    main()
