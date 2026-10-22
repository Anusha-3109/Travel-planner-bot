# TripMate ✈️ travel planner chatbot

TripMate builds day-by-day trip plans between US cities: transport, three meals a day, attractions and a place to stay each night, within the traveller's budget and house rules. It searches flights, restaurants and accommodations, adds up the cost of a plan and checks it against the traveller's constraints before answering. It is built with LangChain, OpenRouter and Streamlit, and combines advanced RAG with tool calling.

## Features

| Requirement | How TripMate covers it |
|---|---|
| Knowledge base | The [TravelPlanner](https://huggingface.co/datasets/osunlp/TravelPlanner) reference data (US attractions, restaurants, accommodations, flights, self-driving and taxi routes, March 2022), merged and de-duplicated into one catalog in `travel_data/catalog.py` |
| Embeddings and similarity search | Chroma vector store with local all-MiniLM-L6-v2 embeddings (cosine similarity) |
| Chunking | One chunk per attraction, restaurant or accommodation. The records are short, so each one stays whole, with category, city, price and rating as metadata |
| Query translation | The LLM rewrites each question into 2–3 focused search queries (multi-query) |
| Structured retrieval | The LLM also extracts `category` and `city` filters, which become Chroma metadata filters. Results from all queries are merged with reciprocal rank fusion |
| Tool calling (6 tools) | See [Tools](#tools) below |
| Security | Input validation (length, control characters, city names, dates, prices, ratings and group size), prompt-injection screening, tool arguments validated as untrusted input, retrieved text treated as data in prompts, per-session rate limiting, API key kept in `.env` |
| Error handling | Clear messages for a missing or invalid key, rate limits, timeouts and tool failures. A failing tool returns an error to the model instead of crashing the app |
| UI | Streamlit chat, trip planner form with optional constraints, live progress status, expandable tool calls and sources, token usage |

Optional tasks implemented: conversation export (Markdown and JSON), source citations, an in-app help guide, token usage display, prompt-injection protection, rate limiting and a "rebuild knowledge base" admin action.

## Tools

| Tool | File | What it does |
|---|---|---|
| `search_destination_options` | `tools/destinations.py` | Semantic (RAG) search over attractions, restaurants and accommodations for open questions such as "museums for kids in Chicago". Optional `city` and `category` filters |
| `search_flights` | `tools/transport.py` | Flights between two cities on a date, cheapest first, plus self-driving and taxi options on the same route. Lists other dates with flights when the chosen day has none |
| `search_restaurants` | `tools/places.py` | Restaurants in a city, best rated first, with exact filters for cuisine, maximum average cost and minimum rating |
| `search_accommodations` | `tools/places.py` | Places to stay, cheapest first, filtered by price, room type and a house rule that must be allowed. With `people` and `nights` it adds rooms needed and total cost, and hides stays whose minimum nights are too long |
| `calculate_trip_cost` | `tools/planning.py` | Adds up a day-by-day plan from the data: flights and meals per person, cars per 5 travellers, taxis per 4, rooms by occupancy. Returns a breakdown, the total and the remaining budget |
| `check_constraints` | `tools/planning.py` | Validates a finished plan. Hard constraints: budget, house rule, room type, required cuisines, banned transport. Commonsense checks: items exist in that day's city, no repeated restaurants or attractions, minimum nights met, a stay every night but the last, no mixing flights with self-driving |

For a full plan the agent finds transport for each travel day, picks a stay and restaurants, then calls `calculate_trip_cost` and `check_constraints`, and fixes the plan if a check fails.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # then add your OPENROUTER_API_KEY
python -m travel_data.download  # downloads the TravelPlanner data (about 70 MB) into data/travelplanner/
```

## Run

```bash
streamlit run app.py
```

On the first run, the app downloads a small embedding model (about 80 MB) and indexes the places into `.chroma/`. To rebuild the index, run `python -m rag.ingest` or use the **Admin → Rebuild knowledge base** button.

## Tests

```bash
python -m pytest -q
```

The tests cover validation, the data catalog, the tools, retrieval and the agent loop. The agent tests use a scripted fake LLM, so they run without an API key.

## Project structure

```
app.py                 Streamlit UI
config.py              Settings (model, paths, retrieval, agent steps)
agent/llm.py           ChatOpenAI client pointed at OpenRouter
agent/agent.py         Tool-calling loop, system prompt, error handling
travel_data/download.py  Downloads the TravelPlanner dataset from Hugging Face
travel_data/catalog.py   In-memory catalog of places, flights and ground routes
rag/vectorstore.py     Chroma store with local embeddings
rag/ingest.py          Turning places into documents and indexing them
rag/retriever.py       Query translation, metadata filters, rank fusion
tools/                 Destination search, flights, restaurants, accommodations, trip cost and constraint checks
security/              Input validation and rate limiting
data/travelplanner/    TravelPlanner data files (downloaded, not committed)
legacy/tripmate/       The earlier OpenFlights, insurance and city-guide tools, kept for reference
tests/                 pytest suite
```

## Known limitations and ideas for improvement

- The TravelPlanner data is a snapshot of US cities from March 2022, so flights and prices are not live. A live flight and hotel API such as Amadeus would fix this.
- Coverage is limited to the US cities in the dataset.
- Attractions have no prices in the data, so they count as free in trip costs.
- Prompt-injection screening is pattern-based, so it can miss rephrased attacks. An LLM-based classifier would be stronger.
- Next steps: hybrid search (BM25 plus vectors), a RAGAS evaluation of retrieval quality, scoring plans with the TravelPlanner evaluator, and serving the tools as an MCP server.
