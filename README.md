# TripMate ✈️ travel planner chatbot

[![Tests](https://github.com/Anusha-3109/Travel-planner-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/Anusha-3109/Travel-planner-bot/actions/workflows/tests.yml)

TripMate plans day-by-day trips anywhere in the world: flights, a place to stay, restaurants for each meal, things to see and how to get from the airport, all costed against your budget in your currency. It searches **live** flights, Airbnb and hotel prices, restaurants and public transport, and falls back to snapshot data when live data isn't available. It is built with LangChain, OpenRouter (Claude Haiku 5.5) and Streamlit, and combines advanced RAG with tool calling.

The Sprint 2 task description is in [`125.md`](125.md).

## What you can ask

- *"Plan a 3-night trip from Paris to Barcelona from 20 November for 2 people with a budget of 1,200."*
- *"Flights from New York to Tokyo on 22 November."*
- *"Find an Airbnb in Rome from 10 to 14 November for 2 people."* (add *"in a table"* for a table)
- *"Sushi restaurants in Tokyo rated 4.5 or more."*
- *"How do I get from Fiumicino Airport to the Colosseum?"*

The sidebar has a trip form (any city, dates from today, travellers, budget, Airbnb or hotel, optional constraints) and a currency picker.

## How it works

```
You ──► Streamlit app ──► Agent (Claude Haiku 5.5 via OpenRouter, tool calling)
                               │
        ┌──────────────────────┼──────────────────────────────┐
        ▼                      ▼                              ▼
  Live tools             RAG knowledge base              Planning tools
  flights, stays,        Chroma + local embeddings,      trip cost in any currency,
  restaurants,           query translation, metadata     constraint checks
  public transport       filters, rank fusion
        │                      │
        ▼                      ▼
  SerpApi (Google Flights,     ~35,500 places: Inside Airbnb + OpenStreetMap
  Hotels, Airbnb), Google      (50 cities in the US, Europe and Asia, 2026),
  Places and Routes            TravelPlanner (other US cities, 2022)
```

1. The agent reads your question (with today's date and your currency) and calls tools.
2. Live tools search current data; if a search fails, the date is in the past or a key is missing, the tool falls back to snapshot data and says so.
3. Every live result gets an id. For a full plan the agent calls `calculate_trip_cost` and `check_constraints` with those ids, so totals use the prices the services returned, never numbers the model typed. If the model skips them, it is sent back once to use them.
4. Tool results are screened for injected instructions before the model reads them. The answer gives the best picks as a list (or full tables if you ask), and the app draws every result as a card from the tool's own data: flights by airline, stays and restaurants with ratings and links, transport options, and a cost card with the total against your budget.

## Course requirements

| Requirement | How TripMate covers it |
|---|---|
| Knowledge base | ~35,500 places: Inside Airbnb stays and OpenStreetMap restaurants and attractions from 2026 for 50 cities (34 US areas plus 16 in Europe and Asia), and the [TravelPlanner](https://huggingface.co/datasets/osunlp/TravelPlanner) reference data for the other US cities (merged and de-duplicated in `travel_data/catalog.py`) |
| Embeddings and similarity search | Chroma vector store with local all-MiniLM-L6-v2 embeddings (cosine similarity); no API key needed |
| Chunking | One chunk per attraction, restaurant or stay. Records are short, so each stays whole, with category, city, country, price and rating as metadata |
| Query translation | The LLM rewrites each question into 2–3 focused search queries (multi-query) |
| Structured retrieval | The LLM extracts `category` and `city` filters for Chroma metadata filtering; results from all queries are merged with reciprocal rank fusion |
| Tool calling | 7 tools, see [Tools](#tools) |
| Domain specialisation | A travel-planning system prompt with rules for live versus snapshot data, budgets, citations and answer formats |
| Security | See [Security](#security) |
| LangChain + OpenRouter | `ChatOpenAI` pointed at OpenRouter (`agent/llm.py`), LangChain tools and messages, a hand-written tool loop (`agent/agent.py`) |
| Error handling and validation | Clear messages for missing or rejected keys, rate limits, timeouts and failing services; every tool input is validated |
| User interface | Streamlit chat with a trip form, currency picker, progress messages, result cards (flights, stays, restaurants, transport, trip cost), expandable tool calls and sources, token usage and live-data status |

**Optional tasks implemented**

- *Easy:* conversation export (Markdown and JSON), source citations, an in-app help guide.
- *Medium:* real-time data (live flights, stays, restaurants and transport), prompt-injection protection (user messages and tool results), rate limiting and API key management, token usage display, multi-model support (any OpenRouter model through `OPENROUTER_MODEL`).

## Tools

| Tool | File | What it does |
|---|---|---|
| `search_flights` | `tools/transport.py` | Live Google Flights for a date, grouped by airline, cheapest first, with flight numbers, times, stops and price per person (and the group total). Falls back to TravelPlanner's 2022 US flights or an estimated flight time |
| `search_accommodations` | `tools/places.py` | Live Airbnb (default) or Google Hotels stays for the dates and guests, with nightly and total prices, ratings, free cancellation and booking links. Falls back to the snapshot stays with exact filters (price, room type, house rules) |
| `search_restaurants` | `tools/places.py` | Live Google Places restaurants by city and cuisine, with price range per person (local currency and USD), rating, opening hours and a Maps link |
| `get_local_transport` | `tools/local_transport.py` | Live Google Routes public transport between two places (lines, stops, times, fares where published) and driving time for a car or taxi, with an estimated cost per car in the US (IRS 2026 mileage rate) |
| `search_destination_options` | `tools/destinations.py` | RAG search over the knowledge base for open questions such as "museums for kids in Chicago" |
| `calculate_trip_cost` | `tools/planning.py` | Costs a day-by-day plan from live ids or snapshot names, including airport transfers, in any currency, marking each line live, snapshot or estimate and listing unpriced items |
| `check_constraints` | `tools/planning.py` | Checks a plan: budget, house rule, room type, cuisines, banned transport, items that exist, no repeated restaurants or attractions, minimum nights, a stay every night and stays that fit the group |

## Data sources

**Live** (dates from today, any city; cached so repeat questions are free)

| Data | Source | Cached for |
|---|---|---|
| Flights | Google Flights via [SerpApi](https://serpapi.com) | 1 hour |
| Airbnb and hotel stays | Airbnb and Google Hotels via SerpApi | 6 hours |
| Restaurants | [Google Places API (New)](https://developers.google.com/maps/documentation/places/web-service) | 24 hours |
| Public transport and driving | [Google Routes API](https://developers.google.com/maps/documentation/routes) | 24 hours |
| Exchange rates | [ExchangeRate-API](https://www.exchangerate-api.com) open endpoint, with the [European Central Bank](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) as backup | 12 hours |

**Snapshot** (fallback, past dates and the knowledge base)

| Data | Source | Date | Licence |
|---|---|---|---|
| Stays in 50 cities (34 US areas, 16 in Europe and Asia) | [Inside Airbnb](https://insideairbnb.com) | September 2026 | CC BY 4.0 |
| Restaurants and attractions in those cities | [OpenStreetMap](https://www.openstreetmap.org/copyright) via the Overpass API | October 2026 | ODbL |
| Airports (for flight searches) | [OurAirports](https://ourairports.com/data/) | October 2026 | Public domain |
| US flights and ground routes, and places in the other US cities | [TravelPlanner](https://huggingface.co/datasets/osunlp/TravelPlanner) (Xie et al., 2024) | March 2022 | CC BY 4.0 |
| US driving cost | [IRS standard mileage rate](https://www.irs.gov/tax-professionals/standard-mileage-rates) ($0.725 a mile) with Google Routes distances | 2026 | Public |

The European and Asian cities are London, Paris, Rome, Barcelona, Madrid, Amsterdam, Berlin, Vienna, Prague, Lisbon, Athens, Istanbul, Tokyo, Bangkok, Singapore and Hong Kong. The US areas are Albany, Asheville, Austin, Boston, Bozeman, Cambridge, Chicago, Columbus, Dallas, Denver, Fort Lauderdale, Fort Worth, Honolulu, Jersey City, Las Vegas, Los Angeles, Minneapolis, Nashville, New Orleans, New York, Newark, Oakland, Pacific Grove, Portland, Providence, Rochester, Salem, San Diego, San Francisco, San Jose, San Mateo, Santa Cruz, Seattle and Washington. For those cities the 2026 places replace TravelPlanner's 2022 places; the 2022 flights and ground routes stay, and the original 2022 catalog is still available for evaluation (`build_catalog(world_dir=None)`). Refresh the cities with `python -m travel_data.fetch_world` (about 4–8 minutes per city).

## Setup

You need Python 3.12 and three API keys:

| Key | Used for | Where to get it |
|---|---|---|
| `OPENROUTER_API_KEY` (required) | The chat model | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `SERPAPI_API_KEY` (optional) | Live flights, hotels and Airbnb | [serpapi.com](https://serpapi.com/manage-api-key), free plan: 250 searches a month |
| `GOOGLE_MAPS_API_KEY` (optional) | Live restaurants and public transport | [Google Cloud console](https://console.cloud.google.com/apis/credentials): enable **Places API (New)** and **Routes API** |

Without the optional keys the app still works, using the snapshot data.

```bash
git clone https://github.com/Anusha-3109/Travel-planner-bot.git
cd Travel-planner-bot
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt    # or: uv pip install -r requirements.txt
copy .env.example .env             # macOS/Linux: cp .env.example .env, then add your keys
python -m travel_data.download     # TravelPlanner data, about 70 MB, into data/travelplanner/
```

Other settings in `.env`: `OPENROUTER_MODEL` (default `anthropic/claude-haiku-5.5`), `SESSION_SERPAPI_LIMIT` and `SESSION_GOOGLE_LIMIT` (live calls allowed per chat, default 20 and 60), `LIVE_TIMEOUT_SECONDS`.

## Run

```bash
streamlit run app.py
```

Open <http://localhost:8501>. On the first start the app downloads a small embedding model (about 80 MB) and indexes the places into `.chroma/` (about 25 minutes). Later starts only add new places. To rebuild the index yourself, run `python -m rag.ingest`.

## Costs and limits

- **OpenRouter:** with Claude Haiku 5.5, a full trip plan costs about $0.02 and a simple question well under a cent.
- **SerpApi:** a full plan uses about 3–4 searches (flights both ways and a stay). Repeat questions come from the cache for free, and each chat is limited to 20 searches.
- **Google Maps:** restaurant and route requests are small and covered by Google's free monthly allowance at this scale; each chat is limited to 60.

## Security

- **Keys** live only in `.env` (git-ignored), are sent in request headers or separate parameters, are never cached, and are replaced with `[hidden key]` in every log line, traceback and error message (`security/redaction.py`). A test scans every committed file for key patterns.
- **User messages** are checked for length, control characters and prompt-injection patterns before the model sees them.
- **Tool results** (listing names, place descriptions and other outside text) are screened before the model reads them: instruction-like text is removed, only http(s) links are kept and long text is trimmed (`security/tool_output.py`).
- **Tool inputs** chosen by the model are validated like user input: cities, dates, people, prices, ratings, cuisines, place names and plan structure.
- **Limits:** a per-session message rate limit, per-chat live-call limits, at most 10 agent steps per answer, and clear limits for Google Flights (9 passengers) and Airbnb (16 guests).
- Raw HTML in answers is not rendered.

## Tests

```bash
python -m pytest -q
```

196 tests cover the catalog, RAG, every tool, the live clients (with recorded API answers, so no keys, credit or searches are used), trip costing, the agent loop and its error handling, the app screen and result cards, and the security checks. Test coverage is about 96%. GitHub Actions runs the suite on every push to `main` (`.github/workflows/tests.yml`).

## Project structure

```
app.py                  Streamlit UI
ui_cards.py             Result cards drawn from tool results
trip_form.py            Trip form question and example questions
config.py               Settings: model, keys, paths, cache times, limits
agent/llm.py            ChatOpenAI client pointed at OpenRouter
agent/agent.py          Tool-calling loop, system prompt, error handling, cost guard
live/                   Live data: SerpApi and Google clients, flights, stays, restaurants,
                        routes, exchange rates, airports, cache, request helper, limits, item ids
tools/                  The 7 tools the agent can call
rag/                    Chroma store, indexing and retrieval
travel_data/            TravelPlanner download and catalog, world-city fetch script
security/               Validation, rate limiting, key redaction, tool output screening
data/world/             50 cities from 2026, US, Europe and Asia (committed)
data/ourairports/       Airport list (committed)
data/travelplanner/     TravelPlanner files (downloaded, not committed)
tests/                  pytest suite and recorded API answers in tests/fixtures/
legacy/tripmate/        The first version's tools, kept for reference
```

## Known limitations and ideas for improvement

- **Prices that aren't available:** taxi fares, many public transport fares, attraction tickets and some restaurant prices are not published by the sources, so they are listed as unpriced and left out of totals. US driving costs are an IRS-rate estimate without tolls or parking.
- **Snapshot coverage:** smaller US cities still fall back to TravelPlanner's 2022 data when live search isn't available.
- **Round trips** are searched as two one-way flights; real round-trip fares can be a little cheaper.
- **Public transport times** come from the current timetable, not your travel day.
- **Model accuracy:** the model occasionally adds a detail the data doesn't contain, such as naming a train service. Tools supply all prices, ids and links to keep this to the text.
- **Prompt-injection screening** is pattern-based and can miss rephrased attacks; an LLM-based classifier would be stronger.
- **Next steps:** searching transit by departure time, hybrid search (BM25 plus vectors), a RAGAS evaluation of retrieval quality, scoring plans with the TravelPlanner evaluator, and serving the tools as an MCP server.

## Attribution

- TravelPlanner: Xie, J. et al. (2024). *TravelPlanner: A Benchmark for Real-World Planning with Language Agents.* arXiv:2402.01622. CC BY 4.0.
- Stay listings from [Inside Airbnb](https://insideairbnb.com), CC BY 4.0.
- Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.
- Airport data from [OurAirports](https://ourairports.com), public domain.
- [Rates by Exchange Rate API](https://www.exchangerate-api.com); euro reference rates from the European Central Bank.
- Live flights, hotels and Airbnb results via SerpApi; restaurants and routes via Google Maps Platform, used under their terms and cached for at most 24 hours.
