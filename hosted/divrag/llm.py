"""Chat completions over plain HTTP (httpx): OpenRouter (free models only) and OpenAI.

OpenRouter tries `models` in order and falls back to the next one when a model
is down or rate-limited; the response names the model that answered.

OpenAIClient asks OpenAI's API with OPENAI_API_KEY (DAR-679), and
FallbackClient puts it in front of the OpenRouter client, so a missing,
rejected or out-of-budget OpenAI key costs the visitor nothing but the better
model. client_from_settings() picks between them.

complete() waits for the whole answer; complete_stream() hands it over as it is
written (server-sent events), so the page can show the text while the model is
still writing (DAR-629). Both turn every failure into the same LLMErrors.
"""

import json
import logging
import ssl
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# Answers are a few sentences; a long one is cut off and reported as an error.
MAX_TOKENS = 1200
TIMEOUT_SECONDS = 50.0

log = logging.getLogger(__name__)

_tls: Optional[ssl.SSLContext] = None


def tls_context() -> ssl.SSLContext:
    """One TLS context for every call. Building one reads the CA bundle: 0.3 s per
    httpx client locally, on the event loop, which held the stream's "Writing the
    answer" step back that long. The model warm-up builds it ahead of the first question."""
    global _tls
    if _tls is None:
        _tls = httpx.create_ssl_context()
    return _tls


class LLMError(Exception):
    """The model could not answer. `user_message` is safe to show in the browser."""

    def __init__(self, user_message: str, status: int = 503, detail: str = ""):
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.status = status


BUSY = "The free AI model is busy right now (rate limit reached). Please wait a minute and try again."
BUSY_OPENAI = "The AI model is busy right now (rate limit reached). Please wait a minute and try again."
DAILY_LIMIT = "The demo has reached today's free usage limit. Please try again tomorrow."
TOO_SLOW = "That took too long to answer. Please ask again."
UNAVAILABLE = "The AI service didn't respond. Please try again in a moment."
TOO_LONG = "The answer ran too long. Please try a narrower question."
MISCONFIGURED = "The demo's AI service isn't configured correctly. Please let the demo owner know."


@dataclass(frozen=True)
class Completion:
    text: str
    model: str


# OpenRouter's docs show only the generic 429 body; the daily cap on free models
# arrives as "Rate limit exceeded: free-models-per-day ..." in the message, so
# match the message and metadata text rather than one exact field.
_DAILY_MARKERS = ("free-models-per-day", "per-day", "per day")


def _rate_limited(detail: str) -> LLMError:
    """BUSY for a per-minute limit, DAILY_LIMIT when the free daily cap is spent."""
    daily = any(marker in detail.lower() for marker in _DAILY_MARKERS)
    return LLMError(DAILY_LIMIT if daily else BUSY, status=429, detail=detail[:300])


def _status_error(status: int, text: str, service: str = "OpenRouter") -> Optional[LLMError]:
    """The error a reply's HTTP status stands for; None for 200."""
    if status == 429:
        return _rate_limited(text[:2000])
    if status in (401, 402, 403):
        log.error("%s refused the request (%s): %s", service, status, text[:300])
        return LLMError(MISCONFIGURED, detail=text[:300])
    if status != 200:
        log.warning("%s error %s: %s", service, status, text[:300])
        return LLMError(UNAVAILABLE, detail=text[:300])
    return None


def _upstream_error(error: Any, service: str = "OpenRouter") -> LLMError:
    """The error for an `error` object in a reply.

    Errors from the upstream provider can arrive with HTTP 200, and once a
    stream has started they can only arrive as an event in it.
    """
    code = error.get("code") if isinstance(error, dict) else None
    log.warning("%s upstream error %s: %s", service, code, str(error)[:300])
    if code == 429:
        return _rate_limited(str(error))
    return LLMError(UNAVAILABLE, detail=str(error)[:300])


class OpenRouterClient:
    service = "OpenRouter"  # in log lines
    url = API_URL

    def __init__(self, api_key: str, models: Sequence[str], temperature: float = 0.1,
                 reasoning: str = "off", transport: "httpx.AsyncBaseTransport | None" = None):
        if not models:
            raise ValueError("at least one model is required")
        self._api_key = api_key
        self.models = list(models)
        self.temperature = temperature
        self.reasoning = reasoning
        self._transport = transport

    def retry_models(self, used: str) -> List[str]:
        """The models for a second attempt after `used` answered: the ones after it, or `used` again if it was the last."""
        if used in self.models:
            return self.models[self.models.index(used) + 1:] or [used]
        return self.models[1:] or self.models

    def _body(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]], stream: bool) -> Dict:
        body = {
            "models": list(models) if models else self.models,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": MAX_TOKENS,
            # Reasoning off by default: with it on, Nemotron 3 Ultra took up to a
            # minute on multi-part questions and could spend the whole token
            # budget reasoning, returning its notes instead of an answer.
            "reasoning": {"enabled": False} if self.reasoning == "off" else {"effort": self.reasoning, "exclude": True},
            # Defence in depth behind the ":free" model check: never route to a priced endpoint.
            "provider": {"max_price": {"prompt": 0, "completion": 0}},
        }
        if stream:
            body["stream"] = True
        return body

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "X-Title": "NCDOT cross-division Q&A demo"}

    def _status_error(self, status: int, text: str) -> Optional[LLMError]:
        return _status_error(status, text, self.service)

    def _answered_by(self, reported: Optional[str], requested: Optional[Sequence[str]]) -> str:
        """The model to name as the reply's author: the one the service reports, else the first one asked."""
        return reported or (list(requested) if requested else self.models)[0]

    def _http(self) -> httpx.AsyncClient:
        if self._transport is not None:  # tests: a mock transport, no TLS
            return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport)
        return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, verify=tls_context())

    async def complete(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
        """Ask the service; `models` replaces the configured fallback list for this call."""
        try:
            async with self._http() as client:
                response = await client.post(self.url, json=self._body(messages, models, stream=False),
                                             headers=self._headers())
        except httpx.HTTPError as exc:
            log.warning("%s request failed: %s", self.service, exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc

        error = self._status_error(response.status_code, response.text)
        if error:
            raise error
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(UNAVAILABLE, detail=f"non-JSON response: {response.text[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMError(UNAVAILABLE, detail=f"unexpected response: {str(data)[:300]}")
        if data.get("error"):
            raise _upstream_error(data["error"], self.service)
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(UNAVAILABLE, detail=str(data)[:300]) from exc
        if choice.get("finish_reason") == "length":
            raise LLMError(TOO_LONG, detail="answer cut off at max_tokens")
        if not text.strip():
            raise LLMError(UNAVAILABLE, detail="empty answer")
        return Completion(text=text.strip(), model=self._answered_by(data.get("model"), models))

    def complete_stream(self, messages: List[Dict[str, str]],
                        models: Optional[Sequence[str]] = None) -> "CompletionStream":
        """Ask the service for the answer as it is written: `async for piece in` the result.

        The same request as complete(), with `stream: true`. Failures raise the
        same LLMErrors while iterating; afterwards the stream's `text` and
        `model` are what complete() would have returned.
        """
        return CompletionStream(self, messages, models)


class CompletionStream:
    """One streamed answer. Iterating it yields the answer's text in pieces.

    `model` names the model that is answering (OpenRouter may have fallen back
    from the first one) from its first event on; `text` is the whole answer,
    stripped, once the iteration has finished.
    """

    def __init__(self, client: OpenRouterClient, messages: List[Dict[str, str]], models: Optional[Sequence[str]]):
        self._client = client
        self._messages = messages
        self._models = models
        self.model = (list(models) if models else client.models)[0]
        self.text = ""
        self._finished = False  # a finish reason ("stop", ...) arrived

    def __aiter__(self) -> AsyncIterator[str]:
        return self._pieces()

    async def _pieces(self) -> AsyncIterator[str]:
        client = self._client
        written: List[str] = []
        ended = False
        try:
            async with client._http() as http:
                body = client._body(self._messages, self._models, stream=True)
                async with http.stream("POST", client.url, json=body, headers=client._headers()) as response:
                    if response.status_code != 200:
                        # Errors before the first token come back as an ordinary JSON reply.
                        await response.aread()
                        raise client._status_error(response.status_code, response.text) or LLMError(UNAVAILABLE)
                    async for data in _sse_data(response.aiter_lines()):
                        if data == "[DONE]":
                            ended = True
                            break
                        piece = self._read(data)
                        if piece:
                            written.append(piece)
                            yield piece
        except httpx.HTTPError as exc:
            log.warning("%s stream failed: %s", client.service, exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc
        # A connection closed cleanly mid-answer (by OpenRouter or a proxy) would otherwise
        # pass for a finished answer: only [DONE] or a finish reason says the model was done.
        if not (ended or self._finished):
            raise LLMError(UNAVAILABLE, detail="stream closed before the answer finished")
        self.text = "".join(written).strip()
        if not self.text:
            raise LLMError(UNAVAILABLE, detail="empty answer")

    def _read(self, data: str) -> str:
        """The answer text in one event; raises the LLMError an error event stands for."""
        try:
            event = json.loads(data)
        except ValueError as exc:
            raise LLMError(UNAVAILABLE, detail=f"non-JSON event: {data[:300]}") from exc
        if not isinstance(event, dict):
            raise LLMError(UNAVAILABLE, detail=f"unexpected event: {data[:300]}")
        if event.get("error"):
            raise _upstream_error(event["error"], self._client.service)
        if event.get("model"):
            self.model = self._client._answered_by(event["model"], self._models)
        choices = event.get("choices") or []  # the closing usage event has none
        if not isinstance(choices, list) or (choices and not isinstance(choices[0], dict)):
            raise LLMError(UNAVAILABLE, detail=f"unexpected event: {data[:300]}")
        if not choices:
            return ""
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise LLMError(TOO_LONG, detail="answer cut off at max_tokens")
        if choice.get("finish_reason") == "error":
            raise LLMError(UNAVAILABLE, detail=f"stream ended with an error: {data[:300]}")
        if choice.get("finish_reason"):
            self._finished = True
        delta = choice.get("delta")
        # The answer's content only: reasoning, if a provider sends it, is never shown.
        return (delta.get("content") or "") if isinstance(delta, dict) else ""


# What a 429 from OpenAI says when the key's money or budget is spent rather than its rate limit
# (developers.openai.com/api/docs/guides/error-codes, read 2026-11-11): waiting a minute won't help.
_OPENAI_BILLING = ("insufficient_quota", "credit_balance_exhausted", "spend_limit_exceeded", "usage_limit_exceeded")
# Extra room when LLM_REASONING is on: OpenAI counts reasoning tokens inside max_completion_tokens,
# so MAX_TOKENS alone could be spent before the answer starts.
REASONING_TOKENS = 4000


class OpenAIClient(OpenRouterClient):
    """OpenAI's chat completions with the same complete()/complete_stream() as OpenRouterClient (DAR-679).

    OpenAI takes one model per request, so only the first of `models` is asked.
    """

    service = "OpenAI"
    url = OPENAI_URL

    def _body(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]], stream: bool) -> Dict:
        thinking = self.reasoning != "off"
        body: Dict[str, Any] = {
            "model": (list(models) if models else self.models)[0],
            "messages": messages,
            # max_tokens is deprecated there and refused by reasoning models.
            "max_completion_tokens": MAX_TOKENS + (REASONING_TOKENS if thinking else 0),
            # "none" is what LLM_REASONING=off means for the default model (config.DEFAULT_OPENAI_MODEL):
            # no reasoning tokens to pay or wait for, and temperature stays settable.
            "reasoning_effort": self.reasoning if thinking else "none",
        }
        if not thinking:  # OpenAI's reasoning guide: leave temperature out unless the effort is none
            body["temperature"] = self.temperature
        if stream:
            body["stream"] = True
        return body

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _status_error(self, status: int, text: str) -> Optional[LLMError]:
        if status == 429:
            if any(code in text for code in _OPENAI_BILLING):
                log.error("OpenAI key is out of credit or over its spend limit: %s", text[:300])
                return LLMError(MISCONFIGURED, detail=text[:300])
            return LLMError(BUSY_OPENAI, status=429, detail=text[:300])
        return _status_error(status, text, self.service)

    def _answered_by(self, reported: Optional[str], requested: Optional[Sequence[str]]) -> str:
        # The configured name, not the dated snapshot OpenAI reports: the Answerer hands a
        # reply's model back as the one to ask again, and FallbackClient tells the two
        # services' models apart by these names.
        return (list(requested) if requested else self.models)[0]


def _falls_back(error: LLMError) -> bool:
    """Whether the other service should be asked after this failure: all but an answer that ran too long."""
    return error.user_message != TOO_LONG


def _brief(error: LLMError) -> str:
    """The error on one short log line (the service's JSON error body runs over several)."""
    return " ".join(str(error).split())[:160]


class FallbackClient:
    """`primary` (OpenAI) with `fallback` (free OpenRouter models) behind it, as one client.

    `models` is one list, the primary's first, so the Answerer's "next model"
    after a refusal is the first free model, as it is between the free models.
    A call asks the primary with its models in the list; when that fails (key
    rejected, budget spent, rate limit, outage) the fallback is asked with the
    rest, so the site keeps answering.
    """

    def __init__(self, primary: OpenRouterClient, fallback: OpenRouterClient):
        self.primary = primary
        self.fallback = fallback
        self.models = list(dict.fromkeys([*primary.models, *fallback.models]))

    retry_models = OpenRouterClient.retry_models

    def _split(self, models: Optional[Sequence[str]]) -> Tuple[List[str], List[str]]:
        """The models of a call, as the primary's and the fallback's."""
        asked = list(models) if models else self.models
        return ([m for m in asked if m in self.primary.models], [m for m in asked if m not in self.primary.models])

    async def complete(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
        first, rest = self._split(models)
        if first:
            try:
                return await self.primary.complete(messages, models=first)
            except LLMError as exc:
                if not (rest and _falls_back(exc)):
                    raise
                log.warning("%s failed (%s); answering with %s", self.primary.service, _brief(exc), self.fallback.service)
        return await self.fallback.complete(messages, models=rest)

    def complete_stream(self, messages: List[Dict[str, str]],
                        models: Optional[Sequence[str]] = None) -> "FallbackStream":
        return FallbackStream(self, messages, models)


class FallbackStream:
    """CompletionStream over a FallbackClient: `model` and `text` are the answering stream's.

    The fallback takes over only before the first piece of text: once the page
    has shown some of an answer, a failure is reported like any other.
    """

    def __init__(self, client: FallbackClient, messages: List[Dict[str, str]], models: Optional[Sequence[str]]):
        self._client = client
        self._messages = messages
        self._first, self._rest = client._split(models)
        self.model = (self._first or self._rest)[0]
        self.text = ""

    def __aiter__(self) -> AsyncIterator[str]:
        return self._pieces()

    async def _relay(self, stream: CompletionStream) -> AsyncIterator[str]:
        self.model = stream.model
        async for piece in stream:
            self.model = stream.model
            yield piece
        self.model, self.text = stream.model, stream.text

    async def _pieces(self) -> AsyncIterator[str]:
        client = self._client
        if self._first:
            started = False
            try:
                async for piece in self._relay(client.primary.complete_stream(self._messages, models=self._first)):
                    started = True
                    yield piece
                return
            except LLMError as exc:
                if started or not (self._rest and _falls_back(exc)):
                    raise
                log.warning("%s failed (%s); answering with %s", client.primary.service, _brief(exc), client.fallback.service)
        async for piece in self._relay(client.fallback.complete_stream(self._messages, models=self._rest)):
            yield piece


def client_from_settings(settings: Any, transport: "httpx.AsyncBaseTransport | None" = None):
    """The answering client for the settings (config.Settings), or None when no usable key is set.

    LLM_PROVIDER=openai with OPENAI_API_KEY: OpenAI, with the free OpenRouter
    models behind it when OPENROUTER_API_KEY is set too. Otherwise OpenRouter
    alone, which is also what a deployment that selects OpenAI but has lost
    its key falls back to.
    """
    openrouter = None
    if settings.openrouter_api_key:
        openrouter = OpenRouterClient(settings.openrouter_api_key, settings.models, settings.temperature,
                                      settings.reasoning, transport=transport)
    if settings.llm_provider != "openai" or not settings.openai_api_key:
        return openrouter
    openai = OpenAIClient(settings.openai_api_key, [settings.openai_model], settings.temperature,
                          settings.reasoning, transport=transport)
    return FallbackClient(openai, openrouter) if openrouter else openai


async def _sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """The data of each server-sent event, skipping comments such as ": OPENROUTER PROCESSING".

    OpenRouter sends those comments while a model starts up, to keep the
    connection open. An event's data may span several "data:" lines, joined
    with newlines; a blank line ends the event.
    """
    data: List[str] = []
    async for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)
