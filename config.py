"""Central configuration, loaded from environment variables and an optional .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

# Live data. Without these keys the app still works, using the snapshot data only.
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")  # live flights, hotels and Airbnb stays
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")  # live restaurants and local transport
LIVE_TIMEOUT_SECONDS = int(os.getenv("LIVE_TIMEOUT_SECONDS", "30"))
LIVE_RETRIES = 2  # extra attempts after a timeout, rate limit or server error
# Per chat session, so one conversation can't use up the monthly quota (SerpApi free plan: 250/month).
SESSION_LIMITS = {"serpapi": int(os.getenv("SESSION_SERPAPI_LIMIT", "20")),
                  "google": int(os.getenv("SESSION_GOOGLE_LIMIT", "60"))}
# How long a live answer is reused before asking again. Cached answers are free.
CACHE_TTL_SECONDS = {"flights": 3600, "stays": 6 * 3600, "restaurants": 24 * 3600, "transport": 24 * 3600,
                     "exchange_rates": 12 * 3600}

DATA_DIR = ROOT_DIR / "data"
TRAVELPLANNER_DIR = DATA_DIR / "travelplanner"
WORLD_DIR = DATA_DIR / "world"
CHROMA_DIR = ROOT_DIR / ".chroma"
CACHE_DB = ROOT_DIR / ".cache" / "live.sqlite3"
COLLECTION_NAME = "travelplanner_places"

INDEX_BATCH_SIZE = 500
RETRIEVAL_K = 6
MAX_QUERY_VARIANTS = 3
MAX_RESULTS_SHOWN = 10

MAX_AGENT_STEPS = 10  # a full itinerary needs transport, stays, restaurants, costing and checks
