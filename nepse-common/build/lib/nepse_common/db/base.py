from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared SQLAlchemy 2.0 declarative base for all ORM models."""
