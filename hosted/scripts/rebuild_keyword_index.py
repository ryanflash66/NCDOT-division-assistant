"""Rebuild hosted/index/bm25.npz from the committed chunks, without re-embedding anything.

The keyword index is built from chunks.json alone (no PDFs, no models), so a
change to the tokenizer or the caption/ID field (divrag/keyword.py,
divrag/index_file.field_text) needs only this, not a full prototype.ingest run:

    python hosted/scripts/rebuild_keyword_index.py [index_dir]      (default: hosted/index)

Only bm25.npz is written; chunks.json and vectors.npy are left as they are.
"""

import sys
import time
from pathlib import Path

HOSTED_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOSTED_DIR))

from divrag.index_file import IndexFile  # noqa: E402
from divrag.keyword import KEYWORD_FILE  # noqa: E402


def main(argv) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else HOSTED_DIR / "index"
    started = time.perf_counter()
    index = IndexFile.load(directory).with_keyword_index()
    index.keyword.save(directory)
    print(f"wrote {directory / KEYWORD_FILE}: {len(index.chunks)} chunks, {len(index.keyword.body.terms)} body terms, "
          f"{len(index.keyword.field.terms)} field terms, {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
