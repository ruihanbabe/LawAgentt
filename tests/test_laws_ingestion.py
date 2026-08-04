from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lawagent_ingestion.laws.models import DocumentType
from lawagent_ingestion.laws.parser import LawParser, normalize_article_no


class LawParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_compound_article_number_is_exact_single_field(self) -> None:
        path = self.write(
            "刑法/刑法.md",
            "# 中华人民共和国刑法\n<!-- INFO END -->\n第一百二十条 基础条。\n第一百二十条之一 独立新增条。\n",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual([chunk.article_no for chunk in result.chunks], ["120", "120-1"])
        self.assertIn("第一百二十条之一", result.chunks[1].content)

    def test_versions_do_not_overwrite(self) -> None:
        first = self.write("民法商法/公司法(2018-10-26).md", "# 中华人民共和国公司法\n<!-- INFO END -->\n第一条 旧。")
        second = self.write("民法商法/公司法(2023-12-29).md", "# 中华人民共和国公司法\n<!-- INFO END -->\n第一条 新。")
        parser = LawParser(self.root)
        old = parser.parse_file(first).document
        new = parser.parse_file(second).document
        self.assertEqual(old.law_family_id, new.law_family_id)
        self.assertNotEqual(old.law_version_id, new.law_version_id)

    def test_only_explicit_effective_date_is_used(self) -> None:
        path = self.write(
            "民法商法/示例法.md",
            "# 示例法\n2023年12月29日通过\n<!-- INFO END -->\n第一条 内容。\n第二条 本法自2024年7月1日起施行。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_from), "2024-07-01")

    def test_amendment_uses_numbered_items(self) -> None:
        path = self.write(
            "刑法/刑法修正案（十二）.md",
            "# 中华人民共和国刑法修正案（十二）\n<!-- INFO END -->\n一、修改第一条。\n二、增加第二条。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(result.document.document_type, DocumentType.AMENDMENT)
        self.assertEqual([chunk.chunk_type for chunk in result.chunks], ["amendment_item", "amendment_item"])

    def test_single_item_amendment_falls_back_to_section(self) -> None:
        path = self.write(
            "刑法/刑法修正案（二）.md",
            "# 中华人民共和国刑法修正案（二）\n<!-- INFO END -->\n为了惩治犯罪，将刑法第三百四十二条修改为：\n修改后的正文。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(result.document.document_type, DocumentType.AMENDMENT)
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].chunk_type, "amendment_item")

    def test_interpretation_about_amendment_is_not_an_amendment(self) -> None:
        path = self.write(
            "司法解释/关于刑法修正案时间效力的解释.md",
            "# 最高人民法院关于《中华人民共和国刑法修正案（八）》时间效力问题的解释\n<!-- INFO END -->\n第一条 解释正文。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(result.document.document_type, DocumentType.JUDICIAL_INTERPRETATION)
        self.assertEqual(result.chunks[0].chunk_type, "article")

    def test_non_normative_article_is_excluded(self) -> None:
        path = self.write("其他/劳动攻略.md", "# 劳动仲裁攻略\n<!-- INFO END -->\n经验文章")
        result = LawParser(self.root).parse_file(path)
        self.assertIsNone(result.document)
        self.assertEqual(result.excluded_reason, "non_normative_other")

    def test_normalize_arabic_and_chinese(self) -> None:
        self.assertEqual(normalize_article_no("120", "2"), "120-2")
        self.assertEqual(normalize_article_no("一百二十", "二"), "120-2")


if __name__ == "__main__":
    unittest.main()
