"""FastAPI router for document ingestion and ChromaDB-backed retrieval.

Endpoints
---------
POST /api/ingest  -- upload files into the data directory and refresh the index.
                     Needs `Authorization: Bearer <RAG_API_KEY>`.
POST /api/query   -- retrieve relevant chunks from the index without LLM generation.

Dependencies (get_config, get_index) can be swapped with
app.dependency_overrides, which is how the tests isolate each run.
"""

import hmac
import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from rag import loader
from rag.config import AppConfig, load_config
from rag.index import EmptyIndexError, NoDocumentsError, RetrievalIndex, make_embed_model, make_reranker
from rag.staging import UploadRejected, stage

_indexes: Dict[AppConfig, RetrievalIndex] = {}
_indexes_lock = threading.Lock()
_ingest_lock = threading.Lock()


def get_config() -> AppConfig:
    return load_config()


def get_index(config: AppConfig = Depends(get_config)) -> RetrievalIndex:
    with _indexes_lock:
        index = _indexes.get(config)
        if index is None:
            index = RetrievalIndex(config, make_embed_model(config), make_reranker(config))
            index.ensure_built()
            _indexes[config] = index
        return index


_bearer = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    config: AppConfig = Depends(get_config),
) -> None:
    """Refuse the caller unless it sends `Authorization: Bearer <RAG_API_KEY>`.

    Ingest overwrites files in data/ and rebuilds the whole index, and nothing
    else checked who was calling. With RAG_API_KEY unset every call is refused,
    so a server started without the setting can't be written to.
    """
    if not config.api_key:
        raise HTTPException(status_code=403, detail="Ingest is turned off: set RAG_API_KEY to enable it.")
    sent = credentials.credentials if credentials else ""
    if not hmac.compare_digest(sent.encode(), config.api_key.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or wrong API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    top_k: int = 4
    where: Optional[Dict[str, str]] = None


class SourceNode(BaseModel):
    text: str
    source: Optional[str] = None
    score: Optional[float] = None
    topic: Optional[str] = None
    doc_domain: Optional[str] = None
    page: Optional[str] = None
    section: Optional[str] = None


def _optional_label(value) -> Optional[str]:
    """A metadata label as a string, or None when it is missing or the "N/A" placeholder."""
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text == "N/A" else text


class QueryResponse(BaseModel):
    query: str
    results: List[SourceNode]


class IngestResponse(BaseModel):
    success: bool
    indexed_docs: int
    vector_count: int
    collection: str
    message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api")


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_api_key)])
def ingest_documents(
    files: List[UploadFile] = File(...),
    index: RetrievalIndex = Depends(get_index),
):
    """Save uploaded files to the data directory and refresh the index.

    The whole batch is validated first. If the refresh fails, the uploads are
    removed and any files they replaced are restored.
    """
    try:
        staged = stage(
            index.config.data_dir,
            ((upload.filename, upload.file.read()) for upload in files),
            loader.supported_extensions(),
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with _ingest_lock:
        try:
            with staged:
                stats = index.refresh()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(
        success=True,
        indexed_docs=stats.documents,
        vector_count=stats.vectors,
        collection=stats.collection,
        message=f"Saved {len(staged.filenames)} file(s) and rebuilt collection '{stats.collection}'.",
    )


@router.post("/query", response_model=QueryResponse)
def query_rag(body: QueryRequest, index: RetrievalIndex = Depends(get_index)):
    """Retrieve the top-k most relevant chunks for a query.

    Read-only: this never rebuilds the index. Optional `where` filters on
    Document classification fields, e.g. {"topic": "work_zone"}.

    Each result carries `page` (the PDF page label the chunk came from) and
    `section` (the heading it sits under) when the source records them;
    both are null otherwise.
    """
    try:
        hits = index.retrieve(body.query, k=body.top_k, where=body.where)
    except (EmptyIndexError, NoDocumentsError) as exc:
        raise HTTPException(status_code=503, detail=f"Index unavailable: {exc}")

    return QueryResponse(
        query=body.query,
        results=[
            SourceNode(
                text=hit.text,
                source=hit.source,
                score=hit.score,
                topic=hit.metadata.get("topic"),
                doc_domain=hit.metadata.get("doc_domain"),
                page=_optional_label(hit.metadata.get("page_label")),
                section=_optional_label(hit.metadata.get("section")),
            )
            for hit in hits
        ],
    )
