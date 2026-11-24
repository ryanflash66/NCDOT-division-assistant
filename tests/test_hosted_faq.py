"""Tests for the checked-answer store (hosted/divrag/faq.py, DAR-673) and its use in /api/ask; no network."""

import asyncio
import dataclasses
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hosted"))

import index as hosted  # noqa: E402
from divrag import faq  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import IndexFile  # noqa: E402
from divrag.spend import RedisStore, StoreError  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
TMP = "TMP Design Manual (Combined, No Links).pdf"
UTILITIES_DOCS = [d.file for d in BY_ID["utilities"].documents]
QUESTION = "Who pays for relocating a utility line on a state highway project?"


def _doc(file):
    return next(d for d in BY_ID["utilities"].documents + BY_ID["wztc"].documents if d.file == file)


def _source(n=1, file=UAM, page=126, page_end=None, division="utilities"):
    doc = _doc(file)
    return {"n": n, "division": division, "title": doc.title, "page": page, "page_end": page_end,
            "section": "8.2 Reimbursement", "url": f"{doc.url}#page={page}", "excerpt": "...",
            "printed_page": None, "printed_page_end": None, "image": None}


def _index(texts=None, extra_documents=()):
    """A small index: UAM pages 125-127 and one page of every other utilities document (plus `extra_documents`)."""
    texts = texts or {}
    chunks = [{"text": texts.get(p, f"UAM page {p} text"), "source": UAM, "page": p, "section": "8",
               "division": "utilities"} for p in (125, 126, 127)]
    for file in [d for d in UTILITIES_DOCS if d != UAM] + list(extra_documents):
        chunks.append({"text": f"{file} p.1", "source": file, "page": 1, "section": "", "division": "utilities"})
    chunks.append({"text": "TMP page 10", "source": TMP, "page": 10, "section": "", "division": "wztc"})
    return IndexFile("BAAI/bge-small-en-v1.5", chunks, np.zeros((len(chunks), 4), dtype=np.float16))


def _entry(question=QUESTION, answer="The utility pays unless it holds prior rights [1].", sources=None, **kw):
    fields = dict(id="utilities-relocation", division="utilities", question=question, answer=answer,
                  sources=sources if sources is not None else [_source()], checked_by="Ryan",
                  checked_on="2026-11-20", asked={"times": 6, "askers": 4, "days": 30}, added_on="2026-11-20")
    fields.update(kw)
    return faq.Entry(**fields)


def _stamped(index=None, **kw):
    return faq.PageText(index or _index()).stamp(_entry(**kw))


def _embed_table(table):
    """A fake embedder: each text's vector from `table` (unit vectors), so similarities are chosen by the test."""
    def embed(texts):
        return np.array([table[t] for t in texts], dtype=np.float32)
    return embed


def _unit(*values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


# --- the word rules ----------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    ("Is a 55 mph taper long enough?", "Is a 55 miles per hour taper long enough?"),
    ("Is positive protection needed for a 2 ft drop-off?", "When must positive protection be used for a drop-off of 2 feet?"),
    ("What is the minimum cover?", "What is the shortest cover allowed?"),
    ("Do I need a permit in the right of way?", "Is a permit needed within the right-of-way?"),
    ("How much cover is needed, at least?", "What is the minimum cover?"),
])
def test_question_keys_match_for_rewordings(a, b):
    assert faq.question_key(a) == faq.question_key(b)


@pytest.mark.parametrize("a, b", [
    ("What is the taper for a 55 mph road?", "What is the taper for a 45 mph road?"),  # another number
    ("Drop-off of 2 feet?", "Drop-off of 2 inches?"),  # another unit
    ("Buffer for 60 mph?", "Buffer for 60 km/h?"),
    ("Install a pole in the right of way?", "Install a pole outside the right of way?"),  # opposite
    ("Reimbursable with prior rights?", "Reimbursable without prior rights?"),  # negation
    ("The TMP for a significant project?", "The TMP for a non-significant project?"),
    ("The minimum mounting height?", "The maximum mounting height?"),
    ("When is a protected left-turn phase warranted?", "When is a protected right-turn phase warranted?"),
    ("Spacing between driveways?", "Spacing between driveways in meters?"),
])
def test_question_keys_differ_for_answer_changing_words(a, b):
    assert faq.question_key(a) != faq.question_key(b)


def test_no_more_than_is_a_maximum_not_a_negation():
    assert faq.contrast_classes("no more than 6 inches") == frozenset({"max"})
    assert faq.contrast_classes("in the right of way") == frozenset()  # "right" of way is no side


def test_best_match_needs_the_threshold_the_rules_and_picks_the_closest():
    q = "How deep must a water line be buried under a paved road?"
    near, far = _entry(question="How deep does a water line have to be buried under a paved road?", id="near"), \
        _entry(question="What depth of cover does a water line need?", id="far")
    vector = _unit(1, 0)
    candidates = [(near, near.question, _unit(1, 0.2)), (far, far.question, _unit(1, 0.6))]
    match = faq.best_match(q, vector, candidates, 0.95)
    assert match.entry.id == "near" and match.similarity == pytest.approx(0.98, abs=0.01)
    assert faq.best_match(q, vector, candidates, 0.99) is None
    # Same similarity but another number: never served.
    assert faq.best_match("Is 36 inches deep enough for a water line under a paved road?", vector, candidates, 0.5) is None


def test_best_match_serves_the_same_text_without_an_embedder_and_matches_aliases():
    entry = _entry(aliases=["Who covers utility relocation costs on a state highway project?"])
    assert faq.best_match("who pays for relocating a utility line on a state highway project", None,
                          [(entry, p, None) for p in entry.phrasings], 0.95).similarity == 1.0
    alias = entry.aliases[0]
    candidates = [(entry, entry.question, _unit(0, 1)), (entry, alias, _unit(1, 0))]
    assert faq.best_match("Who covers utility relocation costs on state highway projects?", _unit(1, 0.05),
                          candidates, 0.95).entry is entry


# --- entries and fingerprints -------------------------------------------------

def test_stamp_takes_every_cited_page_and_the_division_documents():
    entry = _stamped(sources=[_source(page=125, page_end=126), _source(n=2, page=127)])
    assert [(p["file"], p["page"]) for p in entry.pages] == [(UAM, 125), (UAM, 126), (UAM, 127)]
    assert all(len(p["fingerprint"]) == 20 for p in entry.pages)
    assert entry.documents == sorted(UTILITIES_DOCS)


def test_a_changed_or_removed_page_is_stale_and_other_pages_are_not():
    entry = _stamped()
    assert faq.PageText(_index()).stale_pages(entry) == []
    assert faq.PageText(_index({125: "edited, but not cited"})).stale_pages(entry) == []
    assert faq.PageText(_index({126: "UAM page 126 text, amended"})).stale_pages(entry) == [f"{UAM} p.126 (changed)"]
    gone = _index()
    gone.chunks = [c for c in gone.chunks if c.get("page") != 126]
    assert faq.PageText(gone).stale_pages(entry) == [f"{UAM} p.126 (removed)"]


def test_entry_round_trips_through_json_and_ignores_unknown_fields():
    entry = _stamped()
    data = json.loads(entry.to_json())
    data["added_later"] = True
    assert faq.Entry.from_json(json.dumps(data)) == entry


def test_validate_entry_enforces_the_criteria():
    assert faq.validate_entry(_entry()) == []
    problems = " ".join(faq.validate_entry(_entry(asked={"times": 4, "askers": 3, "days": 30})))
    assert "at least 5 times" in problems
    assert faq.validate_entry(_entry(asked={"times": 9, "askers": 2, "days": 30}))
    assert faq.validate_entry(_entry(asked={"times": 9, "askers": 3, "days": 45}))
    assert "checked_by" in " ".join(faq.validate_entry(_entry(checked_by=" ")))
    assert "date" in " ".join(faq.validate_entry(_entry(checked_on="Nov 20")))
    assert "depends" in " ".join(faq.validate_entry(_entry(answer="It depends on prior rights [1].")))
    assert "cites no source" in " ".join(faq.validate_entry(_entry(sources=[])))
    assert "division" in " ".join(faq.validate_entry(_entry(sources=[_source(file=TMP, page=10, division="wztc")])))


# --- the store ---------------------------------------------------------------

def test_memory_store_puts_pulls_queues_and_removes():
    async def run():
        store = faq.FaqStore(namespace="test")
        entry = _stamped()
        await store.put(entry)
        assert [e.id for e in await store.entries("utilities")] == [entry.id]
        assert await store.entries("wztc") == []
        await store.pull(entry, "cited page changed", today="2026-11-23")
        assert await store.entries("utilities") == []
        (queued,) = await store.queue()
        assert queued["reason"] == "cited page changed" and queued["entry"]["id"] == entry.id
        assert queued["pulled_on"] == "2026-11-23"
        assert await store.remove(entry.id) == 1 and await store.queue() == []
    asyncio.run(run())


def test_redis_store_keys_are_namespaced_per_deployment():
    sent = []
    table = {}

    def upstash(request):
        commands = json.loads(request.content)
        sent.extend(commands)
        results = []
        for op, key, *args in commands:
            if op == "HSET":
                table.setdefault(key, {})[args[0]] = args[1]
                results.append({"result": 1})
            elif op == "HGETALL":
                results.append({"result": [x for pair in table.get(key, {}).items() for x in pair]})
            else:
                results.append({"result": int(table.get(key, {}).pop(args[0], None) is not None)})
        return httpx.Response(200, json=results)

    redis = RedisStore("https://kv.example.upstash.io", "t", transport=httpx.MockTransport(upstash))

    async def run():
        production = faq.FaqStore(redis, "production")
        await production.put(_stamped())
        assert [e.id for e in await production.entries("utilities")] == ["utilities-relocation"]
        assert await faq.FaqStore(redis, "preview").entries("utilities") == []
    asyncio.run(run())
    assert sent[0][:2] == ["HSET", "faq:production:utilities"]


def test_namespace_comes_from_the_setting_then_vercel_env():
    assert faq.namespace_from_env({}) == "local"
    assert faq.namespace_from_env({"VERCEL_ENV": "production"}) == "production"
    assert faq.namespace_from_env({"VERCEL_ENV": "preview", "FAQ_NAMESPACE": "Test-DAR673"}) == "test-dar673"
    assert faq.store_from_env({"KV_REST_API_URL": "https://kv", "KV_REST_API_TOKEN": "t"}).shared
    assert not faq.store_from_env({}).shared


# --- serving -------------------------------------------------------------------

def _service(index=None, entries=(), threshold=0.95):
    store = faq.FaqStore(namespace="test")
    for entry in entries:
        asyncio.run(store.put(entry))
    return faq.FaqService(store, faq.PageText(index or _index()), threshold)


REWORDED = "When a state highway project requires relocating a utility line, who pays for it?"
EMBED = _embed_table({QUESTION: _unit(1, 0), REWORDED: _unit(1, 0.2), "Who pays for a detour?": _unit(0, 1)})


def test_lookup_serves_a_rewording_and_not_an_unrelated_question():
    service = _service(entries=[_stamped()])
    match = asyncio.run(service.lookup(REWORDED, "utilities", None, EMBED))
    assert match.entry.id == "utilities-relocation" and match.similarity > 0.95
    assert asyncio.run(service.lookup("Who pays for a detour?", "utilities", None, EMBED)) is None
    assert asyncio.run(service.lookup(REWORDED, "wztc", None, EMBED)) is None  # another division's store


def test_lookup_serves_only_entries_citing_ticked_documents():
    service = _service(entries=[_stamped()])
    assert asyncio.run(service.lookup(QUESTION, "utilities", [UAM], EMBED)) is not None
    other = [d for d in UTILITIES_DOCS if d != UAM][:1]
    assert asyncio.run(service.lookup(QUESTION, "utilities", other, EMBED)) is None


def test_lookup_pulls_an_entry_whose_cited_page_changed_in_the_loaded_index():
    entry = _stamped()
    service = _service(index=_index({126: "UAM page 126 text, amended"}), entries=[entry])

    async def run():
        assert await service.lookup(QUESTION, "utilities", None, EMBED) is None
        await asyncio.gather(*service._pending)
        assert await service.store.entries("utilities") == []
        (queued,) = await service.store.queue()
        assert "p.126 (changed)" in queued["reason"]
    asyncio.run(run())


def test_lookup_holds_an_entry_back_when_a_document_was_added_until_it_is_re_run():
    service = _service(index=_index(extra_documents=["new-utility-guide.pdf"]), entries=[_stamped()])
    assert asyncio.run(service.lookup(QUESTION, "utilities", None, EMBED)) is None
    assert len(asyncio.run(service.store.entries("utilities"))) == 1  # waiting for the re-run, not pulled


def test_lookup_answers_in_full_when_the_store_is_down():
    class Down(faq.FaqStore):
        async def entries(self, division):
            raise StoreError("timeout")
    service = faq.FaqService(Down(), faq.PageText(_index()))
    assert asyncio.run(service.lookup(QUESTION, "utilities", None, EMBED)) is None


# --- keeping entries current -----------------------------------------------

def _reply(answer="The utility pays unless it holds prior rights [1].", sources=None, refused=False):
    return {"answer": answer, "refused": refused, "uncited": False, "sources": sources or [_source()]}


def test_check_pulls_entries_whose_cited_page_changed():
    async def run():
        store = faq.FaqStore(namespace="test")
        await store.put(_stamped())
        report = await faq.check_entries(store, faq.PageText(_index({126: "rewritten"})), today="2026-11-23")
        assert [i for i, _ in report.pulled] == ["utilities-relocation"]
        assert await store.entries("utilities") == []
    asyncio.run(run())


@pytest.mark.parametrize("reply, kept", [
    (_reply(answer="Relocation is paid by the utility, except with prior rights [1]."), True),  # same page, no numbers
    (_reply(sources=[_source(page=127)]), False),  # another page cited
    (_reply(answer="NCDOT pays 50 % [1]."), False),  # a number appeared
    (_reply(refused=True, sources=[]), False),
])
def test_check_re_runs_a_division_whose_documents_changed(reply, kept):
    asked = []

    async def rerun(entry):
        asked.append(entry.question)
        return reply

    async def run():
        store = faq.FaqStore(namespace="test")
        await store.put(_stamped())
        pages = faq.PageText(_index(extra_documents=["new-utility-guide.pdf"]))
        report = await faq.check_entries(store, pages, rerun, today="2026-11-23")
        assert asked == [QUESTION]
        if kept:
            (entry,) = await store.entries("utilities")
            assert report.rechecked == [entry.id] and entry.rechecked_on == "2026-11-23"
            assert "new-utility-guide.pdf" in entry.documents and entry.checked_on == "2026-11-20"
        else:
            assert await store.entries("utilities") == []
            (queued,) = await store.queue()
            assert "added ['new-utility-guide.pdf']" in queued["reason"] and queued["new_answer"] == reply
    asyncio.run(run())


def test_check_without_a_site_lists_the_entries_to_re_run():
    async def run():
        store = faq.FaqStore(namespace="test")
        await store.put(_stamped())
        report = await faq.check_entries(store, faq.PageText(_index(extra_documents=["new.pdf"])))
        assert report.needs_rerun == ["utilities-relocation"] and len(await store.entries("utilities")) == 1
        assert (await faq.check_entries(store, faq.PageText(_index()))).kept == ["utilities-relocation"]
    asyncio.run(run())


# --- /api/ask ----------------------------------------------------------------

class _Embedder:
    def __init__(self, table):
        self.passages = _embed_table(table)


@pytest.fixture
def api(monkeypatch):
    from tests.test_hosted_api import SECRET, _FakeLLM, _FakeRetriever  # the API tests' fakes

    retriever = _FakeRetriever()
    retriever.embedder = _Embedder({QUESTION: _unit(1, 0), REWORDED: _unit(1, 0.2),
                                    "When is a lane closure required?": _unit(0, 1)})
    llm = _FakeLLM("Within 5 feet of the travel lane on an undivided facility [1].")
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, openrouter_api_key=SECRET))
    monkeypatch.setattr(hosted.runtime, "settings", dataclasses.replace(hosted.runtime.settings, rerank=False))
    monkeypatch.setattr(hosted.runtime, "retriever", lambda: retriever)
    monkeypatch.setattr(type(hosted.runtime), "loaded", property(lambda self: True))
    monkeypatch.setattr(hosted, "_make_llm", lambda: llm)
    monkeypatch.setattr(hosted, "limiter", hosted._RateLimiter(100))
    monkeypatch.setattr(hosted, "faq", _service(entries=[_stamped()]))
    return TestClient(hosted.app), retriever, llm


def _post(client, question, **body):
    return client.post("/api/ask", json={"question": question, "asker": "wztc", "target": "utilities", **body})


def test_ask_serves_a_checked_answer_without_searching_or_calling_the_model(api):
    client, retriever, llm = api
    data = _post(client, REWORDED).json()
    assert data["answer"] == "The utility pays unless it holds prior rights [1]."
    assert data["checked_answer"]["checked_on"] == "2026-11-20" and data["checked_answer"]["similarity"] > 0.95
    assert data["sources"][0]["page"] == 126 and data["refused"] is False and data["searched"] is None
    assert data["steps"][0]["id"] == "faq" and set(data["timing_ms"]) == {"faq", "total"}
    assert data["target"]["id"] == "utilities" and data["asker"]["id"] == "wztc"
    assert retriever.questions == [] and llm.calls == 0


def test_ask_answers_in_full_for_a_follow_up_a_bypass_or_another_question(api):
    client, retriever, llm = api
    history = [{"question": "When is a lane closure required?", "answer": "Within 5 feet [1]."}]
    for body in ({"question": QUESTION, "history": history}, {"question": QUESTION, "faq": False},
                 {"question": "When is a lane closure required?"}):
        data = _post(client, **body).json()
        assert data["checked_answer"] is None and data["searched"]["passages"] >= 0
        assert "faq" in data["timing_ms"]
    assert llm.calls == 3


def test_stream_sends_a_checked_answer_as_one_done_event(api):
    client, _, llm = api
    response = client.post("/api/ask/stream", json={"question": REWORDED, "asker": "wztc", "target": "utilities"})
    events = [line.split(": ", 1)[1] for line in response.text.splitlines() if line.startswith("event: ")]
    assert events == ["done"] and llm.calls == 0
    done = json.loads(response.text.split("data: ", 1)[1].split("\n", 1)[0])
    assert done["checked_answer"]["id"] == "utilities-relocation"


# --- the test pairs, with the real model when it is on this machine --------------

def _model_available():
    models = Path(hosted.model_cache_dir())
    return models.is_dir() and any(models.glob("models--Qdrant--bge-small*"))


@pytest.mark.skipif(not _model_available(), reason="the bge-small model files aren't on this machine")
def test_the_faq_pairs_never_serve_a_similar_but_different_question():
    sys.path.insert(0, str(ROOT))
    from evaluation.faq.run import HERE, evaluate
    from divrag.embedder import Embedder

    embedder = Embedder(cache_dir=hosted.model_cache_dir())
    tuning = evaluate(json.loads((HERE / "pairs.json").read_text(encoding="utf-8")), embedder, faq.DEFAULT_THRESHOLD)
    held_out = evaluate(json.loads((HERE / "pairs_holdout.json").read_text(encoding="utf-8")), embedder,
                        faq.DEFAULT_THRESHOLD)
    assert tuning["different_served"] == 0 and held_out["different_served"] == 0
    assert tuning["wrong_entry"] == 0 and held_out["wrong_entry"] == 0
    # What evaluation/faq/RESULTS.md reports; a change to the rules or threshold has to update it.
    assert (tuning["rewordings_served"], held_out["rewordings_served"]) == (24, 8)


# --- scripts/faq.py ------------------------------------------------------------

def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("faq_script", ROOT / "hosted" / "scripts" / "faq.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_asks_the_site_with_the_store_skipped(monkeypatch):
    script = _script()
    seen = []

    def site(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_reply())

    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "bypass")
    reply = asyncio.run(script.ask_site("https://preview.example", QUESTION, "utilities",
                                        transport=httpx.MockTransport(site)))
    assert seen == [{"question": QUESTION, "asker": "utilities", "target": "utilities", "faq": False}]
    assert reply["sources"][0]["page"] == 126


def test_script_add_refuses_an_unchecked_entry_and_stores_a_checked_one(tmp_path, monkeypatch, capsys):
    script = _script()
    store = faq.FaqStore(namespace="production")
    monkeypatch.setattr(script, "_store", lambda namespace: store)
    index_dir = tmp_path / "index"
    _index().save(index_dir)
    draft = json.loads(_entry().to_json())
    draft["checked_by"] = ""
    path = tmp_path / "entry.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    assert script.main(["--index", str(index_dir), "add", str(path)]) == 1
    assert "checked_by" in capsys.readouterr().err
    draft["checked_by"] = "Ryan"
    path.write_text(json.dumps(draft), encoding="utf-8")
    assert script.main(["--index", str(index_dir), "add", str(path)]) == 0
    (stored,) = asyncio.run(store.entries("utilities"))
    assert [p["page"] for p in stored.pages] == [126] and stored.documents == sorted(UTILITIES_DOCS)
    assert script.main(["--index", str(index_dir), "add", str(path)]) == 1  # already stored
