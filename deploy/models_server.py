"""PharmaReg 本地推理服务（规格选型：Embedding=bge-m3, Rerank=bge-reranker-large）。

协议与 app/rag/embedder.py 期望一致：
  POST /embed  {input: [str], model}           -> {data: [{embedding: [float]}]}
  POST /rerank {query, documents, model, top_n} -> {results: [{index, relevance_score}]}

模型目录（实现规格 1.6/05 章本地化选型）：
  embed   : <repo>/models/bge-m3             （1024 维）
  rerank  : <repo>/models/bge-reranker-large （CrossEncoder 交叉编码器）
生成模型（LLM）不在本服务内：由 LLM_PROVIDER 配置指向本地合规服务或远程白名单 API。

启动示例：
  python deploy/models_server.py --port 8081
  python deploy/models_server.py --port 8081 --embed-model-dir <dir> --reranker-model-dir <dir>
"""
import argparse
import math
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="PharmaReg Local Inference (bge-m3 / bge-reranker-large)")

_REPO = Path(__file__).resolve().parents[1]
DEFAULT_EMBED_DIR = _REPO / "models" / "bge-m3"
DEFAULT_RERANK_DIR = _REPO / "models" / "bge-reranker-large"

_embed_model = None
_reranker = None


class EmbedRequest(BaseModel):
    input: list[str]
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model: str | None = None
    top_n: int = 8


def _lazy_embed(model_dir: Path):
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(str(model_dir), device="cpu")
    return _embed_model


def _lazy_reranker(model_dir: Path):
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(str(model_dir), device="cpu")
    return _reranker


def _embed(texts: list[str], model_dir: Path) -> list[list[float]]:
    model = _lazy_embed(model_dir)
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [e.tolist() for e in emb]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "embedding_model": "bge-m3",
        "dim": 1024,
        "rerank_model": "bge-reranker-large",
        "device": "cpu",
    }


@app.post("/embed")
def embed(req: EmbedRequest):
    vectors = _embed(req.input, EMBED_DIR)
    return {"data": [{"embedding": v} for v in vectors]}


@app.post("/rerank")
def rerank(req: RerankRequest):
    if not req.documents:
        return {"results": []}
    model = _lazy_reranker(RERANK_DIR)
    pairs = [[req.query, doc] for doc in req.documents]
    scores = model.predict(pairs)
    if scores.ndim == 2:
        scores = scores[:, 0]
    ranked = sorted(range(len(req.documents)), key=lambda i: float(scores[i]), reverse=True)[: req.top_n]
    return {
        "results": [
            {"index": i, "relevance_score": round(float(scores[i]), 6)} for i in ranked
        ],
        "provider": "bge-reranker-large",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--embed-model-dir", default=str(DEFAULT_EMBED_DIR))
    parser.add_argument("--reranker-model-dir", default=str(DEFAULT_RERANK_DIR))
    args = parser.parse_args()

    global EMBED_DIR, RERANK_DIR
    EMBED_DIR = Path(args.embed_model_dir)
    RERANK_DIR = Path(args.reranker_model_dir)

    import uvicorn

    print(f"[models_server] embed={EMBED_DIR} rerank={RERANK_DIR} port={args.port}")
    _lazy_embed(EMBED_DIR)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
