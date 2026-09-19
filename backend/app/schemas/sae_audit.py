from typing import Any

from pydantic import BaseModel, Field


class CreateSaeRequest(BaseModel):
    subject_no: str | None = None
    ae_description: str = Field(..., min_length=1)
    seriousness: list[str] | None = None
    ai_assist: bool = False


class PvReviewRequest(BaseModel):
    seriousness: list[str]
    causality: str


class DraftSaeRequest(BaseModel):
    draft: dict[str, Any]


class SignSaeRequest(BaseModel):
    meaning: str = Field(..., min_length=1)
    signature_pin: str = Field(..., min_length=6)
    idempotency_key: str | None = None


class SubmitSaeRequest(BaseModel):
    meaning: str = Field(..., min_length=1)
    signature_pin: str = Field(..., min_length=6)
    idempotency_key: str | None = None


class CreateAuditCheckRequest(BaseModel):
    check_type: str = Field(..., description="gmp / gcp / iso")


class AddEvidenceRequest(BaseModel):
    item_id: str
    evidence_key: str
    description: str | None = None


class ConfirmGapsRequest(BaseModel):
    gaps: list[dict[str, Any]]


class RectifyRequest(BaseModel):
    item_id: str
    rectification: str


class ReportRequest(BaseModel):
    summary: str | None = None
