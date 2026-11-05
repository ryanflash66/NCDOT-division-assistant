"""Tests for the hosted question parser: the table, figure, section and document numbers a question names (DAR-657)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.query import ParsedQuery, parse  # noqa: E402


def test_a_question_naming_a_table_gives_its_id():
    assert parse("What does Table 3 in the TMP Design Manual give for a 40 mph design speed?") == ParsedQuery(
        ids=["Table 3"], doc_codes=[])


def test_labels_and_numbers_are_normalised():
    parsed = parse("What does Fig. 6h-3 show? See section 4.2, sheet 1, tbl 3-2, Standard 1101.01, Table No. 17, Exhibit A-3.")
    assert parsed.ids == ["Figure 6H-3", "Section 4.2", "Sheet 1", "Table 3-2", "Standard 1101.01", "Table 17", "Exhibit A-3"]


def test_document_codes_but_not_quantities_years_or_decimals():
    parsed = parse("Is document 04091 the same as 04-20340 or no. 12345? ADT 6000 in 2024, #20340")
    assert parsed.doc_codes == ["04091", "04-20340", "12345", "20340"]
    assert parse("Standard 04091 applies") == ParsedQuery(ids=["Standard 04091"], doc_codes=[])  # the id has it
    assert parse("What does Table 3 give for a slope of 0.0200?").doc_codes == []  # a decimal, not a code


def test_a_question_without_identifiers_parses_empty():
    assert parse("Who pays for a detour when a utility closes a road?") == ParsedQuery([], [])
    assert parse("A 12' wide lane with a 2\" drop-off at 5% grade") == ParsedQuery([], [])


def test_each_id_once_and_sentence_punctuation_is_not_part_of_the_number():
    parsed = parse("Table 3-2 and Table 3-2. Then Figure 5, then figure 5?")
    assert parsed.ids == ["Table 3-2", "Figure 5"]
    assert parse("section 4 of the manual").ids == ["Section 4"]
    assert parse("a table 3 columns wide").ids == ["Table 3"]  # a wrong guess only shifts a score
