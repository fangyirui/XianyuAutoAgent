from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])

_live_instance = None


def set_live_instance(instance):
    global _live_instance
    _live_instance = instance


@router.get("/status")
async def status():
    if not _live_instance:
        return {"connected": False, "status": "not_started"}
    return {
        "connected": _live_instance.is_connected,
        "manual_mode_conversations": list(_live_instance.manual_mode_conversations),
    }
