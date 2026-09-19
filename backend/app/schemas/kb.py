
from pydantic import BaseModel, Field


class CreateDocumentRequest(BaseModel):
    title: str = Field(..., max_length=512)
    doc_type: str = Field(..., description="regulation / sop / case / faq_source")
    regulation: str = Field(..., description="gmp / gcp / ich / iso / internal")
    version_label: str | None = None
    doc_no: str | None = None
    source_file: str | None = None
    doc_raw: str | None = Field(None, description="文档全文（入库解析用）")
    domain_id: int | None = None


class CreateVersionRequest(BaseModel):
    regulation: str
    version_label: str
    collection_prefix: str
    diff_source_version_id: int | None = None


class DiffReviewRequest(BaseModel):
    review_status: str = Field(..., description="confirmed / rejected")


class CreateFaqRequest(BaseModel):
    question: str
    answer: str
    kb_version_id: int | None = None
    clause_refs: list[int] | None = None


class InvalidateFaqRequest(BaseModel):
    superseded_by: int | None = None


class ActivateVersionRequest(BaseModel):
    signature_pin: str = Field(..., min_length=6)
    idempotency_key: str | None = None
    reason: str | None = None
