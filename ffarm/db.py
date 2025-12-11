"""
Database utilities.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from .config import DEFAULT_DB_PATH

_engine = None


def get_engine(db_path: Path | None = None):
    global _engine
    if _engine is None:
        target_path = db_path or DEFAULT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{target_path}", echo=False, connect_args={"check_same_thread": False})
    # Always run create_all in case new tables were added since the engine was created.
    SQLModel.metadata.create_all(_engine)
    return _engine


@contextmanager
def session_scope():
    engine = get_engine()
    with Session(engine) as session:
        yield session
