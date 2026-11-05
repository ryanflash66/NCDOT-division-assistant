"""Tests for table text fidelity (rag/table_rows.py, applied by rag/tables.py), DAR-655.

The fixtures are pymupdf4llm's Markdown for TMP Design Manual PDF p. 37 and 38
(NC-PCB deflection tables, with the rotated row header "Offset (ft)") and the
Roadway Design Manual's At Grade Intersections p. 21 (turn radius Table 3).
"""

from pathlib import Path

import pytest
from llama_index.core import Document
from llama_index.core.utils import get_tokenizer

from rag import table_rows, tables

FIXTURES = Path(__file__).parent / "fixtures" / "tables"
ROTATED = ["Offset (ft) "]  # the p. 37 text layer's only line with dir (0, -1)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _table(text: str):
    rows = [line for line in text.split("\n") if tables.is_table_line(line)]
    n_header = tables._header_row_count(rows)
    return table_rows.split_table(rows, n_header)


def _labelled(text: str):
    header, _, body = _table(text)
    return [line for line in table_rows.row_labels(header, body) or [] if line]


@pytest.mark.parametrize("name", ["tmp-design-manual-p37.md", "tmp-design-manual-p38.md"])
def test_rotated_offset_header_labels_every_row(name):
    cleaned = tables.clean_markdown_tables(_fixture(name), ROTATED)
    header, _, body = _table(cleaned)

    assert all(table_rows.plain(values[0]) == "Offset (ft)" for values in header)
    assert "ft)" not in "".join(values[0] for values in body)
    assert all(table_rows.plain(values[0]) for values in body)
    assert len(body) == 20  # 10 offsets x (Impact Angle, Maximum Deflection), stacked rows split

    lines = _labelled(cleaned)
    for offset in ("14", "20", "26"):
        mine = [line for line in lines if line.startswith(f"Offset (ft)={offset} |")]
        assert len(mine) == 2, offset
        assert "Impact Angle" in mine[0] and "Maximum Deflection" in mine[1]
        assert "Design Speed(mph): 30=" in mine[1]


def test_p37_deflection_for_14_ft_at_40_mph_is_named():
    lines = _labelled(tables.clean_markdown_tables(_fixture("tmp-design-manual-p37.md"), ROTATED))
    assert ("Offset (ft)=14 | Maximum Deflection | Design Speed(mph): 30=25.16, 40=27.42, "
            "50=30.43, 60=34.25, 70=37.02, 80=41.45") in lines


def test_sliced_header_titles_are_rejoined_over_their_span():
    cleaned = tables.clean_markdown_tables(_fixture("tmp-design-manual-p37.md"), ROTATED)
    header, _, _ = _table(cleaned)
    assert [table_rows.plain(c) for c in header[0][2:]] == ["Design Speed(mph)"] * 6
    assert table_rows.plain(header[0][1]) == "Impact Angle (degree)/"
    assert table_rows.plain(header[1][1]) == "Maximum Deflection (in)"


def test_without_the_text_layer_rows_still_carry_their_offset():
    cleaned = tables.clean_markdown_tables(_fixture("tmp-design-manual-p37.md"))
    _, _, body = _table(cleaned)
    labels = [table_rows.plain(values[0]) for values in body]
    assert labels[2:4] == ["14", "14"]
    assert labels[4:8] == ["20", "20", "26", "26"]


def test_turn_radius_table_rows_name_angle_and_vehicle():
    lines = _labelled(tables.clean_markdown_tables(_fixture("at-grade-intersections-p21.md")))
    assert ("Angle of Turn (Degrees)=135 | Design Vehicle=SU-40 | Simple: Curve Radius=-, Radius (ft.)=40 | "
            "Curve Radius with Taper: Offset (ft.)=4.0, Taper (ft.:ft.)=8:1") in lines
    assert len(lines) == 27


def test_split_table_keeps_each_offset_whole_and_repeats_the_header():
    tokenizer = get_tokenizer()
    count = lambda s: len(tokenizer(s))  # noqa: E731
    cleaned = tables.clean_markdown_tables(_fixture("tmp-design-manual-p37.md"), ROTATED)
    chunks = [c for c in tables.split_text(cleaned, 512, 50, count) if "|---|" in c]

    assert len(chunks) > 1
    seen = []
    for chunk in chunks:
        assert count(chunk) <= 512
        assert "|**Offset (ft)**|**Impact Angle (degree)/**|" in chunk
        assert "Rows:" in chunk
        offsets = [line.split(" |")[0] for line in chunk.split("\n") if line.startswith("Offset (ft)=")]
        assert offsets and all(offsets.count(o) == 2 for o in set(offsets))  # both rows of an offset
        seen.extend(dict.fromkeys(offsets))
    assert len(seen) == 10 and len(set(seen)) == 10


def test_small_table_gets_its_labelled_rows_in_the_same_chunk():
    text = "\n".join([
        "###### Table 2 Lane widths",
        "|Road|Speed (mph)|Width (ft)|",
        "|---|---|---|",
        "|Interstate|70|12|",
        "|Local|25|10|",
    ])
    chunks = tables.split_text(text, 512, 0, lambda s: len(s.split()))
    assert chunks == [text + "\nRows (Table 2 Lane widths):\nRoad=Interstate | Speed (mph)=70 | Width (ft)=12\n"
                      "Road=Local | Speed (mph)=25 | Width (ft)=10"]


def test_unstack_leaves_a_single_wrapped_cell_alone():
    row = "|10 inches<br>(informal)|5|6|"
    assert table_rows.unstack_rows([row]) == [row]
    assert table_rows.unstack_rows(["|a|1<br>2|3<br>4|"]) == ["|a|1|3|", "||2|4|"]


def test_lone_letter_is_not_taken_for_a_rotated_fragment():
    rows = ["|x|y|z|", "|---|---|---|", "|O<br>1|2|3|", "|4|5|6|"]
    out, found = table_rows.strip_rotated_fragments(rows, ROTATED)
    assert out == rows and found == {}


def test_wrapped_header_and_wrapped_sentences_are_not_unstacked():
    header = "|Design<br>Speed [mph]|Lane<br>Width [ft]|Shoulder<br>Width [ft]|"
    words = "|Cone|Place at<br>50 ft|Orange<br>only|"
    rows = [header, "|---|---|---|", "|[55]|[12]|[8]|", words]
    assert table_rows.unstack_rows(rows) == rows


def test_cell_equal_to_a_rotated_line_is_kept():
    rows = ["|Speed|Width|Notes|", "|---|---|---|", "|40|12|Maximum Deflection|"]
    out, found = table_rows.strip_rotated_fragments(rows, ["Maximum Deflection"])
    assert out == rows and found == {}


def test_header_left_fill_only_over_a_column_group():
    group = ["|Item|Design Speed|||", "|---|---|---|---|", "||30|40|50|", "|a|1|2|3|"]
    filled = table_rows.fill_header_spans(group, 3)
    assert filled[0] == "|Item|Design Speed|Design Speed|Design Speed|"

    lower = ["|Type|Width||", "|---|---|---|", "|||Remarks|", "|a|1|x|"]
    header, _, _ = table_rows.split_table(table_rows.fill_header_spans(lower, 3), 3)
    assert table_rows.header_paths(header)[2] == ["Remarks"]


def test_row_of_words_is_not_given_the_label_above():
    rows = ["|Device|Use|Count|", "|---|---|---|", "|Cone|Orange traffic cone|2|", "||placed at 50 ft intervals||"]
    assert table_rows.fill_row_labels(rows, 2) == rows


def test_description_column_is_not_forward_filled():
    long = "Use this device where the shoulder is closed for more than one day"
    rows = ["|Device|Size|Count|", "|---|---|---|", f"|{long}|36|2|", "||48|3|"]
    assert table_rows.fill_row_labels(rows, 2) == rows


def test_splitter_tags_table_chunks_kind_table_outside_the_embedded_text():
    splitter = tables.TableAwareSplitter(chunk_size=512, chunk_overlap=0)
    prose = " ".join(f"word{i}." for i in range(80))
    nodes = splitter.get_nodes_from_documents([
        Document(text=f"{prose}\n\n|a|b|c|\n|---|---|---|\n|1|2|3|", metadata={"source": "x.pdf"})])
    kinds = [n.metadata.get("kind") for n in nodes]
    assert kinds == [None, "table"]
    assert "kind" not in nodes[1].get_content(metadata_mode="embed")
    assert nodes[1].metadata["source"] == "x.pdf"
