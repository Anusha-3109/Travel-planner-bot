"""The Benchmarks page: the evaluation results (evaluation/results/*.json) as tables.

Each section reads one results file. A section whose evaluation hasn't run yet says
how to run it, so the page works before, during and after the evaluation.
"""

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from backend import config
from evaluation import RESULTS_DIR, ragas_results_path
from frontend.pages.settings import TESTED_MODEL

# The RAGAS judges: the first scored every run; the others scored the same saved answers again
# (ragas_eval --rejudge --judge). MAIN_JUDGE's scores are shown when they exist, as it's the
# stronger judge and isn't one of the models it judges.
FIRST_JUDGE = TESTED_MODEL
MAIN_JUDGE = "openai/gpt-6.1-sol"
JUDGES = {FIRST_JUDGE: "Claude Haiku 5.5", MAIN_JUDGE: "OpenAI GPT-6.1 Sol",
          "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5"}
METRICS = {"faithfulness": "Faithfulness", "answer_relevancy": "Answer relevancy",
           "context_precision": "Context precision"}
# One colour and shape per judge, in this order, so a judge looks the same for every metric
# (colours checked for colour-blind separation on the dark theme).
JUDGE_COLOURS = ["#3987e5", "#d95926", "#199e70"]
JUDGE_SHAPES = ["circle", "diamond", "triangle-up"]
SCORE = st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)
STRATEGY_NOTES = {"vector": "the question alone", "+ filters": "the model's city and category filters",
                  "+ multi-query": "rewritten queries fused with RRF", "full": "queries, filters and RRF"}


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def ragas_result(model: str, judge: str) -> dict | None:
    return load(ragas_results_path(model, None if judge == FIRST_JUDGE else judge))


def judges_run() -> list[str]:
    """The judges that have scored at least one model."""
    return [judge for judge in JUDGES if any(ragas_result(model, judge) for model in config.MODELS)]


def shown_judge() -> str:
    """MAIN_JUDGE once it has scored any model, otherwise the first judge."""
    return MAIN_JUDGE if MAIN_JUDGE in judges_run() else FIRST_JUDGE


def model_table(judge: str | None = None) -> pd.DataFrame:
    """One row per answer model with a RAGAS results file, scored by the shown judge."""
    judge = judge or shown_judge()
    rows = []
    for model, (name, input_price, output_price) in config.MODELS.items():
        result = ragas_result(model, judge)
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


def judge_table() -> pd.DataFrame:
    """Each model's scores under each judge that scored it."""
    rows = []
    for model, (name, *_) in config.MODELS.items():
        for judge, judge_name in JUDGES.items():
            result = ragas_result(model, judge)
            if result:
                overall = result["summary"]["overall"]
                rows.append({"Answer model": name, "Judge": judge_name + ("  ·  judges itself" if judge == model else ""),
                             **{label: overall.get(metric) for metric, label in METRICS.items()}})
    return pd.DataFrame(rows)


def _short(judge_name: str) -> str:
    """"OpenAI GPT-6.1 Sol" -> "GPT-6.1 Sol", so the chart legend fits a narrow window."""
    return judge_name.split(" ", 1)[1]


def judge_scores(metric: str) -> pd.DataFrame:
    """One row per answer model and judge with that metric's overall score, for the dot plot."""
    rows = [{"Answer model": name, "Judge": _short(judge_name), "Score": result["summary"]["overall"].get(metric)}
            for model, (name, *_) in config.MODELS.items() for judge, judge_name in JUDGES.items()
            if (result := ragas_result(model, judge))]
    return pd.DataFrame(rows)


def judge_dot_plot(metric: str) -> alt.Chart:
    """A row per answer model with a dot per judge; a line joins the lowest and highest dot, so its
    length is how much the judges disagree about that model."""
    scores = judge_scores(metric).dropna()
    models = list(dict.fromkeys(scores["Answer model"]))
    low = min(0.5, scores["Score"].min() - 0.05) if not scores.empty else 0.5
    scale = alt.Scale(domain=[round(low, 1), 1])
    x = alt.X("Score:Q", title=f"{METRICS[metric]} (0 to 1)", scale=scale)
    y = alt.Y("Answer model:N", title=None, sort=models, axis=alt.Axis(labelLimit=220))
    spread = alt.Chart(scores).mark_rule(color="#8b8f98", strokeWidth=2).encode(
        x=alt.X("min(Score):Q", scale=scale), x2="max(Score):Q", y=y)
    judges = [_short(name) for name in JUDGES.values()]
    dots = alt.Chart(scores).mark_point(size=140, filled=True, opacity=1).encode(
        x=x, y=y,
        color=alt.Color("Judge:N", title=None, scale=alt.Scale(domain=judges, range=JUDGE_COLOURS),
                        legend=alt.Legend(orient="top", labelLimit=200)),
        shape=alt.Shape("Judge:N", scale=alt.Scale(domain=judges, range=JUDGE_SHAPES)),
        tooltip=["Answer model:N", "Judge:N", alt.Tooltip("Score:Q", format=".3f")])
    return (spread + dots).properties(height=60 * len(models) + 40)


def judge_agreement() -> pd.DataFrame:
    """For each pair of judges: do they rank the models the same way, and how far apart are their
    scores for the same answer (mean absolute gap)? Only models both judges scored are compared."""
    rows = []
    judges = list(JUDGES)
    for index, first in enumerate(judges):
        for second in judges[index + 1:]:
            pairs = [(a, b) for a, b in ((ragas_result(m, first), ragas_result(m, second)) for m in config.MODELS)
                     if a and b]
            if len(pairs) < 2:
                continue
            row = {"Judges": f"{JUDGES[first]} vs {JUDGES[second]}"}
            for metric, label in METRICS.items():
                def ranking(results):
                    return sorted(range(len(results)), key=lambda i: -(results[i]["summary"]["overall"][metric] or 0))
                gaps = [abs(x[metric] - y[metric]) for a, b in pairs for x, y in zip(a["rows"], b["rows"])
                        if x.get(metric) is not None and y.get(metric) is not None]
                same = ranking([a for a, _ in pairs]) == ranking([b for _, b in pairs])
                row[label] = f"{'Same' if same else 'Different'} ranking · gap {sum(gaps) / len(gaps):.2f}"                     if gaps else "—"
            rows.append(row)
    return pd.DataFrame(rows)


def judge_costs() -> str:
    """What each extra judge cost for all the answers it scored (the first judge's cost wasn't recorded)."""
    parts = []
    for judge, judge_name in JUDGES.items():
        costs = [r["judge_cost_usd"] for r in (ragas_result(m, judge) for m in config.MODELS)
                 if r and r.get("judge_cost_usd") is not None]
        if costs and judge != FIRST_JUDGE:
            parts.append(f"{judge_name} ${sum(costs):.2f}")
    return ", ".join(parts)


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


SEARCH_NAMES = {"serpapi": "SerpApi searches", "google": "Google Maps calls", "exchange_rates": "exchange rate look-up"}


def searches_text(used: dict) -> str:
    return ", ".join(f"{count} {SEARCH_NAMES.get(name, name)}" for name, count in used.items() if count)


def _constraints(run: dict) -> str:
    parts = [f"house rule: {run['house_rule']}" if run.get("house_rule") else None,
             f"room: {run['room_type']}" if run.get("room_type") else None,
             f"cuisines: {', '.join(run['cuisines'])}" if run.get("cuisines") else None,
             f"transport: {run['transportation']}" if run.get("transportation") else None]
    return "; ".join(p for p in parts if p) or "none"


def trip_table(result: dict) -> pd.DataFrame:
    """One row per planned trip, with the checks it failed."""
    rows = []
    for run in result.get("runs", []):
        score = run["score"]
        failed = [c["check"] for c in score.get("checks", []) if not c["passed"]]
        rows.append({"Level": run["level"].capitalize(), "Trip": f"{run['origin']} to {run['destination']}",
                     "Start": run["start"], "People": run["people"], "Budget": f"${run['budget']:,.0f}",
                     "Constraints": _constraints(run),
                     "Result": "Passed" if score.get("passed") else ("Failed" if score.get("delivered") else "No plan"),
                     "Failed checks": ", ".join(failed) or "—",
                     "Cost": f"${run['usage']['cost_usd']:.3f}" if run.get("usage") else "—"})
    return pd.DataFrame(rows)


def key_results(models: pd.DataFrame, retrieval: dict | None, plans: dict | None) -> list[tuple[str, str, str]]:
    """(label, value, note) for the metrics row at the top, from whichever evaluations have run."""
    items = []
    if retrieval:
        full = retrieval["summary"]["full"]["overall"]
        items.append(("Retrieval hit rate", f"{full['hit']:.0%}", f"wrong city {full['wrong_city']:.0%}"))
    if not models.empty:
        best = models.loc[models["Faithfulness"].idxmax()]
        items.append(("Best faithfulness", f"{best['Faithfulness']:.2f}", best["Model"].split("  ·  ")[0]))
    if plans:
        rates = plans["summary"]["all"]
        items.append(("Plans delivered", f"{rates['delivery_rate']:.0%}", f"{rates['plans']} trips"))
        items.append(("Plans passing every check", f"{rates['final_pass_rate']:.0%}", "house rules fail most"
                      if max(plans["failed_checks"], key=plans["failed_checks"].get, default="") == "house rule"
                      else ""))
    return items


def _not_run(command: str) -> None:
    st.info(f"Not run yet. Run `{command}` to fill this in.", icon=":material/hourglass_top:")


def render() -> None:
    st.title("Benchmarks")
    st.caption("How well TripMate's retrieval, answers and trip plans do, and what each model costs. Scores are from "
               "the evaluation scripts in evaluation/ and the files they save.")

    models = model_table()
    retrieval = load(RESULTS_DIR / "retrieval.json")
    plans = load(RESULTS_DIR / "plans.json")
    if items := key_results(models, retrieval, plans):
        with st.container(horizontal=True):
            for label, value, note in items:
                st.metric(label, value, note or None, delta_color="off", delta_arrow="off", border=True)

    st.subheader("What each model costs")
    st.caption(f"Knowledge-base questions answered by each model and judged with RAGAS by {JUDGES[shown_judge()]}. "
               "Cost and time are per question, with the knowledge-base search.")
    if models.empty:
        _not_run(".venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model <model>")
    else:
        st.dataframe(models, hide_index=True, width="stretch", column_config={
            "Faithfulness": SCORE, "Answer relevancy": SCORE, "Context precision": SCORE})
        missing = [name for model, (name, *_) in config.MODELS.items() if not ragas_result(model, shown_judge())]
        if missing:
            st.caption(f"Not measured yet: {', '.join(missing)}.")
        if len(judges_run()) > 1:
            st.subheader("Judge comparison")
            st.caption("The same saved answers scored by different judges. Where the judges agree, the scores above "
                       "can be trusted; where they don't, the judge matters as much as the model.")
            with st.container(horizontal=True):
                view = st.segmented_control("View", ["Dot plot", "Table"], default="Dot plot", key="judge-view")
                if view != "Table":
                    metric = st.segmented_control("Metric", list(METRICS), default="faithfulness",
                                                  format_func=METRICS.get, key="judge-metric") or "faithfulness"
            if view == "Table":
                st.dataframe(judge_table(), hide_index=True, width="stretch", column_config={
                    label: SCORE for label in METRICS.values()})
            else:
                st.altair_chart(judge_dot_plot(metric))
                st.caption("Each dot is one judge's score for that model's answers; the grey line spans the lowest "
                           "and highest, so a longer line means the judges disagree more. Hover a dot for the value.")
            agreement = judge_agreement()
            if not agreement.empty:
                st.markdown("**Do the judges agree?**")
                st.dataframe(agreement, hide_index=True, width="stretch")
                st.caption("Gap: how far apart two judges score the same answer, on average (0 to 1). "
                           + (f"Judge cost for all answers: {judge_costs()}.".replace("$", r"\$") if judge_costs() else ""))

    st.subheader("Retrieval strategies")
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
        with st.expander("Each trip"):
            st.dataframe(trip_table(plans), hide_index=True, width="stretch")
        st.caption(f"Live searches used: {searches_text(plans['live_searches_used'])} · model cost "
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
