from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    code: int = 5000
    http_status: int = 500
    message: str = "内部错误"

    def __init__(
        self,
        code: int | None = None,
        message: str | None = None,
        http_status: int | None = None,
        extra: dict[str, Any] | None = None,
    ):
        self.code = code or self.code
        self.message = message or self.message
        self.http_status = http_status or self.http_status
        self.extra = extra or {}


class AuthError(AppError):
    code = 1001
    http_status = 401
    message = "未认证或令牌失效"


class ForbiddenError(AppError):
    code = 1002
    http_status = 403
    message = "无权限"


class TenantError(AppError):
    code = 1003
    http_status = 409
    message = "越权访问其它租户数据"


class ValidationError(AppError):
    code = 2001
    http_status = 422
    message = "参数校验失败"


class NotFoundError(AppError):
    code = 3001
    http_status = 404
    message = "记录不存在"


class StateError(AppError):
    code = 3002
    http_status = 409
    message = "状态非法跃迁"


class SignatureError(AppError):
    code = 4001
    http_status = 409
    message = "电子签名口令错误或未设置"


class SignatureMeaningError(AppError):
    code = 4002
    http_status = 409
    message = "签名含义与动作不匹配"


class IdempotencyConflict(AppError):
    code = 4003
    http_status = 429
    message = "幂等键冲突"


class FourEyeError(AppError):
    code = 4101
    http_status = 409
    message = "四眼审批冲突"


class DeviationCloseError(AppError):
    code = 4102
    http_status = 409
    message = "偏差关闭前置不满足"


class VersionActivateError(AppError):
    code = 4103
    http_status = 409
    message = "版本激活前置不满足"


class AuditIntegrityError(AppError):
    code = 4201
    http_status = 409
    message = "审计记录校验失败"


class LLMError(AppError):
    code = 5001
    http_status = 502
    message = "LLM/模型服务调用失败"


class RetrievalError(AppError):
    code = 5002
    http_status = 504
    message = "检索超时或结果为空"


class HallucinationBlock(AppError):
    code = 5003
    http_status = 500
    message = "证据不足，回答中断"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "extra": exc.extra,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": 5000,
            "message": "服务器内部错误",
            "data": None,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
