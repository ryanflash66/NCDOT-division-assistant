"""Report the pages with no text, or little of it, in the index (DAR-658).

    python -m prototype.no_text_pages --index <scratch>/index-tmsd [--index ...] [--out docs/no-text-pages.md]

The corpus audit (.handoff/redo-nov4/corpus-audit.json: every page of the 60
PDFs with its raw text-layer character count and image count) gives two lists
against the committed index (--baseline, default hosted/index):

- image-only pages: images, under 10 characters of text layer, not "intentionally
  left blank", and no indexed text in the baseline;
- text-loss pages: 200+ characters of text layer of which the baseline indexes
  under half (rotated text layers, tables pymupdf4llm drops).

Each page is then looked up in the new index(es) (--index; a later one wins
for the divisions it holds; a division in none of them is reported as not
rebuilt). A page is "fixed" when it has indexed text now (20+ characters for an
image-only page, half its text layer for a text-loss page); otherwise the
report gives the reason, from NOTES (pages looked at by hand) or from the
build. Figure chunks repeat a page's text, so only text chunks are counted.
It also lists pages that had text in the baseline and have none now, which a
rebuild must not produce.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from prototype import HOSTED_DIR

REPO = HOSTED_DIR.parent
DEFAULT_AUDIT = REPO / ".handoff" / "redo-nov4" / "corpus-audit.json"
DEFAULT_OUT = REPO / "docs" / "no-text-pages.md"
IMAGE_ONLY_CHARS = 10
FIXED_IMAGE_CHARS = 20
TEXT_LOSS_MIN_CHARS = 200
TEXT_LOSS_SHARE = 0.5

Key = Tuple[str, str, int]  # (division, source, page)

# Pages looked at by hand: why they still have no (or little) indexed text.
NOTES: Dict[Tuple[str, int], str] = {
    ("utilities/010604.pdf", 4): "blank scanned page (a white page image; nothing to read)",
    ("utilities/010604.pdf", 238): "blank scanned page (OCR reads one digit at 0.53 confidence)",
    ("utilities/010604.pdf", 308): "blank scanned page (a white page image; nothing to read)",
    ("utilities/010604.pdf", 314): "blank scanned page (a white page image; nothing to read)",
    ("utilities/010604.pdf", 315): "blank scanned page (a white page image; nothing to read)",
    ("wztc/Chapter_5.pdf", 14): "photo page: OCR reads only the running header and the sign 'SHOULDER CLOSED AHEAD'",
    ("utilities/20220713 NCDOT UAM Ver 2-0.pdf", 286): "map legend printed sideways: a rotated text layer pymupdf4llm drops; "
                                                     "text-layer fix, not OCR (no OCR runs on a page with a text layer)",
    ("tmsd/Policy on Access Manual.pdf", 83): "appeal checklist form: the blanks and check boxes are dropped, the "
                                             "questions are indexed",
    ("tmsd/fhwa_hop_08_024.pdf", 219): "table with rotated header text (216 rotated characters); text-layer fix, not OCR",
    ("tmsd/fhwa_hop_08_024.pdf", 230): "table with rotated header text (408 rotated characters); text-layer fix, not OCR",
    ("tmsd/fhwa_hop_08_024.pdf", 233): "table with rotated header text (453 rotated characters); text-layer fix, not OCR",
}


def page_text(chunks: List[Dict]) -> Dict[Key, int]:
    """Indexed characters per page, text chunks only."""
    out: Dict[Key, int] = defaultdict(int)
    for c in chunks:
        if c.get("kind") != "figure" and isinstance(c.get("page"), int):
            out[(c["division"], c["source"], c["page"])] += len(c["text"].strip())
    return out


def page_flags(chunks: List[Dict]) -> Dict[Key, List[str]]:
    out: Dict[Key, List[str]] = defaultdict(list)
    for c in chunks:
        for flag in c.get("flags") or []:
            key = (c["division"], c["source"], c["page"])
            if flag not in out[key]:
                out[key].append(flag)
    return out


def _chunks(index_dir: Path) -> List[Dict]:
    data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
    return data["chunks"] if isinstance(data, dict) else data


def report(audit: Dict, baseline: List[Dict], new: List[List[Dict]], listed: Optional[set] = None) -> Dict:
    """The two page lists with each page's status, plus pages that lost all their text.

    `listed` holds the "<division>/<file>" names divisions.py loads; the audit
    also covers PDFs fetched but not loaded (the Revised Rumble Strip
    Guidelines), which no build reads, so they are left out when it's given.
    """
    before = page_text(baseline)
    after: Dict[Key, int] = {}
    flags: Dict[Key, List[str]] = {}
    rebuilt = set()
    for chunks in new:
        divisions = {c["division"] for c in chunks}
        rebuilt |= divisions
        after = {k: v for k, v in after.items() if k[0] not in divisions}
        after.update(page_text(chunks))
        flags = {k: v for k, v in flags.items() if k[0] not in divisions}
        flags.update(page_flags(chunks))
    rows: Dict[str, List[Dict]] = {"image_only": [], "text_loss": []}
    for name, entry in audit.items():
        if listed is not None and name not in listed:
            continue
        division, source = name.split("/", 1)
        for p in entry["pages"]:
            key = (division, source, p["i"])
            had = before.get(key, 0)
            kind = None
            if p["imgs"] > 0 and p["chars"] < IMAGE_ONLY_CHARS and not p.get("blank") and had == 0:
                kind, needed = "image_only", FIXED_IMAGE_CHARS
            elif p["chars"] >= TEXT_LOSS_MIN_CHARS and had < TEXT_LOSS_SHARE * p["chars"]:
                kind, needed = "text_loss", TEXT_LOSS_SHARE * p["chars"]
            if kind is None:
                continue
            now: Optional[int] = after.get(key, 0) if division in rebuilt else None
            fixed = now is not None and now >= needed
            if fixed:
                reason = ""
            elif now is None:
                reason = "; ".join(x for x in ["division not rebuilt in this run", NOTES.get((name, p["i"]))] if x)
            else:
                reason = NOTES.get((name, p["i"]), "OCR found no usable text" if kind == "image_only" else "text still lost")
            rows[kind].append({
                "division": division, "source": source, "page": p["i"], "layer_chars": p["chars"],
                "images": p["imgs"], "rotated_chars": p.get("rotchars", 0), "before": had, "after": now,
                "status": "fixed" if fixed else ("not rebuilt" if now is None else "not fixed"),
                "reason": reason, "flags": flags.get(key, []),
            })
    lost = sorted(k for k, v in before.items() if k[0] in rebuilt and v > 0 and after.get(k, 0) == 0)
    return {**rows, "lost": [{"division": d, "source": s, "page": p} for d, s, p in lost]}


def markdown(result: Dict, indexes: List[str], skipped: Sequence[str] = ()) -> str:
    def table(rows: List[Dict]) -> List[str]:
        out = ["| Document | PDF page | Text layer (chars) | Images | Indexed before | Indexed now | Status | Reason / flags |",
               "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            note = "; ".join(x for x in [r["reason"], ", ".join(r["flags"])] if x)
            now = "-" if r["after"] is None else r["after"]
            out.append(f"| {r['division']}/{r['source']} | {r['page']} | {r['layer_chars']} | {r['images']} | "
                       f"{r['before']} | {now} | {r['status']} | {note} |")
        return out

    def counts(rows: List[Dict]) -> str:
        n = defaultdict(int)
        for r in rows:
            n[r["status"]] += 1
        return ", ".join(f"{v} {k}" for k, v in sorted(n.items())) or "none"

    lines = [
        "# Pages with no text in the index (DAR-658)",
        "",
        "Written by `python -m prototype.no_text_pages`. Pages come from the corpus audit",
        "(`.handoff/redo-nov4/corpus-audit.json`) checked against the committed index; \"indexed now\"",
        f"is from {', '.join(f'`{i}`' for i in indexes)}. Counts are characters of text-chunk text on the page",
        "(figure chunks excluded). \"Not rebuilt\" pages are in divisions this run didn't rebuild;",
        "rerun after the full rebuild.",
        "",
        f"## Image-only pages ({len(result['image_only'])}: {counts(result['image_only'])})",
        "",
        f"Images, under {IMAGE_ONLY_CHARS} characters of text layer, not \"intentionally left blank\", and no indexed text before.",
        "",
        *table(result["image_only"]),
        "",
        f"## Text-loss pages ({len(result['text_loss'])}: {counts(result['text_loss'])})",
        "",
        f"{TEXT_LOSS_MIN_CHARS}+ characters of text layer, under {TEXT_LOSS_SHARE:.0%} of them indexed before.",
        "",
        *table(result["text_loss"]),
        "",
        f"## Pages that lost all their text ({len(result['lost'])})",
        "",
    ]
    lines += [f"- {r['division']}/{r['source']} p. {r['page']}" for r in result["lost"]] or ["None."]
    if skipped:
        lines += ["", f"## Audited PDFs no division loads ({len(skipped)})", "",
                  "Their pages are left out above: no build reads them. The scanned ones read cleanly with",
                  "`--ocr` (the Revised Rumble Strip Guidelines memo at 0.99 confidence, the Work Zone Safety",
                  "and Mobility Policy at 0.98-0.99), so adding them to divisions.py is enough.", ""]
        lines += [f"- {name}" for name in skipped]
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.no_text_pages", description=__doc__.splitlines()[0])
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help=f"corpus audit JSON (default {DEFAULT_AUDIT})")
    parser.add_argument("--baseline", type=Path, default=HOSTED_DIR / "index", help="index the lists are drawn from (default hosted/index)")
    parser.add_argument("--index", type=Path, action="append", required=True, help="rebuilt index directory (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Markdown report (default {DEFAULT_OUT})")
    parser.add_argument("--json", type=Path, help="also write the rows as JSON here")
    args = parser.parse_args(argv)

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    from divrag.divisions import DIVISIONS

    listed = {f"{d.id}/{doc.file}" for d in DIVISIONS for doc in d.documents}
    skipped = sorted(set(audit) - listed)
    if skipped:
        print(f"not in any division (skipped): {', '.join(skipped)}")
    result = report(audit, _chunks(args.baseline), [_chunks(i) for i in args.index], listed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown(result, [i.name for i in args.index], skipped), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for kind in ("image_only", "text_loss"):
        fixed = sum(r["status"] == "fixed" for r in result[kind])
        print(f"{kind}: {len(result[kind])} pages, {fixed} fixed")
    print(f"pages that lost all their text: {len(result['lost'])}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
