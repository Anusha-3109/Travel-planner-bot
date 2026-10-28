# TripMate: project reflection

This is a reflection on how TripMate was built, the decisions behind it, what the evaluation taught me, the problems found along the way and what I would improve next. Setup and usage are in the [README](../README.md), and the full evaluation is in [EVALUATION.md](EVALUATION.md).

## How the project developed

1. **TravelPlanner snapshot.** I started from the [TravelPlanner](https://huggingface.co/datasets/osunlp/TravelPlanner) dataset: 1,225 planning questions, each with its own bundle of US flights, restaurants, stays, attractions and ground routes from March 2022. I merged the bundles into one de-duplicated catalog (about 13,700 places in 257 cities) and indexed every place as one document in Chroma, with query translation, metadata filters and rank fusion on top.
2. **Tools.** Domain tools for flights, restaurants, stays, semantic place search, trip costing and constraint checks, and later local transport (seven in all). The costing and checking tools follow TravelPlanner's rules (meals and flights per person, cars per 5 travellers, rooms by occupancy).
3. **Beyond the US and beyond 2022.** The dataset is US-only and four years old, so I added European and Asian cities from Inside Airbnb (September 2026) and OpenStreetMap, then live data: Google Flights, Airbnb and Google Hotels through SerpApi, Google Places restaurants, Google Routes for public transport and driving, and daily exchange rates. Finally I replaced the last 2022 data with 2026 OpenStreetMap data for TravelPlanner's other 195 US cities. The knowledge base now holds 54,309 places from 2026 in 245 cities and no 2022 data; TravelPlanner's questions are still used for the evaluation.
4. **Result cards.** The app draws flights, stays, restaurants, transport and the trip cost as cards from the tools' own results, so they look the same in every answer and the written answer can focus on the best picks.
5. **Hardening.** A security review (key redaction in logs, screening of tool results for injected instructions), a test suite, and a GitHub Actions workflow that runs it on every push.
6. **A real app around the chat.** Saved chat history, a request log behind a Dashboard, model choice and token costs, a Plan and an Explore mode, and saved trips with a timeline, a route map, stays and places to discover. The code was split into `frontend/` and `backend/`, with the parts that are only shown written as HTML and CSS.
7. **Evaluation.** Retrieval on 60 questions with known answers (four strategies), RAGAS on three models with three judges and a fresh run, and 18 TravelPlanner trips planned with live 2026 data. The results are on the Benchmarks page and in [EVALUATION.md](EVALUATION.md).
8. **Deployment.** A Docker image with the knowledge base built in, on Google Cloud Run, with saved data in a Cloud Storage bucket and keys in Secret Manager. Every push to `main` now deploys automatically after the tests pass.
9. **For travellers, not only for planning.** A budget tracker, packing list, journal and documents on every saved trip, and user accounts with Google sign-in, so each person sees only their own chats, trips and files.
10. **A finished interface.** Two themes, Graphite amber (dark) and Light amber, chosen in Streamlit's menu, with CSS colours worked out from the theme's text colour so a switch shows at once; a compact, full-width layout; a home box that sends on Enter; and result cards that take the next step ("Use this stay", "Add to the plan") by naming the option's live id, so the planner swaps exactly that item.
11. **German, and a check of the embedding model.** English and German buttons in Settings switch the chat page, trip form, cards, sidebar and Settings, and TripMate answers in the chosen language while its searches stay in English. An embedding probe compared the local model with two OpenAI models in English and German. The suite now has 309 tests.

## Key decisions

- **Live first, snapshot as fallback.** Every live tool falls back to snapshot data when a search fails, a date is in the past or a key is missing, and says so. The app never stops working because one service is down.
- **Prices come from tools, never from the model.** Every live result gets an id; the cost tool looks prices up by id (or exact name), so a total can't contain a number the model invented. Missing prices are listed as unpriced instead of guessed.
- **Ready-made display text.** Small models reformat numbers inconsistently, so tools return finished text (`price_text`, `rating_text`, `cost_text`) for the model to copy. This fixed most formatting errors.
- **Record-level chunks.** Each place is short, so it stays one chunk; splitting would separate a name from its price or house rules.
- **Current data only.** Nobody plans a trip on four-year-old prices, so all 2022 data was replaced. The cost: smaller US cities have no snapshot stay prices and there are no snapshot flight prices at all, so without live data those items are unpriced instead of outdated.
- **A judge that isn't one of the judged.** RAGAS needs a model to judge answers. I moved from Haiku (the smallest model, judging its own answers) to GPT-6.1 Sol, a larger model that isn't one of the three answering, and scored the same saved answers with every judge so only the judge changed.
- **Free where possible.** The packing list starts from plain rules (documents, clothes for the nights, a plug adapter when the sockets differ, items for the season), and only "Suggest more" calls the model. The budget, journal and documents use no model at all.
- **No passwords of my own.** Accounts use Streamlit's Google sign-in, so the app never stores a password, and the owner of each chat or trip is a hash of the email, not the email.
- **The index inside the image.** Building the knowledge base takes minutes, so it's built when the image is built, and a cold start on Cloud Run takes seconds instead.

## What the evaluation taught me

- **Filters do most of the retrieval work.** City and category filters took places from the wrong city from 29% to 12%. Multi-query alone didn't help; with filters it found the last two misses. The risk is a wrong city guess: the model put the Imaginarium of South Texas in Corpus Christi, not Laredo, and the filter hid the right place.
- **Faithfulness found a real prompt problem.** Answers named only retrieved places but added descriptions from the model's own knowledge. One prompt rule (describe places only with what the results say) raised faithfulness from 0.79 to 0.89 for GPT-6 Luna and from 0.70 to 0.89 for Gemini.
- **LLM judges can be confidently wrong.** Sonnet 5.5 scored a fully supported answer at 0.13; GPT-6.1 Sol gave it 0.88. Three judges agree on answer relevancy, mostly agree on faithfulness and disagree on context precision, so it pays to check the lowest scores by hand.
- **Scores move between runs.** A fresh run of the same questions moved faithfulness and context precision by up to 0.05, while the ranking of the models held. Differences smaller than that aren't real.
- **A bigger embedding model isn't needed, because of how the app searches.** In English the local model and two OpenAI models found every place. In German with German city names (Wien, Prag), the local model alone found the right city for only 6 of 10 questions, against 10 of 10 for the OpenAI models, but with the app's English searches added it got 10 of 10 too. The query translation the app already had turned out to be what makes German work.
- **The biggest planning failure is missing data, not the model.** Live Airbnb listings don't publish house rules, so every trip with a rule like "must allow pets" fails that check: 39% of plans pass every check, 72% without it. The knowledge base helps plans: 67% passed with it against 50% without.

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
| Faithfulness scores missing | RAGAS's default reply length cut the judge off for 41 of 45 answers | A longer judge reply, and `--rejudge` to score saved answers again without asking the models |
| Hotels called "private rooms" | The knowledge base filed OpenStreetMap hotels under TravelPlanner's "Private room", so an answer saying "hotel" looked unsupported | The text now says "hotel room (private room)"; searches and checks still use the room type |
| A changed description wasn't picked up | Document ids come from the source, not the text, so the index update skipped the 7,351 changed stays | The update now replaces places whose text changed |
| A run stopped at its first line | The Windows console couldn't print "→" when the output went to a file | Plain "to" in progress lines |
| Text shown as a formula | Two "$" signs in a caption made Streamlit render the text between them as maths | Escape "$" in every caption and label with amounts |
| Local tests failed after adding a password | With `APP_PASSWORD` in `.env`, the app tests only reached the password screen | The tests always turn the password off; a separate test checks the screen |
| A mounted secret would hide the theme | Cloud Run mounts a secret over its whole folder, and `.streamlit/` holds the theme | The sign-in settings are mounted elsewhere and listed in `config.toml` as a secrets file |
| Theme colours lagged after a switch | Streamlit's menu changes the theme in the browser without rerunning the app, so CSS colours picked on the server stayed on the old theme until a refresh | The CSS colours are worked out from each element's text colour (`currentColor`), which follows the theme at once |
| Stale code in the running app | Streamlit's reload kept old modules in memory after changes | Restart the app after code changes |

## Limitations

- **Unavailable prices.** Taxi fares, many public transport fares, attraction tickets and some restaurant prices aren't published by the sources, so totals leave them out (and say so). US driving costs are an estimate at the IRS 2026 mileage rate, without tolls or parking.
- **House rules can't be confirmed** for live stays, which is the main reason trip plans fail their checks.
- **Snapshot prices.** Stays in the 195 smaller US cities and all flights have no snapshot prices, so plans depend on live searches for those.
- **Model accuracy.** The model occasionally adds a detail the data doesn't contain. Tools supply all prices, ids and links, which limits this to the wording, and the prompt rule reduced it for knowledge-base answers.
- **Small evaluation samples.** 60, 15 and 18 questions, and LLM judges that disagree, so small differences between models or strategies aren't meaningful.
- **Pattern-based injection screening** can miss rephrased attacks.
- **Quotas.** SerpApi's free plan has 250 searches a month; a full plan uses about 3–4. The cache and per-chat limits stretch this.
- **One instance.** Saved data is a SQLite file in a Cloud Storage bucket, which is safe only with one instance writing to it, so the app can't scale out yet. Uploaded files are stored as uploaded, without extra encryption.
- **Sign-in for test users.** Until the Google sign-in screen is published, only the up to 100 test users the author adds can sign in.
- **Slow deploys.** Building the knowledge base into the image makes each deploy take about 40 minutes.

## Improvements I would make next

1. **Hybrid search:** keyword plus vector search, which would fix weak semantic matches such as "seafood restaurant" on names-only records, and a retrieval evaluation to show it.
2. **Retry and an honest summary on failure:** a Retry button when an answer fails, and a short list of what's still incomplete when a search fell back or a price is missing.
3. **An LLM-based injection classifier** alongside the patterns.
4. **A shared database** (Firestore or Cloud SQL) instead of SQLite, so the app can run more than one instance.
5. **Faster deploys:** build the knowledge base once per data change and reuse it, instead of on every deploy.
6. **TripMate's search as an MCP server**, so other assistants can use the 2026 knowledge base.
7. **More languages and a German trip plan:** the interface texts are in one dictionary, so a third language is mostly translation; a full German trip plan with live searches is still untested.
8. **Measure the hotel-room wording change** by running the private-room RAGAS questions again.
