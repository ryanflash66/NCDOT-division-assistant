"""Download the embedding and reranking models into a fastembed cache directory.

Vercel runs this as the Build Command (hosted/vercel.json), so the files land in
hosted/models/ and ship inside the function bundle. embedder.model_cache_dir()
finds that directory, and a cold start reads the models from disk instead of
downloading about 90 MB from Hugging Face on the first question.

It uses the standard library only, so it runs on whichever Python the build
image puts on PATH. It writes the Hugging Face cache layout that fastembed reads:

    <cache>/models--Qdrant--bge-small-en-v1.5-onnx-Q/refs/main            commit sha
    <cache>/models--Qdrant--bge-small-en-v1.5-onnx-Q/snapshots/<sha>/...  the files

The files are plain files rather than the hub's symlinks into blobs/, so the
bundle holds one copy of each.

    python scripts/fetch_models.py [cache_dir] [--rerank-model NAME] [--rerank-model-file FILE]

cache_dir defaults to hosted/models. The reranker defaults to RERANK_MODEL and
RERANK_MODEL_FILE from the environment (Vercel gives the build the project's
variables), else the pinned MiniLM below, so the bundle ships the model the
function will load. "none" fetches the embedding model only.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

HUB = "https://huggingface.co"

# The Hugging Face source and model file for each model the demo uses
# (divrag.embedder.MODEL_NAME, and RERANK_MODEL_NAME with RERANK_MODEL_FILE),
# pinned to a commit so every build ships the same files.
# tests/test_fetch_models.py checks these against divrag.embedder and fastembed.
MODELS = (
    {"repo": "Qdrant/bge-small-en-v1.5-onnx-Q", "revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
     "model_file": "model_optimized.onnx"},
    {"repo": "Xenova/ms-marco-MiniLM-L-6-v2", "revision": "a09144355adeed5f58c8ed011d209bf8ee5a1fec",
     "model_file": "onnx/model_quantized.onnx"},
)
# Kept equal to divrag.embedder.RERANK_MODEL_NAME and divrag.config.NO_RERANKER (this
# script runs before the app's dependencies are importable).
DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
NO_RERANKER = "none"
MAX_MODELS_MB = 220  # 500 MB limit - about 280 MB of the bundle that is not models

# The cross-encoders fastembed 0.9 can load (divrag.embedder.known_cross_encoders), with
# the hub repo and ONNX file it reads for each: the script has no fastembed to ask, and
# tests/test_hosted_rerank.py checks this table against fastembed's list. Another file of
# the same repo (RERANK_MODEL_FILE, as the int8 MiniLM file above) is fetched from the
# same repo. These are fetched at the repo's current main, not a pinned commit.
CROSS_ENCODERS = {
    "Xenova/ms-marco-MiniLM-L-6-v2": ("Xenova/ms-marco-MiniLM-L-6-v2", "onnx/model.onnx"),
    "Xenova/ms-marco-MiniLM-L-12-v2": ("Xenova/ms-marco-MiniLM-L-12-v2", "onnx/model.onnx"),
    "BAAI/bge-reranker-base": ("BAAI/bge-reranker-base", "onnx/model.onnx"),
    "BAAI/bge-reranker-v2-m3": ("onnx-community/bge-reranker-v2-m3-ONNX", "onnx/model.onnx"),
    "BAAI/bge-reranker-v2-m3-int8": ("onnx-community/bge-reranker-v2-m3-ONNX", "onnx/model_int8.onnx"),
    "jinaai/jina-reranker-v1-tiny-en": ("jinaai/jina-reranker-v1-tiny-en", "onnx/model.onnx"),
    "jinaai/jina-reranker-v1-turbo-en": ("jinaai/jina-reranker-v1-turbo-en", "onnx/model.onnx"),
    "jinaai/jina-reranker-v2-base-multilingual": ("jinaai/jina-reranker-v2-base-multilingual", "onnx/model.onnx"),
}

# The tokenizer and config files fastembed asks the hub for, besides the model file.
SUPPORT_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json",
                 "special_tokens_map.json", "preprocessor_config.json")

DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "models"


def models_to_fetch(rerank_model: str = DEFAULT_RERANKER, model_file: Optional[str] = None) -> List[Dict[str, str]]:
    """The embedding model and the reranker to fetch: the pinned pair by default."""
    embedding, pinned = MODELS
    if rerank_model.strip().lower() == NO_RERANKER:  # as config.load_settings reads it
        return [embedding]
    if rerank_model == DEFAULT_RERANKER and model_file in (None, pinned["model_file"]):
        return [embedding, pinned]
    if rerank_model not in CROSS_ENCODERS:
        raise ValueError(f"unknown reranker {rerank_model!r}; one of {NO_RERANKER}, {', '.join(CROSS_ENCODERS)}")
    repo, listed_file = CROSS_ENCODERS[rerank_model]
    return [embedding, {"repo": repo, "revision": "main", "model_file": model_file or listed_file}]


def repo_folder(repo: str) -> str:
    """The hub's cache folder name for a model repo."""
    return "models--" + repo.replace("/", "--")


def _get(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
        return response.read()


def _download(url: str, dest: Path, size: Optional[int], timeout: float = 300) -> None:
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=timeout) as response, open(part, "wb") as out:  # noqa: S310
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
    if size is not None and part.stat().st_size != size:
        raise IOError(f"{dest.name}: got {part.stat().st_size} bytes, expected {size}")
    part.replace(dest)


def _with_retries(action: Callable[[], object], what: str, attempts: int = 3) -> object:
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - network errors of every kind get retried
            if attempt == attempts:
                raise
            print(f"  {what} failed ({exc}); retrying", flush=True)
            time.sleep(2 * attempt)
    return None


def files_to_fetch(model: Dict[str, str], siblings: List[Dict]) -> Dict[str, Optional[int]]:
    """The repo files fastembed needs, with their sizes, from the hub's file list."""
    wanted = set(SUPPORT_FILES) | {model["model_file"]}
    # A large ONNX file keeps its weights beside it (onnx/model.onnx_data); onnxruntime needs both.
    data = model["model_file"] + "_data"
    files = {s["rfilename"]: s.get("size") for s in siblings
             if s["rfilename"] in wanted or s["rfilename"].startswith(data)}
    if model["model_file"] not in files:
        raise ValueError(f"{model['repo']}@{model['revision']} has no {model['model_file']}")
    return files


def fetch_model(model: Dict[str, str], cache_dir: Path,
                get: Callable[[str], bytes] = _get,
                download: Callable[[str, Path, Optional[int]], None] = _download) -> Path:
    """Fetch one model into cache_dir (skipping files already there) and return its snapshot dir."""
    repo, revision = model["repo"], model["revision"]
    info = json.loads(_with_retries(lambda: get(f"{HUB}/api/models/{repo}/revision/{revision}?blobs=true"),
                                    f"{repo} file list"))
    revision = info.get("sha") or revision  # a branch name ("main") becomes the commit it points at
    files = files_to_fetch(model, info.get("siblings", []))
    root = cache_dir / repo_folder(repo)
    snapshot = root / "snapshots" / revision
    for name, size in sorted(files.items()):
        dest = snapshot / name
        if dest.is_file() and (size is None or dest.stat().st_size == size):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  {repo}/{name} ({(size or 0) / 1e6:.1f} MB)", flush=True)
        _with_retries(lambda: download(f"{HUB}/{repo}/resolve/{revision}/{name}", dest, size), name)
    (root / "refs").mkdir(parents=True, exist_ok=True)
    (root / "refs" / "main").write_text(revision)
    return snapshot


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache_dir", nargs="?", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--rerank-model", default=os.environ.get("RERANK_MODEL", "").strip() or DEFAULT_RERANKER,
                        help=f"a cross-encoder name or {NO_RERANKER} (default: $RERANK_MODEL, else {DEFAULT_RERANKER})")
    parser.add_argument("--rerank-model-file", default=os.environ.get("RERANK_MODEL_FILE", "").strip() or None,
                        help="an ONNX file of the model's repo (default: $RERANK_MODEL_FILE, else the model's usual file)")
    args = parser.parse_args(argv[1:])
    if os.environ.get("RERANK", "on").strip().lower() in ("off", "0", "false"):
        args.rerank_model = NO_RERANKER  # the app won't load one, so the bundle doesn't carry one
    cache_dir = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    for model in models_to_fetch(args.rerank_model, args.rerank_model_file):
        print(f"Fetching {model['repo']} into {cache_dir}", flush=True)
        fetch_model(model, cache_dir)
    total = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
    print(f"Models ready in {cache_dir}: {total / 1e6:.0f} MB in {time.perf_counter() - started:.1f}s", flush=True)
    if total > MAX_MODELS_MB * 1e6:
        # The function bundle is about 340 MB with the default models (about 60 MB of it)
        # and Vercel's Python limit is 500 MB: a 1 GB reranker would fail the deploy later.
        print(f"Models take {total / 1e6:.0f} MB, over the {MAX_MODELS_MB} MB the bundle has room for; "
              "pick a smaller RERANK_MODEL", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
