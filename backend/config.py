"""Central configuration, loaded from environment variables and an optional .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]  # the project folder (this file is in backend/)
load_dotenv(ROOT_DIR / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-5.5")
# Models offered in the app, all with tool calling on OpenRouter: id -> (name, USD per million input tokens,
# USD per million output tokens). The prices are only used when OpenRouter doesn't report a call's cost.
MODELS = {
    "anthropic/claude-haiku-5.5": ("Claude Haiku 5.5", 0.10, 0.50),
    "openai/gpt-6-luna": ("OpenAI GPT-6 Luna", 0.10, 0.50),
    "google/gemini-3.7-flash": ("Google Gemini 3.7 Flash", 0.75, 3.75),
}
if OPENROUTER_MODEL not in MODELS:  # a default set in .env is always offered, without a known price
    MODELS = {OPENROUTER_MODEL: (OPENROUTER_MODEL, None, None), **MODELS}
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
LIVE_DAYS_AHEAD = 330  # flights and stays can be searched about 11 months ahead
# Driving costs in the US: the IRS 2026 standard mileage rate (fuel, wear and running costs), IR-2025-128.
IRS_MILEAGE_RATE_USD = 0.725
KM_PER_MILE = 1.609344
CACHE_TTL_SECONDS = {"flights": 3600, "stays": 6 * 3600, "restaurants": 24 * 3600, "transport": 24 * 3600,
                     "exchange_rates": 12 * 3600}

DATA_DIR = ROOT_DIR / "data"
TRAVELPLANNER_DIR = DATA_DIR / "travelplanner"
WORLD_DIR = DATA_DIR / "world"
CHROMA_DIR = ROOT_DIR / ".chroma"
CACHE_DB = ROOT_DIR / ".cache" / "backend.live.sqlite3"
# Saved chats and the request log (git-ignored). HISTORY_DIR moves it, for example to a mounted
# Cloud Storage bucket on Cloud Run, so it survives restarts.
HISTORY_DB = Path(os.getenv("HISTORY_DIR") or ROOT_DIR / ".history") / "chats.sqlite3"
# When set, the app asks for this password first (for a deployed copy; empty locally). Google sign-in
# ([auth] in .streamlit/secrets.toml) replaces it when that's set up.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
# With sign-in: the Google email that gets everything saved before sign-in was turned on.
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
COLLECTION_NAME = "travelplanner_places"

INDEX_BATCH_SIZE = 500
RETRIEVAL_K = 6
MAX_QUERY_VARIANTS = 3
MAX_RESULTS_SHOWN = 10

MAX_AGENT_STEPS = 10  # a full itinerary needs transport, stays, restaurants, costing and checks
