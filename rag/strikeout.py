"""Undo pymupdf4llm's false strikeout marks, rejoining the words they split.

MuPDF flags a character as struck out when a drawn line crosses it, and the
manuals' figures and table rules cross a lot of text: Chapter 5 p.16 (locked
wztc-047) came out as "Mo ~~w~~ ing Operat ~~i~~ on ... Speed: ~~5~~ 5 MPH",
so the model read the speed limit "55 MPH" as "5 5 MPH". 128 chunks in 13
documents had these marks, and none was a real deletion: the documents are
published final versions.

pymupdf4llm also puts a space around every styled span, so dropping the `~~`
alone leaves "Mo w ing". Each space next to a mark is checked against the
page's plain text layer, which keeps the characters of a word together: the
two pieces are joined when the page has them joined ("Mowing", "55") and not
spaced, and the space is kept otherwise ("become a permanent system").

A scanned page has no text layer to ask (wzi_guide p.58 is OCR'd and came out
"the ~~id~~ ent ~~ifi~~ cat ~~io~~ n of"). There the pieces between marks are
split into as few words as possible from the document's own vocabulary (its
lines without marks), so "id ent ifi cat io n" becomes "identification"; a
piece that is no known word on any reading keeps its spaces.
"""

import re

_MARK = "~~"
# Markdown a span may carry next to the mark ("**~~E~~**"); not part of the words compared.
_STYLE = re.compile(r"[*_`]|</?sup>")


def _bare(token: str) -> str:
    return _STYLE.sub("", token)


_LETTERS = re.compile(r"[A-Za-z]+")
# A piece left on its own when it is no known word costs more than any word: fewest, known words win.
_UNKNOWN = 3


def vocabulary(lines) -> frozenset:
    """Lowercase words of the lines that carry no marks: what the document spells whole."""
    return frozenset(w.lower() for line in lines if _MARK not in line for w in _LETTERS.findall(line))


def _segment(pieces, vocab) -> list:
    """The pieces grouped into words: fewest groups, each a known word where one exists ([[i, j), ...])."""
    n = len(pieces)
    best = [(0, None)] + [(float("inf"), None)] * n
    for end in range(1, n + 1):
        for start in range(end):
            word = "".join(pieces[start:end]).lower()
            cost = 1 if word in vocab else (_UNKNOWN if end - start == 1 else None)
            if cost is not None and best[start][0] + cost < best[end][0]:
                best[end] = (best[start][0] + cost, start)
    groups, end = [], n
    while end:
        start = best[end][1]
        groups.append((start, end))
        end = start
    return groups[::-1]


_CORE = re.compile(r"[(\"“']?([A-Za-z]+)[.,:;!?)\"”']*")


def _core(piece: str, lead: bool, trail: bool):
    """The piece's letters when it is a word piece (with an opening or closing mark only where allowed)."""
    match = _CORE.fullmatch(piece or "")
    if not match or (not lead and not piece[0].isalpha()) or (not trail and not piece[-1].isalpha()):
        return None
    return match.group(1)


def _unstrike_line(line: str, plain: str, vocab: frozenset) -> str:
    parts = re.split(r"(\s+)", line)
    words, gaps = parts[0::2], parts[1::2]
    # A space is a join candidate when a mark is right beside it: "Mo ~~w~~ ing" has two.
    touched = [_bare(words[k]).endswith(_MARK) or _bare(words[k + 1]).startswith(_MARK) for k in range(len(gaps))]
    words = [w.replace(_MARK, "") for w in words]
    bare = [_bare(w) for w in words]
    # Per gap: True join, False keep, None when the text layer can't tell (a scanned page).
    join = []
    for k, is_touched in enumerate(touched):
        left, right = bare[k], bare[k + 1]
        if not (is_touched and left and right):
            join.append(False)
        elif plain and f"{left} {right}" in plain:
            join.append(False)
        elif plain and left + right in plain:
            join.append(True)
        else:
            join.append(None)
    # Runs of letter pieces joined by undecided gaps are split into words from the vocabulary; the run's
    # first piece may open with a bracket or quote and its last may end in punctuation ("ng:", "ure,").
    k = 0
    while k < len(join):
        first = _core(bare[k], lead=True, trail=False) if join[k] is None else None
        if first is None:
            join[k] = bool(join[k])
            k += 1
            continue
        cores, gap = [first], k
        while gap < len(join) and join[gap] is None:
            following = _core(bare[gap + 1], lead=False, trail=True)
            if following is None:
                break
            cores.append(following)
            gap += 1
            if not bare[gap][-1].isalpha():
                break
        if len(cores) == 1:
            join[k] = False
            k += 1
            continue
        for g in range(k, gap):
            join[g] = False
        for start, stop in _segment(cores, vocab) if vocab else ():
            for g in range(k + start, k + stop - 1):
                join[g] = True
        k = gap
    out = words[0]
    for gap, joined, word in zip(gaps, join, words[1:]):
        out += word if joined else gap + word
    return out


def unstrike(markdown: str, plain_text: str, vocab: frozenset = frozenset()) -> str:
    """The page's Markdown without `~~` marks, split words rejoined as the page's text layer
    (or, where it can't tell, the document's vocabulary) has them whole."""
    if _MARK not in markdown:
        return markdown
    plain = " ".join((plain_text or "").split())
    return "\n".join(_unstrike_line(line, plain, vocab) if _MARK in line else line for line in markdown.split("\n"))
