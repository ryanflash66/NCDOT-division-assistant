"""Tests for the indexing-time image readings of picture pages (prototype.read_pages, DAR-739)."""

import asyncio
import base64
import json

import httpx
import pytest

from prototype import read_pages as rp
from divrag.readings import load

PICTURE = "<!-- Start of picture text -->Bay taper 150'<!-- End of picture text -->"


def _chunk(page, text="prose", source="a.pdf", division="tmsd", **extra):
    return {"text": text, "source": source, "page": page, "division": division, **extra}


def test_flagged_pages_are_the_scans_turns_pictures_and_figures_with_their_text():
    chunks = [
        _chunk(1, "plain prose"),
        _chunk(2, "| a | b |\n|---|---|\n| 1 | 2 |", kind="table"),  # a text-layer table: its text is the print
        _chunk(3, "sideways 200' 575'", flags=["rotated"]),
        _chunk(3, "more of page 3"),
        _chunk(4, PICTURE),
        _chunk(4, "Figure 4 labels", kind="figure"),
        _chunk(5, "scanned text"),
        _chunk(6, "joined table rows", page_end=7, flags=["rotated"]),
    ]

    pages = rp.flagged_pages(chunks, {("tmsd", "a.pdf"): {5}})

    assert [(p.page, p.reasons) for p in pages] == [
        (3, ("rotated",)), (4, ("picture", "figure")), (5, ("scan",)), (6, ("rotated",)), (7, ("rotated",))]
    by_page = {p.page: p for p in pages}
    assert by_page[3].ocr_text == "sideways 200' 575'\n\nmore of page 3"
    assert "Figure 4 labels" not in by_page[4].ocr_text  # a figure chunk repeats its page's labels
    assert by_page[7].ocr_text == "joined table rows"
    assert by_page[3].key == "tmsd/a.pdf:3"


def test_the_estimate_scales_the_measured_image_tokens_by_area():
    small = rp.estimate_tokens((510, 660), 0)
    assert small["input_measured"] == pytest.approx(1300 + rp.PROMPT_TOKENS)
    assert small["input_patches"] == pytest.approx(16 * 21 * 1.2 + rp.PROMPT_TOKENS)
    assert small["output"] == 50
    assert rp.estimate_tokens((850, 1100), 4000)["output"] == pytest.approx(1300)
    assert rp.image_size(612, 792, 100) == (850, 1100)
    assert max(rp.image_size(1224, 1584, 200)) == rp.MAX_SIDE  # an 17 x 22 sheet is scaled down


def test_a_reply_of_no_text_is_kept_apart_from_a_reading():
    assert rp.flag("some text 5 ft", "") == ("no_image_text", [])
    assert rp.flag("", "") == ("image_only", [])
    assert rp.flag("", "Bay taper 150'")[0] == "image_only"
    assert rp.flag("max 1/2 in", "max 1 1/2 in")[0] == "disagree"


def test_the_budget_admits_a_call_only_while_its_worst_case_fits():
    budget = rp.Budget(max_usd=0.1, prices=(1.0, 5.0))
    admitted = 0
    while budget.admit():
        admitted += 1
    assert admitted == int(0.1 // budget.worst)
    budget.charge((1000, 500))  # a real call costs far less than its worst case
    assert budget.spent == pytest.approx(0.0035)
    assert budget.admit()
    # The worst case covers the largest image sent, at the measured rate.
    largest = rp.estimate_tokens((rp.MAX_SIDE, rp.MAX_SIDE), 0)["input_measured"]
    assert budget.worst >= (largest * 1.0 + rp.MAX_COMPLETION_TOKENS * 5.0) / 1e6


def _pages():
    return [rp.Page("utilities", "010604.pdf", 278, ("scan",), "will not exceed 1/2 inches"),
            rp.Page("utilities", "010604.pdf", 279, ("scan",), "depth 9 inches")]


def _fake_run(tmp_path, monkeypatch, replies):
    """read_all against a mock OpenAI: each page's image is its own bytes; returns the pages called and rendered."""
    seen, rendered = [], []

    def handler(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer sk-test"
        assert body["model"] == "gpt-6.1-terra" and body["reasoning_effort"] == "none"
        image = body["messages"][1]["content"][1]["image_url"]
        assert image["url"].startswith("data:image/jpeg;base64,") and image["detail"] == "high"
        page = int(body["messages"][1]["content"][0]["text"].rsplit(" ", 1)[1].rstrip("."))
        # The image sent is the one rendered for this page.
        assert base64.b64decode(image["url"].split(",", 1)[1]) == f"jpeg of page {page}".encode()
        seen.append(page)
        reply = replies[page]
        if reply is None:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 4000, "completion_tokens": 100}})

    def render(path, page, dpi):
        rendered.append((path.name, page, dpi))
        return f"jpeg of page {page}".encode()

    real_client = httpx.AsyncClient
    monkeypatch.setattr(rp.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(rp, "render", render)
    monkeypatch.setattr(rp, "pdf_path", lambda page, documents: tmp_path / page.source)
    (tmp_path / "010604.pdf").write_bytes(b"%PDF-1.7 fake")

    def run(pages):
        store = rp.ReadingsFile(tmp_path / "page_readings.json")
        todo = rp._todo(pages, store, tmp_path, force=False)
        counts = asyncio.run(rp.read_all(todo, store, {"model": "gpt-6.1-terra"}, tmp_path,
                                         "https://example.test/v1", "sk-test", "gpt-6.1-terra", 100,
                                         rp.Budget(1.0, (1.0, 5.0))))
        return todo, counts

    return run, seen, rendered


def test_a_run_reads_each_page_once_saves_as_it_goes_and_resumes(tmp_path, monkeypatch):
    replies = {278: "will not exceed 1 1/2 inches", 279: None}  # page 279's call fails: the run stops partway
    run, seen, rendered = _fake_run(tmp_path, monkeypatch, replies)

    _, counts = run(_pages())

    assert counts["read"] == 1 and counts["failed"] == 1 and sorted(seen) == [278, 279]
    assert sorted(rendered) == [("010604.pdf", 278, 100), ("010604.pdf", 279, 100)]
    # The page that finished is saved; the one that failed is not.
    saved = json.loads((tmp_path / "page_readings.json").read_text(encoding="utf-8"))
    row = saved["pages"]["utilities"]["010604.pdf"]["278"]
    assert row["agreement"] == "disagree" and row["usd"] == pytest.approx(0.0045)
    assert row["pdf_sha256"] == rp.pdf_sha256(tmp_path / "010604.pdf")
    assert "279" not in saved["pages"]["utilities"]["010604.pdf"]
    assert "sk-test" not in (tmp_path / "page_readings.json").read_text(encoding="utf-8")

    # Run again: only the page that failed is read.
    replies[279] = "NO_TEXT"
    todo, counts = run(_pages())
    assert [p.page for p in todo] == [279] and counts["read"] == 1 and sorted(seen) == [278, 279, 279]
    saved = json.loads((tmp_path / "page_readings.json").read_text(encoding="utf-8"))
    assert saved["pages"]["utilities"]["010604.pdf"]["279"]["agreement"] == "no_image_text"
    assert saved["totals"] == {"pages": 2, "agree": 0, "disagree": 1, "image_only": 0, "no_image_text": 1,
                               "usd": 0.009}
    # The app reads the same file: the disagreeing page is used, the one with no image text is not.
    readings = load(tmp_path)
    assert readings.get("utilities", "010604.pdf", 278).differs
    assert readings.get("utilities", "010604.pdf", 279) is None

    # A third run calls nothing.
    todo, counts = run(_pages())
    assert todo == [] and counts["read"] == 0 and len(seen) == 3

    # A new edition of the PDF under the same name is read again.
    (tmp_path / "010604.pdf").write_bytes(b"%PDF-1.7 new edition")
    rp.pdf_sha256.cache_clear()
    todo, _ = run(_pages())
    assert [p.page for p in todo] == [278, 279]


def test_a_page_that_will_not_render_fails_alone(tmp_path, monkeypatch):
    run, seen, _ = _fake_run(tmp_path, monkeypatch, {278: "1 1/2 inches", 279: "9 inches"})
    good = rp.render

    def render(path, page, dpi):
        if page == 278:
            raise RuntimeError("broken page")
        return good(path, page, dpi)

    monkeypatch.setattr(rp, "render", render)
    _, counts = run(_pages())

    assert counts["failed"] == 1 and counts["read"] == 1 and seen == [279]


def test_a_pdf_outside_the_document_folders_is_not_read(tmp_path):
    documents, data = tmp_path / "documents", tmp_path / "data"
    (documents / "tmsd").mkdir(parents=True)
    data.mkdir()
    (documents / "tmsd" / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF")

    def page(source):
        return rp.Page("tmsd", source, 1, ("scan",), "")

    assert rp.pdf_path(page("a.pdf"), documents, data) == (documents / "tmsd" / "a.pdf").resolve()
    assert rp.pdf_path(page("../../secret.pdf"), documents, data) is None
    assert rp.pdf_path(page(str(tmp_path / "secret.pdf")), documents, data) is None


def test_compare_only_drops_readings_of_pages_no_longer_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "pdf_path", lambda page, documents: None)
    store = rp.ReadingsFile(tmp_path / "page_readings.json")
    kept, gone = _pages()
    for page in (kept, gone):
        store.put(page, {"image": "x", "agreement": "agree", "differences": []})

    assert rp.prune([kept], store, tmp_path) == 1
    assert store.get(kept) is not None and store.get(gone) is None


def test_a_page_named_twice_is_read_once():
    pages = _pages()
    assert rp._wanted(pages, [pages[1].key, pages[0].key, pages[1].key]) == [pages[1], pages[0]]


def test_one_run_at_a_time_holds_the_readings_file(tmp_path):
    store = rp.ReadingsFile(tmp_path / "page_readings.json")
    with store.lock():
        with pytest.raises(SystemExit):
            with store.lock():
                pass
    with store.lock():  # released
        pass


def test_a_chunk_over_a_page_break_flags_only_its_scanned_page():
    chunks = [_chunk(6, "joined table rows", page_end=7)]
    pages = rp.flagged_pages(chunks, {("tmsd", "a.pdf"): {7}})
    assert [(p.page, p.reasons) for p in pages] == [(7, ("scan",))]


def test_a_failed_call_costs_its_worst_case_and_leaves_the_page_unread(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(rp.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")), **kw))
    monkeypatch.setattr(rp, "render", lambda path, page, dpi: b"jpeg")
    monkeypatch.setattr(rp, "pdf_path", lambda page, documents: tmp_path / page.source)
    store = rp.ReadingsFile(tmp_path / "page_readings.json")
    budget = rp.Budget(1.0, (1.0, 5.0))

    counts = asyncio.run(rp.read_all(_pages()[:1], store, {}, tmp_path, "https://example.test/v1", "k",
                                     "gpt-6.1-terra", 100, budget))

    assert counts["failed"] == 1 and store.get(_pages()[0]) is None
    assert budget.spent == pytest.approx(budget.worst)


def test_compare_only_refreshes_the_flags_after_the_index_text_changes(tmp_path):
    page = _pages()[0]
    store = rp.ReadingsFile(tmp_path / "page_readings.json")
    store.put(page, {"image": "will not exceed 1 1/2 inches", "agreement": "agree", "differences": []})

    assert rp.recompare([page], store) == 1
    assert store.get(page)["agreement"] == "disagree"
    assert rp.recompare([page], store) == 0
