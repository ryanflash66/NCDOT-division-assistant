"""The locked test set (DAR-653): question files, the tuning/locked split and the loader.

    py -m evaluation.locked.run run --label NAME [--split tuning|locked|all] [--stage retrieval|answer|all]
    py -m evaluation.locked.run freeze | check | validate
    py -m evaluation.locked.validate

Question files are evaluation/locked/<division>.json, one per division, each
{"division": id, "items": [...]} (the schema is in README.md and ITEM_KEYS
below). The runner loads every *.json here and works with none of them too.

Importing this package imports `evaluation`, which puts hosted/ on sys.path so
the runner uses the hosted app's own `divrag` pipeline.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from evaluation import ROOT  # noqa: F401 (puts hosted/ on sys.path)

LOCKED_DIR = Path(__file__).resolve().parent
RESULTS_DIR = LOCKED_DIR / "results"  # gitignored: the answer cache
CACHE_PATH = RESULTS_DIR / "cache.jsonl"
HASH_FILE = LOCKED_DIR / "LOCKED.sha256"
DOCS_DIR = ROOT / "docs" / "locked-set"
RUNS_FILE = DOCS_DIR / "RUNS.md"

TYPES = ("table", "figure", "scan", "rotated", "multipage_table", "text", "unanswerable", "table_id", "page_ref",
         "units", "footnote", "duplicate_pages", "cross_ref")
SPLITS = ("tuning", "locked")
ITEM_KEYS = ("id", "division", "asker", "question", "type", "expected", "refuse", "split")
OPTIONAL_KEYS = ("edge_cases", "verified_by", "note", "behaviour")
# What the right reply does (DAR-718). Without the key: "refuse" when refuse is true, else "answer".
#   answer   state the gold value from the gold page
#   refuse   say the documents don't cover it
#   correct  the question asserts something false; the reply gives the documents' value instead (scored as answer)
#   clarify  the question leaves out a variable the answer depends on; the reply asks for it or shows every
#            branch (expected.all_of lists the branch values)
BEHAVIOURS = ("answer", "refuse", "correct", "clarify")
# Hex digits of the split hash below this go to tuning: 3 of 16, so about one item in five.
TUNING_DIGITS = 3


def split_key(item: Dict[str, Any]) -> str:
    """What an item's split is hashed on: its gold document page, so tuning and locked never share a page.

    Questions about the same page or table are correlated (the asphalt and
    concrete deflection tables of the TMP manual, pp. 37-38, are one failure,
    not ten), so a page seen while tuning must not also sit in the locked set.
    An unanswerable item has no page and hashes on its question.
    """
    expected = item.get("expected")
    if item.get("refuse") or not expected:
        return item["question"]
    return f"{expected['source']}|{expected['pdf_pages'][0]}"


def split_of(item: Dict[str, Any]) -> str:
    digit = int(hashlib.sha1(split_key(item).encode("utf-8")).hexdigest()[-1], 16)
    return "tuning" if digit < TUNING_DIGITS else "locked"


def question_files(directory: Path = LOCKED_DIR) -> List[Path]:
    """Every question file in `directory`, in name order (results/ and the hash file are not JSON files there)."""
    return sorted(p for p in Path(directory).glob("*.json") if p.is_file())


def load_items(directory: Path = LOCKED_DIR, split: Optional[str] = None, only: Optional[Sequence[str]] = None,
               limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """The items of every question file, each with `_file` (the file it came from) and `_division` (the file's)."""
    items: List[Dict[str, Any]] = []
    for path in question_files(directory):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            items.append(dict(item, _file=path.name, _division=data.get("division")))
    if split and split != "all":
        items = [i for i in items if i.get("split") == split]
    if only:
        wanted = set(only)
        items = [i for i in items if i.get("id") in wanted]
    return items[:limit] if limit else items


def public_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """The item without the loader's private keys."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def canonical_json(items: Iterable[Dict[str, Any]]) -> str:
    """The locked items as one canonical string: sorted by id, keys sorted, no whitespace."""
    rows = sorted((public_item(i) for i in items), key=lambda i: i["id"])
    return json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def locked_digest(items: Iterable[Dict[str, Any]]) -> str:
    """SHA-256 of the canonical JSON of the items whose split is locked."""
    locked = [i for i in items if i.get("split") == "locked"]
    return hashlib.sha256(canonical_json(locked).encode("utf-8")).hexdigest()
