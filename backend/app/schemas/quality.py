from typing import Any

from pydantic import BaseModel, Field


class CreateDeviationRequest(BaseModel):
    title: str
    description: str
    occurred_at: str | None = None
    area: str | None = None
    category: str | None = None
    ai_classify: bool = False


class ClassifyRequest(BaseModel):
    severity: str | None = None
    classify_result: dict[str, Any] | None = None


class InvestigateRequest(BaseModel):
    investigation_plan: dict[str, Any]
    ai_suggest: bool = False


class SubmitReviewRequest(BaseModel):
    root_cause: str


class ReviewDeviationRequest(BaseModel):
    review_comment: str | None = None
    approve: bool = True
    signature_pin: str | None = Field(None, min_length=6)
    idempotency_key: str | None = None


class ReopenRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class CloseDeviationRequest(BaseModel):
    review_comment: str | None = None
    signature_pin: str | None = Field(None, min_length=6)
    idempotency_key: str | None = None


class CreateBatchHoldRequest(BaseModel):
    deviation_id: int
    batch_no: str
    product_name: str | None = None
    hold_reason: str | None = None


class ReleaseBatchHoldRequest(BaseModel):
    hold_id: int


class CreateChangeRequest(BaseModel):
    title: str
    change_type: str
    description: str
    ai_assess: bool = False


class AssessChangeRequest(BaseModel):
    impact_assessment: dict[str, Any]


class ApproveChangeRequest(BaseModel):
    approval_comment: str | None = None
    signature_pin: str | None = Field(None, min_length=6)
    idempotency_key: str | None = None


class ImplementChangeRequest(BaseModel):
    implementation_plan: dict[str, Any]


class VerifyChangeRequest(BaseModel):
    verification_result: dict[str, Any]


class CloseChangeRequest(BaseModel):
    comment: str | None = None


class CreateCapaRequest(BaseModel):
    source_type: str = Field(..., description="deviation / change / audit")
    source_id: int
    title: str
    root_cause: str | None = None


class UpdateCapaActionsRequest(BaseModel):
    actions: list[dict[str, Any]]


class VerifyCapaRequest(BaseModel):
    effectiveness_check: dict[str, Any]
    signature_pin: str | None = Field(None, min_length=6)
    idempotency_key: str | None = None
