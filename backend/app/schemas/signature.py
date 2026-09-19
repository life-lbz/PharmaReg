from pydantic import BaseModel, Field


class SignRequest(BaseModel):
    record_type: str = Field(..., description="记录类型")
    record_id: int = Field(..., description="记录ID")
    meaning: str = Field(..., description="签名含义声明")
    action_type: str = Field(..., description="签名动作类型")
    signature_pin: str = Field(..., min_length=6, description="签名口令")
    idempotency_key: str | None = Field(None, description="幂等键")


class SignResponse(BaseModel):
    id: int
    record_type: str
    record_id: int
    signer_id: int
    action_type: str
    signed_at: str | None = None
