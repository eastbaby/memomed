from sqlalchemy.ext.asyncio import async_sessionmaker

from langchain_postgres import PGEngine

from app.settings import settings


pg_engine = PGEngine.from_connection_string(settings.POSTGRES_URI_CUSTOM)
async_engine = pg_engine._pool
AsyncSessionLocal = async_sessionmaker(bind=async_engine, expire_on_commit=False)
