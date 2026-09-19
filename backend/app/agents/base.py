from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    name: str = "base"
    description: str = ""
    tools: list[str] = []

    @abstractmethod
    async def run(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


