from fastapi import APIRouter

from app.api.v1.audit_logs import router as audit_logs_router
from app.api.v1.kb import router as kb_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.qa import router as qa_router
from app.api.v1.quality import router as quality_router
from app.api.v1.sae_audit import router as sae_audit_router
from app.api.v1.sign import router as sign_router
from app.api.v1.sys import router as sys_router
from app.api.v1.training import router as training_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(sys_router)
api_router.include_router(users_router)
api_router.include_router(notifications_router)
api_router.include_router(sign_router)
api_router.include_router(audit_logs_router)
api_router.include_router(kb_router)
api_router.include_router(qa_router)
api_router.include_router(training_router)
api_router.include_router(quality_router)
api_router.include_router(sae_audit_router)


@api_router.get("/ping")
async def ping():
    return {"code": 0, "message": "ok", "data": {"ping": "pong"}}
