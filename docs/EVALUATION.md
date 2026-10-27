# Evaluation

How well TripMate finds places, answers from them and plans whole trips, measured on the 2026 knowledge base (54,309 places in 245 cities) and live 2026 data. All runs are from 26 October 2026. The result files are in [`evaluation/results/`](../evaluation/results), and the app's **Benchmarks** page shows them.

## Contents

- [Summary](#summary)
- [Part 1: Retrieval](#part-1-retrieval)
- [Part 2: Answer quality (RAGAS)](#part-2-answer-quality-ragas)
- [Part 3: Trip plans](#part-3-trip-plans)
- [What it cost](#what-it-cost)
- [Limitations](#limitations)
- [How to run it again](#how-to-run-it-again)

## Summary

| Part | What it measures | Main result |
|---|---|---|
| 1. Retrieval | Does the search find the right places? | The app's strategy finds a right place for **96.7%** of questions, with **12%** of places from the wrong city (29% with plain vector search) |
| 2. Answers (RAGAS) | Are answers built on what was found? | Faithfulness **0.90** for GPT-6 Luna, **0.85** for Gemini 3.7 Flash and **0.81** for Haiku (judged by GPT-6.1 Sol), after a prompt fix the evaluation found; two other judges rank Haiku last too |
| 3. Trip plans | Does a full plan meet the traveller's rules? | **100%** of 18 plans delivered, **39%** pass every check, **72%** if the house-rule check is left out |

## Part 1: Retrieval

**Script:** [`evaluation/retrieval.py`](../evaluation/retrieval.py) · **Results:** [`results/retrieval.json`](../evaluation/results/retrieval.json)

### Method

- **60 questions with known answers**, generated from the catalog with a fixed seed, 15 of each kind:
  - *museums:* "museums in Memphis": every museum in that city is a right answer
  - *cuisine:* "barbecue restaurants in Sacramento": every restaurant there with that cuisine
  - *private room:* "a private room to stay in Fort Dodge": every private room there
  - *named place:* "Neuberger Museum of Art": that one place
- **Four strategies**, each adding one RAG technique, all returning 6 places:
  1. *vector:* the question alone, plain similarity search
  2. *+ filters:* the model's city and category filters
  3. *+ multi-query:* the model's rewritten queries fused with reciprocal rank fusion (RRF), no filters
  4. *full:* queries, filters and RRF, which is what the app uses
- The model (Claude Haiku 5.5) makes one search plan per question, shared by strategies 2 to 4, so they differ only in how the plan is used.
- **Scores:**
  - *hit rate:* at least one right place
  - *precision:* the share of right places
  - *MRR:* 1 / rank of the first right place
  - *wrong city:* the share of places from another city

### Results

| Strategy | Hit rate | Precision | MRR | Wrong city |
|---|---|---|---|---|
| vector | 93.3% | 0.569 | 0.851 | 28.9% |
| + filters | 95.0% | 0.627 | **0.889** | 12.5% |
| + multi-query | 93.3% | 0.572 | 0.831 | 26.4% |
| **full (the app)** | **96.7%** | **0.630** | 0.867 | **12.2%** |

By kind of question (vector → full):

| Kind | Hit rate | Precision | Wrong city |
|---|---|---|---|
| Cuisine | 80% → 93% | 0.29 → 0.44 | 47% → 0% |
| Museums | 100% → 100% | 0.84 → 0.92 | 12% → 0% |
| Private room | 100% → 100% | 0.99 → 1.00 | 1% → 0% |
| Named place | 93% → 93% | 0.16 → 0.16 | 56% → 49% |

### What it shows

- **City and category filters do most of the work:** they remove almost every place from the wrong city, and cuisine questions gain the most.
- **Multi-query alone doesn't help**, but with filters it finds the 2 cuisine questions that filters alone missed.
- **Rank fusion costs a little ranking:** the full strategy's MRR (0.867) is below filters alone (0.889), as fusion sometimes moves the first right place down one spot.
- **Named places:** precision can't go above 1 in 6, because only one place is right, and the question names no city, so "wrong city" there isn't an error.
- **The main risk of filters is a wrong city guess:** for "Imaginarium of South Texas" (in Laredo) the model guessed Corpus Christi, and the filter hid the right place, which plain vector search found.

## Part 2: Answer quality (RAGAS)

**Script:** [`evaluation/ragas_eval.py`](../evaluation/ragas_eval.py) · **Results:** [`results/ragas/`](../evaluation/results/ragas)

### Method

- **15 knowledge-base questions** (5 museums, 5 cuisine, 5 private room) from the same generator as part 1.
- Each of the three app models answers with **only the knowledge-base search tool**, so every answer is built on retrieved places.
- **RAGAS 0.4.3** scores each answer against the places it was given:
  - *faithfulness:* the share of the answer's claims supported by the retrieved places
  - *answer relevancy:* whether the answer addresses the question (local all-MiniLM-L6-v2 embeddings)
  - *context precision:* whether the useful places are ranked first
- **The judge is OpenAI GPT-6.1 Sol**, a larger model that isn't one of the three it judges. The answers were first judged by Claude Haiku 5.5, then scored again by GPT-6.1 Sol and Claude Sonnet 5.5 to compare the judges (see [Does the judge matter?](#does-the-judge-matter)).

### Results

Judged by GPT-6.1 Sol:

| Model | Faithfulness | Answer relevancy | Context precision | Cost per question | Median time |
|---|---|---|---|---|---|
| Claude Haiku 5.5 (the app's default) | 0.810 | 0.846 | **0.988** | $0.0012 | 8.7 s |
| OpenAI GPT-6 Luna | **0.901** | 0.901 | 0.967 | **$0.0003** | 8.2 s |
| Google Gemini 3.7 Flash | 0.850 | **0.931** | 0.978 | $0.0058 | 9.5 s |

By kind of question (faithfulness):

| Model | Museums | Cuisine | Private room |
|---|---|---|---|
| Claude Haiku 5.5 | 0.84 | 0.74 | 0.85 |
| OpenAI GPT-6 Luna | 0.95 | 0.96 | 0.80 |
| Google Gemini 3.7 Flash | 0.94 | 0.72 | 0.89 |

- **GPT-6 Luna writes the most faithful answers** and is also the cheapest, at $0.0003 per question.
- **Gemini's answers are the most relevant**, but cost about 20 times more than GPT-6 Luna's.
- **Haiku is last on faithfulness and answer relevancy** with every judge. It stays the app's default because the app's planning rules were developed and tested with it, and part 3's trip plans use it; GPT-6 Luna is a strong cheaper option for knowledge-base questions.

### A prompt fix found by the evaluation

The first run (judged by Haiku) scored faithfulness at about 0.7 for every model. The answers named only retrieved places, but added descriptions from the model's own knowledge, such as "honouring veterans across various eras" for a military museum. RAGAS counts every claim that isn't in the retrieved text as unsupported, even a true one.

A rule was added to the system prompt ([`backend/agent/agent.py`](../backend/agent/agent.py)): describe knowledge-base places only with what the results say. Then all three models answered again. Judged by Haiku, before and after:

| Model | Faithfulness before → after | Answer relevancy before → after |
|---|---|---|
| Claude Haiku 5.5 | 0.702 → 0.706 | 0.850 → 0.862 |
| OpenAI GPT-6 Luna | 0.793 → **0.894** | 0.925 → 0.901 |
| Google Gemini 3.7 Flash | 0.696 → **0.885** | 0.932 → 0.937 |

- **GPT-6 Luna and Gemini follow the rule:** Gemini's museum answers went from 0.51 to 0.91, and GPT-6 Luna's cuisine answers from 0.62 to 0.94.
- **Answer relevancy stayed about the same**, so the shorter answers still answer the question.
- **Haiku barely changed.** Part of its low score is the wording of the data: Haiku calls OpenStreetMap hotels "hotels", while the knowledge-base text says "private room", the room type they're stored under.

### Does the judge matter?

Haiku is the smallest of the models and judged its own answers, so the same 45 saved answers were scored again by two stronger judges. Only the judge changes, so every difference comes from the judge.

Faithfulness by judge:

| Answer model | Judged by Haiku 5.5 | Judged by GPT-6.1 Sol | Judged by Sonnet 5.5 |
|---|---|---|---|
| Claude Haiku 5.5 | 0.706 (itself) | 0.810 | 0.742 |
| OpenAI GPT-6 Luna | **0.894** | **0.901** | 0.770 |
| Google Gemini 3.7 Flash | 0.885 | 0.850 | **0.853** |

Do the judges agree?

| Judges | Faithfulness | Answer relevancy | Context precision |
|---|---|---|---|
| Haiku vs GPT-6.1 Sol | Same ranking · gap 0.07 | Same ranking · gap 0.02 | Different ranking · gap 0.07 |
| Haiku vs Sonnet | Different ranking · gap 0.08 | Same ranking · gap 0.03 | Different ranking · gap 0.05 |
| GPT-6.1 Sol vs Sonnet | Different ranking · gap 0.11 | Same ranking · gap 0.03 | Different ranking · gap 0.04 |

*Gap:* how far apart two judges score the same answer, on average.

- **Answer relevancy is stable:** all three judges rank the models the same way (Gemini, GPT-6 Luna, Haiku), within 0.03 per answer.
- **Faithfulness mostly holds:** Haiku and GPT-6.1 Sol rank the models the same way, and every judge puts Haiku's answers last.
- **No self-preference:** Haiku scored its own answers lower (0.71) than GPT-6.1 Sol did (0.81).
- **Context precision depends on the judge:** the rankings differ, so small differences there shouldn't be read as real.
- **Sonnet made clear mistakes.** It scored GPT-6 Luna's answer to "Italian restaurants in St. Louis" at 0.13, but the answer only lists the 6 retrieved restaurants, each of which the retrieved text calls "Cuisines: Italian". GPT-6.1 Sol scored it 0.88. Sonnet did the same on two more cuisine answers, which is why it ranks GPT-6 Luna lower.
- **The lesson:** a single LLM judge can be confidently wrong, so it's worth checking the lowest scores by hand and comparing judges before trusting small differences.

## Part 3: Trip plans

**Script:** [`evaluation/plans.py`](../evaluation/plans.py) · **Results:** [`results/plans.json`](../evaluation/results/plans.json)

### Method

- **18 TravelPlanner validation questions**, 6 easy, 6 medium and 6 hard. The harder ones add constraints: house rule, room type, cuisines and transport.
- TravelPlanner's questions are dated March 2022, so only their structure is kept: origin, destination, length, travellers, budget and constraints. Each trip moves to a future date, three days apart from 16 November 2026, so the agent plans it with **live flights, stays and restaurants**.
- All trips are 3 days (2 nights) with one destination city, planned by Claude Haiku 5.5.
- **Each plan is scored with the app's own checks**, but with the dataset's budget, travellers and constraints rather than the ones the model read from the question, plus three TravelPlanner-style checks: the right number of days, out and back from the origin, and a stay in the destination.
- These are TripMate's checks modelled on TravelPlanner's rules, **not its official evaluator**.
- **Without the knowledge base:** 6 of the trips (2 per level) run again without the knowledge-base search tool.

### Results

| Level | Plans | Delivered | All hard constraints met | All commonsense checks met | Final pass |
|---|---|---|---|---|---|
| Easy | 6 | 100% | 100% | 83% | **83%** |
| Medium | 6 | 100% | 33% | 50% | **17%** |
| Hard | 6 | 100% | 17% | 100% | **17%** |
| **All** | **18** | **100%** | **50%** | **78%** | **39%** |

Checks that failed (14 in total, some plans fail more than one):

| Check | Plans |
|---|---|
| House rule | 8 |
| Travels out and back | 3 |
| Right number of days | 1 |
| Budget | 1 |
| All items found in the data | 1 |
| Stays in the destination | 1 |

With and without the knowledge base, on the same 6 trips:

| Agent | Final pass | All commonsense checks met |
|---|---|---|
| With the knowledge base | **67%** | **83%** |
| Without it | 50% | 67% |

### What it shows

- **Every question got a costed plan**, and easy trips (no constraints) pass 83% of the time.
- **House rules are the main failure, and it's a data gap.** Live Airbnb listings don't publish house rules, so "must allow pets" can't be confirmed. 6 plans (5 hard, 1 medium) failed only that check, so without it 13 of 18 plans (72%) would pass.
- **The other failures are planning mistakes:** a missing or wrong flight leg (3 plans, one of them easy), an 8-person group over budget, a plan with the wrong number of days, and one stay outside the destination.
- **The knowledge base helps plans:** it supplies real restaurants and attractions, which the commonsense checks look for.
- **Prices:** only 44% of plans were fully priced. Taxi fares, many transit fares and some restaurant prices aren't published, so the real totals are higher than the priced ones.

## What it cost

| Part | Model calls | Live searches |
|---|---|---|
| 1. Retrieval | $0.006 | none |
| 2. RAGAS, both runs (answers) | about $0.23, plus Haiku's judging (not recorded) | none |
| 2. Two more judges on the saved answers | $4.92 (GPT-6.1 Sol $1.98, Sonnet 5.5 $2.94) | none |
| 3. Trip plans (18 + 6 without the knowledge base) | about $0.76 | 61 SerpApi searches, 230 Google Maps calls |

## Limitations

- **Small samples:** 60, 15 and 18 questions. One answer more or less moves a score by up to 7 points (in part 3, by 17 points within one level).
- **LLM judges disagree:** three judges agree on answer relevancy, mostly agree on faithfulness and disagree on context precision, and one judge (Sonnet 5.5) made clear mistakes. The same judge also varies a little between runs: Haiku rejudging the same answers moved context precision by up to 0.03.
- **Live data changes:** the trip plans use live prices and availability, so a new run gives different plans and totals.
- **Not TravelPlanner's official score:** the checks follow its rules, but the questions were moved to 2026 and scored with TripMate's own checks.
- **The house-rule check can't pass** for live stays until a source publishes house rules.

## How to run it again

```bash
python -m evaluation.retrieval                                        # part 1, about $0.01
python -m backend.travel_data.download                                # TravelPlanner questions, once
python -m evaluation.plans                                            # part 3, about $0.76 and 61 SerpApi searches
.venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna            # part 2, per model
.venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna --rejudge  # score saved answers again
.venv-eval/Scripts/python.exe -m evaluation.ragas_eval --model openai/gpt-6-luna --rejudge --judge openai/gpt-6.1-sol  # another judge, about $0.66
```

The RAGAS environment is set up as described in the [README](../README.md#evaluation).
