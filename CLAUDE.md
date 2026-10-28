# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TripMate is a Turing College Sprint 2 project (task description in `125.md`): a travel-planning RAG chatbot built with LangChain, OpenRouter and Streamlit, deployed on Google Cloud Run. The README is the full user-facing documentation; `docs/EVALUATION.md` and `docs/REFLECTION.md` cover the evaluation and the project history.

## Commands

```bash
streamlit run app.py                              # run the app at http://localhost:8501
python -m pytest -q                               # full suite (~1.5 min); what CI runs
python -m pytest tests/test_trips.py -q           # one file
python -m pytest tests/test_trips.py::test_unknown_trip_says_so -q   # one test
python -m backend.rag.ingest                      # rebuild the Chroma index in .chroma/
```

- Python 3.12, virtualenv in `.venv` (Windows: `.venv\Scripts\activate`). Keys go in `.env` (copy `.env.example`); only `OPENROUTER_API_KEY` is required, SerpApi and Google Maps keys are optional (the app falls back to snapshot data).
- Streamlit keeps old modules in memory: restart the app after changing code, don't rely on its reload.
- Evaluation scripts (`evaluation/`) write to `evaluation/results/`, which the Benchmarks page reads. RAGAS needs its own environment, `.venv-eval` (`requirements-eval.txt`); see the README's Evaluation section. Retrieval, RAGAS and plan runs cost money (OpenRouter, SerpApi): say what a run will cost before starting one.

## Architecture

- **`frontend/` draws, `backend/` decides.** `backend/` has no Streamlit imports, so it is tested and evaluated on its own. `app.py` handles sign-in and routes to `frontend/pages/` (chat, trips, benchmarks, dashboard, how_it_answers, settings).
- **Agent** (`backend/agent/agent.py`): a hand-written LangChain tool loop over an OpenRouter model (`llm.py`, `ChatOpenAI` pointed at OpenRouter), at most `MAX_AGENT_STEPS` steps. The system prompt holds the planning rules and answer formats. A cost guard sends the model back once if it writes a full plan without calling `calculate_trip_cost` and `check_constraints`. Plan mode offers all 7 tools; Explore mode only the place, restaurant and transport tools.
- **Tools** (`backend/tools/`): live first (`backend/live/`: SerpApi for Google Flights, Airbnb and Google Hotels; Google Places and Routes; exchange rates), falling back to the 2026 snapshot (`backend/travel_data/`, files in `data/world/`) when a key is missing, a date is in the past or a call fails, and saying so. Live calls are cached in SQLite (`backend/live/cache.py`) and limited per chat (`backend/live/budget.py`).
- **Prices never come from the model.** Every live result has an `id`; the cost tool looks prices up by id (or exact snapshot name). Tools return ready-made display strings (`price_text`, `rating_text`, `cost_text`, …) for the model to copy, because small models reformat numbers inconsistently. Keep both properties when changing tools.
- **RAG** (`backend/rag/`): one Chroma document per place (no chunking), local all-MiniLM-L6-v2 embeddings. Retrieval = query translation into 2–3 searches + `city`/`category` metadata filters + reciprocal rank fusion. Ingest replaces places whose text changed (ids come from the source, not the text).
- **Security** (`backend/security/`): user input is validated before the model sees it; tool output from outside sources is screened for injected instructions (`tool_output.py`); keys are redacted from all logs (`redaction.py`). A test scans committed files for key patterns.
- **Result cards** (`frontend/components/cards.py`) are drawn from the tools' JSON, not from the model's text. Their buttons ("Use this stay", "Add to the plan") send a follow-up message naming the option's live id, so the agent swaps exactly that item.
- **Storage** (`backend/storage/history.py`): chats, request log, trips and trip extras in `.history/chats.sqlite3` (`HISTORY_DIR` moves it; on Cloud Run it's a mounted bucket, so only one instance may write). Every row has an owner — a sha256 hash of the Google email, or `local` without sign-in — and reads filter by it. `trips.py` builds a saved trip only from a costed plan's tool results.

## Frontend conventions

- Two themes in `.streamlit/config.toml` (`[theme.dark]` Graphite amber, `[theme.light]` Light amber), switched in Streamlit's ⋮ menu. A theme switch doesn't rerun the app, so `frontend/html/theme.css` derives every colour from `currentColor` (`color-mix`) and sets no fixed `background-color: #…`; `tests/test_trips.py` enforces this. Python-side colours (charts, maps) come from `frontend/components/palette.py`.
- `theme.css` must not contain `<` — Streamlit's HTML cleaner drops the whole style block.
- Display-only HTML lives in `frontend/html/` (templates rendered by `render.py`), which escapes every value and only links to http(s).
- Escape `$` in captions and labels with amounts, or Streamlit renders the text between two `$` as maths.
- English and German: text on the chat page, trip form, result cards, sidebar and Settings goes through `t("key")` from `frontend/i18n.py`, with both languages for every key (`tests/test_i18n.py` checks this). Benchmarks, Dashboard, How it answers and the trip pages are English only. Tool inputs and knowledge-base searches stay in English whatever the language.

## Tests

- `tests/conftest.py` blanks the live API keys, points the cache and history DBs at a temp dir and resets the per-chat budget for every test, so tests never make real calls. Live clients are tested against recorded responses in `tests/fixtures/`; tests that need the index use the session-scoped `small_index` fixture (two cities).
- Page tests use `streamlit.testing.v1.AppTest`.
- `legacy/` is the first version's code, kept for reference only.

## Deployment and git

- Every push to `main` runs `.github/workflows/tests.yml` and then `deploy.yml`: Docker image (knowledge base built into it, ~40 min) → Artifact Registry → Cloud Run service `tripmate` in `europe-west1`. Secrets live in Secret Manager; Google sign-in settings are mounted at `/secrets/streamlit/secrets.toml`.
- Two remotes: `origin` (GitHub, drives the deploy) and `turing` (course submission). Push to both.
- Commits are numbered steps, one topic each: `Step N: short description`.
