from fastapi import APIRouter, HTTPException, status, Depends
from common.schemas import LoginRequest, TokenResponse, RefreshRequest
from common.core import settings
from common.db import get_redis
from app.api.deps import get_current_user
from app.core.security import verify_password, hash_password, create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["auth"])

_admin_password_hash = hash_password(settings.ADMIN_PASSWORD)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    if body.username != settings.ADMIN_USERNAME or not verify_password(body.password, _admin_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(body.username)
    refresh_token = create_refresh_token(body.username)

    r = await get_redis()
    await r.set(f"refresh_token:{refresh_token}", body.username, ex=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    r = await get_redis()
    username = await r.get(f"refresh_token:{body.refresh_token}")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    await r.delete(f"refresh_token:{body.refresh_token}")

    new_access = create_access_token(username)
    new_refresh = create_refresh_token(username)
    await r.set(f"refresh_token:{new_refresh}", username, ex=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me")
async def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}
