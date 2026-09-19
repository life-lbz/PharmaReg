from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseEnvelope(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginationMeta


def ok(data: Any = None) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def paginate(items: list, page: int, page_size: int, total: int) -> dict:
    return {
        "items": items,
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }
