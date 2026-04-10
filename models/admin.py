from enum import StrEnum
from datetime import datetime
from sqlalchemy import Boolean, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from models.base import UUIDBase


class AdminRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MODERATOR = "moderator"


class AdminUser(UUIDBase):
    """Admin panel users — NOT telegram users."""

    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(String(20), default=AdminRole.ADMIN, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AdminUser {self.username} ({self.role})>"
