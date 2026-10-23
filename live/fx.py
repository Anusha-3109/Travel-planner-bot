"""Daily exchange rates for converting prices between currencies.

Primary source: ExchangeRate-API's open endpoint (open.er-api.com), free, no
key, updated once a day, 160+ currencies. Its terms ask for attribution, which
ExchangeRates.source carries into every answer. Backup: the European Central
Bank's daily reference rates (about 30 currencies). Rates are cached for 12
hours, so normally only one request a day is made.
"""

import logging
import re
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

import config
from live import cache
from live.http import LiveDataError, fetch_json
from security.validation import InputValidationError

logger = logging.getLogger(__name__)

PRIMARY_URL = "https://open.er-api.com/v6/latest/USD"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
PRIMARY_SOURCE = "Rates by Exchange Rate API (https://www.exchangerate-api.com)"
ECB_SOURCE = "European Central Bank reference rates"
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")


@dataclass(frozen=True)
class ExchangeRates:
    per_usd: dict[str, float]  # units of each currency for 1 USD
    updated: str  # date the provider published the rates, YYYY-MM-DD
    source: str

    def code(self, currency: object) -> str:
        """A supported currency code, or an error that is safe to show."""
        code = str(currency or "").strip().upper()
        if not _CURRENCY_PATTERN.match(code) or code not in self.per_usd:
            raise InputValidationError(f"'{currency}' isn't a supported currency code. Use codes like USD, EUR, GBP or INR.")
        return code

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        source, target = self.code(from_currency), self.code(to_currency)
        return round(float(amount) / self.per_usd[source] * self.per_usd[target], 2)

    def rate(self, from_currency: str, to_currency: str) -> float:
        """How many units of to_currency one unit of from_currency buys."""
        return self.per_usd[self.code(to_currency)] / self.per_usd[self.code(from_currency)]

    def note(self) -> str:
        return f"Exchange rates from {self.updated} ({self.source})."


def _primary() -> ExchangeRates:
    answer = fetch_json("exchange_rates", PRIMARY_URL, ttl_seconds=config.CACHE_TTL_SECONDS["exchange_rates"],
                        label="The exchange rate service")
    data = answer.data
    if data.get("result") != "success" or not data.get("rates"):
        raise LiveDataError("The exchange rate service returned no rates.")
    updated = datetime.fromtimestamp(data.get("time_last_update_unix", answer.fetched_at), timezone.utc)
    return ExchangeRates({k: float(v) for k, v in data["rates"].items()}, updated.date().isoformat(), PRIMARY_SOURCE)


def _ecb() -> ExchangeRates:
    """The ECB publishes XML with EUR as the base, so it is converted to a USD base here."""
    key = cache.cache_key("exchange_rates", ECB_URL)
    cached = cache.get(key)
    if not cached:
        try:
            response = requests.get(ECB_URL, timeout=config.LIVE_TIMEOUT_SECONDS)
            response.raise_for_status()
            per_eur, day = {"EUR": 1.0}, ""
            for element in ET.fromstring(response.content).iter():
                day = element.get("time") or day
                if element.get("currency"):
                    per_eur[element.get("currency")] = float(element.get("rate"))
        except (requests.RequestException, ET.ParseError, ValueError):
            raise LiveDataError("The ECB exchange rate service couldn't be reached.") from None
        cached = cache.put(key, {"per_eur": per_eur, "date": day}, config.CACHE_TTL_SECONDS["exchange_rates"])
    per_eur = cached.data["per_eur"]
    if "USD" not in per_eur:
        raise LiveDataError("The ECB rates don't include USD.")
    per_usd = {code: rate / per_eur["USD"] for code, rate in per_eur.items()}
    return ExchangeRates(per_usd, cached.data["date"], ECB_SOURCE)


_display_currency: ContextVar[str] = ContextVar("display_currency", default="USD")


@contextmanager
def use_display_currency(currency: str | None):
    """Show listing prices in this currency while the agent answers (the app's currency picker)."""
    token = _display_currency.set((currency or "USD").strip().upper())
    try:
        yield
    finally:
        _display_currency.reset(token)


def display_currency() -> str:
    return _display_currency.get()


def money(amount_usd: float, approx: bool = False, whole: bool = False) -> str:
    """A USD amount as text in the display currency: "$35", "EUR 31.16". Falls back to USD
    when no exchange rate is available."""
    code, prefix = display_currency(), "~" if approx else ""
    if code != "USD":
        try:
            value = get_rates().convert(amount_usd, "USD", code)
            return f"{prefix}{code} {value:,.0f}" if whole else f"{prefix}{code} {value:,.2f}"
        except (LiveDataError, InputValidationError):
            pass
    if whole or float(amount_usd).is_integer():
        return f"{prefix}${amount_usd:,.0f}"
    return f"{prefix}${amount_usd:,.2f}"


def money_range(low_usd: float, high_usd: float | None) -> str:
    """A price range in the display currency: "$22–34", "EUR 20–30", "$50+"."""
    low, high = money(low_usd, whole=True), money(high_usd, whole=True) if high_usd is not None else None
    if high is None:
        return f"{low}+"
    unit = low.split(" ")[0] + " " if " " in low else low[0]
    return f"{low}–{high.removeprefix(unit)}"


def get_rates() -> ExchangeRates:
    """Today's rates. Raises LiveDataError only if both sources fail."""
    try:
        return _primary()
    except LiveDataError as error:
        logger.warning("Primary exchange rates unavailable (%s); trying the ECB", error)
        return _ecb()
