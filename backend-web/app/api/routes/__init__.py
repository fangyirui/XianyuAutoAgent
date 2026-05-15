from fastapi import APIRouter
from .auth import router as auth_router
from .config import router as config_router
from .logs import router as logs_router
from .websocket_proxy import router as ws_router
from .qrlogin import router as qrlogin_router
from .logs_runtime import router as logs_runtime_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(config_router)
router.include_router(logs_router)
router.include_router(ws_router)
router.include_router(qrlogin_router)
router.include_router(logs_runtime_router)
