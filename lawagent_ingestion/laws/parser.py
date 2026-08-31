from __future__ import annotations

import hashlib
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import cn2an

from .models import DocumentType, LawChunk, LawDocumentVersion


INFO_END_RE = re.compile(r"<!--\s*INFO END\s*-->")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
ARTICLE_RE = re.compile(
    r"^(?:#{1,6}\s*)?第(?P<base>[〇零一二三四五六七八九十百千万两\d]+)条"
    r"(?:(?:之)(?P<suffix>[〇零一二三四五六七八九十百千万两\d]+))?\s*(?P<body>.*)$"
)
NUMBERED_ITEM_RE = re.compile(
    r"^(?P<label>[〇零一二三四五六七八九十百千万两]+)、\s*(?P<body>.*)$"
)
FILENAME_DATE_RE = re.compile(r"[（(](?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[）)]$")
ANY_DATE_RE = re.compile(r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日")
REPEAL_FROM_RE = re.compile(
    r"(?P<evidence>(?:本法|本条例|本规定|本办法|本决定|本解释)?\s*"
    r"自\s*(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s*起?"
    r"(?:废止|停止施行|失效))"
)
VALID_UNTIL_RE = re.compile(
    r"(?P<evidence>(?:有效期|施行期限)[^。；\n]{0,16}?(?:至|到)\s*"
    r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日)"
)
CANONICAL_ARTICLE_NO_RE = re.compile(r"^[1-9]\d*(?:-[1-9]\d*)?$")
AMENDMENT_TITLE_RE = re.compile(r"^(?:中华人民共和国)?(?:刑法|宪法|.+法)修正案(?:[（(].+[）)])?$")


@dataclass(slots=True)
class ParseResult:
    source_path: str
    document: LawDocumentVersion | None
    chunks: list[LawChunk]
    excluded_reason: str | None = None
    warnings: list[str] | None = None


@dataclass(frozen=True, slots=True)
class EffectiveDateResolution:
    value: date | None
    method: str | None
    evidence: str | None
    confidence: str
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveEndResolution:
    value: date | None
    method: str | None
    evidence: str | None
    confidence: str
    warning: str | None = None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    return re.sub(r"[《》\s　]", "", title).strip()


def normalize_number(value: str) -> str:
    if value.isdigit():
        return str(int(value))
    normalized = value.replace("〇", "零")
    return str(cn2an.cn2an(normalized, mode="smart"))


def normalize_article_no(base: str, suffix: str | None) -> str:
    base_no = normalize_number(base)
    return f"{base_no}-{normalize_number(suffix)}" if suffix else base_no


def _date_from_match(match: re.Match[str]) -> date | None:
    try:
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError:
        return None


def extract_filename_date(path: Path) -> date | None:
    match = FILENAME_DATE_RE.search(path.stem)
    return _date_from_match(match) if match else None


def article_sort_key(article_no: str) -> tuple[int, int]:
    base, separator, suffix = article_no.partition("-")
    return int(base), int(suffix) if separator else 0


class LawParser:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()

    def parse_all(self, files: Iterable[Path], workers: int = 8) -> list[ParseResult]:
        ordered = sorted(Path(path) for path in files)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(self.parse_file, ordered))

    def parse_file(self, path: Path) -> ParseResult:
        path = path.resolve()
        relative = path.relative_to(self.data_root).as_posix()
        raw = path.read_text(encoding="utf-8")
        header = INFO_END_RE.split(raw, maxsplit=1)[0]
        header_titles = [match.group(1).strip() for match in TITLE_RE.finditer(header)]
        title = header_titles[0] if header_titles else path.stem
        if title == "中华人民共和国民法典" and len(header_titles) > 1:
            title = f"{title}·{header_titles[1]}"
        doc_type, authority, excluded = self._classify(relative, title)
        if excluded:
            return ParseResult(relative, None, [], excluded_reason=excluded, warnings=[])

        raw_hash = sha256_text(raw)
        normalized = normalize_title(title)
        family_key = f"CN|{doc_type.value}|{normalized}"
        family_id = str(uuid.uuid5(uuid.NAMESPACE_URL, family_key))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{family_id}|{raw_hash}"))
        date_resolution = self._extract_effective_from(raw, path)
        if relative == "宪法/宪法修正案（2018年）.md":
            date_resolution = EffectiveDateResolution(
                date(2018, 3, 11),
                "known_document_special_case",
                "2018年3月11日 第十三届全国人民代表大会第一次会议通过",
                "high",
            )
        end_resolution = self._extract_effective_to(raw)
        document = LawDocumentVersion(
            law_family_id=family_id,
            law_version_id=version_id,
            title=title,
            normalized_title=normalized,
            document_type=doc_type,
            authority=authority,
            authority_level=self._authority_level(doc_type),
            effective_from=date_resolution.value,
            effective_from_method=date_resolution.method,
            effective_from_evidence=date_resolution.evidence,
            effective_from_confidence=date_resolution.confidence,
            effective_to=end_resolution.value,
            effective_to_method=end_resolution.method,
            effective_to_evidence=end_resolution.evidence,
            effective_to_confidence=end_resolution.confidence,
            source_path=relative,
            source_name="国家法律法规数据库",
            source_authority_level="official",
            content_hash=raw_hash,
        )

        parts = INFO_END_RE.split(raw, maxsplit=1)
        body = parts[1] if len(parts) == 2 else raw
        warnings: list[str] = []
        if date_resolution.warning:
            warnings.append(date_resolution.warning)
        if end_resolution.warning:
            warnings.append(end_resolution.warning)
        if document.effective_from and document.effective_to and document.effective_to <= document.effective_from:
            warnings.append("invalid_effective_interval")
        if len(parts) == 1:
            warnings.append("missing_info_end")

        if doc_type == DocumentType.AMENDMENT:
            raw_chunks = self._parse_numbered_items(body, "amendment_item")
            if not raw_chunks:
                raw_chunks = self._parse_articles(body)
                for item in raw_chunks:
                    item["chunk_type"] = "amendment_item"
            if not raw_chunks:
                raw_chunks = self._parse_sections(body)
                for item in raw_chunks:
                    item["chunk_type"] = "amendment_item"
        else:
            raw_chunks = self._parse_articles(body)
            warnings.extend(self._validate_article_chunks(raw_chunks))
            if not raw_chunks:
                raw_chunks = self._parse_sections(body)
                warnings.append("no_articles_used_sections")

        chunks = [self._build_chunk(document, item, index) for index, item in enumerate(raw_chunks, 1)]
        if not chunks:
            warnings.append("no_chunks")
        return ParseResult(relative, document, chunks, warnings=warnings)

    @staticmethod
    def _classify(relative: str, title: str) -> tuple[DocumentType, str | None, str | None]:
        top = relative.split("/", 1)[0]
        if top == "案例":
            return DocumentType.NON_NORMATIVE, None, "case_article"
        if top == "其他":
            return DocumentType.NON_NORMATIVE, None, "non_normative_other"
        if top == "刑法" and AMENDMENT_TITLE_RE.fullmatch(title.strip()):
            return DocumentType.AMENDMENT, "全国人民代表大会或其常务委员会", "criminal_law_amendment_not_indexed"
        if AMENDMENT_TITLE_RE.fullmatch(title.strip()):
            return DocumentType.AMENDMENT, "全国人民代表大会或其常务委员会", None
        if top == "司法解释":
            return DocumentType.JUDICIAL_INTERPRETATION, "最高人民法院或最高人民检察院", None
        if top == "行政法规":
            return DocumentType.ADMINISTRATIVE_REGULATION, "国务院", None
        if top == "部门规章":
            parts = relative.split("/")
            return DocumentType.DEPARTMENT_RULE, parts[1] if len(parts) > 2 else None, None
        if top in {"宪法", "宪法相关法", "刑法", "民法典", "民法商法", "社会法", "经济法", "行政法", "诉讼与非诉讼程序法"}:
            return DocumentType.LAW, "全国人民代表大会或其常务委员会", None
        return DocumentType.OTHER_NORMATIVE, None, None

    @staticmethod
    def _authority_level(doc_type: DocumentType) -> str | None:
        return {
            DocumentType.LAW: "law",
            DocumentType.AMENDMENT: "law",
            DocumentType.ADMINISTRATIVE_REGULATION: "administrative_regulation",
            DocumentType.JUDICIAL_INTERPRETATION: "judicial_interpretation",
            DocumentType.DEPARTMENT_RULE: "department_rule",
        }.get(doc_type)

    @staticmethod
    def _extract_effective_from(raw: str, path: Path) -> EffectiveDateResolution:
        filename_value = extract_filename_date(path)
        candidates: list[tuple[int, date, str]] = []
        for keyword in re.finditer("施行", raw):
            start = max(0, keyword.start() - 100)
            end = min(len(raw), keyword.end() + 100)
            window = raw[start:end]
            for match in ANY_DATE_RE.finditer(window):
                value = _date_from_match(match)
                if value:
                    absolute_start = start + match.start()
                    distance = abs(absolute_start - keyword.start())
                    candidates.append((distance, value, window.strip()))

        if candidates:
            _, text_value, evidence = min(candidates, key=lambda item: item[0])
            if filename_value and abs((filename_value - text_value).days) > 1096:
                return EffectiveDateResolution(
                    filename_value,
                    "filename_date_three_year_override",
                    f"{path.name}；正文施行邻近日期={text_value.isoformat()}",
                    "high",
                )
            return EffectiveDateResolution(text_value, "text_near_effective_keyword", evidence, "high")

        if filename_value:
            return EffectiveDateResolution(filename_value, "filename_date_fallback", path.name, "high")
        return EffectiveDateResolution(None, None, None, "unresolved")

    @staticmethod
    def _extract_effective_to(raw: str) -> EffectiveEndResolution:
        repeal_matches = list(REPEAL_FROM_RE.finditer(raw))
        if repeal_matches:
            match = repeal_matches[-1]
            value = _date_from_match(match)
            if value:
                return EffectiveEndResolution(value, "explicit_repeal_from", match["evidence"], "high")
            return EffectiveEndResolution(None, None, match["evidence"], "unresolved", "invalid_explicit_effective_to")
        until_matches = list(VALID_UNTIL_RE.finditer(raw))
        if until_matches:
            match = until_matches[-1]
            value = _date_from_match(match)
            if value:
                return EffectiveEndResolution(value + timedelta(days=1), "explicit_valid_through_inclusive", match["evidence"], "high")
            return EffectiveEndResolution(None, None, match["evidence"], "unresolved", "invalid_explicit_effective_to")
        return EffectiveEndResolution(None, None, None, "unresolved")

    @staticmethod
    def _validate_article_chunks(chunks: list[dict]) -> list[str]:
        article_numbers = [str(item.get("article_no") or "") for item in chunks]
        warnings: list[str] = []
        if any(not CANONICAL_ARTICLE_NO_RE.fullmatch(value) for value in article_numbers):
            warnings.append("invalid_article_no")
        if len(article_numbers) != len(set(article_numbers)):
            warnings.append("duplicate_article_no")
        if article_numbers:
            keys = [article_sort_key(value) for value in article_numbers if CANONICAL_ARTICLE_NO_RE.fullmatch(value)]
            if keys != sorted(keys):
                warnings.append("non_monotonic_article_no")
        return warnings

    @staticmethod
    def _parse_articles(body: str) -> list[dict]:
        chunks: list[dict] = []
        hierarchy: list[str] = []
        current: dict | None = None
        for raw_line in body.splitlines():
            line = raw_line.strip().replace("\u200b", "")
            if not line:
                continue
            heading = HEADING_RE.match(line)
            if heading and not ARTICLE_RE.match(line):
                level = len(heading.group(1)) - 2
                hierarchy = hierarchy[:level]
                hierarchy.append(heading.group(2).strip())
                continue
            article = ARTICLE_RE.match(line)
            if article:
                if current:
                    chunks.append(current)
                current = {
                    "chunk_type": "article",
                    "article_no": normalize_article_no(article["base"], article["suffix"]),
                    "structure_path": "/".join(hierarchy),
                    "lines": [line.lstrip("# ")],
                }
            elif current:
                current["lines"].append(line)
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _parse_numbered_items(body: str, chunk_type: str) -> list[dict]:
        chunks: list[dict] = []
        current: dict | None = None
        for raw_line in body.splitlines():
            line = raw_line.strip().replace("\u200b", "")
            if not line:
                continue
            match = NUMBERED_ITEM_RE.match(line)
            if match:
                if current:
                    chunks.append(current)
                current = {
                    "chunk_type": chunk_type,
                    "article_no": None,
                    "structure_path": match["label"],
                    "lines": [line],
                }
            elif current:
                current["lines"].append(line)
        if current:
            chunks.append(current)
        return chunks

    def _parse_sections(self, body: str, max_chars: int = 2400) -> list[dict]:
        numbered = self._parse_numbered_items(body, "section")
        if numbered:
            return numbered
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        chunks: list[dict] = []
        current: list[str] = []
        size = 0
        for paragraph in paragraphs:
            if current and size + len(paragraph) > max_chars:
                chunks.append({"chunk_type": "section", "article_no": None, "structure_path": "", "lines": current})
                current, size = [], 0
            current.append(paragraph)
            size += len(paragraph)
        if current:
            chunks.append({"chunk_type": "section", "article_no": None, "structure_path": "", "lines": current})
        return chunks

    @staticmethod
    def _build_chunk(document: LawDocumentVersion, item: dict, ordinal: int) -> LawChunk:
        content = "\n".join(item["lines"]).strip()
        content_hash = sha256_text(content)
        locator = item["article_no"] or str(ordinal)
        chunk_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{document.law_version_id}|{item['chunk_type']}|{locator}|{content_hash}",
            )
        )
        context = " / ".join(filter(None, [document.title, item["structure_path"]]))
        embedding_text = f"{context}\n{content}" if context else content
        return LawChunk(
            chunk_id=chunk_id,
            law_family_id=document.law_family_id,
            law_version_id=document.law_version_id,
            title=document.title,
            document_type=document.document_type,
            authority=document.authority,
            authority_level=document.authority_level,
            effective_from=document.effective_from,
            effective_from_method=document.effective_from_method,
            effective_from_confidence=document.effective_from_confidence,
            effective_to=document.effective_to,
            effective_to_method=document.effective_to_method,
            effective_to_confidence=document.effective_to_confidence,
            validity_status=document.validity_status,
            source_path=document.source_path,
            source_authority_level=document.source_authority_level,
            chunk_type=item["chunk_type"],
            article_no=item["article_no"],
            ordinal=ordinal,
            structure_path=item["structure_path"],
            content=content,
            embedding_text=embedding_text,
            content_hash=content_hash,
        )
