"""Extract the bake-off pages with one candidate tool and record what it read (DAR-656).

    # once, in .venv: one single-page PDF per selected page, plus the text layer
    .venv\\Scripts\\python -m prototype.bakeoff.run --candidate textlayer --out <dir> --documents hosted/documents
    .venv\\Scripts\\python -m prototype.bakeoff.run --candidate pymupdf4llm --out <dir>
    <docling venv>\\Scripts\\python -m prototype.bakeoff.run --candidate docling --out <dir>
    <mineru venv>\\Scripts\\python -m prototype.bakeoff.run --candidate mineru --out <dir> [--limit 40]

Candidates:
  textlayer    pymupdf `page.get_text()`: the reference the other tools are
               compared with (ground truth for numbers on every page with a text layer)
  pymupdf4llm  the current reader: rag.loader's pymupdf4llm call with RapidOCR on
               (as `prototype.ingest --ocr`), then the same markup and table cleanup
  docling      Docling, table structure on, RapidOCR with lang=en and
               detect_orientation on (its default language is Simplified Chinese,
               which is what the DAR-651 comparison ran with)
  mineru       MinerU's in-process analyzer (`doc_analyze`, effort "medium" =
               its local layout/OCR/table models, no VLM; --effort high adds its
               1.2B VLM through llama.cpp), rendered to Markdown. In process, so its
               local server, CLI telemetry and the --remote mineru.net service are never used.

Each page is read from its own single-page PDF (<out>/pages/NNN.pdf), so the
seconds are that page's, and every tool sees the same bytes. The first page is
read once before timing starts, so model loading is reported apart
(<out>/<label>.meta.json). Output: <out>/<label>.jsonl, one row per page
{id, text, seconds, cpu_seconds, error}: `seconds` is wall time, `cpu_seconds`
the process's CPU time over all its threads, which other jobs sharing the
machine do not inflate (the bake-off ran beside other index builds); a rerun skips the ids already there, so a slow
candidate can be stopped and resumed, or timed on a subset with --limit/--kind.
"""

import argparse
import importlib.metadata as metadata
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

PAGES = Path(__file__).resolve().with_name("pages.json")
REPO = Path(__file__).resolve().parents[2]

Reader = Callable[[Path], str]


def page_file(out: Path, index: int) -> Path:
    return out / "pages" / f"{index:03d}.pdf"


def check_split(rows: List[Dict], out: Path) -> bool:
    """True when <out>/pages holds exactly these pages. The files are numbered by
    position, so a work folder made from an older pages.json must not be reused."""
    manifest = out / "pages" / "ids.json"
    if not manifest.exists():
        return False
    if json.loads(manifest.read_text(encoding="utf-8")) != [r["id"] for r in rows]:
        raise SystemExit(f"{out} was split from a different pages.json; use a new --out folder")
    return True


def split_pages(rows: List[Dict], documents: Path, out: Path) -> None:
    """Copy each selected page into its own PDF (needs pymupdf, i.e. .venv)."""
    import pymupdf

    (out / "pages").mkdir(parents=True, exist_ok=True)
    if any((out / "pages").glob("*.pdf")) and not (out / "pages" / "ids.json").exists():
        raise SystemExit(f"{out / 'pages'} has page files but no ids.json; use a new --out folder")
    opened: Dict[str, "pymupdf.Document"] = {}
    try:
        for index, row in enumerate(rows):
            target = page_file(out, index)
            if target.exists():
                continue
            key = f"{row['division']}/{row['source']}"
            if key not in opened:
                opened[key] = pymupdf.open(documents / row["division"] / row["source"])
            with pymupdf.open() as single:
                single.insert_pdf(opened[key], from_page=row["page"] - 1, to_page=row["page"] - 1)
                single.save(target, garbage=3, deflate=True)
    finally:
        for doc in opened.values():
            doc.close()
    (out / "pages" / "ids.json").write_text(json.dumps([r["id"] for r in rows]), encoding="utf-8")


def _textlayer(_options: argparse.Namespace) -> Reader:
    import pymupdf

    def read(path: Path) -> str:
        with pymupdf.open(path) as doc:
            return doc[0].get_text()

    return read


def _pymupdf4llm(_options: argparse.Namespace) -> Reader:
    sys.path.insert(0, str(REPO))
    from rag.loader import _PdfMarkdownReader

    reader = _PdfMarkdownReader(ocr=True)  # the reader `prototype.ingest --ocr` uses, so it cannot drift

    def read(path: Path) -> str:
        return "\n".join(doc.text for doc in reader.load_data(path))

    return read


def _docling(_options: argparse.Namespace) -> Reader:
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    ocr = RapidOcrOptions(lang=["en"], detect_orientation=True)
    # Docling's default of 4 threads, stated so the run is reproducible. 16 threads was
    # tried: with other index builds holding the CPU it spent 122 s of wall time on a
    # one-line page that took 4 s at 4 threads, so compare tools on cpu_seconds.
    accelerator = AcceleratorOptions(device="cpu", num_threads=4)
    options = PdfPipelineOptions(do_ocr=True, do_table_structure=True, ocr_options=ocr,
                                 accelerator_options=accelerator)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})

    def read(path: Path) -> str:
        return converter.convert(path).document.export_to_markdown()

    return read


def _mineru(options: argparse.Namespace) -> Reader:
    # CPU only, like the index build: on Windows MinerU picks DirectML by itself when it
    # finds a GPU (it found the dev machine's RTX 5070) and writes that choice to
    # ~/.mineru/config.yaml; the environment overrides the file.
    os.environ.setdefault("MINERU_MODEL_ONNX_DEVICE", "cpu")
    os.environ.setdefault("MINERU_DEVICE_MODE", "cpu")
    from mineru.backend.analyze import doc_analyze
    from mineru.render.markdown import render_markdown

    def read(path: Path) -> str:
        middle, _model = doc_analyze(path.read_bytes(), effort=options.effort, parse_mode="auto")
        # Pictures come back inlined as base64 data URIs (over 1 MB on a drawing page); keep the alt text.
        return re.sub(r"!\[([^\]]*)\]\(data:[^)]*\)", r"![\1](image)", render_markdown(middle))

    return read


CANDIDATES: Dict[str, Callable[[argparse.Namespace], Reader]] = {
    "textlayer": _textlayer, "pymupdf4llm": _pymupdf4llm, "docling": _docling, "mineru": _mineru,
}
# Distributions whose installed files (with their dependencies) make up each candidate's install size.
ROOT_DISTRIBUTIONS = {
    "textlayer": ["pymupdf"],
    "pymupdf4llm": ["pymupdf4llm", "pymupdf-layout", "rapidocr", "onnxruntime"],
    "docling": ["docling", "rapidocr", "onnxruntime"],
    "mineru": ["mineru"],
}
# Model caches outside site-packages, by name fragment (Hugging Face hub and ModelScope layouts).
MODEL_HINTS = {"docling": ["docling", "rapidocr"], "mineru": ["mineru", "opendatalab", "pdf-extract"]}


_REQUIREMENT = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")
_EXTRA_MARKER = re.compile(r"extra\s*==\s*['\"]([^'\"]+)['\"]")


def _requirement(spec: str, extras: Set[str]) -> Optional[Tuple[str, Set[str]]]:
    """(name, extras it asks for) of a requirement line, or None when it belongs to an
    extra nobody asked for. docling pulls everything through "docling-slim[standard]"."""
    marker = _EXTRA_MARKER.search(spec.split(";", 1)[1]) if ";" in spec else None
    if marker and marker.group(1) not in extras:
        return None
    m = _REQUIREMENT.match(spec)
    if not m:
        return None
    return m.group(1), {e.strip() for e in (m.group(2) or "").split(",") if e.strip()}


def install_mb(roots: Iterable[str]) -> float:
    """Size on disk of these distributions and everything they require, in MB."""
    seen: Set[Tuple[str, str]] = set()
    counted: Set[str] = set()
    todo: List[Tuple[str, Set[str]]] = [(r, set()) for r in roots]
    total = 0
    while todo:
        name, extras = todo.pop()
        name = name.lower().replace("_", "-")
        if (name, ",".join(sorted(extras))) in seen:
            continue
        seen.add((name, ",".join(sorted(extras))))
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        if name not in counted:
            counted.add(name)
            for f in dist.files or []:
                try:
                    total += Path(dist.locate_file(f)).stat().st_size
                except OSError:
                    pass
        todo += [r for r in (_requirement(spec, extras) for spec in dist.requires or []) if r]
    return round(total / 1e6, 1)


def _dir_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def model_cache_mb(hints: List[str]) -> Dict[str, float]:
    """Model folders a candidate downloaded on first use, found by name in the usual caches."""
    home = Path.home()
    roots = [Path(os.environ.get("HF_HOME", home / ".cache" / "huggingface")) / "hub",
             home / ".cache" / "modelscope" / "hub", home / ".cache" / "modelscope" / "hub" / "models",
             home / ".cache" / "docling", home / ".mineru" / "models"]
    found: Dict[str, float] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and any(h in child.name.lower() for h in hints):
                found[str(child)] = round(_dir_mb(child), 1)
    return found


def _version(candidate: str) -> Dict[str, str]:
    out = {}
    for name in ROOT_DISTRIBUTIONS[candidate]:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return out


def _done(path: Path) -> Set[str]:
    """Ids already read without an error; a page that failed is tried again on a rerun
    (report.py keeps the last row written for an id)."""
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = {row["id"]: row for row in rows}
    return {i for i, row in last.items() if not row.get("error")}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--label", help="output name (default: the candidate, plus the effort for mineru)")
    parser.add_argument("--out", type=Path, required=True, help="work folder shared by all candidates")
    parser.add_argument("--pages", type=Path, default=PAGES)
    parser.add_argument("--documents", type=Path, default=REPO / "hosted" / "documents")
    parser.add_argument("--effort", default="medium", choices=["flash", "medium", "high", "xhigh"],
                        help="mineru only")
    parser.add_argument("--limit", type=int, help="read at most this many pages (timing subset)")
    parser.add_argument("--kind", action="append", help="only pages of this kind (repeatable)")
    parser.add_argument("--sample", type=int,
                        help="only this many pages, spread evenly over the list (every kind), for timing a slow tool")
    args = parser.parse_args(argv)

    rows = json.loads(args.pages.read_text(encoding="utf-8"))
    if not check_split(rows, args.out):
        split_pages(rows, args.documents, args.out)
    label = args.label or (f"mineru-{args.effort}" if args.candidate == "mineru" else args.candidate)
    out_path = args.out / f"{label}.jsonl"
    if args.sample:
        step = max(1, len(rows) / args.sample)
        rows_in = {int(k * step) for k in range(args.sample) if int(k * step) < len(rows)}
    else:
        rows_in = set(range(len(rows)))
    done = _done(out_path)
    wanted = [(i, r) for i, r in enumerate(rows) if i in rows_in and (not args.kind or r["kind"] in args.kind)]
    todo = [(i, r) for i, r in wanted if r["id"] not in done]
    if args.limit is not None:
        # --limit caps the pages read in this selection, counting those an earlier run already read.
        todo = todo[: max(0, args.limit - (len(wanted) - len(todo)))]
    if not todo:
        print(f"{label}: nothing left to read in {out_path}")
        return 0  # keep the meta (load and warm-up times) of the run that read the pages

    started = time.perf_counter()
    read = CANDIDATES[args.candidate](args)
    load_seconds = time.perf_counter() - started
    warm = time.perf_counter()
    try:
        read(page_file(args.out, todo[0][0]))  # first-call model loading, not counted per page
    except Exception as exc:  # noqa: BLE001 - recorded on the page itself below
        print(f"warm-up failed: {exc!r}", file=sys.stderr)
    warm_seconds = time.perf_counter() - warm
    print(f"{label}: loaded in {load_seconds:.1f}s, warm-up {warm_seconds:.1f}s, {len(todo)} pages to read", flush=True)

    with out_path.open("a", encoding="utf-8") as sink:
        for n, (index, row) in enumerate(todo, 1):
            t0, c0 = time.perf_counter(), time.process_time()
            text, error = "", None
            try:
                text = read(page_file(args.out, index))
            except Exception as exc:  # noqa: BLE001 - a page a tool cannot read is a result
                error = repr(exc)[:500]
            seconds = round(time.perf_counter() - t0, 3)
            cpu_seconds = round(time.process_time() - c0, 3)
            sink.write(json.dumps({"id": row["id"], "text": text, "seconds": seconds, "cpu_seconds": cpu_seconds,
                                   "error": error}) + "\n")
            sink.flush()
            if n % 10 == 0 or error:
                print(f"  {n}/{len(todo)} {row['id']} {seconds:.1f}s{' ERROR ' + error if error else ''}", flush=True)

    meta = {
        "candidate": args.candidate, "label": label, "versions": _version(args.candidate),
        "python": platform.python_version(), "machine": platform.processor(), "cpus": os.cpu_count(),
        "load_seconds": round(load_seconds, 1), "warmup_seconds": round(warm_seconds, 1),
        "install_mb": install_mb(ROOT_DISTRIBUTIONS[args.candidate]),
        "model_cache_mb": {k: v for k, v in model_cache_mb(MODEL_HINTS.get(args.candidate, [])).items()
                           # The 1.2B VLM (GGUF) is only loaded at effort high/xhigh.
                           if not (args.candidate == "mineru" and "gguf" in k.lower()
                                   and args.effort not in ("high", "xhigh"))},
        "effort": args.effort if args.candidate == "mineru" else None,
    }
    (args.out / f"{label}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"{label}: {len(_done(out_path))} pages in {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
