"""Extraction bake-off on the corpus's hardest pages (DAR-656).

    py -m prototype.bakeoff.select_pages        pick the pages -> prototype/bakeoff/pages.json
    py -m prototype.bakeoff.run --candidate X   extract them with one tool -> <out>/X.jsonl
    py -m prototype.bakeoff.report              score every candidate -> docs/extraction-bakeoff/

Each candidate runs in the environment that has it installed (Docling and
MinerU live in their own scratch venvs, never in .venv), so run.py imports
only the standard library at module level and the tool inside its candidate.
"""
