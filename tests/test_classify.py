"""Tests for Document classification (rag.classify), keyed on relative paths."""

import pytest

from rag.classify import classify


@pytest.mark.parametrize("relative_path,topic,doc_domain", [
    ("seed_work_zone_manual.md", "work_zone", "reference"),
    ("utility_accommodations_manual.pdf", "utilities", "reference"),
    ("tmsd_safety_guidelines.pdf", "mobility_safety", "reference"),
    ("design_policy.pdf", "unknown", "reference"),
    ("report.docx", "unknown", "general"),
    ("project_summary.md", "unknown", "general"),
    # Substring false positives: short keywords ("tim", "its", "tmp") match whole tokens only
    ("K-Maps Lecture Notes page.pdf", "unknown", "general"),
    ("timeline/notes.md", "unknown", "general"),
    ("timesheet_items.md", "unknown", "general"),
    # Word-level matches
    ("TIM program.md", "mobility_safety", "general"),
    ("frac-out response.md", "utilities", "general"),
    ("WZ lane closures.md", "work_zone", "general"),
    ("pavement marking plans.md", "signals_signing", "general"),
    # Keywords of 4+ chars also match as a prefix
    ("encroachments 2024.md", "utilities", "general"),
    ("guidebook/q1.md", "unknown", "reference"),
])
def test_topic_and_domain(relative_path, topic, doc_domain):
    result = classify(relative_path)
    assert result.topic == topic
    assert result.doc_domain == doc_domain


def test_directory_names_count():
    assert classify("utilities/overview.md").topic == "utilities"


@pytest.mark.parametrize("relative_path", [
    "standard_drawings.pdf", "standard-drawing 1101.md", "rsd/Roadway Standard Drawings 2024.pdf",
])
def test_standard_drawings(relative_path):
    result = classify(relative_path)
    assert result.doc_domain == "standard_drawings"
    assert result.topic == "general"
    assert result.tags == "standard,drawings"


def test_tags_list_every_match_plus_reference():
    result = classify("utility_work_zone_manual.md")
    assert result.topic == "work_zone"
    assert result.tags == "work_zone,utilities,reference"


def test_no_match_tags_none():
    assert classify("readme.md").tags == "none"


def test_extension_is_not_a_token():
    # ".tmp" would otherwise read as the token "tmp" (transportation management plan)
    assert classify("layout.tmp").topic == "unknown"


@pytest.mark.parametrize("relative_path,topic", [
    ("traffic incident management.md", "mobility_safety"),
    ("temporary traffic control signals.md", "work_zone"),
    ("directional drilling safety.md", "utilities"),
    ("utility_work_zone_manual.md", "work_zone"),
])
def test_most_specific_keyword_wins(relative_path, topic):
    assert classify(relative_path).topic == topic


def test_equal_specificity_goes_to_earlier_label():
    # "wztc" (work_zone) and "tmsd" (mobility_safety) are both one word of four chars
    assert classify("wztc tmsd.md").topic == "work_zone"
