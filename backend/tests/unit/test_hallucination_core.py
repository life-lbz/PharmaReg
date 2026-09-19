"""幻觉校验纯函数单测：语句切分、置信度、阻断判定、stub 声明校验（无需 DB/模型）。"""
import pytest

from app.rag.hallucination import (
    CLAUSE_PATTERN,
    compute_confidence,
    should_block,
    split_sentences,
    verify_claims_stub,
)


class TestSplitSentences:
    def test_split_chinese_sentences(self):
        text = "第一句要求记录。第二句应当复核；第三句禁止省略！"
        parts = split_sentences(text)
        assert any("第一句要求记录" in p for p in parts)
        assert any("第二句应当复核" in p for p in parts)
        assert any("第三句禁止省略" in p for p in parts)

    def test_short_fragment_filtered(self):
        parts = split_sentences("好的。应当保存记录并归档。嗯。")
        assert len(parts) == 1


class TestConfidence:
    def test_compute_confidence_weights(self):
        # 0.5*rerank + 0.3*clause + 0.2*claim
        v = compute_confidence(0.8, 1.0, 0.5)
        assert v == pytest.approx(0.5 * 0.8 + 0.3 * 1.0 + 0.2 * 0.5)

    def test_rerank_capped_at_one(self):
        v = compute_confidence(1.5, 1.0, 1.0)
        assert v <= 1.0


class TestShouldBlock:
    def test_low_confidence_blocks(self):
        assert should_block(0.5, has_unverified=False, unverified_ratio=0.0) is True

    def test_high_unverified_ratio_blocks(self):
        assert should_block(0.9, has_unverified=True, unverified_ratio=0.5) is True

    def test_confident_pass(self):
        assert should_block(0.9, has_unverified=False, unverified_ratio=0.0) is False


class TestVerifyClaimsStub:
    CONTEXT = [
        {"text": "制药用水应当符合相应质量要求，纯化水系统应当按照验证确定的频次进行日常监测。"},
        {"text": "发生偏差时，质量部门应当对偏差调查和处理结果进行审核确认。"},
    ]

    def test_sentence_in_context_verified(self):
        sentences = ["纯化水系统应当按照验证确定的频次进行日常监测。"]
        r = await_verify(sentences)
        assert r["pass_rate"] == 1.0 and not r["unverified"]

    def test_no_basis_regulatory_sentence_unverified(self):
        # 含强约束词但上下文没有该句 -> 未验证
        sentences = ["洁净服必须每2小时更换一次。"]
        r = await_verify(sentences)
        assert r["unverified"] and r["pass_rate"] == 0.0

    def test_plain_sentence_auto_verified(self):
        # 无条款号且无强约束词 -> 视为通用衔接句
        sentences = ["以上内容供参考，如有疑问请联系法规事务。"]
        r = await_verify(sentences)
        assert r["pass_rate"] == 1.0

    def test_clause_pattern_matches(self):
        assert CLAUSE_PATTERN.search("依据第三十二条")
        assert CLAUSE_PATTERN.search("第3200条")


def await_verify(sentences):
    import asyncio

    return asyncio.run(verify_claims_stub(sentences, TestVerifyClaimsStub.CONTEXT))
