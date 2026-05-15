from fastapi import APIRouter
from .health import router as health_router
from .control import router as control_router
from .logs import router as logs_router

router = APIRouter()
router.include_router(health_router)
router.include_router(control_router)
router.include_router(logs_router)
