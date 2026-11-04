"""Tests for the image/table retrieval test (prototype.image_table_check): captions and the patched index."""

import numpy as np

from prototype.image_table_check import captions, patched  # puts hosted/ on sys.path
from divrag.index_file import IndexFile


class _FakeEmbedder:
    def passages(self, texts):
        return np.ones((len(list(texts)), 4), dtype=np.float32) / 2


def _chunk(source, page, text, section=None):
    return {"text": text, "source": source, "page": page, "section": section, "division": "wztc"}


def test_captions_finds_underlined_figure_and_table_titles():
    text = ("|8|Impact Angle|11.1|\n\n<u>Figure 5 – NC-PCB impact design table for CONCRETE pavement</u> \n\n"
            "# <u>TABLE 3 (continued)</u>\nSee Figure 3 for the offsets.\nPart 2: Chapter 5 | Page 14")
    assert captions(text) == ["Figure 5 – NC-PCB impact design table for CONCRETE pavement", "TABLE 3 (continued)"]


def test_patched_replaces_only_the_extracted_pages_in_document_order():
    chunks = [_chunk("a.pdf", 1, "one", "1 Intro"), _chunk("a.pdf", 2, "old two"), _chunk("a.pdf", 4, "four"),
              _chunk("b.pdf", 1, "other document")]
    index = IndexFile("m", chunks, np.arange(16, dtype=np.float32).reshape(4, 4))
    extracted = [{"division": "wztc", "source": "a.pdf", "page": 2, "text": "new two"},
                 {"division": "wztc", "source": "a.pdf", "page": 3, "text": "scanned three"}]

    result = patched(index, _FakeEmbedder(), extracted)

    assert [(c["source"], c["page"], c["text"]) for c in result.chunks] == [
        ("a.pdf", 1, "one"), ("a.pdf", 2, "new two"), ("a.pdf", 3, "scanned three"), ("a.pdf", 4, "four"),
        ("b.pdf", 1, "other document")]
    assert result.chunks[2]["section"] == "1 Intro"  # the section in effect where the page is
    np.testing.assert_array_equal(result.vectors[0], index.vectors[0])  # kept chunks keep their vectors
    np.testing.assert_array_equal(result.vectors[4], index.vectors[3])


def test_patched_with_captions_starts_each_chunk_with_the_page_caption():
    index = IndexFile("m", [_chunk("a.pdf", 1, "old")], np.ones((1, 4), dtype=np.float32))
    # A table long enough to be split away from the caption under it, as on TMP manual page 38.
    rows = "\n".join(f"|{offset}|Maximum Deflection|{offset + 1.28}|{offset + 2.5}|{offset + 3.75}|"
                     for offset in range(8, 400, 6))
    caption = "Figure 5 – NC-PCB impact design table for CONCRETE pavement"
    text = f"|Offset|Row|30|40|50|\n|---|---|---|---|---|\n{rows}\n\n<u>{caption}</u>"
    result = patched(index, _FakeEmbedder(), [{"division": "wztc", "source": "a.pdf", "page": 1, "text": text}],
                     with_captions=True)
    assert len(result.chunks) > 1
    assert all(caption in c["text"] for c in result.chunks)
    assert result.chunks[0]["text"].startswith(caption + "\n\n|Offset|")
