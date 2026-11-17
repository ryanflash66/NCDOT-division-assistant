"""Tests for the page images sent to the model with their passages (DAR-733, PAGE_IMAGES_TO_MODEL)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import page_images as pi  # noqa: E402
from divrag.answer import NOT_FOUND, Answerer  # noqa: E402
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID, document_for  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import API_URL, OPENAI_URL, Completion, client_from_settings  # noqa: E402
from divrag.pages_static import page_image_path, slug  # noqa: E402
from divrag.spend import IMAGE_TOKENS, estimated_usage  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
APPENDIX = "010604.pdf"
JPEG = b"\xff\xd8\xff\xe0" + b"page" * 20
OPENAI = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-openai", "OPENROUTER_API_KEY": "sk-or"}
INDEX_DIR = Path(__file__).resolve().parent.parent / "hosted" / "index"


def _chunk(page, text="plain prose", source=UAM, division="utilities", **extra):
    return {"text": text, "source": source, "page": page, "section": None, "division": division, **extra}


def _hit(page, score=1.0, **extra):
    return Hit(score, _chunk(page, **extra))


def _listing(*refs):
    """A render manifest listing these (source, page) pairs of the utilities division."""
    listed = {}
    for source, page in refs:
        listed.setdefault(f"utilities/{slug(source)}", set()).add(page)
    return lambda: listed


def _images(tmp_path, *refs, **options):
    """PageImages reading these utilities pages from a pages folder under tmp_path."""
    for source, page in refs:
        file = tmp_path / page_image_path("utilities", source, page)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(JPEG)
    return pi.PageImages(options.pop("no_text", {}), pages_dir=tmp_path, listed=_listing(*refs), **options)


# Which pages qualify

def test_a_page_qualifies_for_a_scan_a_turn_a_picture_a_figure_a_table_or_a_caption():
    no_text = {("utilities", APPENDIX): {278}}
    assert pi.reasons(_chunk(278, source=APPENDIX), no_text) == ["scan"]
    assert pi.reasons(_chunk(13, flags=["rotated"]), {}) == ["rotated"]
    assert pi.reasons(_chunk(13, flags=["ocr_low_conf"]), {}) == ["scan"]
    assert pi.reasons(_chunk(3, "<!-- Start of picture text --> 3:1 <!-- End of picture text -->"), {}) == ["picture"]
    assert pi.reasons(_chunk(3, kind="figure"), {}) == ["figure"]
    assert pi.reasons(_chunk(37, kind="table"), {}) == ["table"]
    assert pi.reasons(_chunk(37, "| a | b |\n|---|---|\n| 1 | 2 |"), {}) == ["table"]
    assert pi.reasons(_chunk(5, context="[UAM · p.5 · Figure 3-1]"), {}) == ["caption"]
    # Plain prose on a plain page goes as text alone, and so does a table-quality flag that isn't about the page.
    assert pi.reasons(_chunk(5), no_text) == []
    assert pi.reasons(_chunk(5, flags=["no_caption"]), {}) == []


def test_the_pages_are_ordered_scans_first_then_by_score_one_per_page():
    hits = [_hit(10, score=3.0, kind="table"),
            _hit(11, score=1.0, flags=["rotated"]),
            _hit(10, score=2.0, context="[captions]"),  # page 10 again: kept once, for its better reason
            _hit(12, score=0.5),
            _hit(13, score=5.0, kind="table")]

    refs = pi.wanted_pages(hits, {})

    assert [(r.page, r.reason, r.n) for r in refs] == [(11, "rotated", 2), (13, "table", 5), (10, "table", 1)]


def test_each_part_of_a_merged_passage_and_each_page_of_a_joined_table_counts():
    parts = [_chunk(20), _chunk(21, kind="table", page_end=22)]
    merged = dict(parts[0], text="a\n\nb", page_end=22, parts=parts)

    refs = pi.wanted_pages([Hit(1.0, merged)], {}, start=6)

    assert [(r.n, r.page) for r in refs] == [(6, 21), (6, 22)]
    label = refs[0].label()
    assert label.startswith("Page image for passage [6]: ") and label.endswith(", PDF page 21")
    assert document_for(UAM).title in label


def test_only_rendered_pages_are_picked_and_at_most_max_images(tmp_path):
    images = pi.PageImages({}, pages_dir=tmp_path, max_images=2, listed=_listing((UAM, 1), (UAM, 2), (UAM, 3)))
    hits = [_hit(p, score=10 - p, kind="table") for p in (1, 2, 3, 4)]

    assert [r.page for r in images.pick(hits)] == [1, 2]
    assert [r.page for r in pi.PageImages({}, pages_dir=tmp_path, listed=_listing((UAM, 4))).pick(hits)] == [4]


def test_the_no_text_list_is_read_from_the_index_folder(tmp_path):
    assert pi.load_no_text_pages(tmp_path) == {}
    (tmp_path / pi.NO_TEXT_FILE).write_text(json.dumps({"utilities": {APPENDIX: [278, 279]}}), encoding="utf-8")
    assert pi.load_no_text_pages(tmp_path) == {("utilities", APPENDIX): {278, 279}}
    (tmp_path / pi.NO_TEXT_FILE).write_text("[not a mapping", encoding="utf-8")
    assert pi.load_no_text_pages(tmp_path) == {}


def test_the_committed_index_lists_its_pages_without_a_text_layer():
    no_text = pi.load_no_text_pages(INDEX_DIR)
    # The scanned UAM appendix (010604.pdf) is most of them; utilities-h056's permit page is one.
    assert 278 in no_text[("utilities", APPENDIX)]
    assert sum(len(p) for p in no_text.values()) >= 100


def test_the_five_ocr_pages_behind_dar_732s_wrong_values_all_qualify():
    """DAR-732: 5 of the 6 wrong values came from these gold pages. Each would go to the model as an image."""
    chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))["chunks"]
    no_text = pi.load_no_text_pages(INDEX_DIR)
    gold = {"tmsd-h009": ("TODS Manual - September 2024.pdf", 39),
            "tmsd-h019": ("Policy on Access Manual.pdf", 88),
            "tmsd-h049": ("03. Guardrail, Barriers and Attenuators.pdf", 3),
            "tmsd-h052": ("09. At Grade Intersections.pdf", 13),
            "utilities-h056": (APPENDIX, 278)}
    for item, (source, page) in gold.items():
        on_page = [c for c in chunks if c["source"] == source and c["page"] == page]
        assert on_page, item
        assert all(pi.reasons(c, no_text) for c in on_page), item


# Loading the images

def test_attach_puts_the_pages_on_the_message_as_jpeg_data_urls(tmp_path):
    images = _images(tmp_path, (UAM, 37))
    message = {"role": "user", "content": "Passages ..."}

    out = asyncio.run(images.attach(message, [_hit(36), _hit(37, kind="table")]))

    (image,) = out["images"]
    assert image["url"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    assert image["detail"] == "auto"
    assert image["label"].startswith("Page image for passage [2]: ") and image["label"].endswith("PDF page 37")
    assert out["content"] == "Passages ..." and "images" not in message  # the original is left alone


def test_attach_leaves_the_message_alone_when_no_page_qualifies_or_loads(tmp_path):
    message = {"role": "user", "content": "x"}
    images = _images(tmp_path, (UAM, 37))
    assert asyncio.run(images.attach(message, [_hit(37)])) is message  # plain prose
    missing = pi.PageImages({}, pages_dir=tmp_path, listed=_listing((UAM, 40)))  # listed, but not on disk, no URL
    assert asyncio.run(missing.attach(message, [_hit(40, kind="table")])) is message
    (tmp_path / page_image_path("utilities", UAM, 41)).write_bytes(b"<html>login</html>")
    not_jpeg = pi.PageImages({}, pages_dir=tmp_path, listed=_listing((UAM, 41)))
    assert asyncio.run(not_jpeg.attach(message, [_hit(41, kind="table")])) is message


def test_a_page_not_on_disk_is_fetched_from_the_deployment_once_with_the_bypass_header(tmp_path):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("x-vercel-protection-bypass")))
        return httpx.Response(200, content=JPEG)

    images = pi.PageImages({}, base_url="https://preview.vercel.app/", headers={"x-vercel-protection-bypass": "s"},
                           pages_dir=tmp_path, transport=httpx.MockTransport(handler), listed=_listing((UAM, 37)))
    hits = [_hit(37, kind="table")]

    first = asyncio.run(images.attach({"role": "user", "content": "x"}, hits))
    again = asyncio.run(images.attach({"role": "user", "content": "x"}, hits))

    expected = f"https://preview.vercel.app/pages/{page_image_path('utilities', UAM, 37)}"
    assert seen == [(str(httpx.URL(expected)), "s")]  # the second question used this instance's copy
    assert first["images"] == again["images"] and len(first["images"]) == 1


def test_a_page_the_deployment_refuses_is_left_out(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="<html>Log in to Vercel</html>"))
    images = pi.PageImages({}, base_url="https://preview.vercel.app", pages_dir=tmp_path, transport=transport,
                           listed=_listing((UAM, 37)))
    message = {"role": "user", "content": "x"}
    assert asyncio.run(images.attach(message, [_hit(37, kind="table")])) is message


def test_slow_pages_are_given_up_on_rather_than_held_against_the_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "FETCH_TIMEOUT_SECONDS", 0.05)

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, content=JPEG)

    images = pi.PageImages({}, base_url="https://x.vercel.app", pages_dir=tmp_path,
                           transport=httpx.MockTransport(slow), listed=_listing((UAM, 37)))
    message = {"role": "user", "content": "x"}
    assert asyncio.run(images.attach(message, [_hit(37, kind="table")])) is message


# What each service is sent

def _with_images():
    return [{"role": "system", "content": "rules"},
            {"role": "user", "content": "passages", "images": [
                {"label": "Page image for passage [1]: UAM, PDF page 37", "url": "data:image/jpeg;base64,AAA",
                 "detail": "high"}]}]


def test_openai_gets_the_images_as_content_parts_after_the_text():
    system, user = pi.openai_messages(_with_images())

    assert system == {"role": "system", "content": "rules"}
    assert user == {"role": "user", "content": [
        {"type": "text", "text": "passages"},
        {"type": "text", "text": pi.INTRO},
        {"type": "text", "text": "Page image for passage [1]: UAM, PDF page 37"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA", "detail": "high"}},
    ]}


def test_messages_without_images_are_sent_exactly_as_before():
    plain = [{"role": "system", "content": "rules"}, {"role": "user", "content": "passages"}]
    assert pi.openai_messages(plain) == plain
    assert pi.text_messages(plain) == plain
    assert pi.text_messages(_with_images())[1] == {"role": "user", "content": "passages"}


def _router(seen, openai_status=200):
    def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), body))
        if str(request.url) == OPENAI_URL and openai_status != 200:
            return httpx.Response(openai_status, text="down")
        return httpx.Response(200, json={"model": body.get("model") or body["models"][0],
                                         "choices": [{"finish_reason": "stop", "message": {"content": "Yes [1]."}}]})
    return httpx.MockTransport(handler)


def test_openai_reads_the_images_and_the_free_fallback_gets_the_text_only_prompt():
    seen = []
    client = client_from_settings(load_settings(OPENAI), transport=_router(seen, openai_status=500))
    assert client.reads_images

    completion = asyncio.run(client.complete(_with_images()))

    (openai_url, openai_body), (free_url, free_body) = seen
    assert openai_url == OPENAI_URL and openai_body["messages"][1]["content"][3]["type"] == "image_url"
    # OpenAI failed: the free model answered from the same passages, without images or the private key.
    assert free_url == API_URL and completion.model.endswith(":free")
    assert free_body["messages"] == [{"role": "system", "content": "rules"}, {"role": "user", "content": "passages"}]


def test_the_free_models_alone_read_no_images():
    client = client_from_settings(load_settings({"OPENROUTER_API_KEY": "sk-or"}))
    assert not client.reads_images


def test_a_guessed_call_cost_counts_each_image():
    messages = _with_images()
    assert estimated_usage(messages, "")[0] == estimated_usage(pi.text_messages(messages), "")[0] + IMAGE_TOKENS


# The answer flow

class _Retriever:
    reranker = object()
    candidates = 40

    def __init__(self, more=()):
        self.more = list(more)

    def as_passages(self, hits):
        return list(hits)


class _LLM:
    def __init__(self, replies, reads_images=True):
        self.replies = list(replies)
        self.reads_images = reads_images
        self.calls = []

    def retry_models(self, used):
        return [used]

    async def complete(self, messages, models=None):
        self.calls.append(messages)
        return Completion(self.replies[min(len(self.calls), len(self.replies)) - 1], "gpt-6.1-terra")


def _answerer(tmp_path, llm, *pages):
    return Answerer(_Retriever(), llm, page_images=_images(tmp_path, *[(UAM, p) for p in pages]))


def test_the_first_call_carries_the_images_of_its_passages(tmp_path):
    llm = _LLM(["The table on that page covers it [2]."])
    hits = [_hit(36), _hit(37, kind="table")]

    result = asyncio.run(_answerer(tmp_path, llm, 37).answer("q", BY_ID["utilities"], BY_ID["utilities"], hits))

    assert not result.refused and result.sources[0].page == 37
    (call,) = llm.calls
    assert [m["role"] for m in call] == ["system", "user"]
    assert [i["label"].split(":")[0] for i in call[1]["images"]] == ["Page image for passage [2]"]
    assert "images" not in call[0]


def test_no_image_is_loaded_for_a_client_that_cannot_read_them(tmp_path):
    llm = _LLM(["Yes [1]."], reads_images=False)
    asyncio.run(_answerer(tmp_path, llm, 37).answer("q", BY_ID["utilities"], BY_ID["utilities"],
                                                     [_hit(37, kind="table")]))
    assert "images" not in llm.calls[0][1]


def test_the_second_look_after_a_refusal_carries_its_own_passages_images(tmp_path):
    from divrag.answer import Passages

    llm = _LLM([NOT_FOUND, "Found it [2]."])
    hits = Passages([_hit(36, score=2.0)], more=[_hit(90, score=1.0, flags=["rotated"])])

    result = asyncio.run(_answerer(tmp_path, llm, 90).answer("q", BY_ID["utilities"], BY_ID["utilities"], hits))

    assert result.retried and not result.refused
    first, second = llm.calls
    assert "images" not in first[1]  # page 36 is plain prose
    assert second[-1]["role"] == "user" and second[-1]["images"][0]["label"].startswith("Page image for passage [2]")


# Settings

def test_page_images_are_off_by_default_and_validated():
    default = load_settings({})
    assert not default.page_images_to_model and default.page_images_max == pi.DEFAULT_MAX_IMAGES
    on = load_settings({"PAGE_IMAGES_TO_MODEL": "on", "PAGE_IMAGES_MAX": "2", "PAGE_IMAGES_DETAIL": "HIGH"})
    assert on.page_images_to_model and on.page_images_max == 2 and on.page_images_detail == "high"
    for bad in ({"PAGE_IMAGES_TO_MODEL": "yes please"}, {"PAGE_IMAGES_MAX": "0"}, {"PAGE_IMAGES_MAX": "11"},
                {"PAGE_IMAGES_DETAIL": "ultra"}, {"PAGE_IMAGES_BASE_URL": "ftp://example.com"},
                {"PAGE_IMAGES_BASE_URL": "http://example.com"}):
        with pytest.raises(ValueError):
            load_settings(bad)


def test_the_images_come_from_the_deployment_and_the_bypass_secret_goes_only_there():
    assert pi.base_url_from_env({}) is None  # locally: the rendered pages on disk only
    assert pi.base_url_from_env({"PAGE_IMAGES_BASE_URL": "https://x.example/"}) == "https://x.example"
    prod = {"VERCEL_URL": "app-abc123.vercel.app", "VERCEL_PROJECT_PRODUCTION_URL": "app.vercel.app"}
    # A deployment URL sits behind Vercel's protection; the production domain doesn't.
    assert pi.base_url_from_env(prod) == "https://app.vercel.app"
    assert pi.headers_from_env(prod, "https://app.vercel.app") == {}
    bypass = dict(prod, VERCEL_AUTOMATION_BYPASS_SECRET="s3cret")
    assert pi.base_url_from_env(bypass) == "https://app-abc123.vercel.app"
    assert pi.headers_from_env(bypass, "https://app-abc123.vercel.app") == {"x-vercel-protection-bypass": "s3cret"}
    assert pi.headers_from_env(bypass, "https://elsewhere.example") == {}


# The list beside the index (prototype)

def test_the_index_build_lists_the_pages_with_a_passage_but_no_text_layer(tmp_path):
    import pymupdf

    from prototype.build_report import write_no_text_pages

    folder = tmp_path / "documents" / "utilities"
    folder.mkdir(parents=True)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A page with a real text layer, read without OCR.")
        pdf.new_page()  # a scan: an image only, its passage came from OCR
        pdf.new_page()  # blank, and no passage: not listed
        pdf.save(folder / APPENDIX)
    chunks = [_chunk(1, source=APPENDIX), _chunk(2, "OCR text", source=APPENDIX), _chunk(5, source="missing.pdf")]
    index = tmp_path / "index"
    index.mkdir()

    assert write_no_text_pages(index, chunks, tmp_path / "documents") == 1
    assert pi.load_no_text_pages(index) == {("utilities", APPENDIX): {2}}
