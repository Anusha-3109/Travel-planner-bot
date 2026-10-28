"""The Benchmarks page, with made-up result files in a temporary folder."""

import json

import pytest
from streamlit.testing.v1 import AppTest

import evaluation
from frontend.pages import benchmarks

HAIKU = "anthropic/claude-haiku-5.5"
LUNA = "openai/gpt-6-luna"
SOL = "openai/gpt-6.1-sol"


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
        "failed_checks": {"house rule": 8, "budget": 2}, "live_searches_used": {"serpapi": 70, "google": 0},
        "run_at": "2026-10-27T10:00:00+00:00", "runs": [
            {"level": "hard", "origin": "Houston", "destination": "Pensacola", "start": "2027-01-03", "people": 2,
             "budget": 1400.0, "house_rule": "visitors", "room_type": None, "cuisines": ["Indian", "Chinese"],
             "transportation": "no self-driving", "usage": {"cost_usd": 0.0412},
             "score": {"delivered": True, "passed": False, "checks": [
                 {"check": "budget", "passed": True}, {"check": "house rule", "passed": False}]}}]})
    _write(results / "embeddings.json", PROBE)


def _check(city, kind):
    return {"city_hits": city, "kind_hits": kind, "questions": 10, "kind_share": kind / 10}


def _probe_model(cross_lingual, europe_direct, cost):
    return {"means": {"paraphrase": 0.8, "cross_lingual": cross_lingual, "city_differs": 0.69,
                      "category_differs": 0.73, "unrelated": 0.05}, "gap": 0.11, "cost_usd": cost,
            "retrieval": {"place_hits": 10, "place_questions": 10, "city_hits": 10, "city_questions": 10,
                          "mean_margin": 0.3},
            "languages": {"us": {s: _check(10, 10) for s in ("english", "german", "german_translated")},
                          "europe": {"english": _check(10, 10), "german": europe_direct,
                                     "german_translated": _check(10, 10)}}}


PROBE = {"run_at": "2026-10-28T12:00:00+00:00", "test_cities": ["Tulsa"] * 10, "places": 3031,
         "pairs_per_group": {"paraphrase": 10}, "translation_cost_usd": 0.002, "models": {
             "all-MiniLM-L6-v2": _probe_model(0.38, _check(6, 7), 0.0),
             "openai/text-embedding-3-small": _probe_model(0.67, _check(10, 10), 0.0036),
             "openai/text-embedding-3-large": _probe_model(0.73, _check(10, 10), 0.0233)}}


def test_embedding_probe_tables_and_dot_plot():
    table = benchmarks.probe_table(PROBE)
    assert list(table.columns)[0] == "Sentence group" and len(table) == 6  # five groups and the gap
    assert table.iloc[-1]["all-MiniLM-L6-v2 (the app, local)"] == 0.11
    assert len(benchmarks.probe_scores(PROBE)) == 15  # five groups for three models
    retrieval = benchmarks.probe_retrieval_table(PROBE)
    assert list(retrieval["Cost"]) == ["free", "$0.0036", "$0.0233"]
    languages = benchmarks.probe_language_table(PROBE)
    assert len(languages) == 6  # two city sets, three ways of searching
    row = languages.iloc[4]
    assert row["Search"] == "German, searched directly" and row["Cities"].startswith("Europe")
    assert row["MiniLM (the app)"] == "city 6/10 · kind 7/10"
    benchmarks.probe_dot_plot(PROBE).to_dict()  # builds without errors


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


def _ragas(faithfulness, per_answer, cost=None):
    return {"questions": 2, "agent_cost_usd": 0.004, "median_seconds": 5.0, "judge_cost_usd": cost,
            "summary": {"overall": {"faithfulness": faithfulness, "answer_relevancy": 0.9, "context_precision": 0.8}},
            "rows": [{"faithfulness": f, "answer_relevancy": 0.9, "context_precision": 0.8} for f in per_answer]}


def test_the_main_judge_is_shown_and_compared_with_the_first(results):
    _write(evaluation.ragas_results_path(HAIKU), _ragas(0.7, [0.6, 0.8]))
    _write(evaluation.ragas_results_path(LUNA), _ragas(0.9, [0.9, 0.9]))
    assert benchmarks.shown_judge() == HAIKU and benchmarks.judges_run() == [HAIKU]
    _write(evaluation.ragas_results_path(HAIKU, SOL), _ragas(0.8, [0.8, 0.8], cost=0.7))
    _write(evaluation.ragas_results_path(LUNA, SOL), _ragas(0.85, [0.9, 0.8], cost=0.5))
    assert benchmarks.shown_judge() == SOL
    assert list(benchmarks.model_table()["Faithfulness"]) == [0.8, 0.85]  # the main judge's scores
    judges = benchmarks.judge_table()
    assert list(judges["Judge"][:2]) == ["Claude Haiku 5.5  ·  judges itself", "OpenAI GPT-6.1 Sol"]
    agreement = benchmarks.judge_agreement().iloc[0]
    assert agreement["Judges"] == "Claude Haiku 5.5 vs OpenAI GPT-6.1 Sol"
    assert agreement["Faithfulness"] == "Same ranking · gap 0.08"  # (0.2 + 0 + 0 + 0.1) / 4
    assert benchmarks.judge_costs() == "OpenAI GPT-6.1 Sol $1.20"
    scores = benchmarks.judge_scores("faithfulness")
    assert list(scores["Judge"]) == ["Haiku 5.5", "GPT-6.1 Sol"] * 2
    assert list(scores["Score"]) == [0.7, 0.8, 0.9, 0.85]
    spec = benchmarks.judge_dot_plot("faithfulness").to_dict()
    assert [layer["mark"]["type"] for layer in spec["layer"]] == ["rule", "point"]


def test_a_fresh_run_shows_how_much_the_scores_change(results):
    _write(evaluation.ragas_results_path(HAIKU, SOL), _ragas(0.8, [0.8, 0.8]))
    _write(evaluation.ragas_results_path(LUNA, SOL), _ragas(0.9, [0.9, 0.9]))
    assert benchmarks.stability_table().empty and benchmarks.stability_summary() == ""
    _write(evaluation.ragas_results_path(HAIKU, SOL, "repeat"), _ragas(0.75, [0.7, 0.8]))
    _write(evaluation.ragas_results_path(LUNA, SOL, "repeat"), _ragas(0.92, [0.9, 0.94]))
    row = benchmarks.stability_table().iloc[0]
    assert row["Model"] == "Claude Haiku 5.5" and row["Faithfulness"] == "0.80 → 0.75 (-0.05)"
    assert benchmarks.stability_summary() == ("Largest change between the two runs: faithfulness 0.05, answer "
                                              "relevancy 0.00, context precision 0.00; the faithfulness ranking "
                                              "of the models stayed the same.")


def test_judge_comparison_switches_between_dot_plot_and_table(results):
    _write(evaluation.ragas_results_path(HAIKU), _ragas(0.7, [0.6, 0.8]))
    _write(evaluation.ragas_results_path(HAIKU, SOL), _ragas(0.8, [0.8, 0.8], cost=0.7))
    at = AppTest.from_function(_page, default_timeout=30)
    at.run()
    assert not at.exception
    assert at.button_group(key="judge-view").value == "Dot plot"
    tables = len(at.dataframe)
    at.button_group(key="judge-view").set_value("Table").run()
    assert not at.exception and len(at.dataframe) == tables + 1


def test_each_trip_lists_its_constraints_and_failed_checks(results):
    _fill(results)
    trip = benchmarks.trip_table(benchmarks.load(results / "plans.json")).iloc[0]
    assert trip["Trip"] == "Houston to Pensacola" and trip["Budget"] == "$1,400" and trip["Cost"] == "$0.041"
    assert trip["Constraints"] == "house rule: visitors; cuisines: Indian, Chinese; transport: no self-driving"
    assert trip["Result"] == "Failed" and trip["Failed checks"] == "house rule"


def test_key_results_and_search_counts_read_as_text(results):
    assert benchmarks.searches_text({"serpapi": 61, "google": 230, "exchange_rates": 0}) ==         "61 SerpApi searches, 230 Google Maps calls"
    _fill(results)
    items = benchmarks.key_results(benchmarks.model_table(), benchmarks.load(results / "retrieval.json"),
                                   benchmarks.load(results / "plans.json"))
    assert items == [("Retrieval hit rate", "90%", "wrong city 0%"), ("Best faithfulness", "0.92", "Claude Haiku 5.5"),
                     ("Plans delivered", "100%", "18 trips"), ("Plans passing every check", "30%", "house rules fail most")]


def _page():
    from frontend.pages import benchmarks
    benchmarks.render()


def test_page_explains_how_to_run_each_missing_evaluation(results):
    at = AppTest.from_function(_page, default_timeout=30)
    at.run()
    assert not at.exception
    messages = " ".join(i.value for i in at.info)
    assert "evaluation.ragas_eval" in messages and "evaluation.retrieval" in messages and "evaluation.plans" in messages
    assert "evaluation.embeddings" in messages


def test_page_shows_the_results(results):
    _fill(results)
    at = AppTest.from_function(_page, default_timeout=30)
    at.run()
    assert not at.exception and not at.info
    assert len(at.dataframe) == 8  # models, strategies, by kind, probe retrieval and German, plans, with/without RAG, each trip
    assert len(at.metric) == 4 and "70 SerpApi searches" in " ".join(c.value for c in at.caption)
    assert any("Not measured yet: OpenAI GPT-6 Luna, Google Gemini 3.7 Flash" in c.value for c in at.caption)
