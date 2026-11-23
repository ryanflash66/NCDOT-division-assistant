"""The document register (DAR-674): each document's level, issuer, binding, edition and supersession.

register.json holds one row per document in divisions.py, keyed by file name
(a test checks the two lists agree). The levels, highest first by default:

    federal    the CFR, the Federal Register, the MUTCD and FHWA publications
    state      NCDOT department-wide specifications, drawings, manuals and policies
    division   one NCDOT unit's own manuals and guidance
    internal   NCDOT procedures, memos, reviews, reports and training material

Which document governs which is NCDOT's call: the rows are a first pass from
each document's cover. The register is data, so NCDOT can change a level or
mark an edition superseded without a code change. prototype.ingest copies each
document's level and edition onto its passages; the app reads them from here
(a test checks the committed index agrees).

An older edition is marked by setting its `superseded_by` to the newer
edition's file name. While the newer one is in the index, the older one is
left out of every search (index_file.IndexFile), so it can never be the answer.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

REGISTER_FILE = Path(__file__).resolve().parent / "register.json"
LEVELS: Tuple[str, ...] = ("federal", "state", "division", "internal")
BINDINGS: Tuple[str, ...] = ("rule", "guidance")


@dataclass(frozen=True)
class Entry:
    file: str
    issuer: str
    level: str
    binding: str
    edition: Optional[str] = None
    superseded_by: Optional[str] = None


class Register:
    def __init__(self, entries: Mapping[str, Entry], labels: Mapping[str, str]):
        self.entries = dict(entries)
        self.labels = dict(labels)

    @classmethod
    def from_json(cls, data: Mapping) -> "Register":
        """A register from register.json's contents; a bad row raises, so a mistake stops startup."""
        levels = data.get("levels") or {}
        if sorted(levels) != sorted(LEVELS):
            raise ValueError(f"register levels must be {', '.join(LEVELS)}; got {', '.join(levels)}")
        labels = {level: str(levels[level]["label"]) for level in LEVELS}
        entries: Dict[str, Entry] = {}
        for file, row in (data.get("documents") or {}).items():
            entry = Entry(file=file, issuer=str(row["issuer"]), level=row["level"], binding=row["binding"],
                          edition=row.get("edition") or None, superseded_by=row.get("superseded_by") or None)
            if entry.level not in LEVELS:
                raise ValueError(f"register: {file!r} has level {entry.level!r}, not one of {', '.join(LEVELS)}")
            if entry.binding not in BINDINGS:
                raise ValueError(f"register: {file!r} has binding {entry.binding!r}, not one of {', '.join(BINDINGS)}")
            entries[file] = entry
        for entry in entries.values():
            if entry.superseded_by is not None and (entry.superseded_by == entry.file
                                                     or entry.superseded_by not in entries):
                raise ValueError(f"register: {entry.file!r} is superseded by {entry.superseded_by!r}, "
                                 "which is not another document in the register")
        return cls(entries, labels)

    @classmethod
    def load(cls, path: "str | Path" = REGISTER_FILE) -> "Register":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))

    def entry(self, file: str) -> Optional[Entry]:
        return self.entries.get(file)

    def label(self, level: Optional[str]) -> Optional[str]:
        """What the page and the answer call a level ("Federal"); None for none."""
        return self.labels.get(level) if level else None

    def superseded(self, files: Iterable[str]) -> Set[str]:
        """The files among `files` whose newer edition is also among them, following chains (A by B by C)."""
        present = set(files)
        out: Set[str] = set()
        for file in present:
            seen = {file}
            newer = self.entries[file].superseded_by if file in self.entries else None
            while newer is not None and newer not in seen:
                if newer in present:
                    out.add(file)
                    break
                seen.add(newer)
                newer = self.entries[newer].superseded_by if newer in self.entries else None
        return out


REGISTER = Register.load()


def entry_for(file: str) -> Optional[Entry]:
    """The register row of a chunk's `source` (its file name)."""
    return REGISTER.entry(file)


def level_label(level: Optional[str]) -> Optional[str]:
    return REGISTER.label(level)


def tag(chunks: Iterable[Dict], register: Register = REGISTER) -> None:
    """Copy each chunk's document level and edition onto it (prototype.ingest, before saving the index)."""
    for chunk in chunks:
        entry = register.entry(chunk.get("source") or "")
        chunk.pop("level", None)
        chunk.pop("edition", None)
        if entry is not None:
            chunk["level"] = entry.level
            if entry.edition:
                chunk["edition"] = entry.edition
