from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import UUIDBase


class AdminUser(UUIDBase):
    """Admin panel users — NOT telegram users."""

    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<AdminUser {self.username}>"
