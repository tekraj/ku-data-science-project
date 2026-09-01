from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from nepse_common.config import DatabaseConfig


def _build_url(db_config: DatabaseConfig) -> str:
    return (
        f"postgresql+psycopg2://{db_config.user}:{db_config.password}"
        f"@{db_config.host}:{db_config.port}/{db_config.dbname}"
    )


def get_engine(db_config: DatabaseConfig) -> Engine:
    return create_engine(_build_url(db_config))


def get_sessionmaker(db_config: DatabaseConfig) -> sessionmaker[Session]:
    engine = get_engine(db_config)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(db_config: DatabaseConfig) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session_factory = get_sessionmaker(db_config)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
