"""The locked set's runner, pointed at the held-out set.

    py -m evaluation.heldout.run run --label NAME --split locked --env-file .env
    py -m evaluation.heldout.run freeze | check | validate

Same subcommands and options as evaluation.locked.run. The defaults change:
questions from evaluation/heldout/, the hash in HELDOUT.sha256, reports in
docs/heldout-set/, runs counted in docs/heldout-set/RUNS.md, answers cached in
evaluation/heldout/results/. Every command first checks that the items only
use the edge-case tags of evaluation.heldout.EDGE_CASES.
"""

import sys
from typing import List, Optional, Sequence

from evaluation.locked import load_items
from evaluation.locked.run import main as locked_main

from . import CACHE_PATH, DOCS_DIR, HASH_FILE, HELDOUT_DIR, RUNS_FILE, tag_errors

_DEFAULTS = {
    "run": (("--questions", HELDOUT_DIR), ("--out", DOCS_DIR), ("--runs-file", RUNS_FILE), ("--cache", CACHE_PATH)),
    "freeze": (("--questions", HELDOUT_DIR), ("--hash-file", HASH_FILE)),
    "check": (("--questions", HELDOUT_DIR), ("--hash-file", HASH_FILE)),
    "validate": (("--questions", HELDOUT_DIR),),
}


def with_defaults(argv: Sequence[str]) -> List[str]:
    """argv with the held-out paths added for every option the caller left out."""
    argv = list(argv)
    if argv and argv[0].startswith("--") and argv[0] != "--help":
        argv = ["run", *argv]
    for option, value in _DEFAULTS.get(argv[0] if argv else "", ()):
        if option not in argv:
            argv += [option, str(value)]
    return argv


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = with_defaults(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _DEFAULTS:
        questions = argv[argv.index("--questions") + 1]
        errors = tag_errors(load_items(questions))
        if errors:
            print("\n".join(errors))
            print(f"{len(errors)} item(s) with unknown edge-case tags")
            return 1
    return locked_main(argv)


if __name__ == "__main__":
    sys.exit(main())
