"""Check the locked-set question files against the schema (README.md).

    py -m evaluation.locked.validate [--questions DIR]

Exit 1 with one line per problem, or "N items in M files: ok".
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import BEHAVIOURS, ITEM_KEYS, LOCKED_DIR, OPTIONAL_KEYS, SPLITS, TYPES, load_items, split_of


def _divisions() -> Dict[str, set]:
    from divrag.divisions import DIVISIONS

    return {d.id: {doc.file for doc in d.documents} for d in DIVISIONS}


def _check_expected(item: Dict[str, Any], files: set, errors: List[str]) -> None:
    where = f"{item.get('_file', '?')}:{item.get('id')}"
    expected = item.get("expected")
    if not isinstance(expected, dict):
        errors.append(f"{where}: expected must be an object when refuse is false")
        return
    source = expected.get("source")
    if source not in files:
        errors.append(f"{where}: expected.source {source!r} is not a document of division {item.get('division')!r}")
    pages = expected.get("pdf_pages")
    if not isinstance(pages, list) or not pages or not all(isinstance(p, int) and not isinstance(p, bool) and p >= 1
                                                            for p in pages):
        errors.append(f"{where}: expected.pdf_pages must be a non-empty list of 1-based page numbers")
    printed = expected.get("printed_pages", [])
    if not isinstance(printed, list) or not all(isinstance(p, str) for p in printed):
        errors.append(f"{where}: expected.printed_pages must be a list of strings (\"\" when a page has none)")
    if not isinstance(expected.get("value"), str) or not expected["value"].strip():
        errors.append(f"{where}: expected.value must be a non-empty string")
    accept = expected.get("accept", [])
    if not isinstance(accept, list) or not all(isinstance(a, str) for a in accept):
        errors.append(f"{where}: expected.accept must be a list of strings")
    if "unit" in expected and expected["unit"] is not None and not isinstance(expected["unit"], str):
        errors.append(f"{where}: expected.unit must be a string or null")
    all_of = expected.get("all_of")
    if all_of is not None and not _is_all_of(all_of):
        errors.append(f"{where}: expected.all_of must be a non-empty list whose entries are a string or a list of "
                      f"strings (the wordings of one required part)")
    if item.get("behaviour") == "clarify" and not (_is_all_of(all_of) and len(all_of) >= 2):
        errors.append(f"{where}: behaviour clarify needs expected.all_of with the value of each branch (two or more)")


def _is_all_of(value: Any) -> bool:
    def part(entry: Any) -> bool:
        if isinstance(entry, str):
            return bool(entry.strip())
        return isinstance(entry, list) and bool(entry) and all(isinstance(e, str) and e.strip() for e in entry)

    return isinstance(value, list) and bool(value) and all(part(entry) for entry in value)


def validate_items(items: Iterable[Dict[str, Any]], divisions: Optional[Dict[str, set]] = None) -> List[str]:
    """Every problem found, as "file:id: what is wrong"; an empty list means the items are valid."""
    divisions = _divisions() if divisions is None else divisions
    errors: List[str] = []
    seen_ids: Dict[str, str] = {}
    for n, item in enumerate(items, 1):
        where = f"{item.get('_file', '?')}:{item.get('id') or f'item {n}'}"
        missing = [k for k in ITEM_KEYS if k not in item]
        if missing:
            errors.append(f"{where}: missing keys {missing}")
            continue
        unknown = [k for k in item if not k.startswith("_") and k not in ITEM_KEYS + OPTIONAL_KEYS]
        if unknown:
            errors.append(f"{where}: unknown keys {unknown}")
        if not isinstance(item["id"], str) or not item["id"].strip():
            errors.append(f"{where}: id must be a non-empty string")
        elif item["id"] in seen_ids:
            errors.append(f"{where}: duplicate id (also in {seen_ids[item['id']]})")
        else:
            seen_ids[item["id"]] = item.get("_file", "?")
        if not isinstance(item["question"], str) or len(item["question"].strip()) < 3:
            errors.append(f"{where}: question must be a string of at least 3 characters")
        if item["division"] not in divisions:
            errors.append(f"{where}: division {item['division']!r} is not a division id")
        elif item.get("_division") not in (None, item["division"]):
            errors.append(f"{where}: division {item['division']!r} differs from the file's {item['_division']!r}")
        if item["asker"] not in divisions:
            errors.append(f"{where}: asker {item['asker']!r} is not a division id")
        if item["type"] not in TYPES:
            errors.append(f"{where}: type {item['type']!r} is not one of {', '.join(TYPES)}")
        if not isinstance(item.get("edge_cases", []), list) or not all(isinstance(e, str) for e in item.get("edge_cases", [])):
            errors.append(f"{where}: edge_cases must be a list of strings")
        for key in ("verified_by", "note"):
            if key in item and not isinstance(item[key], str):
                errors.append(f"{where}: {key} must be a string")
        if not isinstance(item["refuse"], bool):
            errors.append(f"{where}: refuse must be true or false")
            continue
        if item["refuse"] != (item["expected"] is None):
            errors.append(f"{where}: refuse must be true exactly when expected is null")
            continue
        behaviour = item.get("behaviour")
        if behaviour is not None and behaviour not in BEHAVIOURS:
            errors.append(f"{where}: behaviour {behaviour!r} is not one of {', '.join(BEHAVIOURS)}")
        elif behaviour is not None and (behaviour == "refuse") != item["refuse"]:
            errors.append(f"{where}: behaviour {behaviour!r} does not fit refuse {str(item['refuse']).lower()}")
        if item["type"] == "unanswerable" and not item["refuse"]:
            errors.append(f"{where}: type unanswerable needs refuse true")
        if not item["refuse"]:
            _check_expected(item, divisions.get(item["division"], set()), errors)
        if item["split"] not in SPLITS:
            errors.append(f"{where}: split must be tuning or locked")
            continue
        try:
            wanted = split_of(item)
        except (KeyError, IndexError, TypeError):
            continue  # the expected block is already reported above
        if item["split"] != wanted:
            errors.append(f"{where}: split is {item['split']!r} but the hash rule says {wanted!r}")
    return errors


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.locked.validate", description=__doc__.splitlines()[0])
    parser.add_argument("--questions", default=str(LOCKED_DIR), help="directory of question files (default: evaluation/locked)")
    args = parser.parse_args(argv)
    items = load_items(Path(args.questions))
    errors = validate_items(items)
    for error in errors:
        print(error)
    files = {i["_file"] for i in items}
    if errors:
        print(f"{len(errors)} problem(s) in {len(items)} items from {len(files)} file(s)")
        return 1
    print(f"{len(items)} items in {len(files)} file(s): ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
