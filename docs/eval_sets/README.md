# 评估集目录说明
> 依据实现规格 10.1 测试分层"离线评估集"层建立。规格基线：200 条 GMP/GCP 高频条款 + 40 条场景 + 幻觉专项（当前 v1.0 已交付条款级命中 + 幻觉注入双维度 200 条）。

## 当前资产

| 文件 | 范围 | 状态 |
|---|---|---|
| `qa_subset_0_1.json` | 最小子集：13 命中(hit) + 3 幻觉(illusion) | ✅ 16/16 通过，报告见 `docs/eval_reports/qa_subset_0_1_run_20260903_124655.json` |
| `qa_full_200.json` | 全量 v1.0：GMP 88 + GCP 88 条款级命中(hit) + 24 幻觉注入(illusion) | ✅ 200/200 通过：命中 176/176、幻觉阻断 24/24（见 `docs/eval_reports/qa_full_200_run_20260903_162234.json`） |
| 场景集（40 场景） | 待扩充 | 未建 |

## 门禁（开发方案 9.5 口径）
- 命中率 ≥ 90%
- 准确率 ≥ 85%
- 幻觉率 ≤ 2%（= illusion 阻断率，目标阻断 100%）

## 用法
评估脚本 `backend/tests/eval/run_subset.py [eval_set_file]`（默认 `qa_subset_0_1.json`），逐条调用 `/qa/ask`（SSE），按 `kind` 断言：
- `hit`：返回 mode ∈ {faq, retrieval} 且 citations 非空、回答含 expect_terms 之一；
- `illusion`：返回 mode = needs_human_review 或触发 5003/5001 阻断，且 unverified_claims 非空。
评估结果留存至 `docs/eval_reports/`，作为 10.2 上线门禁证据。
