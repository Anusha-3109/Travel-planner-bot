"""The Benchmarks page: the evaluation results (evaluation/results/*.json) as tables.

Each section reads one results file. A section whose evaluation hasn't run yet says
how to run it, so the page works before, during and after the evaluation.
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from evaluation import RESULTS_DIR, ragas_results_path
from ui.settings import TESTED_MODEL

SCORE = st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)
STRATEGY_NOTES = {"vector": "the question alone", "+ filters": "the model's city and category filters",
                  "+ multi-query": "rewritten queries fused with RRF", "full": "queries, filters and RRF"}


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def model_table() -> pd.DataFrame:
    """One row per answer model with a RAGAS results file."""
    rows = []
    for model, (name, input_price, output_price) in config.MODELS.items():
        result = load(ragas_results_path(model))
        if not result:
            continue
        overall = result["summary"]["overall"]
        questions = result["questions"] or 1
        rows.append({
            "Model": name + ("  ·  used by the app" if model == config.OPENROUTER_MODEL else ""),
            "Faithfulness": overall.get("faithfulness"),
            "Answer relevancy": overall.get("answer_relevancy"),
            "Context precision": overall.get("context_precision"),
            "Cost per question": f"${result['agent_cost_usd'] / questions:.4f}",
            "Time per question": f"{result['median_seconds']:.1f} s" if result.get("median_seconds") else "—",
            "Price (in / out per M tokens)": f"${input_price:g} / ${output_price:g}" if input_price is not None else "—",
        })
    return pd.DataFrame(rows)


def strategy_table(result: dict) -> pd.DataFrame:
    rows = []
    for strategy, scores in result["summary"].items():
        overall = scores["overall"]
        rows.append({"Strategy": strategy + ("  ·  used by the app" if strategy == "full" else ""),
                     "What it uses": STRATEGY_NOTES.get(strategy, ""), "Hit rate": overall["hit"],
                     "Precision": overall["precision"], "MRR": overall["reciprocal_rank"],
                     "Wrong city": overall["wrong_city"]})
    return pd.DataFrame(rows)


def plan_table(result: dict) -> pd.DataFrame:
    labels = {"all": "All", "easy": "Easy", "medium": "Medium", "hard": "Hard"}
    rows = []
    for level, label in labels.items():
        rates = result["summary"].get(level)
        if rates:
            rows.append({"Questions": label, "Plans": rates["plans"], "Delivered": rates["delivery_rate"],
                         "Hard constraints": rates["hard_constraint_pass_rate_macro"],
                         "Common sense": rates["commonsense_pass_rate_macro"], "Final pass": rates["final_pass_rate"],
                         "Fully priced": rates["budget_fully_priced_rate"]})
    return pd.DataFrame(rows)


def _not_run(command: str) -> None:
    st.info(f"Not run yet. Run `{command}` to fill this in.", icon=":material/hourglass_top:")


def render() -> None:
    st.title("Benchmarks")
    st.caption("How well TripMate's retrieval, answers and trip plans do, and what each model costs. Scores are from "
               "the evaluation scripts in evaluation/ and the files they save.")

    st.subheader("What each model costs")
    st.caption("Knowledge-base questions answered by each model and judged with RAGAS (the judge is always "
               f"{config.MODELS[TESTED_MODEL][0]}). Cost and time are per question, with the knowledge-base search.")
    models = model_table()
    if models.empty:
        _not_run(".venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model <model>")
    else:
        st.dataframe(models, hide_index=True, width="stretch", column_config={
            "Faithfulness": SCORE, "Answer relevancy": SCORE, "Context precision": SCORE})
        missing = [name for model, (name, *_) in config.MODELS.items() if not ragas_results_path(model).exists()]
        if missing:
            st.caption(f"Not measured yet: {', '.join(missing)}.")

    st.subheader("Retrieval strategies")
    retrieval = load(RESULTS_DIR / "retrieval.json")
    if not retrieval:
        _not_run("python -m evaluation.retrieval")
    else:
        st.caption(f"{retrieval['questions']} questions with known answers from the catalog (museums, cuisines, "
                   f"private rooms and named places), {retrieval['k']} places per search. Each strategy adds one "
                   "RAG technique.")
        st.dataframe(strategy_table(retrieval), hide_index=True, width="stretch", column_config={
            "Hit rate": SCORE, "Precision": SCORE, "MRR": SCORE, "Wrong city": SCORE})
        with st.expander("By kind of question"):
            kinds = [kind for kind in retrieval["summary"]["full"] if kind != "overall"]
            st.dataframe(pd.DataFrame([
                {"Kind": kind, "Strategy": strategy, "Hit rate": scores[kind]["hit"],
                 "Precision": scores[kind]["precision"], "MRR": scores[kind]["reciprocal_rank"]}
                for kind in kinds for strategy, scores in retrieval["summary"].items()]),
                hide_index=True, width="stretch", column_config={"Hit rate": SCORE, "Precision": SCORE, "MRR": SCORE})

    st.subheader("Trip plans")
    plans = load(RESULTS_DIR / "plans.json")
    if not plans:
        _not_run("python -m evaluation.plans")
    else:
        st.caption("TravelPlanner validation questions moved to future dates and planned with live data, scored "
                   "against the dataset's own budget and constraints.")
        st.dataframe(plan_table(plans), hide_index=True, width="stretch", column_config={
            "Delivered": SCORE, "Hard constraints": SCORE, "Common sense": SCORE, "Final pass": SCORE,
            "Fully priced": SCORE})
        left, right = st.columns(2)
        with left, st.container(border=True, height="stretch"):
            st.markdown("**With and without the knowledge-base search**")
            comparison = plans["rag_comparison"]
            st.dataframe(pd.DataFrame([
                {"Agent": label, "Plans": rates["plans"], "Final pass": rates["final_pass_rate"],
                 "Common sense": rates["commonsense_pass_rate_macro"]}
                for label, rates in (("With RAG", comparison["with_rag"]), ("Without RAG", comparison["without_rag"]))]),
                hide_index=True, width="stretch", column_config={"Final pass": SCORE, "Common sense": SCORE})
        with right, st.container(border=True, height="stretch"):
            st.markdown("**Checks that failed most**")
            failed = plans["failed_checks"]
            if failed:
                st.bar_chart(pd.Series(failed, name="plans"), horizontal=True, color="#3b82f6")
            else:
                st.caption("Every check passed.")
        st.caption(f"Live searches used: {plans['live_searches_used']} · model cost "
                   f"${plans['summary']['all']['cost_usd']:.2f} · run {plans['run_at'][:10]}")

    st.subheader("How this was measured")
    st.markdown(
        "- **Retrieval:** questions are generated from the catalog with a fixed seed, so the right answers are "
        "known exactly. Hit rate counts questions with at least one right place in the results, precision the share "
        "of right places, MRR how high the first right place is, wrong city the share of places from another city.\n"
        "- **Answers (RAGAS):** the agent answers with only its knowledge-base search, and RAGAS checks each answer "
        "against the places it was given: faithfulness (claims supported by them), answer relevancy (it answers "
        "the question) and context precision (useful places ranked first).\n"
        "- **Trip plans:** delivered means a costed plan for the right number of days; hard constraints are budget, "
        "house rule, room type, cuisine and transport; common sense covers items that exist, no repeats, minimum "
        "nights, a stay every night, travelling out and back. These are TripMate's checks modelled on "
        "TravelPlanner's rules, not its official evaluator. Live Airbnb listings don't publish house rules, so "
        "plans with a house-rule constraint can't pass that check.\n"
        "- Results depend on live prices and change from run to run; the files keep each run's date.")
