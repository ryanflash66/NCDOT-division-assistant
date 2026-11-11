"""Settings for the hosted demo, read once from environment variables.

One key is required: OPENROUTER_API_KEY, or OPENAI_API_KEY with
LLM_PROVIDER=openai. Everything else has a default suitable for the public demo.

    LLM_PROVIDER                "openrouter" (default) or "openai": which service writes the answers.
                                "openai" needs OPENAI_API_KEY; the free OpenRouter models stay behind it
                                (when OPENROUTER_API_KEY is set) and answer whenever OpenAI can't.
    OPENAI_API_KEY              secret; only used with LLM_PROVIDER=openai
    OPENAI_MODEL                the OpenAI model (default gpt-6.1-terra; see DEFAULT_OPENAI_MODEL)
    OPENAI_PRICE_PER_MILLION    "input,output" dollars per million tokens of OPENAI_MODEL (default: spend.PRICES_PER_MILLION;
                                another model needs it, or startup stops)
    OPENAI_MONTHLY_BUDGET_USD   the month's OpenAI budget (default 50, Dr. Namian's limit; see spend.py)
    OPENAI_BUDGET_MARGIN_USD    how far under the budget answers switch to the free models (default 5: at $45)
    KV_REST_API_URL, KV_REST_API_TOKEN   the Upstash Redis store that keeps the month's OpenAI total for every
                                instance (or UPSTASH_REDIS_REST_URL and _TOKEN; read by spend.store_from_env)
    OPENROUTER_API_KEY          secret; never sent to the browser
    OPENROUTER_MODEL            primary model (must end in ":free")
    OPENROUTER_FALLBACK_MODELS  comma-separated backups, tried in order by OpenRouter (":free" only)
    LLM_TEMPERATURE             default 0.1
    LLM_REASONING               "off" (default), "low", "medium" or "high" for reasoning models
    RERANK                      "on" (default) or "off": rerank vector hits with the cross-encoder
    RERANK_MODEL                the cross-encoder (a name fastembed supports, see embedder.known_cross_encoders),
                                or "none" (the same as RERANK=off); default Xenova/ms-marco-MiniLM-L-6-v2
    RERANK_MODEL_FILE           an ONNX file of that model's repo (default: the int8 MiniLM file, else fastembed's)
    RERANK_TEXT_ONLY            "on" (default) or "off": tables keep their fused rank, only text chunks are reranked
    RERANK_BATCH_SIZE           passages per cross-encoder call (default 1; see embedder.RERANK_BATCH_SIZE)
                                RETRY_MIN_SCORE and answer.SUGGEST_THRESHOLD are MiniLM-L-6 logits: another
                                RERANK_MODEL scores on its own scale, so retune them before deploying it.
    KEYWORD_SEARCH              "on" (default) or "off": add the index's keyword (BM25) search to the vector search
    KEYWORD_FIELD               "on" (default) or "off": score the keyword index's caption/ID field as well as the body
    KEYWORD_FIELD_BOOST         how many times the field's score counts next to the body's (default 1.5; see keyword.DEFAULT_FIELD_BOOST)
    KEYWORD_ID_BOOST            how many times more a table, figure or document number the question names counts in the field (default 2)
    RERANK_CANDIDATES          vector hits handed to the reranker (default 40; see retrieval.DEFAULT_CANDIDATES)
    TOP_K                       passages given to the model (default 5)
    PAGE_AGGREGATION            "off" (default), "max" or "sum": rank the reranked chunks by page before the top k
                                (see retrieval.aggregate_pages)
    MAX_CHUNKS_PER_PAGE         chunks one page may give to the top k when PAGE_AGGREGATION is on (default 2)
    MAX_CHUNKS_PER_DOCUMENT     chunks one document may give to the top k after the rerank (default 0: no cap)
    RRF_K                       reciprocal rank fusion constant (default 60; see keyword.fuse)
    FUSION_WEIGHTS              "vector,keyword" multipliers inside the fusion (default "1,1")
    BM25_K1, BM25_B             BM25 parameters (defaults 1.2 and 0.75); they are baked into bm25.npz, so a change
                                takes a rebuild of the index (prototype.ingest)
    MODEL_CACHE_DIR             fastembed model directory (see embedder.model_cache_dir)
    ONNX_THREADS                onnxruntime threads per model (default: onnxruntime's own choice; see embedder.onnx_threads)
    INDEX_DIR                   directory with chunks.json and vectors.npy (default hosted/index)
    MAX_QUESTION_CHARS          default 500
    RATE_LIMIT_PER_MINUTE       questions per client IP per minute, per server instance (default 8)
    REQUEST_BUDGET_SECONDS      total time one question may take, kept under Vercel's 60 s maxDuration (default 55)
    RETRY_ON_REFUSAL            "on" (default) or "off": ask once more when the model refuses although retrieval was strong
    RETRY_MIN_SCORE             top reranker score that counts as strong retrieval (default 1.0)
    RETRY_MIN_SECONDS           retry only if at least this much of the request budget is left (default 15)
    ROW_GUARD                   "off" (default) or "on": flag an answer whose number sits in a table row that lacks a label
                                the question names while another row of that table has it (DAR-664, rowcheck.py)
    ALLOWED_ORIGINS             comma-separated origins allowed to call the API from another site
                                (default none: only the page served by this app can call it)
"""

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .keyword import B, DEFAULT_FIELD_BOOST, DEFAULT_ID_BOOST, K1, RRF_K
from .spend import DEFAULT_BUDGET_USD, DEFAULT_MARGIN_USD, price_for
from .retrieval import (DEFAULT_MAX_CHUNKS_PER_DOCUMENT, DEFAULT_MAX_CHUNKS_PER_PAGE, DEFAULT_PAGE_AGGREGATION,
                        PAGE_AGGREGATION_MODES)

from .embedder import RERANK_BATCH_SIZE, RERANK_MODEL_NAME, default_model_file

HOSTED_DIR = Path(__file__).resolve().parent.parent
NO_RERANKER = "none"

# Free models only, so the public link cannot spend the account's credits.
# Chosen from https://openrouter.ai/api/v1/models on 2026-10-10: Nemotron 3 Ultra
# answered the grounded test prompt correctly in ~2.5 s; Gemma 4 31B was
# rate-limited upstream at the time but is a strong instruction follower when up.
# Nemotron 3 Super, the first fallback until 2026-10-28, stopped being free (404
# "unavailable for free"), so every retry after a refusal failed on it; Nemotron
# 3.5 Super, its successor on the same endpoint, answered a cited test prompt.
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_FALLBACK_MODELS = ("nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it:free")
FREE_SUFFIX = ":free"

# The paid path (DAR-679), used only with LLM_PROVIDER=openai. Picked from OpenAI's model and
# pricing pages on 2026-11-11: gpt-6.1-terra is the mid-priced model ($1 per million input
# tokens, $5 per million output; gpt-6.1-sol is twice that, gpt-6-luna a tenth) and it accepts
# reasoning effort "none", which LLM_REASONING=off sends: no reasoning tokens to pay or wait
# for, and temperature stays settable (gpt-6.1-sol starts at "low"). A question sends about
# 5,000 tokens of passages and gets about 300 back, so one model call is about 0.7 cents and
# a question with every recheck (up to 3 calls) about 2 cents.
DEFAULT_OPENAI_MODEL = "gpt-6.1-terra"
PROVIDERS = ("openrouter", "openai")


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    openai_api_key: Optional[str]
    openai_model: str
    openai_prices: Optional[Tuple[float, float]]  # dollars per million tokens in and out; None for an unknown model
    openai_monthly_budget_usd: float
    openai_budget_margin_usd: float
    openrouter_api_key: Optional[str]
    models: Tuple[str, ...]
    temperature: float
    reasoning: str
    rerank: bool
    rerank_model: str
    rerank_model_file: Optional[str]
    rerank_text_only: bool
    rerank_batch_size: int
    keyword_search: bool
    keyword_field: bool
    keyword_field_boost: float
    keyword_id_boost: float
    rerank_candidates: int
    top_k: int
    page_aggregation: str
    max_chunks_per_page: int
    max_chunks_per_document: int
    rrf_k: int
    fusion_weights: Tuple[float, float]
    bm25_k1: float
    bm25_b: float
    index_dir: Path
    max_question_chars: int
    rate_limit_per_minute: int
    request_budget_seconds: float
    retry_on_refusal: bool
    retry_min_score: float
    retry_min_seconds: float
    allowed_origins: Tuple[str, ...]
    row_guard: bool = False

    @property
    def answers_with_openai(self) -> bool:
        """OpenAI was selected and has its key; without the key the free OpenRouter models answer."""
        return self.llm_provider == "openai" and bool(self.openai_api_key)

    @property
    def answer_models(self) -> Tuple[str, ...]:
        """The models a question can be answered by, in the order they are tried."""
        if not self.answers_with_openai:
            return self.models
        return (self.openai_model,) + (self.models if self.openrouter_api_key else ())

    @property
    def openai_limit_usd(self) -> float:
        """The month's estimated OpenAI spend at which answers switch to the free models (spend.SpendLedger)."""
        return self.openai_monthly_budget_usd - self.openai_budget_margin_usd

    @property
    def llm_configured(self) -> bool:
        return self.answers_with_openai or bool(self.openrouter_api_key)

    def retriever_options(self) -> Dict[str, object]:
        """Retriever's keyword arguments for these settings (index.py's _Runtime builds its Retriever with them)."""
        return dict(candidates=self.rerank_candidates, keyword=self.keyword_search,
                    page_aggregation=self.page_aggregation, max_chunks_per_page=self.max_chunks_per_page,
                    max_chunks_per_document=self.max_chunks_per_document, rrf_k=self.rrf_k,
                    fusion_weights=self.fusion_weights,
                    field_boost=self.keyword_field_boost if self.keyword_field else 0.0,
                    id_boost=self.keyword_id_boost, text_only=self.rerank_text_only)


def _csv(value: str) -> Tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _boost(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value < 0:  # nan would turn every keyword score to nan: no hits at all
        raise ValueError(f"{name} must be a finite number, 0 or more, got {raw!r}")
    return value


def _setting(env: Mapping[str, str], name: str, default: object) -> str:
    """The variable's value, or the default when it is unset or blank (a `BM25_K1=` line left in .env)."""
    return env.get(name, "").strip() or str(default)


def bm25_parameters(env: Optional[Mapping[str, str]] = None) -> Tuple[float, float]:
    """BM25_K1 and BM25_B, validated (prototype.ingest reads only these, so other settings can't stop a rebuild)."""
    env = os.environ if env is None else env
    k1 = float(_setting(env, "BM25_K1", K1))
    if not (math.isfinite(k1) and k1 >= 0):
        raise ValueError(f"BM25_K1 must be 0 or more, got {k1}")
    b = float(_setting(env, "BM25_B", B))
    if not 0 <= b <= 1:
        raise ValueError(f"BM25_B must be between 0 and 1, got {b}")
    return k1, b


def retrieval_options(env: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    """PAGE_AGGREGATION, MAX_CHUNKS_PER_PAGE, MAX_CHUNKS_PER_DOCUMENT, RRF_K and FUSION_WEIGHTS, validated,
    as Retriever's keyword arguments.

    load_settings reads them through here, and the offline measurements
    (prototype.search, stress_test, image_table_check) call it alone, so they
    rank as the app would and an unrelated setting can't stop them.
    """
    env = os.environ if env is None else env
    aggregation = _setting(env, "PAGE_AGGREGATION", DEFAULT_PAGE_AGGREGATION).lower()
    if aggregation not in PAGE_AGGREGATION_MODES:
        raise ValueError(f"PAGE_AGGREGATION must be off, max or sum, got {aggregation!r}")
    per_page = int(_setting(env, "MAX_CHUNKS_PER_PAGE", DEFAULT_MAX_CHUNKS_PER_PAGE))
    if per_page < 1:
        raise ValueError(f"MAX_CHUNKS_PER_PAGE must be 1 or more, got {per_page}")
    per_document = int(_setting(env, "MAX_CHUNKS_PER_DOCUMENT", DEFAULT_MAX_CHUNKS_PER_DOCUMENT))
    if per_document < 0:
        raise ValueError(f"MAX_CHUNKS_PER_DOCUMENT must be 0 (no cap) or more, got {per_document}")
    rrf_k = int(_setting(env, "RRF_K", RRF_K))
    if rrf_k < 1:
        raise ValueError(f"RRF_K must be 1 or more, got {rrf_k}")
    weights = _csv(env.get("FUSION_WEIGHTS", "")) or ("1", "1")
    try:
        fusion_weights = tuple(float(w) for w in weights)
    except ValueError:
        raise ValueError(f"FUSION_WEIGHTS must be two numbers, vector,keyword; got {weights}") from None
    if (len(fusion_weights) != 2 or not all(math.isfinite(w) and w >= 0 for w in fusion_weights)
            or sum(fusion_weights) == 0):
        raise ValueError(f"FUSION_WEIGHTS must be two numbers of 0 or more (not both 0), vector,keyword; got {weights}")
    return dict(page_aggregation=aggregation, max_chunks_per_page=per_page, max_chunks_per_document=per_document,
                rrf_k=rrf_k, fusion_weights=fusion_weights)


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    primary = env.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL
    fallbacks = _csv(env["OPENROUTER_FALLBACK_MODELS"]) if "OPENROUTER_FALLBACK_MODELS" in env else DEFAULT_FALLBACK_MODELS
    models = tuple(dict.fromkeys((primary,) + fallbacks))
    paid = [m for m in models if not m.endswith(FREE_SUFFIX)]
    if paid:
        raise ValueError(f"Only free OpenRouter models (ending in {FREE_SUFFIX!r}) are allowed; got {paid}")
    # A paid model is reachable only by choosing the OpenAI provider on purpose: OPENAI_API_KEY or
    # OPENAI_MODEL alone change nothing. "ollama" counts as unset: it is the Chainlit app's value
    # for this same variable, and the local run reads the repo's one .env (--env-file .env).
    provider = env.get("LLM_PROVIDER", "").strip().lower() or "openrouter"
    if provider == "ollama":
        provider = "openrouter"
    if provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be openrouter or openai, got {provider!r}")
    rerank = env.get("RERANK", "on").strip().lower()
    if rerank not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"RERANK must be on or off, got {rerank!r}")
    rerank_model = env.get("RERANK_MODEL", "").strip() or RERANK_MODEL_NAME
    if rerank_model.lower() == NO_RERANKER:
        rerank, rerank_model = "off", NO_RERANKER
    elif rerank_model != RERANK_MODEL_NAME:
        # The default needs no model import at startup; another name is checked against
        # fastembed's list now, so a typo stops the deploy instead of the first question.
        from .embedder import known_cross_encoders

        known = known_cross_encoders()
        if rerank_model not in known:
            raise ValueError(f"RERANK_MODEL must be {NO_RERANKER!r} or one of {', '.join(known)}; got {rerank_model!r}")
    rerank_model_file = env.get("RERANK_MODEL_FILE", "").strip() or default_model_file(rerank_model)
    # On by default since DAR-652: on the locked set (rebuilt index, retrieval only) it gave hit@1
    # 152/204 and hit@5 183/204 against MiniLM-L-6 on every chunk's 147 and 180, the same lead
    # it had on the tuning split it was picked on (33 and 39 of 41 against 32 and 38); see
    # docs/locked-set/reranker-pick.md. The cross-encoder, trained on web passages, ranks
    # labelled table rows below prose that only mentions the numbers.
    text_only = env.get("RERANK_TEXT_ONLY", "on").strip().lower()
    if text_only not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"RERANK_TEXT_ONLY must be on or off, got {text_only!r}")
    batch = env.get("RERANK_BATCH_SIZE", "").strip() or str(RERANK_BATCH_SIZE)
    if not (batch.isdigit() and int(batch) >= 1):
        raise ValueError(f"RERANK_BATCH_SIZE must be a whole number of 1 or more, got {batch!r}")
    keyword = env.get("KEYWORD_SEARCH", "on").strip().lower()
    if keyword not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"KEYWORD_SEARCH must be on or off, got {keyword!r}")
    keyword_field = env.get("KEYWORD_FIELD", "on").strip().lower()
    if keyword_field not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"KEYWORD_FIELD must be on or off, got {keyword_field!r}")
    field_boost = _boost(env, "KEYWORD_FIELD_BOOST", DEFAULT_FIELD_BOOST)
    id_boost = _boost(env, "KEYWORD_ID_BOOST", DEFAULT_ID_BOOST)
    reasoning = env.get("LLM_REASONING", "off").strip().lower()
    if reasoning not in ("off", "low", "medium", "high"):
        raise ValueError(f"LLM_REASONING must be off, low, medium or high, got {reasoning!r}")
    top_k = int(env.get("TOP_K", "5"))
    if not 1 <= top_k <= 10:
        raise ValueError(f"TOP_K must be 1-10, got {top_k}")
    retrieval = retrieval_options(env)
    bm25_k1, bm25_b = bm25_parameters(env)
    budget = float(env.get("REQUEST_BUDGET_SECONDS", "55"))
    if not 10 <= budget <= 58:
        raise ValueError(f"REQUEST_BUDGET_SECONDS must be 10-58 (Vercel stops the function at 60), got {budget}")
    retry = env.get("RETRY_ON_REFUSAL", "on").strip().lower()
    if retry not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"RETRY_ON_REFUSAL must be on or off, got {retry!r}")
    row_guard = env.get("ROW_GUARD", "off").strip().lower()
    if row_guard not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"ROW_GUARD must be on or off, got {row_guard!r}")
    retry_min_seconds = float(env.get("RETRY_MIN_SECONDS", "15"))
    if retry_min_seconds < 0:
        raise ValueError(f"RETRY_MIN_SECONDS must be 0 or more, got {retry_min_seconds}")
    # Read by embedder.onnx_threads() when the models load; checked here so a bad value stops startup.
    threads = env.get("ONNX_THREADS", "").strip()
    if threads and not (threads.isdigit() and int(threads) >= 1):
        raise ValueError(f"ONNX_THREADS must be a whole number of 1 or more, got {threads!r}")
    index_dir = Path(env.get("INDEX_DIR", "").strip() or HOSTED_DIR / "index")
    openai_model = env.get("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
    openai_prices = price_for(openai_model, env)
    if provider == "openai" and openai_prices is None:
        # Without a price the monthly cap (DAR-715) would count nothing and never stop the paid model.
        raise ValueError(f"OPENAI_MODEL {openai_model!r} has no known price: set OPENAI_PRICE_PER_MILLION to "
                         "its input,output dollars per million tokens")
    budget_usd = _boost(env, "OPENAI_MONTHLY_BUDGET_USD", DEFAULT_BUDGET_USD)
    margin_usd = _boost(env, "OPENAI_BUDGET_MARGIN_USD", DEFAULT_MARGIN_USD)
    if budget_usd > 0 and margin_usd >= budget_usd:
        # A budget of 0 means no OpenAI spending at all; any other budget must leave room under it.
        raise ValueError(f"OPENAI_BUDGET_MARGIN_USD ({margin_usd}) must be less than OPENAI_MONTHLY_BUDGET_USD "
                         f"({budget_usd})")
    return Settings(
        llm_provider=provider,
        openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
        openai_model=openai_model,
        openai_prices=openai_prices,
        openai_monthly_budget_usd=budget_usd,
        openai_budget_margin_usd=margin_usd,
        openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip() or None,
        models=models,
        temperature=float(env.get("LLM_TEMPERATURE", "0.1")),
        reasoning=reasoning,
        rerank=rerank in ("on", "1", "true"),
        rerank_model=rerank_model,
        rerank_model_file=rerank_model_file,
        rerank_text_only=text_only in ("on", "1", "true"),
        rerank_batch_size=int(batch),
        keyword_search=keyword in ("on", "1", "true"),
        keyword_field=keyword_field in ("on", "1", "true"),
        keyword_field_boost=field_boost,
        keyword_id_boost=id_boost,
        rerank_candidates=int(env.get("RERANK_CANDIDATES", "40")),
        top_k=top_k,
        **retrieval,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        index_dir=index_dir if index_dir.is_absolute() else HOSTED_DIR / index_dir,
        max_question_chars=int(env.get("MAX_QUESTION_CHARS", "500")),
        rate_limit_per_minute=int(env.get("RATE_LIMIT_PER_MINUTE", "8")),
        request_budget_seconds=budget,
        retry_on_refusal=retry in ("on", "1", "true"),
        retry_min_score=float(env.get("RETRY_MIN_SCORE", "1.0")),
        retry_min_seconds=retry_min_seconds,
        allowed_origins=_csv(env.get("ALLOWED_ORIGINS", "")),
        row_guard=row_guard in ("on", "1", "true"),
    )
