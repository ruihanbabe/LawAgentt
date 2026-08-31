from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lawagent_ingestion.laws.models import DocumentType
from lawagent_ingestion.laws.parser import LawParser, normalize_article_no
from lawagent_ingestion.laws.pipeline import apply_family_version_dates, derive_version_intervals


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
        self.assertEqual(result.document.effective_from_method, "text_near_effective_keyword")
        self.assertEqual(result.document.effective_from_confidence, "high")

    def test_nearby_date_wins_when_within_three_years(self) -> None:
        path = self.write(
            "司法解释/示例规定(2015-12-24).md",
            "# 示例规定\n2015年12月16日讨论通过\n<!-- INFO END -->\n第一条 内容。\n第二条 本规定自发布之日起施行。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_from), "2015-12-16")
        self.assertEqual(result.document.effective_from_method, "text_near_effective_keyword")
        self.assertEqual(result.document.effective_from_confidence, "high")

    def test_near_effective_keyword_can_use_header_date(self) -> None:
        path = self.write(
            "司法解释/示例规定.md",
            "# 示例规定\n2009年2月28日发布\n<!-- INFO END -->\n第一条 内容。\n第二条 本规定自公布之日起施行。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_from), "2009-02-28")
        self.assertEqual(result.document.effective_from_method, "text_near_effective_keyword")
        self.assertEqual(result.document.effective_from_confidence, "high")

    def test_relative_date_without_anchor_remains_unresolved(self) -> None:
        path = self.write(
            "司法解释/无日期规定.md",
            "# 无日期规定\n<!-- INFO END -->\n第一条 内容。\n第二条 本规定自发布之日起施行。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertIsNone(result.document.effective_from)
        self.assertEqual(result.document.effective_from_confidence, "unresolved")

    def test_filename_overrides_effective_text_more_than_three_years_away(self) -> None:
        path = self.write(
            "行政法规/音像制品管理条例(2024-12-06).md",
            "# 音像制品管理条例\n<!-- INFO END -->\n第一条 内容。\n第二条 本条例自2002年2月1日起施行。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_from), "2024-12-06")
        self.assertEqual(result.document.effective_from_method, "filename_date_three_year_override")

    def test_explicit_repeal_date_is_exclusive_effective_to(self) -> None:
        path = self.write(
            "民法商法/旧规.md",
            "# 旧规\n<!-- INFO END -->\n第一条 内容。\n第二条 本规定自2024年7月1日起废止。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_to), "2024-07-01")
        self.assertEqual(result.document.effective_to_method, "explicit_repeal_from")
        self.assertEqual(result.document.effective_to_confidence, "high")

    def test_inclusive_valid_through_becomes_next_day_exclusive(self) -> None:
        path = self.write(
            "民法商法/暂行规定.md",
            "# 暂行规定\n<!-- INFO END -->\n第一条 内容。\n第二条 本规定有效期至2024年12月31日。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_to), "2025-01-01")
        self.assertEqual(result.document.effective_to_method, "explicit_valid_through_inclusive")

    def test_next_full_version_closes_previous_interval(self) -> None:
        old_path = self.write(
            "民法商法/示例法(2018-01-01).md",
            "# 示例法\n<!-- INFO END -->\n第一条 本法自2018年1月1日起施行。",
        )
        new_path = self.write(
            "民法商法/示例法(2024-01-01).md",
            "# 示例法\n<!-- INFO END -->\n第一条 本法自2024年1月1日起施行。",
        )
        parser = LawParser(self.root)
        old_result = parser.parse_file(old_path)
        new_result = parser.parse_file(new_path)
        apply_family_version_dates([old_result, new_result])
        derive_version_intervals([old_result, new_result])
        self.assertEqual(str(old_result.document.effective_to), "2024-01-01")
        self.assertEqual(old_result.document.effective_to_method, "next_full_version_effective_from")
        self.assertEqual(new_result.document.supersedes_version_id, old_result.document.law_version_id)
        self.assertEqual(old_result.chunks[0].effective_to, old_result.document.effective_to)

    def test_multi_version_family_always_uses_filename_dates(self) -> None:
        old_path = self.write(
            "社会法/未成年人保护法(2020-10-17).md",
            "# 未成年人保护法\n<!-- INFO END -->\n第一条 本法自2021年6月1日起施行。",
        )
        new_path = self.write(
            "社会法/未成年人保护法(2024-04-26).md",
            "# 未成年人保护法\n<!-- INFO END -->\n第一条 本法自2021年6月1日起施行。",
        )
        parser = LawParser(self.root)
        results = [parser.parse_file(old_path), parser.parse_file(new_path)]
        apply_family_version_dates(results)
        self.assertEqual([str(item.document.effective_from) for item in results], ["2020-10-17", "2024-04-26"])
        self.assertTrue(all(item.document.effective_from_method == "filename_date_family_version" for item in results))

    def test_duplicate_and_non_monotonic_article_numbers_are_reported(self) -> None:
        path = self.write(
            "民法商法/异常法.md",
            "# 异常法\n<!-- INFO END -->\n第二条 二。\n第一条 一。\n第一条 重复。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertIn("duplicate_article_no", result.warnings)
        self.assertIn("non_monotonic_article_no", result.warnings)

    def test_criminal_law_amendment_is_excluded(self) -> None:
        path = self.write(
            "刑法/刑法修正案（十二）.md",
            "# 中华人民共和国刑法修正案（十二）\n<!-- INFO END -->\n一、修改第一条。\n二、增加第二条。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertIsNone(result.document)
        self.assertEqual(result.excluded_reason, "criminal_law_amendment_not_indexed")

    def test_non_criminal_single_item_amendment_falls_back_to_section(self) -> None:
        path = self.write(
            "宪法/宪法修正案（二）.md",
            "# 中华人民共和国宪法修正案（二）\n<!-- INFO END -->\n将宪法第一条修改为：\n修改后的正文。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(result.document.document_type, DocumentType.AMENDMENT)
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].chunk_type, "amendment_item")

    def test_civil_code_uses_second_h1_as_complete_title(self) -> None:
        path = self.write(
            "民法典/合同编.md",
            "# 中华人民共和国民法典\n\n# 合同编\n\n2021年1月1日 施行\n<!-- INFO END -->\n第一条 内容。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(result.document.title, "中华人民共和国民法典·合同编")
        self.assertEqual(result.document.normalized_title, "中华人民共和国民法典·合同编")

    def test_2018_constitutional_amendment_uses_known_date(self) -> None:
        path = self.write(
            "宪法/宪法修正案（2018年）.md",
            "# 中华人民共和国宪法修正案（2018年）\n\n2018年3月11日 第十三届全国人民代表大会第一次会议通过\n<!-- INFO END -->\n第一条 修改。",
        )
        result = LawParser(self.root).parse_file(path)
        self.assertEqual(str(result.document.effective_from), "2018-03-11")
        self.assertEqual(result.document.effective_from_method, "known_document_special_case")

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
