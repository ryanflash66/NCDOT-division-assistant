"""The OpenAI spending estimate for the month, and the cap that hands answers to the free models (DAR-715).

Dr. Namian set the OpenAI budget at $50 a month (November 2026). Every OpenAI
call adds tokens in and out times the model's price to the current calendar
month's total (UTC, as OpenAI bills). Once the total reaches the limit
(OPENAI_MONTHLY_BUDGET_USD minus OPENAI_BUDGET_MARGIN_USD, $45 by default)
OpenAIClient stops asking OpenAI and FallbackClient answers with the free
OpenRouter models until the month ends.

The margin is there because the total is an estimate checked before each call:
a question already under way finishes its calls (up to about 2 cents), several
instances can pass the check at once, and the token counts of a call that broke
off are guessed from its length.

Vercel runs several instances and starts new ones with empty memory, so the
total has to live outside the function: an Upstash Redis database (Vercel's
Marketplace store; it sets KV_REST_API_URL and KV_REST_API_TOKEN, or the
UPSTASH_REDIS_REST_* pair). Without one each instance counts only its own calls
from its own start, which is fine locally and a weak cap on Vercel, so startup
logs a warning and /api/health says "shared": false. When the store can't be
reached the instance keeps counting on its own and answers go on: the
OpenAI dashboard's budget alert is the backstop, not this.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set, Tuple

import httpx

log = logging.getLogger(__name__)

# Dollars per million tokens (input, output), from OpenAI's pricing page on 2026-11-11 (see
# config.DEFAULT_OPENAI_MODEL). Another model needs OPENAI_PRICE_PER_MILLION: a model with no
# known price would make the cap count nothing, so config refuses to start without one.
PRICES_PER_MILLION: Dict[str, Tuple[float, float]] = {
    "gpt-6.1-terra": (1.0, 5.0),
}
DEFAULT_BUDGET_USD = 50.0
DEFAULT_MARGIN_USD = 5.0
# A token is about 4 characters of English: used only for a call whose reply never said how many it used.
CHARS_PER_TOKEN = 4
# Totals are kept as whole micro-dollars, so concurrent INCRBYs add exactly.
MICRO = 1_000_000
STORE_TIMEOUT_SECONDS = 2.0
# A month's key outlives the month by a good while, so last month's total can still be read for a report.
KEY_TTL_SECONDS = 400 * 24 * 3600
KEY_PREFIX = "openai_spend:"

MONTHLY_LIMIT = "The demo has reached this month's AI spending limit. Please try again next month."


def price_for(model: str, env: Optional[Mapping[str, str]] = None,
              setting: str = "OPENAI_PRICE_PER_MILLION") -> Optional[Tuple[float, float]]:
    """The model's (input, output) dollars per million tokens: the setting's "in,out" if set, else the table's."""
    raw = (env or {}).get(setting, "").strip()
    if not raw:
        return PRICES_PER_MILLION.get(model)
    parts = [p.strip() for p in raw.split(",")]
    try:
        prices = tuple(float(p) for p in parts)
    except ValueError:
        raise ValueError(f"{setting} must be two numbers, input,output dollars per million tokens; got {raw!r}") from None
    if len(prices) != 2 or not all(math.isfinite(p) and p >= 0 for p in prices):
        raise ValueError(f"{setting} must be two numbers of 0 or more, input,output; got {raw!r}")
    return prices[0], prices[1]


def cost_usd(prices: Tuple[float, float], input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def usage_tokens(usage: Any) -> Optional[Tuple[int, int]]:
    """(input, output) tokens from a chat completion's `usage`, or None when it has no counts.

    Reasoning tokens are inside completion_tokens; cached input tokens are counted
    at the full input price, which can only overstate the cost.
    """
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return prompt, completion


def estimated_usage(messages: Iterable[Dict[str, str]], written: str, cut_off_at: Optional[int] = None) -> Tuple[int, int]:
    """A guess at a call's tokens when its reply never said: the prompt's and the answer's length.

    `cut_off_at` is the output token cap for an answer that ran into it (all of it was paid for).
    """
    prompt = sum(estimate_tokens(m.get("content") or "") for m in messages)
    return prompt, cut_off_at if cut_off_at is not None else estimate_tokens(written)


class StoreError(Exception):
    pass


class MemoryStore:
    """This instance's own totals (locally, or on Vercel without a shared store)."""

    shared = False

    def __init__(self):
        self._totals: Dict[str, int] = {}

    async def get(self, key: str) -> int:
        return self._totals.get(key, 0)

    async def add(self, key: str, micro: int) -> int:
        self._totals[key] = self._totals.get(key, 0) + micro
        return self._totals[key]


class RedisStore:
    """An Upstash Redis database over its REST API (plain httpx, no Redis client in the bundle)."""

    shared = True

    def __init__(self, url: str, token: str, transport: "httpx.AsyncBaseTransport | None" = None):
        self._url = url.rstrip("/")
        self._token = token
        self._transport = transport

    async def _pipeline(self, *commands: list) -> list:
        try:
            async with httpx.AsyncClient(timeout=STORE_TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(f"{self._url}/pipeline", json=list(commands),
                                             headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise StoreError(f"{exc.__class__.__name__}: {exc}") from exc
        if response.status_code != 200:
            raise StoreError(f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            replies = response.json()
            errors = [r["error"] for r in replies if r.get("error")]
            results = [r.get("result") for r in replies]
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise StoreError(f"unexpected reply: {response.text[:200]}") from exc
        if errors or len(results) != len(commands):
            raise StoreError(f"store error: {errors or response.text[:200]}")
        return results

    async def get(self, key: str) -> int:
        (value,) = await self._pipeline(["GET", key])
        try:
            return int(value or 0)
        except (TypeError, ValueError) as exc:
            raise StoreError(f"not a number at {key}: {value!r}") from exc

    async def add(self, key: str, micro: int) -> int:
        total, _ = await self._pipeline(["INCRBY", key, micro], ["EXPIRE", key, KEY_TTL_SECONDS])
        return int(total)


class SpendLedger:
    """The month's estimated OpenAI spend, shared through `store`, and the limit it is held under."""

    def __init__(self, budget_usd: float = DEFAULT_BUDGET_USD, margin_usd: float = DEFAULT_MARGIN_USD,
                 store: Any = None, clock: Optional[Callable[[], datetime]] = None):
        self.budget_usd = budget_usd
        self.limit_usd = budget_usd - margin_usd
        self.store = store if store is not None else MemoryStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # The last total read or written per month, and what this instance added when the store was down.
        self._known: Dict[str, int] = {}
        self._warned: Set[str] = set()  # months whose limit was already logged here
        self._pending: Set[asyncio.Task] = set()

    def month(self) -> str:
        return self._clock().strftime("%Y-%m")

    def _key(self, month: str) -> str:
        return KEY_PREFIX + month

    async def total_usd(self) -> float:
        month = self.month()
        try:
            self._known[month] = await self.store.get(self._key(month))
        except StoreError as exc:
            log.warning("OpenAI spend store unreachable (%s); using this instance's count", exc)
        return self._known.get(month, 0) / MICRO

    async def over_limit(self) -> bool:
        total = await self.total_usd()
        if total < self.limit_usd:
            return False
        month = self.month()
        if month not in self._warned:
            self._warned.add(month)
            log.warning("OpenAI spend for %s is $%.2f, at the $%.2f limit (budget $%.2f): answering with the free "
                        "OpenRouter models until the month ends", month, total, self.limit_usd, self.budget_usd)
        return True

    async def charge(self, model: str, prices: Tuple[float, float], tokens: Tuple[int, int],
                     estimated: bool = False) -> float:
        """Add one call's cost to the month and log the running total; returns the month's total in dollars."""
        month = self.month()
        cost = cost_usd(prices, *tokens)
        micro = math.ceil(cost * MICRO)
        try:
            self._known[month] = await self.store.add(self._key(month), micro)
        except StoreError as exc:
            log.warning("OpenAI spend store unreachable (%s); counting this call on this instance only", exc)
            self._known[month] = self._known.get(month, 0) + micro
        total = self._known[month] / MICRO
        log.info("openai_spend month=%s total_usd=%.4f call_usd=%.5f model=%s tokens_in=%d tokens_out=%d%s "
                 "limit_usd=%.2f shared=%s", month, total, cost, model, tokens[0], tokens[1],
                 " estimated=true" if estimated else "", self.limit_usd, self.store.shared)
        return total

    def charge_soon(self, model: str, prices: Tuple[float, float], tokens: Tuple[int, int]) -> None:
        """charge() from code that can't wait for it: a stream the visitor left mid-answer."""
        try:
            task = asyncio.get_running_loop().create_task(self.charge(model, prices, tokens, estimated=True))
        except RuntimeError:  # no loop left (the generator was collected after the loop closed)
            log.warning("OpenAI call of about %d+%d tokens could not be counted", *tokens)
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def status(self) -> Dict[str, Any]:
        """The month's numbers for /api/health."""
        total = await self.total_usd()
        return {"month": self.month(), "estimated_usd": round(total, 4), "limit_usd": self.limit_usd,
                "budget_usd": self.budget_usd, "over_limit": total >= self.limit_usd, "shared": self.store.shared}


def store_from_env(env: Mapping[str, str]) -> Any:
    """The shared Upstash store when its URL and token are set (either naming Vercel uses), else this instance's."""
    for url_name, token_name in (("KV_REST_API_URL", "KV_REST_API_TOKEN"),
                                 ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")):
        url, token = env.get(url_name, "").strip(), env.get(token_name, "").strip()
        if url and token:
            return RedisStore(url, token)
    return MemoryStore()
