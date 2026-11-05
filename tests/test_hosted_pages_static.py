"""Tests for the cited page's image (DAR-654): slugs, the manifest, image_url and Source.image. No rendering."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import pages_static  # noqa: E402
from divrag.answer import Source, _source_for  # noqa: E402
from divrag.divisions import DIVISIONS  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.pages_static import image_url, page_image_path, slug  # noqa: E402

TMP = "TMP Design Manual (Combined, No Links).pdf"


@pytest.fixture(autouse=True)
def _fresh_cache():
    pages_static.reset()
    yield
    pages_static.reset()


def _point_at(monkeypatch, public: Path):
    monkeypatch.setattr(pages_static, "PAGES_DIR", public / "pages")
    monkeypatch.setattr(pages_static, "MANIFEST_FILE", public / "page-images.json")


def _render(public: Path, division: str, file: str, *pages: int):
    for page in pages:
        target = public / "pages" / page_image_path(division, file, page)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\xff\xd8\xff")


@pytest.mark.parametrize("file, expected", [
    (TMP, "tmp-design-manual-combined-no-links"),
    ("2023 WZ Safety & Mobility Process Review.pdf", "2023-wz-safety-mobility-process-review"),
    ("09. Right of Way.pdf", "09-right-of-way"),
    ("03. Guardrail, Barriers and Attenuators.pdf", "03-guardrail-barriers-and-attenuators"),
    ("20220713 NCDOT UAM Ver 2-0.pdf", "20220713-ncdot-uam-ver-2-0"),
    ("16-1-Two-Party-Utility-Primary-and-Secondary-Highways-Non-C-A.pdf",
     "16-1-two-party-utility-primary-and-secondary-highways-non-c-a"),
    ("()..pdf", "document"),
])
def test_slugs_are_url_safe_and_deterministic(file, expected):
    assert slug(file) == expected
    assert slug(file) == slug(file)


def test_every_real_file_name_has_a_distinct_slug_within_its_division():
    for division in DIVISIONS:
        slugs = [slug(d.file) for d in division.documents]
        assert len(set(slugs)) == len(slugs), division.id
        for s in slugs:
            assert s and all(c.islower() or c.isdigit() or c == "-" for c in s), s


def test_page_image_path_is_division_slug_page():
    assert page_image_path("wztc", TMP, 37) == "wztc/tmp-design-manual-combined-no-links/37.jpg"


def test_image_url_is_none_without_rendered_pages(tmp_path, monkeypatch):
    _point_at(monkeypatch, tmp_path / "public")
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) is None


def test_image_url_names_the_rendered_page_found_in_the_folder(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _point_at(monkeypatch, public)
    _render(public, "wztc", TMP, 37, 38)
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) == "/pages/wztc/tmp-design-manual-combined-no-links/37.jpg"
    assert image_url({"division": "wztc", "source": TMP, "page": 39}) is None
    assert image_url({"division": "utilities", "source": TMP, "page": 37}) is None  # another division's folder
    assert image_url({"division": "wztc", "source": TMP, "page": None}) is None


def test_image_url_reads_the_manifest_when_the_folder_is_absent(tmp_path, monkeypatch):
    # On Vercel the function bundle has the manifest but not the images (vercel.json's excludeFiles).
    public = tmp_path / "public"
    _point_at(monkeypatch, public)
    public.mkdir()
    (public / "page-images.json").write_text(json.dumps({"wztc/tmp-design-manual-combined-no-links": [37]}))
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) == "/pages/wztc/tmp-design-manual-combined-no-links/37.jpg"
    assert image_url({"division": "wztc", "source": TMP, "page": 38}) is None


def test_a_damaged_manifest_means_no_images_not_an_error(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _point_at(monkeypatch, public)
    public.mkdir()
    (public / "page-images.json").write_text("{not json")
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) is None


def test_write_manifest_lists_the_rendered_pages_per_document(tmp_path):
    public = tmp_path / "public"
    _render(public, "wztc", TMP, 3, 1, 2)
    _render(public, "utilities", "20220713 NCDOT UAM Ver 2-0.pdf", 126)
    (public / "pages" / "wztc" / "tmp-design-manual-combined-no-links" / "notes.txt").write_text("x")
    found = pages_static.write_manifest(public / "pages", public / "page-images.json")
    assert found == {"wztc/tmp-design-manual-combined-no-links": {1, 2, 3}, "utilities/20220713-ncdot-uam-ver-2-0": {126}}
    assert json.loads((public / "page-images.json").read_text()) == {
        "utilities/20220713-ncdot-uam-ver-2-0": [126],
        "wztc/tmp-design-manual-combined-no-links": [1, 2, 3],
    }


def test_the_listing_is_read_once(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _point_at(monkeypatch, public)
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) is None
    _render(public, "wztc", TMP, 37)
    assert image_url({"division": "wztc", "source": TMP, "page": 37}) is None  # cached: the folder was empty at first use
    pages_static.reset()
    assert image_url({"division": "wztc", "source": TMP, "page": 37})


def test_source_carries_the_image_and_as_dict_includes_it(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _point_at(monkeypatch, public)
    _render(public, "wztc", TMP, 37)
    chunk = {"text": "Table 3", "source": TMP, "page": 37, "section": "5.2", "division": "wztc"}
    with_image = _source_for(Hit(1.0, chunk), 1)
    assert with_image.image == "/pages/wztc/tmp-design-manual-combined-no-links/37.jpg"
    assert with_image.as_dict()["image"] == with_image.image
    without = _source_for(Hit(1.0, dict(chunk, page=38)), 2)
    assert without.image is None
    assert "image" in without.as_dict() and without.as_dict()["image"] is None
    assert Source(1, "wztc", "t", 1, None, None, "", "").image is None


def _script():
    from prototype.render_pages import _load
    return _load()


def test_indexed_pages_are_kept_per_division(tmp_path):
    chunks = tmp_path / "chunks.json"
    chunks.write_text(json.dumps({"chunks": [
        {"division": "wztc", "source": TMP, "page": 37},
        {"division": "wztc", "source": TMP, "page": 38},
        {"division": "tmsd", "source": TMP, "page": 5},
        {"division": "wztc", "source": TMP, "page": None},
    ]}))
    assert _script().indexed_pages(chunks) == {("wztc", TMP): {37, 38}, ("tmsd", TMP): {5}}


def test_render_document_renders_only_the_wanted_pages(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "doc.pdf"
    with pymupdf.open() as doc:
        for n in range(3):
            doc.new_page().insert_text((72, 72), f"Page {n + 1}")
        doc.save(pdf)
    out = tmp_path / "out"
    script = _script()
    sizes = script.render_document(pdf, out, 30, 50, pages={2, 9})  # 9 is past the end
    assert sorted(p.name for p in out.iterdir()) == ["2.jpg"]
    assert len(sizes) == 1 and (out / "2.jpg").read_bytes()[:2] == b"\xff\xd8"
    assert script.render_document(pdf, out, 30, 50, pages={2}) == []  # already there
    assert script.render_document(pdf, tmp_path / "none", 30, 50, pages=set()) == []
    assert not (tmp_path / "none").exists()
