import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, StateError
from app.models.training import Certification, Exam, ExamRecord, Question


async def list_questions(db: AsyncSession, position_type: str | None = None, section_id: int | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(Question).where(Question.is_deleted == False, Question.tenant_id == tenant_id)
    if position_type:
        query = query.where(Question.position_type == position_type)
    if section_id:
        query = query.where(Question.section_id == section_id)
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.offset((page-1)*page_size).limit(page_size).order_by(Question.id.desc()))
    items = [
        {"id": q.id, "position_type": q.position_type, "section_id": q.section_id,
         "type": q.type, "stem": q.stem, "options": q.options, "difficulty": q.difficulty, "status": q.status}
        for q in result.scalars().all()
    ]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


async def create_question(db: AsyncSession, req, tenant_id: int = 1) -> Question:
    q = Question(position_type=req.position_type, section_id=req.section_id, type=req.type,
                 stem=req.stem, options=req.options, answer=req.answer, difficulty=req.difficulty,
                 status=req.status or "active", tenant_id=tenant_id)
    db.add(q)
    await db.flush()
    return q


async def update_question(db: AsyncSession, qid: int, req) -> Question:
    result = await db.execute(select(Question).where(Question.id == qid, Question.is_deleted == False))
    q = result.scalar_one_or_none()
    if not q:
        raise NotFoundError()
    if req.stem:
        q.stem = req.stem
    if req.options is not None:
        q.options = req.options
    if req.answer:
        q.answer = req.answer
    if req.difficulty:
        q.difficulty = req.difficulty
    if req.status:
        q.status = req.status
    await db.flush()
    return q


async def auto_generate_questions(db: AsyncSession, position_type: str, n: int = 20, tenant_id: int = 1) -> list[int]:
    result = await db.execute(
        select(Question).where(Question.position_type == position_type, Question.status == "active",
                               Question.is_deleted == False, Question.tenant_id == tenant_id)
    )
    pool = result.scalars().all()
    if len(pool) < n:
        return [q.id for q in pool]
    return [q.id for q in random.sample(pool, n)]


async def create_exam(db: AsyncSession, req, tenant_id: int = 1) -> Exam:
    question_ids = req.question_ids
    if not question_ids and req.assist:
        question_ids = await auto_generate_questions(db, req.position_type, 20, tenant_id)
    exam = Exam(title=req.title, position_type=req.position_type, scope=req.scope,
                pass_score=req.pass_score, question_ids={"ids": question_ids or []},
                start_at=req.start_at, end_at=req.end_at, status="published", tenant_id=tenant_id)
    db.add(exam)
    await db.flush()
    return exam


async def list_exams(db: AsyncSession, position_type: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(Exam).where(Exam.is_deleted == False, Exam.tenant_id == tenant_id)
    if position_type:
        query = query.where(Exam.position_type == position_type)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.offset((page-1)*page_size).limit(page_size).order_by(Exam.id.desc()))
    items = [{"id": e.id, "title": e.title, "position_type": e.position_type, "pass_score": e.pass_score,
              "status": e.status, "start_at": e.start_at, "end_at": e.end_at} for e in result.scalars().all()]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


async def get_exam(db: AsyncSession, exam_id: int) -> Exam:
    result = await db.execute(select(Exam).where(Exam.id == exam_id, Exam.is_deleted == False))
    exam = result.scalar_one_or_none()
    if not exam:
        raise NotFoundError()
    return exam


async def start_exam(db: AsyncSession, exam_id: int, employee_no: str, tenant_id: int = 1) -> dict[str, Any]:
    exam = await get_exam(db, exam_id)
    if exam.status != "published":
        raise StateError(message="考核未发布")
    question_ids = (exam.question_ids or {}).get("ids", [])
    result = await db.execute(select(Question).where(Question.id.in_(question_ids)))
    questions = result.scalars().all()
    record = ExamRecord(exam_id=exam_id, employee_no=employee_no, status="in_progress", tenant_id=tenant_id)
    db.add(record)
    await db.flush()
    return {"record_id": record.id, "questions": [
        {"id": q.id, "type": q.type, "stem": q.stem, "options": q.options} for q in questions
    ]}


async def submit_exam(db: AsyncSession, record_id: int, answers: dict[str, str], tenant_id: int = 1) -> dict[str, Any]:
    result = await db.execute(select(ExamRecord).where(ExamRecord.id == record_id, ExamRecord.is_deleted == False))
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError()
    if record.status != "in_progress":
        raise StateError(message="考核已提交")
    exam = await get_exam(db, record.exam_id)
    question_ids = (exam.question_ids or {}).get("ids", [])
    questions = (await db.execute(select(Question).where(Question.id.in_(question_ids)))).scalars().all()
    q_map = {str(q.id): q for q in questions}
    correct = 0
    for qid, ans in answers.items():
        q = q_map.get(qid)
        if q and ans.strip() == q.answer.strip():
            correct += 1
    total = len(questions) or 1
    score = round(correct / total * 100, 1)
    record.score = score
    record.answers = answers
    record.status = "passed" if score >= exam.pass_score else "failed"
    record.training_type = "initial"
    record.completed_at = func.now()
    await db.flush()
    return {"record_id": record.id, "score": score, "status": record.status, "passed": record.status == "passed"}


async def issue_certification(db: AsyncSession, req, tenant_id: int = 1) -> Certification:
    result = await db.execute(select(ExamRecord).where(ExamRecord.id == req.exam_record_id))
    record = result.scalar_one_or_none()
    if not record or record.status != "passed":
        raise StateError(message="考试未通过")
    cert = Certification(employee_no=req.employee_no, position_type=req.position_type,
                         exam_record_id=req.exam_record_id, issue_date=date.today(),
                         expire_date=date.today() + timedelta(days=365), status="valid", tenant_id=tenant_id)
    db.add(cert)
    await db.flush()
    return cert


async def get_cert_matrix(db: AsyncSession, department: str | None = None, tenant_id: int = 1) -> list[dict[str, Any]]:
    query = select(Certification).where(Certification.status == "valid", Certification.tenant_id == tenant_id)
    result = await db.execute(query)
    certs = result.scalars().all()
    matrix: dict[str, dict[str, Any]] = {}
    for c in certs:
        key = c.employee_no
        if key not in matrix:
            matrix[key] = {"employee_no": c.employee_no, "positions": []}
        matrix[key]["positions"].append({
            "position_type": c.position_type, "issue_date": c.issue_date.isoformat() if c.issue_date else None,
            "expire_date": c.expire_date.isoformat() if c.expire_date else None,
            "is_expiring_soon": c.expire_date and (c.expire_date - date.today()).days <= 30 if c.expire_date else False,
        })
    return list(matrix.values())


async def get_analytics(db: AsyncSession, tenant_id: int = 1) -> dict[str, Any]:
    total_certs = (await db.execute(select(func.count()).select_from(Certification).where(Certification.tenant_id == tenant_id, Certification.is_deleted == False))).scalar() or 0
    valid_certs = (await db.execute(select(func.count()).select_from(Certification).where(Certification.status == "valid", Certification.tenant_id == tenant_id))).scalar() or 0
    expiring = (await db.execute(select(func.count()).select_from(Certification).where(Certification.status == "valid", Certification.expire_date <= date.today() + timedelta(days=30), Certification.tenant_id == tenant_id))).scalar() or 0
    return {"total_certifications": total_certs, "valid_certifications": valid_certs,
            "expiring_soon": expiring, "cert_rate": round(valid_certs / total_certs * 100, 1) if total_certs else 0}
