"""Evaluation of TripMate's RAG system and trip plans (see docs/EVALUATION.md).

The result files live in evaluation/results/; the Benchmarks page reads them.
"""

from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def _slug(model: str) -> str:
    return model.replace("/", "-")


def ragas_results_path(model: str, judge: str | None = None, run: str | None = None) -> Path:
    """One RAGAS results file per answer model, e.g. results/ragas/anthropic-claude-haiku-5.5.json.
    Scores from another judge go in their own folder, results/ragas/judges/<judge>/, next to them.
    A named run (new answers, for example to check how stable the scores are) goes in
    results/ragas/runs/<run>/, so it never replaces the answers the other judges scored."""
    folder = RESULTS_DIR / "ragas" / "runs" / run if run else RESULTS_DIR / "ragas"
    return (folder / "judges" / _slug(judge) if judge else folder) / f"{_slug(model)}.json"
