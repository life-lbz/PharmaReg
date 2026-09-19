import pytest

from app.ingestion.chunker import chunk_clause
from app.ingestion.parser import cn_to_int, extract_sections_and_clauses, normalize_clause_no
from app.rag.hallucination import (
    compute_confidence,
    should_block,
)


class TestConfidence:
    def test_high_confidence_not_blocked(self):
        confidence = compute_confidence(0.9, 1.0, 1.0)
        assert confidence > 0.8
        assert should_block(confidence, False, 0.0) is False

    def test_low_confidence_blocked(self):
        confidence = compute_confidence(0.1, 0.0, 0.0)
        assert confidence < 0.6
        assert should_block(confidence, True, 0.5) is True

    def test_unverified_ratio_blocked(self):
        assert should_block(0.9, True, 0.4) is True
        assert should_block(0.9, False, 0.0) is False

    def test_weighted_formula(self):
        # 0.5*0.8 + 0.3*0.7 + 0.2*0.6 = 0.4+0.21+0.12 = 0.73
        assert compute_confidence(0.8, 0.7, 0.6) == pytest.approx(0.73)


class TestClauseNo:
    def test_normalize_digit(self):
        assert normalize_clause_no("第12条") == 12

    def test_normalize_cn(self):
        assert cn_to_int("三十一") == 31
        assert cn_to_int("十") == 10
        assert cn_to_int("一百零二") == 102
        assert normalize_clause_no("第三十五条") == 35

    def test_parse_clauses(self):
        text = """
第一章 总则
第一条 为保证药品质量，制定本规范。
第二条 本规范适用于药品生产全过程。
第二章 机构与人员
第三条 企业应当建立质量管理机构。
"""
        clauses = extract_sections_and_clauses(text)
        assert len(clauses) == 3
        assert clauses[0]["clause_no"] == "第一条"
        assert "药品质量" in clauses[0]["content"]


class TestChunker:
    def test_short_content_single_chunk(self):
        chunks = chunk_clause(1, "第一条 内容较短。", "第一条")
        assert len(chunks) == 1
        assert chunks[0]["clause_id"] == 1

    def test_long_content_split(self):
        long_text = "第一条 " + ("这是很长的条款内容，包含多个句子。" * 60)
        chunks = chunk_clause(1, long_text, "第一条")
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk["clause_id"] == 1
            assert chunk["clause_no"] == "第一条"
