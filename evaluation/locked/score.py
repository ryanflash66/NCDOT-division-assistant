"""Deterministic scoring of one locked-set item, and the aggregates with their intervals.

No LLM judge: the page, the value, the unit and the abstention are all checked
by rule (the research note's recommendation, C-eval-edgecases.md section 5),
so the highest-stakes dimensions never depend on a judge's leniency.

Per item (score_item):

    right_document         the gold document is in the top-5 retrieval
    page_rank              1-based rank of the first gold PDF page in the top 5, or None
    hit1, hit5             page_rank == 1 / page_rank <= 5
    cited_pages_pdf        every page the answer's sources cite, as [{"file", "page", "page_end"}]
    cited_pages_printed    the same with the sources' printed_page fields (when the API sends them)
    cited_page_ok_pdf      there is a citation, and every cited page is a gold page of the gold
                           document (a page..page_end range counts when it overlaps)
    cited_page_ok_printed  the same against the gold printed pages; None when the API or
                           the item has no printed pages
    value_ok               normalize.value_matches on the answer text; with expected.all_of, every
                           part must be in the answer (a list that runs over a page break)
    clarify_ok             behaviour "clarify" only (the question leaves out a variable): the answer
                           shows every branch of expected.all_of, or names none of them and asks.
                           These items have no value_ok or strict_ok: there is no single right value
    strict_ok              value_ok and cited_page_ok_pdf and not refused ("strict attributed
                           accuracy": right answer from the right page)
    refused, uncited       the answer's flags
    unverified             numbers the hosted guardrail could not find in the cited passages,
                           passed through from the payload when present
    flagged                a cited answer (not refused, not uncited) the guardrail marked
                           unverified: the rate DAR-659 wants near zero
    false_flag             flagged although its value is right (the guardrail's false alarms,
                           over the cited answers with the right value)
    critical               a confident wrong answer: cited (not refused, not uncited) with the
                           wrong value, or a cited answer to an unanswerable question, or a cited
                           answer that picks some branches of a clarify item and not the others
    seconds, model, error  the answer call

Aggregates (aggregate): for every stratum (all; per split, division, type,
edge case and asker-vs-target) each metric as count/n with a 95% Wilson
interval, the number of distinct gold pages (clusters) in the stratum, and
the 4-way abstention table with the over-refusal and false-answer rates.
"""

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .normalize import value_matches

TOP = 5
Z_95 = 1.959963984540054
# Metrics reported per stratum, in table order; each is a per-item True/False/None field.
METRICS = ("right_document", "hit1", "hit5", "cited_page_ok_pdf", "cited_page_ok_printed", "value_ok", "strict_ok",
           "critical", "over_refusal", "false_answer", "flagged", "false_flag", "clarify_ok")


def wilson(k: int, n: int, z: float = Z_95) -> Tuple[float, float]:
    """The Wilson score interval for k successes in n trials; (0, 1) when n is 0.

    Recommended over the normal approximation and the bootstrap for the small n
    of a test set (Bowyer et al., ICML 2025): 14/15 gives 0.70-0.99, not a
    point estimate of 93%.
    """
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    # At 0 or n the bound is exactly the edge; the arithmetic leaves 1e-18 of rounding noise there.
    return (0.0 if k == 0 else max(0.0, centre - half)), (1.0 if k == n else min(1.0, centre + half))


def zero_failure_upper(n: int, confidence: float = 0.95) -> Optional[float]:
    """One-sided Clopper-Pearson upper bound on a failure rate when 0 of n failed (0/50: 5.8%).

    Used for the critical-error rate: zero errors in a small run does not show
    the rate is low, and this is how low it is shown to be.
    """
    if n <= 0:
        return None
    return 1 - (1 - confidence) ** (1 / n)


def source_file(source: Dict[str, Any]) -> Optional[str]:
    """The divisions.Document file a cited source is from, by its url (without #page) or its title."""
    from divrag.divisions import DIVISIONS

    url = (source.get("url") or "").split("#", 1)[0]
    title = source.get("title")
    for division in DIVISIONS:
        for document in division.documents:
            if (url and document.url == url) or (title and document.title == title):
                return document.file
    return None


def _pages_of(page: Optional[int], page_end: Optional[int]) -> List[int]:
    if not page:
        return []
    return list(range(page, (page_end or page) + 1)) if page_end and page_end >= page else [page]


def page_rank(ranked: Sequence[Dict[str, Any]], source: str, pages: Iterable[int]) -> Optional[int]:
    """1-based rank of the first hit on a gold page of the gold document in the top TOP, or None."""
    gold = set(pages)
    for rank, hit in enumerate(ranked[:TOP], 1):
        if hit.get("source") == source and hit.get("page") in gold:
            return rank
    return None


def cited_pages(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """The answer's cited pages: (pdf pages, printed pages or None when any source lacks the field)."""
    pdf, printed = [], []
    has_printed = True
    for source in payload.get("sources") or []:
        file = source_file(source)
        pdf.append({"file": file, "page": source.get("page"), "page_end": source.get("page_end")})
        if "printed_page" not in source:
            has_printed = False
        printed.append({"file": file, "page": source.get("printed_page"), "page_end": source.get("printed_page_end")})
    return pdf, (printed if has_printed else None)


def _cited_ok_pdf(cited: Sequence[Dict[str, Any]], source: str, pages: Iterable[int]) -> bool:
    gold = set(pages)
    if not cited:
        return False
    return all(c["file"] == source and set(_pages_of(c["page"], c["page_end"])) & gold for c in cited)


_LABEL = re.compile(r"^(.*?)(\d+)$")


def printed_range(page: Any, page_end: Any) -> set:
    """Every printed label a cited printed range covers.

    "13".."15" is 13, 14 and 15, and "5-12".."5-14" or "A-3".."A-5" expand on
    their trailing number when the prefix is the same, as the PDF range does;
    anything else (roman numerals, a prefix change) is just the two ends.
    """
    start, end = str(page or "").strip(), str(page_end or "").strip()
    labels = {p for p in (start, end) if p}
    a, b = _LABEL.match(start), _LABEL.match(end)
    if a and b and a.group(1) == b.group(1) and 0 < int(b.group(2)) - int(a.group(2)) <= 50:
        labels |= {f"{a.group(1)}{n}" for n in range(int(a.group(2)), int(b.group(2)) + 1)}
    return labels


def _cited_ok_printed(cited: Optional[Sequence[Dict[str, Any]]], source: str,
                      printed_pages: Optional[Sequence[str]]) -> Optional[bool]:
    gold = {str(p).strip() for p in (printed_pages or []) if str(p).strip()}
    if cited is None or not gold:
        return None
    if not cited:
        return False
    return all(c["file"] == source and printed_range(c["page"], c["page_end"]) & gold for c in cited)


def _parts_found(all_of: Sequence[Any], answer: str) -> List[bool]:
    """For each required part (a wording, or a list of wordings of the same thing): is it in the answer?"""
    return [value_matches(None, [part] if isinstance(part, str) else list(part), answer) for part in all_of]


# A reply that asks for the missing variable instead of answering: a question, or "which"/"depends on".
_ASKS = re.compile(r"\?|\bwhich\b|\bdepends? on\b|\bspecify\b|\bclarify\b", re.IGNORECASE)


def clarify_score(all_of: Sequence[Any], answer: str) -> Tuple[bool, bool]:
    """(clarify_ok, picked a branch) for a question that leaves out a variable.

    Right: every branch is shown, or none is and the reply asks for the
    variable. Showing some branches and not the others is the failure the case
    is about (a default picked silently): with a citation it is critical.
    """
    found = _parts_found(all_of, answer)
    if all(found):
        return True, False
    if not any(found):
        return bool(_ASKS.search(answer)), False
    return False, True


def score_item(item: Dict[str, Any], ranked: Optional[Sequence[Dict[str, Any]]], payload: Optional[Dict[str, Any]],
               seconds: Optional[float] = None, error: Optional[str] = None) -> Dict[str, Any]:
    """One row of scores for an item.

    `ranked`: the top-TOP retrieval as [{"source", "page", ...}], best first
    (None when the retrieval stage did not run). `payload`: the answer as
    /api/ask returns it (Answer.as_dict), None when the answer stage did not run
    or `error` says why the call failed. Fields that do not apply are None, so
    aggregates count only the items where a metric is defined.
    """
    expected = item.get("expected") or None
    answerable = not item.get("refuse") and expected is not None
    row: Dict[str, Any] = {
        "id": item["id"], "division": item["division"], "asker": item.get("asker"), "type": item.get("type"),
        "edge_cases": list(item.get("edge_cases") or []), "split": item.get("split"), "answerable": answerable,
        "right_document": None, "page_rank": None, "hit1": None, "hit5": None, "top": None,
        "answered": payload is not None, "refused": None, "uncited": None, "unverified": None,
        "cited_pages_pdf": None, "cited_pages_printed": None, "cited_page_ok_pdf": None, "cited_page_ok_printed": None,
        "value_ok": None, "strict_ok": None, "critical": None, "over_refusal": None, "false_answer": None,
        "flagged": None, "false_flag": None, "clarify_ok": None, "behaviour": item.get("behaviour"), "answer": None, "seconds": seconds, "model": None, "error": error,
    }
    if ranked is not None:
        row["top"] = [f"{h.get('source')} p.{h.get('page')}" for h in ranked[:TOP]]
        if answerable:
            rank = page_rank(ranked, expected["source"], expected["pdf_pages"])
            row.update(right_document=any(h.get("source") == expected["source"] for h in ranked[:TOP]),
                       page_rank=rank, hit1=rank == 1, hit5=rank is not None)
    if payload is None:
        return row
    refused, uncited = bool(payload.get("refused")), bool(payload.get("uncited"))
    pdf, printed = cited_pages(payload)
    row.update(refused=refused, uncited=uncited, answer=payload.get("answer"), model=payload.get("model"),
               cited_pages_pdf=pdf, cited_pages_printed=printed,
               unverified=list(payload["unverified"]) if payload.get("unverified") is not None else None)
    if answerable:
        row["over_refusal"] = refused
        clarify = item.get("behaviour") == "clarify"
        text = payload.get("answer") or ""
        if refused:
            row.update(critical=False, **({"clarify_ok": False} if clarify else {"value_ok": False, "strict_ok": False}))
            return row
        row["cited_page_ok_pdf"] = _cited_ok_pdf(pdf, expected["source"], expected["pdf_pages"])
        row["cited_page_ok_printed"] = _cited_ok_printed(printed, expected["source"], expected.get("printed_pages"))
        if clarify:
            row["clarify_ok"], picked = clarify_score(expected.get("all_of") or [], text)
            row["critical"] = picked and not uncited
            return row
        if expected.get("all_of"):
            row["value_ok"] = all(_parts_found(expected["all_of"], text))
        else:
            row["value_ok"] = value_matches(expected.get("value"), expected.get("accept"), text)
        row["strict_ok"] = bool(row["value_ok"] and row["cited_page_ok_pdf"])
        # The wrong number with a citation beside it is what a visitor would act on;
        # an uncited answer is shown with "No source cited" and is counted separately.
        row["critical"] = not uncited and not row["value_ok"]
        if not uncited and row["unverified"] is not None:
            row["flagged"] = bool(row["unverified"])
            if row["value_ok"]:
                row["false_flag"] = row["flagged"]
    else:
        row["false_answer"] = not refused
        row["critical"] = not refused and not uncited
        if not refused and not uncited and row["unverified"] is not None:
            row["flagged"] = bool(row["unverified"])
    return row


def _stat(rows: Sequence[Dict[str, Any]], metric: str) -> Dict[str, Any]:
    defined = [r[metric] for r in rows if r.get(metric) is not None]
    k, n = sum(1 for v in defined if v), len(defined)
    low, high = wilson(k, n)
    stat: Dict[str, Any] = {"k": k, "n": n, "rate": k / n if n else None, "ci": [low, high] if n else None}
    if metric == "critical" and n and k == 0:
        stat["upper_if_zero"] = zero_failure_upper(n)
    return stat


def clusters(items: Sequence[Dict[str, Any]]) -> int:
    """Distinct gold (document, first page) pairs among the answerable items: the independent observations."""
    pages = set()
    for item in items:
        expected = item.get("expected")
        if expected and not item.get("refuse"):
            pages.add((expected["source"], expected["pdf_pages"][0]))
    return len(pages)


def abstention(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The 4-way table (answerable x refused) over the items whose answer stage ran."""
    ran = [r for r in rows if r.get("refused") is not None]
    table = {}
    for answerable in (True, False):
        group = [r for r in ran if r["answerable"] == answerable]
        refused = sum(1 for r in group if r["refused"])
        table["answerable" if answerable else "unanswerable"] = {"answered": len(group) - refused, "refused": refused,
                                                                 "n": len(group)}
    return {**table, "over_refusal": _stat(ran, "over_refusal"), "false_answer": _stat(ran, "false_answer")}


def _block(rows: Sequence[Dict[str, Any]], items_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    items = [items_by_id[r["id"]] for r in rows if r["id"] in items_by_id]
    return {
        "n": len(rows), "answerable": sum(1 for r in rows if r["answerable"]),
        "unanswerable": sum(1 for r in rows if not r["answerable"]), "clusters": clusters(items),
        "retrieval_run": sum(1 for r in rows if r.get("top") is not None),
        "answer_run": sum(1 for r in rows if r.get("refused") is not None),
        "metrics": {metric: _stat(rows, metric) for metric in METRICS},
    }


def _relation(row: Dict[str, Any]) -> str:
    return "same division" if (row.get("asker") or row["division"]) == row["division"] else "cross-division"


def aggregate(rows: Sequence[Dict[str, Any]], items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Every stratum's counts and intervals, plus the abstention table and answer times."""
    by_id = {i["id"]: i for i in items}

    def strata(key) -> Dict[str, Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            values = key(row)
            for value in ([values] if isinstance(values, str) or values is None else values):
                groups.setdefault(str(value), []).append(row)
        return {name: _block(group, by_id) for name, group in sorted(groups.items())}

    seconds = sorted(r["seconds"] for r in rows if r.get("seconds") is not None)
    return {
        "all": _block(rows, by_id),
        "split": strata(lambda r: r.get("split")),
        "division": strata(lambda r: r["division"]),
        "type": strata(lambda r: r.get("type")),
        "edge_case": strata(lambda r: r.get("edge_cases") or []),
        "asker": strata(_relation),
        "abstention": abstention(rows),
        "seconds": {"n": len(seconds), "median": seconds[len(seconds) // 2] if seconds else None,
                    "p90": seconds[min(len(seconds) - 1, max(0, math.ceil(0.9 * len(seconds)) - 1))] if seconds else None,
                    "max": seconds[-1] if seconds else None},
    }
