from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from common.db import engine, migrate
    from common.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent API", version="2.0.0", lifespan=lifespan)

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
