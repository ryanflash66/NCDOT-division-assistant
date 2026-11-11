"""Tests for the monthly OpenAI spending cap (DAR-715): the estimate, the switch to OpenRouter and the shared store."""

import asyncio
import dataclasses
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.config import load_settings  # noqa: E402
from divrag.llm import MAX_TOKENS, OPENAI_URL, TOO_LONG, LLMError, client_from_settings  # noqa: E402
from divrag.spend import (  # noqa: E402
    MONTHLY_LIMIT, MemoryStore, RedisStore, SpendLedger, StoreError, cost_usd, price_for, store_from_env,
)

OPENAI = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-openai", "OPENROUTER_API_KEY": "sk-or"}
FREE = "nvidia/nemotron-3-ultra-550b-a55b:free"
MESSAGES = [{"role": "user", "content": "x" * 400}]  # about 100 tokens
NOV = datetime(2026, 11, 20, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, now=NOV):
        self.now = now

    def __call__(self):
        return self.now


def _usage(prompt=5000, completion=300):
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def _openai_reply(usage=None, finish="stop"):
    body = {"model": "gpt-6.1-terra-2026-10-01", "choices": [{"finish_reason": finish, "message": {"content": "Answer [1]."}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _free_reply(request):
    if json.loads(request.content).get("stream"):
        return _sse({"model": FREE, "choices": [{"index": 0, "delta": {"content": "Free [1]."}, "finish_reason": "stop"}]},
                    "[DONE]")
    return httpx.Response(200, json={"model": FREE, "choices": [{"finish_reason": "stop", "message": {"content": "Free [1]."}}]})


def _sse(*events):
    return httpx.Response(200, text="".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events))


def _chunk(text, finish=None):
    return {"model": "gpt-6.1-terra", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


def _setup(openai, budget=50.0, margin=5.0, store=None, clock=None, env=OPENAI):
    """A FallbackClient with a ledger, and the list of (service, body) requests it sent."""
    seen = []

    def handler(request):
        body = json.loads(request.content)
        if str(request.url) == OPENAI_URL:
            seen.append(("openai", body))
            return openai(request)
        seen.append(("openrouter", body))
        return _free_reply(request)

    ledger = SpendLedger(budget, margin, store or MemoryStore(), clock=clock or _Clock())
    client = client_from_settings(load_settings(env), transport=httpx.MockTransport(handler), ledger=ledger)
    return client, ledger, seen


def _stream(client):
    async def run():
        stream = client.complete_stream(MESSAGES)
        pieces = [piece async for piece in stream]
        return pieces, stream
    return asyncio.run(run())


# The estimate

def test_a_call_costs_its_tokens_times_the_models_price():
    terra = price_for("gpt-6.1-terra")
    assert terra == (1.0, 5.0)
    # The README's estimate: about 5,000 tokens in and 300 out is 0.65 cents.
    assert cost_usd(terra, 5000, 300) == pytest.approx(0.0065)
    assert price_for("gpt-6.1-sol") is None
    assert price_for("gpt-6.1-sol", {"OPENAI_PRICE_PER_MILLION": "2, 10"}) == (2.0, 10.0)
    for bad in ("2", "a,b", "-1,5", "nan,5"):
        with pytest.raises(ValueError):
            price_for("gpt-6.1-sol", {"OPENAI_PRICE_PER_MILLION": bad})


def test_each_openai_answer_adds_its_reported_usage_to_the_month(caplog):
    client, ledger, seen = _setup(lambda r: _openai_reply(_usage(5000, 300)))
    with caplog.at_level(logging.INFO, logger="divrag.spend"):
        assert asyncio.run(client.complete(MESSAGES)).model == "gpt-6.1-terra"
        asyncio.run(client.complete(MESSAGES))
    assert asyncio.run(ledger.total_usd()) == pytest.approx(0.013)
    # The running total is logged for the report.
    line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("openai_spend")][-1]
    assert "month=2026-11" in line and "total_usd=0.0130" in line and "tokens_in=5000" in line
    assert [s for s, _ in seen] == ["openai", "openai"]


def test_a_streamed_answer_asks_for_its_usage_and_counts_it():
    events = [_chunk("Answer "), _chunk("[1].", finish="stop"), {"choices": [], "usage": _usage(4000, 200)}, "[DONE]"]
    client, ledger, seen = _setup(lambda r: _sse(*events))
    pieces, stream = _stream(client)
    assert "".join(pieces) == "Answer [1]." and stream.model == "gpt-6.1-terra"
    assert seen[0][1]["stream_options"] == {"include_usage": True}
    assert asyncio.run(ledger.total_usd()) == pytest.approx(cost_usd((1.0, 5.0), 4000, 200))


def test_a_reply_without_usage_is_estimated_from_its_length():
    client, ledger, _ = _setup(lambda r: _openai_reply(usage=None))
    asyncio.run(client.complete(MESSAGES))
    # 400 characters in (100 tokens) and "Answer [1]." out (3 tokens).
    assert asyncio.run(ledger.total_usd()) == pytest.approx(cost_usd((1.0, 5.0), 100, 3))


def test_an_answer_cut_off_at_the_token_cap_is_still_counted():
    # A stream that hit max tokens raises TOO_LONG before its usage event; the whole cap was paid for.
    client, ledger, _ = _setup(lambda r: _sse(_chunk("Long "), _chunk("answer", finish="length")))
    openai = client.primary  # OpenAI alone, so the error reaches the caller

    async def run():
        with pytest.raises(LLMError) as raised:
            async for _ in openai.complete_stream(MESSAGES):
                pass
        # The charge of a broken-off stream is scheduled, not awaited: it lands on the same loop.
        await asyncio.gather(*ledger._pending)
        return raised.value, await ledger.total_usd()

    error, total = asyncio.run(run())
    assert error.user_message == TOO_LONG
    assert total == pytest.approx(cost_usd((1.0, 5.0), 100, MAX_TOKENS))


def test_a_stream_the_visitor_left_is_counted_for_what_was_written():
    events = [_chunk("Answer " * 40), _chunk("more"), _chunk("[1].", finish="stop"), "[DONE]"]
    client, ledger, _ = _setup(lambda r: _sse(*events))

    async def leave_early():
        stream = client.primary.complete_stream(MESSAGES)
        pieces = stream.__aiter__()
        await pieces.__anext__()
        await pieces.aclose()  # what cancelling the answer does to the generator
        await asyncio.gather(*ledger._pending)
        return await ledger.total_usd()

    assert asyncio.run(leave_early()) == pytest.approx(cost_usd((1.0, 5.0), 100, 70))


def test_a_refused_request_costs_nothing():
    client, ledger, seen = _setup(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    assert asyncio.run(client.complete(MESSAGES)).model == FREE
    assert asyncio.run(ledger.total_usd()) == 0
    assert [s for s, _ in seen] == ["openai", "openrouter"]


# The switch

def test_answers_switch_to_openrouter_once_the_months_estimate_passes_the_limit(caplog):
    # A $0.02 budget with a $0.01 margin: the second answer at 0.65 cents each crosses $0.01.
    client, ledger, seen = _setup(lambda r: _openai_reply(_usage(5000, 300)), budget=0.02, margin=0.01)
    first = asyncio.run(client.complete(MESSAGES))
    second = asyncio.run(client.complete(MESSAGES))
    assert (first.model, second.model) == ("gpt-6.1-terra", "gpt-6.1-terra")
    assert asyncio.run(ledger.over_limit())
    with caplog.at_level(logging.WARNING):
        third = asyncio.run(client.complete(MESSAGES))
        pieces, stream = _stream(client)
    # The reply's model field shows the free model answered, and OpenAI wasn't called again.
    assert third.model == FREE and stream.model == FREE and "".join(pieces) == "Free [1]."
    assert [s for s, _ in seen] == ["openai", "openai", "openrouter", "openrouter"]
    assert any("at the $0.01 limit" in r.getMessage() for r in caplog.records)
    # Spending stopped where it was: free answers cost nothing.
    assert asyncio.run(ledger.total_usd()) == pytest.approx(0.013)


def test_the_default_limit_is_45_of_the_50_dollar_budget():
    settings = load_settings(OPENAI)
    assert (settings.openai_monthly_budget_usd, settings.openai_limit_usd) == (50.0, 45.0)
    store = MemoryStore()
    client, ledger, seen = _setup(lambda r: _openai_reply(_usage()), store=store)
    asyncio.run(store.add("openai_spend:2026-11", 44_990_000))  # $44.99 so far
    assert asyncio.run(client.complete(MESSAGES)).model == "gpt-6.1-terra"
    asyncio.run(store.add("openai_spend:2026-11", 10_000))  # $45.0065 now
    assert asyncio.run(client.complete(MESSAGES)).model == FREE
    assert [s for s, _ in seen] == ["openai", "openrouter"]


def test_openai_answers_again_when_the_next_month_starts():
    clock = _Clock()
    client, ledger, _ = _setup(lambda r: _openai_reply(_usage()), budget=0.01, margin=0.005, clock=clock)
    asyncio.run(client.complete(MESSAGES))
    assert asyncio.run(client.complete(MESSAGES)).model == FREE
    clock.now = datetime(2026, 12, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert asyncio.run(client.complete(MESSAGES)).model == "gpt-6.1-terra"
    assert ledger.month() == "2026-12"


def test_without_openrouter_the_limit_is_a_clear_error():
    client, ledger, _ = _setup(lambda r: _openai_reply(_usage()), budget=0.0, margin=0.0,
                               env={"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-openai"})
    with pytest.raises(LLMError) as raised:
        asyncio.run(client.complete(MESSAGES))
    assert raised.value.user_message == MONTHLY_LIMIT


# The settings

def test_budget_settings_are_validated():
    assert load_settings({**OPENAI, "OPENAI_MONTHLY_BUDGET_USD": "100", "OPENAI_BUDGET_MARGIN_USD": "10"}).openai_limit_usd == 90
    for env in ({"OPENAI_MONTHLY_BUDGET_USD": "10", "OPENAI_BUDGET_MARGIN_USD": "10"},
                {"OPENAI_MONTHLY_BUDGET_USD": "-5"}, {"OPENAI_BUDGET_MARGIN_USD": "lots"}):
        with pytest.raises(ValueError):
            load_settings({**OPENAI, **env})
    # A model with no known price can't be the paid model: its spend would never be counted.
    with pytest.raises(ValueError, match="OPENAI_PRICE_PER_MILLION"):
        load_settings({**OPENAI, "OPENAI_MODEL": "gpt-6-astra"})
    # Without LLM_PROVIDER=openai no price is needed: OpenAI is never called.
    assert load_settings({"OPENAI_MODEL": "gpt-6-astra"}).openai_prices is None


# The shared store

class _Upstash:
    """An Upstash REST pipeline endpoint over a dict, recording the commands it got."""

    def __init__(self, fail=False):
        self.data = {}
        self.commands = []
        self.fail = fail

    def __call__(self, request):
        assert request.url.path == "/pipeline" and request.headers["authorization"] == "Bearer kv-token"
        if self.fail:
            return httpx.Response(503, text="down")
        replies = []
        for command in json.loads(request.content):
            self.commands.append(command)
            name, key = command[0], command[1]
            if name == "GET":
                replies.append({"result": self.data.get(key)})
            elif name == "INCRBY":
                self.data[key] = str(int(self.data.get(key, "0")) + command[2])
                replies.append({"result": int(self.data[key])})
            else:
                replies.append({"result": 1})
        return httpx.Response(200, json=replies)


def test_every_instance_shares_one_monthly_total_through_the_store():
    upstash = _Upstash()
    store = lambda: RedisStore("https://kv.example.upstash.io", "kv-token", transport=httpx.MockTransport(upstash))  # noqa: E731
    one = SpendLedger(1.0, 0.5, store(), clock=_Clock())
    two = SpendLedger(1.0, 0.5, store(), clock=_Clock())
    asyncio.run(one.charge("gpt-6.1-terra", (1.0, 5.0), (200_000, 20_000)))  # $0.30
    asyncio.run(two.charge("gpt-6.1-terra", (1.0, 5.0), (200_000, 20_000)))
    assert asyncio.run(one.total_usd()) == pytest.approx(0.6) and asyncio.run(one.over_limit())
    assert upstash.data == {"openai_spend:2026-11": "600000"}  # whole micro-dollars
    assert ["EXPIRE", "openai_spend:2026-11", 400 * 24 * 3600] in upstash.commands
    status = asyncio.run(two.status())
    assert status == {"month": "2026-11", "estimated_usd": 0.6, "limit_usd": 0.5, "budget_usd": 1.0,
                      "over_limit": True, "shared": True}


def test_an_unreachable_store_keeps_answering_and_counts_on_the_instance(caplog):
    upstash = _Upstash(fail=True)
    store = RedisStore("https://kv.example.upstash.io", "kv-token", transport=httpx.MockTransport(upstash))
    with pytest.raises(StoreError):
        asyncio.run(store.get("k"))
    client, ledger, _ = _setup(lambda r: _openai_reply(_usage()), store=store)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(client.complete(MESSAGES)).model == "gpt-6.1-terra"
    assert asyncio.run(ledger.total_usd()) == pytest.approx(0.0065)
    assert any("store unreachable" in r.getMessage() for r in caplog.records)


def test_the_store_comes_from_vercels_kv_variables():
    assert isinstance(store_from_env({}), MemoryStore)
    assert not store_from_env({}).shared
    for env in ({"KV_REST_API_URL": "https://a.upstash.io", "KV_REST_API_TOKEN": "t"},
                {"UPSTASH_REDIS_REST_URL": "https://a.upstash.io", "UPSTASH_REDIS_REST_TOKEN": "t"}):
        assert isinstance(store_from_env(env), RedisStore)
    assert isinstance(store_from_env({"KV_REST_API_URL": "https://a.upstash.io"}), MemoryStore)  # no token


# The API

def test_health_shows_the_months_estimated_spend_without_secrets(monkeypatch):
    from fastapi.testclient import TestClient

    import index as hosted

    ledger = SpendLedger(50.0, 5.0, MemoryStore(), clock=_Clock())
    asyncio.run(ledger.charge("gpt-6.1-terra", (1.0, 5.0), (1_000_000, 100_000)))  # $1.50
    monkeypatch.setattr(hosted, "spend", ledger)
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, llm_provider="openai",
                                                                openai_api_key="sk-openai-secret"))
    health = TestClient(hosted.app).get("/api/health").json()
    assert health["openai_spend"] == {"month": "2026-11", "estimated_usd": 1.5, "limit_usd": 45.0, "budget_usd": 50.0,
                                      "over_limit": False, "shared": False}
    assert "sk-openai-secret" not in str(health)
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, llm_provider="openrouter"))
    assert TestClient(hosted.app).get("/api/health").json()["openai_spend"] is None


# Evaluation runs (DAR-650, DAR-661) on the same key

def _judge_reply(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={"model": body["model"], "usage": _usage(6000, 1000),
                                     "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]})


def test_an_evaluation_judge_on_openai_counts_against_the_same_month_and_stops_at_the_limit():
    from evaluation.judge import ChatClient

    ledger = SpendLedger(0.03, 0.01, MemoryStore(), clock=_Clock())  # $0.02 limit; a verdict is $0.011
    judge = ChatClient("https://api.openai.com/v1", "key", ["gpt-6.1-terra"], transport=httpx.MockTransport(_judge_reply),
                       ledger=ledger, prices={"gpt-6.1-terra": (1.0, 5.0)})
    asyncio.run(judge.complete(MESSAGES))
    asyncio.run(judge.complete(MESSAGES))
    assert asyncio.run(ledger.total_usd()) == pytest.approx(0.022)
    with pytest.raises(LLMError) as raised:
        asyncio.run(judge.complete(MESSAGES))
    assert raised.value.user_message == MONTHLY_LIMIT
    with pytest.raises(ValueError):  # a model without a price can't be counted
        ChatClient("https://api.openai.com/v1", "key", ["gpt-6-astra"], ledger=ledger, prices={})


def test_an_evaluation_run_prints_its_most_cost_first_and_stops_if_it_would_pass_the_limit(tmp_path, capsys):
    from types import SimpleNamespace

    from evaluation.judge import ChatClient
    from evaluation.run_ragas import Cache, check_openai_budget, openai_estimate_usd

    terra = {"gpt-6.1-terra": (1.0, 5.0)}
    # 100 questions: up to 3 answer calls of 0.65 cents and 2 verdict calls of 1.35 cents each.
    assert openai_estimate_usd((1.0, 5.0), 100, (1.0, 5.0), 100) == pytest.approx(1.95 + 2.70)

    ledger = SpendLedger(50.0, 5.0, MemoryStore(), clock=_Clock())
    asyncio.run(ledger.charge("gpt-6.1-terra", (1.0, 5.0), (44_000_000, 0)))  # $44 of the $45 limit spent
    judge = ChatClient("https://api.openai.com/v1", "key", ["gpt-6.1-terra"], ledger=ledger, prices=terra)
    free = ChatClient("https://openrouter.ai/api/v1", "key", ["a/b:free"])
    items = [{"id": f"Q{n}", "question": "q", "answerable": True, "target": "wztc"} for n in range(100)]
    cache = Cache(tmp_path / "cache.jsonl")
    args = SimpleNamespace(stage="judge", start_anyway=False)
    with pytest.raises(SystemExit, match=r"passes the \$1.00 left"):
        asyncio.run(check_openai_budget(ledger, free, "cfg", [(judge, "judge-cfg")], items, cache, args))
    assert "costs at most $2.70" in capsys.readouterr().out
    args.start_anyway = True
    assert asyncio.run(check_openai_budget(ledger, free, "cfg", [(judge, "judge-cfg")], items, cache, args)) \
        == pytest.approx(2.70)
    # Nothing on OpenAI: no estimate, no stop.
    assert asyncio.run(check_openai_budget(ledger, free, "cfg", [(free, "free-cfg")], items, cache, args)) == 0
