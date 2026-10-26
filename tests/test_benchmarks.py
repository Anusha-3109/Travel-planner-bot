"""The Benchmarks page, with made-up result files in a temporary folder."""

import json

import pytest
from streamlit.testing.v1 import AppTest

import evaluation
from ui import benchmarks

HAIKU = "anthropic/claude-haiku-5.5"


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(benchmarks, "RESULTS_DIR", tmp_path)
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _scores(value):
    return {"hit": value, "precision": value / 2, "reciprocal_rank": value, "wrong_city": 0.0}


def _rates(plans, final):
    return {"plans": plans, "delivery_rate": 1.0, "hard_constraint_pass_rate_macro": 0.5,
            "commonsense_pass_rate_macro": 0.8, "final_pass_rate": final, "budget_fully_priced_rate": 0.4,
            "cost_usd": 0.4}


def _fill(results):
    _write(evaluation.ragas_results_path(HAIKU), {
        "questions": 15, "agent_cost_usd": 0.03, "median_seconds": 6.4,
        "summary": {"overall": {"faithfulness": 0.92, "answer_relevancy": 0.85, "context_precision": 0.7}}})
    _write(results / "retrieval.json", {"questions": 60, "k": 6, "summary": {
        s: {"overall": _scores(v), "museums": _scores(v)} for s, v in
        (("vector", 0.6), ("+ filters", 0.8), ("+ multi-query", 0.7), ("full", 0.9))}})
    _write(results / "plans.json", {
        "summary": {"all": _rates(18, 0.3), "easy": _rates(6, 0.5), "medium": _rates(6, 0.3), "hard": _rates(6, 0.1)},
        "rag_comparison": {"with_rag": _rates(6, 0.33), "without_rag": _rates(6, 0.17)},
        "failed_checks": {"house rule": 8, "budget": 2}, "live_searches_used": {"serpapi": 70},
        "run_at": "2026-10-27T10:00:00+00:00"})


def test_tables_are_built_from_the_result_files(results):
    assert benchmarks.model_table().empty
    _fill(results)
    models = benchmarks.model_table()
    assert list(models["Model"]) == ["Claude Haiku 5.5  ·  used by the app"]
    assert models.iloc[0]["Cost per question"] == "$0.0020" and models.iloc[0]["Time per question"] == "6.4 s"
    strategies = benchmarks.strategy_table(benchmarks.load(results / "retrieval.json"))
    assert strategies.iloc[-1]["Strategy"] == "full  ·  used by the app" and strategies.iloc[-1]["Hit rate"] == 0.9
    plans = benchmarks.plan_table(benchmarks.load(results / "plans.json"))
    assert list(plans["Questions"]) == ["All", "Easy", "Medium", "Hard"] and plans.iloc[3]["Final pass"] == 0.1


def _page():
    from ui import benchmarks
    benchmarks.render()


def test_page_explains_how_to_run_each_missing_evaluation(results):
    at = AppTest.from_function(_page, default_timeout=30)
    at.run()
    assert not at.exception
    messages = " ".join(i.value for i in at.info)
    assert "evaluation.ragas_eval" in messages and "evaluation.retrieval" in messages and "evaluation.plans" in messages


def test_page_shows_the_results(results):
    _fill(results)
    at = AppTest.from_function(_page, default_timeout=30)
    at.run()
    assert not at.exception and not at.info
    assert len(at.dataframe) == 5  # models, strategies, by kind, plans, with/without RAG
    assert any("Not measured yet: OpenAI GPT-6 Luna, Google Gemini 3.7 Flash" in c.value for c in at.caption)
