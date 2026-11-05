"""Tests for the index-time table-quality flags (prototype.table_quality) and the build report (DAR-655)."""

import json

from prototype import build_report as br  # noqa: I001  (puts hosted/ on sys.path)
from prototype.table_quality import chunk_flags, flag_chunks, table_flags

# The TMP Design Manual's deflection table (PDF p. 37) as pymupdf4llm reads it:
# the rotated "Offset (ft)" row label is split down the first column and
# "Design Speed (mph)" over several header cells.
TMP_P37 = "\n".join([
    "|**Imp**|**act Angle (degree)/**||**D**|**esign Sp**|**eed(mph**|**)**|",
    "|---|---|---|---|---|---|---|",
    "|**ft)**|**30**|**40**|**50**|**60**|**70**|**80**|",
    "|**et (**|8|11.1|14.6|17.2|19.5|21.4|",
    "|**ffs**|10|12.1|15.9|18.7|21.2|23.3|",
    "|**O**|14|13.6|17.9|21.0|23.8|26.1|",
])

CLEAN = "\n".join([
    "Table 3 Lane widths",
    "",
    "||Width (ft)|Speed (mph)|",
    "|---|---|---|",
    "|Urban|11|35|",
    "|Rural|12|55|",
])


def test_a_clean_captioned_table_has_no_flags():
    assert table_flags(CLEAN) == []


def test_a_chunk_without_a_table_has_no_flags():
    assert table_flags("Table 3 lists lane widths. | not a table") == []


def test_the_tmp_p37_table_is_flagged_fragmented_with_an_empty_header():
    flags = table_flags(TMP_P37, context="[TMP Design Manual · p.37 · Figure 5 – NC-PCB impact design table]")
    assert "fragmented_header" in flags
    assert "empty_header" in flags
    assert "no_caption" not in flags  # the context line carries the caption


def test_rotated_comes_from_the_page_and_no_caption_from_text_and_context():
    flags = table_flags(TMP_P37, page_info={"chars": 900, "rotated_share": 0.9})
    assert "rotated" in flags and "no_caption" in flags
    assert "rotated" not in table_flags(TMP_P37, page_info={"chars": 900, "rotated_share": 0.02})


def test_a_row_with_a_different_cell_count_is_a_column_mismatch():
    text = CLEAN + "\n|Ramp|10|"
    assert table_flags(text) == ["column_mismatch"]


def test_a_grid_of_empty_cells_is_low_text():
    text = "Table 1 Title block\n\n|A|B|C|D|\n|---|---|---|---|\n| | | | |\n| | |x| |"
    assert "low_text" in table_flags(text)


def test_the_blank_corner_cell_is_not_an_empty_header_but_a_blank_column_header_is():
    assert "empty_header" not in table_flags(CLEAN)
    text = "Table 3\n\n|Area|Width (ft)||\n|---|---|---|\n|Urban|11|35|"
    assert "empty_header" in table_flags(text)


def test_short_units_are_not_fragments():
    text = "Table 4\n\n|No. of lanes|Width in ft|Area sq ft|\n|---|---|---|\n|2|24|100|"
    assert "fragmented_header" not in table_flags(text)


def test_single_letter_row_labels_and_enumerations_are_not_fragments():
    los = "Table 5\n\n|Level|Delay (s)|\n|---|---|\n|A|10|\n|B|20|\n|C|35|\n|D|55|"
    assert "fragmented_header" not in table_flags(los)
    items = "Table 6\n\n|Item|Rule|\n|---|---|\n|1)|Close the lane|\n|2)|Set the taper|"
    assert "fragmented_header" not in table_flags(items)


def test_a_narrow_table_of_single_digits_is_not_low_text():
    text = "Table 7\n\n|Lanes|Open|Closed|\n|---|---|---|\n|2|1|1|\n|3|2|1|"
    assert "low_text" not in table_flags(text)


def test_flags_set_by_another_step_are_kept():
    chunk = {"text": CLEAN, "flags": ["ocr_low_conf"]}
    assert chunk_flags(chunk) == ["ocr_low_conf"]


def test_flag_chunks_sets_flags_and_drops_empty_ones():
    chunks = [{"text": TMP_P37, "page": 37}, {"text": CLEAN, "page": 38, "flags": []}]
    assert flag_chunks(chunks, None) == 1
    assert "fragmented_header" in chunks[0]["flags"]
    assert "flags" not in chunks[1]


def test_the_report_has_a_row_per_document_with_flagged_pages_and_totals(tmp_path):
    chunks = [
        {"text": TMP_P37, "source": "tmp.pdf", "page": 37, "division": "wztc"},
        {"text": CLEAN, "source": "tmp.pdf", "page": 38, "division": "wztc"},
        {"text": "prose", "source": "uam.pdf", "page": 1, "division": "utilities"},
    ]
    stats = [{"division": "wztc", "source": "tmp.pdf", "pdf_pages": 40, "pages_with_text": 2},
             {"division": "utilities", "source": "scan.pdf", "pdf_pages": 3, "pages_with_text": 0}]
    path = tmp_path / "report.json"
    report = br.write_report(path, chunks, stats, {"mode": "test"}, documents_dir=tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["totals"] == report["totals"]
    rows = {r["source"]: r for r in report["documents"]}
    assert set(rows) == {"tmp.pdf", "uam.pdf", "scan.pdf"}  # a document with no chunks still gets a row
    tmp = rows["tmp.pdf"]
    assert tmp["table_chunks"] == 2 and [f["page"] for f in tmp["flagged"]] == [37]
    assert tmp["empty_text_pages"] == [p for p in range(1, 41) if p not in (37, 38)]
    assert tmp["ocr_pages"] is None  # no PDF to tell
    assert rows["scan.pdf"]["empty_text_pages"] == [1, 2, 3]
    assert report["totals"]["all"]["flagged_chunks"] == 1
    assert report["totals"]["all"]["flagged_structure"] == 1
    assert report["totals"]["wztc"]["fragmented_header"] == 1
    assert "tmp.pdf" not in br.markdown_summary(report).split("| Document |")[1]  # under 5 tables: not ranked


def test_the_standalone_mode_reads_an_index_directory(tmp_path):
    index = tmp_path / "index"
    index.mkdir()
    chunks = [{"text": TMP_P37, "source": "tmp.pdf", "page": 37, "division": "wztc", "section": None}]
    (index / "chunks.json").write_text(json.dumps({"model": "m", "dim": 2, "chunks": chunks}), encoding="utf-8")
    out = tmp_path / "out.json"
    assert br.main(["--index", str(index), "--out", str(out), "--documents", str(tmp_path)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["settings"]["mode"] == "standalone"
    assert report["documents"][0]["flagged"][0]["page"] == 37
