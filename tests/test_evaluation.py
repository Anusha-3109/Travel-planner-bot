"""The evaluation's scoring functions, with small made-up inputs and no model calls."""

from types import SimpleNamespace

import pytest

from backend.rag.retriever import SearchPlan
from backend.travel_data.catalog import load_catalog
from evaluation import RESULTS_DIR, plans, ragas_results_path
from evaluation.retrieval import Question, build_questions, score, strategy_plans, summarise

QUESTION = Question("museums", "museums in Boston", "Boston",
                    frozenset({"attraction: Museum of Science, Boston", "attraction: Isabella Stewart Gardner Museum, Boston"}))


def test_retrieval_scores():
    sources = ["attraction: Swan Boats, Boston", "attraction: Museum of Science, Boston", "restaurant: Picco, Boston",
               "attraction: Isabella Stewart Gardner Museum, Boston"]
    result = score(sources, ["Boston", "Boston", "Cambridge", "Boston"], QUESTION)
    assert result == {"hit": 1.0, "precision": 0.5, "reciprocal_rank": 0.5, "wrong_city": 0.25}
    assert score([], [], QUESTION) == {"hit": 0.0, "precision": 0.0, "reciprocal_rank": 0.0, "wrong_city": 0.0}


def test_strategies_use_one_search_plan_differently():
    plan = SearchPlan(queries=["museums in Boston", "art museum Boston"], category="attraction", city="Boston")
    strategies = strategy_plans("museums in Boston", plan)
    assert strategies["vector"] == SearchPlan(queries=["museums in Boston"])
    assert strategies["+ filters"].queries == ["museums in Boston"] and strategies["+ filters"].city == "Boston"
    assert strategies["+ multi-query"].queries == plan.queries and strategies["+ multi-query"].city is None
    assert strategies["full"] is plan


def test_summary_is_the_mean_per_strategy_and_kind():
    def row(kind, value):
        scores = {"hit": value, "precision": value, "reciprocal_rank": value, "wrong_city": 0.0}
        return {"kind": kind, **{s: scores for s in ("vector", "+ filters", "+ multi-query", "full")}}
    summary = summarise([row("museums", 1.0), row("cuisine", 0.0)])
    assert summary["full"]["overall"]["hit"] == 0.5 and summary["full"]["museums"]["hit"] == 1.0


def test_questions_have_known_answers_from_the_catalog():
    questions = build_questions(load_catalog(), per_kind=3)
    assert {q.kind for q in questions} == {"museums", "cuisine", "private room", "named place"}
    assert all(q.relevant and all(s.endswith(f", {q.city}") for s in q.relevant) for q in questions)
    assert build_questions(load_catalog(), per_kind=3) == questions  # the same questions on every run


@pytest.fixture
def validation_csv(tmp_path):
    rows = ["org,dest,days,visiting_city_number,date,people_number,local_constraint,budget,query,level,reference_information"]
    for level, rule in (("easy", "None"), ("medium", "'pets'"), ("hard", "'pets'")):
        constraint = (f"\"{{'house rule': {rule}, 'cuisine': ['Indian'], 'room type': 'private room', "
                      f"'transportation': 'no flight'}}\"")
        rows.append(f"Washington,Myrtle Beach,3,1,\"['2022-03-13']\",2,{constraint},1400,old question,{level},[]")
        rows.append(f"Washington,Boston,5,2,\"['2022-03-13']\",2,{constraint},1400,five days,{level},[]")
    path = tmp_path / "validation.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def test_questions_keep_constraints_but_move_to_future_dates(validation_csv):
    rows = plans.select_questions(validation_csv, per_level=1)
    assert [r["level"] for r in rows] == ["easy", "medium", "hard"]  # only the 3-day trips
    easy, medium = rows[0], rows[1]
    assert easy["start"] == "2026-11-16" and medium["start"] == "2026-11-19"
    assert easy["house_rule"] is None and medium["house_rule"] == "pets"
    assert medium["cuisines"] == ["Indian"] and medium["transportation"] == "no flight"
    assert "2026-11-19 to 2026-11-21" in medium["question"] and "must allow pets" in medium["question"]
    assert "2022" not in medium["question"]


ROW = {"origin": "Washington", "destination": "Boston", "people": 1, "budget": 1400, "house_rule": None,
       "room_type": None, "cuisines": [], "transportation": None}
PLAN = {"people": 1, "budget": 900, "days": [
    {"day": 1, "city": "Boston", "transportation": {"mode": "flight", "origin": "Washington", "destination": "Boston"},
     "accommodation": "Shelly's Swan Room"},
    {"day": 2, "city": "Boston", "accommodation": "Shelly's Swan Room"},
    {"day": 3, "city": "Boston", "transportation": {"mode": "flight", "origin": "Boston", "destination": "Washington"}},
]}


def test_a_complete_plan_passes_with_the_dataset_budget():
    result = plans.score_plan(PLAN, ROW)
    checks = {c["check"]: c["passed"] for c in result["checks"]}
    assert result["delivered"] and result["passed"] and checks["travels out and back"]
    assert not result["budget_complete"]  # estimated flights have no price
    assert next(c for c in result["checks"] if c["check"] == "budget")["detail"].endswith(
        "so the real total is higher.")  # the dataset's budget of 1,400 is used, not the plan's 900


def test_wrong_plans_fail_the_trip_checks():
    wrong = {**PLAN, "people": 2, "days": PLAN["days"][:2]}
    checks = {c["check"]: c["passed"] for c in plans.score_plan(wrong, ROW)["checks"]}
    assert not checks["right number of days"] and not checks["travels out and back"]
    assert not checks["right number of travellers"]
    assert plans.score_plan(None, ROW) == {"delivered": False, "checks": [], "passed": False}


def test_the_final_costed_plan_is_used():
    calls = [SimpleNamespace(name="calculate_trip_cost", args={"plan": {"people": 1}}),
             SimpleNamespace(name="check_constraints", args={"plan": {"people": 2}}),
             SimpleNamespace(name="search_flights", args={})]
    assert plans.final_plan(calls) == {"people": 2}
    assert plans.final_plan([]) is None


def test_rates_follow_travelplanner_metrics():
    passed = {"score": plans.score_plan(PLAN, ROW), "usage": {"cost_usd": 0.02}}
    missing = {"score": plans.score_plan(None, ROW), "usage": {"cost_usd": 0.01}}
    summary = plans.rates([passed, missing])
    assert summary["delivery_rate"] == 0.5 and summary["final_pass_rate"] == 0.5
    assert summary["commonsense_pass_rate_micro"] == 1.0 and summary["cost_usd"] == 0.03
    assert plans.failed_checks([passed, missing]) == {}


def test_without_rag_removes_only_the_search_tool():
    from backend.agent import agent as agent_module
    before = [t.name for t in agent_module.TOOLS]
    with plans.without_rag():
        assert "search_destination_options" not in agent_module.TOOLS_BY_NAME
        assert len(agent_module.TOOLS) == len(before) - 1
    assert [t.name for t in agent_module.TOOLS] == before


def test_each_judge_has_its_own_ragas_results():
    assert ragas_results_path("openai/gpt-6-luna") == RESULTS_DIR / "ragas" / "openai-gpt-6-luna.json"
    assert ragas_results_path("openai/gpt-6-luna", "openai/gpt-6.1-sol") ==         RESULTS_DIR / "ragas" / "judges" / "openai-gpt-6.1-sol" / "openai-gpt-6-luna.json"
    assert ragas_results_path("openai/gpt-6-luna", "openai/gpt-6.1-sol", "repeat") ==         RESULTS_DIR / "ragas" / "runs" / "repeat" / "judges" / "openai-gpt-6.1-sol" / "openai-gpt-6-luna.json"
