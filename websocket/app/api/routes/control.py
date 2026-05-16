from fastapi import APIRouter

router = APIRouter(prefix="/control", tags=["control"])

_live_instance = None


def set_live_instance(instance):
    global _live_instance
    _live_instance = instance


@router.post("/reconnect")
async def reconnect():
    if _live_instance:
        _live_instance.connection_restart_flag = True
        if _live_instance.ws:
            await _live_instance.ws.close()
        return {"status": "reconnecting"}
    return {"status": "not_running"}


@router.post("/reload")
async def reload():
    from ... import _reload
    await _reload()
    return {"status": "reloaded"}


@router.post("/manual-mode/{chat_id}")
async def toggle_manual(chat_id: str):
    if not _live_instance:
        return {"error": "not_running"}
    mode = _live_instance.toggle_manual_mode(chat_id)
    return {"chat_id": chat_id, "mode": mode}


@router.post("/sync-items")
async def sync_items():
    if not _live_instance:
        return {"error": "not_running"}
    saved = await _live_instance.sync_my_items()
    return {"status": "ok", "saved": saved, "seller_id": str(_live_instance.myid)}
