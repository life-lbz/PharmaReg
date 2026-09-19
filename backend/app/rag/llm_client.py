from collections.abc import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import LLMError


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            )
            if resp.status_code != 200:
                raise LLMError(message=f"LLM chat failed: {resp.status_code}")
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def chat_stream(self, messages: list[dict[str, str]], temperature: float = 0.3) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            ) as resp:
                if resp.status_code != 200:
                    raise LLMError(message=f"LLM stream failed: {resp.status_code}")
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        import json
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta


llm_client = LLMClient(settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL)
