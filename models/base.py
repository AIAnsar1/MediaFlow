from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import MetaData, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):

    metadata = MetaData(naming_convention=convention)

    # Автоматическое имя таблицы из имени класса
    @declared_attr.directive
    def __tablename__(cls) -> str:
        # UserProfile -> user_profiles
        name = cls.__name__
        return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_") + "s"

    def to_dict(self) -> dict[str, Any]:
        """Конвертация в словарь"""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__}(id={pk})>"


class TimestampMixin:

    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(),server_default=func.now(),onupdate=func.now())


class SoftDeleteMixin:

    is_deleted: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)

class UUIDBase(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
