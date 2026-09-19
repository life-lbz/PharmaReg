from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import LLMError


class Embedder:
    def __init__(self, base_url: str, model: str, dim: int = 1024):
        self.base_url = base_url
        self.model = model
        self.dim = dim

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/embed",
                json={"input": texts, "model": self.model},
            )
            if resp.status_code != 200:
                raise LLMError(message=f"Embedding failed: {resp.status_code}")
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def embed_single(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0] if result else []


class Reranker:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def rerank(self, query: str, documents: list[str], top_n: int = 8) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{self.base_url}/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "model": self.model,
                    "top_n": top_n,
                },
            )
            if resp.status_code != 200:
                raise LLMError(message=f"Rerank failed: {resp.status_code}")
            data = resp.json()
            return data.get("results", [])


embedder = Embedder(settings.EMBEDDING_BASE_URL, settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM)
reranker = Reranker(settings.RERANK_BASE_URL, settings.RERANK_MODEL)
