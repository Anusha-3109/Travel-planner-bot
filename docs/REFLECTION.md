# TripMate: project reflection

This is a short reflection on how TripMate was built, the decisions behind it, the problems found along the way and what I would improve next. Setup and usage are in the [README](../README.md).

## How the project developed

1. **TravelPlanner snapshot.** I started from the [TravelPlanner](https://huggingface.co/datasets/osunlp/TravelPlanner) dataset: 1,225 planning questions, each with its own bundle of US flights, restaurants, stays, attractions and ground routes from March 2022. I merged the bundles into one de-duplicated catalog (about 13,700 places in 257 cities) and indexed every place as one document in Chroma, with query translation, metadata filters and rank fusion on top.
2. **Tools.** Six domain tools covered flights, restaurants, stays, semantic place search, trip costing and constraint checks. The costing and checking tools follow TravelPlanner's rules (meals and flights per person, cars per 5 travellers, rooms by occupancy).
3. **Beyond the US and beyond 2022.** The dataset is US-only and four years old, so I added 16 European and Asian cities from Inside Airbnb (September 2026) and OpenStreetMap, then live data: Google Flights, Airbnb and Google Hotels through SerpApi, Google Places restaurants, Google Routes for public transport and driving, and daily exchange rates. Finally I added 2026 Inside Airbnb and OpenStreetMap data for 34 US areas, so the snapshot fallback is current for the main US cities.
4. **Result cards.** The app draws flights, stays, restaurants, transport and the trip cost as cards from the tools' own results, so they look the same in every answer and the written answer can focus on the best picks.
5. **Hardening.** A security review (key redaction in logs, screening of tool results for injected instructions), a test suite of 207 tests at 96% coverage, and a GitHub Actions workflow that runs them on every push.

## Key decisions

- **Live first, snapshot as fallback.** Every live tool falls back to snapshot data when a search fails, a date is in the past or a key is missing, and says so. The app never stops working because one service is down.
- **Prices come from tools, never from the model.** Every live result gets an id; the cost tool looks prices up by id (or exact name), so a total can't contain a number the model invented. Missing prices are listed as unpriced instead of guessed.
- **Ready-made display text.** Small models reformat numbers inconsistently, so tools return finished text (`price_text`, `rating_text`, `cost_text`) for the model to copy. This fixed most formatting errors.
- **Record-level chunks.** Each place is short, so it stays one chunk; splitting would separate a name from its price or house rules.
- **Keep the 2022 data.** It remains the fallback for smaller US cities and is the only data that fits TravelPlanner's own test questions, which an evaluation needs.

## Problems found and how I fixed them

| Problem | How it showed | Fix |
|---|---|---|
| Group flight fares doubled | For 2 people Google returns the total for both, which the tool reported as per person; the model then multiplied again | Price per person = Google's price ÷ passengers, plus ready-made text "$35 per person · $70 total for 2" |
| The model added up costs itself | A plan skipped the cost tool and treated EUR 1,500 as "about $1,500" | A guard sends the model back once to use the cost and check tools; totals are copied from the tool |
| Unreliable plans with gpt-4o-mini | Only 1 of 3 test plans was correct (wrong restaurants, stays costed for one night) | Compared gpt-4o-mini, Claude Haiku 5.5 and Claude Sonnet 5.5 on the same plan; Haiku was correct at about $0.02 per plan, so it became the default |
| Flight distances in the wrong unit | TravelPlanner's flight distances are miles but were labelled kilometres | Renamed the field, and added a test that checks every city's position against the flight distances |
| Wrong city data in TravelPlanner | "Washington" attractions are Seattle sights; "Manchester" attractions are in England | Fixed those two cities' coordinates; the 2026 data now replaces Washington's places |
| Ambiguous airport lookups | "Sydney" matched Sydney, Nova Scotia; Delhi's airport is filed under "New Delhi" | Match the city as a word in the airport's town or name, prefer the country with the most large airports, and add aliases (Bangalore → Bengaluru) |
| Hotel results were dorms | Sorting by lowest price surfaced capsule hotels far from the centre | Google's relevance order with a 3.5-star floor |
| Airport transfer missing from totals | A plan day held only one transport entry, so the flight crowded out the transfer | Each day now has a list of local trips, costed like the main transport |
| Prices in USD despite the currency picker | Totals followed the picker, listings didn't | Listing texts are converted to the chosen currency at today's rate |
| Stale code in the running app | Streamlit's reload kept old settings in memory after changes | Restart the app after code changes |

## Limitations

- **Unavailable prices.** Taxi fares, many public transport fares, attraction tickets and some restaurant prices aren't published by the sources, so totals leave them out (and say so). US driving costs are an estimate at the IRS 2026 mileage rate, without tolls or parking.
- **Snapshot coverage.** 2026 snapshot data covers 50 cities; smaller US cities fall back to 2022 data when live search is unavailable.
- **Model accuracy.** The model occasionally adds a detail the data doesn't contain (once it named a train service the data didn't). Tools supply all prices, ids and links, which limits this to the wording.
- **Pattern-based injection screening** can miss rephrased attacks.
- **Quotas.** SerpApi's free plan has 250 searches a month; a full plan uses about 3–4. The cache and per-chat limits stretch this.
- **Not evaluated systematically yet.** Quality was checked with unit tests, real app runs and a model comparison, but not yet on a sample of TravelPlanner's validation questions.

## Improvements I would make next

1. **Evaluation:** run the agent on a sample of TravelPlanner's validation questions with the 2022 catalog and report how many plans are complete and pass the hard and commonsense constraints; compare with and without retrieval.
2. **Hybrid search:** keyword plus vector search, which would fix weak semantic matches such as "seafood restaurant" on names-only records.
3. **An LLM-based injection classifier** alongside the patterns.
