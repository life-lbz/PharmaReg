from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.common import ok
from app.schemas.training import (
    CreateCertificationRequest,
    CreateExamRequest,
    CreateQuestionRequest,
    SubmitExamRequest,
    UpdateQuestionRequest,
)
from app.services.training_service import (
    create_exam,
    create_question,
    get_analytics,
    get_cert_matrix,
    get_exam,
    issue_certification,
    list_exams,
    list_questions,
    start_exam,
    submit_exam,
    update_question,
)

router = APIRouter(prefix="/training", tags=["培训认证"])


@router.get("/questions")
async def get_questions(position_type: str | None = None, section_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(require_permission("training.manage")), db: AsyncSession = Depends(get_db)):
    return ok(await list_questions(db, position_type, section_id, page, page_size, user.tenant_id))


@router.post("/questions")
async def add_question(req: CreateQuestionRequest, request: Request, user: SysUser = Depends(require_permission("training.manage")), db: AsyncSession = Depends(get_db)):
    q = await create_question(db, req, user.tenant_id)
    await write_audit(db, event_type="training.question_create", action="create", actor_id=user.id, object_type="questions", object_id=q.id, ip=request.client.host if request else None, tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": q.id})


@router.put("/questions/{qid}")
async def edit_question(qid: int, req: UpdateQuestionRequest, user: SysUser = Depends(require_permission("training.manage")), db: AsyncSession = Depends(get_db)):
    q = await update_question(db, qid, req)
    await db.commit()
    return ok({"id": q.id})


@router.post("/exams")
async def create_exam_api(req: CreateExamRequest, request: Request, user: SysUser = Depends(require_permission("training.manage")), db: AsyncSession = Depends(get_db)):
    exam = await create_exam(db, req, user.tenant_id)
    await write_audit(db, event_type="training.exam_publish", action="publish", actor_id=user.id, object_type="exams", object_id=exam.id, ip=request.client.host if request else None, tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": exam.id, "title": exam.title, "status": exam.status})


@router.get("/exams")
async def get_exams(position_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return ok(await list_exams(db, position_type, page, page_size, user.tenant_id))


@router.get("/exams/{exam_id}")
async def get_exam_detail(exam_id: int, user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    exam = await get_exam(db, exam_id)
    return ok({"id": exam.id, "title": exam.title, "position_type": exam.position_type, "pass_score": exam.pass_score, "status": exam.status, "start_at": exam.start_at, "end_at": exam.end_at})


@router.post("/exams/{exam_id}/start")
async def start_exam_api(exam_id: int, user: SysUser = Depends(require_permission("training.take")), db: AsyncSession = Depends(get_db)):
    result = await start_exam(db, exam_id, user.employee_no, user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/exams/{exam_id}/submit")
async def submit_exam_api(exam_id: int, req: SubmitExamRequest, user: SysUser = Depends(require_permission("training.take")), db: AsyncSession = Depends(get_db)):
    result = (await db.execute(__import__('sqlalchemy').select(__import__('app.models.training', fromlist=['ExamRecord']).ExamRecord).where(__import__('app.models.training', fromlist=['ExamRecord']).ExamRecord.exam_id == exam_id, __import__('app.models.training', fromlist=['ExamRecord']).ExamRecord.employee_no == user.employee_no, __import__('app.models.training', fromlist=['ExamRecord']).ExamRecord.status == "in_progress"))).scalar_one_or_none()
    if not result:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(message="无进行中的考核记录")
    data = await submit_exam(db, result.id, req.answers, user.tenant_id)
    await db.commit()
    return ok(data)


@router.post("/certifications")
async def issue_cert(req: CreateCertificationRequest, request: Request, user: SysUser = Depends(require_permission("cert.issue")), db: AsyncSession = Depends(get_db)):
    cert = await issue_certification(db, req, user.tenant_id)
    await write_audit(db, event_type="cert.issue", action="issue", actor_id=user.id, object_type="certifications", object_id=cert.id, ip=request.client.host if request else None, tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": cert.id, "cert_no": f"CERT-{cert.id:06d}", "status": cert.status})


@router.get("/matrix")
async def cert_matrix(user: SysUser = Depends(require_permission("matrix.export")), db: AsyncSession = Depends(get_db)):
    return ok(await get_cert_matrix(db, None, user.tenant_id))


@router.get("/analytics")
async def training_analytics(user: SysUser = Depends(require_permission("training.manage")), db: AsyncSession = Depends(get_db)):
    return ok(await get_analytics(db, user.tenant_id))
