"""Render the divisions' PDF pages to images for the Sources panel (DAR-654).

    py -m prototype.render_pages [--division ID ...] [--file NAME ...] [--out hosted/public/pages]
                                 [--dpi 60] [--quality 60] [--only-indexed hosted/index/chunks.json] [--force]

The work is in hosted/scripts/render_pages.py, where Vercel's build can reach
it (the build runs from hosted/ only); this wrapper runs it from the repo root
like the other prototype tools. It needs pymupdf, which requirements.txt has.
"""

import importlib.util
import sys

from prototype import HOSTED_DIR

_SCRIPT = HOSTED_DIR / "scripts" / "render_pages.py"


def _load():
    # By path rather than `import render_pages`: hosted/scripts is not a package,
    # and a module named render_pages would shadow this one on sys.path.
    spec = importlib.util.spec_from_file_location("hosted_render_pages", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    return _load().main(argv)


if __name__ == "__main__":
    sys.exit(main())
