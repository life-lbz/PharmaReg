from app.rag.retriever import classify_intent


class TestIntentClassification:
    def test_plain_question_is_qa(self):
        scenario, weights = classify_intent("纯化水检测频次依据哪一条？")
        assert scenario == "qa"
        assert weights["doc"] > weights["faq"]

    def test_faq_keyword(self):
        scenario, weights = classify_intent("洁净区消毒的标准口径是什么？")
        assert scenario == "faq_match"
        assert weights["faq"] > weights["doc"]

    def test_case_keyword(self):
        scenario, weights = classify_intent("有没有类似温度偏差的历史案例？")
        assert scenario == "deviation"
        assert weights["case"] > weights["doc"]
