"""Part 3: full trip plans on TravelPlanner validation questions, with 2026 live data.

Run:  python -m evaluation.plans             (needs the API keys in .env)
      python -m evaluation.plans --dry-run   (only print the questions)

TravelPlanner's questions are dated March 2022 and their answers are 2022 places,
so only their structure is kept: origin, destination, trip length, travellers,
budget and constraints (house rule, cuisine, room type, transport). Each trip is
moved to a future date (from START, three days apart) and planned by the agent
with live flights, stays and restaurants. 3-day trips are used, so every
question has one destination city; the sample has the same number of easy,
medium and hard questions (harder ones add constraints).

Each plan is scored with the app's own checks, but with the dataset's budget,
traveller count and constraints, not the ones the model read from the question,
plus three TravelPlanner-style checks: the plan has the right number of days, it
flies out from the origin and back, and it stays in the destination. These are
TripMate's checks modelled on TravelPlanner's rules, not its official evaluator.

A few questions run a second time without the knowledge-base search tool, to see
what retrieval adds to plans.
"""

import argparse
import ast
import json
import random
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from backend import config
from backend.agent import agent as agent_module
from backend.agent.trip_request import trip_question
from backend.live.budget import SessionBudget, use_budget
from backend.tools.planning import check_plan
from evaluation import RESULTS_DIR

QUESTIONS_FILE = config.TRAVELPLANNER_DIR / "validation.csv"
PER_LEVEL = 6
WITHOUT_RAG_PER_LEVEL = 2
START = date(2026, 11, 16)
SEED = 2026
TRIP_DAYS = 3
EVAL_LIMITS = {"serpapi": 200, "google": 400}  # the whole evaluation, not one chat


def select_questions(path: Path = QUESTIONS_FILE, per_level: int = PER_LEVEL, seed: int = SEED) -> list[dict]:
    """per_level 3-day questions of each level, the same ones on every run."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python -m backend.travel_data.download")
    data = pd.read_csv(path)
    rows = []
    for level in ("easy", "medium", "hard"):
        pool = data[(data["level"] == level) & (data["days"] == TRIP_DAYS)]
        picked = pool.sample(n=min(per_level, len(pool)), random_state=seed)
        for _, row in picked.iterrows():
            rules = ast.literal_eval(row["local_constraint"])
            rows.append({"level": level, "origin": row["org"], "destination": row["dest"],
                         "people": int(row["people_number"]), "budget": float(row["budget"]),
                         "house_rule": rules.get("house rule"), "room_type": rules.get("room type"),
                         "cuisines": list(rules.get("cuisine") or []), "transportation": rules.get("transportation"),
                         "original_question": row["query"]})
    for number, row in enumerate(rows):
        row["start"] = (START + timedelta(days=3 * number)).isoformat()
        row["question"] = trip_question(row["origin"], row["destination"], date.fromisoformat(row["start"]),
                                        TRIP_DAYS - 1, row["people"], row["budget"], "USD", "Airbnb",
                                        row["house_rule"], row["room_type"], row["cuisines"], row["transportation"])
    return rows


def final_plan(tool_calls) -> dict | None:
    """The last plan the agent costed or checked."""
    for call in reversed(tool_calls):
        if call.name in ("check_constraints", "calculate_trip_cost") and isinstance(call.args.get("plan"), dict):
            return call.args["plan"]
    return None


def _same(a: str | None, b: str) -> bool:
    return (a or "").strip().lower() == b.strip().lower()


def score_plan(plan: dict | None, row: dict) -> dict:
    """The plan checked against the dataset's own requirements."""
    if not plan or not plan.get("days"):
        return {"delivered": False, "checks": [], "passed": False}
    truth = {**plan, "people": row["people"], "budget": row["budget"], "currency": "USD",
             "constraints": {"house_rule": row["house_rule"], "room_type": row["room_type"],
                             "cuisines": row["cuisines"], "transportation": row["transportation"]}}
    try:
        checked = check_plan(truth)
    except Exception as error:  # a plan the checker can't read counts as not delivered
        return {"delivered": False, "checks": [], "passed": False, "error": str(error)}
    days = sorted(plan["days"], key=lambda d: d.get("day", 0))
    first, last = days[0].get("transportation") or {}, days[-1].get("transportation") or {}
    route = (first.get("mode") == "transit" or _same(first.get("origin"), row["origin"]) or first.get("item_id")) and \
            (_same(last.get("destination"), row["origin"]) or bool(last.get("item_id")))
    trip = [
        {"check": "right number of days", "passed": len(days) == TRIP_DAYS, "detail": f"{len(days)} day(s)"},
        {"check": "travels out and back", "passed": bool(first and last and route),
         "detail": "Transport on the first and last day, from and back to the origin."},
        {"check": "stays in the destination", "passed": any(_same(d.get("city"), row["destination"]) for d in days),
         "detail": f"A day in {row['destination']}."},
        {"check": "right number of travellers", "passed": plan.get("people") == row["people"],
         "detail": f"Plan has {plan.get('people')}, the question {row['people']}."},
    ]
    hard = [{**c, "type": "hard"} for c in checked["hard_constraints"]]
    commonsense = [{**c, "type": "commonsense"} for c in checked["commonsense_checks"] + trip]
    checks = hard + commonsense
    return {"delivered": True, "checks": checks, "passed": all(c["passed"] for c in checks),
            "hard_passed": all(c["passed"] for c in hard), "commonsense_passed": all(c["passed"] for c in commonsense),
            "budget_complete": checked["cost"]["budget_check_complete"], "total_usd": checked["cost"]["total_cost"]}


@contextmanager
def without_rag():
    """The agent without its knowledge-base search tool."""
    tools, by_name = agent_module.TOOLS, agent_module.TOOLS_BY_NAME
    agent_module.TOOLS = [t for t in tools if t.name != "search_destination_options"]
    agent_module.TOOLS_BY_NAME = {t.name: t for t in agent_module.TOOLS}
    try:
        yield
    finally:
        agent_module.TOOLS, agent_module.TOOLS_BY_NAME = tools, by_name


def run_one(row: dict, budget: SessionBudget) -> dict:
    with use_budget(budget):
        try:
            result = agent_module.run_agent(row["question"], currency="USD")
        except Exception as error:
            return {"error": str(error), "score": score_plan(None, row), "usage": {}}
    plan = final_plan(result.tool_calls)
    return {"score": score_plan(plan, row), "plan": plan, "usage": result.token_usage,
            "tools": [c.name for c in result.tool_calls], "answer": result.answer[:3000]}


def rates(runs: list[dict]) -> dict:
    """TravelPlanner's metrics: delivery, hard and commonsense pass rates, final pass rate."""
    n = len(runs) or 1
    scores = [r["score"] for r in runs]
    checks = [c for s in scores for c in s["checks"]]

    def share(kind: str) -> float:
        items = [c for c in checks if c["type"] == kind]
        return round(sum(c["passed"] for c in items) / len(items), 3) if items else 0.0
    return {"plans": len(runs), "delivery_rate": round(sum(s["delivered"] for s in scores) / n, 3),
            "hard_constraint_pass_rate_micro": share("hard"),
            "commonsense_pass_rate_micro": share("commonsense"),
            "hard_constraint_pass_rate_macro": round(sum(s.get("hard_passed", False) for s in scores) / n, 3),
            "commonsense_pass_rate_macro": round(sum(s.get("commonsense_passed", False) for s in scores) / n, 3),
            "final_pass_rate": round(sum(s["passed"] for s in scores) / n, 3),
            "budget_fully_priced_rate": round(sum(s.get("budget_complete", False) for s in scores) / n, 3),
            "cost_usd": round(sum((r.get("usage") or {}).get("cost_usd") or 0 for r in runs), 4)}


def failed_checks(runs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        for check in run["score"]["checks"]:
            if not check["passed"]:
                counts[check["check"]] = counts.get(check["check"], 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def run(per_level: int = PER_LEVEL, without_rag_per_level: int = WITHOUT_RAG_PER_LEVEL) -> dict:
    rows = select_questions(per_level=per_level)
    budget = SessionBudget(limits=dict(EVAL_LIMITS))
    runs = []
    for number, row in enumerate(rows, 1):
        print(f"{number}/{len(rows)} {row['level']}: {row['origin']} → {row['destination']} on {row['start']}", flush=True)
        runs.append({**row, **run_one(row, budget)})
    rng = random.Random(SEED)
    ablation_rows = [r for level in ("easy", "medium", "hard")
                     for r in rng.sample([x for x in rows if x["level"] == level], without_rag_per_level)]
    ablation = []
    with without_rag():
        for number, row in enumerate(ablation_rows, 1):
            print(f"without RAG {number}/{len(ablation_rows)}: {row['origin']} → {row['destination']}", flush=True)
            ablation.append({**row, **run_one(row, budget)})
    with_rag_same = [next(r for r in runs if r["question"] == a["question"]) for a in ablation]
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": config.OPENROUTER_MODEL,
        "live_searches_used": budget.used,
        "summary": {"all": rates(runs), **{level: rates([r for r in runs if r["level"] == level])
                                           for level in ("easy", "medium", "hard")}},
        "failed_checks": failed_checks(runs),
        "rag_comparison": {"with_rag": rates(with_rag_same), "without_rag": rates(ablation)},
        "runs": runs, "without_rag_runs": ablation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate full trip plans on TravelPlanner questions.")
    parser.add_argument("--dry-run", action="store_true", help="Print the questions without running the agent")
    arguments = parser.parse_args()
    if arguments.dry_run:
        for row in select_questions():
            print(f"[{row['level']}] {row['question']}")
        return
    result = run()
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "plans.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nSaved {path}.")
    print(json.dumps(result["summary"], indent=1))
    print("RAG comparison:", json.dumps(result["rag_comparison"], indent=1))
    print("Live searches used:", result["live_searches_used"])


if __name__ == "__main__":
    main()
