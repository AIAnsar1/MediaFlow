from typing import TYPE_CHECKING
from enum import StrEnum
from sqlalchemy import String, Text, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.download import Download
    from models.user import TelegramUser


class BotStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class Bot(Base, TimestampMixin):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[BotStatus] = mapped_column(default=BotStatus.ACTIVE)
    is_webhook: Mapped[bool] = mapped_column(default=True)
    webhook_url: Mapped[str | None] = mapped_column(String(512))
    webhook_secret: Mapped[str | None] = mapped_column(String(64))

    # Stats (cached, updated periodically)
    total_users: Mapped[int] = mapped_column(default=0)
    active_users: Mapped[int] = mapped_column(default=0)  # Last 30 days
    total_downloads: Mapped[int] = mapped_column(default=0)

    # Relations
    users: Mapped[list["TelegramUser"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    downloads: Mapped[list["Download"]] = relationship(back_populates="bot")
