"""Evaluation of TripMate's RAG system and trip plans (see docs/EVALUATION.md).

The result files live in evaluation/results/; the Benchmarks page reads them.
"""

from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def ragas_results_path(model: str) -> Path:
    """One RAGAS results file per answer model, e.g. results/ragas/anthropic-claude-haiku-5.5.json."""
    return RESULTS_DIR / "ragas" / f"{model.replace('/', '-')}.json"
