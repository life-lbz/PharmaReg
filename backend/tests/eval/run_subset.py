"""评估集实跑（SSE）：逐条 /qa/ask，按 kind 断言，留存 docs/eval_reports/。

口径（docs/eval_sets/README.md，开发方案 9.5 门禁）：
  hit     : 未触发 flag/error，且 citations 非空、回答命中 expect_terms 之一（≥90%）
  illusion: 触发 flag(needs_human_review) 或 error(5003)，unverified_claims 非空（目标 ≥90% 阻断）

用法：python tests/eval/run_subset.py [eval_set_file]
  默认 qa_subset_0_1.json；示例：python tests/eval/run_subset.py qa_full_200.json

前置：后端 127.0.0.1:8000（stub LLM + bge-m3 + bge-reranker-large）已启动；
运行：cd backend && python tests/eval/run_subset.py
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parents[3]
EVAL_SET_NAME = sys.argv[1] if len(sys.argv) > 1 else "qa_subset_0_1.json"
EVAL_SET = BASE / "docs" / "eval_sets" / EVAL_SET_NAME
REPORT_DIR = BASE / "docs" / "eval_reports"
API = "http://127.0.0.1:8000/api/v1"
LOGIN = {"username": "qa_user1", "password": "QaPass@123456"}


def run_case(h: dict, case: dict) -> dict:
    """每次请求独立连接，规避 uvicorn keep-alive 关闭导致的 ReadError"""
    events = []
    with httpx.Client(base_url=API, timeout=300, headers=h) as c:
        with c.stream("POST", "/qa/ask", json={"query": case["question"]}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except Exception:
                        pass

    answer = "".join(e.get("content", "") for e in events if e.get("type") == "delta")
    citations = next((e.get("citations", []) for e in events if e.get("type") == "citation"), [])
    flag = next((e for e in events if e.get("type") == "flag"), None)
    err = next((e for e in events if e.get("type") == "error"), None)
    done_conf = next((e.get("confidence") for e in events if e.get("type") == "done" and "confidence" in e), None)

    kind = case["kind"]
    if kind == "hit":
        blocked = bool(flag or err)
        terms = case.get("expect_terms", [])
        term_hit = next((t for t in terms if t in answer), None)
        passed = (not blocked) and bool(citations) and bool(term_hit) and len(answer) > 10
        detail = {"blocked": blocked, "term_hit": term_hit,
                  "citations": len(citations), "answer_len": len(answer)}
    else:  # illusion
        passed = bool(flag or (err and err.get("code") in ("5003", "5001")))
        unverified = (flag or {}).get("unverified_claims", []) or []
        detail = {"flag": bool(flag), "error_code": (err or {}).get("code"),
                  "confidence": (flag or {}).get("confidence", done_conf),
                  "unverified_count": len(unverified)}

    return {
        "id": case["id"],
        "kind": kind,
        "question": case["question"],
        "passed": passed,
        "detail": detail,
        "answer_head": answer[:80].replace("\n", " "),
    }


def main():
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    with httpx.Client(base_url=API, timeout=30) as c:
        login = c.post("/sys/auth/login", json=LOGIN)
        tok = login.json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}", "Accept": "text/event-stream"}

    results = []
    t0 = time.time()
    for case in cases:
        r = run_case(h, case)
        results.append(r)
        print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']:10s} {r['kind']:8s} {r['question'][:36]}")
        if not r["passed"]:
            print("        detail:", json.dumps(r["detail"], ensure_ascii=False))
        sys.stdout.flush()

    hits = [r for r in results if r["kind"] == "hit"]
    ills = [r for r in results if r["kind"] == "illusion"]
    hit_rate = (sum(r["passed"] for r in hits) / len(hits)) if hits else 1.0
    ill_block = (sum(r["passed"] for r in ills) / len(ills)) if ills else 1.0

    summary = {
        "schema": "pharmareg-eval-run",
        "eval_set": EVAL_SET_NAME,
        "prompt_version": "v1",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "llm_provider": "stub",
        "embed_model": "bge-m3",
        "rerank_model": "bge-reranker-large",
        "milvus": "2.4 standalone @19530",
        "total": len(results),
        "hit_total": len(hits), "hit_pass": sum(r["passed"] for r in hits),
        "hit_rate": round(hit_rate, 4),
        "illusion_total": len(ills), "illusion_blocked": sum(r["passed"] for r in ills),
        "illusion_block_rate": round(ill_block, 4),
        "elapsed_sec": round(time.time() - t0, 1),
        "gates": {
            "hit_rate_gte_90": hit_rate >= 0.9,
            "illusion_block_pct": ill_block >= 0.9,
        },
        "cases": results,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{Path(EVAL_SET_NAME).stem}_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n== 汇总 ==")
    print(f"hit 命中率: {summary['hit_pass']}/{summary['hit_total']} = {hit_rate:.1%} "
          f"(门禁≥90%: {'OK' if summary['gates']['hit_rate_gte_90'] else 'NG'})")
    print(f"illusion 阻断率: {summary['illusion_blocked']}/{summary['illusion_total']} = {ill_block:.1%} "
          f"(目标≥90%: {'OK' if summary['gates']['illusion_block_pct'] else 'NG'})")
    print(f"报告已留存: {out}")


if __name__ == "__main__":
    main()
