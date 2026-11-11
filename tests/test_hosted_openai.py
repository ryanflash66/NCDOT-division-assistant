"""Tests for the hosted demo's OpenAI answer path (DAR-679): the setting, the client and the OpenRouter fallback."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.config import DEFAULT_OPENAI_MODEL, load_settings  # noqa: E402
from divrag.llm import (  # noqa: E402
    API_URL, BUSY_OPENAI, MISCONFIGURED, OPENAI_URL, TOO_LONG, Completion, FallbackClient, LLMError, OpenAIClient,
    OpenRouterClient, client_from_settings,
)

OPENAI = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-openai", "OPENROUTER_API_KEY": "sk-or"}
FREE = "nvidia/nemotron-3-ultra-550b-a55b:free"
MESSAGES = [{"role": "user", "content": "hi"}]


def _reply(text="Answer [1].", model="some/model:free", finish="stop"):
    return httpx.Response(200, json={"model": model, "choices": [{"finish_reason": finish, "message": {"content": text}}]})


def _sse(*events):
    return httpx.Response(200, text="".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events))


def _chunk(text, model, finish=None):
    return {"model": model, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


def _router(openai, openrouter, seen=None):
    """A transport answering each service with its own handler, recording (url, body) in `seen`."""
    def handler(request):
        if seen is not None:
            seen.append((str(request.url), json.loads(request.content), request.headers["authorization"]))
        return (openai if str(request.url) == OPENAI_URL else openrouter)(request)
    return httpx.MockTransport(handler)


def _client(openai, openrouter, seen=None, env=OPENAI):
    return client_from_settings(load_settings(env), transport=_router(openai, openrouter, seen))


def _stream(client, models=None):
    pieces = []

    async def run():
        stream = client.complete_stream(MESSAGES, models=models)
        async for piece in stream:
            pieces.append(piece)
        return stream

    return pieces, asyncio.run(run())


# Settings

def test_openai_is_used_only_when_the_provider_is_selected_on_purpose():
    default = load_settings({})
    assert default.llm_provider == "openrouter" and not default.answers_with_openai
    assert all(m.endswith(":free") for m in default.answer_models)
    # The key or a model name alone changes nothing: no paid call without LLM_PROVIDER=openai.
    key_only = load_settings({"OPENAI_API_KEY": "sk-openai", "OPENAI_MODEL": "gpt-6-astra", "OPENROUTER_API_KEY": "k"})
    assert not key_only.answers_with_openai and key_only.answer_models == key_only.models
    assert isinstance(client_from_settings(key_only), OpenRouterClient)

    chosen = load_settings(OPENAI)
    assert chosen.answers_with_openai and chosen.llm_configured
    assert chosen.answer_models == (DEFAULT_OPENAI_MODEL,) + chosen.models
    assert load_settings({**OPENAI, "OPENAI_MODEL": "gpt-6.1-sol"}).answer_models[0] == "gpt-6.1-sol"


def test_openrouter_models_must_still_be_free_with_the_openai_provider():
    with pytest.raises(ValueError):
        load_settings({**OPENAI, "OPENROUTER_MODEL": "openai/gpt-4o"})


def test_provider_setting_is_validated_and_the_chainlit_apps_value_is_ignored():
    with pytest.raises(ValueError):
        load_settings({"LLM_PROVIDER": "opnai"})
    assert load_settings({"LLM_PROVIDER": " OpenAI "}).llm_provider == "openai"
    # The repo's one .env sets LLM_PROVIDER=ollama for the Chainlit app; the hosted app must still start.
    assert load_settings({"LLM_PROVIDER": "ollama"}).llm_provider == "openrouter"


def test_a_missing_openai_key_leaves_openrouter_answering():
    settings = load_settings({"LLM_PROVIDER": "openai", "OPENROUTER_API_KEY": "sk-or"})
    assert not settings.answers_with_openai and settings.llm_configured
    assert settings.answer_models == settings.models
    client = client_from_settings(settings)
    assert type(client) is OpenRouterClient and client.models == list(settings.models)


def test_which_client_the_keys_give():
    assert client_from_settings(load_settings({})) is None
    assert client_from_settings(load_settings({"LLM_PROVIDER": "openai"})) is None
    alone = load_settings({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-openai"})
    assert type(client_from_settings(alone)) is OpenAIClient and alone.answer_models == (DEFAULT_OPENAI_MODEL,)
    both = client_from_settings(load_settings(OPENAI))
    assert isinstance(both, FallbackClient) and both.models[0] == DEFAULT_OPENAI_MODEL and both.models[1] == FREE


# The OpenAI client

def test_openai_request_names_one_model_and_turns_reasoning_off():
    seen = []
    client = _client(lambda r: _reply(model="gpt-6.1-terra-2026-10-01"), lambda r: _reply(), seen)

    completion = asyncio.run(client.complete(MESSAGES))

    # The configured name, not OpenAI's dated snapshot: it is handed back as the model to ask again.
    assert completion == Completion("Answer [1].", DEFAULT_OPENAI_MODEL)
    assert len(seen) == 1
    url, body, auth = seen[0]
    assert url == OPENAI_URL and auth == "Bearer sk-openai"
    assert body == {"model": DEFAULT_OPENAI_MODEL, "messages": MESSAGES, "max_completion_tokens": 1200,
                    "reasoning_effort": "none", "temperature": 0.1}


def test_openai_reasoning_drops_temperature_and_leaves_room_for_reasoning_tokens():
    seen = []
    client = _client(lambda r: _reply(), lambda r: _reply(), seen, env={**OPENAI, "LLM_REASONING": "low"})
    asyncio.run(client.complete(MESSAGES))
    body = seen[0][1]
    assert body["reasoning_effort"] == "low" and "temperature" not in body
    assert body["max_completion_tokens"] > 1200


@pytest.mark.parametrize("body, message, status", [
    ({"error": {"message": "Rate limit reached for requests", "type": "rate_limit_error", "code": "slow_down"}}, BUSY_OPENAI, 429),
    ({"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "credit_balance_exhausted"}}, MISCONFIGURED, 503),
    ({"error": {"message": "Spend limit", "code": "project_spend_limit_exceeded"}}, MISCONFIGURED, 503),
])
def test_openai_alone_reports_rate_limits_and_a_spent_budget_without_details(body, message, status):
    client = OpenAIClient("sk-openai", ["gpt-6.1-terra"], transport=httpx.MockTransport(lambda r: httpx.Response(429, json=body)))
    with pytest.raises(LLMError) as caught:
        asyncio.run(client.complete(MESSAGES))
    assert caught.value.user_message == message and caught.value.status == status
    assert "free" not in caught.value.user_message


# The fallback to OpenRouter

@pytest.mark.parametrize("failure", [
    httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}}),
    httpx.Response(429, json={"error": {"code": "project_spend_limit_exceeded"}}),
    httpx.Response(429, json={"error": {"code": "slow_down"}}),
    httpx.Response(500, text="oops"),
    httpx.Response(400, json={"error": {"message": "Unsupported value: reasoning_effort"}}),
])
def test_openrouter_answers_when_openai_cannot(failure):
    seen = []
    client = _client(lambda r: failure, lambda r: _reply("From the free model [1].", FREE), seen)

    completion = asyncio.run(client.complete(MESSAGES))

    assert completion == Completion("From the free model [1].", FREE)
    assert [url for url, _, _ in seen] == [OPENAI_URL, API_URL]
    body, auth = seen[1][1], seen[1][2]
    # Only the free models go to OpenRouter, with its own key and the zero price cap.
    assert auth == "Bearer sk-or" and all(m.endswith(":free") for m in body["models"])
    assert body["provider"] == {"max_price": {"prompt": 0, "completion": 0}}


def test_openrouter_answers_when_openai_is_unreachable():
    def down(request):
        raise httpx.ConnectError("boom")

    completion = asyncio.run(_client(down, lambda r: _reply(model=FREE)).complete(MESSAGES))
    assert completion.model == FREE


def test_an_answer_that_ran_too_long_is_not_asked_again_elsewhere():
    seen = []
    client = _client(lambda r: _reply("We need to", finish="length"), lambda r: _reply(), seen)
    with pytest.raises(LLMError) as caught:
        asyncio.run(client.complete(MESSAGES))
    assert caught.value.user_message == TOO_LONG and len(seen) == 1


def test_both_services_failing_reports_the_fallbacks_error():
    client = _client(lambda r: httpx.Response(401, text="bad key"), lambda r: httpx.Response(401, text="bad key"))
    with pytest.raises(LLMError) as caught:
        asyncio.run(client.complete(MESSAGES))
    assert caught.value.user_message == MISCONFIGURED


def test_the_next_model_after_openai_is_the_first_free_one():
    client = _client(lambda r: _reply(), lambda r: _reply())
    assert client.retry_models(DEFAULT_OPENAI_MODEL)[0] == FREE
    assert DEFAULT_OPENAI_MODEL not in client.retry_models(DEFAULT_OPENAI_MODEL)
    # OpenAI alone has no next model: the same one is asked again.
    alone = client_from_settings(load_settings({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"}))
    assert alone.retry_models(DEFAULT_OPENAI_MODEL) == [DEFAULT_OPENAI_MODEL]


def test_a_call_for_the_free_models_only_never_reaches_openai():
    seen = []
    client = _client(lambda r: _reply(), lambda r: _reply(model=FREE), seen)

    asyncio.run(client.complete(MESSAGES, models=client.retry_models(DEFAULT_OPENAI_MODEL)))  # the retry after a refusal
    assert [url for url, _, _ in seen] == [API_URL]

    seen.clear()
    # The recheck: the model that wrote the answer first, then the rest.
    asyncio.run(client.complete(MESSAGES, models=[DEFAULT_OPENAI_MODEL, FREE]))
    assert [url for url, _, _ in seen] == [OPENAI_URL] and seen[0][1]["model"] == DEFAULT_OPENAI_MODEL


# Streaming

def test_openai_stream_yields_the_text_and_names_the_configured_model():
    seen = []
    openai = lambda r: _sse(_chunk("Three ", "gpt-6.1-terra-2026-10-01"),  # noqa: E731
                            _chunk("feet [1].", "gpt-6.1-terra-2026-10-01", finish="stop"), "[DONE]")
    pieces, stream = _stream(_client(openai, lambda r: _reply(), seen))

    assert pieces == ["Three ", "feet [1]."]
    assert (stream.text, stream.model) == ("Three feet [1].", DEFAULT_OPENAI_MODEL)
    assert len(seen) == 1 and seen[0][1]["stream"] is True and seen[0][1]["model"] == DEFAULT_OPENAI_MODEL


def test_stream_falls_back_to_openrouter_before_any_text_is_shown():
    seen = []
    openrouter = lambda r: _sse(_chunk("Free ", FREE), _chunk("answer [1].", FREE, finish="stop"), "[DONE]")  # noqa: E731
    pieces, stream = _stream(_client(lambda r: httpx.Response(401, text="bad key"), openrouter, seen))

    assert pieces == ["Free ", "answer [1]."]
    assert (stream.text, stream.model) == ("Free answer [1].", FREE)
    assert [url for url, _, _ in seen] == [OPENAI_URL, API_URL]


def test_stream_that_fails_after_showing_text_is_an_error_not_a_second_answer():
    seen = []
    openai = lambda r: _sse(_chunk("Three ", "gpt-6.1-terra"))  # noqa: E731  (closed with no finish reason)
    client = _client(openai, lambda r: _reply(), seen)
    with pytest.raises(LLMError):
        _stream(client)
    assert [url for url, _, _ in seen] == [OPENAI_URL]
