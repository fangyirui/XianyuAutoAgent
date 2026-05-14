# XianyuAutoAgent 微服务架构重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor XianyuAutoAgent from a monolithic Python app into a microservices architecture with React frontend, FastAPI backend-web, FastAPI websocket service, MySQL, and Redis.

**Architecture:** Three Python services (backend-web on 8089, websocket on 8090) share a `common/` module for DB models and config. React frontend (Vite + Tailwind) communicates exclusively with backend-web. Docker Compose orchestrates all services including MySQL 8 and Redis 7.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (asyncmy), Redis (aioredis), React 18, TypeScript, Vite, Tailwind CSS, Zustand, Docker Compose

---

## File Structure

### common/ (shared Python module)
- `common/__init__.py` — package init
- `common/core/__init__.py` — package init
- `common/core/config.py` — Pydantic Settings (env-based config)
- `common/db/__init__.py` — package init
- `common/db/session.py` — async SQLAlchemy engine + session factory
- `common/db/redis_client.py` — Redis connection pool
- `common/models/__init__.py` — re-export all models
- `common/models/base.py` — SQLAlchemy declarative base
- `common/models/conversation.py` — Conversation ORM
- `common/models/message.py` — Message ORM
- `common/models/item_cache.py` — ItemCache ORM
- `common/models/system_config.py` — SystemConfig ORM
- `common/schemas/__init__.py` — package init
- `common/schemas/auth.py` — login/token Pydantic schemas
- `common/schemas/config.py` — config CRUD schemas
- `common/schemas/message.py` — message/conversation schemas
- `common/utils/__init__.py` — package init
- `common/utils/xianyu_utils.py` — migrated from existing utils/

### backend-web/
- `backend-web/main.py` — uvicorn entrypoint
- `backend-web/app/__init__.py` — create_app() factory
- `backend-web/app/api/__init__.py` — package init
- `backend-web/app/api/deps.py` — get_db, get_current_user dependencies
- `backend-web/app/api/routes/__init__.py` — router aggregation
- `backend-web/app/api/routes/auth.py` — login, refresh, init-admin
- `backend-web/app/api/routes/config.py` — prompts + env config CRUD
- `backend-web/app/api/routes/logs.py` — conversation/message queries
- `backend-web/app/api/routes/websocket_proxy.py` — proxy to websocket service
- `backend-web/app/core/__init__.py` — package init
- `backend-web/app/core/security.py` — JWT create/verify, password hashing
- `backend-web/requirements.txt`
- `backend-web/Dockerfile`

### websocket/
- `websocket/main.py` — uvicorn entrypoint
- `websocket/app/__init__.py` — create_app() factory
- `websocket/app/api/__init__.py` — package init
- `websocket/app/api/routes/__init__.py` — router aggregation
- `websocket/app/api/routes/health.py` — health check + status
- `websocket/app/api/routes/control.py` — manual mode toggle, reconnect trigger
- `websocket/app/core/__init__.py` — package init
- `websocket/app/services/__init__.py` — package init
- `websocket/app/services/xianyu/__init__.py` — package init
- `websocket/app/services/xianyu/apis.py` — async XianyuApis (migrated)
- `websocket/app/services/xianyu/connection.py` — WebSocket connection + heartbeat + token refresh
- `websocket/app/services/xianyu/message_handler.py` — message decrypt + dispatch
- `websocket/app/services/agent/__init__.py` — package init
- `websocket/app/services/agent/base.py` — BaseAgent (async)
- `websocket/app/services/agent/router.py` — IntentRouter
- `websocket/app/services/agent/classify.py` — ClassifyAgent
- `websocket/app/services/agent/price.py` — PriceAgent
- `websocket/app/services/agent/tech.py` — TechAgent
- `websocket/app/services/agent/default.py` — DefaultAgent
- `websocket/app/services/agent/bot.py` — XianyuReplyBot orchestrator
- `websocket/app/websocket/__init__.py` — package init
- `websocket/app/websocket/manager.py` — XianyuLive main loop (async)
- `websocket/prompts/` — prompt files (copied from existing)
- `websocket/requirements.txt`
- `websocket/Dockerfile`

### frontend/
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tailwind.config.js`
- `frontend/postcss.config.js`
- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json`
- `frontend/index.html`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/utils/request.ts` — Axios instance + JWT interceptor
- `frontend/src/store/authStore.ts` — Zustand auth state
- `frontend/src/api/auth.ts`
- `frontend/src/api/config.ts`
- `frontend/src/api/logs.ts`
- `frontend/src/pages/auth/LoginPage.tsx`
- `frontend/src/pages/dashboard/DashboardPage.tsx`
- `frontend/src/pages/settings/SettingsPage.tsx`
- `frontend/src/pages/logs/LogsPage.tsx`
- `frontend/src/components/layout/AppLayout.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/Dockerfile`
- `frontend/nginx.conf`

### Root
- `docker-compose.yml`
- `.env.example` (updated)
- `init.sql` — MySQL schema initialization

---

## Task 1: Project Scaffolding & Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example` (replace existing)
- Create: `init.sql`
- Create: `common/__init__.py`
- Create: `backend-web/main.py`
- Create: `websocket/main.py`
- Create: `frontend/package.json`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: "3.8"

services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-xianyu_root_123}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-xianyu}
      MYSQL_USER: ${MYSQL_USER:-xianyu}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-xianyu_pass_123}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - internal
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD:-xianyu_redis_123}
    ports:
      - "6379:6379"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-xianyu_redis_123}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend-web:
    build: ./backend-web
    ports:
      - "8089:8089"
    env_file: .env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./common:/app/common
    networks:
      - internal

  websocket:
    build: ./websocket
    ports:
      - "8090:8090"
    env_file: .env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./common:/app/common
      - ./websocket/prompts:/app/prompts
    networks:
      - internal

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend-web
    networks:
      - internal

networks:
  internal:

volumes:
  mysql_data:
```

- [ ] **Step 2: Create .env.example**

```env
# Database
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_USER=xianyu
MYSQL_PASSWORD=xianyu_pass_123
MYSQL_DATABASE=xianyu
MYSQL_ROOT_PASSWORD=xianyu_root_123

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=xianyu_redis_123
REDIS_DB=0

# JWT
JWT_SECRET_KEY=change-this-to-a-random-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080

# Admin (first-run setup)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

# LLM
API_KEY=your_api_key_here
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max

# Xianyu
COOKIES_STR=your_cookies_here

# WebSocket Config
HEARTBEAT_INTERVAL=15
HEARTBEAT_TIMEOUT=5
TOKEN_REFRESH_INTERVAL=3600
TOKEN_RETRY_INTERVAL=300
MANUAL_MODE_TIMEOUT=3600
MESSAGE_EXPIRE_TIME=300000
TOGGLE_KEYWORDS=。
SIMULATE_HUMAN_TYPING=false

# Service URLs (internal)
WEBSOCKET_SERVICE_URL=http://websocket:8090
BACKEND_WEB_URL=http://backend-web:8089

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 3: Create init.sql**

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(64) UNIQUE NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    item_id VARCHAR(64),
    manual_mode BOOLEAN DEFAULT FALSE,
    manual_mode_at DATETIME,
    bargain_count INT DEFAULT 0,
    last_intent VARCHAR(32),
    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW(),
    INDEX idx_user (user_id),
    INDEX idx_item (item_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT NOW(),
    INDEX idx_conv_time (conversation_id, created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) UNIQUE NOT NULL,
    title VARCHAR(256),
    price DECIMAL(10,2),
    description TEXT,
    raw_json JSON,
    fetched_at DATETIME DEFAULT NOW(),
    expired_at DATETIME
);

CREATE TABLE IF NOT EXISTS system_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(128) UNIQUE NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW()
);
```

- [ ] **Step 4: Create placeholder main files**

`common/__init__.py`:
```python
"""Shared module for XianyuAutoAgent microservices."""
```

`backend-web/main.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8089, reload=True)
```

`websocket/main.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8090, reload=True)
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example init.sql common/__init__.py backend-web/main.py websocket/main.py
git commit -m "feat: project scaffolding with docker-compose and service entrypoints"
```

---

## Task 2: Common Module — Config & Database

**Files:**
- Create: `common/core/__init__.py`
- Create: `common/core/config.py`
- Create: `common/db/__init__.py`
- Create: `common/db/session.py`
- Create: `common/db/redis_client.py`

- [ ] **Step 1: Create common/core/config.py**

```python
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # MySQL
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "xianyu"
    MYSQL_PASSWORD: str = "xianyu_pass_123"
    MYSQL_DATABASE: str = "xianyu"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "xianyu_redis_123"
    REDIS_DB: int = 0

    # JWT
    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080

    # Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # LLM
    API_KEY: str = ""
    MODEL_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    MODEL_NAME: str = "qwen-max"

    # Xianyu
    COOKIES_STR: str = ""

    # WebSocket
    HEARTBEAT_INTERVAL: int = 15
    HEARTBEAT_TIMEOUT: int = 5
    TOKEN_REFRESH_INTERVAL: int = 3600
    TOKEN_RETRY_INTERVAL: int = 300
    MANUAL_MODE_TIMEOUT: int = 3600
    MESSAGE_EXPIRE_TIME: int = 300000
    TOGGLE_KEYWORDS: str = "。"
    SIMULATE_HUMAN_TYPING: bool = False

    # Service URLs
    WEBSOCKET_SERVICE_URL: str = "http://localhost:8090"
    BACKEND_WEB_URL: str = "http://localhost:8089"

    # Logging
    LOG_LEVEL: str = "INFO"

    @property
    def MYSQL_URL(self) -> str:
        return f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

`common/core/__init__.py`:
```python
from .config import settings

__all__ = ["settings"]
```

- [ ] **Step 2: Create common/db/session.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from common.core.config import settings

engine = create_async_engine(
    settings.MYSQL_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

- [ ] **Step 3: Create common/db/redis_client.py**

```python
import redis.asyncio as aioredis
from common.core.config import settings

redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> aioredis.Redis:
    return redis_client
```

`common/db/__init__.py`:
```python
from .session import engine, AsyncSessionLocal, get_db
from .redis_client import redis_client, get_redis

__all__ = ["engine", "AsyncSessionLocal", "get_db", "redis_client", "get_redis"]
```

- [ ] **Step 4: Commit**

```bash
git add common/
git commit -m "feat: common module with config, async SQLAlchemy session, and Redis client"
```

---

## Task 3: Common Module — ORM Models

**Files:**
- Create: `common/models/base.py`
- Create: `common/models/conversation.py`
- Create: `common/models/message.py`
- Create: `common/models/item_cache.py`
- Create: `common/models/system_config.py`
- Create: `common/models/__init__.py`

- [ ] **Step 1: Create common/models/base.py**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Create common/models/conversation.py**

```python
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Integer, func
from .base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chat_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    item_id = Column(String(64), index=True)
    manual_mode = Column(Boolean, default=False)
    manual_mode_at = Column(DateTime, nullable=True)
    bargain_count = Column(Integer, default=0)
    last_intent = Column(String(32), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: Create common/models/message.py**

```python
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Enum, ForeignKey, func
from .base import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum("user", "assistant"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Create common/models/item_cache.py**

```python
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Numeric, JSON, func
from .base import Base


class ItemCache(Base):
    __tablename__ = "item_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False)
    title = Column(String(256), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    description = Column(Text, nullable=True)
    raw_json = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, server_default=func.now())
    expired_at = Column(DateTime, nullable=True)
```

- [ ] **Step 5: Create common/models/system_config.py**

```python
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from .base import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_name = Column(String(128), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 6: Create common/models/__init__.py**

```python
from .base import Base
from .conversation import Conversation
from .message import Message
from .item_cache import ItemCache
from .system_config import SystemConfig

__all__ = ["Base", "Conversation", "Message", "ItemCache", "SystemConfig"]
```

- [ ] **Step 7: Commit**

```bash
git add common/models/
git commit -m "feat: ORM models for conversations, messages, item cache, and system config"
```

---

## Task 4: Common Module — Schemas & Utils

**Files:**
- Create: `common/schemas/__init__.py`
- Create: `common/schemas/auth.py`
- Create: `common/schemas/config.py`
- Create: `common/schemas/message.py`
- Create: `common/utils/__init__.py`
- Create: `common/utils/xianyu_utils.py`

- [ ] **Step 1: Create common/schemas/auth.py**

```python
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
```

- [ ] **Step 2: Create common/schemas/config.py**

```python
from pydantic import BaseModel
from typing import Optional


class ConfigItem(BaseModel):
    key_name: str
    value: Optional[str] = None


class ConfigUpdate(BaseModel):
    value: str


class PromptUpdate(BaseModel):
    name: str
    content: str
```

- [ ] **Step 3: Create common/schemas/message.py**

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: int
    chat_id: str
    user_id: str
    item_id: Optional[str] = None
    manual_mode: bool
    bargain_count: int
    last_intent: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

`common/schemas/__init__.py`:
```python
from .auth import LoginRequest, TokenResponse, RefreshRequest
from .config import ConfigItem, ConfigUpdate, PromptUpdate
from .message import MessageOut, ConversationOut

__all__ = [
    "LoginRequest", "TokenResponse", "RefreshRequest",
    "ConfigItem", "ConfigUpdate", "PromptUpdate",
    "MessageOut", "ConversationOut",
]
```

- [ ] **Step 4: Create common/utils/xianyu_utils.py**

Copy the existing `utils/xianyu_utils.py` file as-is (it has no external dependencies beyond stdlib). No changes needed.

```bash
cp utils/xianyu_utils.py common/utils/xianyu_utils.py
```

`common/utils/__init__.py`:
```python
from .xianyu_utils import (
    trans_cookies,
    generate_mid,
    generate_uuid,
    generate_device_id,
    generate_sign,
    decrypt,
)

__all__ = [
    "trans_cookies", "generate_mid", "generate_uuid",
    "generate_device_id", "generate_sign", "decrypt",
]
```

- [ ] **Step 5: Commit**

```bash
git add common/schemas/ common/utils/
git commit -m "feat: Pydantic schemas and utility functions in common module"
```

---

## Task 5: Backend-Web — App Factory & Security

**Files:**
- Create: `backend-web/app/__init__.py`
- Create: `backend-web/app/api/__init__.py`
- Create: `backend-web/app/api/deps.py`
- Create: `backend-web/app/core/__init__.py`
- Create: `backend-web/app/core/security.py`
- Create: `backend-web/requirements.txt`

- [ ] **Step 1: Create backend-web/requirements.txt**

```
fastapi==0.115.0
uvicorn==0.30.6
pydantic-settings==2.2.1
sqlalchemy[asyncio]==2.0.29
asyncmy==0.2.9
redis==5.0.3
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-dotenv==1.0.1
aiohttp==3.9.3
loguru==0.7.3
```

- [ ] **Step 2: Create backend-web/app/core/security.py**

```python
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from common.core import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
```

`backend-web/app/core/__init__.py`:
```python
```

- [ ] **Step 3: Create backend-web/app/api/deps.py**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from common.db import get_db, get_redis
from backend_web.app.core.security import decode_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload["sub"]
```

`backend-web/app/api/__init__.py`:
```python
```

- [ ] **Step 4: Create backend-web/app/__init__.py (app factory)**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent API", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .api.routes import router
    app.include_router(router, prefix="/api")

    return app
```

- [ ] **Step 5: Commit**

```bash
git add backend-web/
git commit -m "feat: backend-web app factory, security module, and dependencies"
```

---

## Task 6: Backend-Web — Auth Routes

**Files:**
- Create: `backend-web/app/api/routes/__init__.py`
- Create: `backend-web/app/api/routes/auth.py`

- [ ] **Step 1: Create backend-web/app/api/routes/auth.py**

```python
from fastapi import APIRouter, HTTPException, status, Depends
from common.schemas import LoginRequest, TokenResponse, RefreshRequest
from common.core import settings
from common.db import get_redis
from ..deps import get_current_user
from ...core.security import verify_password, hash_password, create_access_token, create_refresh_token, decode_token
import redis.asyncio as aioredis

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

    # Rotate: delete old, issue new
    await r.delete(f"refresh_token:{body.refresh_token}")

    new_access = create_access_token(username)
    new_refresh = create_refresh_token(username)
    await r.set(f"refresh_token:{new_refresh}", username, ex=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me")
async def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}
```

- [ ] **Step 2: Create backend-web/app/api/routes/__init__.py**

```python
from fastapi import APIRouter
from .auth import router as auth_router

router = APIRouter()
router.include_router(auth_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend-web/app/api/routes/
git commit -m "feat: auth routes with JWT login, refresh, and token rotation"
```

---

## Task 7: Backend-Web — Config & Logs Routes

**Files:**
- Create: `backend-web/app/api/routes/config.py`
- Create: `backend-web/app/api/routes/logs.py`
- Modify: `backend-web/app/api/routes/__init__.py`

- [ ] **Step 1: Create backend-web/app/api/routes/config.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.db import get_db
from common.models import SystemConfig
from common.schemas import ConfigItem, ConfigUpdate, PromptUpdate
from ..deps import get_current_user
from pathlib import Path
from typing import List

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "websocket" / "prompts"


@router.get("/prompts", response_model=List[dict])
async def list_prompts():
    prompts = []
    if PROMPTS_DIR.exists():
        for f in sorted(PROMPTS_DIR.glob("*.txt")):
            prompts.append({"name": f.stem, "content": f.read_text(encoding="utf-8")})
    return prompts


@router.put("/prompts")
async def update_prompt(body: PromptUpdate):
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"{body.name}.txt"
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok"}


@router.get("/system", response_model=List[ConfigItem])
async def list_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig))
    rows = result.scalars().all()
    return [ConfigItem(key_name=r.key_name, value=r.value) for r in rows]


@router.put("/system/{key_name}")
async def update_config(key_name: str, body: ConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == key_name))
    row = result.scalar_one_or_none()
    if row:
        row.value = body.value
    else:
        db.add(SystemConfig(key_name=key_name, value=body.value))
    await db.commit()
    return {"status": "ok"}
```

- [ ] **Step 2: Create backend-web/app/api/routes/logs.py**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from common.db import get_db
from common.models import Conversation, Message
from common.schemas import ConversationOut, MessageOut
from ..deps import get_current_user
from typing import List

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(get_current_user)])


@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at)).offset(offset).limit(page_size)
    )
    return result.scalars().all()


@router.get("/conversations/{chat_id}/messages", response_model=List[MessageOut])
async def get_messages(chat_id: str, db: AsyncSession = Depends(get_db)):
    conv_result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return []
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    return result.scalars().all()


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    conv_count = await db.execute(select(func.count(Conversation.id)))
    msg_count = await db.execute(select(func.count(Message.id)))
    return {
        "total_conversations": conv_count.scalar(),
        "total_messages": msg_count.scalar(),
    }
```

- [ ] **Step 3: Update backend-web/app/api/routes/__init__.py**

```python
from fastapi import APIRouter
from .auth import router as auth_router
from .config import router as config_router
from .logs import router as logs_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(config_router)
router.include_router(logs_router)
```

- [ ] **Step 4: Commit**

```bash
git add backend-web/app/api/routes/
git commit -m "feat: config CRUD and conversation logs API routes"
```

---

## Task 8: Backend-Web — WebSocket Proxy & Dockerfile

**Files:**
- Create: `backend-web/app/api/routes/websocket_proxy.py`
- Create: `backend-web/Dockerfile`
- Modify: `backend-web/app/api/routes/__init__.py`

- [ ] **Step 1: Create backend-web/app/api/routes/websocket_proxy.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_current_user
from common.core import settings
import aiohttp

router = APIRouter(prefix="/ws", tags=["websocket"], dependencies=[Depends(get_current_user)])


async def _call_ws_service(method: str, path: str, json_body: dict = None) -> dict:
    url = f"{settings.WEBSOCKET_SERVICE_URL}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=json_body) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="WebSocket service error")
            return await resp.json()


@router.get("/status")
async def ws_status():
    return await _call_ws_service("GET", "/api/health/status")


@router.post("/reconnect")
async def ws_reconnect():
    return await _call_ws_service("POST", "/api/control/reconnect")


@router.post("/manual-mode/{chat_id}")
async def toggle_manual_mode(chat_id: str):
    return await _call_ws_service("POST", f"/api/control/manual-mode/{chat_id}")
```

- [ ] **Step 2: Update backend-web/app/api/routes/__init__.py**

```python
from fastapi import APIRouter
from .auth import router as auth_router
from .config import router as config_router
from .logs import router as logs_router
from .websocket_proxy import router as ws_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(config_router)
router.include_router(logs_router)
router.include_router(ws_router)
```

- [ ] **Step 3: Create backend-web/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8089"]
```

- [ ] **Step 4: Commit**

```bash
git add backend-web/
git commit -m "feat: websocket proxy routes and backend-web Dockerfile"
```

---

## Task 9: WebSocket Service — Agent Module

**Files:**
- Create: `websocket/app/services/agent/base.py`
- Create: `websocket/app/services/agent/router.py`
- Create: `websocket/app/services/agent/classify.py`
- Create: `websocket/app/services/agent/price.py`
- Create: `websocket/app/services/agent/tech.py`
- Create: `websocket/app/services/agent/default.py`
- Create: `websocket/app/services/agent/bot.py`
- Create: `websocket/app/services/agent/__init__.py`
- Create: `websocket/app/services/__init__.py`

- [ ] **Step 1: Create websocket/app/services/agent/base.py**

```python
import os
from typing import List, Dict
from openai import AsyncOpenAI
from common.core import settings


class BaseAgent:
    def __init__(self, client: AsyncOpenAI, system_prompt: str, safety_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter

    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        messages = self._build_messages(user_msg, item_desc, context)
        response = await self._call_llm(messages)
        return self.safety_filter(response)

    def _build_messages(self, user_msg: str, item_desc: str, context: str) -> List[Dict]:
        return [
            {"role": "system", "content": f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"},
            {"role": "user", "content": user_msg}
        ]

    async def _call_llm(self, messages: List[Dict], temperature: float = 0.4) -> str:
        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=500,
            top_p=0.8
        )
        return response.choices[0].message.content or ""
```

- [ ] **Step 2: Create websocket/app/services/agent/classify.py**

```python
from .base import BaseAgent


class ClassifyAgent(BaseAgent):
    async def generate(self, **kwargs) -> str:
        return await super().generate(**kwargs)
```

- [ ] **Step 3: Create websocket/app/services/agent/price.py**

```python
from typing import List, Dict
from .base import BaseAgent
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context)
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=dynamic_temp,
            max_tokens=500,
            top_p=0.8
        )
        return self.safety_filter(response.choices[0].message.content)

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
```

- [ ] **Step 4: Create websocket/app/services/agent/tech.py**

```python
from typing import List, Dict
from .base import BaseAgent
from common.core import settings


class TechAgent(BaseAgent):
    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        messages = self._build_messages(user_msg, item_desc, context)
        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
            top_p=0.8,
            extra_body={"enable_search": True}
        )
        return self.safety_filter(response.choices[0].message.content)
```

- [ ] **Step 5: Create websocket/app/services/agent/default.py**

```python
from .base import BaseAgent


class DefaultAgent(BaseAgent):
    async def _call_llm(self, messages, *args) -> str:
        return await super()._call_llm(messages, temperature=0.7)
```

- [ ] **Step 6: Create websocket/app/services/agent/router.py**

```python
import re


class IntentRouter:
    def __init__(self, classify_agent):
        self.rules = {
            "tech": {
                "keywords": ["参数", "规格", "型号", "连接", "对比"],
                "patterns": [r"和.+比"],
            },
            "price": {
                "keywords": ["便宜", "价", "砍价", "少点"],
                "patterns": [r"\d+元", r"能少\d+"],
            },
        }
        self.classify_agent = classify_agent

    async def detect(self, user_msg: str, item_desc: str, context: str) -> str:
        text_clean = re.sub(r"[^\w一-龥]", "", user_msg)

        if any(kw in text_clean for kw in self.rules["tech"]["keywords"]):
            return "tech"
        for pattern in self.rules["tech"]["patterns"]:
            if re.search(pattern, text_clean):
                return "tech"

        if any(kw in text_clean for kw in self.rules["price"]["keywords"]):
            return "price"
        for pattern in self.rules["price"]["patterns"]:
            if re.search(pattern, text_clean):
                return "price"

        return await self.classify_agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=context
        )
```

- [ ] **Step 7: Create websocket/app/services/agent/bot.py**

```python
import re
from typing import List, Dict
from pathlib import Path
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings
from .router import IntentRouter
from .classify import ClassifyAgent
from .price import PriceAgent
from .tech import TechAgent
from .default import DefaultAgent


class XianyuReplyBot:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.API_KEY,
            base_url=settings.MODEL_BASE_URL,
        )
        self._init_system_prompts()
        self._init_agents()
        self.router = IntentRouter(self.agents["classify"])
        self.last_intent = None

    def _init_agents(self):
        self.agents = {
            "classify": ClassifyAgent(self.client, self.classify_prompt, self._safe_filter),
            "price": PriceAgent(self.client, self.price_prompt, self._safe_filter),
            "tech": TechAgent(self.client, self.tech_prompt, self._safe_filter),
            "default": DefaultAgent(self.client, self.default_prompt, self._safe_filter),
        }

    def _init_system_prompts(self):
        prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"

        def load_prompt(name: str) -> str:
            target = prompt_dir / f"{name}.txt"
            if target.exists():
                return target.read_text(encoding="utf-8")
            fallback = prompt_dir / f"{name}_example.txt"
            return fallback.read_text(encoding="utf-8")

        self.classify_prompt = load_prompt("classify_prompt")
        self.price_prompt = load_prompt("price_prompt")
        self.tech_prompt = load_prompt("tech_prompt")
        self.default_prompt = load_prompt("default_prompt")
        logger.info("成功加载所有提示词")

    def _safe_filter(self, text: str) -> str:
        if not text:
            return "-"
        blocked = ["微信", "QQ", "支付宝", "银行卡", "线下"]
        return "[安全提醒]请通过平台沟通" if any(p in text for p in blocked) else text

    def format_history(self, context: List[Dict]) -> str:
        msgs = [m for m in context if m["role"] in ("user", "assistant")]
        return "\n".join(f"{m['role']}: {m['content']}" for m in msgs)

    async def generate_reply(self, user_msg: str, item_desc: str, context: List[Dict]) -> str:
        formatted_context = self.format_history(context)
        detected_intent = await self.router.detect(user_msg, item_desc, formatted_context)

        if detected_intent == "no_reply":
            self.last_intent = "no_reply"
            return "-"

        internal_intents = {"classify"}
        if detected_intent in self.agents and detected_intent not in internal_intents:
            agent = self.agents[detected_intent]
            self.last_intent = detected_intent
        else:
            agent = self.agents["default"]
            self.last_intent = "default"

        bargain_count = self._extract_bargain_count(context)
        return await agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=formatted_context, bargain_count=bargain_count
        )

    def _extract_bargain_count(self, context: List[Dict]) -> int:
        for msg in context:
            if msg["role"] == "system" and "议价次数" in msg["content"]:
                match = re.search(r"议价次数[:：]\s*(\d+)", msg["content"])
                if match:
                    return int(match.group(1))
        return 0

    def reload_prompts(self):
        self._init_system_prompts()
        self._init_agents()
        self.router = IntentRouter(self.agents["classify"])
```

`websocket/app/services/agent/__init__.py`:
```python
from .bot import XianyuReplyBot

__all__ = ["XianyuReplyBot"]
```

`websocket/app/services/__init__.py`:
```python
```

- [ ] **Step 8: Commit**

```bash
git add websocket/app/services/
git commit -m "feat: async Agent module with IntentRouter, all agents, and bot orchestrator"
```

---

## Task 10: WebSocket Service — Async Xianyu APIs

**Files:**
- Create: `websocket/app/services/xianyu/__init__.py`
- Create: `websocket/app/services/xianyu/apis.py`
- Create: `websocket/app/services/xianyu/token_manager.py`

- [ ] **Step 1: Create websocket/app/services/xianyu/apis.py**

Migrate `XianyuApis.py` from sync `requests` to async `aiohttp`:

```python
import time
import re
import aiohttp
from loguru import logger
from common.utils import generate_sign


class XianyuApis:
    def __init__(self, cookies_str: str):
        self.cookies_str = cookies_str
        self.cookies = self._parse_cookies(cookies_str)
        self._headers = {
            "accept": "application/json",
            "origin": "https://www.goofish.com",
            "referer": "https://www.goofish.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        }

    def _parse_cookies(self, cookies_str: str) -> dict:
        cookies = {}
        for item in cookies_str.split("; "):
            parts = item.split("=", 1)
            if len(parts) == 2:
                cookies[parts[0]] = parts[1]
        return cookies

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    async def get_token(self, device_id: str, retry_count: int = 0) -> dict | None:
        if retry_count >= 3:
            login_ok = await self.has_login()
            if login_ok:
                return await self.get_token(device_id, 0)
            logger.error("Cookie已失效")
            return None

        t = str(int(time.time()) * 1000)
        data_val = f'{{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"{device_id}"}}'
        token = self.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idlemessage.pc.login.token",
            "sessionOption": "AutoLoginOnly",
        }

        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(
                "https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/",
                params=params, data={"data": data_val}
            ) as resp:
                res = await resp.json()
                # Update cookies from response
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value

        if not isinstance(res, dict):
            return await self.get_token(device_id, retry_count + 1)

        ret_value = res.get("ret", [])
        if any("SUCCESS" in r for r in ret_value):
            logger.info("Token获取成功")
            return res

        error_msg = str(ret_value)
        if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
            logger.error(f"触发风控: {ret_value}")
            return None

        logger.warning(f"Token API调用失败: {ret_value}")
        return await self.get_token(device_id, retry_count + 1)

    async def has_login(self) -> bool:
        url = "https://passport.goofish.com/newlogin/hasLogin.do"
        data = {
            "hid": self.cookies.get("unb", ""),
            "ltl": "true", "appName": "xianyu", "appEntrance": "web",
            "fromSite": "77", "lang": "zh_CN",
        }
        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(url, params={"appName": "xianyu", "fromSite": "77"}, data=data) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value
        return res.get("content", {}).get("success", False)

    async def get_item_info(self, item_id: str, retry_count: int = 0) -> dict:
        if retry_count >= 3:
            return {"error": "获取商品信息失败"}

        t = str(int(time.time()) * 1000)
        data_val = f'{{"itemId":"{item_id}"}}'
        token = self.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idle.pc.detail",
            "sessionOption": "AutoLoginOnly",
        }

        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(
                "https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/",
                params=params, data={"data": data_val}
            ) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value

        if isinstance(res, dict):
            ret_value = res.get("ret", [])
            if any("SUCCESS" in r for r in ret_value):
                return res
        return await self.get_item_info(item_id, retry_count + 1)
```

- [ ] **Step 2: Create websocket/app/services/xianyu/token_manager.py**

```python
import time
import asyncio
from loguru import logger
from common.core import settings
from .apis import XianyuApis


class TokenManager:
    def __init__(self, apis: XianyuApis, device_id: str):
        self.apis = apis
        self.device_id = device_id
        self.current_token: str | None = None
        self.last_refresh_time: float = 0
        self.refresh_interval = settings.TOKEN_REFRESH_INTERVAL
        self.retry_interval = settings.TOKEN_RETRY_INTERVAL

    async def refresh(self) -> str | None:
        result = await self.apis.get_token(self.device_id)
        if result and "data" in result and "accessToken" in result["data"]:
            self.current_token = result["data"]["accessToken"]
            self.last_refresh_time = time.time()
            logger.info("Token刷新成功")
            return self.current_token
        logger.error("Token刷新失败")
        return None

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time >= self.refresh_interval
```

`websocket/app/services/xianyu/__init__.py`:
```python
from .apis import XianyuApis
from .token_manager import TokenManager

__all__ = ["XianyuApis", "TokenManager"]
```

- [ ] **Step 3: Commit**

```bash
git add websocket/app/services/xianyu/
git commit -m "feat: async XianyuApis and TokenManager"
```

---

## Task 11: WebSocket Service — Connection Manager (Main Loop)

**Files:**
- Create: `websocket/app/services/xianyu/connection.py`
- Create: `websocket/app/services/xianyu/message_handler.py`
- Create: `websocket/app/websocket/__init__.py`
- Create: `websocket/app/websocket/manager.py`

- [ ] **Step 1: Create websocket/app/services/xianyu/message_handler.py**

```python
import base64
import json
from loguru import logger
from common.utils import decrypt


def is_sync_package(data: dict) -> bool:
    try:
        return (
            "body" in data
            and "syncPushPackage" in data["body"]
            and "data" in data["body"]["syncPushPackage"]
            and len(data["body"]["syncPushPackage"]["data"]) > 0
        )
    except Exception:
        return False


def is_chat_message(message: dict) -> bool:
    try:
        return (
            isinstance(message, dict)
            and "1" in message
            and isinstance(message["1"], dict)
            and "10" in message["1"]
            and isinstance(message["1"]["10"], dict)
            and "reminderContent" in message["1"]["10"]
        )
    except Exception:
        return False


def is_typing_status(message: dict) -> bool:
    try:
        return (
            isinstance(message, dict)
            and "1" in message
            and isinstance(message["1"], list)
            and len(message["1"]) > 0
            and isinstance(message["1"][0], dict)
            and "1" in message["1"][0]
            and "@goofish" in message["1"][0].get("1", "")
        )
    except Exception:
        return False


def is_bracket_system_message(text: str) -> bool:
    if not text:
        return False
    clean = text.strip()
    return clean.startswith("[") and clean.endswith("]")


def decrypt_sync_data(sync_data: dict) -> dict | None:
    if "data" not in sync_data:
        return None
    data = sync_data["data"]
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        return None  # plain JSON means non-chat, skip
    except Exception:
        pass
    try:
        decrypted = decrypt(data)
        return json.loads(decrypted)
    except Exception as e:
        logger.error(f"消息解密失败: {e}")
        return None
```

- [ ] **Step 2: Create websocket/app/websocket/manager.py**

```python
import json
import time
import asyncio
import base64
import random
import websockets
from loguru import logger
from sqlalchemy import select
from common.core import settings
from common.db import AsyncSessionLocal
from common.models import Conversation, Message, ItemCache
from common.utils import generate_mid, generate_uuid, generate_device_id, trans_cookies
from ..services.xianyu import XianyuApis, TokenManager
from ..services.xianyu.message_handler import (
    is_sync_package, is_chat_message, is_typing_status,
    is_bracket_system_message, decrypt_sync_data,
)
from ..services.agent import XianyuReplyBot


class XianyuLive:
    def __init__(self):
        cookies_str = settings.COOKIES_STR
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.myid = self.cookies["unb"]
        self.device_id = generate_device_id(self.myid)

        self.apis = XianyuApis(cookies_str)
        self.token_mgr = TokenManager(self.apis, self.device_id)
        self.bot = XianyuReplyBot()

        self.ws = None
        self.heartbeat_interval = settings.HEARTBEAT_INTERVAL
        self.heartbeat_timeout = settings.HEARTBEAT_TIMEOUT
        self.last_heartbeat_time = 0.0
        self.last_heartbeat_response = 0.0
        self.connection_restart_flag = False

        self.manual_mode_conversations: set = set()
        self.manual_mode_timestamps: dict = {}
        self.manual_mode_timeout = settings.MANUAL_MODE_TIMEOUT
        self.message_expire_time = settings.MESSAGE_EXPIRE_TIME
        self.toggle_keywords = settings.TOGGLE_KEYWORDS
        self.simulate_human_typing = settings.SIMULATE_HUMAN_TYPING

    # --- Connection status (exposed to health API) ---
    @property
    def is_connected(self) -> bool:
        return self.ws is not None and self.ws.open

    # --- Manual mode ---
    def is_manual_mode(self, chat_id: str) -> bool:
        if chat_id not in self.manual_mode_conversations:
            return False
        if time.time() - self.manual_mode_timestamps.get(chat_id, 0) > self.manual_mode_timeout:
            self.manual_mode_conversations.discard(chat_id)
            self.manual_mode_timestamps.pop(chat_id, None)
            return False
        return True

    def toggle_manual_mode(self, chat_id: str) -> str:
        if self.is_manual_mode(chat_id):
            self.manual_mode_conversations.discard(chat_id)
            self.manual_mode_timestamps.pop(chat_id, None)
            return "auto"
        self.manual_mode_conversations.add(chat_id)
        self.manual_mode_timestamps[chat_id] = time.time()
        return "manual"

    # --- DB helpers ---
    async def _get_or_create_conversation(self, chat_id: str, user_id: str, item_id: str):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
            if not conv:
                conv = Conversation(chat_id=chat_id, user_id=user_id, item_id=item_id)
                db.add(conv)
                await db.commit()
                await db.refresh(conv)
            return conv

    async def _add_message(self, conversation_id: int, role: str, content: str):
        async with AsyncSessionLocal() as db:
            db.add(Message(conversation_id=conversation_id, role=role, content=content))
            await db.commit()

    async def _get_context(self, conversation_id: int, limit: int = 50) -> list:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
                .limit(limit)
            )
            return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def _get_item_cache(self, item_id: str) -> dict | None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row and row.raw_json:
                return row.raw_json
            return None

    async def _save_item_cache(self, item_id: str, data: dict):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row:
                row.raw_json = data
                row.title = data.get("title", "")
                row.price = float(data.get("soldPrice", 0))
            else:
                db.add(ItemCache(
                    item_id=item_id, raw_json=data,
                    title=data.get("title", ""),
                    price=float(data.get("soldPrice", 0)),
                    description=data.get("desc", ""),
                ))
            await db.commit()

    async def _increment_bargain(self, chat_id: str):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
            if conv:
                conv.bargain_count += 1
                await db.commit()

    # --- Message sending ---
    async def send_msg(self, ws, cid: str, toid: str, text: str):
        payload = {"contentType": 1, "text": {"text": text}}
        text_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {"contentType": 101, "custom": {"type": 1, "data": text_b64}},
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {"actualReceivers": [f"{toid}@goofish", f"{self.myid}@goofish"]},
            ],
        }
        await ws.send(json.dumps(msg))

    # --- Item description builder ---
    def build_item_description(self, item_info: dict) -> str:
        clean_skus = []
        for sku in item_info.get("skuList", []):
            specs = [p["valueText"] for p in sku.get("propertyList", []) if p.get("valueText")]
            clean_skus.append({
                "spec": " ".join(specs) or "默认规格",
                "price": round(float(sku.get("price", 0)) / 100, 2),
                "stock": sku.get("quantity", 0),
            })
        valid_prices = [s["price"] for s in clean_skus if s["price"] > 0]
        if valid_prices:
            mn, mx = min(valid_prices), max(valid_prices)
            price_display = f"¥{mn}" if mn == mx else f"¥{mn} - ¥{mx}"
        else:
            price_display = f"¥{round(float(item_info.get('soldPrice', 0)), 2)}"
        summary = {
            "title": item_info.get("title", ""),
            "desc": item_info.get("desc", ""),
            "price_range": price_display,
            "total_stock": item_info.get("quantity", 0),
            "sku_details": clean_skus,
        }
        return json.dumps(summary, ensure_ascii=False)

    # --- Main message handler ---
    async def handle_message(self, message_data: dict, ws):
        if not is_sync_package(message_data):
            return

        sync_data = message_data["body"]["syncPushPackage"]["data"][0]
        message = decrypt_sync_data(sync_data)
        if not message:
            return

        if is_typing_status(message) or not is_chat_message(message):
            return

        create_time = int(message["1"]["5"])
        if (time.time() * 1000 - create_time) > self.message_expire_time:
            return

        send_user_id = message["1"]["10"]["senderUserId"]
        send_message = message["1"]["10"]["reminderContent"]
        url_info = message["1"]["10"]["reminderUrl"]
        item_id = url_info.split("itemId=")[1].split("&")[0] if "itemId=" in url_info else None
        chat_id = message["1"]["2"].split("@")[0]

        if not item_id:
            return

        # Seller control commands
        if send_user_id == self.myid:
            if send_message.strip() in self.toggle_keywords:
                mode = self.toggle_manual_mode(chat_id)
                logger.info(f"{'🔴 已接管' if mode == 'manual' else '🟢 已恢复'} 会话 {chat_id}")
                return
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
            await self._add_message(conv.id, "assistant", send_message)
            return

        logger.info(f"用户消息 | 会话: {chat_id}, 商品: {item_id}, 内容: {send_message}")

        if self.is_manual_mode(chat_id):
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
            await self._add_message(conv.id, "user", send_message)
            return

        if is_bracket_system_message(send_message):
            return

        # Get item info
        item_info = await self._get_item_cache(item_id)
        if not item_info:
            api_result = await self.apis.get_item_info(item_id)
            if "data" in api_result and "itemDO" in api_result["data"]:
                item_info = api_result["data"]["itemDO"]
                await self._save_item_cache(item_id, item_info)
            else:
                return

        conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
        context = await self._get_context(conv.id)

        item_desc = f"当前商品的信息如下：{self.build_item_description(item_info)}"
        bot_reply = await self.bot.generate_reply(send_message, item_desc, context)

        if bot_reply == "-":
            return

        await self._add_message(conv.id, "user", send_message)

        if self.bot.last_intent == "price":
            await self._increment_bargain(chat_id)

        await self._add_message(conv.id, "assistant", bot_reply)
        logger.info(f"机器人回复: {bot_reply}")

        if self.simulate_human_typing:
            delay = min(random.uniform(0, 1) + len(bot_reply) * random.uniform(0.1, 0.3), 10.0)
            await asyncio.sleep(delay)

        await self.send_msg(ws, chat_id, send_user_id, bot_reply)

    # --- Heartbeat ---
    async def heartbeat_loop(self, ws):
        while True:
            if time.time() - self.last_heartbeat_time >= self.heartbeat_interval:
                await ws.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
                self.last_heartbeat_time = time.time()
            if (time.time() - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                logger.warning("心跳超时")
                break
            await asyncio.sleep(1)

    # --- Main loop ---
    async def run(self):
        while True:
            try:
                self.connection_restart_flag = False
                if self.token_mgr.needs_refresh():
                    await self.token_mgr.refresh()
                if not self.token_mgr.current_token:
                    logger.error("无法获取Token，等待重试...")
                    await asyncio.sleep(30)
                    continue

                headers = {
                    "Cookie": self.cookies_str,
                    "Host": "wss-goofish.dingtalk.com",
                    "Origin": "https://www.goofish.com",
                }
                async with websockets.connect("wss://wss-goofish.dingtalk.com/", extra_headers=headers) as ws:
                    self.ws = ws
                    # Register
                    reg_msg = {
                        "lwp": "/reg",
                        "headers": {
                            "cache-header": "app-key token ua wv",
                            "app-key": "444e9908a51d1cb236a27862abc769c9",
                            "token": self.token_mgr.current_token,
                            "ua": "Mozilla/5.0 DingTalk(2.1.5) DingWeb/2.1.5 IMPaaS",
                            "dt": "j", "wv": "im:3,au:3,sy:6", "sync": "0,0;0;0;",
                            "did": self.device_id, "mid": generate_mid(),
                        },
                    }
                    await ws.send(json.dumps(reg_msg))
                    await asyncio.sleep(1)
                    logger.info("连接注册完成")

                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()
                    hb_task = asyncio.create_task(self.heartbeat_loop(ws))

                    async for raw in ws:
                        if self.connection_restart_flag:
                            break
                        data = json.loads(raw)
                        # Heartbeat response
                        if data.get("code") == 200 and "mid" in data.get("headers", {}):
                            self.last_heartbeat_response = time.time()
                            continue
                        await self.handle_message(data, ws)

                    hb_task.cancel()

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接关闭")
            except Exception as e:
                logger.error(f"连接错误: {e}")
            finally:
                self.ws = None
                wait = 0 if self.connection_restart_flag else 5
                if wait:
                    await asyncio.sleep(wait)
```

`websocket/app/websocket/__init__.py`:
```python
from .manager import XianyuLive

__all__ = ["XianyuLive"]
```

- [ ] **Step 3: Commit**

```bash
git add websocket/app/services/xianyu/message_handler.py websocket/app/websocket/
git commit -m "feat: WebSocket connection manager with heartbeat, message handling, and DB persistence"
```

---

## Task 12: WebSocket Service — App Factory, Routes & Dockerfile

**Files:**
- Create: `websocket/app/__init__.py`
- Create: `websocket/app/api/__init__.py`
- Create: `websocket/app/api/routes/__init__.py`
- Create: `websocket/app/api/routes/health.py`
- Create: `websocket/app/api/routes/control.py`
- Create: `websocket/app/core/__init__.py`
- Create: `websocket/requirements.txt`
- Create: `websocket/Dockerfile`
- Copy: `websocket/prompts/` from existing `prompts/`

- [ ] **Step 1: Create websocket/app/api/routes/health.py**

```python
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
```

- [ ] **Step 2: Create websocket/app/api/routes/control.py**

```python
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


@router.post("/manual-mode/{chat_id}")
async def toggle_manual(chat_id: str):
    if not _live_instance:
        return {"error": "not_running"}
    mode = _live_instance.toggle_manual_mode(chat_id)
    return {"chat_id": chat_id, "mode": mode}
```

- [ ] **Step 3: Create websocket/app/api/routes/__init__.py and websocket/app/api/__init__.py**

`websocket/app/api/routes/__init__.py`:
```python
from fastapi import APIRouter
from .health import router as health_router
from .control import router as control_router

router = APIRouter()
router.include_router(health_router)
router.include_router(control_router)
```

`websocket/app/api/__init__.py`:
```python
```

`websocket/app/core/__init__.py`:
```python
```

- [ ] **Step 4: Create websocket/app/__init__.py (app factory)**

```python
import asyncio
from fastapi import FastAPI
from loguru import logger
from common.core import settings


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent WebSocket Service", version="2.0.0")

    from .api.routes import router
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    async def startup():
        if not settings.COOKIES_STR or not settings.API_KEY:
            logger.warning("配置不完整，WebSocket服务未启动")
            return
        from .websocket import XianyuLive
        from .api.routes.health import set_live_instance as set_health
        from .api.routes.control import set_live_instance as set_control

        live = XianyuLive()
        set_health(live)
        set_control(live)
        asyncio.create_task(live.run())
        logger.info("WebSocket服务已启动")

    return app
```

- [ ] **Step 5: Create websocket/requirements.txt**

```
fastapi==0.115.0
uvicorn==0.30.6
pydantic-settings==2.2.1
sqlalchemy[asyncio]==2.0.29
asyncmy==0.2.9
redis==5.0.3
openai==1.65.5
websockets==13.1
aiohttp==3.9.3
python-dotenv==1.0.1
loguru==0.7.3
```

- [ ] **Step 6: Create websocket/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
```

- [ ] **Step 7: Copy prompts**

```bash
cp -r prompts/ websocket/prompts/
```

- [ ] **Step 8: Commit**

```bash
git add websocket/
git commit -m "feat: websocket service with health/control routes, app factory, and Dockerfile"
```

---

## Task 13: Frontend — React Project Setup

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/utils/request.ts`
- Create: `frontend/src/store/authStore.ts`
- Create: `frontend/src/index.css`

- [ ] **Step 1: Create frontend/package.json**

```json
{
  "name": "xianyu-auto-agent-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "build": "tsc && vite build",
    "preview": "vite preview --host 0.0.0.0"
  },
  "dependencies": {
    "axios": "^1.6.5",
    "lucide-react": "^0.309.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.21.1",
    "zustand": "^4.4.7"
  },
  "devDependencies": {
    "@types/react": "^18.2.46",
    "@types/react-dom": "^18.2.18",
    "@vitejs/plugin-react": "^4.2.1",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.33",
    "tailwindcss": "^3.4.1",
    "typescript": "^5.3.3",
    "vite": "^5.0.10"
  }
}
```

- [ ] **Step 2: Create frontend/vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 9000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8089',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'static',
  },
})
```

- [ ] **Step 3: Create frontend/tailwind.config.js**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

`frontend/postcss.config.js`:
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 4: Create frontend/tsconfig.json and tsconfig.node.json**

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create frontend/index.html**

```html
<!DOCTYPE html>
<html lang="zh">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>XianyuAutoAgent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create frontend/src/index.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-gray-900 text-gray-100;
}
```

- [ ] **Step 7: Create frontend/src/utils/request.ts**

```typescript
import axios from 'axios'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(request(originalRequest))
          })
        })
      }
      originalRequest._retry = true
      isRefreshing = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) throw new Error('No refresh token')

        const { data } = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)

        pendingRequests.forEach((cb) => cb(data.access_token))
        pendingRequests = []

        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return request(originalRequest)
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        window.location.href = '/login'
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }
    return Promise.reject(error)
  }
)

export default request
```

- [ ] **Step 8: Create frontend/src/store/authStore.ts**

```typescript
import { create } from 'zustand'

interface AuthState {
  isAuthenticated: boolean
  username: string | null
  login: (accessToken: string, refreshToken: string, username: string) => void
  logout: () => void
  checkAuth: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!localStorage.getItem('access_token'),
  username: null,
  login: (accessToken, refreshToken, username) => {
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('refresh_token', refreshToken)
    set({ isAuthenticated: true, username })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ isAuthenticated: false, username: null })
  },
  checkAuth: () => {
    set({ isAuthenticated: !!localStorage.getItem('access_token') })
  },
}))
```

- [ ] **Step 9: Create frontend/src/main.tsx and App.tsx**

`frontend/src/main.tsx`:
```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```

`frontend/src/App.tsx`:
```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import LoginPage from '@/pages/auth/LoginPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import SettingsPage from '@/pages/settings/SettingsPage'
import LogsPage from '@/pages/logs/LogsPage'
import AppLayout from '@/components/layout/AppLayout'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<PrivateRoute><AppLayout /></PrivateRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="logs" element={<LogsPage />} />
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "feat: React frontend project setup with Vite, Tailwind, auth store, and routing"
```

---

## Task 14: Frontend — Pages & Components

**Files:**
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/config.ts`
- Create: `frontend/src/api/logs.ts`
- Create: `frontend/src/components/layout/AppLayout.tsx`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/pages/auth/LoginPage.tsx`
- Create: `frontend/src/pages/dashboard/DashboardPage.tsx`
- Create: `frontend/src/pages/settings/SettingsPage.tsx`
- Create: `frontend/src/pages/logs/LogsPage.tsx`

- [ ] **Step 1: Create frontend/src/api/auth.ts**

```typescript
import request from '@/utils/request'

export async function login(username: string, password: string) {
  const { data } = await request.post('/auth/login', { username, password })
  return data
}

export async function getMe() {
  const { data } = await request.get('/auth/me')
  return data
}
```

- [ ] **Step 2: Create frontend/src/api/config.ts**

```typescript
import request from '@/utils/request'

export async function getPrompts() {
  const { data } = await request.get('/config/prompts')
  return data
}

export async function updatePrompt(name: string, content: string) {
  const { data } = await request.put('/config/prompts', { name, content })
  return data
}

export async function getWsStatus() {
  const { data } = await request.get('/ws/status')
  return data
}

export async function reconnectWs() {
  const { data } = await request.post('/ws/reconnect')
  return data
}
```

- [ ] **Step 3: Create frontend/src/api/logs.ts**

```typescript
import request from '@/utils/request'

export async function getConversations(page = 1, pageSize = 20) {
  const { data } = await request.get('/logs/conversations', { params: { page, page_size: pageSize } })
  return data
}

export async function getMessages(chatId: string) {
  const { data } = await request.get(`/logs/conversations/${chatId}/messages`)
  return data
}

export async function getStats() {
  const { data } = await request.get('/logs/stats')
  return data
}
```

- [ ] **Step 4: Create frontend/src/components/layout/Sidebar.tsx**

```tsx
import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Settings, MessageSquare, LogOut } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '仪表盘' },
  { to: '/logs', icon: MessageSquare, label: '对话日志' },
  { to: '/settings', icon: Settings, label: '设置' },
]

export default function Sidebar() {
  const logout = useAuthStore((s) => s.logout)

  return (
    <aside className="w-56 bg-gray-800 border-r border-gray-700 flex flex-col">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-semibold text-emerald-400">XianyuAutoAgent</h1>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm ${
                isActive ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <button
        onClick={logout}
        className="flex items-center gap-3 px-5 py-3 text-sm text-gray-400 hover:text-red-400 border-t border-gray-700"
      >
        <LogOut size={18} />
        退出登录
      </button>
    </aside>
  )
}
```

- [ ] **Step 5: Create frontend/src/components/layout/AppLayout.tsx**

```tsx
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function AppLayout() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
```

- [ ] **Step 6: Create frontend/src/pages/auth/LoginPage.tsx**

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { login } from '@/api/auth'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const authLogin = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const data = await login(username, password)
      authLogin(data.access_token, data.refresh_token, username)
      navigate('/')
    } catch {
      setError('用户名或密码错误')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={handleSubmit} className="bg-gray-800 p-8 rounded-xl border border-gray-700 w-80 space-y-4">
        <h2 className="text-center text-lg font-semibold text-emerald-400">XianyuAutoAgent</h2>
        <input
          type="text" placeholder="用户名" value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-emerald-400"
        />
        <input
          type="password" placeholder="密码" value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-emerald-400"
        />
        {error && <p className="text-red-400 text-xs text-center">{error}</p>}
        <button
          type="submit" disabled={loading}
          className="w-full py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50"
        >
          {loading ? '登录中...' : '登录'}
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 7: Create frontend/src/pages/dashboard/DashboardPage.tsx**

```tsx
import { useEffect, useState } from 'react'
import { getStats } from '@/api/logs'
import { getWsStatus, reconnectWs } from '@/api/config'

export default function DashboardPage() {
  const [stats, setStats] = useState({ total_conversations: 0, total_messages: 0 })
  const [wsStatus, setWsStatus] = useState<{ connected: boolean }>({ connected: false })

  useEffect(() => {
    getStats().then(setStats).catch(() => {})
    getWsStatus().then(setWsStatus).catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">仪表盘</h2>
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">连接状态</p>
          <p className={`text-lg font-semibold ${wsStatus.connected ? 'text-emerald-400' : 'text-red-400'}`}>
            {wsStatus.connected ? '已连接' : '未连接'}
          </p>
          {!wsStatus.connected && (
            <button onClick={() => reconnectWs()} className="mt-2 text-xs text-emerald-400 hover:underline">
              重新连接
            </button>
          )}
        </div>
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">总会话数</p>
          <p className="text-lg font-semibold">{stats.total_conversations}</p>
        </div>
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">总消息数</p>
          <p className="text-lg font-semibold">{stats.total_messages}</p>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Create frontend/src/pages/settings/SettingsPage.tsx**

```tsx
import { useEffect, useState } from 'react'
import { getPrompts, updatePrompt } from '@/api/config'

interface Prompt {
  name: string
  content: string
}

export default function SettingsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [selected, setSelected] = useState<Prompt | null>(null)
  const [editing, setEditing] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getPrompts().then((data) => {
      setPrompts(data)
      if (data.length > 0) {
        setSelected(data[0])
        setEditing(data[0].content)
      }
    })
  }, [])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    await updatePrompt(selected.name, editing)
    setPrompts((prev) => prev.map((p) => (p.name === selected.name ? { ...p, content: editing } : p)))
    setSaving(false)
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">提示词配置</h2>
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        <div className="w-48 space-y-1">
          {prompts.map((p) => (
            <button
              key={p.name}
              onClick={() => { setSelected(p); setEditing(p.content) }}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm ${
                selected?.name === p.name ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'
              }`}
            >
              {p.name}
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col">
          <textarea
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:border-emerald-400"
          />
          <button
            onClick={handleSave} disabled={saving}
            className="mt-3 self-end px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 9: Create frontend/src/pages/logs/LogsPage.tsx**

```tsx
import { useEffect, useState } from 'react'
import { getConversations, getMessages } from '@/api/logs'

interface Conversation {
  id: number
  chat_id: string
  user_id: string
  item_id: string | null
  bargain_count: number
  updated_at: string
}

interface Message {
  id: number
  role: string
  content: string
  created_at: string
}

export default function LogsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedChat, setSelectedChat] = useState<string | null>(null)

  useEffect(() => {
    getConversations().then(setConversations)
  }, [])

  const selectConversation = async (chatId: string) => {
    setSelectedChat(chatId)
    const msgs = await getMessages(chatId)
    setMessages(msgs)
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">对话日志</h2>
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        <div className="w-72 overflow-auto space-y-1 border-r border-gray-700 pr-4">
          {conversations.map((c) => (
            <button
              key={c.chat_id}
              onClick={() => selectConversation(c.chat_id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm ${
                selectedChat === c.chat_id ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'
              }`}
            >
              <p className="truncate">{c.chat_id}</p>
              <p className="text-xs text-gray-500">{c.updated_at}</p>
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto space-y-3">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === 'assistant' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[70%] px-3 py-2 rounded-lg text-sm ${
                m.role === 'assistant' ? 'bg-emerald-900/50 text-emerald-100' : 'bg-gray-700 text-gray-200'
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {!selectedChat && <p className="text-gray-500 text-sm">选择一个会话查看消息</p>}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 10: Commit**

```bash
git add frontend/src/
git commit -m "feat: frontend pages - login, dashboard, settings, and logs"
```

---

## Task 15: Frontend Dockerfile + Nginx & Final Integration

**Files:**
- Create: `frontend/nginx.conf`
- Create: `frontend/Dockerfile`

- [ ] **Step 1: Create frontend/nginx.conf**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api {
        proxy_pass http://backend-web:8089;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Create frontend/Dockerfile**

```dockerfile
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 3: Verify docker-compose builds**

```bash
docker-compose build
```

Expected: all 3 service images build successfully.

- [ ] **Step 4: Start services and verify**

```bash
docker-compose up -d
```

Verify:
- `curl http://localhost:8089/docs` — backend-web Swagger UI
- `curl http://localhost:8090/api/health/status` — websocket health
- `curl http://localhost:80` — frontend loads

- [ ] **Step 5: Commit**

```bash
git add frontend/nginx.conf frontend/Dockerfile
git commit -m "feat: frontend Dockerfile with Nginx reverse proxy"
```

---

## Task 16: Cleanup & Final Commit

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Update .gitignore**

Add entries for the new structure:

```
# Python
__pycache__/
*.pyc
.env
venv/
data/

# Frontend
frontend/node_modules/
frontend/dist/

# Docker
mysql_data/

# IDE
.idea/
```

- [ ] **Step 2: Final integration test**

```bash
docker-compose up -d
# Wait for services to be healthy
docker-compose ps
# Test login
curl -X POST http://localhost:8089/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}'
# Should return access_token and refresh_token
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: update .gitignore for microservices structure"
```

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Project scaffolding + docker-compose |
| 2 | Common: config + DB session |
| 3 | Common: ORM models |
| 4 | Common: schemas + utils |
| 5 | Backend-web: app factory + security |
| 6 | Backend-web: auth routes |
| 7 | Backend-web: config + logs routes |
| 8 | Backend-web: WS proxy + Dockerfile |
| 9 | WebSocket: agent module (async) |
| 10 | WebSocket: async Xianyu APIs |
| 11 | WebSocket: connection manager (main loop) |
| 12 | WebSocket: app factory + routes + Dockerfile |
| 13 | Frontend: project setup |
| 14 | Frontend: pages + components |
| 15 | Frontend: Dockerfile + Nginx |
| 16 | Cleanup + integration test |


