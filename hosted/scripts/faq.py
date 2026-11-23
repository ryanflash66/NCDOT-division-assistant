"""Add, list, re-check and pull checked answers to frequent questions (DAR-673; rules in divrag/faq.py).

Run from the repo root. It talks to the same Upstash store the deployment uses:
KV_REST_API_URL and KV_REST_API_TOKEN (the store's REST URL and token, from the
Upstash database's page in the Vercel dashboard, Storage tab) in the environment
or the repo's .env. --namespace picks the deployment's entries (default
production; a preview's are under "preview").

    python hosted/scripts/faq.py draft --site https://ncdot-division-assistant-iota.vercel.app \\
        --division utilities --question "Who pays for a detour?" --out faq-detour.json
        # asks the site with the checked-answer store skipped and writes an entry to fill in:
        # id, the question log's counts (asked), who checked it and when, any confirmed rewordings
    python hosted/scripts/faq.py add faq-detour.json      # checks the criteria, fingerprints the cited
                                                          # pages from hosted/index, stores it
    python hosted/scripts/faq.py alias ID "another phrasing a person confirmed"
    python hosted/scripts/faq.py list | queue | remove ID
    python hosted/scripts/faq.py check [--site URL]        # after every index rebuild, see below

`check` reads hosted/index (the index being deployed): an entry whose cited page
text changed or is gone is pulled at once and queued; an entry whose division
gained or lost a document is re-run through the full pipeline on --site (which
must already serve the rebuilt index) and kept, with today as rechecked_on, if
it cites the same pages and states the same numbers, else pulled and queued with
the new answer for a person to check. Without --site those entries are listed and
the exit code is 1. The deployed app also checks the page fingerprints on every
served answer and pulls a stale entry itself.

A protected preview needs VERCEL_AUTOMATION_BYPASS_SECRET, as the held-out runner does.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

HOSTED = Path(__file__).resolve().parent.parent
ROOT = HOSTED.parent
sys.path.insert(0, str(HOSTED))

from divrag import faq  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import IndexFile  # noqa: E402
from divrag.spend import RedisStore  # noqa: E402

SITE_TIMEOUT_SECONDS = 90.0
STORE_TIMEOUT_SECONDS = 10.0


def _load_env() -> None:
    path = ROOT / ".env"
    if path.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError:  # the hosted requirements alone: the variables must be set already
            return
        load_dotenv(path, override=False)


def _store(namespace: str) -> faq.FaqStore:
    for url_name, token_name in (("KV_REST_API_URL", "KV_REST_API_TOKEN"),
                                 ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")):
        url, token = os.environ.get(url_name, "").strip(), os.environ.get(token_name, "").strip()
        if url and token:
            return faq.FaqStore(RedisStore(url, token, timeout=STORE_TIMEOUT_SECONDS), namespace)
    raise SystemExit("KV_REST_API_URL and KV_REST_API_TOKEN must be set (the Upstash store's REST URL and token)")


async def ask_site(site: str, question: str, division: str, asker: Optional[str] = None,
                   transport: Any = None) -> Dict[str, Any]:
    """The full pipeline's answer from a deployed copy, with the checked-answer store skipped."""
    import httpx

    secret = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    headers = {"x-vercel-protection-bypass": secret} if secret else None
    body = {"question": question, "asker": asker or division, "target": division, "faq": False}
    async with httpx.AsyncClient(timeout=SITE_TIMEOUT_SECONDS, headers=headers, transport=transport) as client:
        reply = await client.post(f"{site.rstrip('/')}/api/ask", json=body)
    data = reply.json()
    if reply.status_code != 200:
        return {"error": data.get("error", f"HTTP {reply.status_code}")}
    return data


def _today() -> str:
    return date.today().isoformat()


async def draft(args) -> int:
    reply = await ask_site(args.site, args.question, args.division, args.asker)
    if reply.get("error") or reply.get("refused"):
        print(f"not an answer to store: {reply.get('error') or reply.get('answer')}", file=sys.stderr)
        return 1
    entry = {
        "id": "", "division": args.division, "question": args.question, "answer": reply["answer"],
        "sources": reply["sources"], "aliases": [],
        "asked": {"times": None, "askers": None, "days": faq.ASKED_WINDOW_DAYS},
        "checked_by": "", "checked_on": "",
        "_model": reply.get("model"), "_uncited": reply.get("uncited"), "_unverified": reply.get("unverified"),
    }
    text = json.dumps(entry, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}: check the answer against its cited pages, then fill in id, asked, checked_by "
              "and checked_on, and run add")
    else:
        print(text)
    return 0


def entry_from_file(path: Path) -> faq.Entry:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    data.setdefault("added_on", _today())
    return faq.Entry(**{k: v for k, v in data.items() if k in faq.Entry.__dataclass_fields__})


async def add(args) -> int:
    entry = entry_from_file(Path(args.file))
    problems = faq.validate_entry(entry)
    if not entry.id.strip():
        problems.append("id is empty")
    if problems:
        print("not stored:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    faq.PageText(IndexFile.load(args.index)).stamp(entry)
    store = _store(args.namespace)
    existing = {e.id for e in await store.entries(entry.division)}
    if entry.id in existing and not args.replace:
        print(f"{entry.id} is already stored; pass --replace to overwrite it", file=sys.stderr)
        return 1
    await store.put(entry)
    pages = ", ".join(f"{p['file']} p.{p['page']}" for p in entry.pages)
    print(f"stored {entry.id} in {store.key(entry.division)}: cites {pages}")
    return 0


async def alias(args) -> int:
    store = _store(args.namespace)
    for entry in await store.all_entries():
        if entry.id == args.id:
            if faq.question_key(args.phrasing) != faq.question_key(entry.question):
                print("not added: its numbers, units or contrast words differ from the question's, so it would "
                      "never be served", file=sys.stderr)
                return 1
            if args.phrasing not in entry.aliases:
                entry.aliases.append(args.phrasing)
                await store.put(entry)
            print(f"{entry.id}: {len(entry.aliases)} other phrasings")
            return 0
    print(f"no entry {args.id}", file=sys.stderr)
    return 1


async def list_entries(args) -> int:
    store = _store(args.namespace)
    for entry in await store.all_entries():
        print(f"{entry.id}  [{entry.division}]  checked {entry.checked_on} by {entry.checked_by}"
              f"{'  rechecked ' + entry.rechecked_on if entry.rechecked_on else ''}\n    {entry.question}"
              + "".join(f"\n    = {a}" for a in entry.aliases))
    return 0


async def queue(args) -> int:
    for item in await _store(args.namespace).queue():
        print(f"{item['entry']['id']}  pulled {item['pulled_on']}: {item['reason']}")
    return 0


async def remove(args) -> int:
    removed = await _store(args.namespace).remove(args.id)
    print(f"removed {removed} item(s) for {args.id}")
    return 0 if removed else 1


async def check(args) -> int:
    pages = faq.PageText(IndexFile.load(args.index))
    rerun = None
    if args.site:
        async def rerun(entry: faq.Entry) -> Dict[str, Any]:
            return await ask_site(args.site, entry.question, entry.division)
    report = await faq.check_entries(_store(args.namespace), pages, rerun, _today())
    for entry_id, reason in report.pulled:
        print(f"pulled  {entry_id}: {reason}")
    for entry_id in report.rechecked:
        print(f"re-run  {entry_id}: same cited pages and numbers, kept")
    for entry_id in report.needs_rerun:
        print(f"waiting {entry_id}: its division's documents changed; run check with --site to re-run it")
    print(f"{len(report.kept)} unchanged, {len(report.rechecked)} re-run and kept, {len(report.pulled)} pulled, "
          f"{len(report.needs_rerun)} waiting for a re-run")
    return 1 if report.needs_rerun else 0


def main(argv: Optional[List[str]] = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--namespace", default="production", help="the deployment's entries (default production)")
    parser.add_argument("--index", default=str(HOSTED / "index"), help="the index being deployed (default hosted/index)")
    commands = parser.add_subparsers(dest="command", required=True)
    d = commands.add_parser("draft", help="ask the site in full and write an entry to check and fill in")
    d.add_argument("--site", required=True)
    d.add_argument("--division", required=True, choices=sorted(BY_ID))
    d.add_argument("--question", required=True)
    d.add_argument("--asker", choices=sorted(BY_ID))
    d.add_argument("--out")
    a = commands.add_parser("add", help="store a checked entry (a filled-in draft)")
    a.add_argument("file")
    a.add_argument("--replace", action="store_true")
    al = commands.add_parser("alias", help="add another phrasing a person confirmed asks the same thing")
    al.add_argument("id")
    al.add_argument("phrasing")
    commands.add_parser("list", help="the stored entries")
    commands.add_parser("queue", help="pulled entries waiting for a person to re-check them")
    r = commands.add_parser("remove", help="delete an entry (stored or queued)")
    r.add_argument("id")
    c = commands.add_parser("check", help="after an index rebuild: pull changed entries, re-run changed divisions")
    c.add_argument("--site", help="a deployment already serving the rebuilt index, to re-run entries on")
    args = parser.parse_args(argv)
    handler = {"draft": draft, "add": add, "alias": alias, "list": list_entries, "queue": queue,
               "remove": remove, "check": check}[args.command]
    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
