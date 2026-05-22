from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import settings


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _prepare_sqlite_path(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    sqlite_path = database_url.replace("sqlite:///", "", 1)
    if sqlite_path:
        parent = Path(sqlite_path).parent
        if str(parent) and str(parent) != ".":
            parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)
engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(settings.database_url),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
