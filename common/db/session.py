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
