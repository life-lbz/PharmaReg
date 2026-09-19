from typing import Any

from pydantic import BaseModel, Field


class CreateQuestionRequest(BaseModel):
    position_type: str
    section_id: int | None = None
    type: str = Field(..., description="single / multi / judge")
    stem: str
    options: dict[str, Any] | None = None
    answer: str
    difficulty: int = Field(3, ge=1, le=5)
    status: str | None = None


class UpdateQuestionRequest(BaseModel):
    stem: str | None = None
    options: dict[str, Any] | None = None
    answer: str | None = None
    difficulty: int | None = Field(None, ge=1, le=5)
    status: str | None = None


class CreateExamRequest(BaseModel):
    title: str
    position_type: str
    scope: dict[str, Any] | None = None
    pass_score: float = 80.0
    question_ids: list[int] | None = None
    assist: bool = False
    start_at: str | None = None
    end_at: str | None = None


class StartExamResponse(BaseModel):
    record_id: int
    questions: list[dict[str, Any]]
    countdown_seconds: int | None = None


class SubmitExamRequest(BaseModel):
    answers: dict[str, str]


class CreateCertificationRequest(BaseModel):
    exam_record_id: int
    employee_no: str
    position_type: str
    expire_date: str | None = None
