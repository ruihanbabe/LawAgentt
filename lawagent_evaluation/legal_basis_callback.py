from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import cn2an


ARTICLE_RE = re.compile(r"第\s*([〇零一二两三四五六七八九十百千万0-9]+)\s*条(?:\s*之\s*([〇零一二两三四五六七八九十百千万0-9]+))?")
BOOK_TITLE_RE = re.compile(r"[《》〈〉\s]")
VERSION_SUFFIX_RE = re.compile(r"[（(]([^）)]*(?:19|20)\d{2}[^）)]*|[^）)]*(?:修正|修订|注释版)[^）)]*)[）)]$")
PRC_PREFIX = "中华人民共和国"


def normalize_law_title(value: str) -> str:
    return BOOK_TITLE_RE.sub("", value or "").strip()


def canonical_law_title(value: str) -> str:
    """Conservative exact-match key: normalize prefix/punctuation but preserve version hints."""
    normalized = normalize_law_title(value).replace("(", "（").replace(")", "）")
    match = VERSION_SUFFIX_RE.search(normalized)
    version_hint = re.sub(r"\s+", "", match.group(1)) if match else ""
    base = normalized[:match.start()] if match else normalized
    base = base.removeprefix(PRC_PREFIX)
    return f"{base}|version={version_hint}" if version_hint else base


def law_title_keys(value: str) -> tuple[str, ...]:
    normalized = canonical_law_title(value)
    # Civil Code books are stored as separate documents but retain globally unique article numbers.
    base = normalized.split("·", 1)[0]
    return (normalized,) if base == normalized else (normalized, base)


def normalize_article_no(value: str) -> str | None:
    match = ARTICLE_RE.search(value or "")
    if not match:
        return None
    try:
        main = str(cn2an.cn2an(match.group(1), "smart"))
        suffix = str(cn2an.cn2an(match.group(2), "smart")) if match.group(2) else None
    except Exception:  # cn2an raises KeyError/IndexError for some malformed real-world numerals
        return None
    return f"{main}-{suffix}" if suffix else main


@dataclass(frozen=True, slots=True)
class LegalCitation:
    law_title: str
    article_no: str


@dataclass(frozen=True, slots=True)
class LawRecord:
    chunk_id: str
    title: str
    article_no: str
    content: str
    effective_from: date | None
    effective_to: date | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CallbackResult:
    citation: LegalCitation
    status: str
    record: LawRecord | None = None


def citations_from_legal_basis(items: Iterable[dict[str, Any]]) -> list[LegalCitation]:
    result: list[LegalCitation] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        title = normalize_law_title(str(item.get("law") or ""))
        article_no = normalize_article_no(str(item.get("terms") or ""))
        key = (title, article_no or "")
        if title and article_no and key not in seen:
            seen.add(key)
            result.append(LegalCitation(*key))
    return result


class LawCatalog:
    """Deterministic title/article lookup over the versioned processed law corpus."""

    def __init__(self, records: Sequence[LawRecord]) -> None:
        self.records = list(records)
        self._by_exact: dict[tuple[str, str], list[LawRecord]] = defaultdict(list)
        self._titles: set[str] = set()
        for record in records:
            for title in law_title_keys(record.title):
                self._titles.add(title)
                self._by_exact[(title, record.article_no)].append(record)

    @classmethod
    def from_jsonl(cls, path: Path) -> "LawCatalog":
        records: list[LawRecord] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                article_no = str(item.get("article_no") or "").strip()
                if not article_no:
                    continue
                records.append(LawRecord(
                    chunk_id=str(item["chunk_id"]), title=str(item["title"]), article_no=article_no,
                    content=str(item["content"]), effective_from=_parse_date(item.get("effective_from")),
                    effective_to=_parse_date(item.get("effective_to")), payload=item,
                ))
        return cls(records)

    def resolve(self, citation: LegalCitation, event_date: date | None = None) -> CallbackResult:
        title = canonical_law_title(citation.law_title)
        candidates = self._by_exact.get((title, citation.article_no), [])
        if not candidates:
            status = "article_not_found" if title in self._titles else "law_not_found"
            return CallbackResult(citation, status)
        applicable = [record for record in candidates if _is_applicable(record, event_date)]
        if event_date is not None and not applicable:
            return CallbackResult(citation, "historical_source_missing")
        selected = max(applicable or candidates, key=lambda record: record.effective_from or date.min)
        return CallbackResult(citation, "matched", selected)


def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _is_applicable(record: LawRecord, event_date: date | None) -> bool:
    if event_date is None:
        return True
    return (record.effective_from is None or record.effective_from <= event_date) and (
        record.effective_to is None or event_date < record.effective_to
    )
